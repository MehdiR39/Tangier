"""The T+1 book on Solana: discover a launch, judge its first minute, buy, sell on the clock.

Same shape as the Robinhood watcher, same book, same exit rule, and deliberately NOT the same
thresholds. A Robinhood launch that clears the bar trades 27 to 60 times in its first minute; the
first Solana measurements, taken 2026-09-07, run from 186 to 2 834. Carrying those numbers across
would either buy everything or nothing, which is the mistake that cost real money that morning.

So the entry rule here is expressed in the terms Solana actually offers, and its thresholds start
deliberately impossible: `solana.min_buyers` at 0 buys nothing. They are meant to be set from the
measurement running in intel/research/solana_watch.py, not from judgement.

What Solana gives that Robinhood never could: the payer of every transaction, in plain sight. On
Robinhood the swap `sender` is a router for 98 % of trades, so "how many distinct people are
buying" was unknowable and no filter could separate a bundle from a crowd. Here the first readings
already show the gap -- 2 834 trades between 40 wallets on one launchpad against 343 trades
between 139 on another -- and that ratio is the rule this engine is built to test.

It never signs unless two separate acts have been taken: a key in SOLANA_PRIVATE_KEY and
`solana.mode` set to live. Neither is done here.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx

from intel.context import IntelContext
from intel.execution import solana as sol
from intel.utils.timeutil import now_ts

log = logging.getLogger(__name__)
MODEL_VERSION = "sol-t1-v0.1"
DISCOVERY = (
    "https://api.dexscreener.com/token-profiles/latest/v1",
    "https://api.dexscreener.com/token-boosts/latest/v1",
)
PAIRS_URL = "https://api.dexscreener.com/latest/dex/tokens/"


class SolanaWatcher:
    def __init__(self, ctx: IntelContext) -> None:
        self.ctx = ctx
        self.client = httpx.AsyncClient(headers={"User-Agent": "tangier-intel/solana"})
        self.judged: dict[str, int] = {}          # pair -> ts, so a launch is judged once
        self.sent_ts: list[int] = []

    def _cfg(self, key: str, default: Any) -> Any:
        return self.ctx.config.get(f"solana.{key}", default)

    async def close(self) -> None:
        await self.client.aclose()

    # ---------------------------------------------------------------- cycle
    async def run_cycle(self) -> dict[str, Any]:
        if not self._cfg("enabled", False):
            return {"status": "disabled"}
        rpc = sol.rpc_url()
        if not rpc:
            return {"status": "disabled", "reason": "SOLANA_RPC_URL absent"}
        try:
            pairs = await self._discover()
        except Exception as exc:  # noqa: BLE001
            log.info("solana: decouverte refusee (%s)", str(exc)[:80])
            return {"status": "skipped", "error": str(exc)[:120]}
        judged = bought = 0
        for p in pairs:
            pid = p.get("pairAddress")
            created = p.get("pairCreatedAt")
            if not pid or not created or pid in self.judged:
                continue
            age_s = time.time() - created / 1000.0
            if age_s < 75 or age_s > float(self._cfg("max_age_seconds", 600)):
                continue                                   # judged once its first minute is complete
            self.judged[pid] = now_ts()
            judged += 1
            if await self._decide(rpc, p):
                bought += 1
        self._forget()
        await self._book(rpc)
        return {"status": "ok", "seen": len(pairs), "judged": judged, "decisions": bought}

    async def _discover(self) -> list[dict[str, Any]]:
        tokens: list[str] = []
        for url in DISCOVERY:
            r = await self.client.get(url, timeout=25)
            for x in r.json() if isinstance(r.json(), list) else []:
                if x.get("chainId") == "solana" and x.get("tokenAddress"):
                    tokens.append(x["tokenAddress"])
        tokens = list(dict.fromkeys(tokens))
        out: list[dict[str, Any]] = []
        for i in range(0, len(tokens), 25):
            r = await self.client.get(PAIRS_URL + ",".join(tokens[i: i + 25]), timeout=25)
            out.extend((r.json() or {}).get("pairs") or [])
        return [p for p in out if p.get("chainId") == "solana"]

    async def _first_minute(self, rpc: str, pair_id: str, created_ms: int) -> tuple[int, int]:
        """(trades, distinct payers) in the pool's first sixty seconds."""
        start = created_ms // 1000
        sigs: list[dict[str, Any]] = []
        before = None
        for _ in range(6):
            params: dict[str, Any] = {"limit": 1000}
            if before:
                params["before"] = before
            r = await self.client.post(rpc, json={"jsonrpc": "2.0", "id": 1, "method": "getSignaturesForAddress",
                                                  "params": [pair_id, params]}, timeout=40)
            got = (r.json() or {}).get("result") or []
            if not got:
                break
            sigs.extend(got)
            before = got[-1]["signature"]
            if (got[-1].get("blockTime") or 0) <= start:
                break
        window = [g for g in sigs if g.get("blockTime") and start <= g["blockTime"] <= start + 60]
        if not window:
            return 0, 0
        payers: set[str] = set()
        key = rpc.split("api-key=")[-1] if "api-key=" in rpc else ""
        if key:
            for i in range(0, min(len(window), 300), 100):
                try:
                    r = await self.client.post(f"https://api.helius.xyz/v0/transactions/?api-key={key}",
                                               json={"transactions": [w["signature"] for w in window[i: i + 100]]},
                                               timeout=50)
                    for tx in r.json() or []:
                        if tx.get("feePayer"):
                            payers.add(tx["feePayer"])
                except Exception:  # noqa: BLE001
                    break
        return len(window), len(payers)

    async def _decide(self, rpc: str, p: dict[str, Any]) -> bool:
        pid = p["pairAddress"]
        mint = (p.get("baseToken") or {}).get("address")
        symbol = (p.get("baseToken") or {}).get("symbol") or mint[:8]
        if not mint:
            return False
        trades, payers = await self._first_minute(rpc, pid, p["pairCreatedAt"])
        liq = float((p.get("liquidity") or {}).get("usd") or 0)
        ratio = trades / max(payers, 1)
        self._observe(pid, mint, symbol, p.get("dexId"), trades, payers, liq)
        min_buyers = int(self._cfg("min_buyers", 0))
        max_ratio = float(self._cfg("max_trades_per_buyer", 0) or 0)
        min_liq = float(self._cfg("min_liquidity_usd", 5000))
        why = None
        if not min_buyers:
            why = "regle non calibree (solana.min_buyers = 0)"
        elif payers < min_buyers:
            why = f"{payers} acheteurs distincts < {min_buyers}"
        elif max_ratio and ratio > max_ratio:
            why = f"{ratio:.0f} echanges par acheteur > {max_ratio:.0f} (bundle probable)"
        elif liq < min_liq:
            why = f"liquidite {liq:,.0f} $ < {min_liq:,.0f} $"
        if why:
            log.info("solana: %s ecarte — %s (%d echanges, %d acheteurs)", symbol, why, trades, payers)
            return False
        now = now_ts()
        self.sent_ts = [t for t in self.sent_ts if now - t < 3600]
        if len(self.sent_ts) >= int(self._cfg("max_per_hour", 10)):
            log.info("solana: %s passe la regle mais le plafond horaire est atteint", symbol)
            return False
        self.ctx.db.insert("decisions", {
            "ts": now, "chain_id": self.ctx.chain_id, "token_address": mint, "label": symbol,
            "kind": "BUY", "reason": f"Solana T+1 · {trades} echanges, {payers} acheteurs distincts",
            "price": float(p.get("priceUsd") or 0) or None, "size_eur": float(self._cfg("size_eur", 5.0)),
            "position_id": None, "sent": 0,
            "metrics_json": json.dumps({"pair": pid, "dex": p.get("dexId"), "trades_first_minute": trades,
                                        "uniq_payers": payers, "liquidity_usd": liq, "chain": "solana"}),
            "model_version": MODEL_VERSION,
        })
        self.sent_ts.append(now)
        log.info("solana ACHAT %s · %d echanges, %d acheteurs · %.0f EUR", symbol, trades, payers,
                 float(self._cfg("size_eur", 5.0)))
        return True

    def _observe(self, pid: str, mint: str, symbol: str, dex: str | None, trades: int, payers: int, liq: float) -> None:
        """One row per judged launch, bought or not: the series any calibration will be built from."""
        try:
            self.ctx.db.execute(
                "CREATE TABLE IF NOT EXISTS solana_observations("
                "  ts INTEGER NOT NULL, pair_id TEXT PRIMARY KEY, mint TEXT, symbol TEXT, dex TEXT,"
                "  trades_first_minute INTEGER, uniq_payers INTEGER, liquidity_usd REAL)")
            self.ctx.db.execute("INSERT OR IGNORE INTO solana_observations VALUES(?,?,?,?,?,?,?,?)",
                                (now_ts(), pid, mint, symbol, dex, trades, payers, liq))
        except Exception as exc:  # noqa: BLE001
            log.info("solana: observation non enregistree (%s)", str(exc)[:80])

    # ----------------------------------------------------------------- book
    async def _book(self, rpc: str) -> None:
        """Execute pending Solana decisions, then close positions on the same clock as Robinhood."""
        mode = str(self._cfg("mode", "dry_run"))
        db = self.ctx.db
        sol_eur = float(self._cfg("sol_eur", 180.0))
        for d in db.query(
                "SELECT d.* FROM decisions d LEFT JOIN executions e ON e.chain_id=d.chain_id AND e.decision_id=d.id "
                "WHERE d.chain_id=? AND d.model_version=? AND e.id IS NULL ORDER BY d.id LIMIT 5",
                (self.ctx.chain_id, MODEL_VERSION)):
            res = await sol.prepare_buy(self.client, mint=d["token_address"], size_eur=float(d["size_eur"] or 5.0),
                                        sol_eur=sol_eur, slippage_pct=float(self._cfg("slippage_pct", 5.0)),
                                        max_impact_pct=float(self._cfg("max_impact_pct", 10.0)))
            tx_b64 = res.pop("tx", None)
            status = res.pop("status")
            row = {"ts": now_ts(), "chain_id": self.ctx.chain_id, "decision_id": d["id"],
                   "token_address": d["token_address"], "label": d["label"], "kind": "BUY",
                   "size_eur": d["size_eur"], "mode": mode, "status": status,
                   "model_version": MODEL_VERSION, **res}
            if status == "BUILT" and mode == "live" and tx_b64:
                try:
                    sig = await sol.send(self.client, rpc, sol.sign(tx_b64))
                    row.update({"status": "SUBMITTED", "tx_hash": sig})
                    log.info("solana ordre envoye %s tx=%s", d["label"], sig[:16])
                except sol.SolanaRefused as exc:
                    row.update({"status": "FAILED", "error": str(exc)[:400]})
                    log.warning("solana ordre non envoye %s : %s", d["label"], str(exc)[:160])
            elif status == "BUILT":
                log.info("solana ordre construit a blanc %s · %s · impact %.2f %%", d["label"],
                         res.get("route"), float(res.get("slippage_pct") or 0))
            else:
                log.info("solana ordre refuse %s : %s", d["label"], res.get("refused_reason"))
            db.insert("executions", row)

    def _forget(self) -> None:
        cutoff = now_ts() - 6 * 3600
        for pid in [k for k, v in self.judged.items() if v < cutoff]:
            del self.judged[pid]
