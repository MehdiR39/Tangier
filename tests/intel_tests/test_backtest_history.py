"""Historical replay: series loading, the depth gate, exits, and the effect of each rule."""
import random

from intel.backtest.history import Rules, _feature, load_series, make_picker, monte_carlo, replay
from intel.context import IntelContext
from intel.db.connection import Database
from intel.providers.base import ProviderStatusRegistry
from intel.settings import IntelConfig, Settings

USDG = "0x5fc5360d0400a0fd4f2af552add042d716f1d168"
A = "0x" + "aa" * 20   # x10 then holds
B = "0x" + "bb" * 20   # slow death
C = "0x" + "cc" * 20   # never traded enough to be bought

GATE = 20_000.0        # tests state the depth gate explicitly rather than lean on the default


def _ctx() -> IntelContext:
    ctx = IntelContext.__new__(IntelContext)
    ctx.settings = Settings.load(db_path=":memory:", telegram_dry_run=True)
    ctx.config = IntelConfig()
    ctx.db = Database(":memory:")
    ctx.status = ProviderStatusRegistry(ctx.db)
    ctx.rpc = ctx.blockscout = ctx.dex = None  # type: ignore[assignment]
    return ctx


def _seed(ctx, token, points, vol=50_000.0):
    """points are (ts, price, hourly_volume_usd).

    Depth is the volume traded over the preceding hour, so a point every 600 s carries a sixth
    of the intended hourly figure and the rolling sum reproduces it.
    """
    ctx.db.upsert("history_meta", {"chain_id": ctx.chain_id, "token_address": token, "pool_id": "p" + token[-4:], "quote_address": USDG,
                                   "quote_symbol": "USDG", "token_decimals": 18, "quote_decimals": 6, "from_block": 1, "to_block": 2,
                                   "first_ts": points[0][0], "last_ts": points[-1][0], "n_swaps": len(points), "n_points": len(points), "built_ts": 1},
                  ("chain_id", "token_address", "pool_id"))
    ctx.db.insert_many("history_series", [{"chain_id": ctx.chain_id, "token_address": token, "ts": ts, "price_quote": px,
                                           "liquidity_quote": None, "vol_quote": (v if v is not None else vol) / 6.0, "n_trades": 1,
                                           "block_number": None} for ts, px, v in points], ignore=True)


def test_depth_is_the_rolling_hour_of_traded_volume():
    ctx = _ctx()
    T0 = 1_800_000_000
    _seed(ctx, A, [(T0 + i * 600, 1.0, 60_000.0) for i in range(12)])
    s = load_series(ctx, [A], {USDG: 1.0})[A]
    # first point: one bucket of 60000/6; after an hour: six buckets, i.e. the full figure
    assert round(s[0][2]) == 10_000
    assert round(s[6][2]) == 60_000
    # volume that scrolled out of the window stops counting, so it plateaus instead of piling up
    assert round(s[-1][2]) == 60_000
    # an unpriced quote token is skipped rather than silently valued at zero
    assert load_series(ctx, [A], {}) == {}


def test_entry_gate_and_rule_effects():
    ctx = _ctx()
    T0 = 1_800_000_000
    # A: flat 3h (warm-up), then x10 over 6h, then holds
    pts_a = [(T0 + i * 600, 1.0, 50_000.0) for i in range(18)] + [(T0 + 18 * 600 + i * 600, 1.0 + i * 0.25, 50_000.0) for i in range(37)]
    pts_a += [(pts_a[-1][0] + i * 600, 10.0, 50_000.0) for i in range(1, 30)]
    _seed(ctx, A, pts_a)
    # B: dies slowly to -80 %
    pts_b = [(T0 + i * 600, max(0.2, 1.0 - i * 0.012), 40_000.0) for i in range(80)]
    _seed(ctx, B, pts_b)
    # C: always too thinly traded to enter
    _seed(ctx, C, [(T0 + i * 600, 1.0, 5_000.0) for i in range(80)])
    series = load_series(ctx, [A, B, C], {USDG: 1.0})
    assert set(series) == {A, B, C}

    def first(pool, rng, t, series):
        return sorted(pool)[0]

    hold = Rules("hold", moonbag=None, stop=None, trail=None, timeout_h=None, entry_min_vol_usd=GATE, exit_min_vol_usd=0.0)
    res = replay(series, hold, capital=40.0, line=20.0, picker=first, rng=None, warmup_h=2.0)
    assert res.played == 2, "C never trades enough and must never be bought"
    assert res.final > 40.0  # A's x10 more than covers B
    # the old tight trailing stop cuts the winner: same universe, worse outcome
    tight = Rules("tight", moonbag=3.0, stop=0.5, trail=0.35, timeout_h=None, entry_min_vol_usd=GATE, exit_min_vol_usd=0.0)
    res_t = replay(series, tight, capital=40.0, line=20.0, picker=first, rng=None, warmup_h=2.0)
    assert res_t.final < res.final
    # a 1h timeout exits before the move and lands near the stake minus fees
    fast = Rules("fast", moonbag=None, stop=None, trail=None, timeout_h=1.0, entry_min_vol_usd=GATE, exit_min_vol_usd=0.0)
    res_f = replay(series, fast, capital=40.0, line=20.0, picker=first, rng=None, warmup_h=2.0)
    assert res_f.final < res.final and res_f.played >= 2


