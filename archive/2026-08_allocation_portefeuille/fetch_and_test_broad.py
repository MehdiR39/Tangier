"""Télécharge un univers large de cryptos (daily) et teste momentum cross-sectionnel vs équipondéré."""
import os, json, time, warnings, urllib.request
warnings.filterwarnings("ignore")
import numpy as np, pandas as pd

UNIV = ["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT","ADAUSDT","DOGEUSDT","AVAXUSDT",
        "LINKUSDT","DOTUSDT","MATICUSDT","LTCUSDT","TRXUSDT","ATOMUSDT","UNIUSDT","ETCUSDT",
        "XLMUSDT","NEARUSDT","ALGOUSDT","FILUSDT","VETUSDT","ICPUSDT","HBARUSDT","AAVEUSDT",
        "EOSUSDT","THETAUSDT","AXSUSDT","SANDUSDT","MANAUSDT","FTMUSDT","GRTUSDT","CHZUSDT",
        "ENJUSDT","ZECUSDT","EGLDUSDT","XTZUSDT","IOTAUSDT","KAVAUSDT","ZILUSDT","QTUMUSDT"]
HOST = "https://data-api.binance.vision"
START = int(pd.Timestamp("2022-01-01", tz="UTC").timestamp() * 1000)
END   = int(pd.Timestamp("2026-02-13", tz="UTC").timestamp() * 1000)
OUT   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data_raw", "broad_daily_close.csv")


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return json.load(urllib.request.urlopen(req, timeout=20))


def fetch_daily(symbol):
    out, cur = [], START
    while cur < END:
        url = f"{HOST}/api/v3/klines?symbol={symbol}&interval=1d&startTime={cur}&endTime={END}&limit=1000"
        try:
            data = get(url)
        except Exception:
            return None
        if not data:
            break
        out += data
        if len(data) < 1000:
            break
        cur = data[-1][0] + 86_400_000
    if not out:
        return None
    idx = pd.to_datetime([r[0] for r in out], unit="ms")
    return pd.Series([float(r[4]) for r in out], index=idx).sort_index()


print("Téléchargement…")
series = {}
for s in UNIV:
    ser = fetch_daily(s)
    if ser is not None and len(ser) > 100:
        series[s] = ser
    print(f"  {s:10s} {'OK '+str(len(ser)) if ser is not None else 'échec'}")
    time.sleep(0.05)

PX = pd.DataFrame(series)
# garde les actifs à HISTOIRE COMPLÈTE 2022-01 → 2026-02 (évite de tronquer l'univers)
first_ok = PX.apply(lambda c: c.first_valid_index())
last_ok = PX.apply(lambda c: c.last_valid_index())
keep = [c for c in PX.columns
        if first_ok[c] <= pd.Timestamp("2022-01-05") and last_ok[c] >= pd.Timestamp("2026-02-01")]
dropped = [c[:-4] for c in PX.columns if c not in keep]
print("Écartés (histoire incomplète) :", ", ".join(dropped) if dropped else "aucun")
PX = PX[keep].loc["2022-01-01":].dropna(how="any")
PX.to_csv(OUT)
print(f"\nUnivers retenu : {len(keep)} actifs, {len(PX)} jours ({PX.index[0].date()}→{PX.index[-1].date()})")
print("Actifs :", ", ".join(c[:-4] for c in keep))

R = PX.pct_change().dropna()
mkt = (1 + R.mean(axis=1)).cumprod()
trough = mkt.idxmin(); peak = mkt.loc[trough:].idxmax()
print(f"\nRégime Consol+Bull : {trough.date()}→{peak.date()}  (marché ×{mkt.loc[peak]/mkt.loc[trough]:.1f})")

# ---- Backtest : équipondéré-tout vs momentum top-tercile ----
N = len(keep); STEP = 7; WARM = 200
Pv = PX.values


