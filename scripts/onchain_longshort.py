#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Le signal d'adoption a-t-il un alpha NEUTRE AU MARCHE ?

Le long-only melange deux paris : « le marche monte » et « ces actifs-la montent plus ». En
2020-2021 le premier suffisait -- l'equipondere battait la selection. Le long-short retire le
marche et ne laisse que la selection. Si l'ecart top-bottom mesure quelque chose de reel, un
portefeuille long le sextile haut / short le sextile bas doit gagner dans LES DEUX periodes,
independamment de la direction.

Couts pris au serieux : 15 pb par jambe et par rebalancement (30 pb l'aller-retour, deux jambes),
plus un cout de portage du short. Le short crypto se paie en financement de perpetuel ; on teste
plusieurs niveaux parce qu'il varie enormement.

Aucune position, aucun ordre : lecture de fichiers deja sur le disque.
"""
import os
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT, RAW = os.path.join(ROOT, "data_onchain"), os.path.join(ROOT, "data_raw")
REB, LB, K, FEE = 30, 90, 6, 0.0015
METRIQUE = os.environ.get("METRIQUE", "AdrActCnt")


def metrics(eq):
    eq = eq.dropna()
    r = eq.pct_change().dropna(); yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    tot = eq.iloc[-1] / eq.iloc[0]
    return dict(total=tot, cagr=tot ** (1 / yrs) - 1 if yrs > 0 else np.nan,
                sharpe=r.mean() / r.std() * np.sqrt(365) if r.std() > 0 else np.nan,
                maxdd=(eq / eq.cummax() - 1).min())


def longshort(price_csv, start, end, label, portage_annuel):
    price = pd.read_csv(os.path.join(RAW, price_csv), index_col=0, parse_dates=True)
    price = price.loc[(price.index >= start) & (price.index <= end)]
    cm = pd.read_csv(os.path.join(OUT, "coinmetrics.csv"), parse_dates=["date"])
    adr = cm[cm.metric == METRIQUE].pivot_table(index="date", columns="coin", values="value")
    coins = [c for c in adr.columns if (c + "USDT") in price.columns]
    cal = price.index
    px = price[[c + "USDT" for c in coins]].copy(); px.columns = coins
    sig = adr[coins].reindex(cal).ffill(limit=7).pct_change(LB)
    bnds = list(cal[LB + 1::REB]) + [cal[-1]]

    out = {}
    for nom, p in portage_annuel.items():
        eq = pd.Series(index=cal, dtype=float); val = 1.0; eq.iloc[0] = 1.0
        for i in range(len(bnds) - 1):
            t0, t1 = bnds[i], bnds[i + 1]
            v = sig.loc[t0].dropna()
            v = v[[c for c in v.index if np.isfinite(px.loc[t0, c])]]
            if len(v) < 2 * K:
                seg = cal[(cal > t0) & (cal <= t1)]
                for d in seg:
                    eq.loc[d] = val
                continue
            o = v.sort_values(ascending=False).index
            haut, bas = list(o[:K]), list(o[-K:])
            val *= (1 - 2 * FEE)                       # deux jambes rebalancees
            qh = (0.5 / len(haut)) / px.loc[t0, haut]
            qb = (0.5 / len(bas)) / px.loc[t0, bas]
            base = val
            seg = cal[(cal > t0) & (cal <= t1)]
            for j, d in enumerate(seg, 1):
                lon = (qh * px.loc[d, haut]).sum()
                cou = (qb * px.loc[d, bas]).sum()
                brut = lon + (0.5 - (cou - 0.5)) if False else lon + (1.0 - cou) - 0.5
                eq.loc[d] = base * (brut / 0.5 * 0.5 + 0.5) if False else base * (lon + (0.5 - (cou - 0.5)))
                eq.loc[d] *= (1 - p / 365) ** j        # portage du short
            val = eq.loc[seg[-1]] if len(seg) else val
        out[nom] = metrics(eq.ffill())
    print(f"\n{'='*74}\n{label}   {cal.min().date()}..{cal.max().date()}   {len(coins)} actifs\n{'='*74}")
    print("  {:<28}{:>9}{:>9}{:>8}{:>9}".format("portage du short", "totalX", "CAGR", "Sharpe", "maxDD"))
    for nom, m in out.items():
        print("  {:<28}{:>9.2f}{:>8.1%}{:>8.2f}{:>9.1%}".format(nom, m["total"], m["cagr"], m["sharpe"], m["maxdd"]))
    return out


PORT = {"0 % (gratuit, irrealiste)": 0.0, "5 % / an": 0.05, "10 % / an": 0.10, "20 % / an": 0.20}
a = longshort("broad_2020_2026.csv", "2020-10-01", "2022-01-31", "2020-2021  HORS ECHANTILLON", PORT)
b = longshort("broad_daily_close_current.csv", "2022-01-01", "2026-07-31", "2022-2026", PORT)
print("\n" + "#" * 74)
print("GAGNE-T-IL DANS LES DEUX PERIODES, NEUTRE AU MARCHE ?")
print("#" * 74)
for k in PORT:
    print("  %-28s 2020-2021 %+7.1%%   2022-2026 %+7.1%%" % (k, a[k]["cagr"], b[k]["cagr"]) if False else
          "  %-28s 2020-2021 CAGR %+6.1f%%   2022-2026 CAGR %+6.1f%%" % (k, 100 * a[k]["cagr"], 100 * b[k]["cagr"]))
