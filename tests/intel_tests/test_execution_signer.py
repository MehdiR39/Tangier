"""Signing refuses by default, and the key never leaves the environment.

The key used here is a throwaway constant with no funds on any chain; its address is derived at
run time rather than hardcoded, so the test never carries a value that looks like a real secret.
"""
import asyncio

import pytest

from intel.context import IntelContext
from intel.db.connection import Database
from intel.execution.signer import KEY_ENV, SigningRefused, build_and_sign, signer_address
from intel.providers.base import ProviderStatusRegistry
from intel.settings import IntelConfig, Settings

TEST_KEY = "0x" + "11" * 32
TO = "0x" + "22" * 20


class _Rpc:
    """Just enough of an RPC to exercise the signing path, with no network."""

    def __init__(self, chain_id=4663, estimate_fails=False):
        self.chain_id, self.estimate_fails = chain_id, estimate_fails

    async def request(self, method, params=None, **kw):
        if method == "eth_chainId":
            return hex(self.chain_id)
        if method == "eth_getTransactionCount":
            return "0x7"
        if method == "eth_estimateGas":
            if self.estimate_fails:
                raise RuntimeError("execution reverted")
            return hex(210_000)
        if method == "eth_gasPrice":
            return hex(1_000_000_000)
        if method == "eth_maxPriorityFeePerGas":
            return hex(100_000_000)
        raise AssertionError(f"unexpected call {method}")


def _ctx(mode="live", rpc=None, kill=False) -> IntelContext:
    ctx = IntelContext.__new__(IntelContext)
    ctx.settings = Settings.load(db_path=":memory:", telegram_dry_run=True)
    ctx.config = IntelConfig({"execution": {"mode": mode, "kill_switch": kill}})
    ctx.db = Database(":memory:")
    ctx.status = ProviderStatusRegistry(ctx.db)
    ctx.rpc = rpc or _Rpc()  # type: ignore[assignment]
    ctx.blockscout = ctx.dex = None  # type: ignore[assignment]
    return ctx


def _expected_address() -> str:
    from eth_account import Account

    return Account.from_key(TEST_KEY).address.lower()


def test_no_key_means_no_signature(monkeypatch):
    monkeypatch.delenv(KEY_ENV, raising=False)
    assert signer_address() is None
    with pytest.raises(SigningRefused, match=KEY_ENV):
        asyncio.run(build_and_sign(_ctx(), to=TO, data="0x", value_wei=0))


def test_dry_run_refuses_even_with_a_key(monkeypatch):
    monkeypatch.setenv(KEY_ENV, TEST_KEY)
    with pytest.raises(SigningRefused, match="dry_run"):
        asyncio.run(build_and_sign(_ctx(mode="dry_run"), to=TO, data="0x", value_wei=0))


def test_kill_switch_refuses_even_in_live_mode(monkeypatch):
    monkeypatch.setenv(KEY_ENV, TEST_KEY)
    with pytest.raises(SigningRefused, match="urgence"):
        asyncio.run(build_and_sign(_ctx(kill=True), to=TO, data="0x", value_wei=0))


def test_a_wrong_chain_is_refused(monkeypatch):
    monkeypatch.setenv(KEY_ENV, TEST_KEY)
    with pytest.raises(SigningRefused, match="chain_id"):
        asyncio.run(build_and_sign(_ctx(rpc=_Rpc(chain_id=1)), to=TO, data="0x", value_wei=0))


def test_an_estimate_that_reverts_aborts_before_signing(monkeypatch):
    # the cheapest possible refusal: the swap would have failed on-chain after paying the gas
    monkeypatch.setenv(KEY_ENV, TEST_KEY)
    with pytest.raises(SigningRefused, match="estimation"):
        asyncio.run(build_and_sign(_ctx(rpc=_Rpc(estimate_fails=True)), to=TO, data="0x", value_wei=0))


def test_a_signed_transaction_carries_the_expected_envelope(monkeypatch):
    monkeypatch.setenv(KEY_ENV, TEST_KEY)
    signed = asyncio.run(build_and_sign(_ctx(), to=TO, data="0x1234", value_wei=5))
    assert signed.from_address == _expected_address()
    assert signed.nonce == 7
    assert signed.gas > 210_000                      # headroom applied to the estimate
    assert signed.max_fee_per_gas > 1_000_000_000    # headroom applied to the base fee
    assert signed.value_wei == 5
    assert signed.raw.startswith("0x") and len(signed.raw) > 100


def test_the_key_is_never_returned_or_logged(monkeypatch, caplog):
    monkeypatch.setenv(KEY_ENV, TEST_KEY)
    with caplog.at_level("DEBUG"):
        signed = asyncio.run(build_and_sign(_ctx(), to=TO, data="0x", value_wei=0))
    blob = " ".join(r.getMessage() for r in caplog.records) + repr(signed)
    assert TEST_KEY not in blob and TEST_KEY[2:] not in blob


def test_an_unreadable_key_does_not_echo_its_value(monkeypatch):
    monkeypatch.setenv(KEY_ENV, "0xthis-is-not-a-key-but-looks-secret")
    with pytest.raises(SigningRefused) as e:
        asyncio.run(build_and_sign(_ctx(), to=TO, data="0x", value_wei=0))
    assert "looks-secret" not in str(e.value)


def test_signer_address_is_public_information(monkeypatch):
    monkeypatch.setenv(KEY_ENV, TEST_KEY)
    assert signer_address() == _expected_address()
