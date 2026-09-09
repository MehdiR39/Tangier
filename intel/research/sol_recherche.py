"""Chercher une regle gagnante honnetement : choisir sur la premiere moitie, juger sur la seconde.

Reproche de l operateur le 09/09, et il est fonde : « tu recuperes des donnees depuis trois jours et
tu es toujours incapable d en profiter ». J avais 745 lancements et 197 000 releves de prix, et je
m en servais pour repondre a des questions une par une -- ce seuil, puis celui-la -- au lieu de
chercher une regle.

Pire, la methode etait fausse. Je regardais les deux moities de la periode PUIS je retenais ce qui
etait positif dans les deux. C est du peeking : en essayant assez de combinaisons, on en trouve
toujours une qui passe les deux, et elle ne vaut rien.

Ce fichier fait ce qu il faut faire :
  1. la periode est coupee en deux par date de creation du pool, une fois pour toutes ;
  2. TOUTE la recherche -- des centaines de combinaisons -- se fait sur la PREMIERE moitie ;
  3. la meilleure combinaison, et elle seule, est ensuite jouee sur la SECONDE, jamais regardee ;
  4. le verdict est ce que rend la seconde moitie, pas ce qu annonce la premiere.

Si la seconde moitie est negative, il n y a pas d avantage et il faut le dire. C est un resultat,
pas un echec : il coute quelques minutes de calcul au lieu de 40 EUR par jour de tickets.

Precautions gardees du paquet existant : entree a T+2 comme en production et non a T+1, couts
reels, et le stop retenu quand un releve a la minute franchit les deux bornes.
"""
from __future__ import annotations

import argparse
import itertools
import statistics
import sys
from typing import Any

sys.path.insert(0, "/app")

from intel.research.solana_backtest import FEE_PCT, GAS_EUR, load

TICKET = 20.0


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
        if stop and m <= stop:          # hypothese defavorable si les deux bornes sont franchies
            mult = stop
            break
        if tp and m >= tp:
            mult = tp
            break
    if mult is None:
        return -GAS_EUR
    return TICKET * mult * (1 - FEE_PCT / 100) ** 2 - TICKET - GAS_EUR


