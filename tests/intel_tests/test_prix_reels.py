"""Enregistrer le prix REELLEMENT paye et encaisse, lu dans la transaction.

Ajoute le 14/09 au soir. `prix_entree` est une lecture du POOL prise quelques secondes avant
l ordre ; sur ces jetons le prix bouge de 50 % en neuf secondes, donc elle ne dit pas a quel prix on
a achete. TWINEGPT affichait 4,05e-07 alors qu on a paye 8,56e-07.

Sans le prix effectif, deux causes opposees sont indiscernables quand un ticket perd : le jeton a
baisse APRES l achat (mauvais signal) ou on a paye trop cher DES l entree (mauvaise execution).

Le cas qui compte le plus est `test_un_echec_de_lecture_ne_prive_pas_le_carnet_de_son_gain` : ce
supplement de diagnostic ne doit jamais empecher le compte lui-meme d etre ecrit.
"""
from __future__ import annotations

import pytest

from intel.execution.solana import echange_reel


class _Reponse:
    def __init__(self, charge):
        self.charge = charge

    def json(self):
        return self.charge


class _Client:
    def __init__(self, charge):
        self.charge = charge

    async def post(self, url, json=None, timeout=None):
        return _Reponse(self.charge)


MINT = "MintTest1111111111111111111111111111111111"
MOI = "MoiTest11111111111111111111111111111111111"


def _tx(sol_avant, sol_apres, jetons_avant, jetons_apres, err=None):
    return {"result": {
        "meta": {
            "err": err,
            "preBalances": [sol_avant], "postBalances": [sol_apres],
            "preTokenBalances": [{"mint": MINT, "owner": MOI,
                                  "uiTokenAmount": {"uiAmountString": str(jetons_avant)}}],
            "postTokenBalances": [{"mint": MINT, "owner": MOI,
                                   "uiTokenAmount": {"uiAmountString": str(jetons_apres)}}],
        },
        "transaction": {"message": {"accountKeys": [MOI]}},
    }}


@pytest.mark.asyncio
async def test_un_achat_rend_le_sol_paye_et_les_jetons_recus():
    # 1 SOL paye (1e9 lamports), 1 000 000 jetons recus
    cl = _Client(_tx(2_000_000_000, 1_000_000_000, 0, 1_000_000))
    r = await echange_reel(cl, "rpc", "sig", MOI, MINT)
    assert r is not None
    dsol, djetons = r
    assert dsol == pytest.approx(-1.0)
    assert djetons == pytest.approx(1_000_000)
    assert abs(dsol) / djetons == pytest.approx(1e-6), "prix effectif : 1 SOL pour 1e6 jetons"


@pytest.mark.asyncio
async def test_une_vente_rend_des_signes_opposes():
    cl = _Client(_tx(1_000_000_000, 2_500_000_000, 1_000_000, 0))
    dsol, djetons = await echange_reel(cl, "rpc", "sig", MOI, MINT)
    assert dsol > 0 and djetons < 0
    assert abs(dsol) / abs(djetons) == pytest.approx(1.5e-6)


@pytest.mark.asyncio
async def test_une_transaction_en_erreur_ne_rend_rien():
    cl = _Client(_tx(2_000_000_000, 1_000_000_000, 0, 1_000_000, err={"InstructionError": [0, "X"]}))
    assert await echange_reel(cl, "rpc", "sig", MOI, MINT) is None


@pytest.mark.asyncio
async def test_un_portefeuille_absent_de_la_transaction_ne_rend_rien():
    cl = _Client(_tx(2_000_000_000, 1_000_000_000, 0, 1_000_000))
    assert await echange_reel(cl, "rpc", "sig", "QuelqunDAutre", MINT) is None


@pytest.mark.asyncio
async def test_un_autre_jeton_dans_la_transaction_n_est_pas_compte():
    """Une route passant par un jeton intermediaire ne doit pas fausser le compte."""
    charge = _tx(2_000_000_000, 1_000_000_000, 0, 1_000_000)
    charge["result"]["meta"]["postTokenBalances"].append(
        {"mint": "AutreJeton11111111111111111111111111111111", "owner": MOI,
         "uiTokenAmount": {"uiAmountString": "999999999"}})
    cl = _Client(charge)
    _, djetons = await echange_reel(cl, "rpc", "sig", MOI, MINT)
    assert djetons == pytest.approx(1_000_000)


@pytest.mark.asyncio
async def test_un_noeud_qui_leve_ne_fait_pas_tomber_le_moteur():
    class _Casse:
        async def post(self, *a, **k):
            raise RuntimeError("noeud injoignable")

    assert await echange_reel(_Casse(), "rpc", "sig", MOI, MINT) is None
