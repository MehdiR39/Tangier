"""End to end in dry run: a decision becomes a checked, journalled order — and never twice."""
import asyncio

from intel.context import IntelContext
from intel.db.connection import Database
from intel.execution import safety
from intel.execution.executor import choose_pool, pending_decisions, prepare, run_once
from intel.execution.quote import Q96
from intel.providers.base import ProviderStatusRegistry
from intel.settings import IntelConfig, Settings
from intel.utils.timeutil import now_ts

USDG = "0x5fc5360d0400a0fd4f2af552add042d716f1d168"
TOKEN = "0x" + "aa" * 20
POOL = "0x" + "cd" * 32
OLD_POOL = "0x" + "ef" * 32
ROUTER = "0xf8b30c1b77e38f2df9d058c43a3af8d47161a0c7"


def _ctx(mode="dry_run") -> IntelContext:
    ctx = IntelContext.__new__(IntelContext)
    ctx.settings = Settings.load(db_path=":memory:", telegram_dry_run=True)
    ctx.config = IntelConfig({"execution": {"mode": mode, "router": ROUTER, "allowed_quotes": [USDG],
                                            "max_eur_per_order": 25.0, "max_slippage_pct": 5.0,
                                            "min_quote_liquidity_usd": 20000.0}})
    ctx.db = Database(":memory:")
    ctx.status = ProviderStatusRegistry(ctx.db)
    ctx.rpc = ctx.blockscout = ctx.dex = None  # type: ignore[assignment]
    return ctx


def _pool(ctx, pair_id, last_block, *, liquidity=10 ** 24):
    ctx.db.insert("pairs", {"chain_id": ctx.chain_id, "pair_id": pair_id, "token_address": TOKEN, "quote_address": USDG,
                            "currency0": TOKEN, "currency1": USDG, "fee": 3000, "tick_spacing": 60,
                            "hooks": "0x" + "00" * 20, "token_is_currency0": 1, "created_block": 1,
                            "first_seen_ts": now_ts() - 3600, "updated_ts": now_ts(), "source": "test"})
    ctx.db.insert("swap_events", {"chain_id": ctx.chain_id, "tx_hash": f"0x{last_block:064x}", "log_index": 0,
                                  "block_number": last_block, "ts": now_ts() - 10, "pair_id": pair_id,
                                  "sender": "0x" + "11" * 20, "amount0": "1", "amount1": "1",
                                  "sqrt_price_x96": str(Q96), "liquidity": str(liquidity), "tick": 0, "fee": 3000,
                                  "source": "test"})


def _decision(ctx, kind=safety.BUY, size=20.0):
    return ctx.db.insert("decisions", {"ts": now_ts(), "chain_id": ctx.chain_id, "token_address": TOKEN, "label": "T",
                                       "kind": kind, "reason": "test", "price": 1.0, "size_eur": size, "sent": 1})


def _market(ctx, liq=60_000.0):
    ctx.db.insert("token_snapshots", {"ts": now_ts(), "chain_id": ctx.chain_id, "token_address": TOKEN,
                                      "source": "test", "price_usd": 1.0, "liquidity_usd": liq})


def test_a_buy_becomes_a_built_order_in_dry_run():
    ctx = _ctx()
    _pool(ctx, POOL, 200)
    _market(ctx)
    _decision(ctx)
    out = asyncio.run(run_once(ctx))
    assert out == {"mode": "dry_run", "seen": 1, "built": 1, "refused": 0, "submitted": 0, "failed": 0}
    row = ctx.db.query_one("SELECT * FROM executions WHERE chain_id=?", (ctx.chain_id,))
    assert row["status"] == "BUILT" and row["tx_hash"] is None
    # the order carries a real minimum and real calldata, not a placeholder
    assert 0 < int(row["min_amount_out"]) < int(row["quoted_amount_out"])
    assert row["calldata"].startswith("0x") and len(row["calldata"]) > 200


def test_the_same_decision_is_never_acted_on_twice():
    ctx = _ctx()
    _pool(ctx, POOL, 200)
    _market(ctx)
    _decision(ctx)
    asyncio.run(run_once(ctx))
    again = asyncio.run(run_once(ctx))
    assert again["seen"] == 0
    assert ctx.db.scalar("SELECT COUNT(*) FROM executions WHERE chain_id=?", (ctx.chain_id,), 0) == 1


def test_a_token_with_no_allowed_pool_is_refused_not_skipped():
    ctx = _ctx()
    _market(ctx)
    _decision(ctx)
    out = asyncio.run(run_once(ctx))
    assert out["refused"] == 1
    row = ctx.db.query_one("SELECT status, refused_reason FROM executions WHERE chain_id=?", (ctx.chain_id,))
    assert row["status"] == "REFUSED" and "pool" in row["refused_reason"]


