#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Le signal d'adoption a-t-il une competence de SELECTION, regime par regime ?

`onchain_cm_validate.py` compare des courbes de capital, ce qui melange deux choses : savoir
QUAND etre investi (le filtre de regime, applique identiquement a toutes les strategies) et savoir
QUOI acheter. Un signal peut battre BTC en etant simplement moins expose.

Ici on ne mesure QUE la selection : a chaque rebalancement, le rendement forward a 30 jours du
sextile haut moins celui du sextile bas, et la correlation de rang entre le signal et le rendement
forward (l'IC, mesure standard). Les deux periodes sont traitees separement -- 2020-2021 n'a jamais
servi a calibrer quoi que ce soit.

Aucune position, aucun ordre : lecture de fichiers deja sur le disque.
"""
import os
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT, RAW = os.path.join(ROOT, "data_onchain"), os.path.join(ROOT, "data_raw")
REB, LB, K = 30, 90, 6


def regimes(btc):
    ma = btc.rolling(100, min_periods=50).mean(); r90 = btc.pct_change(90)
    reg = pd.Series("consolidation", index=btc.index)
    reg[(r90 > 0.30) & (btc > ma)] = "bull"
    reg[(r90 < -0.15) | ((btc < ma) & (r90 < 0))] = "bear"
    return reg


def skill(price_csv, start, end, label):
    btc = pd.read_csv(os.path.join(OUT, "btc_daily.csv"), parse_dates=["date"]).set_index("date")["close"]
    price = pd.read_csv(os.path.join(RAW, price_csv), index_col=0, parse_dates=True)
    price = price.loc[(price.index >= start) & (price.index <= end)]
    cm = pd.read_csv(os.path.join(OUT, "coinmetrics.csv"), parse_dates=["date"])
    adr = cm[cm.metric == "AdrActCnt"].pivot_table(index="date", columns="coin", values="value")

    coins = [c for c in adr.columns if (c + "USDT") in price.columns]
    cal = price.index
    px = price[[c + "USDT" for c in coins]].copy(); px.columns = coins
    reg = regimes(btc).reindex(cal).ffill()
    sig = adr[coins].reindex(cal).ffill(limit=7).pct_change(LB)     # croissance d adresses actives
    mom = px.pct_change(LB)                                        # temoin : momentum de prix

    lignes = []
    jours = list(cal[LB + 1::REB])
    for t0 in jours:
        fwd_end = t0 + pd.Timedelta(days=REB)
        if fwd_end > cal[-1]:
            break
        t1 = cal[cal <= fwd_end][-1]
        fwd = (px.loc[t1] / px.loc[t0] - 1).dropna()
        for nom, s in (("adoption", sig), ("momentum", mom)):
            v = s.loc[t0].dropna()
            comm = [c for c in v.index if c in fwd.index and np.isfinite(v[c]) and np.isfinite(fwd[c])]
            if len(comm) < 2 * K:
                continue
            v2, f2 = v[comm], fwd[comm]
            ordre = v2.sort_values(ascending=False).index
            haut, bas = list(ordre[:K]), list(ordre[-K:])
            ic = spearmanr(v2.values, f2.values).statistic
            lignes.append(dict(date=t0, regime=reg.get(t0, "?"), signal=nom, n=len(comm),
                               haut=f2[haut].mean(), bas=f2[bas].mean(),
                               ecart=f2[haut].mean() - f2[bas].mean(), ic=ic,
                               marche=f2.mean()))
    d = pd.DataFrame(lignes)
    print(f"\n{'='*80}\n{label}   {cal.min().date()}..{cal.max().date()}   {len(coins)} actifs   "
          f"{len(jours)} rebalancements\n{'='*80}")
    for nom in ("adoption", "momentum"):
        s = d[d.signal == nom]
        if s.empty:
            continue
        print(f"\n  --- {nom} ---")
        print("  %-16s %4s %9s %9s %9s %9s %7s" % ("regime", "n", "haut", "bas", "ECART", "marche", "IC moy"))
        for r in ("bull", "consolidation", "bear", "TOUT"):
            g = s if r == "TOUT" else s[s.regime == r]
            if len(g) < 3:
                continue
            gagne = 100 * (g.ecart > 0).mean()
            print("  %-16s %4d %8.1f%% %8.1f%% %8.1f%% %8.1f%% %7.3f   ecart>0 : %.0f%%" % (
                r, len(g), 100 * g.haut.mean(), 100 * g.bas.mean(), 100 * g.ecart.mean(),
                100 * g.marche.mean(), g.ic.mean(), gagne))
    return d


a = skill("broad_2020_2026.csv", "2020-10-01", "2022-01-31", "2020-2021  (jamais utilise pour calibrer)")
b = skill("broad_daily_close_current.csv", "2022-01-01", "2026-07-31", "2022-2026  (periode de calibration)")

print("\n" + "#" * 80)
print("LE SIGNAL SEPARE-T-IL DANS LES DEUX PERIODES ?")
print("#" * 80)
for nom in ("adoption", "momentum"):
    x, y = a[a.signal == nom], b[b.signal == nom]
    print("  %-10s  2020-2021 ecart %+6.1f%% (IC %+.3f, %d periodes)   |   "
          "2022-2026 ecart %+6.1f%% (IC %+.3f, %d periodes)" % (
              nom, 100 * x.ecart.mean(), x.ic.mean(), len(x),
              100 * y.ecart.mean(), y.ic.mean(), len(y)))
