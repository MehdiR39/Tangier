"""Minimal, dependency-free Ethereum ABI helpers.

Provides keccak256 (pure Python with an optional pycryptodome fast path), function
selectors / event topics, and a small ABI encoder/decoder covering the static
types, ``bytes``/``string``, arrays and tuples. This is enough for ERC-20 view
calls, Uniswap v4 event decoding and the V4 quoter.
"""
from __future__ import annotations

import functools
import re
from typing import Any, Iterable

# --------------------------------------------------------------------------- #
# keccak-256 (Ethereum variant: pad10*1 with 0x01)
# --------------------------------------------------------------------------- #
_RC = [
    0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000,
    0x000000000000808B, 0x0000000080000001, 0x8000000080008081, 0x8000000000008009,
    0x000000000000008A, 0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
    0x000000008000808B, 0x800000000000008B, 0x8000000000008089, 0x8000000000008003,
    0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
    0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
]
_ROT = [[0, 36, 3, 41, 18], [1, 44, 10, 45, 2], [62, 6, 43, 15, 61], [28, 55, 25, 21, 56], [27, 20, 39, 8, 14]]
_M64 = (1 << 64) - 1


def _rol(x: int, n: int) -> int:
    n %= 64
    return ((x << n) | (x >> (64 - n))) & _M64 if n else x


def _keccak_f(st: list[list[int]]) -> list[list[int]]:
    for rc in _RC:
        c = [st[x][0] ^ st[x][1] ^ st[x][2] ^ st[x][3] ^ st[x][4] for x in range(5)]
        d = [c[(x - 1) % 5] ^ _rol(c[(x + 1) % 5], 1) for x in range(5)]
        st = [[st[x][y] ^ d[x] for y in range(5)] for x in range(5)]
        b = [[0] * 5 for _ in range(5)]
        for x in range(5):
            for y in range(5):
                b[y][(2 * x + 3 * y) % 5] = _rol(st[x][y], _ROT[x][y])
        st = [[b[x][y] ^ ((~b[(x + 1) % 5][y]) & b[(x + 2) % 5][y]) for y in range(5)] for x in range(5)]
        st[0][0] ^= rc
    return st


