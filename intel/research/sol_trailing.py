"""Un stop suiveur ferait-il mieux que l objectif fixe a x2 ?

L observation qui a ouvert la question vient du reel, le 08/09/2026 : les positions montent puis
retombent avant l echeance des quinze minutes, et l objectif de x2 les laisse passer.

    BIPOLAR   sommet x1,82   vendue x1,44
    NIKEY     sommet x1,50   vendue x0,86
    CPU       sommet x1,80   vendue x1,18   (vu sur l ecran, avant que le sommet soit enregistre)

Trois cas ne decident rien, mais ils designent une regle a tester : sortir des que le prix recule
d un certain pourcentage depuis son plus haut, au lieu d attendre un multiple qui n arrive presque
jamais. Le backtest disait que x2 etait le meilleur reglage -- il ne testait aucun stop suiveur.

Comparaison sur les memes lancements, avec la meme fenetre de quinze minutes comme filet.
"""
from __future__ import annotations

import argparse
import statistics
import sys

sys.path.insert(0, "/app")

from intel.research.solana_backtest import FEE_PCT, GAS_EUR, TICKET, load


def sortie_objectif(r: dict, tp: float, hold: float) -> float:
    """La regle en place : x{tp}, sinon le prix a la fin de la fenetre."""
    a0, px0 = r["entry_age"], r["entry_px"]
    mult = None
    for age, px, _s in r["path"]:
        if age <= a0:
            continue
        if age > a0 + hold:
            break
        if tp and px / px0 >= tp:
            mult = tp
            break
        mult = px / px0
    if mult is None:
        return -GAS_EUR
    return TICKET * mult * (1 - FEE_PCT / 100) ** 2 - TICKET - GAS_EUR


def sortie_suiveuse(r: dict, repli: float, hold: float, tp: float = 0.0) -> float:
    """Sortir au premier recul de `repli` depuis le plus haut vu, ou a la fin de la fenetre.

    Le plus haut est celui des prix DEJA observes : on ne sort jamais retrospectivement au sommet,
    seulement apres l avoir vu passer. C est ce qu un moteur peut faire en direct.
    """
    a0, px0 = r["entry_age"], r["entry_px"]
    sommet = None
    mult = None
    for age, px, _s in r["path"]:
        if age <= a0:
            continue
        if age > a0 + hold:
            break
        m = px / px0
        mult = m
        sommet = m if sommet is None else max(sommet, m)
        if tp and m >= tp:
            mult = tp
            break
        if sommet is not None and sommet > 1.0 and m <= sommet * (1 - repli):
            break                                    # le repli est atteint : on sort ici
    if mult is None:
        return -GAS_EUR
    return TICKET * mult * (1 - FEE_PCT / 100) ** 2 - TICKET - GAS_EUR


def stat(n: list[float]) -> tuple[int, float, float, float, float]:
    s = sorted(n, reverse=True)
    k = max(1, int(len(s) * 0.9))
    return (len(n), sum(1 for x in n if x > 0) / len(n), sum(n) / len(n) / TICKET,
            statistics.median(n) / TICKET, sum(s[len(s) - k:]) / k / TICKET)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="/app/data/solana.sqlite")
    ap.add_argument("--min-payers", type=int, default=75)
    ap.add_argument("--max-trades", type=int, default=600)
    ap.add_argument("--hold", type=float, default=15.0)
    args = ap.parse_args()

    rows = [r for r in load(args.db)
            if r["dex"] != "pumpfun" and r["ratio"] <= 15
            and r["payers"] >= args.min_payers and r["trades"] < args.max_trades]
    print(f"  {len(rows)} lancements sous la regle en place · fenetre {args.hold:.0f} min\n")
    print(f"  {'regle de sortie':<34}{'n':>5}{'gagnants':>10}{'par euro':>11}"
          f"{'mediane':>10}{'sans 10% haut':>14}")

    for tp in (1.5, 2.0, 3.0):
        n = [sortie_objectif(r, tp, args.hold) for r in rows]
        print(f"  {f'objectif x{tp} (en place si x2)':<34}"
              f"{stat(n)[0]:>5}{stat(n)[1]:>9.0%}{stat(n)[2]:>+11.3f}{stat(n)[3]:>+10.3f}{stat(n)[4]:>+14.3f}")
    print()
    for repli in (0.15, 0.20, 0.30, 0.40):
        n = [sortie_suiveuse(r, repli, args.hold) for r in rows]
        print(f"  {f'stop suiveur a -{repli:.0%} du sommet':<34}"
              f"{stat(n)[0]:>5}{stat(n)[1]:>9.0%}{stat(n)[2]:>+11.3f}{stat(n)[3]:>+10.3f}{stat(n)[4]:>+14.3f}")
    print()
    for repli in (0.20, 0.30):
        for tp in (2.0, 3.0):
            n = [sortie_suiveuse(r, repli, args.hold, tp) for r in rows]
            print(f"  {f'suiveur -{repli:.0%} et objectif x{tp:.0f}':<34}"
                  f"{stat(n)[0]:>5}{stat(n)[1]:>9.0%}{stat(n)[2]:>+11.3f}{stat(n)[3]:>+10.3f}{stat(n)[4]:>+14.3f}")


if __name__ == "__main__":
    main()
