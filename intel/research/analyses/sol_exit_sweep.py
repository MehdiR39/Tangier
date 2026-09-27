"""La regle de sortie en production n a jamais ete simulee telle qu elle est.

`solana_backtest.outcome()` connait un objectif et une duree. Il ne connait pas le STOP de perte,
ajoute en production le 08/09/2026 a -30 % (§3.24). Le simulateur juge donc une regle qui n existe
pas, et le journal dit lui-meme qu un simulateur qui se trompe sur la regle en place ne peut pas
trancher entre deux alternatives (§6).

Ce script modelise les trois branches ensemble -- objectif, stop, duree -- et balaie leur produit
sur tout ce qui a ete observe. Trois precautions, les memes que dans le paquet existant :

  1. la periode est coupee en deux moities et rejouee separement : une regle qui ne marche que sur
     une moitie est du bruit ;
  2. le meilleur dixieme des lignes est retire : un avantage porte par trois coups heureux n en est
     pas un ;
  3. les couts sont ceux que Solana facture vraiment, pas zero.

Limite assumee, ecrite ici pour ne pas etre oubliee : le chemin de prix est echantillonne a la
minute. Un stop touche puis rattrape entre deux releves n est pas vu -- le simulateur est donc
OPTIMISTE sur le stop, dans une mesure qu on ne peut pas chiffrer avec ces donnees. Et comme tout
rejeu d observation, il ignore ce que le deployeur fait en reaction a notre propre achat.
"""
from __future__ import annotations

import argparse
import statistics
import sys
from typing import Any

sys.path.insert(0, "/app")

from intel.research.solana_backtest import FEE_PCT, GAS_EUR, load

TICKET = 20.0          # le ticket reel depuis le 08/09, pas les 5 EUR d origine


def entree(r: dict[str, Any], age_min: float) -> tuple[float, float] | None:
    """Premier releve a `age_min` ou apres -- l instant ou l on paie vraiment.

    `solana_backtest.load()` fige l entree au premier releve a T+1. Mais en production on ACHETE a
    T+1,9 en mediane : une minute pour mesurer, puis la decision, la cotation et la signature. Le
    rejeu entre donc avant nous, a un prix que nous ne payons jamais, et empoche une part de la
    montee initiale. C est l hypothese que ce parametre sert a tester.
    """
    for age, px, _s in r["path"]:
        if age >= age_min and px > 0:
            return age, px
    return None


def issue(r: dict[str, Any], tp: float, stop: float, hold_min: float) -> tuple[float, str]:
    """Euros nets pour un ticket, et la branche de sortie qui a decide. Couts compris."""
    a0, px0 = r["entry_age"], r["entry_px"]
    mult, why = None, "jamais recote"
    for age, px, _s in r["path"]:
        if age <= a0:
            continue
        if age > a0 + hold_min:
            break
        m = px / px0
        mult, why = m, "duree"
        # L ordre compte : sur un releve a la minute, si le prix a franchi les deux bornes on ne
        # sait pas laquelle a ete touchee en premier. On retient le STOP -- l hypothese defavorable,
        # celle qui ne flatte pas la regle.
        if stop and m <= stop:
            mult, why = stop, "stop"
            break
        if tp and m >= tp:
            mult, why = tp, "objectif"
            break
    if mult is None:
        return -GAS_EUR, why
    gross = TICKET * mult * (1 - FEE_PCT / 100) ** 2
    return gross - TICKET - GAS_EUR, why


