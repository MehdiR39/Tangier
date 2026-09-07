"""Spending grants: asked for only when missing, and never for native ETH.

Without them a swap reverts after the gas has been paid, so getting this wrong is not free.
"""
import asyncio

from intel.context import IntelContext
from intel.db.connection import Database
from intel.execution.approvals import (APPROVE_AMOUNT, PERMIT2_AMOUNT, missing_approvals,
                                       permit2_allowance, token_allowance)
from intel.providers.base import ProviderStatusRegistry
from intel.settings import IntelConfig, Settings
from intel.utils.abi import decode, encode, selector

TOKEN = "0x" + "aa" * 20
OWNER = "0x" + "bb" * 20
PERMIT2 = "0x000000000022d473030f116ddee9f6b43ac78ba3"
ROUTER = "0xf8b30c1b77e38f2df9d058c43a3af8d47161a0c7"
NATIVE = "0x" + "00" * 20
NOW = 1_800_000_000


class _Rpc:
    """Answers eth_call for the two allowance lookups, with values the test chooses."""

    def __init__(self, token_allow=0, p2_amount=0, p2_expiry=0, fail=False):
        self.token_allow, self.p2_amount, self.p2_expiry, self.fail = token_allow, p2_amount, p2_expiry, fail
        self.calls: list[str] = []

    async def call(self, to, data, block="latest", *, from_address=None):
        if self.fail:
            raise RuntimeError("node says no")
        self.calls.append(to.lower())
        if to.lower() == PERMIT2:
            return "0x" + encode(["uint160", "uint48", "uint48"], [self.p2_amount, self.p2_expiry, 0]).hex()
        return "0x" + encode(["uint256"], [self.token_allow]).hex()


def _ctx(rpc) -> IntelContext:
    ctx = IntelContext.__new__(IntelContext)
    ctx.settings = Settings.load(db_path=":memory:", telegram_dry_run=True)
    ctx.config = IntelConfig({"execution": {"permit2": PERMIT2, "router": ROUTER}})
    ctx.db = Database(":memory:")
    ctx.status = ProviderStatusRegistry(ctx.db)
    ctx.rpc = rpc  # type: ignore[assignment]
    ctx.blockscout = ctx.dex = None  # type: ignore[assignment]
    return ctx


def _needs(rpc, amount=1000, token=TOKEN):
    return asyncio.run(missing_approvals(_ctx(rpc), token=token, owner=OWNER, amount=amount, now_ts=NOW))


def test_a_fresh_token_needs_both_grants():
    needs = _needs(_Rpc())
    assert [n.what for n in needs] == ["token->permit2", "permit2->router"]
    assert needs[0].to == TOKEN and needs[1].to == PERMIT2


def test_nothing_is_asked_when_both_grants_are_already_in_place():
    rpc = _Rpc(token_allow=APPROVE_AMOUNT, p2_amount=PERMIT2_AMOUNT, p2_expiry=NOW + 86400)
    assert _needs(rpc) == []


def test_only_the_missing_half_is_asked_for():
    rpc = _Rpc(token_allow=APPROVE_AMOUNT, p2_amount=0, p2_expiry=0)
    assert [n.what for n in _needs(rpc)] == ["permit2->router"]
    rpc = _Rpc(token_allow=0, p2_amount=PERMIT2_AMOUNT, p2_expiry=NOW + 86400)
    assert [n.what for n in _needs(rpc)] == ["token->permit2"]


def test_an_expired_permit2_grant_is_renewed():
    rpc = _Rpc(token_allow=APPROVE_AMOUNT, p2_amount=PERMIT2_AMOUNT, p2_expiry=NOW - 1)
    assert [n.what for n in _needs(rpc)] == ["permit2->router"]


def test_a_grant_too_small_for_the_order_is_topped_up():
    rpc = _Rpc(token_allow=500, p2_amount=PERMIT2_AMOUNT, p2_expiry=NOW + 86400)
    assert [n.what for n in _needs(rpc, amount=1000)] == ["token->permit2"]


def test_native_eth_needs_no_grant_at_all():
    rpc = _Rpc()
    assert _needs(rpc, token=NATIVE) == []
    assert rpc.calls == [], "native ETH must not even be looked up"


def test_an_unreadable_allowance_is_treated_as_missing_never_as_granted():
    # refusing by default: an RPC failure must not be read as "already approved"
    assert len(_needs(_Rpc(fail=True))) == 2


def test_the_calls_are_the_real_approve_signatures():
    needs = _needs(_Rpc())
    assert needs[0].data.startswith(selector("approve(address,uint256)"))
    spender, amount = decode(["address", "uint256"], needs[0].data[10:])
    assert spender.lower() == PERMIT2 and amount == APPROVE_AMOUNT
    assert needs[1].data.startswith(selector("approve(address,address,uint160,uint48)"))
    token, router, p2_amount, expiry = decode(["address", "address", "uint160", "uint48"], needs[1].data[10:])
    assert token.lower() == TOKEN and router.lower() == ROUTER
    assert p2_amount == PERMIT2_AMOUNT and expiry > NOW


def test_the_token_approval_is_large_but_not_infinite():
    # an unlimited approval on a token that later turns out to be malicious is a standing invitation
    assert APPROVE_AMOUNT < 2 ** 256 - 1
    assert APPROVE_AMOUNT > 10 ** 30      # still covers years of small orders


def test_allowance_readers_return_none_rather_than_zero_on_failure():
    ctx = _ctx(_Rpc(fail=True))
    assert asyncio.run(token_allowance(ctx, TOKEN, OWNER, PERMIT2)) is None
    assert asyncio.run(permit2_allowance(ctx, PERMIT2, OWNER, TOKEN, ROUTER)) is None
