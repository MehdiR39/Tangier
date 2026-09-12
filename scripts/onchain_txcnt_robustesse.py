#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""TxCnt survit-il a des reglages voisins, ou vit-il sur une lame de rasoir ?

La croissance du nombre de transactions passe le test long-short dans les deux periodes. Avant d'y
croire il faut ecarter le surajustement : douze combinaisons metrique x mode ont ete essayees, puis
trois long-shorts. Trouver un gagnant par hasard est tout a fait possible.

Un effet reel est insensible aux details : il tient pour K voisin, pour une fenetre voisine, pour un
rythme de rebalancement voisin. Un artefact disparait des qu'on bouge un cran.

On balaye donc la grille complete et on compte la proportion de reglages positifs DANS LES DEUX
periodes -- pas le meilleur, qui existe toujours.

Aucune position, aucun ordre : lecture de fichiers deja sur le disque.
"""
import os
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT, RAW = os.path.join(ROOT, "data_onchain"), os.path.join(ROOT, "data_raw")
FEE, PORTAGE = 0.0015, 0.10          # 10 %/an de portage du short : hypothese realiste


def cagr_longshort(price, cm, metrique, LB, K, REB):
    piv = cm[cm.metric == metrique].pivot_table(index="date", columns="coin", values="value")
    coins = [c for c in piv.columns if (c + "USDT") in price.columns]
    if len(coins) < 2 * K:
        return np.nan
    cal = price.index
    px = price[[c + "USDT" for c in coins]].copy(); px.columns = coins
    sig = piv[coins].reindex(cal).ffill(limit=7).pct_change(LB)
    bnds = list(cal[LB + 1::REB]) + [cal[-1]]
    if len(bnds) < 3:
        return np.nan
    val = 1.0; serie = []
    for i in range(len(bnds) - 1):
        t0, t1 = bnds[i], bnds[i + 1]
        v = sig.loc[t0].dropna()
        v = v[[c for c in v.index if np.isfinite(px.loc[t0, c])]]
        seg = cal[(cal > t0) & (cal <= t1)]
        if len(v) < 2 * K or not len(seg):
            continue
        o = v.sort_values(ascending=False).index
        haut, bas = list(o[:K]), list(o[-K:])
        val *= (1 - 2 * FEE)
        qh = (0.5 / K) / px.loc[t0, haut]; qb = (0.5 / K) / px.loc[t0, bas]
        base = val
        for j, d in enumerate(seg, 1):
            lon = (qh * px.loc[d, haut]).sum(); cou = (qb * px.loc[d, bas]).sum()
            val = base * (lon + 1.0 - cou) * (1 - PORTAGE / 365) ** j
            serie.append(val)
    if len(serie) < 30:
        return np.nan
    ans = (cal[-1] - cal[LB + 1]).days / 365.25
    return serie[-1] ** (1 / ans) - 1 if ans > 0 and serie[-1] > 0 else -1.0


price1 = pd.read_csv(os.path.join(RAW, "broad_2020_2026.csv"), index_col=0, parse_dates=True)
price1 = price1.loc["2020-10-01":"2022-01-31"]
price2 = pd.read_csv(os.path.join(RAW, "broad_daily_close_current.csv"), index_col=0, parse_dates=True)
price2 = price2.loc["2022-01-01":"2026-07-31"]
cm = pd.read_csv(os.path.join(OUT, "coinmetrics.csv"), parse_dates=["date"])

print("  CAGR long-short net, portage 10 %/an, frais 15 pb par jambe")
print("  chaque case : 2020-2021 (hors echantillon) / 2022-2026\n")
for metrique in ("TxCnt", "AdrActCnt"):
    print("  === %s ===" % metrique)
    deux, total = 0, 0
    for LB in (45, 60, 90, 120, 180):
        ligne = "   fenetre %3dj : " % LB
        for K in (4, 5, 6, 8):
            for REB in (30,):
                a = cagr_longshort(price1, cm, metrique, LB, K, REB)
                b = cagr_longshort(price2, cm, metrique, LB, K, REB)
                if np.isnan(a) or np.isnan(b):
                    ligne += "  K%d:   n/a   " % K; continue
                total += 1
                ok = a > 0 and b > 0
                deux += ok
                ligne += "  K%d:%+5.0f/%+5.0f%s" % (K, 100 * a, 100 * b, "*" if ok else " ")
        print(ligne)
    for REB in (15, 60):
        ligne = "   rebal %3dj  : " % REB
        for K in (4, 6, 8):
            a = cagr_longshort(price1, cm, metrique, 90, K, REB)
            b = cagr_longshort(price2, cm, metrique, 90, K, REB)
            if np.isnan(a) or np.isnan(b):
                ligne += "  K%d:   n/a   " % K; continue
            total += 1; ok = a > 0 and b > 0; deux += ok
            ligne += "  K%d:%+5.0f/%+5.0f%s" % (K, 100 * a, 100 * b, "*" if ok else " ")
        print(ligne)
    print("   -> positif dans LES DEUX periodes : %d / %d reglages (%.0f %%)\n" % (deux, total, 100 * deux / max(total, 1)))
