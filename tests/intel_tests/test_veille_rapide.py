"""La veille rapide lit le prix dans le pool et REVEILLE le carnet -- elle ne vend jamais.

Ce qui doit etre garanti, parce que c est ce qui a coute de l argent la derniere fois qu on a
accelere le carnet (§3.55, quota Jupiter sature, ventes bloquees) :
  - aucune cotation n est demandee par cette boucle ;
  - sans position ouverte, elle ne fait AUCUNE lecture ;
  - un seuil franchi appelle `run_carnet` une fois, jamais la vente directement ;
  - la meme position n est pas reveillee deux fois en moins de `reveil_min_secondes` ;
  - le prix d entree est repris en SOL dans `solana_prix_chaine`, jamais melange aux dollars de
    `positions.entry_price` ;
  - un second compte qui n est pas du WSOL est ignore (§3.82).
"""
from __future__ import annotations

import base64
import struct

import base58
import pytest

from intel.engines.prix_chaine import OFF_BASE_TA, OFF_RESERVE_VIRTUELLE, TAILLE_POOL
from intel.engines.veille_rapide import VeilleRapide

POOL = "9b66Px3PoMpu12LL3dKwU6TxfSmD41oopS4MnS5FevTd"
BASE_TA = "BaseTA111111111111111111111111111111111111"
QUOTE_TA = "QuoteTA11111111111111111111111111111111111"
WSOL = "So11111111111111111111111111111111111111112"


def _compte_pool(virtuelle=17.5845):
    d = bytearray(TAILLE_POOL)
    d[OFF_BASE_TA:OFF_BASE_TA + 32] = base58.b58decode(BASE_TA).ljust(32, b"\0")[:32]
    d[OFF_BASE_TA + 32:OFF_BASE_TA + 64] = base58.b58decode(QUOTE_TA).ljust(32, b"\0")[:32]
    struct.pack_into("<Q", d, OFF_RESERVE_VIRTUELLE, int(virtuelle * 1e9))
    return {"value": {"data": [base64.b64encode(bytes(d)).decode(), "base64"]}}


def _jeton(montant, mint=None):
    info = {"tokenAmount": {"uiAmountString": str(montant)}}
    if mint:
        info["mint"] = mint
    return {"data": {"parsed": {"info": info}}}


class _Base:
    def __init__(self, positions, prix):
        self.positions, self.prix, self.ecrits = positions, prix, []

    def query(self, sql, params=()):
        if "solana_prix_chaine" in sql:
            return [{"prix_sol": self.prix}] if self.prix else []
        return self.positions

    def execute(self, sql, params=()):
        self.ecrits.append((sql, params))


class _Config:
    def __init__(self, **kv):
        self.kv = {"solana.enabled": True, "solana.veille_rapide.enabled": True, **kv}

    def get(self, cle, defaut=None):
        return self.kv.get(cle, defaut)


class _Ctx:
    def __init__(self, db, config):
        self.db, self.config, self.chain_id = db, config, "solana"


class _Watcher:
    """Un carnet factice : il compte les reveils et refuse de coter."""

    def __init__(self, cfg=None):
        self.reveils = 0
        self.cfg = cfg or {}
        self.client = None

    def _cfg(self, cle, defaut=None):
        return self.cfg.get(cle, defaut)

    async def run_carnet(self):
        self.reveils += 1
        return {"status": "ok"}


def _veille(positions, prix=1.0, comptes=None, cfg=None, config=None):
    ctx = _Ctx(_Base(positions, prix), config or _Config())
    w = _Watcher(cfg or {"take_profit_multiple": 2.0, "stop_loss_multiple": 0.7})
    v = VeilleRapide(ctx, w)
    appels = []

    async def _rpc(methode, params):
        appels.append(methode)
        if methode == "getAccountInfo":
            return _compte_pool()
        return {"value": comptes or []}

    v._rpc = _rpc
    return v, w, appels


