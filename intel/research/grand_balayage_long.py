"""Grand balayage, etape 5 : les horizons LONGS (minutes a heures), sur le suivi DexScreener.

POURQUOI. Sur 4 minutes, un aller-retour a ~2 % mange tout. Sur des heures, les mouvements depassent
largement les frais. `solana_suivi_long` : 7 449 pools suivis jusqu a 24 h, un releve toutes les ~5 min.
Verifie le 15/09 : le prix DexScreener INCLUT la reserve virtuelle (SOL/USD implicite constant a
100-102 $ avec le prix corrige, de 103 a 674 $ avec le prix du coffre).

PROTOCOLE FIGE AVANT LE CALCUL (15/09)
  decision   age A (min) parmi {15, 30, 60, 120, 240, 480}, sur les releves d age <= A.
  entree     au releve SUIVANT (pas au releve de decision) ; sortie au releve le plus proche de
             entree + H, H (min) parmi {30, 60, 120, 240, 480}, tolerance 15 min.
  cout       1,7 % + 2 x 35 $ / (liquidite/2) (impact d un ordre de 30 EUR a l aller et au retour) ;
             pools de moins de 2 000 $ de liquidite exclus.
  tranches   par premiere apparition du pool : RECHERCHE 60 %, TRI 20 %, TEST FINAL 20 %.
  chaine     identique a grand_balayage.py (F1, F2, hasard melange, TRI, TEST FINAL une fois), puis
             LightGBM par duree avec seuil choisi sur TRI.
"""
from __future__ import annotations

import itertools
import os
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import grand_balayage as gb  # noqa: E402

RACINE = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
D = os.path.join(RACINE, "data", "recherche")
AGES = (15, 30, 60, 120, 240, 480)
HORIZONS = (30, 60, 120, 240, 480)
COUT_FIXE = 0.017
CONT = ["ret_naiss", "ret_15", "ret_30", "ret_60", "dd_max", "t_depuis_max", "vol", "liq", "liq_croiss",
        "liq_croiss_60", "mcap", "vol_h1", "buys_h1", "sells_h1", "ratio_achats", "chg_h1", "chg_h6",
        "n_descr", "heure", "cout"]
CAT = ["telegram", "twitter", "site"]


