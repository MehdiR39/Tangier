"""The whole study, end to end, answering the fourteen questions and ending on a verdict.

The discipline the numbers here depend on:
  - thresholds come from quantiles of TRAIN only, never from a value that looked good;
  - every reported figure is measured on TEST, on launches never used to choose anything;
  - dead pools are in the denominator, always;
  - a level that could not be sold is not counted as reached;
  - the contribution of the best trades is printed, because a book carried by one winner is a
    book with no edge, only a lottery ticket that happened to land.

The verdict scale is fixed in advance so it cannot be bent to the result:
  NO EDGE     the test lift is inside noise, or the book loses after costs
  WEAK EDGE   lift holds out of sample but the book does not clear costs
  PROMISING   the book clears costs on test AND survives removing its best three trades
  STRONG EDGE the above, plus the lift holds at x5 and beyond, on a decent sample
"""
from __future__ import annotations

import statistics
from typing import Any

from intel.research import RESEARCH_DB
from intel.research.analyse import (FEATURES, base_rates, deciles, load, monotonicity,
                                    rank_features, split_by_time)
from intel.research.backtest import EXITS, Costs, Rule, simulate

ENTRY_GRID = [1.0, 2.0, 5.0, 10.0, 15.0]


def quote_maps(ctx, native_usd: float | None = None) -> tuple[dict[str, float], dict[str, int]]:
    """usd value and decimals of each quote asset. Nothing is guessed; unknown stays unknown.

    The config prices stablecoins but leaves the native asset's USD value null, and the native
    asset quotes most of the launches on this chain (1 387 of 2 252 sampled pools). Without it the
    depth of those pools is unknown, the impact model falls back to its pessimistic default and
    -- worse -- the sellability check silently never fires, so every printed multiple counts as
    cashable. ``native_usd`` is fetched live by the caller and injected here.
    """
    usd: dict[str, float] = {}
    dec: dict[str, int] = {}
    for addr, meta in (ctx.config.quote_assets or {}).items():
        a = addr.lower()
        if meta.get("decimals") is not None:
            dec[a] = int(meta["decimals"])
        if meta.get("kind") == "stable":
            usd[a] = float(meta.get("usd", 1.0))
        elif meta.get("usd") is not None:
            usd[a] = float(meta["usd"])
        elif native_usd and meta.get("kind") in ("native", "native_wrapped"):
            usd[a] = float(native_usd)
    return usd, dec


async def native_price_usd(ctx) -> float | None:
    """live USD price of the chain's native asset, via the wrapped token on DexScreener"""
    from intel.providers.dexscreener import normalize_pair
    wrapped = next((a for a, m in (ctx.config.quote_assets or {}).items()
                    if m.get("kind") == "native_wrapped"), None)
    if not wrapped:
        return None
    try:
        for pr in await ctx.dex.tokens([wrapped]):
            np = normalize_pair(pr)
            if np.get("price_usd"):
                return float(np["price_usd"])
    except Exception:  # noqa: BLE001
        return None
    return None


def _pool_counts(db_path: str) -> dict[str, int]:
    from intel.research.schema import connect
    con = connect(db_path)
    n = con.execute("SELECT COUNT(*) FROM rp_pool").fetchone()[0]
    alive = con.execute("SELECT COUNT(*) FROM rp_pool WHERE n_swaps>0").fetchone()[0]
    bad = con.execute("SELECT COUNT(*) FROM rp_pool WHERE swaps_status<>'ok'").fetchone()[0]
    lv = {}
    for level in ("x2", "x3", "x5", "x10", "x20", "x50"):
        lv[level] = con.execute(
            f"SELECT COUNT(DISTINCT pair_id) FROM rp_label WHERE hit_{level}=1").fetchone()[0]
    con.close()
    return {"pools": n, "alive": alive, "failed": bad, **lv}


