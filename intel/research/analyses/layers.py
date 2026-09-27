"""The layered test: A all → B security → C + momentum → D + organic flow. Judged on future data.

Each layer is a HARD filter stacked on the previous one, and the question for each is the same:
does it raise P(x5 / x10 / x20 / x50) on launches it was never tuned on? The abandonment rule is
fixed before looking: if D does not beat B on the test half, the organic-flow idea is dropped.

Bounds are not hand-picked. B's cut-offs are quartiles of the training half; C's are the natural
ones (acceleration above 1, velocity above 0); D's are medians of the training half among the
launches that already passed C. All of them are printed.

Exit is a THESIS stop, not a price stop: at the next observation the position is sold if the
adoption that justified it has collapsed (buyer acceleration under 0.5, volume under a third,
no new buyers), whatever the price did. Otherwise it runs to the horizon, recovering the ticket
at x5 and letting the rest ride -- the book is built so that one x50 pays for many losers.
"""
from __future__ import annotations

import statistics
from typing import Any, Callable

from intel.research import RESEARCH_DB
from intel.research.analyse import load, split_by_time

FEE = 0.02
TICKET = 15.0
BANKROLL = 400.0
NEXT = {5.0: 10.0, 10.0: 15.0, 15.0: 30.0, 30.0: 60.0}
LEVELS = ("hit_x5", "hit_x10", "hit_x20", "hit_x50")


def _q(rows: list[dict], f: str, q: float) -> float | None:
    v = sorted(r[f] for r in rows if r.get(f) is not None)
    return v[int(len(v) * q)] if v else None


def security_bounds(train: list[dict]) -> dict[str, float]:
    """Quartiles over launches that can actually be vetted -- at least a handful of holders.

    Taken over every row, the early snapshots (one or two holders, the deployer owning all of
    it) pushed the quartiles to 1.00 and the "filter" kept everything; the first dry run printed
    exactly that. A bound that does not discriminate is reported as such, not applied silently.
    """
    vet = [r for r in train if (r.get("holders") or 0) >= 5]
    b = {"deployer_pct_max": _q(vet, "deployer_pct", 0.75),
         "top10_max": _q(vet, "top10", 0.75),
         "holders_min": _q(vet, "holders", 0.25)}
    b["degenerate"] = (b["deployer_pct_max"] is None or b["deployer_pct_max"] >= 0.999
                       or b["top10_max"] is None or b["top10_max"] >= 0.999
                       or (b["holders_min"] or 0) < 5)
    b["deployer_pct_max"] = b["deployer_pct_max"] if b["deployer_pct_max"] is not None else 1.0
    b["top10_max"] = b["top10_max"] if b["top10_max"] is not None else 1.0
    b["holders_min"] = max(5.0, b["holders_min"] or 0.0)
    return b


def passes_b(r: dict, sb: dict[str, float]) -> bool:
    if r.get("holders") is None:
        return False                                   # no transfers: cannot be vetted → 0 EUR
    if (r.get("deployer_pct") or 0.0) > sb["deployer_pct_max"]:
        return False
    if (r.get("top10") or 1.0) > sb["top10_max"]:
        return False
    if (r.get("holders") or 0) < sb["holders_min"]:
        return False
    if r.get("deployer_sold"):
        return False
    if not (r.get("uniq_sellers") or 0):
        return False                                   # nobody has ever managed to sell
    return True


def passes_c(r: dict) -> bool:
    return ((r.get("buyer_accel") or 0) > 1.0 and (r.get("holder_velocity_5m") or 0) > 0
            and (r.get("vol_accel") or 0) > 1.0)


def organic_bounds(train_c: list[dict]) -> dict[str, float]:
    return {"holders_vs_price_min": _q(train_c, "holders_vs_price", 0.5) or 0.0,
            "organic_min": _q(train_c, "organic_buy_ratio", 0.5) or 0.0,
            "repeat_max": _q(train_c, "repeat_amount_share", 0.5) or 1.0}


def passes_d(r: dict, ob: dict[str, float]) -> bool:
    return ((r.get("holders_vs_price") or 0) >= ob["holders_vs_price_min"]
            and (r.get("organic_buy_ratio") or 0) >= ob["organic_min"]
            and (r.get("repeat_amount_share") or 1.0) <= ob["repeat_max"])


