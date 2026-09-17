"""Le collecteur non-prix : il ne doit RIEN casser, et surtout jamais s arreter.

Il tourne toute la nuit a cote de six tests geles. Les tests portent donc d abord sur sa
resistance -- un appel RPC qui echoue, un jeton sans detenteur, une offre a zero -- et sur le fait
qu il n enregistre que des FAITS, jamais une variable derivee qui pourrait regarder l avenir.
"""
from __future__ import annotations

import sqlite3

import pytest

from intel.research import social_collecte as S


def test_il_n_enregistre_que_des_faits_bruts():
    """La separation qui rend `createur_prec` non fuyante : le collecteur note QUI, l analyse
    compte COMBIEN en ne regardant que ce qui etait connu a l instant de la decision."""
    c = sqlite3.connect(":memory:")
    S.schema(c)
    cols = [r[1] for r in c.execute("PRAGMA table_info(jeton)")]
    assert set(cols) == {"pair", "mint", "naissance", "t_vu", "sac_wallet",
                         "sac1", "n_sacs5", "erreur"}
    for derivee in ("createur_prec", "det_a_vide", "fin_a_vide", "sac1_prec"):
        assert derivee not in cols


def test_un_appel_qui_echoue_n_arrete_pas_la_boucle(monkeypatch):
    """Le 16/09 une erreur DNS d une seconde a tue un test apres trois heures. Ici un pool rate
    doit etre enregistre avec son motif et la boucle continuer."""
    def rpc_casse(_):
        raise RuntimeError("DNS")
    monkeypatch.setattr(S.cc, "rpc", rpc_casse)
    ici = sqlite3.connect(":memory:")
    S.schema(ici)
    moteur = sqlite3.connect(":memory:")
    moteur.executescript("CREATE TABLE solana_prix_chaine(pair_id TEXT, mint TEXT, ts REAL, age_s REAL);")
    import time
    moteur.execute("INSERT INTO solana_prix_chaine VALUES('P','M',?,50)", (time.time(),))
    moteur.commit()
    assert S.tour(ici, moteur) == 1
    r = ici.execute("SELECT sac_wallet, erreur FROM jeton").fetchone()
    assert r[0] is None and "DNS" in r[1]


def test_un_jeton_sans_detenteur_ne_casse_rien(monkeypatch):
    monkeypatch.setattr(S.cc, "rpc", lambda c: {"value": []} if c["method"] == "getTokenLargestAccounts" else None)
    assert S.detenteurs("M") == (None, None, None)


def test_une_offre_a_zero_ne_divise_pas_par_zero(monkeypatch):
    """Un jeton dont l offre lue vaut zero existe : il ne doit pas faire tomber le collecteur."""
    def rpc(c):
        if c["method"] == "getTokenLargestAccounts":
            return {"value": [{"address": "W1", "uiAmount": 5.0}]}
        return {"value": {"uiAmount": 0}}
    monkeypatch.setattr(S.cc, "rpc", rpc)
    assert S.detenteurs("M") == ("W1", None, None)


def test_les_parts_sont_rapportees_a_l_offre_lue(monkeypatch):
    def rpc(c):
        if c["method"] == "getTokenLargestAccounts":
            return {"value": [{"address": "W%d" % i, "uiAmount": v}
                              for i, v in enumerate([40.0, 20.0, 10.0, 5.0, 5.0, 1.0])]}
        return {"value": {"uiAmount": 100.0}}
    monkeypatch.setattr(S.cc, "rpc", rpc)
    sac, s1, s5 = S.detenteurs("M")
    assert sac == "W0"
    assert s1 == pytest.approx(0.40)
    assert s5 == pytest.approx(0.80)          # les CINQ premiers, pas les six


def test_on_ne_fait_qu_un_seul_appel_de_detention(monkeypatch):
    """Le createur et le financeur ont ete abandonnes : ils demandent une pagination lourde et
    n apportent rien de plus que les deux parts de detention (0,682 contre 0,699 pour les cinq).
    Ce test garde la porte fermee -- c est ce genre d appel qui a bloque le collecteur au premier
    essai."""
    appels = []
    monkeypatch.setattr(S.cc, "rpc", lambda c: appels.append(c["method"]) or
                        ({"value": [{"address": "W", "uiAmount": 1.0}]}
                         if c["method"] == "getTokenLargestAccounts" else {"value": {"uiAmount": 10.0}}))
    S.detenteurs("M")
    assert appels == ["getTokenLargestAccounts", "getTokenSupply"]
    assert "getSignaturesForAddress" not in appels


def test_un_pool_trop_jeune_est_ignore(monkeypatch):
    """La decision se prend a 45 s : documenter un pool a 20 s donnerait des detenteurs qui ne
    sont pas ceux qu on verrait au moment de decider."""
    monkeypatch.setattr(S.cc, "rpc", lambda c: None)
    ici = sqlite3.connect(":memory:")
    S.schema(ici)
    moteur = sqlite3.connect(":memory:")
    moteur.executescript("CREATE TABLE solana_prix_chaine(pair_id TEXT, mint TEXT, ts REAL, age_s REAL);")
    import time
    moteur.execute("INSERT INTO solana_prix_chaine VALUES('P','M',?,20)", (time.time(),))
    moteur.commit()
    assert S.tour(ici, moteur) == 0
