"""La confirmation en deuxieme minute marche-t-elle aussi sur Solana ?

C est la seule chose solide trouvee le 08/09/2026 : un pool qui s arrete de negocier pendant sa
deuxieme minute est un pool mort, et l ecarter fait passer le carnet Robinhood de -0,21 a +0,14 par
euro engage, avec les pools morts qui tombent de 39 % a 10 %.

Personne n a teste si ca transfere sur Solana. La question compte plus la que sur l autre chaine,
parce que Solana est le carnet ou les sorties aboutissent toujours : y ajouter un filtre qui evite
les lancements sans lendemain, c est ameliorer une strategie qui fonctionne plutot que reparer une
strategie cassee.

La mesure d activite disponible ici est `buys_m5 + sells_m5`, un compteur glissant sur cinq
minutes. A t+2 il couvre toute la vie du pool, donc la difference entre t+2 et t+1 approche
l activite de la deuxieme minute. C est une approximation, elle est dite comme telle.
"""
from __future__ import annotations

import argparse
import sqlite3
import statistics
from typing import Any

FEE_PCT = 0.30
GAS_EUR = 0.02
TICKET = 5.0


def proche(obs: list[sqlite3.Row], age: float, tol: float = 0.6) -> sqlite3.Row | None:
    """L observation la plus proche de `age` minutes, si elle existe dans la tolerance."""
    cand = [o for o in obs if abs(float(o["age_min"]) - age) <= tol]
    return min(cand, key=lambda o: abs(float(o["age_min"]) - age)) if cand else None


def charge(db: str) -> list[dict[str, Any]]:
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    out = []
    for p in c.execute(
            "SELECT p.pair_id, p.dex, f.trades, f.uniq_payers FROM sol_pair p "
            "JOIN sol_first_min f ON f.pair_id=p.pair_id WHERE f.trades>0 AND f.uniq_payers>0"):
        obs = c.execute("SELECT age_min, price_usd, buys_m5, sells_m5 FROM sol_obs "
                        "WHERE pair_id=? AND price_usd>0 ORDER BY age_min", (p["pair_id"],)).fetchall()
        if len(obs) < 4:
            continue
        o1, o2 = proche(obs, 1.0), proche(obs, 2.0)
        if o1 is None or o2 is None:
            continue
        a1 = (o1["buys_m5"] or 0) + (o1["sells_m5"] or 0)
        a2 = (o2["buys_m5"] or 0) + (o2["sells_m5"] or 0)
        entree = proche(obs, 2.0)
        out.append({
            "dex": p["dex"], "trades": p["trades"], "payers": p["uniq_payers"],
            "ratio": p["trades"] / max(p["uniq_payers"], 1),
            "minute2": max(a2 - a1, 0),
            "a1": a1,
            "px_t1": float(o1["price_usd"]), "px_t2": float(entree["price_usd"]),
            "chemin": [(float(o["age_min"]), float(o["price_usd"])) for o in obs],
        })
    return out


def resultat(r: dict[str, Any], *, entree: float, tp: float, fenetre: float,
             morts_sous: int) -> float:
    suite = [x for x in r["chemin"] if x[0] > entree]
    if not suite:
        return -TICKET - GAS_EUR
    px0 = r["px_t2"] if entree >= 2.0 else r["px_t1"]
    if px0 <= 0:
        return -TICKET - GAS_EUR
    if r["minute2"] < morts_sous:
        # Pool sans activite : sur Solana on sort quand meme, mais au prix qu il reste.
        pass
    dedans = [x for x in suite if x[0] <= entree + fenetre]
    if not dedans:
        return -TICKET - GAS_EUR
    mult = tp if (tp and any(px / px0 >= tp for _t, px in dedans)) else dedans[-1][1] / px0
    mult = min(mult, 50.0)
    return TICKET * mult * (1 - FEE_PCT / 100) ** 2 - TICKET - GAS_EUR


def stat(g: list[float]) -> tuple[int, float, float, float, float] | None:
    if len(g) < 10:
        return None
    s = sorted(g, reverse=True)
    k = max(1, int(len(s) * 0.9))
    return (len(g), sum(1 for x in g if x > 0) / len(g), sum(g) / len(g) / TICKET,
            statistics.median(g) / TICKET, sum(s[len(s) - k:]) / k / TICKET)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="/app/data/solana.sqlite")
    ap.add_argument("--min-payers", type=int, default=75)
    ap.add_argument("--max-trades", type=int, default=600)
    args = ap.parse_args()

    rows = [r for r in charge(args.db)
            if r["dex"] != "pumpfun" and r["ratio"] <= 15
            and r["payers"] >= args.min_payers and r["trades"] < args.max_trades]
    if len(rows) < 15:
        print(f"  seulement {len(rows)} lancements sous la regle en place : echantillon trop mince")
        rows = [r for r in charge(args.db) if r["dex"] != "pumpfun" and r["ratio"] <= 15]
        print(f"  on elargit au filtre anti-bundle seul : {len(rows)} lancements\n")
    else:
        print(f"  {len(rows)} lancements sous la regle en place "
              f"(>= {args.min_payers} acheteurs, < {args.max_trades} echanges)\n")

    med = statistics.median(r["minute2"] for r in rows)
    print(f"  activite mediane en 2e minute : {med:.0f} echanges\n")
    print(f"  {'regle':<44}{'n':>5}{'gagnants':>10}{'par euro':>11}{'mediane':>10}{'sans 10% haut':>14}")
    for lab, seuil, entree in (("achat a T+1, sans confirmation", 0, 1.0),
                               ("achat a T+2, sans condition", 0, 2.0),
                               ("achat a T+2 si activite 2e min >= 5", 5, 2.0),
                               ("achat a T+2 si activite 2e min >= 15", 15, 2.0),
                               ("achat a T+2 si activite 2e min >= 30", 30, 2.0),
                               ("achat a T+2 si activite 2e min >= 60", 60, 2.0)):
        g = [r for r in rows if r["minute2"] >= seuil]
        n = [resultat(r, entree=entree, tp=2.0, fenetre=15.0, morts_sous=0) for r in g]
        st = stat(n)
        if st is None:
            print(f"  {lab:<44}{len(n):>5}   trop peu de lignes")
            continue
        print(f"  {lab:<44}{st[0]:>5}{st[1]:>9.0%}{st[2]:>+11.3f}{st[3]:>+10.3f}{st[4]:>+14.3f}")


if __name__ == "__main__":
    main()
