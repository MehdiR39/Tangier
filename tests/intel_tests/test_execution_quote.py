"""Quoting from pool state: exact tick math, and refusal whenever the quote cannot be trusted."""
from intel.context import IntelContext
from intel.db.connection import Database
from intel.execution.quote import Q96, price_impact_pct, quote_exact_in, quote_from_pool
from intel.providers.base import ProviderStatusRegistry
from intel.settings import IntelConfig, Settings
from intel.utils.timeutil import now_ts

POOL = "0x" + "cd" * 32


def _ctx() -> IntelContext:
    ctx = IntelContext.__new__(IntelContext)
    ctx.settings = Settings.load(db_path=":memory:", telegram_dry_run=True)
    ctx.config = IntelConfig()
    ctx.db = Database(":memory:")
    ctx.status = ProviderStatusRegistry(ctx.db)
    ctx.rpc = ctx.blockscout = ctx.dex = None  # type: ignore[assignment]
    return ctx


def _swap(ctx, *, sqrt_p=Q96, liquidity=10 ** 18, age_s=10, block=100):
    ctx.db.insert("swap_events", {"chain_id": ctx.chain_id, "tx_hash": f"0x{block:064x}", "log_index": 0,
                                  "block_number": block, "ts": now_ts() - age_s, "pair_id": POOL, "sender": "0x" + "11" * 20,
                                  "amount0": "1", "amount1": "1", "sqrt_price_x96": str(sqrt_p), "liquidity": str(liquidity),
                                  "tick": 0, "fee": 3000, "source": "test"})


def test_a_balanced_pool_returns_almost_one_for_one_minus_the_fee():
    # sqrtPrice = Q96 means price 1.0; a tiny trade against deep liquidity loses only the fee
    out = quote_exact_in(sqrt_price_x96=Q96, liquidity=10 ** 24, zero_for_one=True, amount_in=10 ** 18, fee_pips=3000)
    assert 0.996 < out / 10 ** 18 < 0.9971


def test_no_fee_returns_more_than_with_a_fee():
    args = dict(sqrt_price_x96=Q96, liquidity=10 ** 24, zero_for_one=True, amount_in=10 ** 18)
    assert quote_exact_in(**args, fee_pips=0) > quote_exact_in(**args, fee_pips=3000)


def test_both_directions_are_symmetric_on_a_balanced_pool():
    a = quote_exact_in(sqrt_price_x96=Q96, liquidity=10 ** 24, zero_for_one=True, amount_in=10 ** 18, fee_pips=3000)
    b = quote_exact_in(sqrt_price_x96=Q96, liquidity=10 ** 24, zero_for_one=False, amount_in=10 ** 18, fee_pips=3000)
    assert abs(a - b) / a < 1e-6


def test_a_bigger_order_gets_a_worse_rate():
    small = quote_exact_in(sqrt_price_x96=Q96, liquidity=10 ** 21, zero_for_one=True, amount_in=10 ** 18, fee_pips=3000)
    big = quote_exact_in(sqrt_price_x96=Q96, liquidity=10 ** 21, zero_for_one=True, amount_in=10 ** 20, fee_pips=3000)
    assert big / 10 ** 20 < small / 10 ** 18


def test_impact_grows_with_size_and_shrinks_with_depth():
    thin = price_impact_pct(sqrt_price_x96=Q96, liquidity=10 ** 20, zero_for_one=True, amount_in=10 ** 18, fee_pips=3000)
    deep = price_impact_pct(sqrt_price_x96=Q96, liquidity=10 ** 24, zero_for_one=True, amount_in=10 ** 18, fee_pips=3000)
    assert thin > deep >= 0.0


def test_degenerate_inputs_return_nothing_rather_than_a_number():
    assert quote_exact_in(sqrt_price_x96=Q96, liquidity=0, zero_for_one=True, amount_in=10 ** 18, fee_pips=3000) == 0
    assert quote_exact_in(sqrt_price_x96=0, liquidity=10 ** 20, zero_for_one=True, amount_in=10 ** 18, fee_pips=3000) == 0
    assert quote_exact_in(sqrt_price_x96=Q96, liquidity=10 ** 20, zero_for_one=True, amount_in=0, fee_pips=3000) == 0


def test_a_usable_quote_from_a_fresh_pool_state():
    ctx = _ctx()
    _swap(ctx, liquidity=10 ** 24)
    q = quote_from_pool(ctx, pool_id=POOL, zero_for_one=True, amount_in=10 ** 18, fee_pips=3000)
    assert q.usable and q.amount_out > 0 and q.state_age_s < 60


def test_an_unknown_pool_is_refused():
    q = quote_from_pool(_ctx(), pool_id=POOL, zero_for_one=True, amount_in=10 ** 18, fee_pips=3000)
    assert not q.usable and "état du pool inconnu" in q.reasons


def test_a_stale_pool_state_is_refused():
    ctx = _ctx()
    _swap(ctx, liquidity=10 ** 24, age_s=3600)
    q = quote_from_pool(ctx, pool_id=POOL, zero_for_one=True, amount_in=10 ** 18, fee_pips=3000, max_state_age_s=900)
    assert not q.usable and any("dernier échange" in r for r in q.reasons)


def test_an_order_too_large_for_single_tick_math_is_refused():
    ctx = _ctx()
    _swap(ctx, liquidity=10 ** 20)
    q = quote_from_pool(ctx, pool_id=POOL, zero_for_one=True, amount_in=10 ** 19, fee_pips=3000)
    assert not q.usable
    assert any("trop gros" in r for r in q.reasons) or any("impact" in r for r in q.reasons)


def test_the_most_recent_state_wins():
    ctx = _ctx()
    _swap(ctx, liquidity=10 ** 24, block=100)
    _swap(ctx, liquidity=10 ** 22, block=200)
    q = quote_from_pool(ctx, pool_id=POOL, zero_for_one=True, amount_in=10 ** 18, fee_pips=3000)
    assert q.liquidity == 10 ** 22