def test_an_oversized_order_is_refused_by_the_envelope():
    ctx = _ctx()
    _pool(ctx, POOL, 200)
    _market(ctx)
    _decision(ctx, size=500.0)      # above max_eur_per_order
    out = asyncio.run(run_once(ctx))
    assert out["refused"] == 1
    reason = ctx.db.query_one("SELECT refused_reason FROM executions WHERE chain_id=?", (ctx.chain_id,))["refused_reason"]
    assert "plafond" in reason


def test_thin_liquidity_is_refused():
    ctx = _ctx()
    _pool(ctx, POOL, 200)
    _market(ctx, liq=1_000.0)
    _decision(ctx)
    assert asyncio.run(run_once(ctx))["refused"] == 1


def test_selling_without_knowing_the_balance_is_refused():
    ctx = _ctx()
    _pool(ctx, POOL, 200)
    _market(ctx)
    # the token is fully known; what is missing is any position of ours to sell
    ctx.db.insert("tokens", {"chain_id": ctx.chain_id, "address": TOKEN, "symbol": "T", "name": "T", "decimals": 18,
                             "first_seen_ts": now_ts() - 7200, "updated_ts": now_ts()})
    _decision(ctx, kind=safety.SELL_ALL, size=None)
    out = asyncio.run(run_once(ctx))
    assert out["refused"] == 1
    reason = ctx.db.query_one("SELECT refused_reason FROM executions WHERE chain_id=?", (ctx.chain_id,))["refused_reason"]
    assert "aveugle" in reason


def _position(ctx, size_eur=20.0, entry=1.0, status="OPEN"):
    return ctx.db.insert("positions", {"chain_id": ctx.chain_id, "token_address": TOKEN, "label": "T", "kind": "VIRTUAL",
                                       "opened_ts": now_ts() - 600, "entry_price": entry, "size_eur": size_eur,
                                       "status": status, "peak_price": entry})


def test_a_sell_is_sized_from_our_own_position_not_from_a_chain_holder():
    """Regression: sizing a sell from an observed holder's balance gave a 103 352 % price impact."""
    ctx = _ctx()
    _pool(ctx, POOL, 200)
    _market(ctx)
    _position(ctx, size_eur=20.0, entry=1.0)
    # a whale's balance sits in the observed-holders table and must be ignored entirely
    ctx.db.insert("wallet_token_positions", {"chain_id": ctx.chain_id, "address": "0x" + "99" * 20,
                                             "token_address": TOKEN, "balance": "1" + "0" * 30,
                                             "balance_float": 1e12, "ts": now_ts(), "source": "test"})
    ctx.db.insert("tokens", {"chain_id": ctx.chain_id, "address": TOKEN, "symbol": "T", "name": "T", "decimals": 18,
                             "first_seen_ts": now_ts() - 7200, "updated_ts": now_ts()})
    d = dict(ctx.db.query_one("SELECT * FROM decisions WHERE id=?", (_decision(ctx, kind=safety.SELL_ALL, size=None),)))
    res = prepare(ctx, d, limits=safety.Limits.from_config(ctx), eur_usd=1.0)
    assert res["status"] == "BUILT", res.get("refused_reason")
    # 20 EUR at an entry price of 1 USD is 20 tokens, not the whale's 1e12
    assert int(res["amount_in"]) == 20 * 10 ** 18


def test_a_half_sold_position_only_offers_what_is_left():
    ctx = _ctx()
    _pool(ctx, POOL, 200)
    _market(ctx)
    _position(ctx, size_eur=20.0, entry=1.0, status="HALF")
    ctx.db.insert("tokens", {"chain_id": ctx.chain_id, "address": TOKEN, "symbol": "T", "name": "T", "decimals": 18,
                             "first_seen_ts": now_ts() - 7200, "updated_ts": now_ts()})
    d = dict(ctx.db.query_one("SELECT * FROM decisions WHERE id=?", (_decision(ctx, kind=safety.SELL_ALL, size=None),)))
    res = prepare(ctx, d, limits=safety.Limits.from_config(ctx), eur_usd=1.0)
    assert int(res["amount_in"]) == 10 * 10 ** 18


def test_a_stale_decision_is_dropped_rather_than_executed_late():
    ctx = _ctx()
    _pool(ctx, POOL, 200)
    _market(ctx)
    old = ctx.db.insert("decisions", {"ts": now_ts() - 4 * 3600, "chain_id": ctx.chain_id, "token_address": TOKEN,
                                      "label": "T", "kind": safety.BUY, "reason": "old", "price": 1.0,
                                      "size_eur": 20.0, "sent": 1})
    out = asyncio.run(run_once(ctx))
    assert out["refused"] == 1
    row = ctx.db.query_one("SELECT refused_reason FROM executions WHERE decision_id=?", (old,))
    assert "vieille" in row["refused_reason"]


