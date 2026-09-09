"""Ce qu on peut VRAIMENT vendre, a notre taille, contre ce que le marche affiche.

Toutes les regles de sortie qui battent la production dans le rejeu (§3.46) reposent sur un objectif
a x2. Or aucune de nos 25 positions reelles n a jamais atteint x2, sommet median x1,02 (§3.34).
L un des deux se trompe, et il faut le savoir avant de changer quoi que ce soit.

Explication a tester : DexScreener publie un PRIX MOYEN DE MARCHE. Notre carnet, lui, demande au
routeur ce que la position vaut A LA VENTE, POUR NOTRE TAILLE. Sur un pool mince les deux n ont
rien a voir -- x2 au prix moyen peut valoir x1,3 quand on vend reellement.

La mesure ici ne demande ni position ouverte ni argent engage : pour chaque pool suivi, on demande
a Jupiter une cotation d achat de 20 EUR, puis une cotation de revente immediate de ce qu on aurait
recu. Ce qui manque au retour est le cout complet d un aller-retour a notre taille -- frais, impact
a l achat, impact a la vente. Deux cotations, aucun ordre.

Si ce cout est de quelques pour cent, les rejeux sont utilisables et la sortie partielle merite
d etre deployee. S il est de dix ou vingt, tout rejeu bati sur des prix DexScreener est optimiste,
ce qui expliquerait d un coup pourquoi une semaine de backtests ne s est jamais traduite en argent.
"""
from __future__ import annotations

import argparse
import asyncio
import sqlite3
import statistics
import sys
from typing import Any

sys.path.insert(0, "/app")

import httpx

from intel.execution.solana import SOL_MINT, SolanaRefused, quote, sol_eur


async def aller_retour(client: httpx.AsyncClient, mint: str, lamports: int) -> dict[str, Any] | None:
    """Acheter puis revendre aussitot, en cotation seulement. Rend ce qui manque au retour."""
    try:
        achat = await quote(client, input_mint=SOL_MINT, output_mint=mint,
                            amount=lamports, slippage_bps=1500)
        if not achat.usable:
            return None
        vente = await quote(client, input_mint=mint, output_mint=SOL_MINT,
                            amount=achat.out_amount, slippage_bps=1500)
        if not vente.usable:
            return None
    except (SolanaRefused, Exception):  # noqa: BLE001
        return None
    return {"mint": mint, "retour": vente.out_amount / lamports,
            "impact_achat": achat.price_impact_pct, "impact_vente": vente.price_impact_pct,
            "route": achat.route}


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="/app/db/intel.sqlite")
    ap.add_argument("--taille-eur", type=float, default=20.0)
    ap.add_argument("--n", type=int, default=25)
    args = ap.parse_args()

    c = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    mints = [r["mint"] for r in c.execute(
        "SELECT DISTINCT j.mint FROM solana_judgements j JOIN solana_suivi s ON s.pair_id=j.pair_id "
        "WHERE j.mint IS NOT NULL ORDER BY j.ts DESC LIMIT ?", (args.n,))]
    if not mints:
        print("  aucun pool suivi : lancer apres quelques cycles.")
        return

    async with httpx.AsyncClient(headers={"User-Agent": "tangier-intel/recherche"}) as client:
        eur = await sol_eur(client)
        lamports = int(args.taille_eur / eur * 1_000_000_000)
        print(f"  aller-retour de {args.taille_eur:.0f} EUR ({lamports} lamports, 1 SOL = {eur:.0f} EUR)")
        print(f"  sur {len(mints)} pools suivis, en cotation seulement -- aucun ordre envoye\n")
        res = []
        for m in mints:
            r = await aller_retour(client, m, lamports)
            if r:
                res.append(r)
            await asyncio.sleep(0.25)          # on ne bouscule pas l API

    if not res:
        print("  aucune cotation exploitable.")
        return
    pertes = sorted((1 - r["retour"]) * 100 for r in res)
    print(f"  {'ce qui manque au retour':<32}{'valeur':>10}")
    print(f"  {'mediane':<32}{pertes[len(pertes)//2]:>9.1f} %")
    print(f"  {'1er quartile':<32}{pertes[len(pertes)//4]:>9.1f} %")
    print(f"  {'3e quartile':<32}{pertes[3*len(pertes)//4]:>9.1f} %")
    print(f"  {'pire':<32}{pertes[-1]:>9.1f} %")
    print(f"  {'meilleur':<32}{pertes[0]:>9.1f} %")
    ia = statistics.median(r["impact_achat"] for r in res)
    iv = statistics.median(r["impact_vente"] for r in res)
    print(f"\n  impact cote median : {ia:.2f} % a l achat, {iv:.2f} % a la vente")
    print(f"  frais de routage annonces : 0,30 % par sens, soit 0,60 % sur l aller-retour")
    print(f"\n  {sum(1 for p in pertes if p > 10)}/{len(pertes)} pools coutent plus de 10 %"
          f" · {sum(1 for p in pertes if p > 25)}/{len(pertes)} plus de 25 %")
    print("\n  Lecture : ce chiffre est le handicap qu un rejeu bati sur des prix DexScreener ignore.")
    print("  Un objectif a x2 dans le rejeu vaut en realite x2 MOINS ce cout, paye deux fois --")
    print("  a l entree et a la sortie.")


if __name__ == "__main__":
    asyncio.run(main())
