"""La piste foule pre-enregistree : ses bornes ne doivent plus bouger, et elle ne doit RIEN ecrire.

Une piste pre-enregistree ne vaut que par deux proprietes, toutes deux testees ici :
  - son seuil et son critere sont figes AVANT les donnees qui la jugeront ;
  - elle ne juge aucun ticket anterieur a son gel, sinon elle se valide sur ce qui l a inspiree.
"""
from __future__ import annotations

import sqlite3

import pytest

from intel.research import piste_foule as PF


def test_les_bornes_sont_celles_qui_ont_ete_gelees():
    assert PF.SEUIL_FOULE == 91                  # mediane observee AVANT le gel, jamais reajustee
    assert PF.CRITERE_FOULE == 0.10
    assert PF.GEL_FOULE == 1789675200.0          # 17/09/2026 20h00 UTC = 22h00 Paris
    assert PF.BANDE == (0.20, 0.35)


def test_la_taille_exigee_est_celle_du_calcul_de_puissance():
    """1 566 n est pas un chiffre rond choisi au hasard : c est 32 x (0,70 / 0,10)^2, la taille
    qu il faut pour distinguer 10 points quand un ticket varie de 70. Le changer, ce serait
    s autoriser a conclure sur du bruit."""
    assert PF.N_FOULE == round(32 * (0.70 / PF.CRITERE_FOULE) ** 2)


def test_les_bases_sont_ouvertes_en_lecture_seule():
    """Mes propres rapports ont deja tue deux tests geles en ecrivant dans leurs bases."""
    assert "mode=ro" in PF.BASE_COMBO and "mode=ro" in PF.BASE_LARGE


def test_un_nan_est_ecarte_avant_tout_tri():
    """Un NaN ne leve pas d erreur : il rend `sorted()` arbitraire en silence et fabrique un
    resultat. Le 17/09 ca m a donne un AUC 0,221 spectaculaire et faux."""
    assert PF._propre(3) and PF._propre(0.5)
    assert not PF._propre(float("nan"))
    assert not PF._propre(None)
    assert not PF._propre("91")


def _base(tmp_path, lignes):
    """Deux bases jointes, comme en production : les decisions d un cote, la foule de l autre."""
    combo, large = tmp_path / "c.sqlite", tmp_path / "l.sqlite"
    cl = sqlite3.connect(str(large))
    cl.executescript("CREATE TABLE decision(pair TEXT, acheteurs INTEGER);")
    cc = sqlite3.connect(str(combo))
    cc.executescript("""CREATE TABLE decision(pair TEXT, t_dec REAL, eligible INTEGER, risque REAL,
                                              cout_reduit REAL);
                        CREATE TABLE issue(pair TEXT, brut_240 REAL);""")
    for pair, t, risque, foule, brut in lignes:
        cc.execute("INSERT INTO decision VALUES(?,?,1,?,0.0)", (pair, t, risque))
        cc.execute("INSERT INTO issue VALUES(?,?)", (pair, brut))
        cl.execute("INSERT INTO decision VALUES(?,?)", (pair, foule))
    cc.commit(); cl.commit(); cl.close()
    return cc, "file:%s?mode=ro" % large


def test_aucun_ticket_anterieur_au_gel_n_est_juge(tmp_path, monkeypatch):
    cc, large = _base(tmp_path, [
        ("avant", PF.GEL_FOULE - 1, 0.25, 120, 0.5),      # dans la bande, mais anterieur au gel
        ("apres", PF.GEL_FOULE + 1, 0.25, 120, 0.5),
        ("hors_bande", PF.GEL_FOULE + 2, 0.40, 120, 0.5),  # posterieur, mais hors bande
        ("sans_foule", PF.GEL_FOULE + 3, 0.25, None, 0.5),  # foule manquante -> ecartee
    ])
    monkeypatch.setattr(PF, "BASE_LARGE", large)
    t = PF.tickets(cc)
    assert [x["t"] for x in t] == [PF.GEL_FOULE + 1]


def test_l_ecart_compare_bien_le_groupe_haut_au_groupe_bas(tmp_path, monkeypatch):
    lignes = []
    for i in range(25):
        lignes.append(("h%d" % i, PF.GEL_FOULE + i, 0.25, PF.SEUIL_FOULE + 10, 0.30))
        lignes.append(("b%d" % i, PF.GEL_FOULE + 100 + i, 0.25, PF.SEUIL_FOULE - 10, 0.10))
    cc, large = _base(tmp_path, lignes)
    monkeypatch.setattr(PF, "BASE_LARGE", large)
    assert PF.ecart(PF.tickets(cc)) == pytest.approx(0.20)


def test_un_groupe_trop_petit_ne_rend_pas_de_verdict(tmp_path, monkeypatch):
    """Sans les deux groupes garnis, un « ecart » ne mesure que le hasard : mieux vaut rien dire."""
    lignes = [("h%d" % i, PF.GEL_FOULE + i, 0.25, PF.SEUIL_FOULE + 10, 0.30) for i in range(25)]
    lignes += [("b%d" % i, PF.GEL_FOULE + 50 + i, 0.25, PF.SEUIL_FOULE - 10, 0.10) for i in range(5)]
    cc, large = _base(tmp_path, lignes)
    monkeypatch.setattr(PF, "BASE_LARGE", large)
    assert PF.ecart(PF.tickets(cc)) is None