def test_the_pool_with_the_freshest_activity_is_chosen():
    ctx = _ctx()
    _pool(ctx, OLD_POOL, 100)
    _pool(ctx, POOL, 999)
    assert choose_pool(ctx, TOKEN, (USDG,))["pair_id"] == POOL


def test_a_pool_quoted_in_a_forbidden_asset_is_ignored():
    ctx = _ctx()
    _pool(ctx, POOL, 200)
    assert choose_pool(ctx, TOKEN, ("0x" + "99" * 20,)) is None


def test_decisions_are_taken_oldest_first():
    ctx = _ctx()
    _pool(ctx, POOL, 200)
    _market(ctx)
    first = _decision(ctx)
    second = _decision(ctx)
    assert [d["id"] for d in pending_decisions(ctx)] == [first, second]


NATIVE = "0x" + "00" * 20


def test_native_eth_is_priced_through_its_wrapped_twin():
    """Native ETH has no contract and no snapshot of its own; WETH is what trades."""
    from intel.execution.executor import quote_price_usd

    ctx = _ctx()
    wrapped = next(a for a, m in ctx.config.quote_assets.items() if m.get("kind") == "native_wrapped")
    ctx.db.insert("token_snapshots", {"ts": now_ts(), "chain_id": ctx.chain_id, "token_address": wrapped,
                                      "source": "test", "price_usd": 2500.0})
    assert quote_price_usd(ctx, NATIVE) == 2500.0
    assert quote_price_usd(ctx, USDG) == 1.0            # a stable is worth its face value
    assert quote_price_usd(ctx, "0x" + "77" * 20) is None  # unknown stays unknown, never zero


def test_an_eth_quoted_order_carries_the_value_and_needs_no_approval():
    ctx = _ctx()
    ctx.config.data["execution"]["allowed_quotes"] = [USDG, NATIVE]
    wrapped = next(a for a, m in ctx.config.quote_assets.items() if m.get("kind") == "native_wrapped")
    ctx.db.insert("token_snapshots", {"ts": now_ts(), "chain_id": ctx.chain_id, "token_address": wrapped,
                                      "source": "test", "price_usd": 2500.0})
    ctx.db.insert("pairs", {"chain_id": ctx.chain_id, "pair_id": POOL, "token_address": TOKEN, "quote_address": NATIVE,
                            "currency0": NATIVE, "currency1": TOKEN, "fee": 3000, "tick_spacing": 60,
                            "hooks": "0x" + "00" * 20, "token_is_currency0": 0, "created_block": 1,
                            "first_seen_ts": now_ts() - 3600, "updated_ts": now_ts(), "source": "test"})
    ctx.db.insert("swap_events", {"chain_id": ctx.chain_id, "tx_hash": "0x" + "1" * 64, "log_index": 0,
                                  "block_number": 200, "ts": now_ts() - 10, "pair_id": POOL, "sender": "0x" + "11" * 20,
                                  "amount0": "1", "amount1": "1", "sqrt_price_x96": str(Q96),
                                  "liquidity": str(10 ** 24), "tick": 0, "fee": 3000, "source": "test"})
    _market(ctx)
    d = dict(ctx.db.query_one("SELECT * FROM decisions WHERE id=?", (_decision(ctx),)))
    res = prepare(ctx, d, limits=safety.Limits.from_config(ctx), eur_usd=1.0)
    assert res["status"] == "BUILT", res.get("refused_reason")
    # 20 USD of ETH at 2500 USD is 0.008 ETH, attached as the transaction's value
    assert int(res["amount_in"]) == int(0.008 * 10 ** 18)
    assert res["order"].value_wei == int(res["amount_in"])


def test_dry_run_still_prices_against_real_pool_state():
    # a dry run that skipped the quote would prove nothing: the built order must reflect the pool
    ctx = _ctx()
    _pool(ctx, POOL, 200, liquidity=10 ** 24)
    _market(ctx)
    d = dict(ctx.db.query_one("SELECT * FROM decisions WHERE id=?", (_decision(ctx),)))
    res = prepare(ctx, d, limits=safety.Limits.from_config(ctx))
    assert res["status"] == "BUILT"
    assert int(res["quoted_amount_out"]) > 0
    # The journalled slippage is the MEASURED impact, not the tolerance we allow: on a deep pool it
    # is legitimately near zero, and it must grow when the same order meets a thinner pool. Recording
    # the tolerance there (2026-09-07) made every live buy read "8.0 %" and hid the real figure.
    deep = float(res["slippage_pct"])
    ctx2 = _ctx()
    _pool(ctx2, POOL, 200, liquidity=10 ** 20)
    _market(ctx2)
    d2 = dict(ctx2.db.query_one("SELECT * FROM decisions WHERE id=?", (_decision(ctx2),)))
    thin = float(prepare(ctx2, d2, limits=safety.Limits.from_config(ctx2))["slippage_pct"])
    assert thin > deep, f"un pool plus mince doit coûter plus cher: {thin} vs {deep}"
