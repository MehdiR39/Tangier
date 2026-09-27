"""La capitalisation a l entree predit-elle le resultat ?

Hypothese de l operateur, le 08/09/2026 devant LAPTOP : un jeton lance a 154 millions de
capitalisation ne bouge pas, parce qu il faudrait des sommes enormes pour le faire monter -- on
paie donc les frais pour rien. Un jeton a 40 000 se deplace tout seul.

C est mesurable et personne ne l a fait : la collecte enregistre la capitalisation entierement
diluee a chaque instant, donc aussi au moment ou l on entre.

Si l hypothese tient, c est un filtre d entree gratuit -- refuser au-dessus d un certain seuil ne
coute aucun appel et n a aucun effet de bord. Si elle ne tient pas, il faut le dire aussi : ce
serait le troisieme reglage de la journee suggere par une intuition juste et ecarte par la mesure.
"""
from __future__ import annotations

import argparse
import sqlite3
import statistics
import sys

sys.path.insert(0, "/app")

from intel.research.solana_backtest import TICKET, load, outcome

BASE = dict(tp=1.5, hold_min=15)


def mcap_entree(db: str) -> dict[str, float]:
    """Capitalisation au premier releve situe a T+1 ou apres -- le moment de notre achat."""
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    out: dict[str, float] = {}
    for r in c.execute("SELECT pair_id, age_min, fdv FROM sol_obs WHERE fdv > 0 ORDER BY pair_id, age_min"):
        if r["pair_id"] in out:
            continue
        if float(r["age_min"]) >= 1.0:
            out[r["pair_id"]] = float(r["fdv"])
    return out


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
    args = ap.parse_args()

    caps = mcap_entree(args.db)
    rows = [r for r in load(args.db)
            if r["dex"] != "pumpfun" and r["ratio"] <= 15
            and r["payers"] >= args.min_payers and r["trades"] < args.max_trades
            and r["pair"] in caps]
    if len(rows) < 12:
        print(f"  seulement {len(rows)} lancements avec une capitalisation connue sous la regle;")
        print("  on elargit au filtre anti-bundle seul pour avoir de quoi mesurer.")
        rows = [r for r in load(args.db)
                if r["dex"] != "pumpfun" and r["ratio"] <= 15 and r["pair"] in caps]
    for r in rows:
        r["mcap"] = caps[r["pair"]]
    med = statistics.median(r["mcap"] for r in rows)
    print(f"  {len(rows)} lancements · capitalisation mediane a l entree : {med:,.0f} $\n")
    print(f"  {'capitalisation a l entree':<30}{'n':>5}{'gagnants':>10}{'par euro':>11}"
          f"{'mediane':>10}{'sans 10% haut':>14}")
    seuils = [(0, 50_000), (50_000, 150_000), (150_000, 500_000), (500_000, 2_000_000),
              (2_000_000, 10 ** 12)]
    for lo, hi in seuils:
        g = [outcome(r, **BASE) for r in rows if lo <= r["mcap"] < hi]
        if len(g) < 6:
            continue
        s = stat(g)
        lab = f"{lo/1000:,.0f} k a {hi/1000:,.0f} k $" if hi < 10 ** 11 else f"plus de {lo/1e6:,.0f} M $"
        print(f"  {lab:<30}{s[0]:>5}{s[1]:>9.0%}{s[2]:>+11.3f}{s[3]:>+10.3f}{s[4]:>+14.3f}")

    print("\n  et si l on plafonnait la capitalisation a l entree :")
    print(f"  {'regle':<30}{'n':>5}{'gagnants':>10}{'par euro':>11}{'mediane':>10}{'sans 10% haut':>14}")
    for cap in (0, 100_000, 250_000, 1_000_000):
        g = [outcome(r, **BASE) for r in rows if not cap or r["mcap"] < cap]
        if len(g) < 6:
            continue
        s = stat(g)
        lab = "aucun plafond" if not cap else f"moins de {cap/1000:,.0f} k $"
        print(f"  {lab:<30}{s[0]:>5}{s[1]:>9.0%}{s[2]:>+11.3f}{s[3]:>+10.3f}{s[4]:>+14.3f}")


if __name__ == "__main__":
    main()
