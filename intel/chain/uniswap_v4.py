"""Uniswap v4 decoding helpers (PoolManager singleton, bytes32 PoolIds).

Sign convention (verified on Robinhood Chain tx 0xef10f67a...): ``Swap.amount0/amount1``
are the swapper's balance deltas — negative = paid into the pool, positive = received.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from intel.chain.constants import TOPIC_V4_INITIALIZE, TOPIC_V4_MODIFY_LIQUIDITY, TOPIC_V4_SWAP, V4_DYNAMIC_FEE_FLAG
from intel.utils.abi import decode, encode, keccak256, topic_to_address

Q96 = 2 ** 96
# Tick range bounds. A swap that lands on one of them emptied one side of the pool: the
# reported sqrtPriceX96 is the clamp value, not a price anything could trade at.
MIN_SQRT_PRICE = 4295128739
MAX_SQRT_PRICE = 1461446703485210103287273052203988822378723970342


def is_price_at_bound(sqrt_price_x96: int, tolerance: float = 1e-4) -> bool:
    """True when the pool sits at (or within ``tolerance`` of) a tick boundary."""
    if sqrt_price_x96 <= 0:
        return True
    return sqrt_price_x96 <= MIN_SQRT_PRICE * (1 + tolerance) or sqrt_price_x96 >= MAX_SQRT_PRICE * (1 - tolerance)


@dataclass(frozen=True)
class PoolKey:
    currency0: str
    currency1: str
    fee: int
    tick_spacing: int
    hooks: str

    @property
    def pool_id(self) -> str:
        return compute_pool_id(self.currency0, self.currency1, self.fee, self.tick_spacing, self.hooks)

    @property
    def dynamic_fee(self) -> bool:
        return bool(self.fee & V4_DYNAMIC_FEE_FLAG)

    def as_tuple(self) -> tuple[str, str, int, int, str]:
        return (self.currency0, self.currency1, self.fee, self.tick_spacing, self.hooks)


@dataclass(frozen=True)
class PoolInitialize:
    pool_id: str
    currency0: str
    currency1: str
    fee: int
    tick_spacing: int
    hooks: str
    sqrt_price_x96: int
    tick: int
    block_number: int
    tx_hash: str
    log_index: int

    @property
    def key(self) -> PoolKey:
        return PoolKey(self.currency0, self.currency1, self.fee, self.tick_spacing, self.hooks)


@dataclass(frozen=True)
class SwapEvent:
    pool_id: str
    sender: str
    amount0: int
    amount1: int
    sqrt_price_x96: int
    liquidity: int
    tick: int
    fee: int
    block_number: int
    tx_hash: str
    log_index: int


@dataclass(frozen=True)
class ModifyLiquidityEvent:
    pool_id: str
    sender: str
    tick_lower: int
    tick_upper: int
    liquidity_delta: int
    salt: str
    block_number: int
    tx_hash: str
    log_index: int


def compute_pool_id(currency0: str, currency1: str, fee: int, tick_spacing: int, hooks: str) -> str:
    return "0x" + keccak256(encode(["address", "address", "uint24", "int24", "address"], [currency0, currency1, fee, tick_spacing, hooks])).hex()


def _bn(lg: dict[str, Any]) -> int:
    v = lg["blockNumber"]
    return int(v, 16) if isinstance(v, str) else int(v)


def _li(lg: dict[str, Any]) -> int:
    v = lg.get("logIndex") or "0x0"
    return int(v, 16) if isinstance(v, str) else int(v)


def decode_initialize(lg: dict[str, Any]) -> PoolInitialize:
    topics = lg["topics"]
    if topics[0].lower() != TOPIC_V4_INITIALIZE:
        raise ValueError("not an Initialize log")
    fee, tick_spacing, hooks, sqrt_price, tick = decode(["uint24", "int24", "address", "uint160", "int24"], lg["data"])
    return PoolInitialize(
        pool_id=topics[1].lower(),
        currency0=topic_to_address(topics[2]),
        currency1=topic_to_address(topics[3]),
        fee=int(fee),
        tick_spacing=_signed(tick_spacing, 24),
        hooks=hooks,
        sqrt_price_x96=int(sqrt_price),
        tick=_signed(tick, 24),
        block_number=_bn(lg),
        tx_hash=lg["transactionHash"].lower(),
        log_index=_li(lg),
    )


def decode_swap(lg: dict[str, Any]) -> SwapEvent:
    topics = lg["topics"]
    if topics[0].lower() != TOPIC_V4_SWAP:
        raise ValueError("not a Swap log")
    a0, a1, sqrt_price, liq, tick, fee = decode(["int128", "int128", "uint160", "uint128", "int24", "uint24"], lg["data"])
    return SwapEvent(
        pool_id=topics[1].lower(),
        sender=topic_to_address(topics[2]),
        amount0=_signed(a0, 128),
        amount1=_signed(a1, 128),
        sqrt_price_x96=int(sqrt_price),
        liquidity=int(liq),
        tick=_signed(tick, 24),
        fee=int(fee),
        block_number=_bn(lg),
        tx_hash=lg["transactionHash"].lower(),
        log_index=_li(lg),
    )


def decode_modify_liquidity(lg: dict[str, Any]) -> ModifyLiquidityEvent:
    topics = lg["topics"]
    if topics[0].lower() != TOPIC_V4_MODIFY_LIQUIDITY:
        raise ValueError("not a ModifyLiquidity log")
    tl, tu, delta, salt = decode(["int24", "int24", "int256", "bytes32"], lg["data"])
    return ModifyLiquidityEvent(
        pool_id=topics[1].lower(),
        sender=topic_to_address(topics[2]),
        tick_lower=_signed(tl, 24),
        tick_upper=_signed(tu, 24),
        liquidity_delta=int(delta),
        salt=salt,
        block_number=_bn(lg),
        tx_hash=lg["transactionHash"].lower(),
        log_index=_li(lg),
    )


def _signed(v: int, bits: int) -> int:
    """Our decoder returns int256 semantics; re-wrap narrower ints that were encoded unsigned."""
    v = int(v)
    if v >= (1 << (bits - 1)):
        v -= 1 << bits
    elif v < -(1 << (bits - 1)):
        v += 1 << 256
        if v >= (1 << (bits - 1)):
            v -= 1 << bits
    return v


# --------------------------------------------------------------------------- #
# price math
# --------------------------------------------------------------------------- #
def sqrt_price_to_price0_in_1(sqrt_price_x96: int, dec0: int, dec1: int) -> float:
    """Price of one unit of currency0 expressed in currency1 (human units)."""
    if sqrt_price_x96 <= 0:
        return 0.0
    ratio = (sqrt_price_x96 / Q96) ** 2  # raw token1 per raw token0
    return ratio * (10 ** dec0) / (10 ** dec1)


def token_price_in_quote(sqrt_price_x96: int, token_is_currency0: bool, token_decimals: int, quote_decimals: int) -> float:
    if token_is_currency0:
        return sqrt_price_to_price0_in_1(sqrt_price_x96, token_decimals, quote_decimals)
    p0 = sqrt_price_to_price0_in_1(sqrt_price_x96, quote_decimals, token_decimals)  # quote priced in token
    return 1.0 / p0 if p0 else 0.0


def virtual_reserves(liquidity: int, sqrt_price_x96: int) -> tuple[float, float]:
    """Full-range-equivalent virtual reserves (raw units) for in-range liquidity L.

    For concentrated positions this is an upper bound on depth around the current price
    (approximation; flagged as such by callers).
    """
    if liquidity <= 0 or sqrt_price_x96 <= 0:
        return 0.0, 0.0
    sp = sqrt_price_x96 / Q96
    reserve0 = liquidity / sp
    reserve1 = liquidity * sp
    return reserve0, reserve1


def cpmm_price_impact(reserve_in: float, reserve_out: float, amount_in: float, fee_bps: float = 0.0) -> float | None:
    """Constant-product price impact of ``amount_in`` (same units as reserve_in)."""
    if reserve_in <= 0 or reserve_out <= 0 or amount_in <= 0:
        return None
    eff = amount_in * (1 - fee_bps / 10000.0)
    out = reserve_out * eff / (reserve_in + eff)
    mid = reserve_out / reserve_in
    exec_price = out / amount_in
    return max(0.0, 1.0 - exec_price / mid)


def swap_token_and_quote_deltas(ev: SwapEvent, token_is_currency0: bool) -> tuple[int, int]:
    """Return (token_delta, quote_delta) from the swapper's perspective."""
    return (ev.amount0, ev.amount1) if token_is_currency0 else (ev.amount1, ev.amount0)