def test_a_bag_nobody_trades_is_worth_nothing():
    ctx = _ctx()
    T0 = 1_800_000_000
    # tradeable for 5h, then the book dies while the printed price stays high
    pts = [(T0 + i * 600, 1.0, 60_000.0) for i in range(30)] + [(T0 + (30 + i) * 600, 50.0, 0.0) for i in range(30)]
    _seed(ctx, A, pts)
    series = load_series(ctx, [A], {USDG: 1.0})
    rules = Rules("hold", moonbag=None, stop=None, trail=None, timeout_h=None, entry_min_vol_usd=GATE, exit_min_vol_usd=1_000.0)
    res = replay(series, rules, capital=20.0, line=20.0, picker=make_picker("random"), rng=random.Random(1), warmup_h=2.0)
    assert res.played == 1
    # nothing trades any more at the end: the bag cannot be sold, so it is worth zero, not x50
    assert res.final < 1.0


def test_no_buying_into_a_pool_that_has_stopped_trading():
    ctx = _ctx()
    T0 = 1_800_000_000
    # deep for 3h, then volume dies and the price collapses; the collapse must not be buyable
    pts = [(T0 + i * 600, 1.0, 60_000.0) for i in range(18)] + [(T0 + (18 + i) * 600, 1e-9, 0.0) for i in range(30)]
    _seed(ctx, A, pts)
    series = load_series(ctx, [A], {USDG: 1.0})
    rules = Rules("hold", moonbag=None, stop=None, trail=None, timeout_h=None, entry_min_vol_usd=GATE, exit_min_vol_usd=1_000.0)
    res = replay(series, rules, capital=20.0, line=20.0, picker=make_picker("random"), rng=random.Random(1), warmup_h=4.0)
    # the warm-up ends after the book is gone, so no buy happens at the 1e-9 print
    assert res.played == 0 and res.final == 20.0


def test_monte_carlo_reports_distribution():
    ctx = _ctx()
    T0 = 1_800_000_000
    for i in range(6):
        tok = "0x" + f"{i:02d}" * 20
        mult = 5.0 if i == 0 else 0.5
        pts = [(T0 + j * 600, 1.0, 60_000.0) for j in range(18)] + [(T0 + (18 + j) * 600, 1.0 + (mult - 1.0) * j / 20, 60_000.0) for j in range(21)]
        _seed(ctx, tok, pts)
    series = load_series(ctx, ["0x" + f"{i:02d}" * 20 for i in range(6)], {USDG: 1.0})
    rules = Rules("hold", moonbag=None, stop=None, trail=None, timeout_h=None, entry_min_vol_usd=GATE, exit_min_vol_usd=0.0)
    out = monte_carlo(series, rules, capital=40.0, line=20.0, draws=40)
    assert out["worst"] <= out["median"] <= out["best"] and 0.0 <= out["win_rate"] <= 1.0
    assert out["lines"] >= 2


def test_pickers_are_point_in_time_and_rankable():
    ctx = _ctx()
    T0 = 1_800_000_000
    deep = "0x" + "d1" * 20    # heavily traded, flat price
    pumped = "0x" + "e2" * 20  # thinly traded, already up a lot by the decision time
    _seed(ctx, deep, [(T0 + i * 600, 1.0, 90_000.0) for i in range(40)])
    _seed(ctx, pumped, [(T0 + i * 600, 1.0 + i * 0.1, 25_000.0) for i in range(40)])
    series = load_series(ctx, [deep, pumped], {USDG: 1.0})
    t = T0 + 20 * 600
    assert make_picker("deep")([deep, pumped], None, t, series) == deep
    assert make_picker("thin")([deep, pumped], None, t, series) == pumped
    assert make_picker("momentum")([deep, pumped], None, t, series) == pumped
    assert make_picker("flat")([deep, pumped], None, t, series) == deep
    # a feature never reads past the decision time: at t=T0 nothing has moved yet
    assert _feature(series, pumped, T0, "momentum") == 1.0


