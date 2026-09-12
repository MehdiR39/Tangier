#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Le plus haut historique : faut-il l acheter ou le vendre ?

Demande de l operateur le 11/09, formulee de facon ambigue -- « n importe quelle crypto achete, si
elle tape un nouveau plus haut tu la vends ». Deux lectures opposees, on teste les deux :

  A. VENDRE LE PLUS HAUT   detenir tout, sortir la ligne qui touche un nouveau sommet historique,
                           y revenir quand elle a rechute d un certain pourcentage.
  B. ACHETER LE PLUS HAUT  entrer quand une ligne franchit son sommet historique, tenir N jours.

La reference est l equipondere achete-et-garde sur le meme univers et la meme periode : une
strategie ne vaut que ce qu elle ajoute a ne rien faire.

DISCIPLINE, la meme que partout dans ce projet :
  - deux periodes INDEPENDANTES, 2017-2021 et 2022-2026, jamais melangees ;
  - une periode de chauffe avant tout signal, sinon les premiers jours donnent des « plus hauts »
    qui n en sont pas -- le maximum d une semaine de donnees est atteint une fois sur sept ;
  - frais de 15 pb par transaction, aller comme retour ;
  - la moyenne s accompagne du nombre d operations : une strategie qui ne se declenche jamais ne
    prouve rien.

Aucune position, aucun ordre : lecture de fichiers deja sur le disque.
"""
import os

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data_raw")
FRAIS = 0.0015
CHAUFFE = 180          # jours avant qu un « plus haut » veuille dire quelque chose


def charger(f, debut, fin):
    d = pd.read_csv(os.path.join(RAW, f), index_col=0, parse_dates=True)
    d = d.loc[(d.index >= debut) & (d.index <= fin)]
    return d.dropna(axis=1, how="all")


def metriques(eq):
    eq = eq.dropna()
    if len(eq) < 30:
        return dict(total=np.nan, cagr=np.nan, sharpe=np.nan, maxdd=np.nan)
    r = eq.pct_change().dropna()
    ans = (eq.index[-1] - eq.index[0]).days / 365.25
    tot = eq.iloc[-1] / eq.iloc[0]
    return dict(total=tot, cagr=tot ** (1 / ans) - 1 if ans > 0 and tot > 0 else -1.0,
                sharpe=r.mean() / r.std() * np.sqrt(365) if r.std() > 0 else np.nan,
                maxdd=(eq / eq.cummax() - 1).min())


def simuler(px, mode, rachat=0.30, tenue=30, sommets=None):
    """Une poche par actif, equiponderee au depart. Rend (courbe de capital, nombre d operations)."""
    cols = list(px.columns)
    n = len(cols)
    poche = pd.Series(1.0 / n, index=cols)      # valeur de chaque poche
    dedans = pd.Series(mode == "A", index=cols)  # A part investi, B part en liquide
    # Le VRAI sommet historique, quand on le connait. Sans amorcage, le « plus haut » n est que le
    # plus haut DE LA FENETRE : sur 2022-2026 la plupart des pieces sont restees sous leur sommet
    # de 2021 toute la periode, donc les declenchements mesures n etaient pas des sommets
    # historiques du tout. On amorce avec le maximum de la periode precedente quand il existe.
    ath = px.iloc[:CHAUFFE].max()
    if sommets is not None:
        for c in ath.index:
            if c in sommets.index and not np.isnan(sommets[c]):
                ath[c] = max(ath[c], float(sommets[c]))
    depuis = pd.Series(0, index=cols)
    valeurs, ops = [], 0
    for i in range(CHAUFFE, len(px)):
        jour = px.index[i]
        prix = px.iloc[i]
        veille = px.iloc[i - 1]
        for c in cols:
            if np.isnan(prix[c]) or np.isnan(veille[c]) or veille[c] <= 0:
                continue
            if dedans[c]:
                poche[c] *= prix[c] / veille[c]
            neuf = prix[c] > ath[c]
            if mode == "A":
                if dedans[c] and neuf:
                    dedans[c] = False; poche[c] *= (1 - FRAIS); ops += 1
                elif not dedans[c] and prix[c] < ath[c] * (1 - rachat):
                    dedans[c] = True; poche[c] *= (1 - FRAIS); ops += 1
            else:
                if not dedans[c] and neuf:
                    dedans[c] = True; depuis[c] = 0; poche[c] *= (1 - FRAIS); ops += 1
                elif dedans[c]:
                    depuis[c] += 1
                    if depuis[c] >= tenue:
                        dedans[c] = False; poche[c] *= (1 - FRAIS); ops += 1
            if neuf:
                ath[c] = prix[c]
        valeurs.append((jour, poche.sum()))
    eq = pd.Series([v for _d, v in valeurs], index=[d for d, _v in valeurs])
    return eq, ops


def garder(px):
    """Achete-et-garde equipondere, meme depart que les strategies."""
    sub = px.iloc[CHAUFFE:]
    parts = (1.0 / len(sub.columns)) / sub.iloc[0]
    return (sub * parts).sum(axis=1)


def main():
    periodes = [("2017-2021", "broad_2017_2021.csv", "2018-06-01", "2021-06-30"),
                ("2022-2026", "broad_daily_close_current.csv", "2022-01-01", "2026-07-31")]
    sommets = None
    for nom, f, a, b in periodes:
        px = charger(f, a, b)
        px = px.dropna(axis=1, thresh=int(0.9 * len(px)))
        if px.shape[1] < 8 or len(px) < CHAUFFE + 200:
            print("  %s : donnees insuffisantes (%d actifs, %d jours)" % (nom, px.shape[1], len(px)))
            continue
        print("\n  === %s · %d actifs · %s a %s ===" % (nom, px.shape[1], px.index[0].date(), px.index[-1].date()))
        print("  %-34s %8s %8s %8s %8s %7s" % ("strategie", "totalX", "CAGR", "Sharpe", "maxDD", "ops"))
        print("  " + "-" * 78)
        m = metriques(garder(px))
        print("  %-34s %8.2f %7.1f%% %8.2f %7.1f%% %7s" % (
            "acheter et garder (reference)", m["total"], 100 * m["cagr"], m["sharpe"], 100 * m["maxdd"], "-"))
        for r in (0.20, 0.30, 0.50, 1.00):
            eq, ops = simuler(px, "A", rachat=r, sommets=sommets)
            m = metriques(eq)
            print("  %-34s %8.2f %7.1f%% %8.2f %7.1f%% %7d" % (
                ("A. vendre le sommet, jamais racheter" if r >= 1 else "A. vendre le sommet, racheter -%.0f%%" % (100 * r)), m["total"], 100 * m["cagr"],
                m["sharpe"], 100 * m["maxdd"], ops))
        # le sommet atteint pendant cette periode sert d amorcage a la suivante
        brut = charger(f, a, b)
        sommets = brut.max() if sommets is None else pd.concat([sommets, brut.max()], axis=1).max(axis=1)

if __name__ == "__main__":
    main()
