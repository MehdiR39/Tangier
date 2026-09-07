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
            return self.positions()
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
        mode = "réel" if self.ctx.config.get("execution.mode", "dry_run") == "live" else "à blanc"
        etat = "en pause" if t1_paused(self.ctx) else "actifs"
        return NL.join([
            "<b>Commandes</b>", "",
            "<code>/pnl       </code> résultat du jour",
            "<code>/positions </code> ce qui est ouvert",
            "<code>/closed    </code> dernières fermetures",
            "<code>/orders    </code> ordres passés en chaîne",
            "<code>/solde     </code> portefeuille",
            "<code>/pause     </code> arrêter d'acheter",
            "<code>/resume    </code> reprendre les achats",
            "<code>/restart   </code> redémarrer le moteur",
            "", f"<i>/pnl all pour le cumul · /closed 20 pour plus de lignes</i>",
            "", f"Mode {mode} · achats {etat}",
        ])

    def _mark(self, p: Any) -> float | None:
        if self.t1 is None:
            return None
        notes = dict(kv.split(":", 1) for kv in (p["notes"] or "").split() if ":" in kv)
        return self.t1._mark(notes.get("pool"), p["token_address"], notes.get("quote"))

    def _name(self, token: str) -> str:
        """The token's ticker, which is what a person recognises -- never a hex address."""
        sym = self.ctx.db.scalar("SELECT symbol FROM tokens WHERE chain_id=? AND address=?", (self.ctx.chain_id, token))
        sym = (sym or "").strip()
        return (sym[:12] if sym else token[2:8].upper())

    @staticmethod
    def _eur(v: float | None) -> str:
        return "—" if v is None else f"{v:+.2f} €".replace("-", "−")

    @staticmethod
    def _recovering(p: Any) -> int:
        """How many recovery rounds this line has had: > 0 means a written-off bag, not a position."""
        return sum(1 for kv in (p["notes"] or "").split() if kv.startswith("recover:"))

    def positions(self) -> str:
        rows = self.ctx.db.query(
            "SELECT * FROM positions WHERE chain_id=? AND model_version LIKE 't1-%' AND status='OPEN' AND kind='PORTFOLIO' "
            "ORDER BY opened_ts DESC", (self.ctx.chain_id,))
        # A bag reopened by the recovery loop is not a position: its euros are already lost and its
        # multiple is a price nobody will pay. Counting them as engaged capital (2026-09-07:
        # "3 positions ouvertes · 15 € engagés" for three honeypots) says the opposite of the truth.
        live = [p for p in rows if not self._recovering(p)]
        bags = [p for p in rows if self._recovering(p)]
        out: list[str] = []
        now = now_ts()
        if live:
            engaged = sum(float(p["size_eur"] or 0) for p in live)
            out += [f"<b>{len(live)} position{'s' if len(live) > 1 else ''} ouverte{'s' if len(live) > 1 else ''}</b> · {engaged:.0f} € engagés", ""]
            for p in live:
                price = self._mark(p)
                mult = (price / float(p["entry_price"])) if (price and p["entry_price"]) else None
                out.append(f"<code>{self._name(p['token_address']):<11}</code> "
                           + (f"×{mult:.2f}" if mult is not None else "  ?  ")
                           + f"  T+{(now - int(p['opened_ts'])) // 60} min")
        else:
            out.append("Aucune position ouverte." + (" Achats en pause." if t1_paused(self.ctx) else ""))
        if bags:
            cap = int(self.ctx.config.get("t1.recover_max", 8))
            out += ["", f"<i>{len(bags)} sac{'s' if len(bags) > 1 else ''} invendable{'s' if len(bags) > 1 else ''}, déjà perdu{'s' if len(bags) > 1 else ''}, réessayé{'s' if len(bags) > 1 else ''} :</i>"]
            for p in bags:
                out.append(f"<code>{self._name(p['token_address']):<11}</code> tentative {self._recovering(p)}/{cap}")
        return NL.join(out)

    def closed(self, n: int) -> str:
        rows = self.ctx.db.query(
            "SELECT * FROM positions WHERE chain_id=? AND model_version LIKE 't1-%' AND status='CLOSED' AND kind='PORTFOLIO' "
            "ORDER BY closed_ts DESC LIMIT ?", (self.ctx.chain_id, n))
        if not rows:
            return "Aucune position fermée."
        out = [f"<b>{len(rows)} dernières fermetures</b>", ""]
        for p in rows:
            sold = (p["close_reason"] or "").startswith("vendu")
            mult = (float(p["close_price"]) / float(p["entry_price"])) if (p["close_price"] and p["entry_price"]) else None
            out.append(f"<code>{time.strftime('%H:%M', time.gmtime(int(p['closed_ts'] or 0)))} {self._name(p['token_address']):<11}</code> "
                       + (f"×{mult:.2f}  " if (mult is not None and sold) else "      ")
                       + self._eur(p["realized_eur"]) + ("" if sold else "  invendable"))
        return NL.join(out)

    async def pnl(self, full: bool = False) -> str:
        """The real book, plainly. The paper book is one line; /pnl all opens everything."""
        db = self.ctx.db
        since = 0 if full else now_ts() - (now_ts() % 86400)
        title = "depuis le début" if full else "aujourd'hui"

        def tally(kind: str) -> tuple[int, int, float, int, float]:
            r = db.query_one(
                "SELECT COUNT(*) n, SUM(CASE WHEN realized_eur>0 THEN 1 ELSE 0 END) w, COALESCE(SUM(realized_eur),0) p "
                "FROM positions WHERE chain_id=? AND model_version LIKE 't1-%' AND status='CLOSED' AND kind=? "
                "AND closed_ts>=? AND close_reason LIKE 'vendu%'", (self.ctx.chain_id, kind, since))
            # A bag being retried is still a loss on the books: counting only CLOSED rows made the
            # reported result jump by the amount under recovery.
            w = db.query_one(
                "SELECT COUNT(*) n, COALESCE(SUM(realized_eur),0) p FROM positions WHERE chain_id=? AND model_version LIKE 't1-%' "
                "AND kind=? AND opened_ts>=? AND realized_eur IS NOT NULL "
                "AND (close_reason IS NULL OR close_reason NOT LIKE 'vendu%')", (self.ctx.chain_id, kind, since))
            return int(r["n"] or 0), int(r["w"] or 0), float(r["p"] or 0), int(w["n"] or 0), float(w["p"] or 0)

        n, wins, pnl, lost, lost_eur = tally("PORTFOLIO")
        rec = db.query_one(
            "SELECT COUNT(*) n, COALESCE(SUM(realized_eur),0) p FROM positions WHERE chain_id=? AND model_version LIKE 't1-%' "
            "AND kind='PORTFOLIO' AND closed_ts>=? AND close_reason LIKE 'recupere%'", (self.ctx.chain_id, since))
        out = [f"<b>Résultat réel · {title}</b>", "", f"<b>{self._eur(pnl + lost_eur)}</b>", ""]
        if n:
            out.append(f"<code>Vendues     {n:>3}</code>  {wins} gagnante{'s' if wins > 1 else ''}   {self._eur(pnl)}")
        if lost:
            out.append(f"<code>Invendables {lost:>3}</code>              {self._eur(lost_eur)}")
        if rec and rec["n"]:
            out.append(f"<code>Récupérés   {int(rec['n']):>3}</code>  hors règle    {self._eur(float(rec['p']))}")
        op = db.query_one("SELECT COUNT(*) n, COALESCE(SUM(size_eur),0) s FROM positions WHERE chain_id=? AND model_version LIKE 't1-%' "
                          "AND status='OPEN' AND kind='PORTFOLIO' AND notes NOT LIKE '%recover:%'", (self.ctx.chain_id,))
        out.append(f"<code>Ouvertes    {int(op['n']):>3}</code>" + (f"  {float(op['s']):.0f} € engagés" if op["n"] else ""))
        rec = db.scalar("SELECT COUNT(*) FROM positions WHERE chain_id=? AND model_version LIKE 't1-%' AND status='OPEN' "
                        "AND kind='PORTFOLIO' AND notes LIKE '%recover:%'", (self.ctx.chain_id,), 0)
        if rec:
            out.append(f"<code>Réessayés   {int(rec):>3}</code>  sacs déjà perdus")
        try:
            from intel.execution.signer import signer_address
            addr = signer_address()
            if addr:
                raw = await self.ctx.rpc.request("eth_getBalance", [addr, "latest"])
                out += ["", f"Solde : {int(raw, 16) / 1e18:.4f} ETH"]
        except Exception:  # noqa: BLE001
            pass
        vn, vw, vp, vl, vle = tally("VIRTUAL")
        if vn or vl:
            # The sold half alone read as a profit while the simulation's own write-offs were
            # larger (2026-09-07: +98 shown, -207 hidden). One number, the net, or none.
            # "Carnet à blanc" was read as a second pot of money. It is a simulation on far more
            # launches than the real book buys, and its euros do not exist: say so in the label.
            out += ["", f"<i>Simulation, argent fictif : {self._eur(vp + vle)} sur {vn + vl} lignes</i>"]
        if t1_paused(self.ctx):
            out += ["", "⏸ Achats en pause · /resume"]
        return NL.join(out)

    def orders(self, n: int) -> str:
        # Refused orders never left the machine and cost nothing: diagnostics, not history. And a
        # sell that was retried five times on the same bag is one event, not five lines.
        rows = self.ctx.db.query(
            "SELECT ts, kind, status, token_address FROM executions "
            "WHERE chain_id=? AND mode='live' AND kind IN ('BUY','SELL_ALL') AND status IN ('CONFIRMED','SUBMITTED','FAILED') "
            "ORDER BY id DESC LIMIT ?", (self.ctx.chain_id, max(n * 6, 40)))
        if not rows:
            return "Aucun ordre passé en chaîne."
        fr = {"CONFIRMED": "passé", "SUBMITTED": "en vol", "FAILED": "échoué"}
        groups: list[list[Any]] = []
        for r in rows:
            key = (r["kind"], r["token_address"], r["status"])
            if groups and groups[-1][0] == key:
                groups[-1][2] += 1
            else:
                groups.append([key, r["ts"], 1])
            if len(groups) > n:
                break
        out = [f"<b>Derniers ordres en chaîne</b>", ""]
        for (kind, token, status), ts, count in groups[:n]:
            out.append(f"<code>{time.strftime('%H:%M', time.gmtime(int(ts)))} "
                       f"{'achat' if kind == 'BUY' else 'vente':<5} {self._name(token):<11}</code> "
                       f"{fr.get(status, status.lower())}" + (f" (×{count})" if count > 1 else ""))
        return NL.join(out)

    async def balance(self) -> str:
        from intel.execution.signer import signer_address
        addr = signer_address()
        if not addr:
            return "aucune clé configurée : pas de portefeuille à lire"
        raw = await self.ctx.rpc.request("eth_getBalance", [addr, "latest"])
        eth = int(raw, 16) / 1e18
        usd = None
        try:
            from intel.research.report import native_price_usd
            px = await native_price_usd(self.ctx)
            usd = eth * px if px else None
        except Exception:  # noqa: BLE001
            usd = None
        n = await self.ctx.rpc.request("eth_getTransactionCount", [addr, "latest"])
        return (f"<b>portefeuille</b> {addr[:10]}…{addr[-4:]}\nETH : {eth:.5f}" + (f" ≈ {usd:,.0f} $" if usd else "")
                + f"\ntransactions envoyées : {int(n, 16)}")

    async def close(self) -> None:
        await self._client.aclose()
