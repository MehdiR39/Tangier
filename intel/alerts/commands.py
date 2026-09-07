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
        return ("/positions · /closed [n] · /pnl · /orders [n] · /solde · /pause · /resume · /restart\n"
                f"mode: {self.ctx.config.get('execution.mode', 'dry_run')} · achats {'EN PAUSE' if t1_paused(self.ctx) else 'actifs'}")

    def _mark(self, p: Any) -> float | None:
        if self.t1 is None:
            return None
        notes = dict(kv.split(":", 1) for kv in (p["notes"] or "").split() if ":" in kv)
        return self.t1._mark(notes.get("pool"), p["token_address"], notes.get("quote"))

    def positions(self) -> str:
        rows = self.ctx.db.query(
            "SELECT * FROM positions WHERE chain_id=? AND model_version LIKE 't1-%' AND status='OPEN' ORDER BY opened_ts DESC",
            (self.ctx.chain_id,))
        if not rows:
            return "aucune position ouverte" + (" · achats EN PAUSE" if t1_paused(self.ctx) else "")
        now = now_ts()
        lines = [f"<b>{len(rows)} position(s) ouverte(s)</b>"]
        exposure = 0.0
        for p in rows:
            price = self._mark(p)
            mult = (price / float(p["entry_price"])) if (price and p["entry_price"]) else None
            age = (now - int(p["opened_ts"])) // 60
            exposure += float(p["size_eur"] or 0)
            lines.append(f"{p['token_address'][:10]} · {float(p['size_eur'] or 0):.0f} € · T+{age} min · "
                         + (f"x{mult:.2f}" if mult is not None else "prix inconnu")
                         + (" · réel" if p["kind"] == "PORTFOLIO" else " · à blanc"))
        lines.append(f"engagé : {exposure:.0f} €")
        return "\n".join(lines)

    def closed(self, n: int) -> str:
        rows = self.ctx.db.query(
            "SELECT * FROM positions WHERE chain_id=? AND model_version LIKE 't1-%' AND status='CLOSED' ORDER BY closed_ts DESC LIMIT ?",
            (self.ctx.chain_id, n))
        if not rows:
            return "aucune position fermée"
        lines = [f"<b>{len(rows)} dernières positions fermées</b>"]
        for p in rows:
            mult = (float(p["close_price"]) / float(p["entry_price"])) if (p["close_price"] and p["entry_price"]) else None
            held = (int(p["closed_ts"] or 0) - int(p["opened_ts"])) // 60
            r = p["realized_eur"]
            lines.append(f"{time.strftime('%H:%M', time.gmtime(int(p['closed_ts'] or 0)))} {p['token_address'][:10]} · "
                         + (f"x{mult:.2f}" if mult is not None else "x?") + f" · {held} min · "
                         + (f"{r:+.2f} €" if r is not None else "?") + f" · {(p['close_reason'] or '')[:28]}"
                         + (" · réel" if p["kind"] == "PORTFOLIO" else ""))
        return "\n".join(lines)

    async def pnl(self, full: bool = False) -> str:
        """Short by default: the real book today, one line for the paper book. /pnl all for everything."""
        db = self.ctx.db
        day0 = now_ts() - (now_ts() % 86400)
        since = 0 if full else day0
        head = "<b>P&amp;L</b> " + ("depuis le début" if full else "aujourd'hui") + (" · achats EN PAUSE" if t1_paused(self.ctx) else "")
        out = [head]
        for kind, klab in (("PORTFOLIO", "Réel"), ("VIRTUAL", "À blanc")):
            r = db.query_one(
                "SELECT COUNT(*) n, SUM(CASE WHEN realized_eur>0 THEN 1 ELSE 0 END) w, COALESCE(SUM(realized_eur),0) pnl "
                "FROM positions WHERE chain_id=? AND model_version LIKE 't1-%' AND status='CLOSED' AND kind=? AND closed_ts>=? "
                "AND close_reason LIKE 'vendu%'", (self.ctx.chain_id, kind, since))
            w = db.query_one(
                "SELECT COUNT(*) n, COALESCE(SUM(realized_eur),0) pnl FROM positions WHERE chain_id=? AND model_version LIKE 't1-%' "
                "AND status='CLOSED' AND kind=? AND closed_ts>=? AND close_reason NOT LIKE 'vendu%'", (self.ctx.chain_id, kind, since))
            n, wins, pnl = (r["n"] or 0), int(r["w"] or 0), float(r["pnl"] or 0)
            lost, lost_eur = (w["n"] or 0), float(w["pnl"] or 0)
            if kind == "PORTFOLIO" or full or n or lost:
                line = f"{klab} : {n} vendue{'s' if n > 1 else ''}"
                if n:
                    line += f", {wins} gagnante{'s' if wins > 1 else ''}, {pnl:+.2f} €"
                if lost:
                    line += f" · {lost} invendable{'s' if lost > 1 else ''} ({lost_eur:+.0f} €)"
                out.append(line)
        op = db.query_one("SELECT COUNT(*) n, COALESCE(SUM(size_eur),0) s FROM positions WHERE chain_id=? AND model_version LIKE 't1-%' AND status='OPEN' AND kind='PORTFOLIO'",
                          (self.ctx.chain_id,))
        out.append(f"Ouvertes : {op['n']}" + (f" ({op['s']:.0f} € engagés)" if op["n"] else ""))
        ex = db.query("SELECT kind, status, COUNT(*) n FROM executions WHERE chain_id=? AND mode='live' AND ts>=? AND kind IN ('BUY','SELL_ALL') GROUP BY kind, status",
                      (self.ctx.chain_id, since))
        if ex:
            fr = {"CONFIRMED": "confirmé", "SUBMITTED": "envoyé", "FAILED": "échoué", "REFUSED": "refusé", "BUILT": "construit"}
            out.append("Ordres : " + " · ".join(f"{'achat' if r['kind'] == 'BUY' else 'vente'} {fr.get(r['status'], r['status'].lower())} {r['n']}" for r in ex))
        try:
            from intel.execution.signer import signer_address
            addr = signer_address()
            if addr:
                raw = await self.ctx.rpc.request("eth_getBalance", [addr, "latest"])
                out.append(f"Solde : {int(raw, 16) / 1e18:.4f} ETH")
        except Exception:  # noqa: BLE001
            pass
        return "\n".join(out)

    def orders(self, n: int) -> str:
        rows = self.ctx.db.query(
            "SELECT ts, kind, status, mode, size_eur, token_address, tx_hash, refused_reason, error FROM executions "
            "WHERE chain_id=? ORDER BY id DESC LIMIT ?", (self.ctx.chain_id, n))
        if not rows:
            return "aucun ordre journalisé"
        lines = [f"<b>{len(rows)} derniers ordres</b>"]
        for r in rows:
            why = (r["refused_reason"] or r["error"] or "")[:40]
            lines.append(f"{time.strftime('%H:%M', time.gmtime(int(r['ts'])))} {r['kind']} {r['status'].lower()} · {r['token_address'][:10]} · "
                         f"{float(r['size_eur'] or 0):.0f} € · {r['mode']}"
                         + (f" · tx {r['tx_hash'][:10]}…" if r["tx_hash"] else "") + (f" · {why}" if why else ""))
        return "\n".join(lines)

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
