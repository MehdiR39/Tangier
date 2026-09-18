"""Les bons et les mauvais trades arrivent-ils par SERIES ? (question de l operateur, 15/09)

« Je constate plusieurs bons coups qui se suivent et plusieurs mauvais qui se suivent, il y a pas une
cause ? » Si oui, c est un regime, et une regle « ne trader qu apres de bons resultats » en vivrait.

PROTOCOLE FIGE AVANT LE CALCUL
  S1 carnet reel     227 tickets par ordre d entree : test des series (Wald-Wolfowitz) sur gagne/perdu,
                     et P(gagne | les k derniers tickets TERMINES avant l entree etaient gagnants).
  S2 population      tous les jetons, entree 60 s, sortie 240 s, prix corriges, cout reel, par ordre de
                     decision. Pour chaque decision : moyenne des N derniers resultats CONNUS a cet instant
                     (sortie terminee), N = 5, 10, 20. Relation avec le resultat suivant, et test du hasard par
                     melange de l ordre (global, et par jour pour separer « intra-jour » de « jour bon/mauvais »).
  S3 strategie       ne trader que si la moyenne des N derniers resultats connus depasse un seuil choisi sur
                     RECHERCHE (quantiles 50/70/90), juge sur TRI puis TEST FINAL (niveau >= +1,1 %, sb > 0).
"""
from __future__ import annotations

import os
import sqlite3
import sys
from bisect import bisect_right

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import grand_balayage as gb  # noqa: E402

RACINE = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))


def series_ww(x):
    """Test de Wald-Wolfowitz : z < 0 = moins de series que le hasard = resultats groupes."""
    x = np.asarray(x, bool)
    n1, n2 = x.sum(), (~x).sum()
    runs = 1 + np.sum(x[1:] != x[:-1])
    mu = 2 * n1 * n2 / (n1 + n2) + 1
    var = 2 * n1 * n2 * (2 * n1 * n2 - n1 - n2) / ((n1 + n2) ** 2 * (n1 + n2 - 1))
    return runs, mu, (runs - mu) / np.sqrt(var)


