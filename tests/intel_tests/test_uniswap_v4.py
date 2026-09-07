"""Decoding verified against logs captured from Robinhood Chain PoolManager."""
from intel.chain import uniswap_v4 as v4
from intel.chain.constants import TOPIC_V4_INITIALIZE, TOPIC_V4_SWAP

TOKEN = "0xd18528b39da6464b3662c331a52181ecb15b1e18"
MSTR = "0xec262a75e413fafd0df80480274532c79d42da09"
HOOK = "0x4e3468951d49f2eea976ed0d6e75ffcb44a9a544"
POOL_MSTR = "0xd1c2f6cb178a165a643deae8752098dea08d51b6170cd8e36e196ef03dc74751"


def _w(v: int) -> str:
    return (v % (1 << 256)).to_bytes(32, "big").hex()


def test_pool_id_matches_onchain():
    # Initialize event observed: currency0=SAYLORMOON, currency1=MSTR, fee=0x800000, tickSpacing=8, hooks=DopplerHookInitializer
    key = v4.PoolKey(TOKEN, MSTR, 0x800000, 8, HOOK)
    assert key.pool_id == POOL_MSTR
    assert key.dynamic_fee


def test_decode_initialize():
    lg = {
        "topics": [TOPIC_V4_INITIALIZE, POOL_MSTR, "0x" + "0" * 24 + TOKEN[2:], "0x" + "0" * 24 + MSTR[2:]],
        "data": "0x" + _w(0x800000) + _w(8) + _w(int(HOOK, 16)) + _w(1078956805201688333146527869297183536) + _w(-328555),
        "blockNumber": hex(48778658), "transactionHash": "0x8222fa944e" + "0" * 54, "logIndex": "0x5",
    }
    init = v4.decode_initialize(lg)
    assert init.pool_id == POOL_MSTR and init.currency0 == TOKEN and init.currency1 == MSTR
    assert init.fee == 0x800000 and init.tick_spacing == 8 and init.hooks == HOOK and init.tick == -328555
    assert init.key.pool_id == POOL_MSTR


def test_decode_swap_sign_convention():
    # user sold 25578.5 tokens (amount0 negative) for +0.7585 MSTR
    lg = {
        "topics": [TOPIC_V4_SWAP, POOL_MSTR, "0x" + "0" * 24 + "39b38686a19836ac10162c490e4558e120cbbe5f"],
        "data": "0x" + _w(-25578503961399380000000) + _w(758500000000000000) + _w(5000000000000000000000000) + _w(123456789) + _w(-300000) + _w(30000),
        "blockNumber": hex(52561000), "transactionHash": "0xef10f67a26" + "0" * 54, "logIndex": "0x9",
    }
    ev = v4.decode_swap(lg)
    assert ev.amount0 < 0 and ev.amount1 > 0 and ev.tick == -300000 and ev.fee == 30000
    td, qd = v4.swap_token_and_quote_deltas(ev, token_is_currency0=True)
    assert td < 0 and qd > 0  # sell


def test_price_math_roundtrip():
    # price 0.003 quote per token with 18/18 decimals -> sqrtP = sqrt(0.003) * 2^96
    import math
    sp = int(math.sqrt(0.003) * v4.Q96)
    p = v4.token_price_in_quote(sp, True, 18, 18)
    assert abs(p - 0.003) / 0.003 < 1e-6
    # token as currency1 with 6-dec quote (USDG) as currency0: price(token in quote)
    sp2 = int(math.sqrt(1 / 0.003 * 10 ** 18 / 10 ** 6) * v4.Q96)
    p2 = v4.token_price_in_quote(sp2, False, 18, 6)
    assert abs(p2 - 0.003) / 0.003 < 1e-6


def test_cpmm_price_impact():
    assert v4.cpmm_price_impact(1000.0, 1000.0, 100.0) is not None
    assert 0.08 < v4.cpmm_price_impact(1000.0, 1000.0, 100.0) < 0.10  # ~9.1%
    assert v4.cpmm_price_impact(0, 1, 1) is None
