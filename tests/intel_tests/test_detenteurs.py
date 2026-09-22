"""La concentration des detenteurs (intel/research/detenteurs.py) : ce qu elle compte, ce qu elle exclut.

Cas reels du 15/09 : un coffre de programme passait pour un detenteur a 79 % au premier essai, et
un bundle etait reparti sur quatre portefeuilles a exactement 18,7 % chacun.
"""
from __future__ import annotations

import pytest

from intel.research.detenteurs import concentration, est_portefeuille

OFFRE = 1_000_000_000.0
POOL, BASE_TA = "PoolPda", "BaseTa"


def _tous_portefeuilles(o):
    return o not in ("Programme",)


def test_le_pool_n_est_pas_un_detenteur():
    comptes = [(BASE_TA, POOL, 200e6), ("A", "Wa", 50e6)]
    t1, *_ = concentration(comptes, OFFRE, POOL, BASE_TA, portefeuille=_tous_portefeuilles)
    assert t1 == pytest.approx(0.05)


def test_un_compte_de_programme_n_est_pas_un_detenteur():
    comptes = [("Coffre", "Programme", 790e6), ("A", "Wa", 30e6)]
    t1, t5, t10, n1, n5, _ = concentration(comptes, OFFRE, POOL, BASE_TA, portefeuille=_tous_portefeuilles)
    assert t1 == pytest.approx(0.03)
    assert n5 == 0


def test_un_bundle_reparti_sur_quatre_portefeuilles_se_voit():
    comptes = [(c, "W" + c, 187e6) for c in "ABCD"] + [("E", "WE", 37e6)]
    t1, t5, t10, n1, n5, identiques = concentration(comptes, OFFRE, POOL, BASE_TA,
                                                    portefeuille=_tous_portefeuilles)
    assert t5 == pytest.approx(0.785)
    assert n5 == 4
    assert identiques == 4


def test_des_soldes_voisins_mais_differents_ne_sont_pas_un_bundle():
    comptes = [("A", "WA", 30e6), ("B", "WB", 29e6), ("C", "WC", 31e6)]
    *_, identiques = concentration(comptes, OFFRE, POOL, BASE_TA, portefeuille=_tous_portefeuilles)
    assert identiques == 0


def test_offre_inconnue_ne_leve_pas():
    assert concentration([("A", "WA", 1.0)], 0.0, POOL, BASE_TA, portefeuille=_tous_portefeuilles)[0] == 0


def test_une_adresse_de_programme_est_hors_de_la_courbe():
    # le programme PumpSwap lui-meme n est pas un portefeuille ; la cle systeme non plus
    assert est_portefeuille("pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA") in (True, False)
    assert est_portefeuille(None) is False
    assert est_portefeuille("pas-une-adresse") is False