def main():
    rng = np.random.default_rng(11)
    # ---------------- S1 : carnet reel ----------------
    c = sqlite3.connect("file:%s?mode=ro" % os.path.join(RACINE, "data", "recherche", "archive_solana.sqlite"), uri=True)
    r = pd.read_sql("SELECT ts_entree, ts_sortie, gain_eur, mise_eur, methode FROM tg_lignes WHERE mode='live'"
                    " AND gain_eur IS NOT NULL ORDER BY ts_entree", c)
    r["gagne"] = r.gain_eur > 0
    runs, mu, z = series_ww(r.gagne)
    print("S1 CARNET REEL (%d tickets) : %d series observees contre %.1f attendues au hasard · z = %+.2f %s"
          % (len(r), runs, mu, z, "(resultats GROUPES)" if z < -1.96 else "(compatible avec le hasard)"))
    sortie = r.ts_sortie.to_numpy()
    ordre_sortie = np.argsort(sortie)
    for k in (1, 2, 3):
        cond, tous = [], []
        for i, te in enumerate(r.ts_entree):
            finis = ordre_sortie[:bisect_right(sortie[ordre_sortie], te)]
            if len(finis) < k:
                continue
            derniers = r.gagne.to_numpy()[finis[-k:]]
            tous.append(r.gagne.iloc[i])
            if derniers.all():
                cond.append(r.gagne.iloc[i])
        print("   P(gagne) = %.0f %% · P(gagne | les %d derniers termines gagnants) = %.0f %% (n=%d)"
              % (100 * np.mean(tous), k, 100 * np.mean(cond) if cond else 0, len(cond)))

    # ---------------- S2 : population ----------------
    df = gb.tranches(pd.read_pickle(os.path.join(gb.D, "table.pkl")))
    d = df[(df.A == 60)].dropna(subset=["net_240"]).copy()
    d["t_dec"] = d.naissance + 60
    d["t_fin"] = d.naissance + 60 + 2 + 240
    d = d.sort_values("t_dec").reset_index(drop=True)
    y = np.minimum(d.net_240.to_numpy(), gb.PLAFOND)
    fin = d.t_fin.to_numpy()
    o = np.argsort(fin)
    fin_tri, y_tri = fin[o], y[o]
    for N in (5, 10, 20):
        passe = np.full(len(d), np.nan)
        for i, t in enumerate(d.t_dec.to_numpy()):
            k = bisect_right(fin_tri, t)
            if k >= N:
                passe[i] = y_tri[k - N:k].mean()
        d["passe_%d" % N] = passe
    print("\nS2 POPULATION (%d decisions, entree 60 s, sortie 240 s, cout reel)" % len(d))
    for N in (5, 10, 20):
        m = ~np.isnan(d["passe_%d" % N].to_numpy())
        x, yy = d["passe_%d" % N].to_numpy()[m], y[m]
        corr = np.corrcoef(x, yy)[0, 1]
        # hasard 1 : ordre completement melange ; hasard 2 : melange A L INTERIEUR de chaque jour
        jours = pd.to_datetime(d.t_dec[m], unit="s").dt.date.to_numpy()
        nul_g, nul_j = [], []
        for _ in range(500):
            nul_g.append(np.corrcoef(x, rng.permutation(yy))[0, 1])
            yj = yy.copy()
            for j in np.unique(jours):
                idx = np.where(jours == j)[0]
                yj[idx] = rng.permutation(yj[idx])
            nul_j.append(np.corrcoef(x, yj)[0, 1])
        q = pd.qcut(x, 5, labels=False, duplicates="drop")
        par_q = " · ".join("Q%d %+.3f" % (k + 1, yy[q == k].mean()) for k in range(int(q.max()) + 1))
        print("   N=%2d : correlation passe/suivant %+.3f · hasard global p=%.3f · hasard intra-jour p=%.3f · resultat suivant par quintile du passe : %s"
              % (N, corr, np.mean(np.abs(nul_g) >= abs(corr)), np.mean(np.abs(nul_j) >= abs(corr)), par_q))

    # ---------------- S3 : strategie ----------------
    print("\nS3 STRATEGIE « ne trader qu apres de bons resultats »")
    for N in (5, 10, 20):
        col = "passe_%d" % N
        R, T, F = (d.tranche == "R").to_numpy(), (d.tranche == "T").to_numpy(), (d.tranche == "F").to_numpy()
        ok = ~np.isnan(d[col].to_numpy())
        best = None
        for qq in (0.5, 0.7, 0.9):
            seuil = np.nanquantile(d[col].to_numpy()[R & ok], qq)
            sR = gb.stats(y[R & ok & (d[col].to_numpy() > seuil)])
            if sR and (best is None or sR["moy"] > best[1]["moy"]):
                best = (seuil, sR, qq)
        seuil, sR, qq = best
        choix = ok & (d[col].to_numpy() > seuil)
        sT, sF = gb.stats(y[T & choix]), gb.stats(y[F & choix])
        tout = [gb.stats(y[m_ & ok]) for m_ in (R, T, F)]
        go = bool(sT and sF and sT["moy"] >= gb.OBJ and sF["moy"] >= gb.OBJ and sF["sb1"] > 0)
        f = lambda s: ("%+.3f (n=%d)" % (s["moy"], s["n"])) if s else "-"
        print("   N=%2d, passe > p%d : RECHERCHE %s [tout %s] · TRI %s [tout %s] · TEST %s [tout %s] %s"
              % (N, 100 * qq, f(sR), f(tout[0]), f(sT), f(tout[1]), f(sF), f(tout[2]), "GO" if go else "non"))


if __name__ == "__main__":
    main()
