"""Garde-fous du frein sur le taux de gagnants.

Le piege central de ce module est la CAUSALITE : un ticket decide a t ne rend son resultat qu a
t+242 s. Compter un ticket encore ouvert dans le taux recent, c est lire l avenir -- et c est
exactement ce qui a fabrique de faux regimes plus tot dans ce projet.
"""
from __future__ import annotations

import inspect

from intel.research import frein_taux as ft


def test_le_seuil_est_une_frontiere_naturelle_pas_un_reglage():
    """Un seuil ajuste sur les donnees serait invalide d avance. 50 % = plus de perdants que de
    gagnants, une frontiere qui ne doit rien aux donnees."""
    assert ft.SEUIL == 0.50


def test_la_causalite_est_respectee():
    src = inspect.getsource(ft.taux_recents)
    assert "TENUE_S" in src, "le taux doit se calculer sur les tickets CLOTURES, pas decides"
    assert "bisect_right" in src
    assert ft.TENUE_S == 242.0


def test_seuls_les_tickets_clotures_avant_la_decision_comptent():
    """Test de bout en bout : un ticket qui se cloture APRES la decision ne doit pas y entrer."""
    R = [(0.0, +1.0)] + [(float(i), -1.0) for i in range(1, 30)]
    out = ft.taux_recents(R)
    for t, taux, _ in out:
        # a l instant t, seuls les tickets dont t_dec + 242 <= t sont connus
        connus = [x for td, x in R if td + ft.TENUE_S <= t]
        attendu = sum(1 for x in connus[-ft.FENETRE:] if x > 0) / ft.FENETRE
        assert abs(taux - attendu) < 1e-9, "le taux utilise des tickets pas encore clotures"


def test_le_critere_exige_les_trois_conditions():
    src = inspect.getsource(ft.rapport)
    assert "correlation positive" in src and "Q1 pire et Q4 meilleur" in src and "le frein aide" in src
    assert "CRITERE TENU" in src


def test_il_ne_touche_a_rien():
    src = inspect.getsource(ft)
    for interdit in ("INSERT", "UPDATE", "DELETE", "CREATE TABLE", "Popen"):
        assert interdit not in src, "ce module ne doit que LIRE"