MAX_PART = 0.20     # a ticket may be at most this share of the volume traded at the exit


def _eur(r: dict, raw: float | None, quote_usd: dict, quote_dec: dict) -> float | None:
    from intel.research.backtest import _quote_eur
    qe = _quote_eur(r, quote_usd, quote_dec)
    return (raw * qe) if (qe and raw is not None) else None


def thesis_outcome(r: dict, nxt: dict | None, quote_usd: dict, quote_dec: dict,
                   ticket: float = TICKET) -> float:
    """net multiple of one position under the thesis stop + stake-back-at-x5 exit.

    A multiple that could not be sold is not a multiple. The horizon exit and the x5 stake-back
    both check the quote volume actually traded around the exit against the ticket, exactly as
    the main backtest does; without it a single unsellable print carried a whole group (EV
    +1 022 % on 12 positions, 390 EUR once the top three were removed) in the second dry run.
    """
    # The thesis can only be judged where it can be SEEN. A None here means the transfers for this
    # token are not in the dataset, not that adoption collapsed; reading it as collapse sold nearly
    # every position at the first check and printed -4.0 % on every group of the first dry run.
    if nxt is not None and all(nxt.get(k) is not None for k in ("buyer_accel", "vol_accel", "new_buyers_5m")):
        dead = (nxt["buyer_accel"] < 0.5 or nxt["vol_accel"] < 0.3 or not nxt["new_buyers_5m"])
        if dead and r.get("price") and nxt.get("price"):
            return (nxt["price"] / r["price"]) * (1 - FEE) * 0.98   # sold at the check, behind the print
    end = r.get("ret_6h") or 0.0
    exit_eur = _eur(r, r.get("exit_vol_6h"), quote_usd, quote_dec)
    if exit_eur is not None and ticket > MAX_PART * exit_eur:
        end = 0.0                                                     # nobody to sell into
    if r.get("hit_x5"):
        sell5 = _eur(r, r.get("sellable_x5"), quote_usd, quote_dec)
        if sell5 is None or ticket * 0.2 <= MAX_PART * sell5:
            return (0.2 * 5.0 + 0.8 * end) * (1 - FEE)
    return end * (1 - FEE)


def book(rows: list[dict], hold_h: float = 6.0, ticket: float = TICKET,
         mult_key: str = "thesis_mult") -> dict[str, Any]:
    picks = sorted(rows, key=lambda r: (r.get("created_block") or 0, r.get("block") or 0))
    cash, open_pos, pnl, seen = BANKROLL, [], [], set()
    for r in picks:
        now = int(r.get("block") or 0)
        open_pos, back = [(b, v) for b, v in open_pos if b > now], sum(v for b, v in open_pos if b <= now)
        cash += back
        if r["pair_id"] in seen or cash < ticket:
            continue
        seen.add(r["pair_id"])
        cash -= ticket
        val = ticket * r[mult_key]
        open_pos.append((now + int(hold_h * 60 * 600), val))
        pnl.append(val - ticket)
    cash += sum(v for _b, v in open_pos)
    if not pnl:
        return {"n": 0}
    top = sorted(pnl, reverse=True)
    return {"n": len(pnl), "final": cash, "sans_top3": BANKROLL + sum(pnl) - sum(top[:3]),
            "zero": sum(1 for x in pnl if x <= -0.9 * ticket) / len(pnl)}


def placebo(parent: list[dict], n: int, draws: int = 40) -> dict[str, Any] | None:
    """what ``n`` positions drawn AT RANDOM from the parent layer would have given.

    A layer that keeps fewer launches always looks better on a lucky draw; the only fair yardstick
    is a random subset of the same size from the layer it was cut from. Medians across the draws,
    so a single lucky draw cannot carry the comparison.
    """
    import random
    if not parent or n < 10 or n >= len(parent):
        return None
    evs, x10s, x20s, finals = [], [], [], []
    for d in range(draws):
        sub = random.Random(d).sample(parent, n)
        m = metrics(sub)
        evs.append(m["ev"])
        x10s.append(m["hit_x10"])
        x20s.append(m["hit_x20"])
        finals.append(book(sub).get("final", 0.0))
    return {"ev": statistics.median(evs), "hit_x10": statistics.median(x10s),
            "hit_x20": statistics.median(x20s), "final": statistics.median(finals),
            "final_p90": sorted(finals)[int(draws * 0.9)]}


