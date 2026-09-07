"""Teste l'idée de l'utilisateur : top-8 alt-momentum EN régime haussier, CASH sinon.
Mesure sur le CYCLE COMPLET (pas de cherry-picking) — le filtre décide seul quand entrer/sortir."""
import os, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd

CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data_raw", "broad_daily_close.csv")
PX = pd.read_csv(CSV, index_col=0, parse_dates=True).dropna(how="any")
Rv = PX.pct_change().fillna(0.0).values; Pv = PX.values; N = len(PX.columns)
BTC = PX["BTCUSDT"].values
mkt = (1 + PX.pct_change().fillna(0).mean(axis=1)).cumprod(); mlvl = mkt.values
trough = mkt.idxmin(); peak = mkt.loc[trough:].idxmax()
INIT = 4000.0; STEP = 7; FEE = 0.0015; L = 90; K = 8; WARM = 210


def simulate(gate, start, end):
    """top-8 momentum si gate(p)=risk-on, sinon 100% cash. Suivi €, coûts sur turnover réel."""
    pos = list(range(start, end, STEP))
    hold = np.zeros(N); cash = INIT; fees = 0.0; invested_days = 0; total_days = 0; eq = {}
    for k, p in enumerate(pos):
        total = hold.sum() + cash
        on = gate(p)
        fr = np.zeros(N)
        if on:
            tr = Pv[p] / Pv[p - L] - 1; fr[np.argsort(tr)[-K:]] = 1.0 / K
        target = fr * total
        fees += FEE * np.abs(target - hold).sum()
        hold = target; cash = total - hold.sum() - FEE * 0  # coût déjà agrégé
        cash = total - hold.sum() - FEE * np.abs(target - (hold)).sum() * 0
        # (coût imputé au cash proprement)
        nxt = pos[k + 1] if k + 1 < len(pos) else end
        for d in range(p + 1, nxt + 1):
            hold = hold * (1 + Rv[d]); eq[PX.index[d]] = hold.sum() + cash
        total_days += (nxt - p); invested_days += (nxt - p) * (1 if on else 0)
    s = pd.Series(eq)
    dd = (s / s.cummax() - 1).min()
    return s.iloc[-1], dd, fees, invested_days / max(total_days, 1)


# --- version propre du coût (recalcul simple et exact) ---
def simulate2(gate, start, end):
    pos = list(range(start, end, STEP)); hold = np.zeros(N); cash = INIT
    fees = 0.0; inv = 0; tot = 0; eq = {}
    for k, p in enumerate(pos):
        total = hold.sum() + cash; on = gate(p)
        fr = np.zeros(N)
        if on:
            tr = Pv[p] / Pv[p - L] - 1; fr[np.argsort(tr)[-K:]] = 1.0 / K
        target = fr * total
        cost = FEE * np.abs(target - hold).sum(); fees += cost
        hold = target; cash = total - hold.sum() - cost
        nxt = pos[k + 1] if k + 1 < len(pos) else end
        for d in range(p + 1, nxt + 1):
            hold = hold * (1 + Rv[d]); eq[PX.index[d]] = hold.sum() + cash
        tot += (nxt - p); inv += (nxt - p) if on else 0
    s = pd.Series(eq); dd = (s / s.cummax() - 1).min()
    return s.iloc[-1], dd, fees, inv / max(tot, 1)


def ma(arr, n, p): return arr[p] > np.mean(arr[p - n:p])
def ts_mom(arr, n, p): return arr[p] / arr[p - n] - 1 > 0

gates = {
    "TOUJOURS investi (pas de filtre)":     lambda p: True,
    "Régime = BTC > MA100":                 lambda p: ma(BTC, 100, p),
    "Régime = BTC > MA150":                 lambda p: ma(BTC, 150, p),
    "Régime = BTC > MA200":                 lambda p: ma(BTC, 200, p),
    "Régime = marché > MA150":              lambda p: ma(mlvl, 150, p),
    "Régime = BTC mom 90j > 0":             lambda p: ts_mom(BTC, 90, p),
    "Régime = BTC>MA100 ET marché>MA100":   lambda p: ma(BTC, 100, p) and ma(mlvl, 100, p),
}
end = len(PX) - 1
print("=" * 96)
print(f"4 000 € — TOP-8 ALT-MOMENTUM avec FILTRE DE RÉGIME, CYCLE COMPLET {PX.index[WARM].date()}→{PX.index[end].date()}")
print("(le filtre décide seul quand entrer/sortir — aucun cherry-picking)")
print("=" * 96)
print(f"{'filtre de régime':38s} {'val finale':>11s} {'pire chute':>11s} {'% temps investi':>16s} {'frais':>7s}")
for name, g in gates.items():
    vf, dd, fees, inv = simulate2(g, WARM, end)
    print(f"{name:38s} {vf:9.0f} €  {dd*100:9.0f}%  {inv*100:14.0f}%  {fees:6.0f}€")

# références
btc_full = INIT * BTC[end] / BTC[WARM]
print("-" * 96)
print(f"{'[réf] Buy & Hold BTC':38s} {btc_full:9.0f} €")
print(f"{'[réf] Buy & Hold alts équipondérés':38s} {INIT*(1+PX.pct_change().fillna(0).mean(axis=1)).cumprod().values[end]/(1+PX.pct_change().fillna(0).mean(axis=1)).cumprod().values[WARM]:9.0f} €")
