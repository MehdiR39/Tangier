"""ERC-20 / proxy / ownership reads via eth_call (no ABI files needed)."""
from __future__ import annotations

import logging
import re
from typing import Any

from intel.chain.constants import (
    EIP1967_ADMIN_SLOT,
    EIP1967_BEACON_SLOT,
    EIP1967_IMPL_SLOT,
    SEL_BALANCE_OF,
    SEL_DECIMALS,
    SEL_GET_OWNER,
    SEL_NAME,
    SEL_OWNER,
    SEL_PAUSED,
    SEL_SYMBOL,
    SEL_TOTAL_SUPPLY,
)
from intel.providers.rpc import RpcClient
from intel.utils.abi import ZERO_ADDRESS, decode, decode_string_return, encode_call

log = logging.getLogger(__name__)

_EIP1167_RE = re.compile(r"^0x363d3d373d3d3d363d73([0-9a-f]{40})5af43d82803e903d91602b57fd5bf3$")
_EIP1167_PUSH_RE = re.compile(r"^0x3d3d3d3d363d3d37363d73([0-9a-f]{40})5af43d3d93803e602a57fd5bf3$")


def detect_eip1167(code: str | None) -> str | None:
    """Return the implementation address if ``code`` is a minimal-proxy clone."""
    if not code:
        return None
    c = code.lower()
    for rx in (_EIP1167_RE, _EIP1167_PUSH_RE):
        m = rx.match(c)
        if m:
            return "0x" + m.group(1)
    # tolerant fallback: pattern 363d3d373d3d3d363d73<addr>5af43d
    m = re.search(r"363d3d373d3d3d363d73([0-9a-f]{40})5af43d", c) or re.search(r"3d3d3d3d363d3d37363d73([0-9a-f]{40})5af43d", c)
    return "0x" + m.group(1) if m else None


def _slot_to_address(word: str | None) -> str | None:
    if not word or len(word) < 42:
        return None
    addr = "0x" + word[-40:].lower()
    return None if addr == ZERO_ADDRESS else addr


async def fetch_metadata(rpc: RpcClient, token: str) -> dict[str, Any]:
    name = decode_string_return(await rpc.try_call(token, SEL_NAME))
    symbol = decode_string_return(await rpc.try_call(token, SEL_SYMBOL))
    dec_raw = await rpc.try_call(token, SEL_DECIMALS)
    ts_raw = await rpc.try_call(token, SEL_TOTAL_SUPPLY)
    decimals = int(dec_raw, 16) if dec_raw else None
    total_supply = int(ts_raw, 16) if ts_raw else None
    return {"name": name, "symbol": symbol, "decimals": decimals, "total_supply": total_supply}


async def total_supply(rpc: RpcClient, token: str, block: int | str = "latest") -> int | None:
    raw = await rpc.try_call(token, SEL_TOTAL_SUPPLY, block)
    return int(raw, 16) if raw else None


async def balance_of(rpc: RpcClient, token: str, holder: str, block: int | str = "latest") -> int | None:
    raw = await rpc.try_call(token, encode_call("balanceOf(address)", [holder]), block)
    return int(raw, 16) if raw else None


async def owner_of(rpc: RpcClient, contract: str) -> str | None:
    for sel in (SEL_OWNER, SEL_GET_OWNER):
        raw = await rpc.try_call(contract, sel)
        if raw and len(raw) >= 66:
            try:
                return decode(["address"], raw)[0]
            except Exception:
                continue
    return None


async def is_paused(rpc: RpcClient, contract: str) -> bool | None:
    raw = await rpc.try_call(contract, SEL_PAUSED)
    if raw is None:
        return None
    try:
        return bool(decode(["bool"], raw)[0])
    except Exception:
        return None


async def proxy_info(rpc: RpcClient, contract: str, code: str | None = None) -> dict[str, Any]:
    """Detect EIP-1167 clones, EIP-1967 implementation/admin/beacon slots."""
    if code is None:
        code = await rpc.get_code(contract)
    clone_impl = detect_eip1167(code)
    impl = _slot_to_address(await rpc.get_storage_at(contract, EIP1967_IMPL_SLOT))
    admin = _slot_to_address(await rpc.get_storage_at(contract, EIP1967_ADMIN_SLOT))
    beacon = _slot_to_address(await rpc.get_storage_at(contract, EIP1967_BEACON_SLOT))
    proxy_type = None
    if clone_impl:
        proxy_type = "eip1167"
    elif impl:
        proxy_type = "eip1967"
    elif beacon:
        proxy_type = "beacon"
    return {
        "code_size": (len(code) - 2) // 2 if code else 0,
        "proxy_type": proxy_type,
        "implementation": clone_impl or impl,
        "admin": admin,
        "beacon": beacon,
        "code": code,
    }


async def simulate_transfer(rpc: RpcClient, token: str, from_address: str, to_address: str, amount: int) -> tuple[bool | None, str | None]:
    """eth_call ``transfer(to, amount)`` as ``from_address``. (True/False/None=unknown, detail)."""
    data = encode_call("transfer(address,uint256)", [to_address, amount])
    try:
        out = await rpc.call(token, data, from_address=from_address)
    except Exception as exc:  # CallReverted or RpcError
        msg = str(exc)
        if "revert" in msg.lower() or "execution" in msg.lower():
            return False, msg[:200]
        return None, msg[:200]
    if not out or out == "0x":
        return True, "no return data (non-standard ERC20)"
    try:
        ok = bool(decode(["bool"], out)[0])
        return ok, None if ok else "transfer returned false"
    except Exception:
        return None, "undecodable return"
