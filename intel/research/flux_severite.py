"""COMBIEN faut-il en garder ? La severite du tri, du plus laxiste au plus severe.

§3.155 : la foret nourrie au flux d ordres bat le temoin de +0,430 EUR/ticket (p ~ 0,020) en
gardant **80 %** des tickets -- cette proportion n a pas ete choisie, c est celle de la foret en
service, retenue pour comparer a effectif egal. Rien ne dit que ce soit la bonne.

L ENJEU EST ARITHMETIQUE, et il tranche entre deux projets differents :
    beaucoup de tickets  453/jour a +0,069 EUR piece  ->  50 EUR/jour, 193 jours pour le PROUVER
    peu de tickets       100/jour a +0,500 EUR piece  ->  50 EUR/jour,  27 jours pour le PROUVER
Le meme objectif, mais l un est mesurable cette saison et l autre non. Et l argent total est
n x avantage : serrer le tri divise n, donc il faut que l avantage par ticket monte PLUS vite que
le nombre de tickets ne tombe. C est exactement ce qu on mesure ici.

PROTOCOLE identique a foret_vidage_plus.py, sinon les chiffres ne sont pas comparables : marche
avant par coupes de 6 h du 16/09 au 18/09 18h, entrainement sur tout ce qui precede, jugement sur
les 6 h suivantes, cout 2,98 pt, cible vidage = net <= -50 %. Seule la proportion gardee varie.

DEUX GARDE-FOUS, parce qu un tri severe est exactement le terrain ou l on se ment :
  - chaque proportion est jugee SANS SES 3 MEILLEURS tickets aussi bien qu avec ;
  - barre du hasard sur le MAXIMUM parmi toutes les proportions essayees -- essayer sept severites
    et garder la meilleure est une procedure, et c est elle qu il faut permuter (loi du maximum).
"""
from __future__ import annotations

import datetime as dt
import os
import warnings

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier

warnings.filterwarnings("ignore")
DOSSIER = "/app/data/recherche/tout"
COUT = float(os.environ.get("COUT_MESURE", "0.0298"))
MISE = 20.0
NULLS = int(os.environ.get("NULLS", "60"))
GARDES = [0.80, 0.60, 0.40, 0.25, 0.15, 0.10, 0.05]
HEURES = 66.0                     # 16/09 00h -> 18/09 18h, la fenetre de marche avant


def net(r):
    return (1.0 + r) * (1.0 - COUT) - 1.0


