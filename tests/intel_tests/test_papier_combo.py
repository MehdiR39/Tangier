"""Le testeur papier de la combinaison (§3.85) : evaluateur d arbres et variables d entree."""
from __future__ import annotations

import json
import math
import sqlite3

import pytest

from intel.research import papier_combo as PC
from intel.research.arbres import Modele
from intel.research.papier_combo import variables


def _modele(tmp_path, arbres, seuil=0.5):
    d = {"feature_names": ["x", "y"], "tree_info": [{"tree_structure": t} for t in arbres], "seuil_p80": seuil}
    p = tmp_path / "m.json"
    p.write_text(json.dumps(d))
    return Modele(str(p))


def test_une_valeur_absente_suit_le_cote_par_defaut(tmp_path):
    arbre = {"split_feature": 0, "threshold": 1.0, "missing_type": "NaN", "default_left": False,
             "left_child": {"leaf_value": -2.0}, "right_child": {"leaf_value": 2.0}}
    m = _modele(tmp_path, [arbre])
    assert m.probabilite({"x": 0.5}) == pytest.approx(1 / (1 + math.exp(2.0)))
    assert m.probabilite({"x": float("nan")}) == pytest.approx(1 / (1 + math.exp(-2.0)))
    assert m.probabilite({}) == pytest.approx(1 / (1 + math.exp(-2.0)))


def test_les_arbres_s_additionnent_avant_la_sigmoide(tmp_path):
    feuille = {"leaf_value": 0.5}
    m = _modele(tmp_path, [feuille, feuille])
    assert m.probabilite({"x": 1}) == pytest.approx(1 / (1 + math.exp(-1.0)))


def test_la_bande_de_risque_reste_celle_qui_a_ete_gelee():
    """Une regle pre-enregistree ne vaut que si personne ne bouge ses bornes apres coup. Le gel du
    17/09 a 16h30 UTC est l instant AVANT lequel aucun ticket ne compte : c est ce qui separe les
    1 356 tickets qui ont servi a TROUVER la bande de ceux qui la jugeront."""
    assert (PC.BANDE, PC.CRITERE_BANDE, PC.GEL_BANDE) == ((0.20, 0.35), 0.0200, 1789662600.0)


def test_la_bande_ne_juge_rien_avant_son_gel(tmp_path, capsys):
    """Le piege exact de la fois precedente : un gel mal place ferait entrer dans le test des tickets
    deja vus, et la « validation » ne validerait que le choix des bornes."""
    base = tmp_path / "b.sqlite"
    ici = sqlite3.connect(str(base))
    ici.executescript("""CREATE TABLE decision(pair TEXT, t_dec REAL, eligible INTEGER, risque REAL,
                                               cout_reduit REAL);
                         CREATE TABLE issue(pair TEXT, brut_240 REAL);""")
    for pair, t, risque in (("avant", PC.GEL_BANDE - 1, 0.25), ("apres", PC.GEL_BANDE + 1, 0.25),
                            ("hors_bande", PC.GEL_BANDE + 2, 0.40)):
        ici.execute("INSERT INTO decision VALUES(?,?,1,?,0.02)", (pair, t, risque))
        ici.execute("INSERT INTO issue VALUES(?,0.50)", (pair,))
    ici.commit()
    PC.rapport_bande(ici)
    sortie = capsys.readouterr().out
    assert "1 ticket(s) depuis le gel, sur 2 juges" in sortie      # « avant » exclu, « hors_bande » juge mais non pris


def _pts(q=400.0, premier_age=10, v=17.5845):
    return [(premier_age + 10 * i, 1000 + 10 * i, 1e-6 * (1 + 0.01 * i), q, 1e8, v) for i in range(8)]


def test_un_pool_trop_petit_pour_notre_ordre_n_est_pas_eligible():
    assert variables(_pts(q=0.5, v=0.0), 990, []) is None


def test_un_pool_vu_trop_tard_n_est_pas_eligible():
    assert variables(_pts(premier_age=30), 970, []) is None


def test_un_pool_normal_rend_ses_variables_et_la_lecture_d_entree():
    res = variables(_pts(), 990, [900, 1000, 1030])
    assert res is not None
    f, e = res
    assert f["A"] == 45 and f["V"] == 1 and f["n_lect"] == 4
    assert f["lancements_10min"] == 3          # 900, 1000 et 1030 dans la fenetre (435 ; 1035]
    assert f["cout"] == pytest.approx(0.017 + 2 * 0.31 / (400 + 17.5845))


def test_la_bande_pause_reste_celle_qui_a_ete_gelee():
    assert PC.GEL_BP == 1789680600.0          # 17/09/2026 21h30 UTC = 23h30 Paris
    assert (PC.PAUSE_S, PC.SEUIL_PAUSE) == (1800.0, -0.30)


def test_la_pause_part_de_la_CLOTURE_du_perdant_pas_de_son_ouverture():
    """Un moteur ne peut pas reagir a une perte qu il n a pas encore constatee. Le blocage doit
    donc courir depuis la cloture du ticket perdant, pas depuis son entree."""
    perdant = {"t": 0.0, "fin": 242.0, "r": -0.60}
    juste_avant = {"t": 100.0, "fin": 342.0, "r": 1.0}      # ouvert avant que la perte soit connue
    pendant = {"t": 300.0, "fin": 542.0, "r": 1.0}          # dans les 30 min qui suivent la cloture
    apres = {"t": 2100.0, "fin": 2342.0, "r": 1.0}          # 242 + 1800 = 2042, donc autorise
    pris = PC.appliquer_pause([perdant, juste_avant, pendant, apres])
    assert pris == [perdant, juste_avant, apres]


def test_un_petit_perdant_ne_declenche_pas_la_pause():
    perdant = {"t": 0.0, "fin": 242.0, "r": -0.20}          # au-dessus du seuil de -30 %
    suivant = {"t": 300.0, "fin": 542.0, "r": 1.0}
    assert PC.appliquer_pause([perdant, suivant]) == [perdant, suivant]


def test_les_pauses_successives_prolongent_le_blocage():
    a = {"t": 0.0, "fin": 242.0, "r": -0.60}
    b = {"t": 200.0, "fin": 442.0, "r": -0.60}              # ouvert avant, ferme plus tard
    tard = {"t": 2100.0, "fin": 2342.0, "r": 1.0}           # bloque par b jusqu a 442 + 1800 = 2242
    pris = PC.appliquer_pause([a, b, tard])
    assert tard not in pris
