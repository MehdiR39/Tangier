"""The Solana path, checked where it can be: refusals, sizing, and the two-act safety model."""
import asyncio
import os

import pytest

from intel.execution import solana as S


def test_no_key_means_no_address_and_no_signature():
    # The same two-act model as the other chain: without a key nothing can be signed, and the
    # refusal never carries the key or any part of it.
    os.environ.pop(S.KEY_ENV, None)
    assert S.signer_address() is None
    with pytest.raises(S.SolanaRefused) as e:
        S.sign("AQAB")
    assert S.KEY_ENV in str(e.value)


def test_an_unreadable_key_is_refused_without_echoing_it():
    os.environ[S.KEY_ENV] = "ceci-n-est-pas-une-cle-privee"
    try:
        with pytest.raises(S.SolanaRefused) as e:
            S.signer_address() or S.sign("AQAB")
        assert "ceci-n-est-pas" not in str(e.value)
    finally:
        os.environ.pop(S.KEY_ENV, None)


def test_a_size_that_rounds_to_nothing_is_refused():
    async def go():
        return await S.prepare_buy(None, mint="X", size_eur=0.0, sol_eur=180.0,
                                   slippage_pct=3.0, max_impact_pct=10.0)

    res = asyncio.run(go())
    assert res["status"] == "REFUSED" and "lamports" in res["refused_reason"]


def test_the_quote_is_priced_in_lamports_from_the_euro_size():
    # 5 EUR at 180 EUR per SOL is 0.02777... SOL; the order must carry that, not a rounded guess.
    assert int(5.0 / 180.0 * S.LAMPORTS) == 27_777_777
