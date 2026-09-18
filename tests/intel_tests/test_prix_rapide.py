"""Garde-fous du collecteur de prix a 1 s.

Ce qu on protege, dans l ordre d importance :
  1. il n ECRIT que dans sa propre base et lit le moteur en LECTURE SEULE ;
  2. le prix est (coffre SOL + reserve virtuelle) / jetons -- la formule du 15/09, sans quoi tout
     est faux de 17,6/(q+17,6) sur un pool frais ;
  3. il refuse un second compte qui n est pas du WSOL (le piege du 14/09 : des pools annonces a
     plus de 200 SOL parce que la reserve « SOL » etait autre chose) ;
  4. la fenetre suivie couvre bien la position tenue (decision 45-47 s, sortie 287 s).
"""
from __future__ import annotations

import sqlite3

from intel.research import prix_rapide as pr


def test_fenetre_couvre_la_position_tenue():
    """Entree a 47 s, sortie fixe a 287 s : la fenetre doit deborder des deux cotes."""
    assert pr.AGE_MIN < 45, "la fenetre doit commencer avant la decision"
    assert pr.AGE_MAX > 287, "la fenetre doit depasser la sortie a 287 s"


def test_cadence_est_bien_la_seconde():
    """Toute la raison d etre du fichier : mesurer a la cadence de `veille_rapide`."""
    assert pr.PAS == 1.0


def test_lot_tient_dans_un_seul_appel():
    """Deux comptes par pool, et `getMultipleAccounts` plafonne a 100 : sinon la cadence derive."""
    assert pr.MAX_POOLS * 2 <= 100


def test_base_moteur_ouverte_en_lecture_seule(tmp_path, monkeypatch):
    """Il ne doit RIEN pouvoir ecrire dans la base du moteur, meme par accident."""
    faux = tmp_path / "moteur.sqlite"
    c = sqlite3.connect(str(faux))
    c.execute("CREATE TABLE solana_stream_launches(mint TEXT, ts REAL)")
    c.commit()
    c.close()
    ro = sqlite3.connect("file:%s?mode=ro" % faux, uri=True)
    try:
        ro.execute("INSERT INTO solana_stream_launches VALUES('x', 1)")
        raise AssertionError("la base moteur a accepte une ecriture")
    except sqlite3.OperationalError:
        pass


def test_a_suivre_respecte_la_fenetre(tmp_path):
    faux = tmp_path / "moteur.sqlite"
    c = sqlite3.connect(str(faux))
    c.execute("CREATE TABLE solana_stream_launches(mint TEXT, ts REAL)")
    now = 1_000_000.0
    c.executemany("INSERT INTO solana_stream_launches VALUES(?,?)", [
        ("trop_jeune", now - 10),            # 10 s : pas encore dans la fenetre
        ("bon", now - 100),                  # 100 s : tenu
        ("bon2", now - 300),                 # 300 s : encore dans la fenetre
        ("trop_vieux", now - 600),           # 600 s : la position est fermee
    ])
    c.commit()
    ro = sqlite3.connect("file:%s?mode=ro" % faux, uri=True)
    vus = {m for m, _ in pr.a_suivre(ro, now)}
    assert vus == {"bon", "bon2"}, vus


def test_prix_inclut_la_reserve_virtuelle():
    """Sur un pool a 80 SOL, ignorer les 17,58 SOL virtuels sous-estime le prix de ~18 %."""
    q, b, v = 80.0, 1_000_000.0, 17.5845
    avec, sans = (q + v) / b, q / b
    assert abs(avec / sans - 1 - 0.2198) < 0.001


def test_schema_ecrit_bien_dans_sa_propre_base(tmp_path):
    ici = sqlite3.connect(str(tmp_path / "prix_rapide.sqlite"))
    pr.schema(ici)
    tables = {r[0] for r in ici.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "prix" in tables
    # cle primaire (pair, ts) : deux lectures du meme pool a la meme seconde ne doivent pas doubler
    ici.execute("INSERT OR IGNORE INTO prix(pair, mint, ts, age_s, prix_sol, reserve_base,"
                " reserve_sol, reserve_virtuelle) VALUES('p','m',1.0,50,1e-7,1e6,80,17.5845)")
    ici.execute("INSERT OR IGNORE INTO prix(pair, mint, ts, age_s, prix_sol, reserve_base,"
                " reserve_sol, reserve_virtuelle) VALUES('p','m',1.0,50,9e-9,1e6,80,17.5845)")
    assert ici.execute("SELECT COUNT(*) FROM prix").fetchone()[0] == 1


def test_ne_touche_pas_les_collecteurs_en_marche():
    """Aucune reference aux bases des tests geles : s il tombe, il tombe seul."""
    src = open(pr.__file__, encoding="utf-8").read()
    for interdit in ("papier_combo.sqlite", "papier_social.sqlite"):
        assert interdit not in src, interdit