def construire():
    c = sqlite3.connect("file:%s?mode=ro" % os.path.join(D, "archive_solana.sqlite"), uri=True, timeout=120)
    s = pd.read_sql("SELECT pair_id, mint, ts, age_min, price_usd AS p, liquidity_usd AS liq, market_cap AS mcap,"
                    " volume_h1, buys_h1, sells_h1, chg_h1, chg_h6 FROM solana_suivi_long"
                    " WHERE price_usd > 0 ORDER BY pair_id, age_min", c)
    tg = dict(c.execute("SELECT mint, telegram FROM tg_juges").fetchall())
    soc = {m: (tw, si, nd) for m, tw, si, nd in c.execute("SELECT mint, twitter, site, n_descr FROM solana_social")}
    lignes = []
    for pair, g in s.groupby("pair_id", sort=False):
        age = g.age_min.to_numpy(float)
        p = g.p.to_numpy(float)
        liq = g.liq.to_numpy(float)
        if len(age) < 5:
            continue
        mint = g.mint.iloc[0]
        naissance = g.ts.iloc[0] - g.age_min.iloc[0] * 60
        for A in AGES:
            k = np.searchsorted(age, A, side="right")
            if k < 3 or k >= len(age):
                continue
            e = k                                            # releve suivant la decision
            if liq[e] < 2000 or age[e] - A > 15:
                continue
            cout = COUT_FIXE + 2 * 35.0 / (liq[e] / 2)
            pv = p[:k]

            def ret_fen(w):
                j = np.searchsorted(age, A - w, side="right") - 1
                return pv[-1] / p[j] - 1 if 0 <= j < k else np.nan

            j60 = np.searchsorted(age, A - 60, side="right") - 1
            f = {"pair": pair, "naissance": naissance, "A": A, "ret_naiss": pv[-1] / pv[0] - 1,
                 "ret_15": ret_fen(15), "ret_30": ret_fen(30), "ret_60": ret_fen(60),
                 "dd_max": pv[-1] / pv.max() - 1, "t_depuis_max": A - age[int(np.argmax(pv))],
                 "vol": float(np.std(np.diff(np.log(pv)))), "liq": liq[k - 1],
                 "liq_croiss": liq[k - 1] / liq[0] - 1 if liq[0] > 0 else np.nan,
                 "liq_croiss_60": liq[k - 1] / liq[j60] - 1 if (0 <= j60 < k and liq[j60] > 0) else np.nan,
                 "mcap": g.mcap.iloc[k - 1], "vol_h1": g.volume_h1.iloc[k - 1], "buys_h1": g.buys_h1.iloc[k - 1],
                 "sells_h1": g.sells_h1.iloc[k - 1], "chg_h1": g.chg_h1.iloc[k - 1], "chg_h6": g.chg_h6.iloc[k - 1],
                 "heure": int(((naissance + A * 60) % 86400) // 3600), "cout": cout, "telegram": tg.get(mint)}
            b, se = f["buys_h1"] or 0, f["sells_h1"] or 0
            f["ratio_achats"] = b / (b + se) if (b + se) > 0 else np.nan
            tw, si, nd = soc.get(mint, (None, None, None))
            f.update(twitter=tw, site=si, n_descr=nd)
            for H in HORIZONS:
                j = np.searchsorted(age, age[e] + H)
                cand = [x for x in (j - 1, j) if 0 <= x < len(age) and x > e and abs(age[x] - age[e] - H) <= 15]
                if cand:
                    x = min(cand, key=lambda x: abs(age[x] - age[e] - H))
                    f["brut_%d" % H] = p[x] / p[e] - 1
                    f["net_%d" % H] = f["brut_%d" % H] - cout
                else:
                    f["brut_%d" % H] = f["net_%d" % H] = np.nan
            lignes.append(f)
    df = pd.DataFrame(lignes)
    df.to_pickle(os.path.join(D, "balayage", "table_long.pkl"))
    return df


def main():
    gb.CONTINUES, gb.CATEGORIES, gb.HORIZONS = CONT, CAT, HORIZONS
    chemin = os.path.join(D, "balayage", "table_long.pkl")
    df = pd.read_pickle(chemin) if os.path.exists(chemin) and "--refaire" not in sys.argv else construire()
    df = gb.tranches(df)
    print("table longue : %d lignes, %d pools" % (len(df), df.pair.nunique()))
    base = df.assign(w=np.minimum(df.net_240, gb.PLAFOND))
    print(base.groupby(["A", "tranche"]).w.agg(["count", "mean"]).unstack().round(3).to_string())

    rng = np.random.default_rng(21)
    mel = df.copy()
    for H in HORIZONS:
        col = "net_%d" % H
        mel[col] = mel.groupby("A")[col].transform(lambda x: rng.permutation(x.to_numpy()))
    sh = gb.trier(mel, gb.balayer(mel, "net"), "net")
    cand = gb.balayer(df, "net")
    surv = gb.trier(df, cand, "net")
    print("\nHASARD : %d survivants au tri · VRAI : %d candidats, %d survivants au tri" % (len(sh), len(cand), len(surv)))
    surv.sort(key=lambda z: -min(z[3]["moy"], z[4]["moy"]))
    jF = (df[df.tranche == "F"].naissance.max() - df[df.tranche == "F"].naissance.min()) / 86400
    go = 0
    for A, H, noms, sR, sT, edges in surv[:20]:
        F = df[(df.A == A) & (df.tranche == "F")]
        sF = gb.stats(F["net_%d" % H].to_numpy(float)[gb.appliquer(F, noms, edges)])
        ok = bool(sF) and sF["n"] >= 30 and sF["moy"] >= gb.OBJ and sF["sb1"] > 0
        go += ok
        print("  A=%3dmin H=%3dmin %-50s R %+.3f(%d) T %+.3f(%d) F %s %s" % (
            A, H, " & ".join(noms)[:50], sR["moy"], sR["n"], sT["moy"], sT["n"],
            ("%+.3f sb %+.3f n=%d (%.0f/j)" % (sF["moy"], sF["sb1"], sF["n"], sF["n"] / max(jF, 1e-9))) if sF else "trop peu",
            "GO" if ok else ""))
    print("-> %d GO sur %d testees" % (go, min(20, len(surv))))

    # LightGBM par duree
    import lightgbm as lgb
    X = df[CONT + CAT + ["A"]].astype(float)
    R, T, F = [(df.tranche == t).to_numpy() for t in "RTF"]
    print("\nLightGBM : n acheter que les meilleurs rendements predits (seuil choisi sur TRI)")
    for H in HORIZONS:
        y = np.minimum(df["net_%d" % H].to_numpy(float), gb.PLAFOND)
        ok = ~np.isnan(y)
        if (R & ok).sum() < 500:
            continue
        reg = lgb.LGBMRegressor(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=80,
                                subsample=0.8, subsample_freq=1, colsample_bytree=0.7, reg_lambda=5.0,
                                verbose=-1).fit(X[R & ok], y[R & ok])
        pred = reg.predict(X)
        best = None
        for q in (0.5, 0.7, 0.8, 0.9, 0.95):
            seuil = np.quantile(pred[T & ok], q)
            st_ = gb.stats(y[T & ok & (pred >= seuil)])
            if st_ and st_["n"] >= 50 and (best is None or st_["moy"] > best[1]["moy"]):
                best = (seuil, st_, q)
        if not best:
            continue
        seuil, sT, q = best
        sF = gb.stats(y[F & ok & (pred >= seuil)])
        okgo = bool(sF) and sF["n"] >= 30 and sF["moy"] >= gb.OBJ and sF["sb1"] > 0
        print("  H=%3dmin top %2d%% · corr TEST %+.3f · TRI moy %+.3f n=%d · TEST %s %s" % (
            H, round(100 * (1 - q)), np.corrcoef(pred[F & ok], y[F & ok])[0, 1], sT["moy"], sT["n"],
            ("moy %+.3f sb %+.3f n=%d" % (sF["moy"], sF["sb1"], sF["n"])) if sF else "trop peu", "GO" if okgo else "non"))


if __name__ == "__main__":
    main()
