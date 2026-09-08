"""The safety envelope: every refusal path, one case at a time.

This is the only thing standing between a scoring bug and real money, so each limit is asserted
on its own rather than through a single happy-path test.
"""
from intel.context import IntelContext
from intel.db.connection import Database
from intel.execution.safety import BUY, SELL_ALL, Limits, check, spent_today
from intel.providers.base import ProviderStatusRegistry
from intel.settings import IntelConfig, Settings
from intel.utils.timeutil import now_ts

USDG = "0x5fc5360d0400a0fd4f2af552add042d716f1d168"
TOKEN = "0x" + "aa" * 20


def _ctx() -> IntelContext:
    ctx = IntelContext.__new__(IntelContext)
    ctx.settings = Settings.load(db_path=":memory:", telegram_dry_run=True)
    ctx.config = IntelConfig()
    ctx.db = Database(":memory:")
    ctx.status = ProviderStatusRegistry(ctx.db)
    ctx.rpc = ctx.blockscout = ctx.dex = None  # type: ignore[assignment]
    return ctx


def _limits(**kw) -> Limits:
    base = dict(max_eur_per_order=25.0, max_open_positions=15, max_orders_per_day=40, max_eur_per_day=200.0,
                max_slippage_pct=5.0, min_quote_liquidity_usd=20_000.0, allowed_quotes=(USDG,), kill_switch=False)
    base.update(kw)
    return Limits(**base)


def _order(**kw):
    o = {"kind": BUY, "token": TOKEN, "quote": USDG, "size_eur": 20.0, "slippage_pct": 2.0, "quote_liquidity_usd": 60_000.0}
    o.update(kw)
    return o


def test_a_correct_order_passes():
    assert check(_ctx(), _order(), _limits()).allowed


def test_kill_switch_refuses_everything():
    v = check(_ctx(), _order(), _limits(kill_switch=True))
    assert not v.allowed and "arrêt d'urgence" in v.why


def test_unknown_quote_is_refused_by_default():
    # an empty allowlist means nothing is tradeable, not everything
    assert not check(_ctx(), _order(), _limits(allowed_quotes=())).allowed
    assert not check(_ctx(), _order(quote="0x" + "bb" * 20), _limits()).allowed


def test_order_size_ceiling_is_absolute():
    assert not check(_ctx(), _order(size_eur=26.0), _limits()).allowed
    assert not check(_ctx(), _order(size_eur=0.0), _limits()).allowed
    assert not check(_ctx(), _order(size_eur=None), _limits()).allowed


def test_unknown_values_are_never_treated_as_safe():
    assert not check(_ctx(), _order(quote_liquidity_usd=None), _limits()).allowed
    assert not check(_ctx(), _order(slippage_pct=None), _limits()).allowed
    assert not check(_ctx(), _order(kind="TRANSFER"), _limits()).allowed
    assert not check(_ctx(), _order(token="not-an-address"), _limits()).allowed


def test_slippage_ceiling():
    assert check(_ctx(), _order(slippage_pct=5.0), _limits()).allowed
    assert not check(_ctx(), _order(slippage_pct=5.1), _limits()).allowed


def test_thin_liquidity_is_refused():
    assert not check(_ctx(), _order(quote_liquidity_usd=19_999.0), _limits()).allowed


def test_open_position_ceiling():
    ctx = _ctx()
    for i in range(15):
        ctx.db.insert("positions", {"chain_id": ctx.chain_id, "token_address": f"0x{i:040x}", "label": "x", "kind": "VIRTUAL",
                                    "opened_ts": now_ts(), "status": "OPEN", "size_eur": 20.0})
    v = check(ctx, _order(), _limits())
    assert not v.allowed and "positions ouvertes" in v.why


def test_daily_count_and_amount_ceilings_come_from_the_journal():
    ctx = _ctx()
    for i in range(3):
        ctx.db.insert("executions", {"ts": now_ts() - 60, "chain_id": ctx.chain_id, "token_address": TOKEN, "kind": BUY,
                                     "size_eur": 60.0, "mode": "live", "status": "SUBMITTED"})
    assert spent_today(ctx) == (3, 180.0)
    # 180 already committed today: a 20 EUR order fits, a 21 EUR one does not
    assert check(ctx, _order(size_eur=20.0), _limits()).allowed
    assert not check(ctx, _order(size_eur=21.0), _limits()).allowed
    assert not check(ctx, _order(), _limits(max_orders_per_day=3)).allowed


