"""ANALYSE DU MODELE « FORET 75s top 5 % » : ce qu il est, ce qu il prevoit, sur quoi il s appuie.

MIDO, 19/09 au soir, en regardant sa courbe sur la page : « je la trouve stable, certes elle tourne
depuis pas longtemps, mais j aime bien la courbe [...] je veux analyser son modele, interpreter sa
prevision, tout ».

CE QU IL EST. Une foret aleatoire de 300 arbres, gelee le 18/09 a 23h10, entrainee UNE SEULE FOIS
sur les 1 409 tickets qui precedaient, puis jamais reentrainee -- c est ce qui fait d elle un gel et
non une regle qui s adapte. Profondeur moyenne 10,6, 31,9 feuilles par arbre.

CE QU IL PREVOIT. Pas un prix, pas un vidage : **la probabilite que le ticket soit GAGNANT net**,
c est-a-dire `net_240 > 0` une fois le cout retire. Il sort un score entre 0 et 1, et on n achete
que si ce score depasse **0,8660** -- le 95e centile de ses scores d entrainement, donc les 5 % dont
il est le plus sur. Le seuil a 10 % (0,7996) est note a cote pour lecture, jamais pour decider.

CE QUI LE DISTINGUE DES AUTRES GELS. Il decide a **75 secondes** et non 45 : il voit donc TOUTE la
premiere minute de transactions, et entre au dernier prix lu avant 77 s. Sa cible est le rendement
de 77 s a 240 s, pas de 45 s a 240 s. Ce n est donc pas la meme population, et le cout d entree
mesure a 45 s ne s applique pas tel quel.

CE QUE CE SCRIPT AJOUTE. L importance affichee par scikit-learn est celle de l IMPURETE : elle
gonfle les variables a beaucoup de valeurs distinctes et ne dit rien de la generalisation (regle 17
du projet). On la recalcule ici PAR PERMUTATION, sur les seuls tickets NES APRES LE GEL -- ceux que
le modele n a jamais vus. On regarde aussi ou tombent ses scores, ce que valent les tickets retenus
contre les autres, et si sa regularite tient ailleurs que sur une journee.
"""
from __future__ import annotations

import os
import sys

import joblib
import numpy as np
import pandas as pd

os.environ.setdefault("AGE_DECISION", "75")
sys.path.insert(0, "/app/intel/research")

COUT = float(os.environ.get("COUT_MESURE", "0.0371"))
MISE = 20.0
TIRAGES = 10


def main() -> None:
    import foret_gel as G
    from sklearn.metrics import roc_auc_score

    m = joblib.load(os.path.join(G.DOSSIER, "modele.pkl"))
    rf, med = m["rf"], m["med"]
    noms = list(med.index)
    import json
    s = json.load(open(os.path.join(G.DOSSIER, "seuils.json"), encoding="utf-8"))
    seuil = s["seuil05"]

    df, _ = G.table()
    apres = df[df["t_dec"] >= G.GEL].reset_index(drop=True)
    apres = apres[apres["ret_240"].notna()].reset_index(drop=True)
    if len(apres) < 30:
        print("foret75_analyse: %d tickets depuis le gel, trop peu" % len(apres))
        return
    X = apres[noms].apply(pd.to_numeric, errors="coerce").astype(float).fillna(med).fillna(0)
    net = (1.0 + apres["ret_240"].to_numpy(dtype=float)) * (1.0 - COUT) - 1.0
    y = (net > 0).astype(int)
    p = rf.predict_proba(X)[:, 1]
    pris = p >= seuil

    print("FORET 75s top 5 %% -- %d tickets depuis le gel du 18/09 23h10" % len(apres))
    print("   ce qu elle prevoit : P(le ticket est GAGNANT net apres cout %.2f pt)" % (100 * COUT))
    print("   seuil d achat %.4f (95e centile de ses scores d entrainement)" % seuil)
    print()
    auc = roc_auc_score(y, p) if len(set(y)) > 1 else float("nan")
    print("   AUC hors echantillon : %.3f   (0,5 = aucune information)" % auc)
    print("   taux de gagnants du marche : %.0f %% · chez les RETENUS : %.0f %%"
          % (100 * y.mean(), 100 * y[pris].mean() if pris.sum() else 0))
    print("   elle retient %d tickets sur %d (%.0f %%)" % (pris.sum(), len(p), 100 * pris.mean()))
    print()
    print("   EN ARGENT, a %d EUR la mise :" % MISE)
    print("      tout prendre    %6d tickets · %+8.2f EUR · %+0.3f par ticket"
          % (len(net), MISE * net.sum(), MISE * net.mean()))
    if pris.sum():
        v = net[pris]
        s_ = np.sort(v)
        print("      les retenus     %6d tickets · %+8.2f EUR · %+0.3f par ticket"
              % (len(v), MISE * v.sum(), MISE * v.mean()))
        print("      sans ses 3 meilleurs : %+0.3f par ticket" % (MISE * s_[:-3].mean()))
        mi = len(v) // 2
        print("      deux moities : %+0.2f EUR / %+0.2f EUR" % (MISE * v[:mi].sum(), MISE * v[mi:].sum()))
        sig = MISE * net.std(ddof=1)
        k, n = len(v), len(net)
        bruit = sig * np.sqrt((n - k) / (n * k)) if 0 < k < n else float("inf")
        d = MISE * (v.mean() - net.mean())
        print("      contre le temoin %+0.3f · bruit %0.3f -> %+0.2f ecarts-types" % (d, bruit, d / bruit))

    print()
    print("IMPORTANCE PAR PERMUTATION, hors echantillon (%d tirages)" % TIRAGES)
    print("   perte d AUC quand on brouille la variable -- l importance par impureté de")
    print("   scikit-learn est donnee a cote, pour montrer a quel point elles different.")
    print()
    rng = np.random.default_rng(5)
    imp_arbre = dict(zip(noms, rf.feature_importances_))
    pertes = {}
    for n_ in noms:
        d = []
        for _ in range(TIRAGES):
            Z = X.copy()
            Z[n_] = rng.permutation(Z[n_].to_numpy())
            d.append(auc - roc_auc_score(y, rf.predict_proba(Z)[:, 1]))
        pertes[n_] = float(np.mean(d))
    tot = sum(max(0.0, v) for v in pertes.values()) or 1.0
    print("   %-26s %12s %8s   %10s" % ("", "perte d AUC", "part", "impurete"))
    for n_, v in sorted(pertes.items(), key=lambda kv: -kv[1]):
        print("   %-26s %+11.4f %7.0f %% %9.1f %%"
              % (n_, v, 100 * max(0.0, v) / tot, 100 * imp_arbre[n_]))

    fam = {"flux d ordres (v1_)": [n_ for n_ in noms if n_.startswith("v1_")],
           "prix (px_)": [n_ for n_ in noms if n_.startswith("px_")],
           "image (img_)": [n_ for n_ in noms if n_.startswith("img_")],
           "liquidite / risque": [n_ for n_ in noms if n_ in ("q", "risque")],
           "regime (reg_)": [n_ for n_ in noms if n_.startswith("reg_")]}
    print()
    print("   PAR FAMILLE :")
    for f, cols in fam.items():
        if not cols:
            continue
        print("      %-24s %5.0f %%  (%d variables)"
              % (f, 100 * sum(max(0.0, pertes[c]) for c in cols) / tot, len(cols)))


if __name__ == "__main__":
    main()