def metrics(rows: list[dict]) -> dict[str, Any]:
    if not rows:
        return {"n": 0}
    m = [r["thesis_mult"] for r in rows]
    # EV is a 5 %-trimmed mean: one print on a pool whose quote has no price (so no sellability
    # check can run) showed +266 % on a group whose book ended at 9 EUR. The book is the judge;
    # the EV column must not contradict it because of a single unverifiable multiple.
    s = sorted(m)
    k = max(1, int(len(s) * 0.05)) if len(s) >= 10 else 0   # small groups still lose one per end
    core = s[k: len(s) - k] or s
    return {"n": len(rows), **{lv: sum(1 for r in rows if r.get(lv)) / len(rows) for lv in LEVELS},
            "med": statistics.median(m) - 1, "ev": statistics.mean(core) - 1,
            "ev_raw": statistics.mean(m) - 1}


def run(db_path: str = RESEARCH_DB, entries: tuple[float, ...] = (5.0, 10.0, 15.0, 30.0),
        quote_usd: dict | None = None, quote_dec: dict | None = None) -> None:
    quote_usd, quote_dec = quote_usd or {}, quote_dec or {}
    if not quote_usd:
        print("  ATTENTION : aucun prix de quote fourni — la vendabilite ne sera PAS verifiee")
    for T in entries:
        rows = load(db_path, t_min=T)
        nxt_rows = {r["pair_id"]: r for r in load(db_path, t_min=NEXT[T])}
        with_tr = [r for r in rows if r.get("holders") is not None]
        if len(with_tr) < 200:
            print(f"T+{T:g} min : {len(with_tr)} lancements avec transferts — trop peu, on attend la collecte")
            continue
        # Every layer is judged on the SAME population: launches whose transfers exist. Splitting
        # all rows and filtering afterwards starved B/C/D of test rows whenever the transfer pass
        # was incomplete (it fills oldest cohorts first), which the first dry run showed as "TEST 0".
        rows = with_tr
        for r in rows:
            r["thesis_mult"] = thesis_outcome(r, nxt_rows.get(r["pair_id"]), quote_usd, quote_dec)
        train, test = split_by_time(rows, 0.6)
        sb = security_bounds(train)
        if sb["degenerate"]:
            print(f"  ATTENTION : bornes B non discriminantes sur ce train — l'etage B ne filtre presque rien")
        train_c = [r for r in train if passes_b(r, sb) and passes_c(r)]
        ob = organic_bounds(train_c) if len(train_c) >= 30 else None
        groups: list[tuple[str, Callable[[dict], bool]]] = [
            ("A · tous (avec transferts)", lambda r: True),
            ("B · security", lambda r: passes_b(r, sb)),
            ("C · B + momentum", lambda r: passes_b(r, sb) and passes_c(r)),
        ]
        if ob:
            groups.append(("D · C + organic flow", lambda r: passes_b(r, sb) and passes_c(r) and passes_d(r, ob)))
        print("=" * 96)
        print(f"ENTREE T+{T:g} MIN · sortie = thesis stop a T+{NEXT[T]:g} puis mise recuperee a x5 · "
              f"train {len(train)} · test {len(test)} · ticket {TICKET:.0f} EUR")
        print(f"  bornes B (quartiles du train) : deployer <= {sb['deployer_pct_max']:.2f} · top10 <= {sb['top10_max']:.2f} · "
              f"holders >= {sb['holders_min']:.0f} · deployer n'a pas vendu · au moins un vendeur")
        if ob:
            print(f"  bornes D (medianes du train parmi C) : holders/prix >= {ob['holders_vs_price_min']:.3g} · "
                  f"organic >= {ob['organic_min']:.2f} · montants repetes <= {ob['repeat_max']:.2f}")
        print(f"  {'groupe':<24} {'':>5} {'n':>6} {'P(x5)':>7} {'P(x10)':>7} {'P(x20)':>7} {'P(x50)':>7} "
              f"{'med':>8} {'EV/pos':>8} {'400EUR->':>9} {'sans top3':>10} {'zero':>6}")
        test_res: dict[str, dict[str, Any]] = {}
        parent_test: list[dict] | None = None
        for name, pred in groups:
            for lab, sub in (("train", train), ("TEST", test)):
                sel = [r for r in sub if pred(r)]
                m = metrics(sel)
                if not m["n"]:
                    print(f"  {name:<24} {lab:>5}      0")
                    continue
                bk = book(sel)
                print(f"  {name:<24} {lab:>5} {m['n']:>6} {m['hit_x5']:>6.1%} {m['hit_x10']:>6.1%} "
                      f"{m['hit_x20']:>6.1%} {m['hit_x50']:>6.1%} {m['med']:>+7.1%} {m['ev']:>+7.1%} "
                      f"{bk.get('final', 0):>8.0f} {bk.get('sans_top3', 0):>9.0f} {bk.get('zero', 0):>5.0%}")
                if lab == "TEST":
                    test_res[name[0]] = {**m, **{f"book_{k}": v for k, v in bk.items()}}
                    if parent_test is not None:
                        pl = placebo(parent_test, m["n"])
                        if pl:
                            print(f"  {'   placebo (meme n, tire de l etage precedent)':<30} "
                                  f"{'':>6} {'':>7} {pl['hit_x10']:>6.1%} {pl['hit_x20']:>6.1%} {'':>7} "
                                  f"{'':>8} {pl['ev']:>+7.1%} {pl['final']:>8.0f}  (p90 {pl['final_p90']:.0f})")
                            test_res[name[0]]["placebo"] = pl
                    parent_test = sel
        # the abandonment rule, written before the numbers were seen: D must beat B on the test
        # half in P(x10), P(x20) and expectancy, AND beat a random draw of its own size from C.
        b, d = test_res.get("B"), test_res.get("D")
        if b and d and d["n"] >= 20:
            beats_b = d["hit_x10"] > b["hit_x10"] and d["hit_x20"] >= b["hit_x20"] and d["ev"] > b["ev"]
            pl = d.get("placebo")
            beats_pl = (pl is None) or (d["ev"] > pl["ev"] and d["book_final"] > pl["final_p90"])
            verdict = ("ORGANIC FLOW RETENU" if beats_b and beats_pl else
                       "ABANDON — D ne bat pas B" if not beats_b else
                       "ABANDON — D ne bat pas le hasard de meme taille")
            print(f"  >>> {verdict}   [D vs B : P(x10) {d['hit_x10']:.1%} vs {b['hit_x10']:.1%} · "
                  f"P(x20) {d['hit_x20']:.1%} vs {b['hit_x20']:.1%} · EV {d['ev']:+.1%} vs {b['ev']:+.1%}]")
        elif d is not None:
            print(f"  >>> D : {d['n']} positions en test — trop peu pour un verdict")
        # ticket size on the deepest layer that has enough test rows: sellability depends on the
        # ticket, so the outcome is recomputed per size rather than scaled
        deepest = next(((nm, pr) for nm, pr in reversed(groups)
                        if sum(1 for r in test if pr(r)) >= 20), None)
        if deepest:
            nm, pr = deepest
            sel = [r for r in test if pr(r)]
            cells = []
            for tk in (5.0, 10.0, 15.0, 20.0):
                for r in sel:
                    r["_tm"] = thesis_outcome(r, nxt_rows.get(r["pair_id"]), quote_usd, quote_dec, ticket=tk)
                bk = book(sel, ticket=tk, mult_key="_tm")
                cells.append(f"{tk:.0f}EUR -> {bk.get('final', 0):.0f} (sans top3 {bk.get('sans_top3', 0):.0f})")
            print(f"  taille du ticket sur {nm.strip()} (test, {len(sel)} pos) : " + " · ".join(cells))
        print()


if __name__ == "__main__":
    run()