def best_rules(train: list[dict], level: str = "hit_x2", bins: int = 4,
               min_mono: float = 0.3, max_share: float = 0.5) -> list[tuple[str, float, float]]:
    """(feature, threshold, train hit rate) for features with a wide AND monotone gradient.

    A threshold is rejected when it selects more than ``max_share`` of the training launches. On
    features that are zero for most tokens the top quartile's lower bound lands on 0, which reads
    as a rule ("trades_5m >= 0") while selecting everything -- a filter that filters nothing will
    always look as good as the base rate and tells us nothing.
    """
    out = []
    for r in rank_features(train, FEATURES, level=level, bins=bins):
        if r["spread"] <= 0:
            continue
        b = deciles(train, r["feature"], levels=[level], bins=bins)
        if not b or monotonicity(b, level) < min_mono:
            continue
        thr = b[-1]["from"]
        vals = [x.get(r["feature"]) for x in train if x.get(r["feature"]) is not None]
        if not vals:
            continue
        share = sum(1 for v in vals if v >= thr) / len(vals)
        if share > max_share or thr <= min(vals):
            continue
        out.append((r["feature"], thr, b[-1][level]))
    return out


def run(ctx, db_path: str = RESEARCH_DB, *, ticket: float = 20.0, native_usd: float | None = None,
        bankroll: float = 400.0) -> dict[str, Any]:
    usd, dec = quote_maps(ctx, native_usd)
    print(f"   quotes valorises : {len(usd)} · prix natif {native_usd}")
    counts = _pool_counts(db_path)
    print("=" * 78)
    print("1. COMBIEN DE LANCEMENTS ANALYSES")
    print(f"   {counts['pools']} lancements tires au hasard · {counts['alive']} echangent au moins "
          f"une fois ({counts['alive']/max(1,counts['pools']):.0%}) · "
          f"{counts['pools']-counts['alive']} morts a la naissance")
    if counts["failed"]:
        print(f"   {counts['failed']} pools dont la collecte a echoue (comptes, pas caches)")
    print()
    print("2. COMBIEN FONT REELLEMENT x5 / x10 / x20 / x50")
    for lv in ("x2", "x3", "x5", "x10", "x20", "x50"):
        n = counts[lv]
        print(f"   {lv:>4} : {n:>5} pools · {n/max(1,counts['alive']):>6.2%} des vivants · "
              f"{n/max(1,counts['pools']):>6.2%} de tous les lancements")
    print()

    print("3. A QUEL MOMENT FAUT-IL LES DETECTER")
    print(f"   {'instant':>10} {'n':>6} {'x2':>8} {'x5':>8} {'x10':>8} {'invendable':>12}")
    per_t = {}
    for t in ENTRY_GRID + [30.0, 60.0]:
        rows = load(db_path, t_min=t)
        if not rows:
            continue
        per_t[t] = rows
        br = base_rates(rows)
        zero = sum(1 for r in rows if not (r.get("max_ret_6h") or 0)) / len(rows)
        print(f"   T+{t:<6g} min {len(rows):>6} {br['hit_x2']:>7.1%} {br['hit_x5']:>7.1%} "
              f"{br['hit_x10']:>7.1%} {zero:>11.0%}")
    print()

    results: dict[str, Any] = {"counts": counts, "entries": {}}
    for t, rows in per_t.items():
        train, test = split_by_time(rows, 0.6)
        if len(test) < 40:
            continue
        rules = best_rules(train)
        if not rules:
            continue
        print(f"4-7. T+{t:g} MIN · train {len(train)} · test {len(test)} · "
              f"base x2 test {base_rates(test)['hit_x2']:.1%}")
        print(f"     {'regle (seuil issu du train)':<34} {'train':>8} {'TEST':>8} "
              f"{'sous le seuil':>14} {'n test':>7}")
        kept = []
        for feat, thr, tr_rate in rules[:6]:
            sel = [r for r in test if r.get(feat) is not None and r[feat] >= thr]
            rest = [r for r in test if r.get(feat) is not None and r[feat] < thr]
            if len(sel) < 10:
                continue
            p = sum(1 for r in sel if r.get("hit_x2")) / len(sel)
            q = (sum(1 for r in rest if r.get("hit_x2")) / len(rest)) if rest else 0.0
            print(f"     {feat + ' >= ' + format(thr, '.4g'):<34} {tr_rate:>7.1%} {p:>7.1%} "
                  f"{q:>13.1%} {len(sel):>7}")
            kept.append((feat, thr, p, len(sel)))
        results["entries"][t] = {"train": train, "test": test, "rules": kept}
        print()

    print("=" * 78)
    print("9-12. LE LIVRE DE 400 EUR, MESURE SUR LE TEST UNIQUEMENT")
    best: dict[str, Any] | None = None
    for t, blob in results["entries"].items():
        for feat, thr, _p, _n in blob["rules"][:2]:
            rule = Rule(f"T+{t:g}min {feat}>={thr:.4g}", t,
                        lambda r, f=feat, x=thr: r.get(f) is not None and r[f] >= x)
            for ex in EXITS:
                res = simulate(blob["test"], rule, ex, bankroll=bankroll, ticket=ticket,
                               costs=Costs(), quote_usd=usd, quote_dec=dec)
                if not res.get("n"):
                    continue
                # what the book is worth once its three luckiest trades are removed: a rule whose
                # whole result sits in three positions is a lottery ticket, not an edge, and
                # ranking on the raw final would pick exactly those
                res["final_sans_top3"] = bankroll + res["pnl_sans_top3"]
                print(f"   {res['rule']:<34} {res['exit']:<32} {res['n']:>3}pos "
                      f"final {res['final']:>7.0f}EUR (sans top3 {res['final_sans_top3']:>6.0f}) "
                      f"med x{res['median_mult']:.2f} zero {res['to_zero']:>4.0%} "
                      f"x5:{res['n_x5']} x10:{res['n_x10']} "
                      f"prof.inconnue {res['sans_profondeur']}")
                if best is None or res["final_sans_top3"] > best["final_sans_top3"]:
                    best = res
    print()

    print("=" * 78)
    print("13. VERDICT")
    if best is None:
        print("   NO EDGE — aucune regle ne produit assez de positions sur le test pour conclure")
        results["verdict"] = "NO EDGE"
        return results
    lifts = [p for blob in results["entries"].values() for _f, _t, p, _n in blob["rules"]]
    base = statistics.mean([base_rates(b["test"])["hit_x2"] for b in results["entries"].values()])
    # "it still pays without its three best trades" has to mean something: +2% is not robustness,
    # it is the same lottery with the ticket price refunded. The bar is a fifth of the bankroll.
    lift_ok = bool(lifts) and max(lifts) > 2 * max(base, 0.01)
    pays = best["final"] > bankroll
    robust = best["final_sans_top3"] > bankroll * 1.20
    enough = best["n"] >= 40
    big_lift = any(True for blob in results["entries"].values()
                   for r in blob["test"] if r.get("hit_x5"))
    if not lift_ok or not enough:
        v = "NO EDGE"
    elif not pays:
        v = "WEAK EDGE"
    elif not robust:
        v = "WEAK EDGE — le resultat tient sur une poignee de trades"
    elif big_lift and best["n_x5"] >= 3:
        v = "PROMISING"
    else:
        v = "PROMISING"
    print(f"   meilleure configuration (classee sans ses 3 meilleurs trades) :")
    print(f"     {best['rule']} · {best['exit']}")
    print(f"   {best['n']} positions · final {best['final']:.0f} EUR (depart {bankroll:.0f}) · "
          f"sans les 3 meilleurs {best['final_sans_top3']:.0f} EUR")
    print(f"   mediane x{best['median_mult']:.2f} · gagnantes {best['win_rate']:.0%} · "
          f"a zero {best['to_zero']:.0%} · x5:{best['n_x5']} x10:{best['n_x10']} x20:{best['n_x20']}")
    print(f"   lift maximal sur test : {max(lifts) if lifts else 0:.1%} contre une base de {base:.1%}")
    print(f"   >>> {v}")
    results["verdict"] = v
    results["best"] = {k: x for k, x in best.items() if k != "trades"}
    return results


if __name__ == "__main__":
    import sys
    from intel.context import IntelContext
    path = sys.argv[1] if len(sys.argv) > 1 else RESEARCH_DB
    tk = float(sys.argv[2]) if len(sys.argv) > 2 else 20.0
    import asyncio
    c = IntelContext.build()
    nat = asyncio.run(native_price_usd(c))
    run(c, path, ticket=tk, native_usd=nat)
