"""Un stop de perte sauverait-il les lignes qui s effondrent ?

Le carnet a un objectif de gain et une limite de temps, mais rien qui coupe une position qui
tombe. Le 08/09/2026 trois lignes sont mortes dans la fenetre sans qu on en sorte :

    DLSS5   vendue x0,11 a T+15    -18,41 EUR
    ZAPE    x1,57 puis x0,04       -19,40 EUR
    FTFS    x1,02 puis x0,01 en deux minutes

Le stop SUIVEUR, teste plus tot, s est revele mauvais : ces jetons bougent de 20 % en permanence
et il sortait sur du bruit. Mais un stop sec depuis le PRIX D ENTREE est une autre regle -- il ne
suit pas le sommet, il ne se declenche que si la position est reellement dans le rouge, et il ne
coupe donc jamais une gagnante.

C est la mesure qui manque. Elle se fait sur les memes lancements que tout le reste.
"""
from __future__ import annotations

import argparse
import statistics
import sys

sys.path.insert(0, "/app")

from intel.research.solana_backtest import FEE_PCT, GAS_EUR, TICKET, load


def resultat(r: dict, *, tp: float, stop: float, hold: float) -> float:
    """Sortie a l objectif, au stop, ou a la fin de la fenetre -- le premier qui arrive.

    `stop` est un multiple : 0,7 veut dire sortir a -30 % du prix d entree. 0 desactive.
    """
    a0, px0 = r["entry_age"], r["entry_px"]
    mult = None
    for age, px, _s in r["path"]:
        if age <= a0:
            continue
        if age > a0 + hold:
            break
        m = px / px0
        mult = m
        if tp and m >= tp:
            mult = tp
            break
        if stop and m <= stop:
            mult = stop            # on sort au stop, pas au plus bas du creux
            break
    if mult is None:
        return -GAS_EUR
    return TICKET * mult * (1 - FEE_PCT / 100) ** 2 - TICKET - GAS_EUR


def stat(n: list[float]) -> tuple[int, float, float, float, float]:
    s = sorted(n, reverse=True)
    k = max(1, int(len(s) * 0.9))
    return (len(n), sum(1 for x in n if x > 0) / len(n), sum(n) / len(n) / TICKET,
            statistics.median(n) / TICKET, sum(s[len(s) - k:]) / k / TICKET)


def ligne(lab: str, n: list[float]) -> None:
    s = stat(n)
    print(f"  {lab:<38}{s[0]:>5}{s[1]:>9.0%}{s[2]:>+11.3f}{s[3]:>+10.3f}{s[4]:>+14.3f}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="/app/data/solana.sqlite")
    ap.add_argument("--min-payers", type=int, default=75)
    ap.add_argument("--max-trades", type=int, default=600)
    ap.add_argument("--tp", type=float, default=1.5)
    ap.add_argument("--hold", type=float, default=15.0)
    args = ap.parse_args()

    rows = [r for r in load(args.db)
            if r["dex"] != "pumpfun" and r["ratio"] <= 15
            and r["payers"] >= args.min_payers and r["trades"] < args.max_trades]
    print(f"  {len(rows)} lancements · objectif x{args.tp} · fenetre {args.hold:.0f} min\n")
    print(f"  {'regle':<38}{'n':>5}{'gagnants':>9}{'par euro':>11}{'mediane':>10}{'sans 10% haut':>14}")

    ligne("sans stop (en place)", [resultat(r, tp=args.tp, stop=0.0, hold=args.hold) for r in rows])
    for stop in (0.9, 0.8, 0.7, 0.6, 0.5, 0.4):
        ligne(f"stop a -{(1 - stop) * 100:.0f} % du prix d entree",
              [resultat(r, tp=args.tp, stop=stop, hold=args.hold) for r in rows])

    print("\n  le meme balayage avec l ancien objectif x2, pour comparaison")
    ligne("x2 sans stop", [resultat(r, tp=2.0, stop=0.0, hold=args.hold) for r in rows])
    for stop in (0.7, 0.5):
        ligne(f"x2 et stop a -{(1 - stop) * 100:.0f} %",
              [resultat(r, tp=2.0, stop=stop, hold=args.hold) for r in rows])


if __name__ == "__main__":
    main()
