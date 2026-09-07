from intel.context import IntelContext
from intel.db.connection import Database
from intel.metrics.regime import CACHE_KEY, buying_allowed, cached_regime, classify
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


def test_classify_bull_bear_consolidation():
    assert classify([100.0] * 50)[0] == "unknown"                       # not enough history
    bull = [100 + i for i in range(200)]                                 # steady climb
    assert classify([float(x) for x in bull])[0] == "bull"
    bear = [300 - i for i in range(200)]                                 # steady fall
    assert classify([float(x) for x in bear])[0] == "bear"
    flat = [100.0 + (i % 5) for i in range(200)]
    assert classify(flat)[0] == "consolidation"


def test_gate_is_off_by_default_and_can_be_switched_on():
    ctx = _ctx()
    assert cached_regime(ctx) == "unknown"
    # default: recorded but never blocking (no evidence it helps on 24h memecoin moves)
    ctx.db.cache_set(CACHE_KEY, {"regime": "bear"}, now_ts(), 3600)
    assert buying_allowed(ctx)[0]
    ctx.config.data["decisions"]["regime_gate_enabled"] = True
    ok, why = buying_allowed(ctx)
    assert not ok and "baissière" in why
    ctx.db.cache_set(CACHE_KEY, {"regime": "consolidation"}, now_ts(), 3600)
    assert buying_allowed(ctx)[0]


def test_gate_blocks_buy_decisions_but_not_sells():
    from intel.engines.decisions import evaluate_decisions
    from intel.scoring.scores import Scores
    from intel.scoring.states import StateDecision

    ctx = _ctx()
    tok = "0x" + "ab" * 20
    m = {"price_usd": 1.0, "market_cap": 1_000_000.0, "liquidity_usd": 250_000.0, "liquidity": {"liquidity_change_24h": 0.0}, "holders": {"holder_count": 800}, "returns": {}, "security": {"overall": "WARN", "fails": []}}
    sc = Scores(70, 70, 70, 70, 80, None, 20, 50, 75, {})
    buy = StateDecision("ACCUMULATION", "CANDIDATE", "holders en hausse")
    ctx.config.data["decisions"]["regime_gate_enabled"] = True
    ctx.db.cache_set(CACHE_KEY, {"regime": "bear"}, now_ts(), 3600)
    assert evaluate_decisions(ctx, token=tok, label="X", m=m, scores=sc, decision=buy, is_portfolio=False) == []
    ctx.db.cache_set(CACHE_KEY, {"regime": "bull"}, now_ts(), 3600)
    assert [d["kind"] for d in evaluate_decisions(ctx, token=tok, label="X", m=m, scores=sc, decision=buy, is_portfolio=False)] == ["BUY"]
    # a sell is never blocked by the weather
    ctx.db.cache_set(CACHE_KEY, {"regime": "bear"}, now_ts(), 3600)
    out = evaluate_decisions(ctx, token=tok, label="X", m=dict(m, liquidity={"liquidity_change_24h": -0.6}), scores=sc, decision=StateDecision("THESIS_BREAK", "REJECT", "liquidité -60 %", ["liquidity_24h"]), is_portfolio=False)
    assert [d["kind"] for d in out] == ["SELL_ALL"]
