"""Combien de positions faut-il DÉTENIR (en scannant 37) pour garder l'edge ? Charge opérationnelle."""
import os, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd

CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data_raw", "broad_daily_close.csv")
PX = pd.read_csv(CSV, index_col=0, parse_dates=True).dropna(how="any")
R = PX.pct_change().dropna()
N = len(PX.columns); Pv = PX.values; WARM = 200
mkt = (1 + R.mean(axis=1)).cumprod(); trough = mkt.idxmin(); peak = mkt.loc[trough:].idxmax()
full = (PX.index[WARM], PX.index[-1])
print(f"Univers SCANNÉ : {N} actifs (données seulement). On teste combien DÉTENIR.\n")


def run(fn, step, fee_bps, s, e):
    pos = np.arange(WARM, len(PX) - 1, step); ret = pd.Series(0.0, index=PX.index)
    prev = np.zeros(N); TO = []; ORD = []; NPOS = []
    for k, p in enumerate(pos):
        w = fn(p)
        touched = int(np.sum(np.abs(w - prev) > 1e-6))   # nb de lignes à trader = ordres envoyés
        TO.append(np.abs(w - prev).sum()); ORD.append(touched); NPOS.append(int(np.sum(w > 1e-9)))
        c = fee_bps / 1e4 * np.abs(w - prev).sum()
        nxt = pos[k + 1] if k + 1 < len(pos) else len(PX) - 1
        d = (R.iloc[p:nxt].values @ w).copy(); d[0] -= c
        ret.iloc[p:nxt] = d; prev = w
    r = ret.loc[s:e]
    return dict(val=(1 + r).prod() * 100, sharpe=r.mean() / (r.std() + 1e-12) * np.sqrt(365),
                npos=np.mean(NPOS), orders=np.mean(ORD))


def topK(L, K):
    def f(p):
        tr = Pv[p] / Pv[p - L] - 1; w = np.zeros(N)
        w[np.argsort(tr)[-K:]] = 1.0 / K; return w
    return f


def w_eq(p): return np.ones(N) / N

print("=" * 82)
print("HOLD top-K (scan 37, momentum L90) — net 20 bps/rotation, cycle complet 2022-2026")
print("=" * 82)
print(f"{'stratégie':26s} {'val€':>6s} {'Sharpe':>7s} {'#lignes tenues':>15s} {'#ordres/rebal':>14s}")
veq = run(w_eq, 7, 20, *full)
print(f"{'EqualWeight (tient 37)':26s} {veq['val']:6.0f} {veq['sharpe']:7.2f} "
      f"{veq['npos']:15.0f} {veq['orders']:14.1f}   <== référence")
for step, sname in [(7, "hebdo"), (14, "bi-hebdo")]:
    print(f"  --- rebalancement {sname} ---")
    for K in [3, 5, 8, 12, 18]:
        m = run(topK(90, K), step, 20, *full)
        flag = "  *BAT EW*" if m['val'] > veq['val'] else ""
        print(f"  top-{K:<2d} momentum {sname:9s} {m['val']:6.0f} {m['sharpe']:7.2f} "
              f"{m['npos']:15.0f} {m['orders']:14.1f}{flag}")

print("\n" + "=" * 82)
print("Sur la fenêtre CONSOL+BULL uniquement")
print("=" * 82)
veqb = run(w_eq, 7, 20, trough, peak)
print(f"{'EqualWeight (37)':26s} {veqb['val']:6.0f}€  Sh {veqb['sharpe']:.2f}")
for K in [3, 5, 8, 12]:
    m = run(topK(90, K), 7, 20, trough, peak)
    print(f"  top-{K:<2d} hebdo               {m['val']:6.0f}€  Sh {m['sharpe']:.2f} "
          f"({m['orders']:.1f} ordres/sem){'  *BAT EW*' if m['val'] > veqb['val'] else ''}")
