"""Scanner stage 1 applies cheap DexScreener filters and persists discovery events."""
import asyncio
import time

from intel.alerts.dedup import AlertDeduper
from intel.context import IntelContext
from intel.db.connection import Database
from intel.engines.pipeline import TokenPipeline
from intel.engines.scanner import Scanner
from intel.metrics.pricing import QuotePricer
from intel.providers.base import ProviderStatusRegistry
from intel.settings import IntelConfig, Settings

GOOD = "0x" + "aa" * 20
THIN = "0x" + "bb" * 20
USDG = "0x5fc5360d0400a0fd4f2af552add042d716f1d168"


def _pair(base, liq, mc, vol, created_ms):
    return {
        "chainId": "robinhood", "dexId": "uniswap", "labels": ["v4"], "pairAddress": "0x" + base[2:4] * 32, "url": "u",
        "baseToken": {"address": base, "symbol": "T", "name": "T"}, "quoteToken": {"address": USDG, "symbol": "USDG"},
        "priceUsd": "0.01", "priceNative": "0.01", "liquidity": {"usd": liq, "base": 1, "quote": 1}, "fdv": mc, "marketCap": mc,
        "volume": {"h24": vol, "h6": vol / 4, "h1": vol / 24, "m5": 0}, "txns": {"h24": {"buys": 50, "sells": 20}, "h1": {"buys": 3, "sells": 1}, "h6": {"buys": 10, "sells": 4}, "m5": {"buys": 0, "sells": 0}},
        "priceChange": {"h24": 5, "h6": 1, "h1": 0.2, "m5": 0}, "pairCreatedAt": created_ms,
    }


class StubDex:
    def __init__(self, pairs):
        self._pairs = pairs

    async def tokens(self, addresses):
        return [p for p in self._pairs if p["baseToken"]["address"] in addresses]


def _ctx(pairs) -> IntelContext:
    ctx = IntelContext.__new__(IntelContext)
    ctx.settings = Settings.load(db_path=":memory:", telegram_dry_run=True)
    ctx.config = IntelConfig({"scanner": {"stage1": {"min_liquidity_usd": 20000, "max_market_cap_usd": 5_000_000, "min_volume_24h_usd": 5000}}})
    ctx.db = Database(":memory:")
    ctx.status = ProviderStatusRegistry(ctx.db)
    ctx.rpc = None  # type: ignore[assignment]
    ctx.blockscout = None  # type: ignore[assignment]
    ctx.dex = StubDex(pairs)  # type: ignore[assignment]
    return ctx


def test_stage1_filters_and_records_events():
    now_ms = int(time.time() * 1000)
    pairs = [_pair(GOOD, 80_000.0, 900_000.0, 50_000.0, now_ms - 3 * 3600 * 1000), _pair(THIN, 5_000.0, 300_000.0, 20_000.0, now_ms - 3 * 3600 * 1000)]
    ctx = _ctx(pairs)
    pipeline = TokenPipeline(ctx, QuotePricer(ctx), AlertDeduper(ctx.db, ctx.config.section("alerts"), ctx.chain_id), None)
    sc = Scanner(pipeline)
    assert sc._record_candidate(GOOD, None, "test") and sc._record_candidate(THIN, None, "test")
    assert not sc._record_candidate(USDG, None, "test")  # quote assets are never candidates
    res = asyncio.run(sc.stage1())
    assert res["evaluated"] == 2 and res["passed"] == 1 and res["tokens"] == [GOOD]
    rows = {r["token_address"]: dict(r) for r in ctx.db.query("SELECT * FROM scanner_candidates")}
    assert rows[GOOD]["status"] == "ACTIVE" and rows[GOOD]["stage_reached"] == 1
    assert rows[THIN]["status"] == "DORMANT" and "liquidity" in rows[THIN]["reject_reason"]
    events = ctx.db.query("SELECT token_address, stage, passed FROM discovery_events ORDER BY id")
    assert [(e["stage"], e["passed"]) for e in events if e["token_address"] == GOOD] == [(0, 1), (1, 1)]
    # the passing token got a market snapshot for history
    assert ctx.db.scalar("SELECT COUNT(*) FROM token_snapshots WHERE token_address=?", (GOOD,)) == 1
    assert ctx.db.scalar("SELECT COUNT(*) FROM token_snapshots WHERE token_address=?", (THIN,)) == 0


