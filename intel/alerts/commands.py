"""Telegram commands: ask the engine about its book from the phone.

/positions  open T+1 positions, marked at the pool's last swap
/closed     the last closed positions (multiple, result, why)
/pnl        the day and the whole book: closed, winners, realised, open exposure, real orders
/orders     the last orders the executor journalled (sent, failed, refused)
/solde      the signer wallet's ETH balance on chain
/pause      stop opening new T+1 positions (sales continue)
/resume     open positions again
/help

Reads the bot's updates by long polling. Telegram allows ONE reader per bot token, and the older
bot in ``tangier_watcher`` already reads the alerts bot, so commands use a second bot of their own
(``INTEL_TELEGRAM_COMMANDS_TOKEN``). Answers go only to the configured chat; anyone else writing
to the bot is ignored. The update offset is kept in ``sync_cursors`` so a restart never replays
an old command.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx

from intel.context import IntelContext
from intel.utils.timeutil import now_ts

log = logging.getLogger(__name__)
CURSOR = "telegram_commands_offset"
PAUSE_FLAG = "t1_paused"
NL = chr(10)
# The book runs on two chains now. Each has its own model version, its own wallet and its own rule,
# so every command names which one it is talking about rather than blending them into one figure.
BOOKS = (("Robinhood", "t1-%", "ETH"), ("Solana", "sol-t1-%", "SOL"))


def t1_paused(ctx: IntelContext) -> bool:
    return bool(ctx.db.cursor_get(PAUSE_FLAG) or 0)


class TelegramCommands:
    def __init__(self, ctx: IntelContext, sender: Any, t1: Any = None) -> None:
        self.ctx = ctx
        self.sender = sender
        self.t1 = t1
        # either name: the operator wrote the second bot's token as TELEGRAM_BOT_TOKEN_BIS
        self.token = (os.environ.get("INTEL_TELEGRAM_COMMANDS_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN_BIS") or "").strip() or None
        if self.token and self.token == (ctx.settings.telegram_bot_token or ""):
            log.warning("commandes Telegram: le token BIS est le meme que le bot d alertes, deja lu par tangier_watcher (409 garanti)")
        self.chat_id = str(ctx.settings.telegram_chat_id or "")
        self._client = httpx.AsyncClient(timeout=40)
        self._sol_prices: dict[str, float] = {}
        self._sol_liq: dict[str, float] = {}
        self._warned = False

    @property
    def configured(self) -> bool:
        return bool(self.token and self.chat_id)

    # ------------------------------------------------------------------ cycle
    async def run_cycle(self) -> dict[str, Any]:
        if not self.configured:
            if not self._warned:
                log.warning("commandes Telegram inactives : ni INTEL_TELEGRAM_COMMANDS_TOKEN ni TELEGRAM_BOT_TOKEN_BIS (second bot, voir commands.py)")
                self._warned = True
            return {"status": "disabled"}
        offset = int(self.ctx.db.cursor_get(CURSOR) or 0)
        try:
            resp = await self._client.get(f"https://api.telegram.org/bot{self.token}/getUpdates",
                                          params={"offset": offset, "timeout": 20, "allowed_updates": '["message"]'})
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "error": str(exc)[:120]}
        if not data.get("ok"):
            desc = str(data.get("description"))[:120]
            if data.get("error_code") == 409:
                desc = "un autre programme lit deja ce bot (409) : il faut un token de bot dedie"
            log.warning("telegram getUpdates: %s", desc)
            return {"status": "error", "error": desc}
        answered = 0
        for upd in data.get("result") or []:
            offset = max(offset, int(upd["update_id"]) + 1)
            msg = upd.get("message") or {}
            chat = str((msg.get("chat") or {}).get("id") or "")
            text = str(msg.get("text") or "").strip()
            if chat != self.chat_id or not text.startswith("/"):
                continue
            try:
                reply = await self.handle(text)
            except Exception as exc:  # noqa: BLE001
                log.exception("commande %s: %s", text, exc)
                reply = f"erreur en traitant {text}: {str(exc)[:120]}"
            await self._reply(reply)
            answered += 1
        self.ctx.db.cursor_set(CURSOR, offset, now_ts())
        return {"status": "ok", "answered": answered}

    async def _reply(self, text: str) -> None:
        """Answer from the command bot itself, so the reply lands in the chat the question was typed in."""
        if len(text) > 4096:
            text = text[:4080] + "\n…(tronqué)"
        for html in (True, False):
            params = {"chat_id": self.chat_id, "text": text, "disable_web_page_preview": "true"}
            if html:
                params["parse_mode"] = "HTML"
            try:
                resp = await self._client.post(f"https://api.telegram.org/bot{self.token}/sendMessage", data=params)
                if resp.json().get("ok"):
                    return
            except Exception as exc:  # noqa: BLE001
                log.info("reponse telegram (html=%s) refusee: %s", html, str(exc)[:80])
            text = text.replace("<b>", "").replace("</b>", "").replace("&amp;", "&")
        await self.sender.send(text)                     # last resort: the alerts bot

    # --------------------------------------------------------------- commands
    async def handle(self, text: str) -> str:
        cmd, _, arg = text.partition(" ")
        cmd = cmd.split("@")[0].lower()
        n = int(arg) if arg.strip().isdigit() else 5
        if cmd in ("/positions", "/pos"):
            return await self.positions()
        if cmd == "/closed":
            return self.closed(n)
        if cmd == "/pnl":
            return await self.pnl(full=arg.strip().lower() in ("all", "tout", "total"))
        if cmd in ("/orders", "/ordres"):
            return self.orders(n)
        if cmd in ("/solde", "/balance"):
            return await self.balance()
        if cmd == "/pause":
            self.ctx.db.cursor_set(PAUSE_FLAG, 1, now_ts())
            return "achats T+1 en pause. Les ventes continuent. /resume pour reprendre."
        if cmd == "/resume":
            self.ctx.db.cursor_set(PAUSE_FLAG, 0, now_ts())
            return "achats T+1 repris."
        if cmd == "/restart":
            self.ctx.db.cursor_set("engine_restart_request", 1, now_ts())
            return "redémarrage du moteur dans quelques secondes (code et config du disque). /help pour vérifier ensuite."
        rh = "réel" if self.ctx.config.get("execution.mode", "dry_run") == "live" else "à blanc"
        so = "réel" if self.ctx.config.get("solana.mode", "dry_run") == "live" else "à blanc"
        return NL.join([
            "<b>Commandes</b>", "",
            "<code>/pnl       </code> resultat, par chaine",
            "<code>/positions </code> ce qui est ouvert",
            "<code>/closed    </code> dernieres fermetures",
            "<code>/orders    </code> ordres partis en chaine",
            "<code>/solde     </code> les deux portefeuilles",
            "<code>/pause     </code> arreter d acheter (Robinhood)",
            "<code>/resume    </code> reprendre les achats",
            "<code>/restart   </code> redemarrer le moteur",
            "", "<i>/pnl all pour le cumul · /closed 20 pour plus de lignes</i>",
            "", f"Robinhood {rh} · Solana {so}"
            + (" · achats Robinhood en pause" if t1_paused(self.ctx) else ""),
        ])

    def _mark(self, p: Any) -> float | None:
        """The token's price now, from whichever chain the line lives on. None only when unknown."""
        notes = dict(kv.split(":", 1) for kv in (p["notes"] or "").split() if ":" in kv)
        if str(p["model_version"] or "").startswith("sol-"):
            return self._sol_prices.get(p["token_address"])
        if self.t1 is None:
            return None
        return self.t1._mark(notes.get("pool"), p["token_address"], notes.get("quote"))

    async def _load_sol_prices(self, mints: list[str]) -> None:
        """Price the Solana lines in one request, so an open position shows a figure and not a
        question mark: a book that cannot say what a position is worth is not a book."""
        self._sol_prices = {}
        mints = [m for m in dict.fromkeys(mints) if m]
        if not mints:
            return
        try:
            import httpx
            async with httpx.AsyncClient() as c:
                for i in range(0, len(mints), 25):
                    r = await c.get("https://api.dexscreener.com/latest/dex/tokens/" + ",".join(mints[i:i + 25]), timeout=20)
                    for pair in (r.json() or {}).get("pairs") or []:
                        mint = (pair.get("baseToken") or {}).get("address")
                        px = pair.get("priceUsd")
                        if not mint or not px:
                            continue
                        liq = float((pair.get("liquidity") or {}).get("usd") or 0)
                        best = self._sol_liq.get(mint, -1.0)
                        if liq >= best:                    # the deepest pool is the honest price
                            self._sol_liq[mint] = liq
                            self._sol_prices[mint] = float(px)
        except Exception:  # noqa: BLE001
            pass

    def _name(self, token: str) -> str:
        """The token's ticker, which is what a person recognises -- never a hex address."""
        sym = self.ctx.db.scalar("SELECT symbol FROM tokens WHERE chain_id=? AND address=?", (self.ctx.chain_id, token))
        if not sym:
            # Solana mints are not in `tokens`; the decision carried the ticker DexScreener gave.
            sym = self.ctx.db.scalar("SELECT label FROM decisions WHERE chain_id=? AND token_address=? AND label IS NOT NULL "
                                     "ORDER BY id DESC LIMIT 1", (self.ctx.chain_id, token))
        sym = (sym or "").strip()
        return (sym[:11] if sym else str(token)[:8].upper())

    @staticmethod
    def _eur(v: float | None) -> str:
        return "—" if v is None else f"{v:+.2f} €".replace("-", "−")

    @staticmethod
    def _recovering(p: Any) -> int:
        """How many recovery rounds this line has had: > 0 means a written-off bag, not a position."""
        return sum(1 for kv in (p["notes"] or "").split() if kv.startswith("recover:"))

    @staticmethod
    def _chain(model_version: str | None) -> str:
        return "Solana" if str(model_version or "").startswith("sol-") else "Robinhood"

    async def positions(self) -> str:
        """What is open, per chain, and separately what is only waiting to be salvaged."""
        rows = self.ctx.db.query(
            "SELECT * FROM positions WHERE chain_id=? AND kind='PORTFOLIO' AND status='OPEN' "
            "AND (model_version LIKE 't1-%' OR model_version LIKE 'sol-t1-%') ORDER BY opened_ts DESC",
            (self.ctx.chain_id,))
        live = [p for p in rows if not self._recovering(p)]
        bags = [p for p in rows if self._recovering(p)]
        await self._load_sol_prices([p["token_address"] for p in live
                                     if str(p["model_version"] or "").startswith("sol-")])
        now = now_ts()
        out: list[str] = []
        if live:
            out += [f"<b>{len(live)} position{'s' if len(live) > 1 else ''} ouverte{'s' if len(live) > 1 else ''}</b>"
                    f" · {sum(float(p['size_eur'] or 0) for p in live):.0f} € engagés", ""]
            for p in live:
                price = self._mark(p)
                mult = (price / float(p["entry_price"])) if (price and p["entry_price"]) else None
                out.append(f"<code>{self._chain(p['model_version'])[:4]:<5}{self._name(p['token_address']):<11}</code>"
                           + (f" ×{mult:.2f}" if mult is not None else "   ?  ")
                           + f"  T+{(now - int(p['opened_ts'])) // 60} min")
        else:
            out.append("<b>Aucune position ouverte</b>")
        if bags:
            cap = int(self.ctx.config.get("t1.recover_max", 40))
            out += ["", f"<i>{len(bags)} sac{'s' if len(bags) > 1 else ''} invendable{'s' if len(bags) > 1 else ''} : "
                        f"argent deja perdu et compte comme tel, le moteur retente de les vendre.</i>", ""]
            for p in bags:
                out.append(f"<code>{self._chain(p['model_version'])[:4]:<5}{self._name(p['token_address']):<11}</code>"
                           f" tentative {self._recovering(p)}/{cap}")
        if t1_paused(self.ctx):
            out += ["", "⏸ Achats Robinhood en pause · /resume"]
        return NL.join(out)

    def closed(self, n: int) -> str:
        rows = self.ctx.db.query(
            "SELECT * FROM positions WHERE chain_id=? AND kind='PORTFOLIO' AND status='CLOSED' "
            "AND (model_version LIKE 't1-%' OR model_version LIKE 'sol-t1-%') ORDER BY closed_ts DESC LIMIT ?",
            (self.ctx.chain_id, n))
        if not rows:
            return "Aucune position fermee."
        out = [f"<b>{len(rows)} dernieres fermetures</b>", ""]
        for p in rows:
            cr = p["close_reason"] or ""
            sold, late = cr.startswith("vendu"), cr.startswith("recupere")
            mult = (float(p["close_price"]) / float(p["entry_price"])) if (p["close_price"] and p["entry_price"]) else None
            tag = "" if sold else ("  recupere hors regle" if late else "  invendable")
            out.append(f"<code>{time.strftime('%H:%M', time.gmtime(int(p['closed_ts'] or 0)))} "
                       f"{self._chain(p['model_version'])[:4]:<5}{self._name(p['token_address']):<11}</code>"
                       + (f" ×{mult:.2f}" if (mult is not None and (sold or late)) else "      ")
                       + f"  {self._eur(p['realized_eur'])}{tag}")
        return NL.join(out)

    def _tally(self, mv: str, since: int) -> dict[str, Any]:
        """One chain's real book over a period: sold, unsellable, open, and what each is worth."""
        db, cid = self.ctx.db, self.ctx.chain_id
        sold = db.query_one(
            "SELECT COUNT(*) n, SUM(CASE WHEN realized_eur>0 THEN 1 ELSE 0 END) w, COALESCE(SUM(realized_eur),0) p "
            "FROM positions WHERE chain_id=? AND model_version LIKE ? AND kind='PORTFOLIO' AND status='CLOSED' "
            "AND closed_ts>=? AND close_reason LIKE 'vendu%'", (cid, mv, since))
        lost = db.query_one(
            "SELECT COUNT(*) n, COALESCE(SUM(realized_eur),0) p FROM positions WHERE chain_id=? AND model_version LIKE ? "
            "AND kind='PORTFOLIO' AND opened_ts>=? AND realized_eur IS NOT NULL "
            "AND (close_reason IS NULL OR close_reason NOT LIKE 'vendu%')", (cid, mv, since))
        rec = db.query_one(
            "SELECT COUNT(*) n, COALESCE(SUM(realized_eur),0) p FROM positions WHERE chain_id=? AND model_version LIKE ? "
            "AND kind='PORTFOLIO' AND closed_ts>=? AND close_reason LIKE 'recupere%'", (cid, mv, since))
        opn = db.query_one(
            "SELECT COUNT(*) n, COALESCE(SUM(size_eur),0) s FROM positions WHERE chain_id=? AND model_version LIKE ? "
            "AND kind='PORTFOLIO' AND status='OPEN' AND (notes IS NULL OR notes NOT LIKE '%recover:%')", (cid, mv))
        bags = db.scalar(
            "SELECT COUNT(*) FROM positions WHERE chain_id=? AND model_version LIKE ? AND kind='PORTFOLIO' "
            "AND status='OPEN' AND notes LIKE '%recover:%'", (cid, mv), 0)
        return {"sold": int(sold["n"] or 0), "wins": int(sold["w"] or 0), "sold_eur": float(sold["p"] or 0),
                "lost": int(lost["n"] or 0), "lost_eur": float(lost["p"] or 0),
                "rec": int(rec["n"] or 0), "rec_eur": float(rec["p"] or 0),
                "open": int(opn["n"] or 0), "open_eur": float(opn["s"] or 0), "bags": int(bags),
                "net": float(sold["p"] or 0) + float(lost["p"] or 0)}

    async def pnl(self, full: bool = False) -> str:
        """Both chains, always, whether or not they traded -- and both periods, because a day
        boundary otherwise wipes the whole history from the screen at midnight."""
        day0 = now_ts() - (now_ts() % 86400)
        bal = await self._wallets()
        out = ["<b>Résultat réel</b>", ""]
        today = sum(self._tally(mv, day0)["net"] for _n, mv, _u in BOOKS)
        ever = sum(self._tally(mv, 0)["net"] for _n, mv, _u in BOOKS)
        out.append(f"<code>Aujourd'hui     </code><b>{self._eur(today)}</b>")
        out.append(f"<code>Depuis le début </code>{self._eur(ever)}")
        for name, mv, unit in BOOKS:
            t = self._tally(mv, 0 if full else day0)
            out += ["", f"<b>{name}</b>   {bal.get(unit, '—')}"]
            if not (t["sold"] or t["lost"] or t["open"] or t["bags"] or t["rec"]):
                out.append("<code>  aucun mouvement</code>")
                continue
            out.append(f"<code>  vendues     {t['sold']:>3}</code>" +
                       (f"  {t['wins']} gagnante{'s' if t['wins'] > 1 else ''}   {self._eur(t['sold_eur'])}" if t["sold"] else ""))
            out.append(f"<code>  invendables {t['lost']:>3}</code>" + (f"              {self._eur(t['lost_eur'])}" if t["lost"] else ""))
            out.append(f"<code>  ouvertes    {t['open']:>3}</code>" + (f"  {t['open_eur']:.0f} € engagés" if t["open"] else ""))
            if t["rec"]:
                out.append(f"<code>  récupérées  {t['rec']:>3}</code>  hors règle    {self._eur(t['rec_eur'])}")
            if t["bags"]:
                out.append(f"<code>  en reprise  {t['bags']:>3}</code>  sacs déjà perdus, valeur nulle")
        v = self.ctx.db.query_one("SELECT COUNT(*) n, COALESCE(SUM(realized_eur),0) p FROM positions WHERE chain_id=? "
                                  "AND kind='VIRTUAL' AND realized_eur IS NOT NULL AND opened_ts>=?",
                                  (self.ctx.chain_id, 0 if full else day0))
        if v and v["n"]:
            out += ["", f"<i>Simulation, argent fictif : {self._eur(float(v['p']))} sur {int(v['n'])} lignes</i>"]
        if t1_paused(self.ctx):
            out += ["", "⏸ Achats Robinhood en pause · /resume"]
        return NL.join(out)

    async def _wallets(self) -> dict[str, str]:
        """{unit: balance} for every chain the book trades on."""
        out: dict[str, str] = {}
        try:
            from intel.execution.signer import signer_address
            a = signer_address()
            if a:
                raw = await self.ctx.rpc.request("eth_getBalance", [a, "latest"])
                out["ETH"] = f"{int(raw, 16) / 1e18:.4f} ETH"
        except Exception:  # noqa: BLE001
            pass
        try:
            import httpx

            from intel.execution import solana as sol
            rpc, a = sol.rpc_url(), sol.signer_address()
            if rpc and a:
                async with httpx.AsyncClient() as c:
                    out["SOL"] = f"{await sol.sol_balance(c, rpc, a) / 1e9:.4f} SOL"
        except Exception:  # noqa: BLE001
            pass
        return out

    def orders(self, n: int) -> str:
        """Only what actually left for a chain. A refusal costs nothing and is a diagnostic, not
        history; a sale retried five times on one bag is one event, not five lines."""
        rows = self.ctx.db.query(
            "SELECT ts, kind, status, token_address, model_version FROM executions "
            "WHERE chain_id=? AND mode='live' AND kind IN ('BUY','SELL_ALL') AND status IN ('CONFIRMED','SUBMITTED','FAILED') "
            "ORDER BY id DESC LIMIT ?", (self.ctx.chain_id, max(n * 6, 40)))
        if not rows:
            return "Aucun ordre passe en chaine."
        fr = {"CONFIRMED": "passe", "SUBMITTED": "en vol", "FAILED": "echoue"}
        groups: list[list[Any]] = []
        for r in rows:
            key = (r["kind"], r["token_address"], r["status"], self._chain(r["model_version"]))
            if groups and groups[-1][0] == key:
                groups[-1][2] += 1
            else:
                groups.append([key, r["ts"], 1])
            if len(groups) > n:
                break
        out = ["<b>Derniers ordres en chaine</b>", ""]
        for (kind, token, status, chain), ts, count in groups[:n]:
            out.append(f"<code>{time.strftime('%H:%M', time.gmtime(int(ts)))} {chain[:4]:<5}"
                       f"{'achat' if kind == 'BUY' else 'vente':<6}{self._name(token):<11}</code> "
                       f"{fr.get(status, status.lower())}" + (f" (×{count})" if count > 1 else ""))
        return NL.join(out)

    async def balance(self) -> str:
        """Both wallets, each read on its own chain."""
        from intel.execution import solana as sol
        from intel.execution.signer import signer_address

        lines = ["<b>Portefeuilles</b>", ""]
        eth = signer_address()
        if eth:
            # Each figure on its own: a failed transaction count used to hide a balance that read
            # perfectly well, and the screen said "illisible" about a wallet holding 0.18 ETH.
            try:
                raw = await self.ctx.rpc.request("eth_getBalance", [eth, "latest"])
                lines.append(f"Robinhood  {int(raw, 16) / 1e18:.4f} ETH")
            except Exception:  # noqa: BLE001
                lines.append("Robinhood  solde illisible")
            detail = f"  {eth[:10]}…{eth[-4:]}"
            try:
                n = await self.ctx.rpc.request("eth_getTransactionCount", [eth, "latest"])
                detail += f" · {int(n, 16)} transactions"
            except Exception:  # noqa: BLE001
                pass
            lines.append(f"<code>{detail}</code>")
        rpc, addr = sol.rpc_url(), sol.signer_address()
        if rpc and addr:
            try:
                import httpx
                async with httpx.AsyncClient() as c:
                    lines.append(f"Solana     {await sol.sol_balance(c, rpc, addr) / 1e9:.4f} SOL")
                lines.append(f"<code>  {addr[:10]}…{addr[-4:]}</code>")
            except Exception:  # noqa: BLE001
                lines.append("Solana     solde illisible")
        return NL.join(lines)

    async def close(self) -> None:
        await self._client.aclose()
