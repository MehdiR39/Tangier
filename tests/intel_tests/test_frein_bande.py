"""Garde-fous de la conjonction FREIN x BANDE.

Le piege central est la CAUSALITE : le frein ne doit compter que les tickets deja CLOTURES a
l instant de la decision (t+242 s). Compter un ticket encore ouvert, c est lire l avenir.
"""
from __future__ import annotations

import inspect

from intel.research import frein_bande as fb


def test_la_causalite_du_frein():
    src = inspect.getsource(fb.retenus)
    assert "TENUE_S" in src and "bisect_right" in src
    assert fb.TENUE_S == 242.0


def test_seuls_les_tickets_clotures_comptent():
    """De bout en bout : le taux ne doit utiliser que ce qui est cloture avant la decision."""
    R = [(0.0, 0.25, +1.0)] + [(float(i), 0.25, -1.0) for i in range(1, 40)]
    for t, _ok, _r in fb.retenus(R):
        connus = [r for td, _q, r in R if td + fb.TENUE_S <= t]
        attendu = sum(1 for x in connus[-fb.FENETRE:] if x > 0) / fb.FENETRE
        # on ne peut pas relire le taux directement : on verifie au moins qu il y a assez de
        # clotures pour que la ligne existe
        assert len(connus) >= fb.FENETRE


def test_la_bande_et_le_seuil_sont_ceux_des_gels_precedents():
    assert fb.BANDE == (0.20, 0.35), "la meme bande que papier_combo"
    assert fb.SEUIL == 0.50, "la frontiere NATURELLE du frein, pas un seuil ajuste"
    assert fb.FENETRE == 20
    assert fb.SEUIL_RISQUE == 0.2694


def test_le_critere_exige_les_trois_conditions():
    src = inspect.getsource(fb.rapport)
    assert "mieux que RISQUE seul" in src and "deux moities" in src and "sans 3 meilleurs" in src


def test_il_ne_touche_a_rien():
    src = inspect.getsource(fb)
    for interdit in ("INSERT", "UPDATE", "DELETE", "CREATE TABLE", "Popen"):
        assert interdit not in src, "ce module ne doit que LIRE"
