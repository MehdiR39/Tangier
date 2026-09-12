#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Le modele du papier TON, refait sur nos lancements Solana.

Yaremus et al. 2025 (arXiv 2509.01168) obtiennent un AUC de 0,885-0,891 pour predire un rug pull
dans les 5 premieres minutes, par gradient boosting, avec en tete la liquidite, le delai de creation
et le volume des premieres minutes. La question ici : ces variables transferent-elles a PumpSwap ?

Discipline :
  - validation croisee stratifiee, 5 plis, comme le papier (3 plis chez eux) ;
  - AUC rapporte avec son ecart-type entre plis -- sur 120 lignes il sera large, et il faut le dire ;
  - comparaison a une base naive (predire le taux de base) et a un modele a UNE variable ;
  - les importances sont calculees par permutation sur les plis de test, pas sur l entrainement ;
  - deux cibles : le rug (binaire, stable) et le multiple a T+15 min (l argent, bruyant).

Aucune position, aucun ordre : lecture d un CSV.
"""
import os
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV = os.path.join(ROOT, "data", "features_lancement.csv")

VARS = ["delta_creation_s", "lancements_createur", "liq_initiale_sol", "liq_max_90s",
        "var_90s", "pic_90s", "creux_90s", "liq_var_90s", "signes_trop_propre",
        "trades", "payers", "market_cap", "chg_m5", "trades_30s", "payers_30s"]


def main() -> None:
    from sklearn.ensemble import GradientBoostingClassifier, GradientBoostingRegressor
    from sklearn.inspection import permutation_importance
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import StratifiedKFold, cross_val_predict
    from sklearn.pipeline import make_pipeline
    from sklearn.impute import SimpleImputer
    from sklearn.preprocessing import StandardScaler

    d = pd.read_csv(CSV)
    # nettoyage des aberrations, declare et non silencieux
    n0 = len(d)
    d.loc[(d.delta_creation_s < 0) | (d.delta_creation_s > 7 * 86400), "delta_creation_s"] = np.nan
    d.loc[d.liq_initiale_sol > 100_000, "liq_initiale_sol"] = np.nan
    d.loc[d.liq_max_90s > 100_000, "liq_max_90s"] = np.nan
    for c in ("delta_creation_s", "liq_initiale_sol", "liq_max_90s", "trades", "market_cap", "trades_30s"):
        d[c] = np.log1p(d[c].clip(lower=0))
    X = d[VARS].values
    y = d["rug_tvl"].values.astype(int)
    print("  %d lancements · %d rugs (%.0f %%) · %d variables" % (len(d), y.sum(), 100 * y.mean(), len(VARS)))
    print("  valeurs manquantes par variable :", {v: int(d[v].isna().sum()) for v in VARS if d[v].isna().any()})
    print()

    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=1)

    def auc_cv(model, nom):
        aucs = []
        for tr, te in cv.split(X, y):
            model.fit(X[tr], y[tr])
            p = model.predict_proba(X[te])[:, 1]
            aucs.append(roc_auc_score(y[te], p))
        print("  %-34s AUC %.3f  ± %.3f   (plis : %s)" % (
            nom, np.mean(aucs), np.std(aucs), " ".join("%.2f" % a for a in aucs)))
        return np.mean(aucs)

    print("  CIBLE : rug (chute de reserve > 80 % dans les 15 min)")
    print("  " + "-" * 70)
    imp = SimpleImputer(strategy="median")
    gb = make_pipeline(imp, GradientBoostingClassifier(n_estimators=150, max_depth=3, learning_rate=0.05,
                                                        subsample=0.8, random_state=1))
    lr = make_pipeline(imp, StandardScaler(), LogisticRegression(max_iter=2000, C=0.5))
    a_gb = auc_cv(gb, "gradient boosting (papier)")
    a_lr = auc_cv(lr, "regression logistique")
    # une seule variable : notre filtre a trois signes, en reference
    one = make_pipeline(SimpleImputer(strategy="median"), LogisticRegression(max_iter=2000))
    Xo = d[["signes_trop_propre"]].values
    aucs = []
    for tr, te in cv.split(Xo, y):
        one.fit(Xo[tr], y[tr]); aucs.append(roc_auc_score(y[te], one.predict_proba(Xo[te])[:, 1]))
    print("  %-34s AUC %.3f  ± %.3f" % ("signes_trop_propre seul (§3.66)", np.mean(aucs), np.std(aucs)))
    print("  %-34s AUC 0.500" % ("hasard"))
    print("  %-34s AUC 0.885-0.891  (TON, 48 000 jetons)" % ("papier de reference"))
    print()

    # importances par permutation, sur les plis de test
    print("  IMPORTANCE PAR PERMUTATION (baisse d AUC quand la variable est melangee)")
    tot = np.zeros(len(VARS))
    for tr, te in cv.split(X, y):
        gb.fit(X[tr], y[tr])
        r = permutation_importance(gb, X[te], y[te], scoring="roc_auc", n_repeats=10, random_state=1)
        tot += r.importances_mean
    tot /= 5
    for v, s in sorted(zip(VARS, tot), key=lambda x: -x[1])[:10]:
        print("    %-22s %+.3f" % (v, s))
    print()

    print("  CIBLE : multiple a T+15 min (l argent)")
    print("  " + "-" * 70)
    yr = np.log(d["suite_mult"].clip(lower=0.01).values)
    from sklearn.model_selection import KFold
    gr = make_pipeline(SimpleImputer(strategy="median"),
                       GradientBoostingRegressor(n_estimators=150, max_depth=3, learning_rate=0.05, subsample=0.8, random_state=1))
    pred = cross_val_predict(gr, X, yr, cv=KFold(5, shuffle=True, random_state=1))
    from scipy.stats import spearmanr
    ic = spearmanr(pred, yr).statistic
    print("  correlation de rang prediction / realise (IC) : %+.3f" % ic)
    # le quartile predit le meilleur contre le pire
    q = pd.qcut(pred, 4, labels=False, duplicates="drop")
    for k in sorted(set(q)):
        m = d.loc[q == k, "suite_mult"]
        print("    quartile predit %d : multiple median %.2f · moyen %.2f · n=%d" % (k, m.median(), m.mean(), len(m)))


if __name__ == "__main__":
    main()