def main() -> None:
    df = pd.read_pickle(os.path.join(DOSSIER, "table.pkl"))
    df = df[(df["eligible"] == 1) & df["ret_240"].notna() & df["v1_n_achats"].notna()]
    df = df.sort_values("t_dec").reset_index(drop=True)
    flux = [c for c in df.columns if c.startswith("v1_") and df[c].notna().sum() >= 100
            and pd.to_numeric(df[c], errors="coerce").nunique(dropna=True) >= 2]
    y_net = net(df["ret_240"].to_numpy(dtype=float))
    y_vid = (y_net <= -0.5).astype(int)
    t = df["t_dec"].to_numpy()
    X = df[flux].apply(pd.to_numeric, errors="coerce").astype(float)
    sigma = MISE * y_net.std(ddof=1)
    print("%d tickets · %d variables de flux · cout %.2f pt · ecart-type d un ticket %.2f EUR"
          % (len(df), len(flux), 100 * COUT, sigma))
    print()

    tz = dt.timezone(dt.timedelta(hours=2))
    DEBUT = dt.datetime(2026, 9, 16, 0, 0, tzinfo=tz)
    FIN = dt.datetime(2026, 9, 18, 18, 0, tzinfo=tz)

    def marche(yv, yn):
        """Une marche avant complete ; renvoie {garde: liste des nets retenus} + le temoin."""
        tot = {g: [] for g in GARDES}
        tem = []
        c = DEBUT
        while c < FIN:
            c0, c1 = c.timestamp(), (c + dt.timedelta(hours=6)).timestamp()
            A, J = t < c0, (t >= c0) & (t < c1)
            c += dt.timedelta(hours=6)
            if A.sum() < 150 or J.sum() < 20:
                continue
            nets = yn[J]
            tem.extend(nets.tolist())
            med = X[A].median()
            rf = RandomForestClassifier(n_estimators=300, min_samples_leaf=20, n_jobs=-1,
                                        random_state=0).fit(X[A].fillna(med).fillna(0), yv[A])
            p = rf.predict_proba(X[J].fillna(med).fillna(0))[:, 1]
            ordre = np.argsort(p, kind="stable")          # du moins dangereux au plus dangereux
            for g in GARDES:
                k = max(5, int(len(nets) * g))
                tot[g].extend(nets[ordre[:k]].tolist())
        return tot, np.array(tem)

    tot, tem = marche(y_vid, y_net)
    n_jour_tem = len(tem) * 24.0 / HEURES
    print("TEMOIN (tout prendre) : %d tickets · %+.3f EUR/ticket · %.0f tickets/jour · %+.0f EUR/jour"
          % (len(tem), MISE * tem.mean(), n_jour_tem, MISE * tem.mean() * n_jour_tem))
    print()
    print("   %-8s %6s %11s %11s %12s %11s %11s" %
          ("garde", "n", "EUR/tick", "vs temoin", "sans 3 meil.", "tickets/j", "EUR/jour"))
    res = {}
    for g in GARDES:
        v = np.array(tot[g])
        if len(v) < 20:
            continue
        s = np.sort(v)
        d = MISE * (v.mean() - tem.mean())
        res[g] = d
        nj = len(v) * 24.0 / HEURES
        print("   %-8s %6d %+10.3f %+10.3f %+11.3f %11.0f %+10.0f"
              % ("%.0f %%" % (100 * g), len(v), MISE * v.mean(), d,
                 MISE * (s[:-3].mean() - tem.mean()), nj, MISE * v.mean() * nj))
    print()
    print("   (EUR/jour = ce que la ligne rapporterait au rythme de la fenetre, mise 20 EUR)")

    # --- le niveau est-il distinguable de zero ? c est lui qui fait l argent, pas le contraste ---
    print()
    print("LE NIVEAU CONTRE ZERO -- le contraste ne se depense pas, seul le niveau est de l argent")
    print("   %-8s %6s %11s %13s %14s" % ("garde", "n", "EUR/tick", "bruit (1 sig)", "intervalle 2 sig"))
    for g in GARDES:
        v = np.array(tot[g])
        if len(v) < 20:
            continue
        e = sigma / np.sqrt(len(v))
        m = MISE * v.mean()
        print("   %-8s %6d %+10.3f %12.3f   %+.3f a %+.3f%s"
              % ("%.0f %%" % (100 * g), len(v), m, e, m - 2 * e, m + 2 * e,
                 "   <- sort du bruit" if m - 2 * e > 0 else ""))

    if NULLS:
        print()
        print("BARRE DU HASARD : %d marches avant permutees, on retient a chaque fois LA MEILLEURE"
              % NULLS)
        print("   des %d severites -- c est la procedure entiere qu on permute, choix de la coupe compris"
              % len(GARDES))
        rng = np.random.default_rng(23)
        maxs = []
        for i in range(NULLS):
            perm = rng.permutation(len(y_net))
            tp, rt = marche(y_vid[perm], y_net[perm])
            maxs.append(max(MISE * (np.array(tp[g]).mean() - rt.mean()) for g in GARDES
                            if len(tp[g]) >= 20))
            if (i + 1) % 10 == 0:
                print("   %d/%d tirages · meilleur du hasard jusqu ici %+0.3f"
                      % (i + 1, NULLS, max(maxs)), flush=True)
        vrai = max(res.values())
        meilleure = max(res, key=res.get)
        k_sup = sum(1 for m in maxs if m >= vrai)
        print("   -> meilleure severite %.0f %% a %+.3f EUR/ticket · %d tirages sur %d font aussi bien (p ~ %.3f)"
              % (100 * meilleure, vrai, k_sup, NULLS, (k_sup + 1) / (NULLS + 1)))


if __name__ == "__main__":
    main()
