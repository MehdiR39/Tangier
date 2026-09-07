"""Market moonshot scanner: discovery → stage 1 (cheap) → stage 2 → stage 3 (expensive)."""
from __future__ import annotations

import json
import time
import logging
from typing import Any

from intel.chain.constants import TOPIC_AIRLOCK_CREATE, TOPIC_V4_INITIALIZE, TOPIC_V4_SWAP
from intel.chain.doppler import decode_airlock_create
from intel.chain.uniswap_v4 import decode_initialize, decode_swap
from intel.engines.pipeline import TokenPipeline
from intel.ingest.holders import snapshot_holders_blockscout
from intel.ingest.market import aggregate_pairs, snapshot_token_market
from intel.providers.base import BudgetExhausted
from intel.providers.dexscreener import normalize_pair
from intel.utils.timeutil import now_ts

log = logging.getLogger(__name__)
STABLE_SYMBOLS = {"USDG", "USDC", "USDT", "DAI", "WETH", "ETH"}


class Scanner:
    def __init__(self, pipeline: TokenPipeline) -> None:
        self.p = pipeline
        self.ctx = pipeline.ctx
        self.cfg = pipeline.ctx.config.section("scanner")
        self._promoted: list[str] = []   # stage-2 survivors waiting for the deep pass
        self._hot: dict[str, float] = {}  # USD traded per token in the last sweep

    # ---- discovery ------------------------------------------------------- #
    def _is_quote(self, address: str) -> bool:
        return address.lower() in self.ctx.config.quote_assets

    def _is_excluded_name(self, name: str | None, symbol: str | None = None) -> bool:
        pats = [str(p).lower() for p in self.cfg.get("exclude_name_patterns", ["robinhood token"])]
        n = (name or "").lower()
        return any(p in n for p in pats)

    def _record_candidate(self, token: str, pair_id: str | None, source: str, block: int | None = None, meta: dict[str, Any] | None = None) -> bool:
        token = token.lower()
        if self._is_quote(token) or self.ctx.is_system(token):
            return False
        known = self.ctx.db.query_one("SELECT name FROM tokens WHERE chain_id=? AND address=?", (self.ctx.chain_id, token))
        if known and self._is_excluded_name(known["name"]):
            return False
        ts = now_ts()
        row = self.ctx.db.query_one("SELECT status FROM scanner_candidates WHERE chain_id=? AND token_address=?", (self.ctx.chain_id, token))
        if row is None:
            self.ctx.db.execute(
                "INSERT INTO scanner_candidates(chain_id, token_address, first_seen_ts, last_seen_ts, discovery_source, pair_id, stage_reached, status, next_eval_ts) VALUES (?,?,?,?,?,?,0,'NEW',?)",
                (self.ctx.chain_id, token, ts, ts, source, pair_id, ts),
            )
            self.ctx.db.insert("discovery_events", {"ts": ts, "chain_id": self.ctx.chain_id, "token_address": token, "pair_id": pair_id, "source": source, "block_number": block, "stage": 0, "passed": 1, "reason": "discovered", "metrics_json": json.dumps(meta or {}, default=str)})
            return True
        self.ctx.db.execute("UPDATE scanner_candidates SET last_seen_ts=? WHERE chain_id=? AND token_address=?", (ts, self.ctx.chain_id, token))
        return False

    async def discover_onchain(self) -> dict[str, int]:
        head = await self.ctx.rpc.block_number()
        lookback = int(self.cfg.get("discovery_lookback_blocks", 100_000))
        found = {"initialize": 0, "airlock": 0}
        sources = set(self.cfg.get("discovery_sources", []))
        if "poolmanager_initialize" in sources:
            cur = self.ctx.db.cursor_get("scanner:initialize")
            start = head - lookback if cur is None else int(cur) + 1
            async for a, b, logs in self.ctx.rpc.iter_logs(address=self.ctx.pool_manager, topics=[TOPIC_V4_INITIALIZE], from_block=start, to_block=head, chunk=25_000):
                for lg in logs:
                    try:
                        init = decode_initialize(lg)
                    except Exception:
                        continue
                    c0, c1 = init.currency0, init.currency1
                    token = c1 if self._is_quote(c0) else c0 if self._is_quote(c1) else None
                    if token is None:
                        continue
                    if self._record_candidate(token, init.pool_id, "poolmanager_initialize", init.block_number, {"hooks": init.hooks, "fee": init.fee}):
                        found["initialize"] += 1
                    # store the pool key immediately (ground truth) so stage 3 needs no lookup
                    from intel.ingest.pools import store_pool_init  # local import to avoid cycle at module load

                    store_pool_init(self.ctx, token, init, None, "rpc_discovery")
                self.ctx.db.cursor_set("scanner:initialize", b, now_ts())
        if "airlock_create" in sources:
            cur = self.ctx.db.cursor_get("scanner:airlock")
            start = head - lookback if cur is None else int(cur) + 1
            async for a, b, logs in self.ctx.rpc.iter_logs(address=self.ctx.airlock, topics=[TOPIC_AIRLOCK_CREATE], from_block=start, to_block=head, chunk=50_000):
                for lg in logs:
                    ev = decode_airlock_create(lg)
                    if ev and self._record_candidate(ev["asset"], None, "airlock_create", ev["block_number"], {"numeraire": ev["numeraire"], "initializer": ev["initializer"]}):
                        found["airlock"] += 1
                        self.ctx.db.execute("UPDATE tokens SET launchpad='doppler' WHERE chain_id=? AND address=?", (self.ctx.chain_id, ev["asset"].lower()))
                self.ctx.db.cursor_set("scanner:airlock", b, now_ts())
        return found

    async def discover_dexscreener(self) -> dict[str, int]:
        found = {"profiles": 0, "boosts": 0, "search": 0}
        sources = set(self.cfg.get("discovery_sources", []))
        try:
            if "dexscreener_profiles" in sources:
                for p in await self.ctx.dex.token_profiles_latest():
                    if p.get("tokenAddress") and self._record_candidate(p["tokenAddress"], None, "dexscreener_profiles", None, {"url": p.get("url")}):
                        found["profiles"] += 1
            if "dexscreener_boosts" in sources:
                for p in await self.ctx.dex.token_boosts_latest():
                    if p.get("tokenAddress") and self._record_candidate(p["tokenAddress"], None, "dexscreener_boosts", None, {"amount": p.get("amount"), "totalAmount": p.get("totalAmount")}):
                        found["boosts"] += 1
            if "dexscreener_search" in sources:
                for q in self.cfg.get("search_queries", []):
                    for pair in await self.ctx.dex.search(q):
                        np = normalize_pair(pair)
                        if np["base_address"] and self._record_candidate(np["base_address"], np["pair_id"], "dexscreener_search", None, {"query": q, "created_ts": np["pair_created_ts"]}):
                            found["search"] += 1
        except Exception as exc:  # noqa: BLE001
            log.warning("dexscreener discovery error: %s", exc)
        return found

    # ---- activity sweep --------------------------------------------------- #
    async def hot_tokens(self, span_blocks: int | None = None) -> dict[str, float]:
        """USD traded per token over the last window, from one chain-wide Swap sweep.

        Polling a provider about every discovered token wastes the whole budget on pools that never
        traded: most launches die without a single swap. One ``eth_getLogs`` over the PoolManager
        returns every swap on the chain — measured 2026-09-03: 42 145 swaps across 1 829 pools in
        20 s for 5 000 blocks — so the queue can be ordered by what is actually changing hands.
        """
        span = int(span_blocks or self.cfg.get("hot_sweep_blocks", 5_000))
        head = await self.ctx.rpc.block_number()
        cur = self.ctx.db.cursor_get("scanner:hot")
        start = max(head - span, int(cur) + 1 if cur is not None else head - span)
        if start > head:
            return {}
        # Read the quote leg from the pool's own currencies. The stored token_is_currency0 flag is
        # wrong on some rows, which made the token amount (18 decimals) count as a USDG amount
        # (6 decimals) and inflated a token's volume by 12 orders of magnitude.
        pools = {r["pair_id"]: dict(r) for r in self.ctx.db.query(
            "SELECT pair_id, token_address, quote_address, currency0 FROM pairs "
            "WHERE chain_id=? AND quote_address IS NOT NULL AND currency0 IS NOT NULL", (self.ctx.chain_id,))}
        vol_quote: dict[str, dict[str, float]] = {}
        async for _a, b, logs in self.ctx.rpc.iter_logs(address=self.ctx.pool_manager, topics=[TOPIC_V4_SWAP], from_block=start, to_block=head, chunk=span):
            for lg in logs:
                try:
                    ev = decode_swap(lg)
                except Exception:
                    continue
                p = pools.get(ev.pool_id)
                if p is None:
                    continue  # pool we have not resolved yet; the Initialize sweep will add it
                quote_is_c0 = (p["currency0"] or "").lower() == (p["quote_address"] or "").lower()
                raw = abs(ev.amount0 if quote_is_c0 else ev.amount1)
                vol_quote.setdefault(p["token_address"], {}).setdefault(p["quote_address"], 0.0)
                vol_quote[p["token_address"]][p["quote_address"]] += raw
            self.ctx.db.cursor_set("scanner:hot", b, now_ts())
        out: dict[str, float] = {}
        for token, per_quote in vol_quote.items():
            usd = 0.0
            for quote, raw in per_quote.items():
                dec = self.p.pricer.decimals(quote)
                price, _flags = self.p.pricer.usd_price(quote)
                if dec is None or not price:
                    continue
                usd += raw / (10 ** dec) * price
            if usd > 0:
                out[token] = usd
        return out

    # ---- stage 1 --------------------------------------------------------- #
    def _due_candidates(self, statuses: tuple[str, ...], limit: int, *, order: str = "stage_reached DESC, last_seen_ts DESC") -> list[str]:
        rows = self.ctx.db.query(
            f"SELECT token_address FROM scanner_candidates WHERE chain_id=? AND status IN ({','.join('?' for _ in statuses)}) "
            f"AND (next_eval_ts IS NULL OR next_eval_ts<=?) ORDER BY {order} LIMIT ?",
            (self.ctx.chain_id, *statuses, now_ts(), limit),
        )
        return [r["token_address"] for r in rows]

    def _set_candidate(self, token: str, *, status: str | None = None, stage: int | None = None, reason: str | None = None, next_eval: int | None = None) -> None:
        sets = ["last_stage_ts=?"]
        params: list[Any] = [now_ts()]
        if status:
            sets.append("status=?")
            params.append(status)
        if stage is not None:
            sets.append("stage_reached=MAX(stage_reached, ?)")
            params.append(stage)
        if reason is not None:
            sets.append("reject_reason=?")
            params.append(reason)
        if next_eval is not None:
            sets.append("next_eval_ts=?")
            params.append(next_eval)
        params += [self.ctx.chain_id, token]
        self.ctx.db.execute(f"UPDATE scanner_candidates SET {', '.join(sets)} WHERE chain_id=? AND token_address=?", params)

    def _event(self, token: str, stage: int, passed: bool, reason: str, metrics: dict[str, Any], pair_id: str | None = None) -> None:
        self.ctx.db.insert("discovery_events", {"ts": now_ts(), "chain_id": self.ctx.chain_id, "token_address": token, "pair_id": pair_id, "source": "scanner", "block_number": None, "stage": stage, "passed": int(passed), "reason": reason, "metrics_json": json.dumps(metrics, default=str)})

    async def stage1(self) -> dict[str, Any]:
        s1 = self.cfg.get("stage1", {})
        # Never-evaluated tokens get a guaranteed share of every batch, newest first. Ordering the
        # whole queue by stage_reached DESC starved them: on 2026-09-03 MICRON AI sat NEW for 9h44
        # without a single evaluation while it did x27, because thousands of already-staged
        # candidates came back due before the queue ever reached the new ones.
        budget = int(s1.get("max_candidates", 60)) * 2
        # Whatever traded most in the last window goes first: it is the one signal that costs
        # nothing per token and is never stale.
        hot = sorted(self._hot.items(), key=lambda kv: -kv[1])
        hot_budget = max(0, int(budget * float(s1.get("hot_share", 0.4))))
        hot_due = set(self._due_candidates(("NEW", "DORMANT", "ACTIVE"), budget * 4))
        hot_tokens = [t for t, _v in hot if t in hot_due][:hot_budget]
        fresh_budget = max(1, int((budget - len(hot_tokens)) * float(s1.get("fresh_share", 0.5))))
        # Two lanes so neither end of the queue starves: newest first catches a launch while it is
        # still moving, oldest first guarantees every discovery is eventually looked at. With only
        # the newest lane, a token discovered this morning stays buried under the thousands of
        # pools created since — which is how MICRON AI went unseen for 9h44 while doing x27.
        newest = self._due_candidates(("NEW",), max(1, fresh_budget // 2), order="first_seen_ts DESC")
        oldest = self._due_candidates(("NEW",), max(1, fresh_budget // 2), order="first_seen_ts ASC")
        fresh = list(dict.fromkeys(newest + oldest))
        rest = self._due_candidates(("NEW", "DORMANT", "ACTIVE"), max(0, budget - len(hot_tokens) - len(fresh)))
        due = list(dict.fromkeys(hot_tokens + fresh + rest))
        tracked = [r["token_address"] for r in self.ctx.db.query(
            "SELECT DISTINCT s.token_address FROM token_snapshots s WHERE s.chain_id=? AND s.liquidity_usd>=? AND s.ts>? "
            "AND s.token_address NOT IN (SELECT token_address FROM token_snapshots WHERE chain_id=? AND ts>?) LIMIT 40",
            (self.ctx.chain_id, float(s1.get("min_liquidity_usd", 20000.0)), now_ts() - 3 * 86400, self.ctx.chain_id, now_ts() - 1800),
        )]
        due = list(dict.fromkeys(due + tracked))
        if not due:
            return {"evaluated": 0, "passed": 0}
        pairs = await self.ctx.dex.tokens(due)
        by_token: dict[str, list[dict[str, Any]]] = {}
        for p in pairs:
            np = normalize_pair(p)
            by_token.setdefault(np["base_address"], []).append(np)
        raw_by_token: dict[str, list[dict[str, Any]]] = {}
        for p in pairs:
            raw_by_token.setdefault(str((p.get("baseToken") or {}).get("address", "")).lower(), []).append(p)
        now = now_ts()
        rescan = int(self.cfg.get("rescan_interval_seconds", 600))
        passed: list[str] = []
        min_liq = float(s1.get("min_liquidity_usd", 20000.0))
        for token in due:
            norm = by_token.get(token, [])
            if not norm:
                self._set_candidate(token, status="DORMANT", reason="no dexscreener pair", next_eval=now + 6 * rescan)
                self._event(token, 1, False, "no dexscreener pair", {})
                continue
            # tokenised stocks / ETFs (Robinhood Token) are quote assets, not moonshot candidates
            base_name = next((p.get("base_name") for p in norm if p.get("base_name")), None)
            if self._is_excluded_name(base_name):
                self._set_candidate(token, status="REJECTED", reason="tokenised stock (Robinhood Token) — not a candidate", next_eval=now + 30 * 86400)
                self._event(token, 1, False, "tokenised stock", {"name": base_name})
                if token not in self.ctx.config.data["quote_assets"]:
                    self.ctx.config.data["quote_assets"][token] = {"symbol": norm[0].get("base_symbol"), "kind": "stock", "decimals": None}
                continue
            agg = aggregate_pairs(norm, float(self.ctx.config.get("liquidity.meaningful_pool_min_liquidity_usd", 5000.0)))
            created = agg.get("pair_created_ts")
            age_h = ((now - created) / 3600.0) if created else None
            reasons: list[str] = []
            if age_h is not None and age_h > float(s1.get("max_age_hours", 336)):
                reasons.append(f"age {age_h:.0f}h > max")
            if age_h is not None and age_h * 60 < float(s1.get("min_age_minutes", 10)):
                reasons.append("too new")
            if agg.get("liquidity_usd") is None:
                reasons.append("liquidity unknown")
            elif agg["liquidity_usd"] < min_liq:
                reasons.append(f"liquidity {agg['liquidity_usd']:,.0f} < {min_liq:,.0f}")
            mc = agg.get("market_cap") or agg.get("fdv")
            if mc is None:
                reasons.append("market cap unknown")
            else:
                if mc > float(s1.get("max_market_cap_usd", 5_000_000)):
                    reasons.append(f"mc {mc:,.0f} > max")
                if mc < float(s1.get("min_market_cap_usd", 20000)):
                    reasons.append(f"mc {mc:,.0f} < min")
            if (agg.get("volume_24h") or 0) < float(s1.get("min_volume_24h_usd", 5000)):
                reasons.append(f"vol24h {agg.get('volume_24h') or 0:,.0f} < min")
            metrics = {"age_h": age_h, "liquidity_usd": agg.get("liquidity_usd"), "market_cap": mc, "volume_24h": agg.get("volume_24h"), "price_usd": agg.get("price_usd")}
            if reasons:
                # Keep pricing tokens that were tradeable at some point, even when they now fail
                # the filters: otherwise a collapse is never observed (the token just vanishes
                # from the data) and every measured return is biased upward by survivorship.
                # Found on 2026-09-03 while measuring returns; the quote is already in hand.
                if self.ctx.db.query_one(
                    "SELECT 1 FROM token_snapshots WHERE chain_id=? AND token_address=? AND liquidity_usd>=? LIMIT 1",
                    (self.ctx.chain_id, token, min_liq),
                ) is not None:
                    await snapshot_token_market(self.ctx, token, pricer=self.p.pricer, pairs_raw=raw_by_token.get(token, []))
                # only "too old" is permanent here; thin liquidity / small cap can change fast
                hard_dead = any(r.startswith("age") for r in reasons)
                self._set_candidate(token, status="REJECTED" if hard_dead else "DORMANT", reason="; ".join(reasons), next_eval=now + (rescan * 12 if hard_dead else rescan))
                self._event(token, 1, False, "; ".join(reasons), metrics, agg.get("primary_pair"))
                continue
            # persist market snapshot for history (no extra API call: reuse batch result)
            await snapshot_token_market(self.ctx, token, pricer=self.p.pricer, pairs_raw=raw_by_token.get(token, []))
            self._set_candidate(token, status="ACTIVE", stage=1, reason=None, next_eval=now + rescan)
            self._event(token, 1, True, "stage1 pass", metrics, agg.get("primary_pair"))
            passed.append(token)
        return {"evaluated": len(due), "passed": len(passed), "tokens": passed}

    # ---- stage 2 --------------------------------------------------------- #
    async def stage2(self, tokens: list[str]) -> dict[str, Any]:
        s2 = self.cfg.get("stage2", {})
        passed: list[str] = []
        for token in tokens[: int(s2.get("max_candidates", 25))]:
            snap = self.ctx.db.query_one("SELECT holder_count FROM holder_count_snapshots WHERE chain_id=? AND token_address=? ORDER BY ts DESC LIMIT 1", (self.ctx.chain_id, token))
            holders = int(snap["holder_count"]) if snap and snap["holder_count"] is not None else None
            top10 = None
            if holders is None or self.ctx.db.scalar("SELECT COUNT(*) FROM holder_snapshots WHERE chain_id=? AND token_address=?", (self.ctx.chain_id, token), 0) == 0:
                try:
                    hs = await snapshot_holders_blockscout(self.ctx, token, pages=1)
                    holders = hs.get("holder_count", holders)
                    trow = self.ctx.db.query_one("SELECT total_supply FROM tokens WHERE chain_id=? AND address=?", (self.ctx.chain_id, token))
                    supply = int(trow["total_supply"]) if trow and trow["total_supply"] else None
                    econ = [h for h in hs.get("top", []) if not h.get("label") and not h.get("is_contract")]
                    if supply and econ:
                        excluded = sum(h["balance"] for h in hs.get("top", []) if h.get("label") or h.get("is_contract"))
                        top10 = sum(h["balance"] for h in econ[:10]) / max(1, supply - excluded)
                except (BudgetExhausted, Exception) as exc:  # noqa: BLE001
                    log.info("stage2 holders unavailable %s: %s", token[:10], exc)
            pr = self.ctx.db.query_one("SELECT buys_24h, sells_24h FROM pair_snapshots WHERE chain_id=? AND token_address=? ORDER BY ts DESC, liquidity_usd DESC LIMIT 1", (self.ctx.chain_id, token))
            buys = int(pr["buys_24h"] or 0) if pr else 0
            reasons: list[str] = []
            if holders is not None and holders < int(s2.get("min_holders", 50)):
                reasons.append(f"holders {holders} < min")
            if top10 is not None and top10 > float(s2.get("max_top10_pct", 0.6)):
                reasons.append(f"top10 {top10:.0%} > max (explorer top page, pre-cluster)")
            if buys < 20:
                reasons.append(f"buys24h {buys} < 20")
            metrics = {"holders": holders, "top10_pct_explorer": top10, "buys_24h": buys}
            if reasons:
                self._set_candidate(token, status="DORMANT", reason="; ".join(reasons), next_eval=now_ts() + int(self.cfg.get("rescan_interval_seconds", 600)) * 3)
                self._event(token, 2, False, "; ".join(reasons), metrics)
                continue
            self._set_candidate(token, stage=2)
            self._event(token, 2, True, "stage2 pass" + (" (holders unknown: deferred to on-chain replay)" if holders is None else ""), metrics)
            passed.append(token)
        return {"evaluated": len(tokens), "passed": len(passed), "tokens": passed}

    # ---- stage 3 --------------------------------------------------------- #
    def _momentum_queue(self, limit: int) -> list[str]:
        """Candidates awaiting (or deserving) a deep analysis, ranked by price momentum.

        Includes tokens never scored (stage 2) and those parked as DORMANT after a temporary
        rejection: their liquidity or concentration may have improved since.

        Without this, the stage-3 queue was monopolised by already-scored tokens: on
        2026-09-03 a token discovered at $166k market cap passed stage 1 one hundred times
        and reached ×7 without ever being analysed (128 candidates stuck at stage 2).
        """
        rows = self.ctx.db.query(
            "SELECT c.token_address, "
            " (SELECT price_usd FROM token_snapshots s WHERE s.chain_id=c.chain_id AND s.token_address=c.token_address AND s.price_usd IS NOT NULL ORDER BY s.ts DESC LIMIT 1) AS px_now, "
            " (SELECT price_usd FROM token_snapshots s WHERE s.chain_id=c.chain_id AND s.token_address=c.token_address AND s.price_usd IS NOT NULL AND s.ts>? ORDER BY s.ts ASC LIMIT 1) AS px_ref, "
            " (SELECT liquidity_usd FROM token_snapshots s WHERE s.chain_id=c.chain_id AND s.token_address=c.token_address AND s.liquidity_usd IS NOT NULL ORDER BY s.ts DESC LIMIT 1) AS liq "
            "FROM scanner_candidates c WHERE c.chain_id=? AND ((c.status='ACTIVE' AND c.stage_reached=2) "
            "  OR (c.status='DORMANT' AND (c.next_eval_ts IS NULL OR c.next_eval_ts<=?)))",
            (now_ts() - 6 * 3600, self.ctx.chain_id, now_ts()),
        )
        scored = []
        for r in rows:
            if not r["px_now"] or not r["px_ref"]:
                continue
            momentum = r["px_now"] / r["px_ref"]
            scored.append((momentum * (1.0 if (r["liq"] or 0) >= 20000 else 0.5), r["token_address"]))
        scored.sort(reverse=True)
        return [t for _m, t in scored[:limit]]

    async def stage3(self, tokens: list[str]) -> dict[str, Any]:
        s3 = self.cfg.get("stage3", {})
        cap = int(s3.get("max_candidates_per_cycle", 5))
        refresh_cap = int(s3.get("refresh_per_cycle", 2))
        # 1) tokens that just passed stage 2 in this cycle, 2) never-scored candidates with the
        # strongest momentum, 3) a couple of already-scored ones to keep their state fresh
        refresh = [r["token_address"] for r in self.ctx.db.query(
            "SELECT c.token_address FROM scanner_candidates c LEFT JOIN token_states s ON s.chain_id=c.chain_id AND s.token_address=c.token_address "
            "WHERE c.chain_id=? AND c.status='ACTIVE' AND c.stage_reached>=3 ORDER BY COALESCE(s.moonshot,0) DESC, COALESCE(s.last_eval_ts,0) ASC LIMIT ?",
            (self.ctx.chain_id, refresh_cap))]
        # What is trading right now goes first. Measured 2026-09-03: 19.5 h median between a
        # token's birth and its first score, on an asset class where the whole move lasts hours.
        hot_first = [t for t, _v in sorted(self._hot.items(), key=lambda kv: -kv[1])
                     if self.ctx.db.query_one("SELECT 1 FROM scanner_candidates WHERE chain_id=? AND token_address=? AND status IN ('NEW','ACTIVE') AND stage_reached<3", (self.ctx.chain_id, t))]
        fresh = list(dict.fromkeys(list(tokens) + hot_first + self._momentum_queue(cap)))[:cap]
        queue = list(dict.fromkeys(fresh + refresh))
        results = []
        alerts = 0
        budget_s = float(s3.get("cycle_budget_seconds", 240))
        t_start = time.monotonic()
        skipped = 0
        for token in queue:
            # One token with a huge backlog must never eat the whole cycle: the rest of the queue
            # would then wait a full cycle for nothing.
            if time.monotonic() - t_start > budget_s:
                skipped = len(queue) - len(results)
                break
            label = self.ctx.db.scalar("SELECT symbol FROM tokens WHERE chain_id=? AND address=?", (self.ctx.chain_id, token)) or token[:10]
            try:
                # Bound the on-chain catch-up per pass. A busy memecoin produces several events per
                # block (AMC, 2026-09-04: 162 402 transfers and 75 956 swaps over 36 000 blocks,
                # 481 s in one pass) and would otherwise hold the whole cycle hostage. Catching up
                # over several passes keeps every other candidate moving.
                r = await self.p.process(token, label, is_portfolio=False, deep=True,
                                         max_blocks=int(s3.get("max_blocks_per_pass", 20_000)))
                results.append({"token": token, "label": r.get("label", label), "state": r["decision"].state, "action": r["decision"].action, "moonshot": r["scores"].moonshot, "hard_pass": r["hard_filters"].passed})
                alerts += (r.get("alerts") or {}).get("sent", 0)
                # Only a security failure is permanent. Liquidity and concentration change by
                # the hour: a token rejected for them must be looked at again (2026-09-03: PARE
                # was rejected for liquidity $19,225 vs a $20,000 floor, then did ~×90 — and the
                # scanner never re-examined it because REJECTED was terminal).
                if r["hard_filters"].security_reject:
                    status = "REJECTED"
                elif r["decision"].action == "CANDIDATE" or r["scores"].moonshot >= float(self.ctx.config.get("states.watch_moonshot_min", 50)):
                    status = "ACTIVE"
                else:
                    status = "DORMANT"  # scored, uninteresting for now: re-checked later
                delay = 1 if status == "ACTIVE" else (12 if status == "REJECTED" else 3)
                self._set_candidate(token, status=status, stage=3, reason=None if status == "ACTIVE" else r["decision"].reason, next_eval=now_ts() + int(self.cfg.get("rescan_interval_seconds", 600)) * delay)
                self._event(token, 3, status == "ACTIVE", r["decision"].reason, {"moonshot": r["scores"].moonshot, "state": r["decision"].state})
            except Exception as exc:  # noqa: BLE001
                log.exception("stage3 failed %s: %s", token[:10], exc)
        return {"evaluated": len(results), "queued": len(queue), "skipped_over_budget": skipped, "results": results, "alerts_sent": alerts}

    async def analyse_now(self, limit: int = 3) -> dict[str, Any]:
        """Fully evaluate the tokens the sweep just found trading, without queueing them.

        Capacity stopped being the constraint once an evaluation fell to 2.9 s (2026-09-05);
        the appointment did. A token queued for the next deep cycle waits up to five minutes
        against a window that is six minutes long. Evaluating it here costs a few seconds and
        gives it the complete analysis — score, holders, linked wallets — instead of the
        abbreviated judgement the fast lane has to make.
        """
        if not self._hot:
            return {"analysed": 0}
        fresh: list[str] = []
        for token, _vol in sorted(self._hot.items(), key=lambda kv: -kv[1]):
            if len(fresh) >= limit:
                break
            if self.ctx.is_system(token) or token in self.ctx.config.quote_assets:
                continue
            # never scored, or last scored long enough ago that the picture has changed
            last = self.ctx.db.scalar("SELECT MAX(ts) FROM token_scores WHERE chain_id=? AND token_address=?", (self.ctx.chain_id, token))
            if last is None or now_ts() - int(last) > int(self.cfg.get("hot_rescore_seconds", 900)):
                fresh.append(token)
        results = []
        for token in fresh:
            label = self.ctx.db.scalar("SELECT symbol FROM tokens WHERE chain_id=? AND address=?", (self.ctx.chain_id, token)) or token[:10]
            try:
                r = await self.p.process(token, label, is_portfolio=False, deep=True,
                                         max_blocks=int(self.cfg.get("stage3", {}).get("max_blocks_per_pass", 20_000)))
                results.append({"token": token, "state": r["decision"].state, "moonshot": round(r["scores"].moonshot)})
                self._set_candidate(token, stage=3, next_eval=now_ts() + int(self.cfg.get("rescan_interval_seconds", 600)))
            except Exception as exc:  # noqa: BLE001
                log.warning("analyse immédiate de %s: %s", token[:10], exc)
        return {"analysed": len(results), "results": results}

    async def _fastlane(self) -> dict[str, Any]:
        """Hand the sweep's busiest tokens to the fast lane, with the prices we already hold."""
        from intel.engines.fastlane import run as fastlane_run

        if not self._hot or not self.ctx.config.get("decisions.fastlane_enabled", True):
            return {"considered": 0, "bought": 0}
        prices: dict[str, float] = {}
        for tok in sorted(self._hot, key=lambda k: -self._hot[k])[:10]:
            row = self.ctx.db.query_one(
                "SELECT price_usd FROM token_snapshots WHERE chain_id=? AND token_address=? AND price_usd IS NOT NULL ORDER BY ts DESC LIMIT 1",
                (self.ctx.chain_id, tok))
            if row and row["price_usd"]:
                prices[tok] = float(row["price_usd"])
        res = await fastlane_run(self.ctx, self._hot, prices, limit=int(self.cfg.get("fastlane_per_cycle", 5)))
        decisions = res.pop("decisions", [])
        if decisions and self.p.sender is not None:
            from intel.engines.decisions import dispatch_decisions

            res["sent"] = await dispatch_decisions(self.ctx, self.p.sender, decisions)
        return res

    async def triage_cycle(self) -> dict[str, Any]:
        """Discovery + the cheap filters. Must stay fast: this is what sees a token exist at all."""
        out: dict[str, Any] = {}
        try:
            out["discover_onchain"] = await self.discover_onchain()
        except Exception as exc:  # noqa: BLE001
            log.exception("on-chain discovery failed: %s", exc)
        out["discover_dex"] = await self.discover_dexscreener()
        try:
            self._hot = await self.hot_tokens()
            out["hot"] = {"tokens": len(self._hot), "usd": round(sum(self._hot.values()))}
        except Exception as exc:  # noqa: BLE001
            log.warning("activity sweep failed: %s", exc)
        # The busiest tokens are decided on now, from the sweep, without waiting for a score the
        # deep pass cannot deliver in time (2026-09-04: 100 % of tradeable tokens spotted, 0 %
        # scored while their window was open).
        # Full analysis first, on what is trading right now: it is only seconds and it produces a
        # real score. The fast lane below is the fallback for what moves faster than that.
        try:
            out["analysed_now"] = await self.analyse_now(int(self.cfg.get("analyse_now_per_cycle", 3)))
        except Exception as exc:  # noqa: BLE001
            log.exception("immediate analysis failed: %s", exc)
        try:
            out["fastlane"] = await self._fastlane()
        except Exception as exc:  # noqa: BLE001
            log.exception("fast lane failed: %s", exc)
        s1 = await self.stage1()
        out["stage1"] = {k: v for k, v in s1.items() if k != "tokens"}
        s2 = await self.stage2(s1.get("tokens", []))
        out["stage2"] = {k: v for k, v in s2.items() if k != "tokens"}
        self._promoted = s2.get("tokens", [])
        return out

    async def deep_cycle(self) -> dict[str, Any]:
        """Stage 3: full on-chain ingestion and scoring. Slow by nature, hence its own loop."""
        return {"stage3": await self.stage3(self._promoted)}

    async def run_cycle(self) -> dict[str, Any]:
        """Triage then deep, in one pass. Used by ``--once`` and by tests.

        The live scheduler runs the two halves on separate loops instead: on 2026-09-03 a single
        stage-3 token with a 500k-block backlog stretched one cycle to 2h43, so stage 1 ran twice
        a day instead of every two minutes and brand new tokens were simply never looked at.
        """
        out = await self.triage_cycle()
        out.update(await self.deep_cycle())
        return out
