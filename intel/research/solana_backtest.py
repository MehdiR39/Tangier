"""Backtest the Solana T+1 book on what was actually observed, and choose its thresholds.

Twelve hours of minute-by-minute observation of 277 launches, each with the two things Robinhood
Chain could never give at decision time: how many distinct wallets paid in the first minute, and
therefore how many trades each of them made. That ratio is what tells a crowd from a bundle.

What this does, in the order that matters:
  1. sweeps the entry thresholds and the exit rule on the whole sample;
  2. splits the period in two and re-runs, because a rule that only works on one half is noise;
  3. removes the best trades one by one, because an edge carried by three lucky lines is not an edge;
  4. prices the costs Solana actually charges rather than assuming them away.

What it CANNOT show, and no replay of observation ever will: what the deployer does in reaction to
our own purchase. On Robinhood that single unmeasurable turned a backtest that promised +3 EUR per
ticket into a live book that lost 1.72 EUR. The numbers below are therefore an upper bound, and the
only way past it is to buy.
"""
from __future__ import annotations

import argparse
import sqlite3
import statistics
from typing import Any

FEE_PCT = 0.30          # Jupiter route + pool fee, each way
GAS_EUR = 0.02          # Solana fees are cents; this is generous
TICKET = 5.0


def load(db: str) -> list[dict[str, Any]]:
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    out: list[dict[str, Any]] = []
    for p in c.execute(
            "SELECT p.pair_id, p.symbol, p.dex, p.created_ms, f.trades, f.uniq_payers, f.holders "
            "FROM sol_pair p JOIN sol_first_min f ON f.pair_id=p.pair_id "
            "WHERE f.trades>0 AND f.uniq_payers>0"):
        obs = c.execute("SELECT age_min, price_usd, liquidity_usd, buys_m5, sells_m5 FROM sol_obs "
                        "WHERE pair_id=? AND price_usd>0 ORDER BY age_min", (p["pair_id"],)).fetchall()
        if len(obs) < 3:
            continue
        entry = next((o for o in obs if o["age_min"] >= 1), None)
        if entry is None:
            continue
        out.append({
            "pair": p["pair_id"], "symbol": p["symbol"], "dex": p["dex"], "created": p["created_ms"],
            "trades": p["trades"], "payers": p["uniq_payers"], "holders": p["holders"] or 0,
            "ratio": p["trades"] / max(p["uniq_payers"], 1),
            "entry_age": entry["age_min"], "entry_px": entry["price_usd"],
            "path": [(o["age_min"], o["price_usd"], o["sells_m5"] or 0) for o in obs],
        })
    return out


def outcome(r: dict[str, Any], tp: float, hold_min: float) -> float:
    """Net euros for one 5 EUR ticket under one exit rule, costs included."""
    a0, px0 = r["entry_age"], r["entry_px"]
    mult = None
    for age, px, _s in r["path"]:
        if age <= a0:
            continue
        if age > a0 + hold_min:
            break
        if tp and px / px0 >= tp:
            mult = tp
            break
        mult = px / px0
    if mult is None:
        return -GAS_EUR                                  # never priced again: nothing happened
    gross = TICKET * mult * (1 - FEE_PCT / 100) ** 2
    return gross - TICKET - GAS_EUR


def run(rows: list[dict[str, Any]], *, max_ratio: float, exclude: tuple[str, ...],
        tp: float, hold_min: float, min_payers: int = 0) -> dict[str, Any]:
    kept = [r for r in rows
            if (not max_ratio or r["ratio"] <= max_ratio)
            and r["dex"] not in exclude
            and r["payers"] >= min_payers]
    nets = [outcome(r, tp, hold_min) for r in kept]
    if not nets:
        return {"n": 0}
    nets_sorted = sorted(nets, reverse=True)
    return {"n": len(nets), "total": sum(nets), "per": sum(nets) / len(nets),
            "win": sum(1 for x in nets if x > 0) / len(nets),
            "sans_top3": sum(nets_sorted[3:]), "sans_top5": sum(nets_sorted[5:]),
            "median": statistics.median(nets)}


def line(lab: str, r: dict[str, Any]) -> str:
    if not r["n"]:
        return f"  {lab:<34}       —"
    return (f"  {lab:<34}{r['n']:>5}{r['win']:>8.0%}{r['per']:>+9.2f}{r['total']:>+10.2f}"
            f"{r['sans_top3']:>+11.2f}{r['sans_top5']:>+11.2f}")


HDR = f"  {'regle':<34}{'n':>5}{'gagn':>8}{'/ticket':>9}{'total':>10}{'sans top3':>11}{'sans top5':>11}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="/app/data/solana.sqlite")
    args = ap.parse_args()
    rows = load(args.db)
    if not rows:
        print("aucune donnee")
        return
    span = (max(r["created"] for r in rows) - min(r["created"] for r in rows)) / 3_600_000
    print(f"{len(rows)} lancements mesures sur {span:.1f} h · frais {FEE_PCT} % par sens + {GAS_EUR:.2f} EUR\n")

    print("1. SEUIL SUR LES ECHANGES PAR ACHETEUR (sortie x2 ou T+5)")
    print(HDR)
    for mr in (0, 2, 5, 10, 15, 25, 40):
        print(line(f"tous" if not mr else f"<= {mr} echanges par acheteur", run(rows, max_ratio=mr, exclude=(), tp=2.0, hold_min=5)))

    print("\n2. EN ECARTANT PUMP.FUN (seuil 15)")
    print(HDR)
    print(line("tous launchpads", run(rows, max_ratio=15, exclude=(), tp=2.0, hold_min=5)))
    print(line("sans pump.fun", run(rows, max_ratio=15, exclude=("pumpfun",), tp=2.0, hold_min=5)))

    print("\n3. REGLE DE SORTIE (seuil 15, sans pump.fun)")
    print(HDR)
    for tp, hold, lab in ((0, 5, "vendre a T+5"), (1.5, 5, "x1.5 sinon T+5"), (2.0, 5, "x2 sinon T+5"),
                          (3.0, 5, "x3 sinon T+5"), (2.0, 10, "x2 sinon T+10"), (2.0, 30, "x2 sinon T+30"),
                          (0, 15, "vendre a T+15")):
        print(line(lab, run(rows, max_ratio=15, exclude=("pumpfun",), tp=tp, hold_min=hold)))

    print("\n4. STABILITE : premiere moitie de la periode contre seconde")
    print(HDR)
    mid = sorted(r["created"] for r in rows)[len(rows) // 2]
    for lab, sub in (("1re moitie", [r for r in rows if r["created"] <= mid]),
                     ("2de moitie", [r for r in rows if r["created"] > mid])):
        print(line(f"x2 ou T+5, seuil 15, sans pump.fun · {lab}",
                   run(sub, max_ratio=15, exclude=("pumpfun",), tp=2.0, hold_min=5)))


if __name__ == "__main__":
    main()
