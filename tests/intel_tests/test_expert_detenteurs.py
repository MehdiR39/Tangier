"""L expert detenteurs : ses bornes sont gelees, et il ne juge que ce qui vient apres son gel.

Il existe pour une raison precise -- etre DECORRELE du modele de prix (0,682 contre 0,939 entre
notre ensemble et notre foret) -- et non pour etre meilleur : seul, il fait moins bien que le prix.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from intel.research import expert_detenteurs as X
from intel.research.ensemble import Ensemble


def test_les_bornes_sont_celles_qui_ont_ete_gelees():
    assert X.GEL_DETENTEURS == 1789693200.0      # 18/09/2026 01h00 UTC = 03h00 Paris
    assert (X.N_CRITERE, X.JOURS_CRITERE) == (1000, 21)


def test_il_ne_regarde_QUE_la_detention(tmp_path):
    """S il voyait un prix, il ne serait plus decorrele -- et c est sa decorrelation qui fait
    toute sa valeur, pas sa performance."""
    import os
    if not os.path.exists(X.CHEMIN):
        pytest.skip("modele non exporte dans cet environnement")
    assert Ensemble(X.CHEMIN).variables == ["sac1", "n_sacs5"]


def _base(tmp_path, lignes):
    social = tmp_path / "s.sqlite"
    s = sqlite3.connect(str(social))
    s.executescript("CREATE TABLE jeton(pair TEXT, sac1 REAL, n_sacs5 REAL);")
    c = sqlite3.connect(":memory:")
    c.executescript("""CREATE TABLE decision(pair TEXT, t_dec REAL, eligible INTEGER, risque REAL);
                       CREATE TABLE issue(pair TEXT, brut_240 REAL);""")
    for pair, t, risque, sac1, brut in lignes:
        c.execute("INSERT INTO decision VALUES(?,?,1,?)", (pair, t, risque))
        c.execute("INSERT INTO issue VALUES(?,?)", (pair, brut))
        s.execute("INSERT INTO jeton VALUES(?,?,?)", (pair, sac1, 0.9))
    c.commit(); s.commit(); s.close()
    return c, str(social)


def test_aucun_ticket_anterieur_au_gel_n_est_juge(tmp_path, monkeypatch, capsys):
    c, social = _base(tmp_path, [("avant", X.GEL_DETENTEURS - 1, 0.20, 0.5, 0.5),
                                 ("apres", X.GEL_DETENTEURS + 1, 0.20, 0.5, 0.5)])
    monkeypatch.setattr(X, "BASE_SOCIAL", social)
    import os
    if not os.path.exists(X.CHEMIN):
        pytest.skip("modele non exporte dans cet environnement")
    X.rapport(c)
    assert "1 ticket(s) depuis le gel" in capsys.readouterr().out


def test_un_jeton_sans_mesure_de_detention_est_ecarte(tmp_path, monkeypatch, capsys):
    """Le collecteur de detention demarre apres les autres : un ticket qu il n a pas vu ne doit
    pas etre compte comme accepte par defaut."""
    import os
    if not os.path.exists(X.CHEMIN):
        pytest.skip("modele non exporte dans cet environnement")
    c, social = _base(tmp_path, [("a", X.GEL_DETENTEURS + 1, 0.20, None, 0.5),
                                 ("b", X.GEL_DETENTEURS + 2, 0.20, 0.5, 0.5)])
    monkeypatch.setattr(X, "BASE_SOCIAL", social)
    X.rapport(c)
    assert "1 ticket(s) depuis le gel" in capsys.readouterr().out