def test_refused_orders_do_not_count_towards_the_daily_budget():
    ctx = _ctx()
    ctx.db.insert("executions", {"ts": now_ts() - 60, "chain_id": ctx.chain_id, "token_address": TOKEN, "kind": BUY,
                                 "size_eur": 500.0, "mode": "live", "status": "REFUSED"})
    assert spent_today(ctx) == (0, 0.0)


def test_a_sell_is_not_subject_to_the_buy_budget():
    ctx = _ctx()
    for i in range(40):
        ctx.db.insert("executions", {"ts": now_ts() - 60, "chain_id": ctx.chain_id, "token_address": TOKEN, "kind": BUY,
                                     "size_eur": 20.0, "mode": "live", "status": "SUBMITTED"})
    # getting out must never be blocked by how much was spent getting in
    assert check(ctx, _order(kind=SELL_ALL, size_eur=None), _limits()).allowed


def test_every_reason_is_reported_not_just_the_first():
    v = check(_ctx(), _order(size_eur=999.0, slippage_pct=50.0, quote_liquidity_usd=1.0), _limits())
    assert not v.allowed and len(v.reasons) >= 3


def test_a_sell_is_not_blocked_by_the_quote_allowlist():
    # The allowlist says what we are willing to SPEND. A token whose only living pool is quoted
    # outside it must still be sellable: on 2026-09-07 a bag was written off as unsellable while
    # a pool in another quote would have paid for it.
    other = "0x" + "cc" * 20
    assert not check(_ctx(), _order(quote=other), _limits()).allowed          # buying there: refused
    assert check(_ctx(), _order(kind=SELL_ALL, quote=other, size_eur=None), _limits()).allowed


def test_the_entry_slippage_ceiling_does_not_wall_in_a_sell():
    # 7.5 % impact refused an exit on 2026-09-07 while the bag's only alternative was zero.
    # Buying at that price stays refused; leaving is judged against the looser exit ceiling.
    assert not check(_ctx(), _order(slippage_pct=7.5), _limits()).allowed
    assert check(_ctx(), _order(kind=SELL_ALL, size_eur=None, slippage_pct=7.5), _limits()).allowed
    v = check(_ctx(), _order(kind=SELL_ALL, size_eur=None, slippage_pct=95.0), _limits())
    assert not v.allowed and "impact de sortie" in v.why


def test_selling_does_not_consume_the_daily_buying_allowance():
    """Exits must not spend the entry budget.

    On 2026-09-08 fourteen buys were refused for "41 orders today >= 40" while most of those
    orders were sales, and every retried sale ate a little more of the allowance.
    """
    ctx = _ctx()
    for _ in range(40):
        ctx.db.insert("executions", {"ts": now_ts() - 60, "chain_id": ctx.chain_id, "token_address": TOKEN,
                                     "kind": SELL_ALL, "size_eur": 20.0, "mode": "live", "status": "CONFIRMED"})
    assert spent_today(ctx) == (0, 0.0), "une vente n'engage rien du budget d'achat"
    assert check(ctx, _order(), _limits()).allowed


def test_bags_awaiting_recovery_do_not_forbid_new_purchases():
    """A written-off bag reopened to be retried is not a working position.

    On 2026-09-08 seventeen dead bags filled the open-position ceiling and every new purchase was
    refused, so the experiment that was supposed to answer whether the book still works never ran.
    """
    ctx = _ctx()
    for i in range(20):
        ctx.db.insert("positions", {"chain_id": ctx.chain_id, "token_address": f"0x{i:040d}", "kind": "PORTFOLIO",
                                    "opened_ts": now_ts() - 3600, "status": "OPEN", "model_version": "t1-watcher-v0.1",
                                    "notes": f"decision:{i} recover:3"})
    assert check(ctx, _order(model_version="t1-watcher-v0.1"), _limits()).allowed
