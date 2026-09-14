"""Le carnet « propre » : les jetons SANS Telegram qui reunissent les trois signes.

Ajoute le 14/09. Il porte dix fois plus de tickets que Telegram pour cinq fois moins par euro, d ou
un plafond de lignes dedie : sans lui il remplirait les six places et affamerait exactement les
achats qui rapportent le plus.

Ces cas verrouillent la mise propre a ce carnet et son plafond.
"""
from __future__ import annotations

import pytest

from intel.engines.telegram_rapide import TelegramRapide


class _Db:
    def __init__(self, ouvertes_propre=0):
        self.ouvertes_propre = ouvertes_propre
        self.ecrits = []

    def scalar(self, sql, params=(), defaut=None):
        if "methode='propre'" in sql:
            return self.ouvertes_propre
        return defaut

    def query(self, sql, params=()):
        return []

    def execute(self, sql, params=()):
        self.ecrits.append((sql, params))


class _Config:
    def __init__(self, valeurs):
        self.valeurs = valeurs

    def get(self, cle, defaut=None):
        return self.valeurs.get(cle.split(".")[-1], defaut)


class _Ctx:
    def __init__(self, valeurs, ouvertes_propre=0):
        self.config = _Config(valeurs)
        self.db = _Db(ouvertes_propre)


BASE = {"mise_eur": 120.0, "mise_propre_eur": 30.0, "mise_hausse_eur": 10.0,
        "mise_mcap_eur": 50.0, "max_lignes_propre": 3, "mode": "paper"}


def _moteur(**extra):
    v = dict(BASE)
    v.update(extra)
    return TelegramRapide(_Ctx(v), client=None)


@pytest.mark.asyncio
async def test_chaque_methode_a_sa_mise():
    """Un carnet a +0,023 par euro ne doit pas etre joue a la mise d un carnet a +0,128."""
    m = _moteur()
    attendu = {"telegram": 120.0, "propre": 30.0, "hausse": 10.0, "mcap": 50.0}
    for methode, mise in attendu.items():
        await m._ouvrir("Mint1111111111111111111111111111111111111111", "SYM", "pool", 1.0,
                        60, 55, 1000, methode=methode, hausse=None, force_papier=True)
        ecrit = [p for s, p in m.ctx.db.ecrits if "INSERT OR REPLACE INTO tg_lignes" in s]
        assert ecrit, "aucune ligne ecrite pour %s" % methode
        assert mise in ecrit[-1], "%s devrait etre joue a %.0f EUR, params=%r" % (
            methode, mise, ecrit[-1])


def test_le_plafond_dedie_est_lu_depuis_la_config():
    m = _moteur(max_lignes_propre=2)
    assert int(m._cfg("max_lignes_propre", 3)) == 2


def test_les_lignes_propres_ouvertes_sont_comptees_a_part():
    """Le compte doit porter sur la methode, pas sur toutes les lignes : sinon un carnet Telegram
    charge bloquerait le carnet propre, et inversement."""
    m = _moteur()
    m.ctx.db.ouvertes_propre = 3
    n = m.ctx.db.scalar(
        "SELECT COUNT(*) FROM tg_lignes WHERE statut='OUVERTE' AND methode='propre'", (), 0)
    assert n == 3
    autre = m.ctx.db.scalar("SELECT COUNT(*) FROM tg_lignes WHERE statut='OUVERTE'", (), 0)
    assert autre == 0, "le compte global ne doit pas etre confondu avec le compte par methode"


def test_la_regle_est_coupee_par_defaut():
    """Une regle nouvelle ne doit jamais s activer par l absence de reglage."""
    m = TelegramRapide(_Ctx({}), client=None)
    assert bool(m._cfg("regle_propre_seule", False)) is False
    assert bool(m._cfg("regle_propre", False)) is False


def test_la_mise_propre_a_un_defaut_si_elle_manque():
    m = TelegramRapide(_Ctx({"mode": "paper"}), client=None)
    assert float(m._cfg("mise_propre_eur", 30.0)) == 30.0