def bt(weight_fn, s, e):
    pos = np.arange(WARM, len(PX) - 1, STEP)
    ret = pd.Series(0.0, index=PX.index); prev = np.zeros(N)
    for k, p in enumerate(pos):
        w = weight_fn(p)
        nxt = pos[k + 1] if k + 1 < len(pos) else len(PX) - 1
        d = (R.iloc[p:nxt].values @ w).copy(); d[0] -= 0.0015 * np.abs(w - prev).sum()
        ret.iloc[p:nxt] = d; prev = w
    r = ret.loc[s:e]
    return (1 + r).prod() * 100, r.mean() / (r.std() + 1e-12) * np.sqrt(365), \
        ((1 + r).cumprod() / (1 + r).cumprod().cummax() - 1).min()


def w_eq(p): return np.ones(N) / N


def make_mom(L, frac=1 / 3):
    def f(p):
        tr = Pv[p] / Pv[p - L] - 1
        k = max(1, int(round(N * frac)))
        top = np.argsort(tr)[-k:]
        w = np.zeros(N); w[top] = 1.0 / k
        return w
    return f


windows = {"CONSOL+BULL": (trough, peak), "CYCLE COMPLET": (PX.index[WARM], PX.index[-1])}
for lab, (s, e) in windows.items():
    veq, seq, deq = bt(w_eq, s, e)
    print(f"\n===== {lab} : 100€ → valeur finale (Sharpe, MaxDD) =====")
    print(f"  EqualWeight (tous)   : {veq:7.0f}€  Sh {seq:.2f}  DD {deq*100:.0f}%   <== référence")
    wins = 0
    for L in [20, 30, 45, 60, 90, 120, 180]:
        v, sh, dd = bt(make_mom(L), s, e)
        beat = v > veq
        wins += beat
        print(f"  Momentum top-1/3 L={L:3d}: {v:7.0f}€  Sh {sh:.2f}  DD {dd*100:.0f}%{'   *BAT EW*' if beat else ''}")
    print(f"  -> momentum bat l'équipondéré dans {wins}/7 lookbacks")

# ---- Walk-forward HONNÊTE : lookback choisi sur le passé (trailing Sharpe 180j) ----
print("\n===== WALK-FORWARD (lookback choisi hors-échantillon) — cycle complet =====")
Ls = [20, 30, 45, 60, 90, 120]
pos = np.arange(WARM, len(PX) - 1, STEP)
ret = pd.Series(0.0, index=PX.index); prev = np.zeros(N); chosen = []
for k, p in enumerate(pos):
    # choisit le L qui a le meilleur Sharpe sur les 180 derniers jours (info < p)
    best_L, best_s = Ls[0], -9
    for L in Ls:
        seg = []
        for q in range(max(WARM, p - 180), p, STEP):
            w = make_mom(L)(q); nx = min(q + STEP, p)
            seg.append(R.iloc[q:nx].values @ w)
        seg = np.concatenate(seg) if seg else np.array([0.0])
        sc = seg.mean() / (seg.std() + 1e-9)
        if sc > best_s: best_s, best_L = sc, L
    chosen.append(best_L)
    w = make_mom(best_L)(p); nxt = pos[k + 1] if k + 1 < len(pos) else len(PX) - 1
    d = (R.iloc[p:nxt].values @ w).copy(); d[0] -= 0.0015 * np.abs(w - prev).sum()
    ret.iloc[p:nxt] = d; prev = w
for lab, (s, e) in windows.items():
    r = ret.loc[s:e]; veq = bt(w_eq, s, e)[0]
    v = (1 + r).prod() * 100; sh = r.mean() / (r.std() + 1e-12) * np.sqrt(365)
    print(f"  {lab:13s}: WF-momentum {v:7.0f}€ (Sh {sh:.2f})  vs EqualWeight {veq:7.0f}€   "
          f"{'*BAT*' if v > veq else 'perd'}")
print(f"  lookback médian choisi : {int(np.median(chosen))}j")
