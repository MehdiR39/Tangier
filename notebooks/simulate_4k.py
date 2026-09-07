"""Simule 4 000 € sur les stratégies clés — suivi en euros, coûts réels (drift), drawdown."""
import os, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd

CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data_raw", "broad_daily_close.csv")
PX = pd.read_csv(CSV, index_col=0, parse_dates=True).dropna(how="any")
Rv = PX.pct_change().fillna(0.0).values          # Rv[d] = rendement du jour d (aligné sur PX.index)
Pv = PX.values; N = len(PX.columns)
mkt = (1 + PX.pct_change().fillna(0).mean(axis=1)).cumprod(); mlvl = mkt.values
trough = mkt.idxmin(); peak = mkt.loc[trough:].idxmax()
INIT = 4000.0; STEP = 7; FEE = 0.0015; L = 90; K = 8; MA = 100; WARM = max(L, MA) + 5


def simulate(target_fn, start, end):
    """Suivi en euros, poids qui dérivent, coûts sur le turnover réel au rebalancement."""
    pos = list(range(start, end, STEP))
    hold = np.zeros(N); cash = INIT; fees = 0.0; trades = 0; eq = {}
    for k, p in enumerate(pos):
        total = hold.sum() + cash
        fr = target_fn(p)                        # fractions cibles (somme <= 1)
        target = fr * total
        turn = np.abs(target - hold).sum(); cost = FEE * turn; fees += cost
        trades += int(np.sum(np.abs(target - hold) > 0.005 * total))
        hold = target; cash = total - hold.sum() - cost
        nxt = pos[k + 1] if k + 1 < len(pos) else end
        for d in range(p + 1, nxt + 1):
            hold = hold * (1 + Rv[d]); eq[PX.index[d]] = hold.sum() + cash
    return pd.Series(eq), fees, trades, len(pos)


def f_ew(p): return np.ones(N) / N
def f_mom(p):
    tr = Pv[p] / Pv[p - L] - 1; fr = np.zeros(N); fr[np.argsort(tr)[-K:]] = 1.0 / K; return fr
def f_mom_trend(p):
    on = mlvl[p] > mlvl[p - MA:p].mean()          # marché au-dessus de sa MA100 ?
    return f_mom(p) if on else np.zeros(N)         # sinon 100% cash


def report(series, fees, trades, nreb, label):
    v0 = INIT; vf = series.iloc[-1]
    dd = (series / series.cummax() - 1).min()
    peak_eur = series.max()
    yrs = (series.index[-1] - series.index[0]).days / 365.25
    cagr = (vf / v0) ** (1 / yrs) - 1
    print(f"  {label:34s} {vf:8.0f} €   (×{vf/v0:4.1f}, {cagr*100:+5.0f}%/an)   "
          f"pire chute {dd*100:4.0f}% (−{v0*(-dd):.0f}€)   frais {fees:5.0f}€   {trades/nreb:.1f} ordres/reb")


trough_pos = PX.index.get_loc(trough)
for lab, start in [("CYCLE COMPLET 2022→2026", WARM), (f"CONSOL+BULL {trough.date()}→{peak.date()}", trough_pos)]:
    end = PX.index.get_loc(peak) if "BULL" in lab else len(PX) - 1
    print("\n" + "=" * 100)
    print(f"{lab}  —  4 000 € investis   (valeur finale, ×, CAGR, drawdown, frais, ordres)")
    print("=" * 100)
    # BTC buy & hold
    btc = PX["BTCUSDT"]; s0 = PX.index[start]; s1 = PX.index[end]
    vf = INIT * btc.iloc[end] / btc.iloc[start]
    ddb = (btc.iloc[start:end] / btc.iloc[start:end].cummax() - 1).min()
    print(f"  {'Buy & Hold BTC':34s} {vf:8.0f} €   (×{vf/INIT:4.1f})                     "
          f"pire chute {ddb*100:4.0f}%   frais ~0€")
    for fn, name in [(f_ew, "Équipondéré 37 (rebal. hebdo)"),
                     (f_mom, "Top-8 Momentum (sans overlay)"),
                     (f_mom_trend, "Top-8 Momentum + filtre tendance")]:
        s, fe, tr, nr = simulate(fn, start, end)
        report(s, fe, tr, nr, name)
