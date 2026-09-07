"""ABI / keccak helpers verified against on-chain values captured from Robinhood Chain."""
from intel.utils import abi
from intel.utils.abi import _keccak256_pure


def test_keccak_known_vectors():
    assert _keccak256_pure(b"").hex() == "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"
    assert abi.event_topic("Transfer(address,address,uint256)") == "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
    assert abi.selector("name()") == "0x06fdde03"
    assert abi.selector("balanceOf(address)") == "0x70a08231"
    assert abi.event_topic("Swap(bytes32,address,int128,int128,uint160,uint128,int24,uint24)") == "0x40e9cecb9f5f1f1c5b9c97dec2917b7ee92e57ba5563708daca94dd84ad7112f"
    assert abi.event_topic("Initialize(bytes32,address,address,uint24,int24,address,uint160,int24)") == "0xdd466e674ea557f56295e2d0218a125ea4b4f0f6f3307b95f85e6110838d6438"


def test_checksum_address():
    assert abi.to_checksum_address("0xd18528b39da6464b3662c331a52181ecb15b1e18") == "0xD18528b39dA6464B3662c331a52181ecB15b1E18"


def test_encode_call_balance_of():
    data = abi.encode_call("balanceOf(address)", ["0xd18528b39da6464b3662c331a52181ecb15b1e18"])
    assert data == "0x70a08231" + "0" * 24 + "d18528b39da6464b3662c331a52181ecb15b1e18"


def test_decode_string_return_name():
    # eth_call name() on SAYLORMOON
    raw = ("0x0000000000000000000000000000000000000000000000000000000000000020"
           "000000000000000000000000000000000000000000000000000000000000000a"
           "5341594c4f524d4f4f4e00000000000000000000000000000000000000000000")
    assert abi.decode_string_return(raw) == "SAYLORMOON"


def test_decode_v4_swap_data_sign():
    # Swap event data captured on-chain: amount0=-25578.50 tokens (paid into pool), amount1=+0.7585 MSTR
    data = ("0x" + (-25578503961399380000000 % (1 << 256)).to_bytes(32, "big").hex()
            + (758500000000000000).to_bytes(32, "big").hex()
            + (1234567890).to_bytes(32, "big").hex()
            + (99999).to_bytes(32, "big").hex()
            + ((-5000) % (1 << 256)).to_bytes(32, "big").hex()
            + (0x800000).to_bytes(32, "big").hex())
    a0, a1, sqrtp, liq, tick, fee = abi.decode(["int128", "int128", "uint160", "uint128", "int24", "uint24"], data)
    assert a0 < 0 and a1 > 0
    assert tick == -5000 and fee == 0x800000 and liq == 99999 and sqrtp == 1234567890


def test_encode_tuple_with_dynamic_bytes_quoter():
    pool_key = ("0xd18528b39da6464b3662c331a52181ecb15b1e18", "0xec262a75e413fafd0df80480274532c79d42da09", 0x800000, 8, "0x4e3468951d49f2eea976ed0d6e75ffcb44a9a544")
    data = abi.encode_call("quoteExactInputSingle(((address,address,uint24,int24,address),bool,uint128,bytes))", [(pool_key, True, 10 ** 18, b"")])
    body = bytes.fromhex(data[10:])
    # outer tuple is dynamic -> single offset word (0x20), then 5 static words for the pool key,
    # bool, uint128, and the offset of hookData (8 words * 32 = 0x100), then the bytes length (0)
    assert int.from_bytes(body[0:32], "big") == 0x20
    assert int.from_bytes(body[32 + 5 * 32: 32 + 6 * 32], "big") == 1
    assert int.from_bytes(body[32 + 6 * 32: 32 + 7 * 32], "big") == 10 ** 18
    assert int.from_bytes(body[32 + 7 * 32: 32 + 8 * 32], "big") == 8 * 32
    assert int.from_bytes(body[32 + 8 * 32: 32 + 9 * 32], "big") == 0


def test_decode_static_tuple_and_arrays():
    enc = abi.encode(["uint256", "address[]", "(uint256,bool)"], [7, ["0x" + "11" * 20, "0x" + "22" * 20], (3, True)])
    out = abi.decode(["uint256", "address[]", "(uint256,bool)"], enc)
    assert out[0] == 7
    assert out[1] == ["0x" + "11" * 20, "0x" + "22" * 20]
    assert out[2] == (3, True)


def test_bytecode_selector_scan():
    code = "0x6080604052348015600f57600080fd5b50600436106040c10f19"
    assert abi.bytecode_has_selector(code, "0x40c10f19") is False  # needs PUSH4 (0x63) prefix
    assert abi.bytecode_has_selector("0x6340c10f1914", "0x40c10f19") is True
