"""Le filtre « trois signes » : ce qu il garde, ce qu il jette, et ce qu il ne doit pas faire.

Active le 14/09 (S3.79). Trois verifications avant T+90 s sur `solana_prix_chaine` :
    P  le prix a l entree est au-dessus de son premier releve, d au moins +0,7 %
    C  il n est jamais descendu sous ce premier releve
    L  la liquidite du pool a grossi d au moins +0,35 %

Le cas le plus important est `test_historique_trop_court_ne_refuse_pas` : confondre « pas
mesurable » et « pas propre » ferait perdre des tickets pour une raison qui n est pas celle du
filtre, et fausserait le comptage de ce qu il ecarte.
"""
from __future__ import annotations

import pytest

from intel.engines.telegram_rapide import TelegramRapide


class _Db:
    def __init__(self, lignes):
        self.lignes = lignes

    def query(self, sql, params=()):
        return self.lignes

    def execute(self, sql, params=()):
        return None

    def scalar(self, sql, params=(), defaut=None):
        return defaut


class _Config:
    def __init__(self, valeurs=None):
        self.valeurs = valeurs or {}

    def get(self, cle, defaut=None):
        return self.valeurs.get(cle.split(".")[-1], defaut)


class _Ctx:
    def __init__(self, lignes, valeurs=None):
        self.db = _Db(lignes)
        self.config = _Config(valeurs)


def _moteur(lignes):
    return TelegramRapide(_Ctx(lignes), client=None)


def _l(prix, reserve):
    return {"prix_sol": prix, "reserve_sol": reserve}


def test_les_trois_signes_reunis_donnent_trois():
    # prix +2 %, jamais sous le depart, liquidite +1 %
    m = _moteur([_l(1.00, 100.0), _l(1.01, 100.5), _l(1.02, 101.0)])
    sg, detail = m._signes_propre("pool", 1000)
    assert sg == 3
    assert detail == "PCL"


def test_un_prix_qui_a_plonge_perd_le_signe_du_creux():
    m = _moteur([_l(1.00, 100.0), _l(0.90, 100.5), _l(1.02, 101.0)])
    sg, detail = m._signes_propre("pool", 1000)
    assert sg == 2
    assert detail == "P-L"


def test_un_prix_qui_finit_sous_son_depart_perd_deux_signes():
    m = _moteur([_l(1.00, 100.0), _l(0.95, 100.5), _l(0.98, 101.0)])
    sg, detail = m._signes_propre("pool", 1000)
    assert sg == 1
    assert detail == "--L"


def test_une_liquidite_qui_recule_perd_le_signe_de_liquidite():
    m = _moteur([_l(1.00, 100.0), _l(1.01, 99.0), _l(1.02, 98.0)])
    sg, detail = m._signes_propre("pool", 1000)
    assert sg == 2
    assert detail == "PC-"


def test_une_hausse_trop_faible_ne_compte_pas():
    """Le seuil est +0,7 % : +0,3 % ne suffit pas."""
    m = _moteur([_l(1.000, 100.0), _l(1.001, 101.0), _l(1.003, 101.0)])
    sg, detail = m._signes_propre("pool", 1000)
    assert detail[0] == "-", "une hausse de 0,3 %% ne doit pas valider le signe du prix"


def test_historique_trop_court_ne_refuse_pas():
    """« pas mesurable » n est pas « pas propre » : le filtre doit renvoyer None, pas zero."""
    for lignes in ([], [_l(1.0, 100.0)], [_l(1.0, 100.0), _l(1.01, 101.0)]):
        sg, _ = _moteur(lignes)._signes_propre("pool", 1000)
        assert sg is None, "un historique de %d releve(s) doit etre indecidable" % len(lignes)


def test_un_prix_de_depart_nul_est_indecidable():
    m = _moteur([_l(0.0, 100.0), _l(1.0, 101.0), _l(1.1, 102.0)])
    assert m._signes_propre("pool", 1000)[0] is None


def test_une_base_qui_leve_ne_fait_pas_tomber_le_moteur():
    class _Casse(_Db):
        def query(self, sql, params=()):
            raise RuntimeError("base indisponible")

    ctx = _Ctx([])
    ctx.db = _Casse([])
    m = TelegramRapide(ctx, client=None)
    assert m._signes_propre("pool", 1000)[0] is None


def test_liquidite_inconnue_au_depart_ne_valide_pas_le_signe():
    """Une reserve initiale a zero ne doit pas compter comme une hausse de liquidite."""
    m = _moteur([_l(1.00, 0.0), _l(1.01, 50.0), _l(1.02, 100.0)])
    sg, detail = m._signes_propre("pool", 1000)
    assert detail[2] == "-"
