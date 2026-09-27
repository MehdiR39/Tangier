"""Analyse des FRAIS du momentum broad : turnover, cost drag, sensibilité, leviers de réduction."""
import os, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd

CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data_raw", "broad_daily_close.csv")
PX = pd.read_csv(CSV, index_col=0, parse_dates=True).dropna(how="any")
R = PX.pct_change().dropna()
N = len(PX.columns); Pv = PX.values; WARM = 200
mkt = (1 + R.mean(axis=1)).cumprod(); trough = mkt.idxmin(); peak = mkt.loc[trough:].idxmax()
print(f"{N} actifs, {len(PX)} jours. Consol+Bull {trough.date()}→{peak.date()}\n")


def run(fn, step, fee_bps, s, e):
    pos = np.arange(WARM, len(PX) - 1, step); ret = pd.Series(0.0, index=PX.index)
    prev = np.zeros(N); TO = []; COST = 0.0
    for k, p in enumerate(pos):
        w = fn(p, prev); to = np.abs(w - prev).sum(); TO.append(to)
        c = fee_bps / 1e4 * to; COST += c
        nxt = pos[k + 1] if k + 1 < len(pos) else len(PX) - 1
        d = (R.iloc[p:nxt].values @ w).copy(); d[0] -= c
        ret.iloc[p:nxt] = d; prev = w
    r = ret.loc[s:e]; yrs = (e - s).days / 365.25
    val = (1 + r).prod() * 100
    sh = r.mean() / (r.std() + 1e-12) * np.sqrt(365)
    rebals_yr = 365 / step
    return dict(val=val, sharpe=sh, turn=np.mean(TO),
                ann_turn=np.mean(TO) * rebals_yr, cost_drag=COST / yrs * 100)


def w_eq(p, prev): return np.ones(N) / N


def mom(L, frac=1 / 3):
    def f(p, prev):
        tr = Pv[p] / Pv[p - L] - 1; k = max(1, int(round(N * frac)))
        w = np.zeros(N); w[np.argsort(tr)[-k:]] = 1.0 / k; return w
    return f


def mom_buffered(L, enter=1 / 3, exit_=1 / 2):
    """Hystérésis : on garde une position tant qu'elle reste dans le top-50%,
    on n'entre que dans le top-33%. Réduit fortement le churn."""
    def f(p, prev):
        tr = Pv[p] / Pv[p - L] - 1
        rank = np.argsort(np.argsort(tr)) / (N - 1)      # 0=pire, 1=meilleur
        held = prev > 0
        sel = (held & (rank >= 1 - exit_)) | (~held & (rank >= 1 - enter))
        w = np.zeros(N)
        if sel.sum() > 0:
            w[sel] = 1.0 / sel.sum()
        else:
            w[np.argsort(tr)[-max(1, int(N * enter)):]] = 1.0 / max(1, int(N * enter))
        return w
    return f


full = (PX.index[WARM], PX.index[-1])
print("=" * 78)
print("1) TURNOVER & COST DRAG réels (cycle complet, frais 15 bps/rotation)")
print("=" * 78)
print(f"{'stratégie':30s} {'val€':>7s} {'Sharpe':>7s} {'turn/reb':>9s} {'turn/an':>8s} {'coût/an':>8s}")
configs = [
    ("EqualWeight hebdo",        w_eq,             7),
    ("Momentum L90 hebdo",       mom(90),          7),
    ("Momentum L90 MENSUEL",     mom(90),          30),
    ("Momentum L90 buffered hebdo", mom_buffered(90), 7),
    ("Momentum L90 buffered MENSUEL", mom_buffered(90), 30),
]
res = {}
for name, fn, step in configs:
    m = run(fn, step, 15, *full); res[name] = m
    print(f"{name:30s} {m['val']:7.0f} {m['sharpe']:7.2f} {m['turn']:9.2f} "
          f"{m['ann_turn']:8.1f} {m['cost_drag']:7.1f}%")

print("\n" + "=" * 78)
print("2) SENSIBILITÉ AUX FRAIS — Momentum L90 buffered MENSUEL vs EqualWeight")
print("=" * 78)
print(f"{'frais (bps/rotation)':22s} " + " ".join(f"{b:>6d}" for b in [5, 10, 15, 30, 50, 100]))
for name, fn, step in [("EqualWeight hebdo", w_eq, 7), ("Mom L90 buff. mensuel", mom_buffered(90), 30)]:
    vals = [run(fn, step, b, *full)["val"] for b in [5, 10, 15, 30, 50, 100]]
    print(f"{name:22s} " + " ".join(f"{v:6.0f}" for v in vals))

print("\n" + "=" * 78)
print("3) Le momentum bat-il l'EW NET de frais réalistes (30 bps) ? — cycle complet")
print("=" * 78)
veq = run(w_eq, 7, 30, *full)
print(f"  EqualWeight hebdo (30 bps)        : {veq['val']:6.0f}€  Sh {veq['sharpe']:.2f}")
for name, fn, step in [("Momentum L90 hebdo", mom(90), 7),
                       ("Momentum L90 mensuel", mom(90), 30),
                       ("Momentum L90 buffered mensuel", mom_buffered(90), 30)]:
    m = run(fn, step, 30, *full)
    print(f"  {name:33s}: {m['val']:6.0f}€  Sh {m['sharpe']:.2f}  "
          f"{'*BAT EW*' if m['val'] > veq['val'] else 'perd'}")
