"""La reserve virtuelle des pools PumpSwap (§3.83, 15/09).

Un pool issu d une migration pump.fun porte a l octet 245 un u64 de 17,5845 SOL et echange au prix
(SOL du coffre + ce montant) / jetons. Verifie en chaine sur nos 239 achats et 239 ventes.
"""
from __future__ import annotations

import struct

import pytest

from intel.engines.prix_chaine import OFF_RESERVE_VIRTUELLE, reserve_virtuelle


def _compte(lamports: int, taille: int = 301) -> bytes:
    d = bytearray(taille)
    if taille >= OFF_RESERVE_VIRTUELLE + 8:
        struct.pack_into("<Q", d, OFF_RESERVE_VIRTUELLE, lamports)
    return bytes(d)


def test_la_valeur_des_pools_pumpfun_est_lue():
    assert reserve_virtuelle(_compte(17_584_500_000)) == pytest.approx(17.5845)


def test_un_pool_sans_reserve_virtuelle_rend_zero():
    assert reserve_virtuelle(_compte(0)) == 0.0


def test_une_valeur_invraisemblable_est_ignoree():
    """351 pools portent autre chose a cet octet (jusqu a 5 015 « SOL ») : on ne s en sert pas."""
    assert reserve_virtuelle(_compte(5_015_000_000_000)) == 0.0


def test_un_compte_trop_court_rend_zero():
    assert reserve_virtuelle(_compte(17_584_500_000, taille=240)) == 0.0


def test_le_prix_echangeable_colle_a_un_vrai_achat():
    """WOFI, 14/09 : coffre 187 799 277,72 jetons et 76,074 SOL, 0,3121 SOL entres, 622 468 jetons
    recus. Prix du coffre seul : 767 289 jetons attendus (23 % de trop). Avec la reserve virtuelle et
    0,25 % de frais : a 1 % pres."""
    b, q, dq = 187_799_277.72, 76.074373336, 0.3121
    v = 17.5845
    attendu = b * dq * (1 - 0.0025) / (q + v + dq * (1 - 0.0025))
    assert attendu == pytest.approx(622_468, rel=0.01)
    assert b * dq / (q + dq) == pytest.approx(767_289, rel=0.001)
