"""La decision de sortie du test papier G+D, isolee et verifiee.

Ce qui doit tenir, parce que c est exactement la ou j ai deja fait des erreurs mesurables :
  - on ne vend PAS au prix qui declenche la prise de gain, mais a une lecture >= 2 s plus tard
    (vendre au prix du declenchement gonflait les resultats de 20 a 40 %, §3.96) ;
  - le declenchement se retient : si le prix retombe entre-temps, on vend quand meme, au prix d alors ;
  - une lecture illisible ne ferme pas la position, sauf tres au-dela de l echeance ;
  - l echeance a 287 s ferme, meme sans prise de gain.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "intel" / "research"))
import papier_gd_direct as P  # noqa: E402

P0 = 1.0e-6
CIBLE = P0 * (1 + P.TP)


def test_rien_ne_se_passe_sous_la_cible():
    assert P.avancer(P0, None, P0 * 1.2, 100.0) == (None, None)


def test_le_franchissement_ne_vend_pas_tout_de_suite():
    """Le piege : a ce moment precis on connait le prix, mais on ne peut pas encore avoir vendu."""
    declenche, motif = P.avancer(P0, None, CIBLE, 100.0)
    assert declenche == 100.0 and motif is None


def test_on_vend_a_la_premiere_lecture_deux_secondes_plus_tard():
    assert P.avancer(P0, 100.0, CIBLE * 1.1, 101.9)[1] is None      # trop tot
    assert P.avancer(P0, 100.0, CIBLE * 1.1, 102.0)[1] == "prise de gain"


def test_on_vend_meme_si_le_prix_est_retombe():
    """On s est engage a vendre ; le prix encaisse est celui du moment, pas celui du declenchement."""
    assert P.avancer(P0, 100.0, P0 * 0.5, 103.0)[1] == "prise de gain"


def test_l_echeance_ferme_sans_prise_de_gain():
    assert P.avancer(P0, None, P0 * 0.9, P.FIN_S)[1] == "echeance"
    assert P.avancer(P0, None, P0 * 0.9, P.FIN_S - 1)[1] is None


def test_une_lecture_illisible_ne_ferme_pas_la_position():
    assert P.avancer(P0, None, None, 120.0) == (None, None)
    assert P.avancer(P0, 100.0, None, 120.0) == (100.0, None)


def test_une_lecture_illisible_finit_par_ceder_apres_l_echeance():
    assert P.avancer(P0, None, None, P.FIN_S + 25)[1] == "echeance"


def test_le_declenchement_ne_se_perd_pas():
    d, motif = P.avancer(P0, 100.0, P0 * 1.1, 101.0)
    assert d == 100.0 and motif is None


def test_une_panne_reseau_ne_ferme_aucune_position():
    """Le 16/09 une erreur DNS d une seconde a tue le test a 30 s apres trois heures. Une lecture
    absente doit se comporter comme une lecture illisible : on garde la position et on reessaie."""
    for declenche in (None, 100.0):
        d, motif = P.avancer(P0, declenche, None, 150.0)
        assert motif is None and d == declenche


def test_l_emission_est_inerte_par_defaut():
    """Premiere des quatre etapes avant le reel : elle doit etre DESACTIVEE tant qu on ne l allume pas,
    et meme allumee elle ecrit sous un `model_version` a part, que le carnet du moteur ne regarde pas."""
    assert P.EMETTRE is False
    assert P.emettre("pair", "mint", 40, 80.0, 0.05, 46.0, 1e-6) is None
    assert P.MODELE_GD == "sol-gd-v0.1"          # jamais celui du carnet en service (sol-t1-v0.1)
    assert P.MISE_EMISE == 10.0


def test_les_seuils_sont_ceux_annonces():
    assert (P.TP, P.RETARD, P.FIN_S) == (0.25, 2.0, 287)
    assert P.FOULE_MAX == 74 and P.COFFRE_MAX == 100.0
    # On collecte sans plafond utile ; la contrainte de capital se rejoue a l analyse, pas ici.
    assert P.MAX_OUVERTS >= 20
