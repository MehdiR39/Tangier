"""Build and price a Uniswap v4 swap through the UniversalRouter.

Nothing here signs or sends. It produces the exact calldata a transaction would carry, and the
minimum output that calldata enforces on-chain, so an order can be inspected in full before any
key is involved.

The v4 singleton holds all pools, so a swap is expressed as a PoolKey plus a direction rather
than a pair address. The router takes a command string and one input blob per command; the
V4_SWAP command carries its own sub-encoding of actions and their parameters.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from intel.utils.abi import encode, encode_call, norm_address
from intel.utils.timeutil import now_ts

log = logging.getLogger(__name__)

# UniversalRouter command byte for a Uniswap v4 swap.
CMD_V4_SWAP = 0x10
# v4 router actions (Actions library).
ACTION_SWAP_EXACT_IN_SINGLE = 0x06
ACTION_SETTLE_ALL = 0x0c
ACTION_TAKE_ALL = 0x0f

EXACT_IN_SINGLE_TUPLE = (
    "((address,address,uint24,int24,address),bool,uint128,uint128,bytes)"
)


@dataclass(frozen=True)
class PoolKey:
    currency0: str
    currency1: str
    fee: int
    tick_spacing: int
    hooks: str

    def as_tuple(self) -> tuple[Any, ...]:
        return (norm_address(self.currency0), norm_address(self.currency1), int(self.fee), int(self.tick_spacing), norm_address(self.hooks))


@dataclass(frozen=True)
class Order:
    """Everything needed to inspect, price and (later) sign one swap."""
    token: str
    quote: str
    kind: str
    zero_for_one: bool          # True when spending currency0 to receive currency1
    amount_in: int              # raw units of the currency being spent
    min_amount_out: int         # raw units, after the slippage limit
    quoted_amount_out: int      # raw units, before the slippage limit
    slippage_pct: float
    value_wei: int              # native value to attach (non-zero only when spending native ETH)
    calldata: str
    router: str
    deadline: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "token": self.token, "quote": self.quote, "kind": self.kind, "amount_in": str(self.amount_in),
            "min_amount_out": str(self.min_amount_out), "quoted_amount_out": str(self.quoted_amount_out),
            "slippage_pct": self.slippage_pct, "value_wei": str(self.value_wei), "router": self.router,
            "deadline": self.deadline, "calldata": self.calldata,
        }


def _v4_swap_input(key: PoolKey, *, zero_for_one: bool, amount_in: int, min_amount_out: int,
                   currency_in: str, currency_out: str, hook_data: bytes = b"") -> bytes:
    """The single input blob carried by the V4_SWAP command: actions + one param per action."""
    actions = bytes([ACTION_SWAP_EXACT_IN_SINGLE, ACTION_SETTLE_ALL, ACTION_TAKE_ALL])
    swap_params = encode(
        [EXACT_IN_SINGLE_TUPLE],
        [(key.as_tuple(), bool(zero_for_one), int(amount_in), int(min_amount_out), hook_data)],
    )
    settle = encode(["address", "uint256"], [norm_address(currency_in), int(amount_in)])
    take = encode(["address", "uint256"], [norm_address(currency_out), int(min_amount_out)])
    return encode(["bytes", "bytes[]"], [actions, [swap_params, settle, take]])


def build_swap(*, key: PoolKey, token: str, quote: str, kind: str, zero_for_one: bool, amount_in: int,
               quoted_amount_out: int, slippage_pct: float, router: str, deadline_s: int = 120,
               native_quote: bool = False) -> Order:
    """Assemble the router calldata for one exact-input swap.

    ``quoted_amount_out`` is what the pool is expected to return; the on-chain minimum is that
    figure reduced by ``slippage_pct``. The minimum is the only protection the transaction itself
    carries, so it is computed here and never left to a caller's default.
    """
    if amount_in <= 0:
        raise ValueError("amount_in must be positive")
    if not 0 <= slippage_pct < 100:
        raise ValueError("slippage_pct out of range")
    currency_in, currency_out = (key.currency0, key.currency1) if zero_for_one else (key.currency1, key.currency0)
    min_out = int(quoted_amount_out * (1.0 - slippage_pct / 100.0))
    if min_out <= 0:
        raise ValueError("minimum output collapses to zero: refuse to send an unprotected swap")
    blob = _v4_swap_input(key, zero_for_one=zero_for_one, amount_in=amount_in, min_amount_out=min_out,
                          currency_in=currency_in, currency_out=currency_out)
    deadline = now_ts() + int(deadline_s)
    calldata = encode_call("execute(bytes,bytes[],uint256)", [bytes([CMD_V4_SWAP]), [blob], deadline])
    return Order(
        token=norm_address(token), quote=norm_address(quote), kind=kind, zero_for_one=zero_for_one,
        amount_in=int(amount_in), min_amount_out=min_out, quoted_amount_out=int(quoted_amount_out),
        # Native value rides along only when we SPEND native ETH, i.e. a buy on a native-quoted
        # pool. A sell spends tokens: attaching amount_in as ETH there asked the chain for
        # 70 111 ETH on the first real sell (2026-09-07) and was refused for insufficient funds.
        slippage_pct=float(slippage_pct), value_wei=int(amount_in) if (native_quote and kind == "BUY") else 0,
        calldata=calldata, router=norm_address(router), deadline=deadline,
    )


def expected_out_from_reserves(amount_in: int, reserve_in: float, reserve_out: float, fee_pips: int) -> int:
    """Constant-product estimate of the output, fee included.

    Concentrated liquidity makes this an upper bound rather than a promise, which is exactly why
    the order still carries an on-chain minimum: this figure sizes the trade, it does not protect it.
    """
    if amount_in <= 0 or reserve_in <= 0 or reserve_out <= 0:
        return 0
    fee = max(0.0, min(1.0, fee_pips / 1_000_000.0))
    amount_after_fee = amount_in * (1.0 - fee)
    out = reserve_out * amount_after_fee / (reserve_in + amount_after_fee)
    return max(0, int(out))
