"""Stage-3 slots must go to never-scored candidates with momentum, not only to old ones."""
from intel.alerts.dedup import AlertDeduper
from intel.context import IntelContext
from intel.db.connection import Database
from intel.engines.pipeline import TokenPipeline
from intel.engines.scanner import Scanner
from intel.metrics.pricing import QuotePricer
from intel.providers.base import ProviderStatusRegistry
from intel.settings import IntelConfig, Settings
from intel.utils.timeutil import now_ts


def _ctx() -> IntelContext:
    ctx = IntelContext.__new__(IntelContext)
    ctx.settings = Settings.load(db_path=":memory:", telegram_dry_run=True)
    ctx.config = IntelConfig()
    ctx.db = Database(":memory:")
    ctx.status = ProviderStatusRegistry(ctx.db)
    ctx.rpc = ctx.blockscout = ctx.dex = None  # type: ignore[assignment]
    return ctx


def _candidate(ctx, addr, stage, px_ref, px_now, liq):
    ts = now_ts()
    ctx.db.insert("scanner_candidates", {"chain_id": ctx.chain_id, "token_address": addr, "first_seen_ts": ts - 7200, "last_seen_ts": ts, "stage_reached": stage, "status": "ACTIVE"})
    ctx.db.insert("token_snapshots", {"ts": ts - 3600, "chain_id": ctx.chain_id, "token_address": addr, "source": "dexscreener", "price_usd": px_ref, "liquidity_usd": liq})
    ctx.db.insert("token_snapshots", {"ts": ts - 60, "chain_id": ctx.chain_id, "token_address": addr, "source": "dexscreener", "price_usd": px_now, "liquidity_usd": liq})


def test_momentum_queue_prefers_movers_and_ignores_scored_tokens():
    ctx = _ctx()
    pipeline = TokenPipeline(ctx, QuotePricer(ctx), AlertDeduper(ctx.db, ctx.config.section("alerts"), ctx.chain_id), None)
    sc = Scanner(pipeline)
    _candidate(ctx, "0x" + "aa" * 20, 2, 1.0, 7.0, 40_000)    # ×7 : the DOGE-1 case
    _candidate(ctx, "0x" + "bb" * 20, 2, 1.0, 1.02, 500_000)  # flat but deep
    _candidate(ctx, "0x" + "cc" * 20, 2, 1.0, 3.0, 5_000)     # ×3 but very thin -> penalised
    _candidate(ctx, "0x" + "dd" * 20, 3, 1.0, 9.0, 900_000)   # already scored: not in this queue
    q = sc._momentum_queue(3)
    assert q[0] == "0x" + "aa" * 20  # the mover comes first
    assert "0x" + "dd" * 20 not in q  # already-scored tokens are handled by the refresh slots
    assert set(q) == {"0x" + "aa" * 20, "0x" + "cc" * 20, "0x" + "bb" * 20}
    # a candidate without price history is simply skipped, not crashing
    ctx.db.insert("scanner_candidates", {"chain_id": ctx.chain_id, "token_address": "0x" + "ee" * 20, "first_seen_ts": now_ts(), "last_seen_ts": now_ts(), "stage_reached": 2, "status": "ACTIVE"})
    assert "0x" + "ee" * 20 not in sc._momentum_queue(5)


def test_stage3_stops_at_its_time_budget():
    """A slow token must not consume the whole cycle: the rest of the queue would wait for nothing."""
    import asyncio

    ctx = _ctx()
    ctx.config.data["scanner"]["stage3"] = {"max_candidates_per_cycle": 5, "refresh_per_cycle": 0, "cycle_budget_seconds": 0.2}
    scanner = Scanner(TokenPipeline(ctx, QuotePricer(ctx), AlertDeduper(ctx.db, ctx.config.section("alerts"), ctx.chain_id), None))
    seen = []

    async def _slow(token, label, **kw):
        seen.append(token)
        await asyncio.sleep(0.15)
        raise RuntimeError("only the scheduling matters here")

    scanner.p.process = _slow  # type: ignore[assignment]
    toks = ["0x" + f"{i:02d}" * 20 for i in range(5)]
    out = asyncio.run(scanner.stage3(toks))
    assert len(seen) < len(toks), "the cycle must give up once over budget"
    assert out["skipped_over_budget"] > 0


def test_stage3_bounds_the_catch_up_of_a_busy_token():
    """Each pass ingests a bounded range so one dense token cannot hold the cycle.

    AMC (2026-09-04) produced 162 402 transfers over 36 000 blocks and took 481 s in a single pass,
    starving every other candidate.
    """
    import asyncio

    ctx = _ctx()
    ctx.config.data["scanner"]["stage3"] = {"max_candidates_per_cycle": 2, "refresh_per_cycle": 0, "cycle_budget_seconds": 30, "max_blocks_per_pass": 20_000}
    scanner = Scanner(TokenPipeline(ctx, QuotePricer(ctx), AlertDeduper(ctx.db, ctx.config.section("alerts"), ctx.chain_id), None))
    seen = {}

    async def _capture(token, label, **kw):
        seen[token] = kw.get("max_blocks")
        raise RuntimeError("only the bound matters here")

    scanner.p.process = _capture  # type: ignore[assignment]
    asyncio.run(scanner.stage3(["0x" + "ab" * 20]))
    assert list(seen.values()) == [20_000]


def test_smart_money_does_not_requery_the_same_token_per_wallet():
    """The token's first-trade timestamp is wallet-independent and must be computed once.

    Profiled 2026-09-04: 1 835 SQLite queries and 2.1 s for one token's smart-money section,
    because this value was re-read for every wallet examined.
    """
    from intel.metrics.smart_money import token_smart_money

    ctx = _ctx()
    ts = now_ts()
    tok = "0x" + "f1" * 20
    wallets = ["0x" + f"{i:040x}" for i in range(6)]
    for i, w in enumerate(wallets):
        for side, t in (("BUY", ts - 7200), ("SELL", ts - 3600)):
            ctx.db.insert("trades", {"chain_id": ctx.chain_id, "tx_hash": f"0x{i}{side}", "log_index": i, "block_number": 1, "ts": t,
                                     "token_address": tok, "trader": w, "side": side, "usd_value": 100.0,
                                     "token_amount_float": 10.0, "token_amount": "10", "price_usd": 10.0, "source": "test"})
    calls = {"n": 0}
    real = ctx.db.scalar

    def counting(sql, *a, **kw):
        if "MIN(ts) FROM trades" in sql:
            calls["n"] += 1
        return real(sql, *a, **kw)

    ctx.db.scalar = counting  # type: ignore[assignment]
    token_smart_money(ctx, tok, ts, wallets, {})
    assert calls["n"] == 1, f"one query for the whole batch, got {calls['n']}"
