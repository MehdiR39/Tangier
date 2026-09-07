"""Order construction: the calldata must carry the protection we think it carries."""
import pytest

from intel.execution.orders import CMD_V4_SWAP, Order, PoolKey, build_swap, expected_out_from_reserves
from intel.utils.abi import decode, selector

USDG = "0x5fc5360d0400a0fd4f2af552add042d716f1d168"
TOKEN = "0x" + "aa" * 20
ROUTER = "0xf8b30c1b77e38f2df9d058c43a3af8d47161a0c7"
KEY = PoolKey(currency0=TOKEN, currency1=USDG, fee=3000, tick_spacing=60, hooks="0x" + "00" * 20)


def _order(**kw) -> Order:
    args = dict(key=KEY, token=TOKEN, quote=USDG, kind="BUY", zero_for_one=False, amount_in=20_000_000,
                quoted_amount_out=1_000_000_000_000_000_000, slippage_pct=2.0, router=ROUTER)
    args.update(kw)
    return build_swap(**args)


def test_minimum_output_is_the_quote_minus_the_slippage():
    o = _order(quoted_amount_out=1_000, slippage_pct=2.0)
    assert o.min_amount_out == 980
    assert o.quoted_amount_out == 1_000


def test_calldata_targets_execute_and_carries_the_v4_swap_command():
    o = _order()
    assert o.calldata.startswith(selector("execute(bytes,bytes[],uint256)"))
    commands, inputs, deadline = decode(["bytes", "bytes[]", "uint256"], o.calldata[10:])
    assert commands == "0x%02x" % CMD_V4_SWAP
    assert len(inputs) == 1
    assert deadline > 0


def test_the_minimum_output_is_actually_encoded_in_the_calldata():
    # the on-chain minimum is the only protection the transaction carries: it must be inside the
    # bytes we would sign, not merely a field on the Python object
    o = _order(quoted_amount_out=10_000, slippage_pct=1.0)
    assert o.min_amount_out == 9_900
    _c, inputs, _d = decode(["bytes", "bytes[]", "uint256"], o.calldata[10:])
    actions, params = decode(["bytes", "bytes[]"], inputs[0])
    assert actions == "0x060c0f"
    assert len(params) == 3
    # TAKE_ALL carries (currency_out, minimum)
    currency_out, minimum = decode(["address", "uint256"], params[2])
    assert minimum == 9_900
    assert currency_out.lower() == TOKEN


def test_native_value_is_attached_only_for_a_native_quote():
    assert _order(native_quote=True).value_wei == 20_000_000
    assert _order(native_quote=False).value_wei == 0


def test_refuses_to_build_an_unprotected_or_impossible_swap():
    with pytest.raises(ValueError):
        _order(amount_in=0)
    with pytest.raises(ValueError):
        _order(slippage_pct=100.0)
    with pytest.raises(ValueError):
        # a quote so small that the minimum rounds to zero would let the pool return nothing
        _order(quoted_amount_out=10, slippage_pct=99.0)


def test_constant_product_estimate_accounts_for_the_fee():
    out_no_fee = expected_out_from_reserves(1_000, 1_000_000, 1_000_000, 0)
    out_fee = expected_out_from_reserves(1_000, 1_000_000, 1_000_000, 3_000)  # 0.3 %
    assert out_fee < out_no_fee <= 1_000
    assert expected_out_from_reserves(0, 1, 1, 0) == 0
    assert expected_out_from_reserves(10, 0, 1, 0) == 0
