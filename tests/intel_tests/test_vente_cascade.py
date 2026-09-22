"""Vendre dans la seconde quand un pool ouvert s effondre (vente_cascade.py, 15/09).

Ce qui est verrouille ici :
  - le declencheur mesure la chute depuis le PLUS HAUT recent, pas depuis la derniere lecture ;
  - en papier il note et ne vend jamais ; en live il vend UNE fois, avec reessai borne ;
  - deux chemins vendent desormais (240 s et cascade) : jamais deux ventes du meme solde, jamais une
    ecriture qui ecrase la vraie vente ;
  - un crash dans les secondes qui suivent l achat ne ferme pas la ligne sur un solde pas encore
    indexe (§5.3) ;
  - une erreur coute un tour, jamais la boucle.
"""
from __future__ import annotations

import asyncio
import base64
from collections import deque

import base58
import pytest

from intel.engines import vente_cascade as vc
from intel.engines.telegram_rapide import TelegramRapide


# ------------------------------------------------------------------------ doublures
class _Config:
    def __init__(self, valeurs=None):
        self.v = valeurs or {}

    def get(self, cle, defaut=None):
        return self.v.get(cle, defaut)


class _Db:
    def __init__(self, lignes):
        self.lignes = {l["mint"]: dict(l) for l in lignes}
        self.ecrits = []

    def query(self, sql, params=()):
        if "statut='OUVERTE'" in sql:
            return [dict(l) for l in self.lignes.values() if l["statut"] == "OUVERTE"]
        return []

    def scalar(self, sql, params=(), defaut=None):
        if sql.startswith("SELECT statut FROM tg_lignes"):
            l = self.lignes.get(params[0])
            return l["statut"] if l else defaut
        return defaut

    def execute(self, sql, params=()):
        self.ecrits.append((sql, params))
        if sql.startswith("UPDATE tg_lignes SET statut='FERMEE'"):
            mint = params[-1]
            l = self.lignes.get(mint)
            if l and ("AND statut='OUVERTE'" not in sql or l["statut"] == "OUVERTE"):
                l["statut"] = "FERMEE"
                l["motif"] = [p for p in params if isinstance(p, str) and p != mint][-1]

    def insert(self, table, row):
        self.ecrits.append(("INSERT " + table, row))


class _Ctx:
    def __init__(self, lignes, config=None):
        self.db = _Db(lignes)
        self.config = _Config(config)


def _ligne(mint="MintA", mode="live", ts_entree=1_000, statut="OUVERTE"):
    return {"mint": mint, "symbole": mint[-3:], "pair_id": "Pool" + mint, "mode": mode,
            "ts_entree": ts_entree, "statut": statut, "prix_entree": 1.0, "mise_eur": 30.0,
            "echecs": 0, "motif": None}


def _moteur(lignes, mode="live", **cfg):
    c = {"telegram_rapide.vente_cascade.mode": mode,
         "telegram_rapide.vente_cascade.seuil_pct": 15.0,
         "telegram_rapide.vente_cascade.fenetre_s": 5.0}
    c.update({"telegram_rapide.vente_cascade." + k: v for k, v in cfg.items()})
    return TelegramRapide(_Ctx(lignes, c), client=None)


def _guet(moteur, prix_par_tour):
    """Un guetteur dont la lecture de pool rend, tour apres tour, les prix fournis."""
    g = vc.GuetCascade(moteur)
    suite = iter(prix_par_tour)

    async def lire(lignes):
        return next(suite)
    g.lire = lire
    return g


# ------------------------------------------------------------------------ declencheur
def test_la_chute_se_mesure_depuis_le_plus_haut_recent():
    h = deque([(0.0, 1.00), (1.0, 1.20), (2.0, 1.10)])
    c, ref = vc.chute(h, 1.02, now=3.0, fenetre_s=5.0)
    assert ref == pytest.approx(1.20)
    assert c == pytest.approx(1.02 / 1.20 - 1)


def test_un_plus_haut_sorti_de_la_fenetre_ne_compte_plus():
    """Une baisse lente sur une minute n est pas une cascade."""
    h = deque([(0.0, 2.00), (58.0, 1.05)])
    c, ref = vc.chute(h, 1.00, now=60.0, fenetre_s=5.0)
    assert ref == pytest.approx(1.05)
    assert c > -0.15


def test_sans_historique_aucune_chute():
    c, ref = vc.chute(deque(), 1.0, now=0.0, fenetre_s=5.0)
    assert c == 0.0 and ref == 1.0


# ------------------------------------------------------------------------ papier / live
@pytest.mark.asyncio
async def test_en_papier_on_note_et_on_ne_vend_jamais():
    m = _moteur([_ligne()], mode="papier")
    appels = []

    async def vendre(*a, **k):
        appels.append(1)
        return 1
    m._vendre_reel = vendre
    g = _guet(m, [{"MintA": 1.0}, {"MintA": 0.5}, {"MintA": 0.4}, {"MintA": 0.3}])
    for t in (0.0, 1.0, 2.0, 3.0):
        await g.tour(now=t)
    assert appels == []
    notes = [e for e in m.ctx.db.ecrits if e[0].startswith("INSERT INTO tg_cascade")]
    assert len(notes) == 1, "une seule note par position, pas une par seconde"
    assert notes[0][1][8] == pytest.approx(-0.5)


