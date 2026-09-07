"""A token that was tradeable must keep being priced even after it fails the filters.

Without this, collapses are never recorded and every measured return is biased upward.
"""
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
from intel.utils.timeutil import now_ts

DEAD = "0x" + "dd" * 20
USDG = "0x5fc5360d0400a0fd4f2af552add042d716f1d168"


def _pair(base, liq, mc, vol, created_ms):
    return {
        "chainId": "robinhood", "dexId": "uniswap", "labels": ["v4"], "pairAddress": "0x" + base[2:4] * 32, "url": "u",
        "baseToken": {"address": base, "symbol": "DEAD", "name": "Dead"}, "quoteToken": {"address": USDG, "symbol": "USDG"},
        "priceUsd": "0.0001", "priceNative": "0.0001", "liquidity": {"usd": liq, "base": 1, "quote": 1}, "fdv": mc, "marketCap": mc,
        "volume": {"h24": vol, "h6": 0, "h1": 0, "m5": 0}, "txns": {"h24": {"buys": 5, "sells": 30}, "h1": {"buys": 0, "sells": 3}, "h6": {"buys": 1, "sells": 9}, "m5": {"buys": 0, "sells": 0}},
        "priceChange": {"h24": -80, "h6": -60, "h1": -20, "m5": 0}, "pairCreatedAt": created_ms,
    }


class StubDex:
    def __init__(self, pairs):
        self._pairs = pairs

    async def tokens(self, addresses):
        return [p for p in self._pairs if p["baseToken"]["address"] in addresses]


def _ctx(pairs) -> IntelContext:
    ctx = IntelContext.__new__(IntelContext)
    ctx.settings = Settings.load(db_path=":memory:", telegram_dry_run=True)
    ctx.config = IntelConfig()
    ctx.db = Database(":memory:")
    ctx.status = ProviderStatusRegistry(ctx.db)
    ctx.rpc = ctx.blockscout = None  # type: ignore[assignment]
    ctx.dex = StubDex(pairs)  # type: ignore[assignment]
    return ctx


def test_collapsed_token_is_still_priced():
    now_ms = int(time.time() * 1000)
    ctx = _ctx([_pair(DEAD, 4_000.0, 40_000.0, 500.0, now_ms - 6 * 3600 * 1000)])  # liquidity collapsed to 4k
    sc = Scanner(TokenPipeline(ctx, QuotePricer(ctx), AlertDeduper(ctx.db, ctx.config.section("alerts"), ctx.chain_id), None))
    sc._record_candidate(DEAD, None, "test")
    # it used to be tradeable: a snapshot at 50k liquidity exists
    ctx.db.insert("token_snapshots", {"ts": now_ts() - 7200, "chain_id": ctx.chain_id, "token_address": DEAD, "source": "dexscreener", "price_usd": 0.001, "liquidity_usd": 50_000, "market_cap": 400_000})
    res = asyncio.run(sc.stage1())
    assert res["passed"] == 0  # it fails the filters now
    snaps = ctx.db.query("SELECT price_usd, liquidity_usd FROM token_snapshots WHERE token_address=? ORDER BY ts", (DEAD,))
    assert len(snaps) == 2, "the collapse must be recorded, not dropped"
    assert snaps[-1]["liquidity_usd"] == 4_000 and snaps[-1]["price_usd"] == 0.0001
    # a token that was never tradeable is not worth the storage
    NEW = "0x" + "ee" * 20
    ctx.dex._pairs.append(_pair(NEW, 3_000.0, 30_000.0, 100.0, now_ms))  # type: ignore[attr-defined]
    sc._record_candidate(NEW, None, "test")
    asyncio.run(sc.stage1())
    assert ctx.db.scalar("SELECT COUNT(*) FROM token_snapshots WHERE token_address=?", (NEW,)) == 0
