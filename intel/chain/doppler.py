"""Doppler launchpad (Whetstone) specifics on Robinhood Chain.

Tokens launched through the Airlock are EIP-1167 clones of DopplerERC20V1 and trade in
a Uniswap v4 pool whose hook is a Doppler initializer. The Airlock exposes
``getAssetData(asset)`` with governance/timelock/integrator addresses (team-controlled
supply) and ``Create``/``Migrate`` events for discovery.
"""
from __future__ import annotations

import logging
from typing import Any

from intel.chain.constants import (
    AIRLOCK_ASSET_DATA_FIELDS,
    AIRLOCK_GET_ASSET_DATA,
    AIRLOCK_GET_ASSET_DATA_OUTPUTS,
    DOPPLER_ERC20_VIEWS,
    TOPIC_AIRLOCK_CREATE,
    TOPIC_AIRLOCK_MIGRATE,
)
from intel.providers.rpc import RpcClient
from intel.utils.abi import ZERO_ADDRESS, decode, encode_call, topic_to_address

log = logging.getLogger(__name__)


async def airlock_asset_data(rpc: RpcClient, airlock: str, asset: str) -> dict[str, Any] | None:
    raw = await rpc.try_call(airlock, encode_call(AIRLOCK_GET_ASSET_DATA, [asset]))
    if not raw:
        return None
    try:
        vals = decode(AIRLOCK_GET_ASSET_DATA_OUTPUTS, raw)
    except Exception:
        return None
    data = dict(zip(AIRLOCK_ASSET_DATA_FIELDS, vals))
    if data.get("numeraire") == ZERO_ADDRESS and data.get("pool") == ZERO_ADDRESS and not data.get("total_supply"):
        return None  # asset unknown to the airlock
    return data


async def doppler_erc20_views(rpc: RpcClient, token: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, (sig, outputs) in DOPPLER_ERC20_VIEWS.items():
        raw = await rpc.try_call(token, encode_call(sig))
        if raw is None:
            out[name] = None
            continue
        try:
            out[name] = decode(outputs, raw)[0]
        except Exception:
            out[name] = None
    return out


def decode_airlock_create(lg: dict[str, Any]) -> dict[str, Any] | None:
    topics = lg.get("topics") or []
    if not topics or topics[0].lower() != TOPIC_AIRLOCK_CREATE:
        return None
    asset, initializer, pool_or_hook = decode(["address", "address", "address"], lg["data"])
    return {
        "asset": asset,
        "numeraire": topic_to_address(topics[1]) if len(topics) > 1 else None,
        "initializer": initializer,
        "pool_or_hook": pool_or_hook,
        "block_number": int(lg["blockNumber"], 16) if isinstance(lg["blockNumber"], str) else int(lg["blockNumber"]),
        "tx_hash": lg["transactionHash"].lower(),
    }


def decode_airlock_migrate(lg: dict[str, Any]) -> dict[str, Any] | None:
    topics = lg.get("topics") or []
    if not topics or topics[0].lower() != TOPIC_AIRLOCK_MIGRATE:
        return None
    return {
        "asset": topic_to_address(topics[1]),
        "pool": topic_to_address(topics[2]),
        "block_number": int(lg["blockNumber"], 16) if isinstance(lg["blockNumber"], str) else int(lg["blockNumber"]),
        "tx_hash": lg["transactionHash"].lower(),
    }


def is_doppler_hook(address: str | None, system_addresses: dict[str, str]) -> bool:
    if not address:
        return False
    label = system_addresses.get(address.lower(), "")
    return label.startswith("hook:")