@pytest.mark.asyncio
async def test_en_live_une_chute_brutale_vend_une_fois_avec_le_motif_cascade():
    m = _moteur([_ligne()], mode="live")
    appels = []

    async def vendre(l, now, fin, motif=None, cascade=False):
        appels.append((fin, motif, cascade))
        return 1
    m._vendre_reel = vendre
    g = _guet(m, [{"MintA": 1.0}, {"MintA": 0.99}, {"MintA": 0.70}])
    for t in (0.0, 1.0, 2.0):
        await g.tour(now=t)
    assert len(appels) == 1
    fin, motif, cascade = appels[0]
    assert cascade is True and fin == pytest.approx(0.70)
    assert motif.startswith("cascade")


@pytest.mark.asyncio
async def test_une_respiration_normale_ne_declenche_rien():
    m = _moteur([_ligne()], mode="live")
    appels = []

    async def vendre(*a, **k):
        appels.append(1)
        return 1
    m._vendre_reel = vendre
    g = _guet(m, [{"MintA": p} for p in (1.0, 1.03, 0.97, 1.01, 0.93, 0.96, 1.02)])
    for t in range(7):
        await g.tour(now=float(t))
    assert appels == []


@pytest.mark.asyncio
async def test_une_vente_ratee_se_reessaie_mais_pas_a_chaque_seconde_ni_sans_fin():
    m = _moteur([_ligne()], mode="live", reessai_s=2.0, max_essais=3, fenetre_s=100.0)
    appels = []

    async def vendre(*a, **k):
        appels.append(1)
        return 0                                  # la vente echoue, la ligne reste ouverte
    m._vendre_reel = vendre
    g = _guet(m, [{"MintA": 1.0}] + [{"MintA": 0.5}] * 12)
    for t in range(13):
        await g.tour(now=float(t))
    assert len(appels) == 3


@pytest.mark.asyncio
async def test_une_ligne_a_blanc_se_ferme_au_prix_du_crash_sans_signer():
    m = _moteur([_ligne(mode="papier")], mode="live")

    async def interdit(*a, **k):
        raise AssertionError("une ligne a blanc ne doit jamais signer")
    m._vendre_reel = interdit
    g = _guet(m, [{"MintA": 1.0}, {"MintA": 0.6}])
    await g.tour(now=0.0)
    await g.tour(now=1.0)
    l = m.ctx.db.lignes["MintA"]
    assert l["statut"] == "FERMEE" and l["motif"].startswith("cascade")


@pytest.mark.asyncio
async def test_mode_off_ne_lit_meme_pas_le_pool():
    m = _moteur([_ligne()], mode="off")
    g = vc.GuetCascade(m)

    async def lire(lignes):
        raise AssertionError("aucune lecture en mode off")
    g.lire = lire
    assert await g.tour(now=0.0) == 0


# ------------------------------------------------------------------------ verrous de vente
def _sol_factice(monkeypatch, solde=1_000_000, envois=None):
    from intel.execution import solana as sol
    envois = envois if envois is not None else []
    monkeypatch.setattr(sol, "rpc_url", lambda: "http://rpc")
    monkeypatch.setattr(sol, "signer_address", lambda *a, **k: "Moi")

    async def token_balance(*a, **k):
        return solde

    async def prepare_sell(client, **k):
        envois.append(k)
        return {"status": "BUILT", "tx": "tx"}

    async def send(*a, **k):
        await asyncio.sleep(0)
        return "SIGNATURE_DE_VENTE"
    monkeypatch.setattr(sol, "token_balance", token_balance)
    monkeypatch.setattr(sol, "prepare_sell", prepare_sell)
    monkeypatch.setattr(sol, "send", send)
    monkeypatch.setattr(sol, "sign", lambda tx, cle=None: "signe")
    return envois


@pytest.mark.asyncio
async def test_deux_chemins_de_vente_simultanes_ne_vendent_qu_une_fois(monkeypatch):
    envois = _sol_factice(monkeypatch)
    m = _moteur([_ligne()], mode="live")
    l = m.ctx.db.lignes["MintA"]
    r = await asyncio.gather(m._vendre_reel(dict(l), 1240, 0.5),
                             m._vendre_reel(dict(l), 1240, 0.5, motif="cascade : -40 %", cascade=True))
    assert sum(r) == 1
    assert len(envois) == 1


@pytest.mark.asyncio
async def test_une_ligne_deja_vendue_n_est_pas_reecrite(monkeypatch):
    envois = _sol_factice(monkeypatch, solde=0)
    m = _moteur([_ligne(statut="FERMEE")], mode="live")
    m.ctx.db.lignes["MintA"]["motif"] = "tenue de 240 s ecoulee"
    perime = dict(m.ctx.db.lignes["MintA"], statut="OUVERTE")      # lu une seconde plus tot
    assert await m._vendre_reel(perime, 1300, 0.5, motif="cascade", cascade=True) == 0
    assert envois == []
    assert m.ctx.db.lignes["MintA"]["motif"] == "tenue de 240 s ecoulee"