def stats(nets: list[float]) -> dict[str, Any]:
    if not nets:
        return {"n": 0}
    s = sorted(nets, reverse=True)
    coupe = max(1, len(s) // 10)
    return {"n": len(nets), "par_euro": sum(nets) / len(nets) / TICKET,
            "gagnants": sum(1 for x in nets if x > 0) / len(nets),
            "total": sum(nets), "mediane": statistics.median(nets),
            "sans_meilleur_dixieme": sum(s[coupe:]) / max(len(s) - coupe, 1) / TICKET}


def regle_vivante(rows: list[dict[str, Any]], min_payers: int, max_trades: int,
                  max_ratio: float) -> list[dict[str, Any]]:
    return [r for r in rows
            if r["dex"] != "pumpfun" and r["ratio"] <= max_ratio
            and r["payers"] >= min_payers and r["trades"] < max_trades]


def ligne(lab: str, s: dict[str, Any]) -> str:
    if not s["n"]:
        return f"  {lab:<26}      —"
    return (f"  {lab:<26}{s['n']:>5}{s['gagnants']:>9.0%}{s['par_euro']:>+10.3f}"
            f"{s['mediane']:>+10.2f}{s['sans_meilleur_dixieme']:>+12.3f}")


HDR = (f"  {'regle de sortie':<26}{'n':>5}{'gagnants':>9}{'par euro':>10}"
       f"{'mediane':>10}{'sans 10% haut':>12}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="/app/data/solana.sqlite")
    ap.add_argument("--min-payers", type=int, default=75)
    ap.add_argument("--max-trades", type=int, default=600)
    ap.add_argument("--max-ratio", type=float, default=15.0)
    args = ap.parse_args()

    brut = load(args.db)
    rows = regle_vivante(brut, args.min_payers, args.max_trades, args.max_ratio)
    print(f"  {len(brut)} lancements observes · {len(rows)} passent la regle d entree en production\n")
    if len(rows) < 20:
        print("  echantillon trop mince pour conclure quoi que ce soit.")
        return

    prod = (1.5, 0.7, 15)
    print("  La regle en production, simulee entierement pour la premiere fois :")
    print(HDR)
    nets = [issue(r, *prod)[0] for r in rows]
    print(ligne("x1,5 / stop 0,7 / T+15", stats(nets)))
    branches: dict[str, int] = {}
    for r in rows:
        branches[issue(r, *prod)[1]] = branches.get(issue(r, *prod)[1], 0) + 1
    print("  branches de sortie : " + " · ".join(f"{k} {v}" for k, v in sorted(branches.items())))

    print("\n  Le stop sert-il a quelque chose ? (objectif et duree figes)")
    print(HDR)
    for stop in (0, 0.5, 0.6, 0.7, 0.8, 0.9):
        s = stats([issue(r, 1.5, stop, 15)[0] for r in rows])
        print(ligne(f"stop {stop or 'aucun'}", s))

    print("\n  L objectif (stop et duree figes a la production)")
    print(HDR)
    for tp in (1.2, 1.3, 1.5, 1.8, 2.0, 3.0):
        print(ligne(f"objectif x{tp}", stats([issue(r, tp, 0.7, 15)[0] for r in rows])))

    print("\n  La duree (objectif et stop figes a la production)")
    print(HDR)
    for hold in (5, 10, 15, 20, 30, 45, 60):
        print(ligne(f"T+{hold} min", stats([issue(r, 1.5, 0.7, hold)[0] for r in rows])))

    print("\n  Meilleurs triplets du balayage complet, et ce qu ils valent hors echantillon.")
    print("  La periode est coupee en deux par date de creation du pool ; une regle qui ne tient")
    print("  pas sur les deux moities ne vaut rien, quel que soit son score global.")
    med = statistics.median(r["created"] for r in rows)
    tot1 = [r for r in rows if r["created"] <= med]
    tot2 = [r for r in rows if r["created"] > med]
    grille = []
    for tp in (1.2, 1.3, 1.4, 1.5, 1.8, 2.0, 2.5, 3.0):
        for stop in (0, 0.5, 0.6, 0.7, 0.8):
            for hold in (5, 10, 15, 20, 30, 45):
                s = stats([issue(r, tp, stop, hold)[0] for r in rows])
                a = stats([issue(r, tp, stop, hold)[0] for r in tot1])
                b = stats([issue(r, tp, stop, hold)[0] for r in tot2])
                grille.append((s["par_euro"], tp, stop, hold, s, a, b))
    grille.sort(reverse=True)
    print(f"\n  {'regle':<26}{'tout':>9}{'1re moitie':>12}{'2e moitie':>11}{'sans 10% haut':>14}")
    for par, tp, stop, hold, s, a, b in grille[:10]:
        lab = f"x{tp} / stop {stop or '-'} / T+{hold}"
        print(f"  {lab:<26}{par:>+9.3f}{a.get('par_euro', 0):>+12.3f}"
              f"{b.get('par_euro', 0):>+11.3f}{s['sans_meilleur_dixieme']:>+14.3f}")
    prodpar = stats([issue(r, *prod)[0] for r in rows])["par_euro"]
    pa = stats([issue(r, *prod)[0] for r in tot1]).get("par_euro", 0)
    pb = stats([issue(r, *prod)[0] for r in tot2]).get("par_euro", 0)
    print(f"\n  pour comparaison, la production x1,5 / stop 0,7 / T+15 :"
          f" {prodpar:+.3f} par euro (moities {pa:+.3f} / {pb:+.3f})")

    # Le rejeu entre a T+1, la production a T+1,9. Combien de l avantage tient a cette minute ?
    print("\n  L instant d entree. Le rejeu achete a T+1 ; en production on achete a T+1,9 en")
    print("  mediane -- une minute pour mesurer, puis decision, cotation et signature. Si")
    print("  l avantage s evapore en decalant l entree, il n a jamais existe pour nous.")
    print(f"\n  {'entree':<12}{'objectif':<10}{'n':>5}{'gagnants':>9}{'par euro':>10}{'mediane':>10}")
    for age in (1.0, 1.5, 2.0, 3.0):
        decales = []
        for r in rows:
            e = entree(r, age)
            if e is None:
                continue
            q = dict(r)
            q["entry_age"], q["entry_px"] = e
            decales.append(q)
        if len(decales) < 20:
            print(f"  T+{age:<10}  (seulement {len(decales)} lancements, on ne conclut pas)")
            continue
        for tp in (1.5, 2.0):
            s = stats([issue(r, tp, 0.7, 15)[0] for r in decales])
            print(f"  T+{age:<10}x{tp:<9}{s['n']:>5}{s['gagnants']:>9.0%}"
                  f"{s['par_euro']:>+10.3f}{s['mediane']:>+10.2f}")


if __name__ == "__main__":
    main()
