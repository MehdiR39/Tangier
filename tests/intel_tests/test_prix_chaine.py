"""Le pool lu dans la transaction de migration doit etre le pool, pas un sniper.

Ces cas rejouent la transaction reelle du jeton `gptnas` (14/09) qui avait fait enregistrer
`LfEcaUf77iEhnz6gFpLqYgDb5Uk6Ekc5n69wu7Qa9Uw` -- un compte du System Program de 0 octet, partage
par cinq jetons differents -- comme `pair_id` de cinq lignes reelles.
"""
from __future__ import annotations

import pytest

from intel.engines.prix_chaine import PAMM, PrixChaine

MINT = "89jjjEQnBFz7KnRZmintDuTemoin1111111111111"
POOL = "9b66Px3PoMpu12LL3dKwU6TxfSmD41oopS4MnS5FevTd"
SNIPER = "LfEcaUf77iEhnz6gFpLqYgDb5Uk6Ekc5n69wu7Qa9Uw"
COURBE = "FX1EjBAshQJoyESo5Q5ymG1zqTtcJPiqk5eDyKbiDTT6"
WSOL = "So11111111111111111111111111111111111111112"

CLES = ["cle0", "base_ta_pool", "quote_ta_pool", "base_ta_sniper", "quote_ta_sniper",
        "base_ta_courbe"]


def _solde(mint, owner, index, montant):
    return {"mint": mint, "owner": owner, "accountIndex": index,
            "uiTokenAmount": {"uiAmountString": montant}}


def _transaction():
    """L ordre est celui de la chaine : le sniper vient APRES le pool, comme dans la vraie."""
    return {"meta": {"err": None, "postTokenBalances": [
        _solde(MINT, POOL, 1, "205700000"),
        _solde(MINT, COURBE, 5, "0"),
        _solde(MINT, SNIPER, 3, "1200000"),
        _solde(WSOL, POOL, 2, "67.901764461"),
        _solde(WSOL, SNIPER, 4, "1.880049314"),
    ]}, "transaction": {"message": {"accountKeys": CLES}}}


class _Faux(PrixChaine):
    """Un PrixChaine dont les appels RPC sont scriptes. Il ne parle a aucun reseau."""

    def __init__(self, tx, comptes):
        self.tx, self.comptes = tx, comptes
        self.appels = []
        self.pools, self.introuvables = {}, {}

    async def _rpc(self, methode, params):
        self.appels.append(methode)
        if methode == "getTransaction":
            return self.tx
        if methode == "getAccountInfo":
            return {"value": self.comptes.get(params[0])}
        return None


def _comptes(owner_du_pool=PAMM, taille=301):
    return {POOL: {"owner": owner_du_pool, "space": taille},
            SNIPER: {"owner": "11111111111111111111111111111111", "space": 0}}


@pytest.mark.asyncio
async def test_retient_le_plus_gros_porteur_pas_le_dernier():
    """Le defaut d origine : la boucle gardait la DERNIERE entree vue, donc le sniper."""
    p = _Faux(_transaction(), _comptes())
    trouve = await p._depuis_migration(MINT, "sig")
    assert trouve is not None
    pool, base_ta, quote_ta = trouve
    assert pool == POOL, "le pool doit etre le plus gros porteur, pas le dernier de la liste"
    assert pool != SNIPER
    assert base_ta == "base_ta_pool"
    assert quote_ta == "quote_ta_pool"


@pytest.mark.asyncio
async def test_refuse_un_compte_qui_n_appartient_pas_au_programme():
    """Meme designe comme plus gros porteur, un compte hors PumpSwap est refuse."""
    p = _Faux(_transaction(), _comptes(owner_du_pool="11111111111111111111111111111111"))
    assert await p._depuis_migration(MINT, "sig") is None


@pytest.mark.asyncio
async def test_refuse_une_taille_de_compte_inattendue():
    p = _Faux(_transaction(), _comptes(taille=0))
    assert await p._depuis_migration(MINT, "sig") is None


@pytest.mark.asyncio
async def test_tolere_une_taille_absente():
    """Tous les noeuds ne renvoient pas `space` ; le proprietaire suffit alors a trancher."""
    p = _Faux(_transaction(), {POOL: {"owner": PAMM}})
    trouve = await p._depuis_migration(MINT, "sig")
    assert trouve is not None and trouve[0] == POOL


@pytest.mark.asyncio
async def test_ignore_la_courbe_de_bonding_a_zero():
    """L ancienne garde-fou reste : une entree a solde nul n est jamais candidate."""
    tx = _transaction()
    tx["meta"]["postTokenBalances"] = [_solde(MINT, COURBE, 5, "0"),
                                       _solde(MINT, POOL, 1, "205700000"),
                                       _solde(WSOL, POOL, 2, "67.9")]
    p = _Faux(tx, _comptes())
    trouve = await p._depuis_migration(MINT, "sig")
    assert trouve is not None and trouve[0] == POOL


@pytest.mark.asyncio
async def test_sans_reserve_wsol_pour_le_pool_on_abandonne():
    """Si le plus gros porteur n a pas de WSOL, on ne devine pas : on laisse la voie de secours."""
    tx = _transaction()
    tx["meta"]["postTokenBalances"] = [_solde(MINT, POOL, 1, "205700000"),
                                       _solde(WSOL, SNIPER, 4, "1.88")]
    p = _Faux(tx, _comptes())
    assert await p._depuis_migration(MINT, "sig") is None


@pytest.mark.asyncio
async def test_une_transaction_en_erreur_ne_donne_aucun_pool():
    tx = _transaction()
    tx["meta"]["err"] = {"InstructionError": [0, "Custom"]}
    p = _Faux(tx, _comptes())
    assert await p._depuis_migration(MINT, "sig") is None


@pytest.mark.asyncio
async def test_le_compte_n_est_verifie_qu_une_fois_par_lancement():
    """La verification coute un appel : elle ne doit pas s ajouter a chaque cycle."""
    p = _Faux(_transaction(), _comptes())
    await p._depuis_migration(MINT, "sig")
    assert p.appels.count("getAccountInfo") == 1