@pytest.mark.asyncio
async def test_un_crash_juste_apres_l_achat_ne_ferme_pas_sur_un_solde_pas_encore_indexe(monkeypatch):
    _sol_factice(monkeypatch, solde=0)
    m = _moteur([_ligne(ts_entree=1_000)], mode="live")
    assert await m._vendre_reel(dict(m.ctx.db.lignes["MintA"]), 1_008, 0.5,
                                motif="cascade", cascade=True) == 0
    assert m.ctx.db.lignes["MintA"]["statut"] == "OUVERTE"


@pytest.mark.asyncio
async def test_la_vente_sur_cascade_part_avec_plus_de_glissement_et_de_priorite(monkeypatch):
    envois = _sol_factice(monkeypatch)
    m = _moteur([_ligne()], mode="live")
    await m._vendre_reel(dict(m.ctx.db.lignes["MintA"]), 1_100, 0.5, motif="cascade : x", cascade=True)
    assert envois[0]["slippage_pct"] >= 40.0
    assert envois[0]["priorite_lamports"] >= 200_000
    assert m.ctx.db.lignes["MintA"]["motif"].startswith("cascade")


@pytest.mark.asyncio
async def test_la_sortie_a_240_s_garde_son_glissement_habituel(monkeypatch):
    envois = _sol_factice(monkeypatch)
    m = _moteur([_ligne()], mode="live")
    await m._vendre_reel(dict(m.ctx.db.lignes["MintA"]), 1_240, 0.9)
    assert envois[0]["slippage_pct"] == pytest.approx(25.0)


# ------------------------------------------------------------------------ lecture du pool
class _Rep:
    def __init__(self, j):
        self.j = j

    def json(self):
        return self.j


class _ClientPool:
    def __init__(self, owner=vc.PAMM, base=1_000_000.0, quote=50.0):
        d = bytearray(301)
        self.base_ta = base58.b58encode(bytes([7] * 32)).decode()
        self.quote_ta = base58.b58encode(bytes([9] * 32)).decode()
        d[vc.OFF_BASE_TA:vc.OFF_BASE_TA + 32] = bytes([7] * 32)
        d[vc.OFF_BASE_TA + 32:vc.OFF_BASE_TA + 64] = bytes([9] * 32)
        self.data, self.owner, self.base, self.quote = bytes(d), owner, base, quote
        self.appels = []

    async def post(self, url, json=None, timeout=None):
        self.appels.append(json["method"])
        if json["method"] == "getAccountInfo":
            return _Rep({"result": {"value": {"owner": self.owner,
                                              "data": [base64.b64encode(self.data).decode(), "base64"]}}})
        if json["method"] == "getMultipleAccounts":
            val = []
            for a in json["params"][0]:
                q = self.base if a == self.base_ta else self.quote
                val.append({"data": {"parsed": {"info": {"tokenAmount": {"uiAmountString": str(q)}}}}})
            return _Rep({"result": {"value": val}})
        return _Rep({"error": {"message": "inattendu"}})


@pytest.mark.asyncio
async def test_le_prix_est_le_rapport_des_reserves_et_le_pool_n_est_resolu_qu_une_fois(monkeypatch):
    from intel.execution import solana as sol
    monkeypatch.setattr(sol, "rpc_url", lambda: "http://rpc")
    m = _moteur([_ligne()], mode="live")
    m.client = _ClientPool(base=1_000_000.0, quote=50.0)
    g = vc.GuetCascade(m)
    lignes = [m.ctx.db.lignes["MintA"]]
    p1 = await g.lire(lignes)
    p2 = await g.lire(lignes)
    assert p1["MintA"] == pytest.approx(5e-5) and p2 == p1
    assert m.client.appels.count("getAccountInfo") == 1


@pytest.mark.asyncio
async def test_un_compte_qui_n_est_pas_un_pool_pumpswap_n_est_pas_lu(monkeypatch):
    from intel.execution import solana as sol
    monkeypatch.setattr(sol, "rpc_url", lambda: "http://rpc")
    m = _moteur([_ligne()], mode="live")
    m.client = _ClientPool(owner="11111111111111111111111111111111")
    g = vc.GuetCascade(m)
    assert await g.lire([m.ctx.db.lignes["MintA"]]) == {}


@pytest.mark.asyncio
async def test_une_erreur_rpc_coute_un_tour_pas_la_boucle(monkeypatch):
    m = _moteur([_ligne()], mode="live", periode_s=0.2)
    g = vc.GuetCascade(m)
    tours = []

    async def tour(now=None):
        tours.append(1)
        raise RuntimeError("429")
    g.tour = tour
    dormir = asyncio.sleep
    monkeypatch.setattr(vc.asyncio, "sleep", lambda s: dormir(0))
    tache = asyncio.ensure_future(g.boucle())
    for _ in range(20):
        await asyncio.sleep(0)
    tache.cancel()
    assert len(tours) >= 2