def test_monte_carlo_accepts_a_named_picker():
    ctx = _ctx()
    T0 = 1_800_000_000
    for i in range(8):
        tok = "0x" + f"{i:02d}" * 20
        mult = 6.0 if i == 0 else 0.6
        pts = [(T0 + j * 600, 1.0, 40_000.0 + i * 5_000) for j in range(18)]
        pts += [(T0 + (18 + j) * 600, 1.0 + (mult - 1.0) * j / 20, 40_000.0 + i * 5_000) for j in range(21)]
        _seed(ctx, tok, pts)
    series = load_series(ctx, ["0x" + f"{i:02d}" * 20 for i in range(8)], {USDG: 1.0})
    rules = Rules("hold", moonbag=None, stop=None, trail=None, timeout_h=None, entry_min_vol_usd=GATE, exit_min_vol_usd=0.0)
    rnd = monte_carlo(series, rules, capital=40.0, line=20.0, draws=20, picker="random")
    deep = monte_carlo(series, rules, capital=40.0, line=20.0, draws=20, picker="deep")
    assert rnd["picker"] == "random" and deep["picker"] == "deep"
    # sub-universes make a deterministic picker vary too, instead of collapsing to one outcome
    assert deep["worst"] <= deep["median"] <= deep["best"]


def test_tick_bound_prices_never_enter_the_series():
    from intel.chain.uniswap_v4 import MAX_SQRT_PRICE, MIN_SQRT_PRICE, is_price_at_bound
    # A pool pushed out of range reports the clamp value; it is not a price anything traded at.
    assert is_price_at_bound(MAX_SQRT_PRICE)
    assert is_price_at_bound(MIN_SQRT_PRICE)
    assert is_price_at_bound(0)
    assert not is_price_at_bound(2 ** 96)  # price 1.0, well inside the range


def test_choices_counts_the_competition_for_a_slot():
    ctx = _ctx()
    T0 = 1_800_000_000
    toks = ["0x" + f"{i:02d}" * 20 for i in range(5)]
    for tok in toks:
        _seed(ctx, tok, [(T0 + j * 600, 1.0, 50_000.0) for j in range(40)])
    series = load_series(ctx, toks, {USDG: 1.0})
    rules = Rules("hold", moonbag=None, stop=None, trail=None, timeout_h=None, entry_min_vol_usd=GATE, exit_min_vol_usd=0.0)
    # 5 eligible tokens for 2 slots: the picker really chooses
    tight = replay(series, rules, capital=40.0, line=20.0, picker=make_picker("random"), rng=random.Random(1))
    assert tight.played == 2 and tight.avg_choices > 1.0
    # 5 eligible tokens for 10 slots: everything is bought, no selection happens
    loose = replay(series, rules, capital=200.0, line=20.0, picker=make_picker("random"), rng=random.Random(1))
    assert loose.played == 5 and loose.avg_choices <= 5.0


def test_capital_is_finite_and_the_low_point_is_recorded():
    ctx = _ctx()
    T0 = 1_800_000_000
    # six tokens that all halve: the account can never open more lines than the cash allows
    toks = ["0x" + f"{i:02d}" * 20 for i in range(6)]
    for tok in toks:
        pts = [(T0 + j * 600, 1.0, 60_000.0) for j in range(18)] + [(T0 + (18 + j) * 600, 1.0 - j * 0.02, 60_000.0) for j in range(21)]
        _seed(ctx, tok, pts)
    series = load_series(ctx, toks, {USDG: 1.0})
    rules = Rules("hold", moonbag=None, stop=None, trail=None, timeout_h=None, entry_min_vol_usd=GATE, exit_min_vol_usd=0.0)
    res = replay(series, rules, capital=60.0, line=20.0, picker=make_picker("random"), rng=random.Random(3))
    assert res.played == 3, "60 EUR buys three lines of 20, never six"
    # the account is marked to market along the way, so the low point is below the starting stake
    assert res.min_equity < 60.0
    # the low point ignores the exit fee the final figure pays, so they land within a fee of each other
    assert abs(res.min_equity - res.final) <= res.min_equity * rules.fee + 1e-6


def test_gas_is_charged_on_every_transaction():
    ctx = _ctx()
    T0 = 1_800_000_000
    # one token, dead flat: with no costs the line comes back whole
    _seed(ctx, A, [(T0 + j * 600, 1.0, 60_000.0) for j in range(40)])
    series = load_series(ctx, [A], {USDG: 1.0})
    free = Rules("free", moonbag=None, stop=None, trail=None, timeout_h=None, entry_min_vol_usd=GATE, exit_min_vol_usd=0.0, fee=0.0)
    res = replay(series, free, capital=20.0, line=20.0, picker=make_picker("random"), rng=random.Random(1))
    assert res.played == 1 and abs(res.final - 20.0) < 1e-9
    # the same line pays gas twice: once to buy, once to sell
    paid = Rules("gas", moonbag=None, stop=None, trail=None, timeout_h=None, entry_min_vol_usd=GATE, exit_min_vol_usd=0.0, fee=0.0, gas_usd=0.30)
    res_g = replay(series, paid, capital=20.0, line=20.0, picker=make_picker("random"), rng=random.Random(1))
    assert abs(res_g.final - (20.0 - 0.60)) < 1e-9