def test_new_candidates_are_never_starved_by_older_staged_ones():
    """A freshly discovered token must be evaluated even behind a long backlog.

    Regression: ordering the whole queue by stage_reached DESC meant thousands of already-staged
    candidates were always served first. MICRON AI sat NEW for 9h44 while it did x27.
    """
    ctx = _ctx([])
    scanner = Scanner(TokenPipeline(ctx, QuotePricer(ctx), AlertDeduper(ctx.db, ctx.config.section("alerts"), ctx.chain_id), None))
    now = int(time.time())
    # a big backlog of candidates that already reached stage 1 and are due again
    for i in range(300):
        ctx.db.execute(
            "INSERT INTO scanner_candidates(chain_id, token_address, first_seen_ts, last_seen_ts, discovery_source, stage_reached, status, next_eval_ts) "
            "VALUES (?,?,?,?,?,1,'DORMANT',?)",
            (ctx.chain_id, f"0x{i:040x}", now - 86400, now - 60, "test", now - 10),
        )
    fresh = "0x" + "cc" * 20
    ctx.db.execute(
        "INSERT INTO scanner_candidates(chain_id, token_address, first_seen_ts, last_seen_ts, discovery_source, stage_reached, status, next_eval_ts) "
        "VALUES (?,?,?,?,?,0,'NEW',?)",
        (ctx.chain_id, fresh, now - 120, now - 120, "poolmanager_initialize", now - 120),
    )
    batch = scanner._due_candidates(("NEW",), 60, order="first_seen_ts DESC")
    assert fresh in batch, "a brand new token must have a reserved place in the batch"
    # and the old ordering alone would indeed have buried it
    legacy = scanner._due_candidates(("NEW", "DORMANT", "ACTIVE"), 120)
    assert fresh not in legacy


def test_triage_does_not_wait_for_the_deep_pass():
    """The cheap triage and the expensive stage 3 must be separable.

    Regression: they shared one cycle, so a single stage-3 token backfilling 500k blocks stretched
    the cycle to 2h43 and stage 1 stopped running. They are now two scheduler loops.
    """
    ctx = _ctx([_pair(GOOD, 60000, 300000, 50000, int(time.time() * 1000) - 3600_000)])
    scanner = Scanner(TokenPipeline(ctx, QuotePricer(ctx), AlertDeduper(ctx.db, ctx.config.section("alerts"), ctx.chain_id), None))
    scanner.discover_onchain = _noop_dict          # type: ignore[assignment]
    scanner.discover_dexscreener = _noop_dict      # type: ignore[assignment]
    deep_calls = []

    async def _stage3(tokens):
        deep_calls.append(list(tokens))
        return {"evaluated": len(tokens)}

    scanner.stage3 = _stage3                       # type: ignore[assignment]
    out = asyncio.run(scanner.triage_cycle())
    assert "stage1" in out and "stage3" not in out, "triage must return without touching stage 3"
    assert deep_calls == []
    asyncio.run(scanner.deep_cycle())
    assert len(deep_calls) == 1, "the deep pass picks up what triage promoted"


async def _noop_dict():
    return {}


def test_an_older_new_token_is_not_buried_by_a_flood_of_newer_ones():
    """The oldest never-evaluated token must still get its turn.

    Regression: with a newest-first lane only, a steady stream of fresh discoveries kept pushing
    older NEW entries back forever. MICRON AI was discovered at 12:28 and was still unevaluated
    12 hours later, behind 5000 newer pools.
    """
    ctx = _ctx([])
    scanner = Scanner(TokenPipeline(ctx, QuotePricer(ctx), AlertDeduper(ctx.db, ctx.config.section("alerts"), ctx.chain_id), None))
    now = int(time.time())
    old = "0x" + "dd" * 20
    ctx.db.execute(
        "INSERT INTO scanner_candidates(chain_id, token_address, first_seen_ts, last_seen_ts, discovery_source, stage_reached, status, next_eval_ts) "
        "VALUES (?,?,?,?,?,0,'NEW',?)", (ctx.chain_id, old, now - 12 * 3600, now - 12 * 3600, "test", now - 12 * 3600))
    for i in range(500):  # a flood of newer discoveries
        ctx.db.execute(
            "INSERT INTO scanner_candidates(chain_id, token_address, first_seen_ts, last_seen_ts, discovery_source, stage_reached, status, next_eval_ts) "
            "VALUES (?,?,?,?,?,0,'NEW',?)", (ctx.chain_id, f"0x{i:040x}", now - i, now - i, "test", now - i))
    newest = scanner._due_candidates(("NEW",), 50, order="first_seen_ts DESC")
    oldest = scanner._due_candidates(("NEW",), 50, order="first_seen_ts ASC")
    assert old not in newest, "the newest-first lane alone does bury it"
    assert old in oldest, "the oldest-first lane is what rescues it"


