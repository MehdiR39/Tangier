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
        mode = str(self._cfg("mode", "dry_run"))
        if mode == "live":
            await self._reconcile(rpc)
        await self._positions(rpc, mode)
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
        # A ticket is worthless if the wallet cannot fund it. Impact is linear and tiny here
        # (0.37 % at 20 EUR, 1.10 % at 50), so size is not the constraint -- the balance is, and
        # nothing checked it: four concurrent tickets already exhaust a 98 EUR wallet.
        max_open = int(self._cfg("max_open_positions", 4))
        n_open = self.ctx.db.scalar(
            "SELECT COUNT(*) FROM positions WHERE chain_id=? AND model_version=? AND status='OPEN'",
            (self.ctx.chain_id, MODEL_VERSION), 0)
        if n_open >= max_open:
            log.info("solana: %s passe la regle mais %d positions sont deja ouvertes (plafond %d)",
                     symbol, n_open, max_open)
            return False
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
        sol_eur = await sol.sol_eur(self.client)
        for d in db.query(
                "SELECT d.* FROM decisions d LEFT JOIN executions e ON e.chain_id=d.chain_id AND e.decision_id=d.id "
                "WHERE d.chain_id=? AND d.model_version=? AND e.id IS NULL ORDER BY d.id LIMIT 5",
                (self.ctx.chain_id, MODEL_VERSION)):
            res = await sol.prepare_buy(self.client, mint=d["token_address"], size_eur=float(d["size_eur"] or 5.0),
                                        sol_eur=sol_eur, slippage_pct=float(self._cfg("slippage_pct", 5.0)),
                                        max_impact_pct=float(self._cfg("max_impact_pct", 10.0)))
            tx_b64 = res.pop("tx", None)
            status = res.pop("status")
            route = res.pop("route", None)          # journal only: `executions` has no such column
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
                         route, float(res.get("slippage_pct") or 0))
            else:
                log.info("solana ordre refuse %s : %s", d["label"], res.get("refused_reason"))
            db.insert("executions", row)

    async def _reconcile(self, rpc: str) -> None:
        """Turn sent orders into confirmed or failed ones, from their receipts.

        Without this a Solana order stays "in flight" for ever: the book would count a purchase
        the chain rejected, and every screen would show a state that stopped being true seconds
        after it was written.
        """
        rows = self.ctx.db.query(
            "SELECT id, tx_hash, kind, token_address FROM executions WHERE chain_id=? AND model_version=? "
            "AND status='SUBMITTED' AND tx_hash IS NOT NULL AND ts>?",
            (self.ctx.chain_id, MODEL_VERSION, now_ts() - 6 * 3600))
        for e in rows:
            try:
                r = await self.client.post(rpc, json={"jsonrpc": "2.0", "id": 1, "method": "getSignatureStatuses",
                                                      "params": [[e["tx_hash"]], {"searchTransactionHistory": True}]},
                                           timeout=25)
                st = (((r.json() or {}).get("result") or {}).get("value") or [None])[0]
            except Exception:  # noqa: BLE001
                continue
            if not st or not st.get("confirmationStatus"):
                continue                                    # still travelling
            ok = st.get("err") is None
            self.ctx.db.execute("UPDATE executions SET status=?, error=? WHERE id=?",
                                ("CONFIRMED" if ok else "FAILED",
                                 None if ok else str(st.get("err"))[:200], e["id"]))
            log.info("solana ordre %s %s en chaine · tx %s", e["kind"],
                     "confirme" if ok else "REJETE", str(e["tx_hash"])[:14])

    async def _positions(self, rpc: str, mode: str) -> None:
        """Open a line on a confirmed buy, then close it on the rule: x2, or the holding window.

        Chosen on 235 launches observed over 12 h (intel/research/solana_backtest.py). The holding
        sweep has a clear peak at a quarter of an hour, and it wins on all four counts at once:
        +1.06 EUR per ticket, 61 % winners, near-identical on both halves of the period (+1.08 then
        +1.04), and 80 % of the profit survives removing the five best trades. Past it the decay is
        steady -- +0.64 at an hour, +0.37 at two, robustness down to 42 % -- which says what is left
        to gain out there sits in a few rare trades. Below it, T+5 returns only +0.72.

        The opposite of the other chain, where holding past ten minutes destroyed the book: there
        the liquidity is pulled within minutes, here a bonding curve cannot be withdrawn and the
        price is given time to move.
        """
        db = self.ctx.db
        accepted = ("BUILT",) if mode != "live" else ("SUBMITTED", "CONFIRMED")
        ph = ",".join("?" * len(accepted))
        now = now_ts()
        for r in db.query(
                "SELECT d.id, d.token_address, d.label, d.price, d.size_eur, e.ts ets FROM decisions d "
                "JOIN executions e ON e.chain_id=d.chain_id AND e.decision_id=d.id "
                f"WHERE d.chain_id=? AND d.model_version=? AND d.kind='BUY' AND d.ts>? AND e.status IN ({ph}) "
                "AND NOT EXISTS (SELECT 1 FROM positions p WHERE p.chain_id=d.chain_id AND p.notes LIKE ('sol:' || d.id || ' %'))",
                (self.ctx.chain_id, MODEL_VERSION, now - 6 * 3600, *accepted)):
            db.insert("positions", {
                "chain_id": self.ctx.chain_id, "token_address": r["token_address"], "label": r["label"],
                "kind": "VIRTUAL" if mode != "live" else "PORTFOLIO", "opened_ts": int(r["ets"] or now),
                "entry_price": r["price"], "size_eur": r["size_eur"], "status": "OPEN", "peak_price": r["price"],
                "model_version": MODEL_VERSION, "notes": f"sol:{r['id']} mint:{r['token_address']}",
            })
            log.info("solana position ouverte %s · %.0f EUR", r["label"], float(r["size_eur"] or 0))

        tp = float(self._cfg("take_profit_multiple", 2.0))
        hold = int(self._cfg("max_hold_seconds", 900))
        for p in db.query("SELECT * FROM positions WHERE chain_id=? AND model_version=? AND status='OPEN'",
                          (self.ctx.chain_id, MODEL_VERSION)):
            mint = dict(kv.split(":", 1) for kv in (p["notes"] or "").split() if ":" in kv).get("mint")
            if not mint:
                continue
            age = now_ts() - int(p["opened_ts"])
            amount = 0
            if mode == "live":
                try:
                    amount = await sol.token_balance(self.client, rpc, sol.signer_address() or "", mint)
                except Exception as exc:  # noqa: BLE001
                    log.info("solana: solde de %s illisible (%s), vente reportee", p["label"], str(exc)[:60])
                    continue
                if amount <= 0:
                    db.execute("UPDATE positions SET status='CLOSED', closed_ts=?, close_reason=?, realized_eur=0 WHERE id=?",
                               (now_ts(), "aucun jeton en portefeuille", p["id"]))
                    continue
            # What the position is worth is what selling it would RETURN, not what a price feed
            # prints. On 2026-09-08 haMSTR read x1.66 from DexScreener while the chain would pay
            # 4.31 EUR on a 5 EUR stake -- a loss shown as a gain, and a take-profit that would
            # have fired on a doubling that never existed. Impact was 0.6 %, so the gap was the
            # entry price: taken from a feed at decision time, not from the trade that happened.
            mult, value = await self._worth(rpc, mint, amount, float(p["size_eur"] or 5.0))
            if mult is None:
                px = await self._price(mint)
                mult = (px / float(p["entry_price"])) if (px and p["entry_price"]) else None
            if not (mult is not None and mult >= tp) and age < hold:
                continue
            res = await sol.prepare_sell(self.client, mint=mint, amount=amount or 1,
                                         slippage_pct=float(self._cfg("sell_slippage_pct", 25.0)))
            tx = res.pop("tx", None)
            res.pop("route", None)
            row = {"ts": now_ts(), "chain_id": self.ctx.chain_id, "token_address": mint, "label": p["label"],
                   "kind": "SELL_ALL", "size_eur": p["size_eur"], "mode": mode, "status": res.pop("status"),
                   "model_version": MODEL_VERSION, **res}
            if row["status"] == "BUILT" and mode == "live" and tx:
                try:
                    row.update({"status": "SUBMITTED", "tx_hash": await sol.send(self.client, rpc, sol.sign(tx))})
                except sol.SolanaRefused as exc:
                    row.update({"status": "FAILED", "error": str(exc)[:400]})
            db.insert("executions", row)
            if row["status"] in ("SUBMITTED", "CONFIRMED") or (mode != "live" and row["status"] == "BUILT"):
                realized = (float(p["size_eur"]) * (mult - 1.0)) if (mult is not None and p["size_eur"]) else None
                db.execute("UPDATE positions SET status='CLOSED', closed_ts=?, close_price=?, close_reason=?, realized_eur=? WHERE id=?",
                           (now_ts(), px, f"vendu x{mult:.2f}" if mult is not None else "vendu", realized, p["id"]))
                log.info("solana VENTE %s · %s · %s", p["label"],
                         f"x{mult:.2f}" if mult is not None else "multiple inconnu",
                         "objectif atteint" if (mult is not None and mult >= tp) else f"T+{age // 60} min")

    async def _worth(self, rpc: str, mint: str, amount: int, stake_eur: float) -> tuple[float | None, float | None]:
        """(multiple, euros) the position would actually fetch, asked to the router itself."""
        if amount <= 0 or stake_eur <= 0:
            return None, None
        try:
            r = await sol.prepare_sell(self.client, mint=mint, amount=amount, slippage_pct=25.0)
        except Exception:  # noqa: BLE001
            return None, None
        out = int(r.get("quoted_amount_out") or 0)
        if out <= 0:
            return None, None
        eur = out / 1e9 * await sol.sol_eur(self.client)
        return eur / stake_eur, eur

    async def _price(self, mint: str) -> float | None:
        try:
            r = await self.client.get(PAIRS_URL + mint, timeout=20)
            pairs = (r.json() or {}).get("pairs") or []
            best = max((p for p in pairs if p.get("priceUsd")), key=lambda p: float((p.get("liquidity") or {}).get("usd") or 0), default=None)
            return float(best["priceUsd"]) if best else None
        except Exception:  # noqa: BLE001
            return None

    def _forget(self) -> None:
        cutoff = now_ts() - 6 * 3600
        for pid in [k for k, v in self.judged.items() if v < cutoff]:
            del self.judged[pid]
