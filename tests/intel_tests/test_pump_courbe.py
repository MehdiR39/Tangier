"""Un collecteur ne doit jamais pouvoir se figer sur une dependance lente.

Le 14/09, `pump_courbe` est reste muet 25 minutes : `_fiche` essaie neuf passerelles IPFS a 15 s
chacune, et rien ne majorait le total. Aucune erreur au journal — une attente infinie ne leve rien,
donc rien ne signalait la panne. Ces cas verrouillent les trois budgets de temps.
"""
from __future__ import annotations

import asyncio

import pytest

from intel.engines.pump_courbe import PumpCourbe


class _Config:
    def __init__(self, valeurs):
        self.valeurs = valeurs

    def get(self, cle, defaut=None):
        return self.valeurs.get(cle.split(".")[-1], defaut)


class _Db:
    def __init__(self):
        self.ecrits = []

    def execute(self, sql, params=()):
        self.ecrits.append((sql, params))

    def query(self, sql, params=()):
        return []

    def scalar(self, sql, params=(), defaut=None):
        return defaut


class _Ctx:
    def __init__(self, valeurs):
        self.config = _Config(valeurs)
        self.db = _Db()


def _moteur(**reglages):
    base = {"enabled": True, "slots_par_cycle": 2, "max_slots": 300, "part_lue": 1.0,
            "suivi_minutes": 45, "budget_blocs_s": 0.3, "budget_social_s": 0.3,
            "budget_prix_s": 0.3}
    base.update(reglages)
    m = PumpCourbe(_Ctx(base), client=None)
    m.dernier_slot = None
    return m


@pytest.mark.asyncio
async def test_les_blocs_trop_lents_n_empechent_pas_le_cycle_de_rendre_la_main():
    m = _moteur()

    async def rpc(methode, params):
        if methode == "getSlot":
            return 1000
        await asyncio.sleep(10)          # un noeud qui accepte et ne repond jamais
        return None

    m._rpc = rpc
    r = await asyncio.wait_for(m.cycle(), timeout=5)
    assert r["status"] == "ok"
    assert r.get("motif") == "blocs trop lents"


@pytest.mark.asyncio
async def test_on_n_insiste_pas_sur_les_memes_slots_apres_un_abandon():
    """Sinon le collecteur rejouerait eternellement les slots qui l ont fait echouer."""
    m = _moteur()

    async def rpc(methode, params):
        if methode == "getSlot":
            return 1000
        await asyncio.sleep(10)
        return None

    m._rpc = rpc
    await asyncio.wait_for(m.cycle(), timeout=5)
    assert m.dernier_slot is not None and m.dernier_slot > 0


@pytest.mark.asyncio
async def test_une_lecture_ipfs_qui_pend_n_arrete_pas_le_cycle():
    m = _moteur()

    async def rpc(methode, params):
        if methode == "getSlot":
            return 1000
        return {"transactions": []}

    async def social_qui_pend(mints):
        await asyncio.sleep(10)
        return 99

    async def prix(now):
        return 7

    m._rpc = rpc
    m._mints_du_bloc = lambda b: ["MintQuiSeraLu1111111111111111111111111111111"]
    m._lire_social = social_qui_pend
    m._suivre_prix = prix
    r = await asyncio.wait_for(m.cycle(), timeout=5)
    assert r["status"] == "ok"
    assert r["lus"] == 0, "une lecture abandonnee ne doit pas etre comptee"
    assert r["prix"] == 7, "le suivi des prix doit quand meme avoir lieu"


@pytest.mark.asyncio
async def test_un_suivi_de_prix_qui_pend_n_arrete_pas_le_cycle():
    m = _moteur()

    async def rpc(methode, params):
        if methode == "getSlot":
            return 1000
        return {"transactions": []}

    async def social(mints):
        return 3

    async def prix_qui_pend(now):
        await asyncio.sleep(10)
        return 99

    m._rpc = rpc
    m._mints_du_bloc = lambda b: ["MintQuiSeraLu1111111111111111111111111111111"]
    m._lire_social = social
    m._suivre_prix = prix_qui_pend
    r = await asyncio.wait_for(m.cycle(), timeout=5)
    assert r["status"] == "ok"
    assert r["lus"] == 3
    assert r["prix"] == 0


@pytest.mark.asyncio
async def test_le_cycle_normal_rend_ses_comptes():
    """Le garde-fou ne doit pas changer le comportement quand tout va bien."""
    m = _moteur(budget_blocs_s=5, budget_social_s=5, budget_prix_s=5)

    async def rpc(methode, params):
        if methode == "getSlot":
            return 1000
        return {"transactions": []}

    async def social(mints):
        return len(mints)

    async def prix(now):
        return 42

    m._rpc = rpc
    m._mints_du_bloc = lambda b: ["MintA111111111111111111111111111111111111111"]
    m._lire_social = social
    m._suivre_prix = prix
    r = await m.cycle()
    assert r["status"] == "ok"
    assert r["crees"] >= 1
    assert r["prix"] == 42


@pytest.mark.asyncio
async def test_desactive_ne_fait_rien():
    m = _moteur(enabled=False)
    assert (await m.cycle())["status"] == "disabled"