def bilan(nets: list[float]) -> dict[str, Any]:
    if not nets:
        return {"n": 0, "par_euro": 0.0, "gagnants": 0.0, "robuste": 0.0}
    s = sorted(nets, reverse=True)
    coupe = max(1, len(s) // 10)
    return {"n": len(nets), "par_euro": sum(nets) / len(nets) / TICKET,
            "gagnants": sum(1 for x in nets if x > 0) / len(nets),
            "mediane": statistics.median(nets),
            "robuste": sum(s[coupe:]) / max(len(s) - coupe, 1) / TICKET}


def filtre(r: dict[str, Any], p: tuple) -> bool:
    minp, maxt, maxr, mcl, mch = p
    mc = r.get("mcap") or 0
    return (r["payers"] >= minp and r["trades"] < maxt and r["ratio"] <= maxr
            and (not mcl or mc >= mcl) and (not mch or mc < mch))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="/app/data/solana.sqlite")
    ap.add_argument("--entry-age", type=float, default=2.0)
    ap.add_argument("--min-lignes", type=int, default=15,
                    help="une combinaison retenant moins de lignes que ca est ignoree")
    args = ap.parse_args()

    import sqlite3
    c = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    fdv = {}
    for row in c.execute("SELECT pair_id, fdv, age_min FROM sol_obs WHERE fdv > 0 ORDER BY pair_id, age_min"):
        if row["pair_id"] not in fdv and row["age_min"] >= args.entry_age:
            fdv[row["pair_id"]] = float(row["fdv"])

    rows = []
    for r in load(args.db):
        e = entree(r, args.entry_age)
        if e is None:
            continue
        x = dict(r)
        x["entry_age"], x["entry_px"] = e
        x["mcap"] = fdv.get(r["pair"], 0.0)
        rows.append(x)
    rows.sort(key=lambda z: z["created"])
    coupure = rows[len(rows) // 2]["created"]
    un = [r for r in rows if r["created"] <= coupure]
    deux = [r for r in rows if r["created"] > coupure]
    print(f"  {len(rows)} lancements · {len(un)} dans la premiere moitie, {len(deux)} dans la seconde")
    print(f"  la recherche ne voit QUE la premiere ; la seconde sert de verdict\n")

    grille = list(itertools.product(
        (0, 25, 50, 75, 100),                      # plancher d acheteurs
        (300, 450, 600, 1000, 10 ** 9),            # plafond de densite
        (3, 6, 10, 15, 10 ** 9),                   # echanges par acheteur
        (0, 25_000, 50_000),                       # plancher de capitalisation
        (50_000, 150_000, 10 ** 12),               # plafond de capitalisation
    ))
    sorties = list(itertools.product((1.2, 1.5, 1.8, 2.0), (0, 0.6, 0.7, 0.8), (5, 10, 15, 30)))
    print(f"  {len(grille) * len(sorties)} combinaisons essayees sur la premiere moitie")

    meilleures = []
    for p in grille:
        gardes = [r for r in un if filtre(r, p)]
        if len(gardes) < args.min_lignes:
            continue
        for tp, stop, hold in sorties:
            b = bilan([net(r, tp, stop, hold) for r in gardes])
            # On classe sur la ROBUSTESSE, pas sur le rendement brut : une regle portee par ses
            # trois meilleures lignes est exactement ce qu on ne veut pas retenir.
            meilleures.append((b["robuste"], b["par_euro"], p, (tp, stop, hold), b))
    if not meilleures:
        print("  aucune combinaison ne retient assez de lignes.")
        return
    meilleures.sort(reverse=True)

    print(f"\n  Les cinq meilleures sur la premiere moitie, puis ce qu elles donnent sur la seconde :")
    print(f"  {'regle':<52}{'n1':>4}{'moitie 1':>10}{'n2':>5}{'MOITIE 2':>10}{'gagn 2':>8}")
    for _, _, p, s, b1 in meilleures[:5]:
        gardes2 = [r for r in deux if filtre(r, p)]
        b2 = bilan([net(r, *s) for r in gardes2])
        minp, maxt, maxr, mcl, mch = p
        lab = (f"ach>={minp} ech<{maxt if maxt < 10**8 else '-'} r<={maxr if maxr < 10**8 else '-'} "
               f"cap {mcl // 1000}k-{mch // 1000 if mch < 10**11 else '-'}k · x{s[0]}/stop{s[1] or '-'}/T+{s[2]}")
        print(f"  {lab:<52}{b1['n']:>4}{b1['par_euro']:>+10.3f}{b2['n']:>5}{b2['par_euro']:>+10.3f}"
              f"{b2['gagnants']:>8.0%}")

    _, _, p, s, b1 = meilleures[0]
    gardes2 = [r for r in deux if filtre(r, p)]
    b2 = bilan([net(r, *s) for r in gardes2])
    print("\n  VERDICT — la meilleure regle de la premiere moitie, jugee sur la seconde :")
    print(f"    premiere moitie : {b1['n']:>3} lignes · {b1['par_euro']:+.3f} par euro · {b1['gagnants']:.0%} gagnants")
    print(f"    SECONDE MOITIE  : {b2['n']:>3} lignes · {b2['par_euro']:+.3f} par euro · {b2['gagnants']:.0%} gagnants")
    if b2["n"] < args.min_lignes:
        print("    trop peu de lignes hors echantillon : on ne conclut pas.")
    elif b2["par_euro"] > 0:
        print(f"    positive hors echantillon : {b2['par_euro'] * TICKET:+.2f} EUR par ticket de {TICKET:.0f}.")
    else:
        print("    NEGATIVE hors echantillon : la meilleure regle trouvee ne tient pas.")
        print("    Aucun avantage demontre sur ces donnees. Ce n est pas un reglage a chercher.")


if __name__ == "__main__":
    main()
