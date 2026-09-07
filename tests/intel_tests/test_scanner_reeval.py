"""A rejection on a condition that can change (liquidity, concentration) must not be terminal."""
from intel.alerts.dedup import AlertDeduper
from intel.context import IntelContext
from intel.db.connection import Database
from intel.engines.pipeline import TokenPipeline
from intel.engines.scanner import Scanner
from intel.metrics.pricing import QuotePricer
from intel.providers.base import ProviderStatusRegistry
from intel.settings import IntelConfig, Settings
from intel.utils.timeutil import now_ts

THIN = "0x" + "11" * 20   # rejected for liquidity, then grows
HACK = "0x" + "22" * 20   # rejected for a security failure: permanent


def _ctx() -> IntelContext:
    ctx = IntelContext.__new__(IntelContext)
    ctx.settings = Settings.load(db_path=":memory:", telegram_dry_run=True)
    ctx.config = IntelConfig()
    ctx.db = Database(":memory:")
    ctx.status = ProviderStatusRegistry(ctx.db)
    ctx.rpc = ctx.blockscout = ctx.dex = None  # type: ignore[assignment]
    return ctx


def _sc(ctx):
    return Scanner(TokenPipeline(ctx, QuotePricer(ctx), AlertDeduper(ctx.db, ctx.config.section("alerts"), ctx.chain_id), None))


def test_temporary_rejection_is_revisited_permanent_one_is_not():
    ctx = _ctx()
    sc = _sc(ctx)
    ts = now_ts()
    for addr, status, nxt in ((THIN, "DORMANT", ts - 60), (HACK, "REJECTED", ts - 60)):
        ctx.db.insert("scanner_candidates", {"chain_id": ctx.chain_id, "token_address": addr, "first_seen_ts": ts - 7200, "last_seen_ts": ts,
                                             "stage_reached": 3, "status": status, "reject_reason": "x", "next_eval_ts": nxt})
        ctx.db.insert("token_snapshots", {"ts": ts - 3600, "chain_id": ctx.chain_id, "token_address": addr, "source": "dexscreener", "price_usd": 1.0, "liquidity_usd": 40_000})
        ctx.db.insert("token_snapshots", {"ts": ts - 60, "chain_id": ctx.chain_id, "token_address": addr, "source": "dexscreener", "price_usd": 6.0, "liquidity_usd": 90_000})
    q = sc._momentum_queue(5)
    assert THIN in q, "a token parked as DORMANT must come back for a deep analysis"
    assert HACK not in q, "a security rejection stays terminal"
    # stage 1 also keeps DORMANT tokens in the loop
    assert THIN in sc._due_candidates(("NEW", "DORMANT", "ACTIVE"), 10)
    assert HACK not in sc._due_candidates(("NEW", "DORMANT", "ACTIVE"), 10)
