"""Refuser une cotation trop eloignee du prix qu on vient de lire dans le pool.

Ajoute le 14/09. `slippage_achat_pct` borne la derive entre la cotation et l atterrissage de la
transaction ; il ne dit RIEN de l ecart entre cette cotation et le vrai prix du marche. Mesure sur
60 tickets reels : ecart median +5,8 %, p90 +32,8 %, max +74,0 % -- et les trois plus grosses
pertes de la journee sont trois achats payes 28 a 59 % trop cher.

Le controle compare la cotation a NOTRE lecture du pool. Il ne coute aucun appel : ce prix est deja
lu toutes les dix secondes, et il ne depend d aucune promesse du routeur.
"""
from __future__ import annotations

import pytest

from intel.execution import solana as sol

MINT = "MintDeTest11111111111111111111111111111111"
DECIMALES = 6
SOL_EUR = 100.0
MISE = 100.0                      # 1 SOL exactement, pour que les calculs se lisent


class _Cotation:
    """Une cotation Jupiter, reduite a ce que `prepare_buy` en utilise."""

    def __init__(self, out_amount, impact=0.5):
        self.out_amount = out_amount
        self.price_impact_pct = impact
        self.usable = True
        self.route = "test"


def _quote_qui_rend(jetons_entiers):
    async def faux(client, **kw):
        return _Cotation(int(jetons_entiers * 10 ** DECIMALES))
    return faux


async def _acheter(monkeypatch, prix_pool, jetons_recus, plafond=20.0, retour=0.0):
    monkeypatch.setattr(sol, "quote", _quote_qui_rend(jetons_recus))
    monkeypatch.setattr(sol, "signer_address", lambda *a, **k: None)
    return await sol.prepare_buy(
        None, mint=MINT, size_eur=MISE, sol_eur=SOL_EUR, slippage_pct=20.0,
        max_impact_pct=15.0, max_aller_retour_pct=retour, prix_pool_sol=prix_pool,
        decimales=DECIMALES, max_ecart_pool_pct=plafond)


@pytest.mark.asyncio
async def test_une_cotation_au_prix_du_pool_passe(monkeypatch):
    # 1 SOL contre 1 000 000 jetons -> prix implique 1e-6, exactement celui du pool
    r = await _acheter(monkeypatch, prix_pool=1e-6, jetons_recus=1_000_000)
    assert r["status"] != "REFUSED", r.get("refused_reason")


@pytest.mark.asyncio
async def test_une_cotation_60_pour_cent_trop_chere_est_refusee(monkeypatch):
    """Le cas TWINEGPT : paye 8,56e-07 quand le pool etait a 5,27e-07."""
    # on ne recoit que 625 000 jetons pour 1 SOL -> prix implique 1,6e-6, soit +60 %
    r = await _acheter(monkeypatch, prix_pool=1e-6, jetons_recus=625_000)
    assert r["status"] == "REFUSED"
    assert "au-dessus du pool" in r["refused_reason"]
    assert "60" in r["refused_reason"]


@pytest.mark.asyncio
async def test_le_seuil_est_respecte_au_bord(monkeypatch):
    """A +19 % on passe, a +21 % on refuse : le plafond doit mordre la ou il est pose."""
    passe = await _acheter(monkeypatch, prix_pool=1e-6, jetons_recus=int(1_000_000 / 1.19))
    refuse = await _acheter(monkeypatch, prix_pool=1e-6, jetons_recus=int(1_000_000 / 1.21))
    assert passe["status"] != "REFUSED"
    assert refuse["status"] == "REFUSED"


@pytest.mark.asyncio
async def test_une_cotation_MEILLEURE_que_le_pool_passe(monkeypatch):
    """Le controle ne borne que le surcout. Payer moins cher que le pool n a rien d anormal --
    un autre pool peut etre mieux fourni, et le refuser jetterait de bons tickets."""
    r = await _acheter(monkeypatch, prix_pool=1e-6, jetons_recus=1_500_000)
    assert r["status"] != "REFUSED"


@pytest.mark.asyncio
async def test_sans_prix_de_pool_le_controle_ne_bloque_rien(monkeypatch):
    """« pas mesurable » n est pas « trop cher ». Sans lecture de pool on laisse passer, sinon une
    panne du collecteur arreterait tous les achats sans que rien ne le dise."""
    r = await _acheter(monkeypatch, prix_pool=0.0, jetons_recus=100)
    assert r["status"] != "REFUSED"


@pytest.mark.asyncio
async def test_le_plafond_a_zero_desactive_le_controle(monkeypatch):
    r = await _acheter(monkeypatch, prix_pool=1e-6, jetons_recus=100, plafond=0.0)
    assert r["status"] != "REFUSED"


@pytest.mark.asyncio
async def test_l_impact_reste_verifie_avant(monkeypatch):
    """Le nouveau controle s ajoute aux anciens, il ne les remplace pas."""
    async def cotation_a_gros_impact(client, **kw):
        return _Cotation(1_000_000 * 10 ** DECIMALES, impact=40.0)

    monkeypatch.setattr(sol, "quote", cotation_a_gros_impact)
    monkeypatch.setattr(sol, "signer_address", lambda *a, **k: None)
    r = await sol.prepare_buy(None, mint=MINT, size_eur=MISE, sol_eur=SOL_EUR, slippage_pct=20.0,
                              max_impact_pct=15.0, prix_pool_sol=1e-6, decimales=DECIMALES,
                              max_ecart_pool_pct=20.0)
    assert r["status"] == "REFUSED"
    assert "impact" in r["refused_reason"]
