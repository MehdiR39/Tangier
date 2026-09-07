"""Trade reconstruction: settler routing, hook-internal swaps, round trips, mismatches."""
from intel.chain.uniswap_v4 import SwapEvent
from intel.ingest.pools import PoolInfo
from intel.ingest.trades import TransferRow, reconstruct_tx_trades

TOKEN = "0x" + "aa" * 20
USDG = "0x" + "bb" * 20
PM = "0x" + "11" * 20
SETTLER = "0x" + "22" * 20
HOOK = "0x" + "33" * 20
USER = "0x" + "44" * 20
USER2 = "0x" + "55" * 20
POOL = "0x" + "cc" * 32
SYSTEM = {PM: "lp:pool_manager", SETTLER: "router:settler", HOOK: "hook:doppler"}
POOLS = {POOL: PoolInfo(POOL, TOKEN, USDG, True, HOOK, 0x800000, 8, 1, 1, TOKEN, USDG)}


def label(a):
    return SYSTEM.get(a)


def qdec(_q):
    return 6


def qusd(_q, _ts):
    return 1.0, []


def swap(td, qd, sender=SETTLER, li=5):
    return SwapEvent(POOL, sender, td, qd, 10 ** 20, 10 ** 18, 0, 0, 100, "0xtx", li)


def tr(frm, to, v, li):
    return TransferRow("0xtx", li, 100, 1700000000, frm, to, v)


def test_buy_routed_through_settler_attributes_final_recipient():
    transfers = [tr(PM, SETTLER, 12_000 * 10 ** 18, 1), tr(SETTLER, USER, 12_000 * 10 ** 18, 2)]
    swaps = [swap(12_000 * 10 ** 18, -36_000_000)]  # paid 36 USDG (6 dec)
    trades = reconstruct_tx_trades(TOKEN, 18, transfers, swaps, POOLS, label, qdec, qusd)
    assert len(trades) == 1
    t = trades[0]
    assert t.trader == USER and t.side == "BUY"
    assert abs(t.token_amount_float - 12000) < 1e-9
    assert abs(t.quote_amount_float - 36.0) < 1e-9
    assert abs(t.price_native - 0.003) < 1e-12 and abs(t.usd_value - 36.0) < 1e-9
    assert "transfer_swap_mismatch" not in t.quality_flags


def test_hook_internal_swaps_are_excluded():
    transfers = [tr(USER, PM, 25_578 * 10 ** 18, 1), tr(PM, HOOK, 48 * 10 ** 18, 2), tr(HOOK, PM, 48 * 10 ** 18, 3)]
    swaps = [swap(-25_578 * 10 ** 18, 758_500, li=4), swap(48 * 10 ** 18, -1440, sender=HOOK, li=5), swap(24 * 10 ** 18, -720, sender=HOOK, li=6)]
    trades = reconstruct_tx_trades(TOKEN, 18, transfers, swaps, POOLS, label, qdec, qusd)
    assert len(trades) == 1
    t = trades[0]
    assert t.side == "SELL" and t.trader == USER
    assert abs(t.quote_amount_float - 0.7585) < 1e-9  # only the user-level swap counts
    assert t.swap_log_count == 3


def test_same_tx_roundtrip_flagged():
    transfers = [tr(PM, USER, 1000 * 10 ** 18, 1), tr(USER, PM, 1000 * 10 ** 18, 2)]
    swaps = [swap(1000 * 10 ** 18, -3_000_000, li=3), swap(-1000 * 10 ** 18, 2_900_000, li=4)]
    trades = reconstruct_tx_trades(TOKEN, 18, transfers, swaps, POOLS, label, qdec, qusd)
    assert len(trades) == 1 and trades[0].side == "ROUNDTRIP" and "same_tx_roundtrip" in trades[0].quality_flags


def test_unlabeled_passthrough_router_is_not_a_roundtrip():
    # sell path observed on-chain: user -> unlabeled contract X -> unlabeled contract Y -> PoolManager
    X = "0x" + "66" * 20
    Y = "0x" + "77" * 20
    transfers = [tr(USER, X, 2183 * 10 ** 18, 1), tr(X, Y, 2183 * 10 ** 18, 2), tr(Y, PM, 2183 * 10 ** 18, 3)]
    swaps = [swap(-2183 * 10 ** 18, 7_690_000, sender=Y, li=4)]
    trades = reconstruct_tx_trades(TOKEN, 18, transfers, swaps, POOLS, label, qdec, qusd)
    assert [t.side for t in trades] == ["SELL"] and trades[0].trader == USER
    assert all(t.side != "ROUNDTRIP" for t in trades)


def test_plain_transfer_is_not_a_trade():
    transfers = [tr(USER, USER2, 5 * 10 ** 18, 1)]
    assert reconstruct_tx_trades(TOKEN, 18, transfers, [], POOLS, label, qdec, qusd) == []


def test_split_buy_two_recipients_share_quote_proportionally():
    transfers = [tr(PM, SETTLER, 300 * 10 ** 18, 1), tr(SETTLER, USER, 100 * 10 ** 18, 2), tr(SETTLER, USER2, 200 * 10 ** 18, 3)]
    swaps = [swap(300 * 10 ** 18, -900_000)]
    trades = reconstruct_tx_trades(TOKEN, 18, transfers, swaps, POOLS, label, qdec, qusd)
    by = {t.trader: t for t in trades}
    assert abs(by[USER].quote_amount_float - 0.3) < 1e-9 and abs(by[USER2].quote_amount_float - 0.6) < 1e-9


def test_mismatch_flag_when_transfers_disagree_with_swaps():
    transfers = [tr(PM, USER, 500 * 10 ** 18, 1)]
    swaps = [swap(1000 * 10 ** 18, -3_000_000)]  # swap price = 3 USDG / 1000 tokens = 0.003
    trades = reconstruct_tx_trades(TOKEN, 18, transfers, swaps, POOLS, label, qdec, qusd)
    assert trades and "transfer_swap_mismatch" in trades[0].quality_flags
    # price must come from the swap, never from dividing the whole quote leg by a partial amount
    assert abs(trades[0].price_native - 0.003) < 1e-12
    assert abs(trades[0].usd_value - 1.5) < 1e-9