def test_the_busiest_token_is_triaged_first():
    """On-chain traded volume orders the queue ahead of discovery time.

    A token that is changing hands right now must not wait behind thousands of dead pools, whatever
    the order they were discovered in.
    """
    ctx = _ctx([])
    scanner = Scanner(TokenPipeline(ctx, QuotePricer(ctx), AlertDeduper(ctx.db, ctx.config.section("alerts"), ctx.chain_id), None))
    now = int(time.time())
    busy = "0x" + "ee" * 20
    for i in range(400):  # a wall of newer, silent candidates
        ctx.db.execute(
            "INSERT INTO scanner_candidates(chain_id, token_address, first_seen_ts, last_seen_ts, discovery_source, stage_reached, status, next_eval_ts) "
            "VALUES (?,?,?,?,?,0,'NEW',?)", (ctx.chain_id, f"0x{i:040x}", now - 10, now - 10, "test", now - 10))
    ctx.db.execute(
        "INSERT INTO scanner_candidates(chain_id, token_address, first_seen_ts, last_seen_ts, discovery_source, stage_reached, status, next_eval_ts) "
        "VALUES (?,?,?,?,?,0,'NEW',?)", (ctx.chain_id, busy, now - 40000, now - 40000, "test", now - 40000))
    scanner._hot = {busy: 250_000.0}
    out = asyncio.run(scanner.stage1())
    ev = ctx.db.query_one("SELECT token_address FROM discovery_events WHERE chain_id=? AND token_address=? AND stage=1", (ctx.chain_id, busy))
    assert ev is not None, "the token being traded must be evaluated in this very batch"
    assert out["evaluated"] > 0


def test_the_busiest_tokens_are_analysed_inside_the_triage_cycle():
    """Latency, not capacity, is the constraint against a six-minute window.

    A token the sweep just found trading is evaluated in full there and then, instead of waiting
    for a deep cycle that may be minutes away.
    """
    ctx = _ctx([])
    scanner = Scanner(TokenPipeline(ctx, QuotePricer(ctx), AlertDeduper(ctx.db, ctx.config.section("alerts"), ctx.chain_id), None))
    hot = "0x" + "ab" * 20
    cold = "0x" + "cd" * 20
    scanner._hot = {hot: 90_000.0, cold: 10.0}
    seen = []

    async def _process(token, label, **kw):
        seen.append(token)
        return {"decision": type("D", (), {"state": "WATCH"})(), "scores": type("S", (), {"moonshot": 61.0})()}

    scanner.p.process = _process  # type: ignore[assignment]
    out = asyncio.run(scanner.analyse_now(limit=1))
    assert out["analysed"] == 1 and seen == [hot], "the busiest first, and only as many as asked"


def test_a_token_scored_moments_ago_is_not_scored_again():
    ctx = _ctx([])
    scanner = Scanner(TokenPipeline(ctx, QuotePricer(ctx), AlertDeduper(ctx.db, ctx.config.section("alerts"), ctx.chain_id), None))
    tok = "0x" + "ab" * 20
    scanner._hot = {tok: 90_000.0}
    ctx.db.insert("token_scores", {"ts": int(time.time()) - 60, "chain_id": ctx.chain_id, "token_address": tok,
                                   "model_version": "t", "as_of_ts": int(time.time()) - 60, "moonshot": 60.0,
                                   "hard_filter_pass": 1, "state": "WATCH", "action": "WATCH"})
    called = []

    async def _process(token, label, **kw):
        called.append(token)
        return {"decision": type("D", (), {"state": "WATCH"})(), "scores": type("S", (), {"moonshot": 60.0})()}

    scanner.p.process = _process  # type: ignore[assignment]
    assert asyncio.run(scanner.analyse_now(limit=3))["analysed"] == 0 and called == []