def _keccak256_pure(data: bytes) -> bytes:
    rate = 136
    st = [[0] * 5 for _ in range(5)]
    buf = bytearray(data)
    buf.append(0x01)
    while len(buf) % rate:
        buf.append(0)
    buf[-1] |= 0x80
    for off in range(0, len(buf), rate):
        blk = buf[off: off + rate]
        for i in range(rate // 8):
            st[i % 5][i // 5] ^= int.from_bytes(blk[8 * i: 8 * i + 8], "little")
        st = _keccak_f(st)
    out = b"".join(st[i % 5][i // 5].to_bytes(8, "little") for i in range(4))
    return out[:32]


try:  # optional fast path
    from Crypto.Hash import keccak as _pc_keccak  # type: ignore

    def keccak256(data: bytes) -> bytes:
        return _pc_keccak.new(digest_bits=256, data=data).digest()

except Exception:  # pragma: no cover - depends on environment

    def keccak256(data: bytes) -> bytes:  # type: ignore[misc]
        return _keccak256_pure(data)


@functools.lru_cache(maxsize=1024)
def selector(signature: str) -> str:
    """4-byte function selector as 0x-hex for e.g. ``balanceOf(address)``."""
    return "0x" + keccak256(signature.encode()).hex()[:8]


@functools.lru_cache(maxsize=1024)
def event_topic(signature: str) -> str:
    """32-byte event topic as 0x-hex for e.g. ``Transfer(address,address,uint256)``."""
    return "0x" + keccak256(signature.encode()).hex()


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
_ADDR_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_B32_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


def is_address(s: Any) -> bool:
    return isinstance(s, str) and bool(_ADDR_RE.match(s))


def is_bytes32(s: Any) -> bool:
    return isinstance(s, str) and bool(_B32_RE.match(s))


def norm_address(s: str) -> str:
    """Lower-case 0x address. Raises on malformed input."""
    if not is_address(s):
        raise ValueError(f"not an address: {s!r}")
    return s.lower()


def norm_hex(s: str) -> str:
    return s.lower()


def to_checksum_address(addr: str) -> str:
    addr = norm_address(addr)[2:]
    h = keccak256(addr.encode()).hex()
    return "0x" + "".join(c.upper() if int(h[i], 16) >= 8 else c for i, c in enumerate(addr))


def hex_to_int(h: str | None) -> int | None:
    if h is None:
        return None
    return int(h, 16)


def topic_to_address(topic: str) -> str:
    return "0x" + topic[-40:].lower()


def word_to_int(word: str, signed: bool = False, bits: int = 256) -> int:
    v = int(word, 16)
    if signed and v >= (1 << (bits - 1)):
        v -= 1 << bits
    return v


def split_words(data: str) -> list[str]:
    d = data[2:] if data.startswith("0x") else data
    return [d[i: i + 64] for i in range(0, len(d), 64)]


# --------------------------------------------------------------------------- #
# ABI type parsing
# --------------------------------------------------------------------------- #
def _split_top_level(s: str) -> list[str]:
    out: list[str] = []
    depth = 0
    cur: list[str] = []
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    if cur:
        out.append("".join(cur))
    return [x.strip() for x in out if x.strip()]


def _tuple_components(t: str) -> list[str]:
    if not (t.startswith("(") and t.endswith(")")):
        raise ValueError(f"not a tuple type: {t}")
    return _split_top_level(t[1:-1])


def is_dynamic(t: str) -> bool:
    if t in ("bytes", "string") or t.endswith("[]"):
        return True
    if t.startswith("("):
        return any(is_dynamic(c) for c in _tuple_components(t))
    return False


def _head_words(t: str) -> int:
    """Number of 32-byte words a type occupies in the head section."""
    if is_dynamic(t):
        return 1
    if t.startswith("("):
        return sum(_head_words(c) for c in _tuple_components(t))
    return 1


def _enc_static(t: str, v: Any) -> bytes:
    if t == "address":
        return int(norm_address(v), 16).to_bytes(32, "big")
    if t == "bool":
        return (1 if v else 0).to_bytes(32, "big")
    if t.startswith("uint"):
        iv = int(v)
        if iv < 0:
            raise ValueError("negative uint")
        return iv.to_bytes(32, "big")
    if t.startswith("int"):
        return (int(v) % (1 << 256)).to_bytes(32, "big")
    if t.startswith("bytes") and t != "bytes":  # bytesN
        n = int(t[5:])
        b = bytes.fromhex(v[2:]) if isinstance(v, str) else bytes(v)
        if len(b) != n:
            raise ValueError(f"{t} expects {n} bytes")
        return b + b"\x00" * (32 - n)
    raise ValueError(f"unsupported static type {t}")


def encode(types: Iterable[str], values: Iterable[Any]) -> bytes:
    """Standard ABI encoding of a list of values for the given types."""
    types = list(types)
    values = list(values)
    if len(types) != len(values):
        raise ValueError("types/values length mismatch")
    head_len = 32 * sum(_head_words(t) for t in types)
    heads: list[bytes | None] = []
    tails: list[bytes] = []
    for t, v in zip(types, values):
        if is_dynamic(t):
            heads.append(None)
            tails.append(_encode_one(t, v))
        else:
            heads.append(_encode_one(t, v))
            tails.append(b"")
    out = b""
    offset = head_len
    for h, tl in zip(heads, tails):
        if h is None:
            out += offset.to_bytes(32, "big")
            offset += len(tl)
        else:
            out += h
    for tl in tails:
        out += tl
    return out


def _encode_one(t: str, v: Any) -> bytes:
    if t in ("bytes", "string"):
        if t == "string":
            b = v.encode() if isinstance(v, str) else bytes(v)
        else:
            b = bytes.fromhex(v[2:] if v.startswith("0x") else v) if isinstance(v, str) else bytes(v)
        padded = b + b"\x00" * ((32 - len(b) % 32) % 32)
        return len(b).to_bytes(32, "big") + padded
    if t.endswith("[]"):
        inner = t[:-2]
        items = list(v)
        return len(items).to_bytes(32, "big") + encode([inner] * len(items), items)
    if t.startswith("("):
        return encode(_tuple_components(t), list(v))
    return _enc_static(t, v)


def encode_call(signature: str, args: Iterable[Any] = ()) -> str:
    """Return 0x-hex calldata for ``signature`` e.g. ``balanceOf(address)``."""
    _name, _, rest = signature.partition("(")
    inner = rest[:-1]
    types = _split_top_level(inner) if inner else []
    return selector(signature) + encode(types, list(args)).hex()


def decode(types: Iterable[str], data: bytes | str) -> list[Any]:
    """Standard ABI decoding of return data / event data."""
    if isinstance(data, str):
        data = bytes.fromhex(data[2:] if data.startswith("0x") else data)
    types = list(types)
    out: list[Any] = []
    pos = 0
    for t in types:
        if is_dynamic(t):
            off = int.from_bytes(data[pos: pos + 32], "big")
            out.append(_decode_one(t, data, off))
            pos += 32
        elif t.startswith("("):
            out.append(_decode_one(t, data, pos))
            pos += 32 * _head_words(t)
        else:
            out.append(_dec_static(t, data[pos: pos + 32]))
            pos += 32
    return out


def _dec_static(t: str, w: bytes) -> Any:
    if len(w) < 32:
        raise ValueError("truncated ABI data")
    if t == "address":
        return "0x" + w[12:].hex()
    if t == "bool":
        return int.from_bytes(w, "big") != 0
    if t.startswith("uint"):
        return int.from_bytes(w, "big")
    if t.startswith("int"):
        v = int.from_bytes(w, "big")
        return v - (1 << 256) if v >= (1 << 255) else v
    if t.startswith("bytes"):
        n = int(t[5:])
        return "0x" + w[:n].hex()
    raise ValueError(f"unsupported static type {t}")


def _decode_one(t: str, data: bytes, off: int) -> Any:
    if t in ("bytes", "string"):
        n = int.from_bytes(data[off: off + 32], "big")
        b = data[off + 32: off + 32 + n]
        return b.decode("utf-8", "replace") if t == "string" else "0x" + b.hex()
    if t.endswith("[]"):
        inner = t[:-2]
        n = int.from_bytes(data[off: off + 32], "big")
        return decode([inner] * n, data[off + 32:])
    if t.startswith("("):
        return tuple(decode(_tuple_components(t), data[off:]))
    return _dec_static(t, data[off: off + 32])


def decode_string_return(data: str | None) -> str | None:
    """Decode a ``string`` return value; tolerates bytes32-style names used by old tokens."""
    if not data or data == "0x":
        return None
    raw = bytes.fromhex(data[2:])
    if len(raw) == 32:  # bytes32 symbol/name
        return raw.rstrip(b"\x00").decode("utf-8", "replace") or None
    try:
        return decode(["string"], raw)[0]
    except Exception:
        return None


def bytecode_has_selector(bytecode_hex: str, sel: str) -> bool:
    """Heuristic: does deployed bytecode contain ``PUSH4 <selector>``?

    Used for unverified contracts to detect dangerous privileged functions. False
    negatives are possible (proxies, unusual dispatchers), so callers must map a
    miss to UNKNOWN rather than PASS.
    """
    body = bytecode_hex[2:].lower() if bytecode_hex.startswith("0x") else bytecode_hex.lower()
    return ("63" + sel[2:].lower()) in body
