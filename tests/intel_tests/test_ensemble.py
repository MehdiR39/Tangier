"""L ensemble de modeles : ses bornes sont gelees, et il ne juge rien d avant son gel.

Il existe parce qu un seul modele est un TIRAGE : 96 entrainements identiques donnent de -252 a
+348 EUR sur les memes tickets. Moyenner douze tirages divise l ecart-type par racine de douze --
ce n est pas une decouverte, c est de l arithmetique, et c est verifiable.
"""
from __future__ import annotations

import json
import math

import pytest

from intel.research import ensemble as E


def test_les_bornes_sont_celles_qui_ont_ete_gelees():
    assert E.GEL_ENSEMBLE == 1789687800.0        # 17/09/2026 23h30 UTC = 18/09 01h30 Paris
    assert (E.N_CRITERE, E.JOURS_CRITERE) == (1000, 21)


def _modele(tmp_path, feuilles, seuil=0.5):
    """N modeles d un seul arbre-feuille : leur moyenne est calculable a la main."""
    d = {"feature_names": ["x"], "seuil_p80": seuil, "n_modeles": len(feuilles),
         "modeles": [{"tree_info": [{"tree_structure": {"leaf_value": v}}]} for v in feuilles]}
    p = tmp_path / "e.json"
    p.write_text(json.dumps(d))
    return E.Ensemble(str(p))


def test_la_probabilite_est_la_MOYENNE_des_sigmoides_pas_la_sigmoide_des_moyennes():
    """Piege classique : moyenner les scores bruts avant la sigmoide donne un autre resultat, et
    ce n est pas ce qu on a mesure."""
    import tempfile, pathlib
    with tempfile.TemporaryDirectory() as d:
        e = _modele(pathlib.Path(d), [-2.0, +2.0])
        attendu = (1 / (1 + math.exp(2.0)) + 1 / (1 + math.exp(-2.0))) / 2
        assert e.probabilite({"x": 1.0}) == pytest.approx(attendu)
        assert e.probabilite({"x": 1.0}) == pytest.approx(0.5)      # ici les deux se compensent
        # la sigmoide de la moyenne des bruts donnerait aussi 0,5 : on prend un cas qui separe
        e2 = _modele(pathlib.Path(d), [0.0, 4.0])
        moy_sigmoides = (0.5 + 1 / (1 + math.exp(-4.0))) / 2
        sigmoide_moy = 1 / (1 + math.exp(-2.0))
        assert e2.probabilite({"x": 1.0}) == pytest.approx(moy_sigmoides)
        assert abs(moy_sigmoides - sigmoide_moy) > 0.02              # les deux different bien


def test_une_valeur_absente_suit_le_cote_par_defaut():
    import tempfile, pathlib
    with tempfile.TemporaryDirectory() as d:
        arbre = {"split_feature": 0, "threshold": 1.0, "missing_type": "NaN", "default_left": False,
                 "left_child": {"leaf_value": -2.0}, "right_child": {"leaf_value": 2.0}}
        p = pathlib.Path(d) / "e.json"
        p.write_text(json.dumps({"feature_names": ["x"], "seuil_p80": 0.5, "n_modeles": 1,
                                 "modeles": [{"tree_info": [{"tree_structure": arbre}]}]}))
        e = E.Ensemble(str(p))
        assert e.probabilite({"x": 0.5}) == pytest.approx(1 / (1 + math.exp(2.0)))
        assert e.probabilite({}) == pytest.approx(1 / (1 + math.exp(-2.0)))


def test_le_rapport_ne_juge_rien_avant_le_gel(tmp_path, capsys, monkeypatch):
    import sqlite3
    base = tmp_path / "b.sqlite"
    c = sqlite3.connect(str(base))
    c.executescript("""CREATE TABLE decision(pair TEXT, t_dec REAL, eligible INTEGER, risque REAL,
                                             variables TEXT);
                       CREATE TABLE issue(pair TEXT, brut_240 REAL);""")
    v = json.dumps({"q": 100.0})
    for pair, t in (("avant", E.GEL_ENSEMBLE - 1), ("apres", E.GEL_ENSEMBLE + 1)):
        c.execute("INSERT INTO decision VALUES(?,?,1,0.25,?)", (pair, t, v))
        c.execute("INSERT INTO issue VALUES(?,0.5)", (pair,))
    c.commit()
    monkeypatch.setattr(E, "Ensemble", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError))
    E.rapport(c)
    assert "fichier absent" in capsys.readouterr().out


def test_une_foret_ne_passe_PAS_par_la_sigmoide(tmp_path):
    """Un boosting additionne des scores puis applique la sigmoide. Une foret moyenne des
    PROPORTIONS deja comprises entre 0 et 1. Confondre les deux donnerait des probabilites fausses
    -- 0,5 deviendrait 0,62 -- et un seuil qui ne selectionne plus rien de comparable."""
    p = tmp_path / "f.json"
    p.write_text(json.dumps({
        "feature_names": ["x"], "seuil_p80": 0.5, "n_modeles": 1, "sigmoide": False,
        "modeles": [{"tree_info": [{"tree_structure": {"leaf_value": 0.2}},
                                   {"tree_structure": {"leaf_value": 0.8}}]}]}))
    f = E.Ensemble(str(p))
    assert f.sigmoide is False
    assert f.probabilite({"x": 1.0}) == pytest.approx(0.5)          # la moyenne des feuilles
    assert f.probabilite({"x": 1.0}) != pytest.approx(1 / (1 + math.exp(-1.0)))


def test_une_foret_remplace_une_valeur_absente_par_la_mediane_d_apprentissage(tmp_path):
    """Une foret n a pas de « cote par defaut » : elle a ete entrainee sur des donnees ou les
    trous etaient deja bouches. On transporte donc ces medianes avec elle, sinon un NaN partirait
    du mauvais cote a chaque coupe."""
    arbre = {"split_feature": 0, "threshold": 5.0, "missing_type": "None", "default_left": True,
             "left_child": {"leaf_value": 0.1}, "right_child": {"leaf_value": 0.9}}
    p = tmp_path / "f.json"
    p.write_text(json.dumps({"feature_names": ["x"], "seuil_p80": 0.5, "n_modeles": 1,
                             "sigmoide": False, "medianes": {"x": 9.0},
                             "modeles": [{"tree_info": [{"tree_structure": arbre}]}]}))
    f = E.Ensemble(str(p))
    assert f.probabilite({"x": 1.0}) == pytest.approx(0.1)          # 1 <= 5 -> gauche
    assert f.probabilite({}) == pytest.approx(0.9)                  # mediane 9 > 5 -> droite
