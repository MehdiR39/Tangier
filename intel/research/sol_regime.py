"""Le marche donne-t-il encore ce que la regle suppose ? Mesure suivie dans le temps.

Constat du 09/09/2026 qui a motive ce fichier : sur les lancements qui passent la regle d entree,
la part de ceux qui doublent en quinze minutes s effondre -- 23 %, puis 38 %, puis 31 %, puis **7 %**
sur le quart le plus recent. Le rendement du rejeu tombe de +0,277 a +0,050 par euro sur la meme
periode. L avantage n est pas une propriete de la regle, c est une propriete du MARCHE, et il se
consume.

Une strategie de lancement se juge donc sur deux choses distinctes, et les confondre coute cher :
  - la regle est-elle bonne *relativement* aux autres regles ? (c est ce que balaie sol_exit_sweep)
  - le marche paie-t-il encore *en absolu* ? (c est ce que mesure ce fichier)

La seconde question decide de l arret. Une regle peut rester la meilleure de toutes et ne plus
rapporter un centime.

Chaque passage ecrit une ligne dans `sol_regime` : la journee mesuree, le nombre de lancements
eligibles, la part qui traverse chaque multiple, et le rendement du rejeu. La serie se lit d un coup
d oeil et ne depend d aucune memoire humaine.

Ce que la mesure NE dit pas : ce que notre propre achat provoque. Le rejeu est une borne haute. Sur
la meme periode le carnet reel a rendu -0,094 par euro quand le rejeu en promettait +0,050 -- l ecart
est le cout de l execution et de la reaction du deployeur, et il est plus grand que ce qui reste.
"""
from __future__ import annotations

import argparse
import datetime
import sqlite3
import sys
from typing import Any

sys.path.insert(0, "/app")

from intel.research.solana_backtest import FEE_PCT, GAS_EUR, load

TICKET = 20.0
SEUILS = (1.2, 1.5, 2.0)


def entree(r: dict[str, Any], age_min: float) -> tuple[float, float] | None:
    for age, px, _s in r["path"]:
        if age >= age_min and px > 0:
            return age, px
    return None


def net(r: dict[str, Any], tp: float, stop: float, hold: float) -> float:
    a0, px0 = r["entry_age"], r["entry_px"]
    mult = None
    for age, px, _s in r["path"]:
        if age <= a0:
            continue
        if age > a0 + hold:
            break
        m = px / px0
        mult = m
        if stop and m <= stop:
            mult = stop
            break
        if tp and m >= tp:
            mult = tp
            break
    if mult is None:
        return -GAS_EUR
    return TICKET * mult * (1 - FEE_PCT / 100) ** 2 - TICKET - GAS_EUR


def sommet(r: dict[str, Any], hold: float) -> float:
    a0, px0 = r["entry_age"], r["entry_px"]
    hauts = [px / px0 for age, px, _s in r["path"] if a0 < age <= a0 + hold]
    return max(hauts) if hauts else 0.0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="/app/data/solana.sqlite")
    ap.add_argument("--min-payers", type=int, default=75)
    ap.add_argument("--max-trades", type=int, default=600)
    ap.add_argument("--max-ratio", type=float, default=15.0)
    ap.add_argument("--entry-age", type=float, default=2.0, help="on achete a T+1,9 en production")
    ap.add_argument("--hold", type=float, default=15.0)
    ap.add_argument("--ecrire", action="store_true", help="ecrire la serie dans la table sol_regime")
    args = ap.parse_args()

    rows = [r for r in load(args.db)
            if r["dex"] != "pumpfun" and r["ratio"] <= args.max_ratio
            and r["payers"] >= args.min_payers and r["trades"] < args.max_trades]
    par_jour: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        e = entree(r, args.entry_age)
        if e is None:
            continue
        q = dict(r)
        q["entry_age"], q["entry_px"] = e
        jour = datetime.datetime.utcfromtimestamp(r["created"] / 1000.0).strftime("%Y-%m-%d")
        par_jour.setdefault(jour, []).append(q)

    print(f"  entree a T+{args.entry_age:g}, sortie x1,5 / stop 0,7 / T+{args.hold:g}"
          f" -- la regle en production\n")
    print(f"  {'journee':<12}{'n':>4}" + "".join(f"{'>= x' + str(s):>10}" for s in SEUILS)
          + f"{'par euro':>11}")
    lignes = []
    for jour in sorted(par_jour):
        g = par_jour[jour]
        if len(g) < 5:
            print(f"  {jour:<12}{len(g):>4}      (moins de 5 lancements, non mesure)")
            continue
        hauts = [sommet(r, args.hold) for r in g]
        parts = [sum(1 for h in hauts if h >= s) / len(g) for s in SEUILS]
        nets = [net(r, 1.5, 0.7, args.hold) for r in g]
        pe = sum(nets) / len(nets) / TICKET
        print(f"  {jour:<12}{len(g):>4}" + "".join(f"{p:>9.0%} " for p in parts) + f"{pe:>+11.3f}")
        lignes.append((jour, len(g), *parts, pe))

    if args.ecrire and lignes:
        c = sqlite3.connect(args.db)
        c.execute("CREATE TABLE IF NOT EXISTS sol_regime("
                  "  jour TEXT PRIMARY KEY, n INTEGER, part_12 REAL, part_15 REAL, part_20 REAL,"
                  "  par_euro REAL, mesure_ts INTEGER)")
        import time
        c.executemany("INSERT OR REPLACE INTO sol_regime VALUES(?,?,?,?,?,?,?)",
                      [(*l, int(time.time())) for l in lignes])
        c.commit()
        print(f"\n  {len(lignes)} journee(s) ecrites dans sol_regime")

    if len(lignes) >= 2:
        print("\n  Lecture : si la part des lancements qui atteignent x1,5 tombe durablement sous")
        print("  le quart, la regle ne peut plus payer ses frais et il faut arreter d acheter --")
        print("  quelle que soit sa superiorite sur les autres regles.")


if __name__ == "__main__":
    main()
