"""Chercher l avantage du cote de la SORTIE, la ou les mesures disent qu il se trouve.

La recherche sur l entree (§3.45) a essaye 72 000 combinaisons de seuils et n a rien trouve qui
survive hors echantillon. Ce n est donc pas la qu il faut chercher.

Mais §3.34 dit autre chose, et je ne l ai jamais exploite : sur les 28 tickets Solana reels, VINGT
ET UN rapportent entre +0,10 et +0,14 par euro, et SEPT effondrements quasi totaux emportent tout.
Le probleme n est pas de choisir quoi acheter, c est de ne pas perdre 90 % sur un ticket sur sept.

Ce fichier cherche donc une regle de SORTIE, l entree restant celle de la production. Quatre formes,
dont trois n ont jamais ete testees :

  1. objectif / stop / duree -- la forme actuelle, pour reference ;
  2. sortie PARTIELLE : vendre une fraction a un premier multiple, laisser courir le reste. C est
     l outil direct contre la queue -- on encaisse avant l effondrement sans renoncer aux x1,5 ;
  3. stop SUIVEUR : sortir quand le prix retombe de X % sous son sommet, ce qui protege un gain
     deja acquis au lieu d attendre un seuil fixe ;
  4. stop qui se RESSERRE avec le temps : large au debut, etroit ensuite.

Meme discipline que §3.45, et c est elle qui compte : toute la recherche se fait sur la PREMIERE
moitie de la periode, la gagnante est ensuite jouee sur la SECONDE, jamais regardee. Le verdict est
ce que rend la seconde moitie.
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
COUT = (1 - FEE_PCT / 100) ** 2


def entree(r: dict[str, Any], age_min: float) -> tuple[float, float] | None:
    for age, px, _s in r["path"]:
        if age >= age_min and px > 0:
            return age, px
    return None


def sortie(r: dict[str, Any], *, tp: float, stop: float, hold: float,
           part: float = 0.0, part_tp: float = 0.0, suiveur: float = 0.0) -> float:
    """Euros nets pour un ticket. `part` de la ligne est vendue des que `part_tp` est touche."""
    a0, px0 = r["entry_age"], r["entry_px"]
    reste, encaisse, sommet = 1.0, 0.0, 1.0
    dernier = None
    for age, px, _s in r["path"]:
        if age <= a0:
            continue
        if age > a0 + hold:
            break
        m = px / px0
        dernier = m
        sommet = max(sommet, m)
        if part > 0 and reste > part and part_tp and m >= part_tp:
            encaisse += part * m
            reste -= part
        # Le stop d abord : sur un releve a la minute, si les deux bornes sont franchies on retient
        # l hypothese defavorable.
        if stop and m <= stop:
            return TICKET * (encaisse + reste * stop) * COUT - TICKET - GAS_EUR
        if suiveur and sommet > 1.0 and m <= sommet * (1 - suiveur):
            return TICKET * (encaisse + reste * m) * COUT - TICKET - GAS_EUR
        if tp and m >= tp:
            return TICKET * (encaisse + reste * tp) * COUT - TICKET - GAS_EUR
    if dernier is None:
        return -GAS_EUR
    return TICKET * (encaisse + reste * dernier) * COUT - TICKET - GAS_EUR


def bilan(nets: list[float]) -> dict[str, Any]:
    if not nets:
        return {"n": 0, "par_euro": 0.0, "gagnants": 0.0, "robuste": 0.0, "pires": 0.0}
    s = sorted(nets, reverse=True)
    coupe = max(1, len(s) // 10)
    return {"n": len(nets), "par_euro": sum(nets) / len(nets) / TICKET,
            "gagnants": sum(1 for x in nets if x > 0) / len(nets),
            "mediane": statistics.median(nets),
            "robuste": sum(s[coupe:]) / max(len(s) - coupe, 1) / TICKET,
            # part des tickets qui perdent plus de la moitie de la mise : la queue, mesuree
            "pires": sum(1 for x in nets if x < -TICKET / 2) / len(nets)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="/app/data/solana.sqlite")
    ap.add_argument("--entry-age", type=float, default=2.0)
    ap.add_argument("--min-payers", type=int, default=75)
    ap.add_argument("--max-trades", type=int, default=450)
    args = ap.parse_args()

    rows = []
    for r in load(args.db):
        if r["dex"] == "pumpfun" or r["payers"] < args.min_payers or r["trades"] >= args.max_trades:
            continue
        e = entree(r, args.entry_age)
        if e is None:
            continue
        x = dict(r)
        x["entry_age"], x["entry_px"] = e
        rows.append(x)
    rows.sort(key=lambda z: z["created"])
    if len(rows) < 40:
        print(f"  {len(rows)} lancements seulement : trop peu pour chercher.")
        return
    coupure = rows[len(rows) // 2]["created"]
    un = [r for r in rows if r["created"] <= coupure]
    deux = [r for r in rows if r["created"] > coupure]
    print(f"  entree de production (>= {args.min_payers} acheteurs, < {args.max_trades} echanges, T+{args.entry_age:g})")
    print(f"  {len(rows)} lancements · {len(un)} pour chercher, {len(deux)} pour juger\n")

    formes: list[tuple[str, dict[str, Any]]] = []
    for tp, stop, hold in itertools.product((1.2, 1.5, 1.8, 2.0, 3.0), (0, 0.5, 0.6, 0.7, 0.8), (5, 10, 15, 30, 60)):
        formes.append((f"x{tp}/stop{stop or '-'}/T+{hold}", dict(tp=tp, stop=stop, hold=hold)))
    for part, ptp, tp, stop, hold in itertools.product((0.3, 0.5, 0.7), (1.15, 1.3, 1.5),
                                                       (2.0, 3.0), (0, 0.6, 0.7), (15, 30, 60)):
        formes.append((f"{int(part*100)}% a x{ptp} puis x{tp}/stop{stop or '-'}/T+{hold}",
                       dict(tp=tp, stop=stop, hold=hold, part=part, part_tp=ptp)))
    for suiv, tp, hold in itertools.product((0.15, 0.25, 0.35, 0.5), (2.0, 3.0, 0), (15, 30, 60)):
        formes.append((f"suiveur -{int(suiv*100)}% / x{tp or '-'} / T+{hold}",
                       dict(tp=tp, stop=0, hold=hold, suiveur=suiv)))
    print(f"  {len(formes)} regles de sortie essayees sur la premiere moitie")

    res = []
    for lab, kw in formes:
        b = bilan([sortie(r, **kw) for r in un])
        res.append((b["robuste"], lab, kw, b))
    res.sort(reverse=True)

    print(f"\n  {'regle de sortie':<44}{'moitie 1':>10}{'queue 1':>9}{'MOITIE 2':>10}{'queue 2':>9}{'gagn 2':>8}")
    for _, lab, kw, b1 in res[:8]:
        b2 = bilan([sortie(r, **kw) for r in deux])
        print(f"  {lab:<44}{b1['par_euro']:>+10.3f}{b1['pires']:>9.0%}{b2['par_euro']:>+10.3f}"
              f"{b2['pires']:>9.0%}{b2['gagnants']:>8.0%}")

    prod = dict(tp=1.5, stop=0.7, hold=15)
    p1, p2 = bilan([sortie(r, **prod) for r in un]), bilan([sortie(r, **prod) for r in deux])
    print(f"\n  {'PRODUCTION x1,5/stop0,7/T+15':<44}{p1['par_euro']:>+10.3f}{p1['pires']:>9.0%}"
          f"{p2['par_euro']:>+10.3f}{p2['pires']:>9.0%}{p2['gagnants']:>8.0%}")

    _, lab, kw, b1 = res[0]
    b2 = bilan([sortie(r, **kw) for r in deux])
    print(f"\n  VERDICT — meilleure regle de la premiere moitie, jugee sur la seconde :")
    print(f"    {lab}")
    print(f"    moitie 1 : {b1['n']:>3} lignes · {b1['par_euro']:+.3f} par euro · queue {b1['pires']:.0%}")
    print(f"    MOITIE 2 : {b2['n']:>3} lignes · {b2['par_euro']:+.3f} par euro · queue {b2['pires']:.0%}")
    gain = (b2["par_euro"] - p2["par_euro"]) * TICKET
    print(f"    contre la production sur la meme moitie : {p2['par_euro']:+.3f} par euro")
    print(f"    soit {gain:+.2f} EUR par ticket de {TICKET:.0f} si l on changeait.")


if __name__ == "__main__":
    main()
