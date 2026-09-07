"""Per-token pipeline shared by the portfolio watcher and the scanner.

ingest (market → pools → transfers → pool events → trades → holders → security)
→ point-in-time metrics → hard filters → scores → state → persisted score row
→ alert candidates → dedup → Telegram.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from intel import MODEL_VERSION
from intel.alerts.dedup import AlertDeduper
from intel.alerts.format import format_alert
from intel.alerts.rules import AlertCandidate, evaluate_alerts
from intel.alerts.telegram import TelegramSender
from intel.chain import erc20
from intel.context import IntelContext
from intel.ingest.holders import label_top_holders, snapshot_holders_blockscout, snapshot_holders_replay
from intel.ingest.market import snapshot_quote_assets, snapshot_token_market
from intel.ingest.pools import PoolInfo, ensure_pools, ingest_pool_events, load_pools
from intel.ingest.security import run_security_checks
from intel.ingest.trades import ingest_trades
from intel.ingest.transfers import ingest_transfers
from intel.metrics.assemble import build_token_metrics
from intel.metrics.pricing import QuotePricer
from intel.providers.base import BudgetExhausted
from intel.scoring.hard_filters import apply_hard_filters
from intel.scoring.scores import Scores, compute_scores
from intel.scoring.states import StateDecision, decide_state
from intel.utils.timeutil import now_ts, parse_iso

log = logging.getLogger(__name__)


class TokenPipeline:
    def __init__(self, ctx: IntelContext, pricer: QuotePricer, deduper: AlertDeduper, sender: TelegramSender | None) -> None:
        self.ctx = ctx
        self.pricer = pricer
        self.deduper = deduper
        self.sender = sender
        self.cfg = ctx.config
        # one heavy ingestion at a time: the portfolio watcher, the scanner and the history
        # backfill all share the (rate-limited) RPC, so they take turns instead of contending.
        # ``priority_waiting`` lets the low-priority history loop yield to engine cycles.
        self.ingest_lock = asyncio.Lock()
        self.priority_waiting = 0

    # ------------------------------------------------------------------ #
    async def ensure_token(self, token: str, *, label: str | None, is_portfolio: bool) -> dict[str, Any]:
        token = token.lower()
        row = self.ctx.db.query_one("SELECT * FROM tokens WHERE chain_id=? AND address=?", (self.ctx.chain_id, token))
        ts = now_ts()
        if row is None:
            meta = await erc20.fetch_metadata(self.ctx.rpc, token)
            creation_block = creation_ts = creation_tx = creator = None
            try:
                info = await self.ctx.blockscout.address(token)
                if info:
                    creation_tx = info.get("creation_transaction_hash")
                    creator = (info.get("creator_address_hash") or "").lower() or None
            except (BudgetExhausted, Exception) as exc:  # noqa: BLE001
                log.info("token creation lookup skipped %s: %s", token[:10], exc)
            if creation_tx:
                try:
                    rc = await self.ctx.rpc.get_transaction_receipt(creation_tx)
                    if rc:
                        creation_block = int(rc["blockNumber"], 16)
                        creation_ts = await self.ctx.rpc.block_timestamp(creation_block)
                except Exception as exc:  # noqa: BLE001
                    log.info("creation receipt failed %s: %s", token[:10], exc)
            self.ctx.db.insert("tokens", {
                "chain_id": self.ctx.chain_id, "address": token, "name": meta.get("name"), "symbol": meta.get("symbol") or label, "decimals": meta.get("decimals"),
                "total_supply": str(meta["total_supply"]) if meta.get("total_supply") is not None else None,
                "creator_address": creator, "creation_tx": creation_tx, "creation_block": creation_block, "creation_ts": creation_ts,
                "first_seen_ts": ts, "launchpad": None, "proxy_type": None, "implementation": None, "is_verified": None, "is_portfolio": int(is_portfolio), "raw_json": None, "updated_ts": ts,
            }, ignore=True)
            row = self.ctx.db.query_one("SELECT * FROM tokens WHERE chain_id=? AND address=?", (self.ctx.chain_id, token))
        elif is_portfolio and not row["is_portfolio"]:
            self.ctx.db.execute("UPDATE tokens SET is_portfolio=1, updated_ts=? WHERE chain_id=? AND address=?", (ts, self.ctx.chain_id, token))
        return dict(row)

    async def refresh_supply(self, token: str) -> None:
        ts_raw = await erc20.total_supply(self.ctx.rpc, token)
        if ts_raw is not None:
            self.ctx.db.execute("UPDATE tokens SET total_supply=?, updated_ts=? WHERE chain_id=? AND address=?", (str(ts_raw), now_ts(), self.ctx.chain_id, token))

    # ------------------------------------------------------------------ #
    async def refresh_market(self, token: str) -> dict[str, Any] | None:
        try:
            agg = await snapshot_token_market(self.ctx, token, pricer=self.pricer)
        except Exception as exc:  # noqa: BLE001
            log.warning("market snapshot failed %s: %s", token[:10], exc)
            return None
        quotes = [p["quote_address"] for p in (agg or {}).get("pairs", []) if p.get("quote_address")]
        if quotes:
            try:
                await snapshot_quote_assets(self.ctx, quotes, self.pricer)
            except Exception as exc:  # noqa: BLE001
                log.info("quote snapshot failed: %s", exc)
        for p in (agg or {}).get("pairs", []):
            if p.get("quote_address") and self.pricer.decimals(p["quote_address"]) is None:
                meta = await erc20.fetch_metadata(self.ctx.rpc, p["quote_address"])
                if meta.get("decimals") is not None:
                    self.pricer.set_current(p["quote_address"], None, meta["decimals"])
        return agg

    async def ingest_onchain(self, token: str, agg: dict[str, Any] | None, *, deep: bool, max_blocks: int | None = None) -> dict[str, Any]:
        token = token.lower()
        stats: dict[str, Any] = {}
        pairs = (agg or {}).get("pairs", [])
        # Cover every pool that can carry real volume, not just the deepest few: buys routed
        # through a secondary pool were invisible and biased whale flow / trader PnL
        # (SAYLORMOON, 2026-09-03: 5 of 11 pools tracked).
        min_liq = float(self.cfg.get("liquidity.meaningful_pool_min_liquidity_usd", 5000.0))
        ranked = sorted(pairs, key=lambda p: -(p.get("liquidity_usd") or 0))
        max_pools = int(self.cfg.get("engine.max_pools_per_token", 10))
        top_pairs = [p for p in ranked if (p.get("liquidity_usd") or 0) >= min_liq][:max_pools] or ranked[:3]
        created = {p["pair_id"]: p.get("pair_created_ts") for p in top_pairs}
        pools = await ensure_pools(self.ctx, token, [p["pair_id"] for p in top_pairs], created)
        stats["pools"] = len(pools)
        head = await self.ctx.rpc.block_number()
        max_blocks = max_blocks or int(self.cfg.get("engine.max_blocks_per_cycle", 300_000))
        # bound the work per cycle: continue from cursor up to max_blocks ahead
        cur = self.ctx.db.cursor_get(f"transfers:{token}")
        target = head if cur is None else min(head, int(cur) + max_blocks)
        if cur is None:
            # progressive history: start with a recent window so the token is evaluated within
            # minutes; the history loop then fills creation -> here backwards (see backfill_history)
            trow = self.ctx.db.query_one("SELECT creation_block FROM tokens WHERE chain_id=? AND address=?", (self.ctx.chain_id, token))
            earliest = min([b for b in [(trow["creation_block"] if trow else None)] + [p.created_block for p in pools.values()] if b], default=None)
            lookback = int(self.cfg.get("engine.initial_lookback_blocks", 900_000)) if deep else int(self.cfg.get("scanner.stage3.backfill_blocks", 900_000))
            start = max(earliest or 0, head - lookback)
            target = min(head, start + max_blocks)
            t = await ingest_transfers(self.ctx, token, to_block=target, from_block=start)
        else:
            t = await ingest_transfers(self.ctx, token, to_block=target)
        stats["transfers"] = t.get("transfers", 0)
        stats["ingest_to_block"] = target
        stats["head"] = head
        stats["backlog_blocks"] = head - target
        if pools:
            pe = await ingest_pool_events(self.ctx, token, pools, to_block=target, from_block=(t.get("from_block") if cur is None else None))
            stats["swaps"] = pe.get("swaps", 0)
            trow = self.ctx.db.query_one("SELECT decimals FROM tokens WHERE chain_id=? AND address=?", (self.ctx.chain_id, token))
            dec = int(trow["decimals"] or 18) if trow else 18
            tr = ingest_trades(self.ctx, token, pools, dec, self.pricer, to_block=target)
            stats["trades"] = tr.get("trades", 0)
        ts = now_ts()
        try:
            block_ts = await self.ctx.rpc.block_timestamp(target)
        except Exception:
            block_ts = ts
        snap = snapshot_holders_replay(self.ctx, token, block_number=target, ts=min(ts, block_ts) if stats["backlog_blocks"] > 1000 else ts)
        stats["holders"] = snap["holder_count"]
        # label the top holders lazily (cached Blockscout address lookups, quota-aware)
        try:
            await label_top_holders(self.ctx, token, [a for a, _b, _s, _l, _c in snap["top"][:30]])
        except (BudgetExhausted, Exception) as exc:  # noqa: BLE001
            log.debug("holder labelling skipped: %s", exc)
        return stats

    async def maybe_refresh_holders_blockscout(self, token: str) -> None:
        interval = int(self.cfg.get("engine.holders_blockscout_interval_seconds", 900))
        last = self.ctx.db.scalar("SELECT MAX(ts) FROM holder_count_snapshots WHERE chain_id=? AND token_address=? AND source='blockscout'", (self.ctx.chain_id, token))
        if last is not None and now_ts() - int(last) < interval:
            return
        try:
            await snapshot_holders_blockscout(self.ctx, token)
        except (BudgetExhausted, Exception) as exc:  # noqa: BLE001
            log.info("blockscout holders skipped %s: %s", token[:10], exc)

    async def maybe_refresh_security(self, token: str, pools: dict[str, PoolInfo], *, force: bool = False) -> None:
        interval = int(self.cfg.get("engine.security_interval_seconds", 6 * 3600))
        last = self.ctx.db.scalar("SELECT MAX(ts) FROM contract_security WHERE chain_id=? AND token_address=?", (self.ctx.chain_id, token))
        if not force and last is not None and now_ts() - int(last) < interval:
            return
        trow = self.ctx.db.query_one("SELECT total_supply FROM tokens WHERE chain_id=? AND address=?", (self.ctx.chain_id, token))
        supply = int(trow["total_supply"]) if trow and trow["total_supply"] else None
        top = self.ctx.db.query_one("SELECT address FROM holders WHERE chain_id=? AND token_address=? AND is_system=0 AND COALESCE(is_contract,0)=0 ORDER BY CAST(balance AS REAL) DESC LIMIT 1", (self.ctx.chain_id, token))
        try:
            await run_security_checks(self.ctx, token, pools, top_holder=top["address"] if top else None, total_supply=supply)
        except Exception as exc:  # noqa: BLE001
            log.warning("security checks failed %s: %s", token[:10], exc)

    # ------------------------------------------------------------------ #
    async def evaluate(self, token: str, label: str, *, is_portfolio: bool, deep: bool = True, as_of_ts: int | None = None, pools: dict[str, PoolInfo] | None = None, dex_pairs_norm: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        token = token.lower()
        as_of = as_of_ts or now_ts()
        m = await build_token_metrics(self.ctx, token, as_of, pricer=self.pricer, live=as_of_ts is None, pools=pools, deep=deep, dex_pairs_norm=dex_pairs_norm)
        m["_is_portfolio"] = is_portfolio
        from intel.metrics.regime import cached_regime  # recorded only, gates nothing

        m["market_regime"] = cached_regime(self.ctx)
        hf = apply_hard_filters(m, self.cfg.section("hard_filters"))
        scores = compute_scores(m, self.cfg.section("scoring"), hf)
        prev = self.ctx.db.query_one("SELECT state, since_ts, moonshot FROM token_states WHERE chain_id=? AND token_address=?", (self.ctx.chain_id, token))
        prev_state = prev["state"] if prev else None
        prev_since = int(prev["since_ts"]) if prev else None
        prev_score_row = self.ctx.db.query_one("SELECT moonshot, hard_filter_pass FROM token_scores WHERE chain_id=? AND token_address=? AND ts<? ORDER BY ts DESC LIMIT 1", (self.ctx.chain_id, token, as_of + 1))
        prev_moonshot = float(prev_score_row["moonshot"]) if prev_score_row and prev_score_row["moonshot"] is not None else None
        prev_hard_pass = bool(prev_score_row["hard_filter_pass"]) if prev_score_row and prev_score_row["hard_filter_pass"] is not None else None
        threshold = float(self.cfg.get("scanner.moonshot_alert_threshold", 70))
        decision = decide_state(m, scores, hf, self.cfg.section("states"), prev_state=prev_state, prev_since_ts=prev_since, is_portfolio=is_portfolio, moonshot_threshold=threshold)
        score_id = self._persist_score(token, m, scores, hf, decision, prev_state, as_of)
        self._persist_state(token, decision, scores, prev_state, prev_since, as_of, score_id)
        result = {"token": token, "label": label, "metrics": m, "scores": scores, "hard_filters": hf, "decision": decision, "prev_state": prev_state, "prev_moonshot": prev_moonshot, "score_id": score_id}
        if as_of_ts is None:  # alerts / decisions only for live evaluations
            mode = str(self.cfg.get("decisions.telegram_mode", "decisions"))
            cands = evaluate_alerts(token=token, label=label, m=m, scores=scores, decision=decision, prev_state=prev_state, prev_moonshot=prev_moonshot, prev_hard_pass=prev_hard_pass, hard_pass=hf.passed, is_portfolio=is_portfolio, cfg=self.cfg.section("alerts"), moonshot_threshold=threshold)
            result["alerts"] = await self.dispatch_alerts(cands, m, scores, decision, prev_state, prev_moonshot, send=mode in ("alerts", "both"))
            if mode in ("decisions", "both"):
                from intel.engines.decisions import dispatch_decisions, evaluate_decisions

                cfg_pos = next((p for p in self.cfg.portfolio_positions if p["address"] == token), None) if is_portfolio else None
                decs = evaluate_decisions(self.ctx, token=token, label=label, m=m, scores=scores, decision=decision, is_portfolio=is_portfolio, cfg_position=cfg_pos)
                result["decisions"] = {"made": len(decs), "sent": await dispatch_decisions(self.ctx, self.sender, decs) if decs else 0, "kinds": [d["kind"] for d in decs]}
        return result

    def _persist_score(self, token: str, m: dict[str, Any], scores: Scores, hf: Any, decision: StateDecision, prev_state: str | None, as_of: int) -> int | None:
        slim = {k: v for k, v in m.items() if k not in ("whale_wallets",)}
        return self.ctx.db.insert("token_scores", {
            "ts": now_ts(), "chain_id": self.ctx.chain_id, "token_address": token, "model_version": MODEL_VERSION, "as_of_ts": as_of, "block_number": None,
            "survival": scores.survival, "traction": scores.traction, "asymmetry": scores.asymmetry, "distribution": scores.distribution, "organic_volume": scores.organic_volume,
            "smart_money": scores.smart_money, "rug_risk": scores.rug_risk, "narrative": scores.narrative, "moonshot": scores.moonshot,
            "hard_filter_pass": int(hf.passed), "hard_filter_reasons": json.dumps(hf.as_dict()), "state": decision.state, "prev_state": prev_state, "action": decision.action,
            "metrics_json": json.dumps(slim, default=str), "explain_json": json.dumps(scores.explain, default=str), "quality_flags": json.dumps(m.get("quality_flags", [])),
        })

    def _persist_state(self, token: str, decision: StateDecision, scores: Scores, prev_state: str | None, prev_since: int | None, as_of: int, score_id: int | None) -> None:
        changed = prev_state != decision.state
        since = as_of if changed or prev_since is None else prev_since
        with self.ctx.db.transaction():
            self.ctx.db.execute(
                "INSERT INTO token_states(chain_id, token_address, state, since_ts, last_eval_ts, moonshot, action, reason) VALUES (?,?,?,?,?,?,?,?) "
                "ON CONFLICT(chain_id, token_address) DO UPDATE SET state=excluded.state, since_ts=excluded.since_ts, last_eval_ts=excluded.last_eval_ts, moonshot=excluded.moonshot, action=excluded.action, reason=excluded.reason",
                (self.ctx.chain_id, token, decision.state, since, as_of, scores.moonshot, decision.action, decision.reason),
            )
            if changed:
                self.ctx.db.insert("state_transitions", {"ts": as_of, "chain_id": self.ctx.chain_id, "token_address": token, "from_state": prev_state, "to_state": decision.state, "reason": decision.reason, "score_id": score_id, "model_version": MODEL_VERSION})

    async def dispatch_alerts(self, cands: list[AlertCandidate], m: dict[str, Any], scores: Scores, decision: StateDecision, prev_state: str | None, prev_moonshot: float | None, *, send: bool = True) -> dict[str, int]:
        """Persist every alert (audit trail, scorecard); send to Telegram only when ``send``."""
        if not cands or not self.cfg.get("alerts.enabled", True):
            return {"sent": 0, "suppressed": len(cands)}
        to_send, suppressed = self.deduper.select(cands)
        for c, reason in suppressed:
            self.deduper.record(c, sent=False, suppressed_reason=reason)
        sent = 0
        url = f"https://dexscreener.com/{self.ctx.settings.dexscreener_chain}/{m['token']}"
        for c in to_send:
            body = format_alert(c, m, scores, decision, prev_state=prev_state, prev_moonshot=prev_moonshot, token_url=url, is_portfolio=bool(m.get("_is_portfolio")))
            if not send:
                # decisions mode: keep the alert as a "would have sent" record for the scorecard
                self.deduper.record(c, sent=True, suppressed_reason=None, body=body, message_id="not-sent:decisions-mode")
                continue
            ok, mid, err = (await self.sender.send(body)) if self.sender else (False, None, "no sender")
            self.deduper.record(c, sent=ok, suppressed_reason=None if ok else "send failed", body=body, message_id=mid, error=err)
            sent += int(ok)
        return {"sent": sent, "suppressed": len(suppressed)}

    # ------------------------------------------------------------------ #
    async def backfill_history(self, token: str, *, max_blocks: int | None = None) -> dict[str, Any]:
        """Complete launch-to-date history: backward transfers, balance rebuild, pool events and
        trades for the earlier range (forward cursors untouched). Bounded by ``max_blocks``."""
        from intel.ingest.transfers import backfill_backward
        from intel.metrics.launch import launch_history_complete

        token = token.lower()
        if launch_history_complete(self.ctx, token):
            return {"status": "complete"}
        first_before = self.ctx.db.scalar("SELECT MIN(block_number) FROM transfers WHERE chain_id=? AND token_address=?", (self.ctx.chain_id, token))
        async with self.ingest_lock:
            res = await backfill_backward(self.ctx, token, max_blocks=max_blocks)
        if res.get("status") != "filled":
            return res
        pools = load_pools(self.ctx, token)
        if pools and first_before is not None:
            async with self.ingest_lock:
                pe = await ingest_pool_events(self.ctx, token, pools, to_block=int(first_before) - 1, from_block=int(res["from_block"]), update_cursor=False)
            res["swaps"] = pe.get("swaps", 0)
            trow = self.ctx.db.query_one("SELECT decimals FROM tokens WHERE chain_id=? AND address=?", (self.ctx.chain_id, token))
            dec = int(trow["decimals"] or 18) if trow else 18
            tr = ingest_trades(self.ctx, token, pools, dec, self.pricer, to_block=int(first_before) - 1, from_block=int(res["from_block"]), update_cursor=False)
            res["trades"] = tr.get("trades", 0)
        return res

    def tokens_needing_history(self, limit: int = 5) -> list[str]:
        """Portfolio tokens first, then active scanner tokens, whose launch history is incomplete."""
        from intel.metrics.launch import launch_history_complete

        rows = self.ctx.db.query(
            "SELECT t.address, t.is_portfolio FROM tokens t LEFT JOIN scanner_candidates c ON c.chain_id=t.chain_id AND c.token_address=t.address "
            "WHERE t.chain_id=? AND (t.is_portfolio=1 OR (c.status='ACTIVE' AND c.stage_reached>=3)) ORDER BY t.is_portfolio DESC, t.first_seen_ts",
            (self.ctx.chain_id,),
        )
        out = []
        for r in rows:
            if self.ctx.db.scalar("SELECT COUNT(*) FROM transfers WHERE chain_id=? AND token_address=?", (self.ctx.chain_id, r["address"]), 0) == 0:
                continue  # nothing ingested yet: the engine's own cycle goes first
            if not launch_history_complete(self.ctx, r["address"]):
                out.append(r["address"])
            if len(out) >= limit:
                break
        return out

    async def process(self, token: str, label: str, *, is_portfolio: bool, deep: bool = True, force_security: bool = False, max_blocks: int | None = None) -> dict[str, Any]:
        token = token.lower()
        t0 = time.monotonic()
        # strict priority: portfolio tokens announce themselves *before* any network work so the
        # scanner yields immediately; scanner tokens wait while a portfolio evaluation is pending
        if is_portfolio:
            self.priority_waiting += 1
        else:
            while self.priority_waiting > 0:
                await asyncio.sleep(2)
        try:
            row = await self.ensure_token(token, label=label, is_portfolio=is_portfolio)
            if not label or label.lower().startswith("0x"):
                label = row.get("symbol") or label or token[:10]
            async with self.ingest_lock:
                if is_portfolio:
                    self.priority_waiting -= 1
                agg = await self.refresh_market(token)
                stats = await self.ingest_onchain(token, agg, deep=deep, max_blocks=max_blocks)
                pools = load_pools(self.ctx, token)
                if deep:
                    await self.refresh_supply(token)
                    await self.maybe_refresh_holders_blockscout(token)
                    await self.maybe_refresh_security(token, pools, force=force_security or self.ctx.db.scalar("SELECT COUNT(*) FROM contract_security WHERE chain_id=? AND token_address=?", (self.ctx.chain_id, token), 0) == 0)
        except BaseException:
            if is_portfolio and not self.ingest_lock.locked():
                self.priority_waiting = max(0, self.priority_waiting - 1)  # cancelled while waiting
            raise
        res = await self.evaluate(token, label, is_portfolio=is_portfolio, deep=deep, pools=pools, dex_pairs_norm=(agg or {}).get("pairs"))
        res["ingest"] = stats
        res["elapsed_s"] = round(time.monotonic() - t0, 1)
        d = res["decision"]
        log.info("processed %s (%s) state=%s action=%s moonshot=%.0f hf=%s alerts=%s ingest=%s %.1fs", label, token[:10], d.state, d.action, res["scores"].moonshot, res["hard_filters"].passed, res.get("alerts"), stats, res["elapsed_s"])
        return res