def _position(pid=1, pool=POOL, entree=0.001):
    return {"id": pid, "label": "TEMOIN", "notes": f"sol:9 mint:M pool:{pool}",
            "opened_ts": 1000, "entry_price": entree, "peak_price": None}


@pytest.mark.asyncio
async def test_sans_position_aucune_lecture():
    """Le cout de la veille doit etre nul quand le carnet est vide."""
    v, w, appels = _veille([])
    assert (await v.cycle())["positions"] == 0
    assert appels == [] and w.reveils == 0


@pytest.mark.asyncio
async def test_seuil_franchi_reveille_le_carnet_sans_vendre():
    # coffre 100 SOL + 17,5845 virtuels pour 100 jetons -> 1,175845 ; entree 0,5 -> x2,35 >= 2
    v, w, _ = _veille([_position()], prix=0.5, comptes=[_jeton(100), _jeton(100, WSOL)])
    r = await v.cycle()
    assert r["reveils"] == 1 and w.reveils == 1


@pytest.mark.asyncio
async def test_sous_le_seuil_ne_reveille_rien():
    # 1,175845 pour une entree a 1 -> x1,18 : entre le stop (0,7) et l objectif (2)
    v, w, _ = _veille([_position()], prix=1.0, comptes=[_jeton(100), _jeton(100, WSOL)])
    assert "reveils" not in await v.cycle() and w.reveils == 0


@pytest.mark.asyncio
async def test_stop_de_perte_reveille_aussi():
    # 1,175845 pour une entree a 2 -> x0,59, sous le stop a 0,7
    v, w, _ = _veille([_position()], prix=2.0, comptes=[_jeton(100), _jeton(100, WSOL)],
                      cfg={"take_profit_multiple": 99.0, "stop_loss_multiple": 0.7})
    assert (await v.cycle())["reveils"] == 1 and w.reveils == 1


@pytest.mark.asyncio
async def test_pas_deux_reveils_rapproches():
    """La garde qui empeche de refaire le 429 du 11/09 : une position ne rappelle pas le routeur
    plus souvent que la cadence actuelle du carnet, meme si le pool reste au-dessus du seuil."""
    v, w, _ = _veille([_position()], prix=0.5, comptes=[_jeton(100), _jeton(100, WSOL)])
    await v.cycle()
    await v.cycle()
    await v.cycle()
    assert w.reveils == 1


@pytest.mark.asyncio
async def test_second_compte_pas_en_wsol_ignore():
    """36 % des relevés du 14/09 comptaient des unites d autre chose que du SOL (§3.82)."""
    v, w, _ = _veille([_position()], prix=0.5, comptes=[_jeton(100), _jeton(100, "AutreMint111")])
    assert (await v.cycle())["suivies"] == 0 and w.reveils == 0


@pytest.mark.asyncio
async def test_sans_prix_d_entree_en_sol_on_ne_juge_pas():
    """Plutot que comparer un prix de pool (SOL) a `entry_price` (dollars), on s abstient."""
    v, w, _ = _veille([_position()], prix=None, comptes=[_jeton(100), _jeton(100, WSOL)])
    assert (await v.cycle())["suivies"] == 0 and w.reveils == 0


@pytest.mark.asyncio
async def test_position_sans_pool_ignoree():
    p = _position()
    p["notes"] = "sol:9 mint:M"
    v, w, _ = _veille([p])
    assert (await v.cycle())["suivies"] == 0 and w.reveils == 0


@pytest.mark.asyncio
async def test_sommet_mis_a_jour():
    v, w, _ = _veille([_position(entree=0.001)], prix=0.5, comptes=[_jeton(100), _jeton(100, WSOL)])
    await v.cycle()
    ecrits = [e for e in v.ctx.db.ecrits if "peak_price" in e[0]]
    assert ecrits and ecrits[0][1][0] == pytest.approx(0.001 * 1.175845 / 0.5)


@pytest.mark.asyncio
async def test_desactivable():
    v, w, appels = _veille([_position()], config=_Config(**{"solana.veille_rapide.enabled": False}))
    assert (await v.cycle())["status"] == "disabled" and appels == []
