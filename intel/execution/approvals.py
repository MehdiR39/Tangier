"""Token spending permissions, without which no swap can settle.

Uniswap's UniversalRouter pulls funds through Permit2, so spending an ERC20 needs two grants in
sequence, each given once and then reusable:

1. the token allows Permit2 to move it (a normal ERC20 approve, on-chain, ~50k gas);
2. Permit2 allows the router to move it, up to an amount and until an expiry.

Both are checked before every order and requested only when actually missing. A swap attempted
without them does not fail politely: it reverts after the gas has been paid.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from intel.context import IntelContext
from intel.utils.abi import decode, encode_call, norm_address

log = logging.getLogger(__name__)

# Grant a large but not unlimited allowance: an infinite approval on a token that later turns out
# to be malicious is a standing invitation. This covers years of 25 EUR orders.
APPROVE_AMOUNT = 2 ** 128 - 1
# Permit2 stores its allowance as (uint160 amount, uint48 expiration, uint48 nonce).
PERMIT2_AMOUNT = 2 ** 160 - 1
PERMIT2_EXPIRY_S = 30 * 24 * 3600


@dataclass(frozen=True)
class ApprovalNeed:
    """One missing grant, with the exact call that would fix it."""
    what: str            # "token->permit2" or "permit2->router"
    to: str              # contract to call
    data: str            # calldata
    reason: str


async def token_allowance(ctx: IntelContext, token: str, owner: str, spender: str) -> int | None:
    data = encode_call("allowance(address,address)", [norm_address(owner), norm_address(spender)])
    try:
        res = await ctx.rpc.call(norm_address(token), data)
    except Exception as exc:  # noqa: BLE001
        log.warning("allowance illisible sur %s: %s", token[:10], exc)
        return None
    if not res or res == "0x":
        return None
    return int(decode(["uint256"], res)[0])


async def permit2_allowance(ctx: IntelContext, permit2: str, owner: str, token: str, spender: str) -> tuple[int, int] | None:
    """(amount, expiration) that Permit2 currently grants the spender."""
    data = encode_call("allowance(address,address,address)", [norm_address(owner), norm_address(token), norm_address(spender)])
    try:
        res = await ctx.rpc.call(norm_address(permit2), data)
    except Exception as exc:  # noqa: BLE001
        log.warning("allowance Permit2 illisible: %s", exc)
        return None
    if not res or res == "0x":
        return None
    amount, expiration, _nonce = decode(["uint160", "uint48", "uint48"], res)
    return int(amount), int(expiration)


def approve_token_call(token: str, permit2: str) -> ApprovalNeed:
    return ApprovalNeed(
        what="token->permit2", to=norm_address(token),
        data=encode_call("approve(address,uint256)", [norm_address(permit2), APPROVE_AMOUNT]),
        reason="le token n'autorise pas encore Permit2 à le déplacer",
    )


def approve_permit2_call(permit2: str, token: str, router: str, now_ts: int) -> ApprovalNeed:
    return ApprovalNeed(
        what="permit2->router", to=norm_address(permit2),
        data=encode_call("approve(address,address,uint160,uint48)",
                         [norm_address(token), norm_address(router), PERMIT2_AMOUNT, now_ts + PERMIT2_EXPIRY_S]),
        reason="Permit2 n'autorise pas encore le routeur à dépenser ce token",
    )


async def missing_approvals(ctx: IntelContext, *, token: str, owner: str, amount: int, now_ts: int) -> list[ApprovalNeed]:
    """What still has to be granted before ``amount`` of ``token`` can be spent by the router.

    Native ETH needs nothing: it travels as the transaction's value rather than being pulled.
    """
    if norm_address(token) == "0x" + "00" * 20:
        return []
    permit2 = str(ctx.config.get("execution.permit2"))
    router = str(ctx.config.get("execution.router"))
    needs: list[ApprovalNeed] = []

    current = await token_allowance(ctx, token, owner, permit2)
    if current is None or current < amount:
        needs.append(approve_token_call(token, permit2))

    p2 = await permit2_allowance(ctx, permit2, owner, token, router)
    if p2 is None or p2[0] < amount or p2[1] <= now_ts:
        needs.append(approve_permit2_call(permit2, token, router, now_ts))
    return needs
