"""Can this token be sold at all? Asked before buying, by simulating a transfer from someone who holds it.

The first real day (2026-09-07) bought six tokens and could sell one: two returned nothing on a sell,
one refused the transfer outright (TRANSFER_FROM_FAILED), one taxed the sale 46 %. None of that is
visible in prices or volumes -- the paper book counted them as winners -- it lives in the token
contract. A read-only ``transfer`` simulated from an existing buyer to the PoolManager is the
cheapest question that catches the outright blocks: one call, no state, no cost.

It does not catch a sell tax, and a contract can behave differently for us than for that buyer.
It is a filter, not a guarantee.
"""
from __future__ import annotations

import logging
from typing import Any

from intel.chain.erc20 import balance_of
from intel.context import IntelContext
from intel.utils.abi import encode_call

log = logging.getLogger(__name__)


async def transfer_probe(ctx: IntelContext, token: str, pool_id: str | None) -> tuple[bool, str]:
    """(ok, reason). ok=False means the token could not be moved by a holder in simulation."""
    token = token.lower()
    holder: str | None = None
    row = None
    if pool_id:
        row = ctx.db.query_one(
            "SELECT tx_hash FROM swap_events WHERE chain_id=? AND pair_id=? AND tx_hash IS NOT NULL ORDER BY block_number, log_index LIMIT 1",
            (ctx.chain_id, pool_id))
    if row and row["tx_hash"]:
        try:
            tx = await ctx.rpc.get_transaction(row["tx_hash"])
            holder = (tx or {}).get("from")
        except Exception as exc:  # noqa: BLE001
            log.info("sonde honeypot: transaction du premier acheteur illisible (%s)", str(exc)[:80])
    if not holder:
        return True, "aucun détenteur connu : sonde impossible, achat laissé passer"
    holder = holder.lower()
    try:
        bal = await balance_of(ctx.rpc, token, holder)
    except Exception as exc:  # noqa: BLE001
        return True, f"solde du détenteur illisible ({str(exc)[:60]}) : sonde impossible"
    if not bal:
        return True, "le premier acheteur ne détient plus rien : sonde impossible"
    amount = max(1, bal // 2)
    data = encode_call("transfer(address,uint256)", [ctx.pool_manager, amount])
    try:
        raw = await ctx.rpc.call(token, data, from_address=holder)
    except Exception as exc:  # noqa: BLE001
        msg = str(getattr(exc, "args", [""])[1] if len(getattr(exc, "args", [])) > 1 else exc)[:80]
        return False, f"transfert bloqué en simulation ({msg})"
    if raw and len(raw) >= 66 and int(raw[2:66], 16) == 0:
        return False, "transfert refusé en simulation (retourne faux)"
    return True, "transfert simulé OK"
