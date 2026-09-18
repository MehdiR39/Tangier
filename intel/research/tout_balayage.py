"""LE BALAYAGE LARGE : toutes les variables, seules puis par paires, sur toutes les cibles.

MIDO, 18/09 : « tout tout tout tout -- partir d un scope tres large, reduire et affiner. » Ce
module est le scope large. Il ne choisit rien a la main : il prend `table.pkl` (une ligne par
ticket, toutes les sources jointes) et essaie, pour CHAQUE variable, CHAQUE coupe, CHAQUE horizon :

    coupes     haut 20 % · haut 50 % · bas 50 % · bas 20 % · milieu (25-75 %)
    horizons   60, 90, 120, 180, 240, 287 s
    cibles     moyenne nette · taux de gagnants · mediane · taux de CATASTROPHE (< -50 %)
               · moyenne sans les 5 % pires (l idee de Mido sur la distribution)

puis les PAIRES des meilleures variables (ET logique de deux coupes), puis un modele.

CE QUI EMPECHE LE BALAYAGE DE SE MENTIR -- et c est le seul point qui compte, parce qu un
balayage de plusieurs milliers de tests TROUVE toujours quelque chose :

 1. Trois tranches CHRONOLOGIQUES : RECHERCHE (40 %) pour mesurer, TRI (30 %) pour choisir, TEST
    (30 %) lu une fois. Une regle est choisie sur RECHERCHE + TRI et n est jugee que sur TEST.
 2. LA LOI DU MAXIMUM, sur le balayage ENTIER. On melange les cibles (permutation des lignes du
    bloc de cibles, variables intactes), on refait TOUT le balayage et TOUTE la selection, et on
    note le meilleur TEST obtenu par hasard. Vingt fois. Le vrai meilleur doit depasser le 95e
    centile de ces meilleurs-du-hasard -- sinon il est ce que 3 000 essais produisent tout seuls.
 3. Cout 6,55 pts, multiplicatif, le cout REEL mesure sur le carnet du 18/09. Pas 2,62.
 4. Chaque resultat porte son n, sa valeur sans les 3 meilleurs tickets, ses deux moities de TEST,
    et la part d EX AEQUO au seuil de coupe (un seuil sur une masse de valeurs identiques est un tri
    par le resultat deguise, journal §3.118).
 5. Les cibles sont lues dans `df.attrs["CIBLES"]`, ecrites par tout_table.py, jamais devinees.

Usage :
    python -m intel.research.tout_balayage            # balayage complet, ~quelques minutes
    NULLS=0 python -m intel.research.tout_balayage    # sans la loi du maximum (plus rapide)
Sortie : impression + /app/data/recherche/tout/balayage.csv (toutes les lignes evaluees).
"""
from __future__ import annotations

import itertools
import os
import sys

import numpy as np
import pandas as pd

DOSSIER = "/app/data/recherche/tout"
COUT = float(os.environ.get("COUT_MESURE", "0.0655"))
NULLS = int(os.environ.get("NULLS", "20"))
N_MIN_RECH, N_MIN_TRI, N_MIN_TEST = 60, 30, 30
TOP_UNI_POUR_PAIRES = 20
CATA = -0.50
COUPES = ("haut20", "haut50", "bas50", "bas20", "milieu")
# FUITES CONNUES, exclues d office : `tg_poste` dit qu un canal Telegram a poste le jeton, mais la
# table montre 0 poste AVANT 45 s sur 891 -- l information n existe qu apres la decision.
EXCLUES = {"tg_poste"}
rng = np.random.default_rng(18)


def net(r: np.ndarray) -> np.ndarray:
    return (1.0 + r) * (1.0 - COUT) - 1.0


def masque(x: np.ndarray, coupe: str, q_lo: float, q_hi: float) -> np.ndarray:
    """La coupe est definie par des seuils calcules sur RECHERCHE seulement (q_lo, q_hi)."""
    ok = ~np.isnan(x)
    if coupe == "haut20":
        return ok & (x >= q_hi)
    if coupe == "haut50":
        return ok & (x >= q_lo)
    if coupe == "bas50":
        return ok & (x <= q_lo)
    if coupe == "bas20":
        return ok & (x <= q_hi)
    return ok & (x >= q_lo) & (x <= q_hi)


def seuils(x: np.ndarray, coupe: str) -> tuple[float, float]:
    v = x[~np.isnan(x)]
    if coupe == "haut20":
        return np.nan, float(np.quantile(v, 0.80))
    if coupe == "haut50":
        return float(np.quantile(v, 0.50)), np.nan
    if coupe == "bas50":
        return float(np.quantile(v, 0.50)), np.nan
    if coupe == "bas20":
        return np.nan, float(np.quantile(v, 0.20))
    return float(np.quantile(v, 0.25)), float(np.quantile(v, 0.75))


def mesures(y: np.ndarray) -> dict:
    y = y[~np.isnan(y)]
    if len(y) == 0:
        return {"n": 0}
    s = np.sort(y)
    h = len(y) // 2
    return {"n": int(len(y)), "moy": float(y.mean()), "med": float(np.median(y)),
            "gagn": float((y > 0).mean()), "cata": float((y < CATA).mean()),
            "sans3": float(s[:-3].mean()) if len(y) > 3 else np.nan,
            "sans5pc": float(s[max(1, int(len(y) * 0.05)):].mean()),
            "m1": float(y[:h].mean()) if h else np.nan, "m2": float(y[h:].mean()) if h else np.nan}


def balayer(df: pd.DataFrame, variables: list[str], Y: dict[int, np.ndarray], tranche: np.ndarray,
            verbeux: bool = True) -> tuple[pd.DataFrame, list[str]]:
    """Univarie : pour chaque (variable, coupe, H), mesure sur RECHERCHE, TRI, TEST."""
    R, T, S = tranche == 0, tranche == 1, tranche == 2
    lignes = []
    scores_uni: dict[str, float] = {}
    for v in variables:
        x = pd.to_numeric(df[v], errors="coerce").to_numpy(dtype=float)
        xr = x[R]
        if (~np.isnan(xr)).sum() < N_MIN_RECH or len(np.unique(xr[~np.isnan(xr)])) < 3:
            continue
        for coupe in COUPES:
            lo, hi = seuils(xr, coupe)
            m = masque(x, coupe, lo, hi)
            # part d ex aequo AU seuil : une masse de valeurs identiques rend la coupe arbitraire
            seuil = hi if coupe in ("haut20", "bas20") else lo
            ex = float((xr == seuil).mean()) if not np.isnan(seuil) else 0.0
            for H, y in Y.items():
                mr, mt, ms = mesures(y[m & R]), mesures(y[m & T]), mesures(y[m & S])
                if mr["n"] < N_MIN_RECH:
                    continue
                lignes.append({"type": "uni", "regle": "%s %s" % (v, coupe), "v1": v, "c1": coupe,
                               "v2": "", "c2": "", "H": H, "exaequo": ex,
                               "rech_n": mr["n"], "rech_moy": mr["moy"],
                               "tri_n": mt["n"], "tri_moy": mt.get("moy", np.nan),
                               "test_n": ms["n"], "test_moy": ms.get("moy", np.nan),
                               "test_med": ms.get("med", np.nan), "test_gagn": ms.get("gagn", np.nan),
                               "test_cata": ms.get("cata", np.nan), "test_sans3": ms.get("sans3", np.nan),
                               "test_sans5pc": ms.get("sans5pc", np.nan),
                               "test_m1": ms.get("m1", np.nan), "test_m2": ms.get("m2", np.nan)})
                scores_uni[v] = max(scores_uni.get(v, -9), mr["moy"])
    uni = pd.DataFrame(lignes)
    top = [v for v, _ in sorted(scores_uni.items(), key=lambda kv: -kv[1])[:TOP_UNI_POUR_PAIRES]]
    if verbeux:
        print("   univarie : %d variables retenues, %d evaluations" % (len(scores_uni), len(uni)), flush=True)

    # ------------------------------------------------------------------ les PAIRES
    lignes = []
    cache = {}
    for v in top:
        x = pd.to_numeric(df[v], errors="coerce").to_numpy(dtype=float)
        for coupe in COUPES:
            lo, hi = seuils(x[R], coupe)
            cache[(v, coupe)] = masque(x, coupe, lo, hi)
    for (va, vb) in itertools.combinations(top, 2):
        for ca in COUPES:
            for cb in COUPES:
                m = cache[(va, ca)] & cache[(vb, cb)]
                if (m & R).sum() < N_MIN_RECH:
                    continue
                for H, y in Y.items():
                    mr, mt, ms = mesures(y[m & R]), mesures(y[m & T]), mesures(y[m & S])
                    lignes.append({"type": "paire", "regle": "%s %s ET %s %s" % (va, ca, vb, cb),
                                   "v1": va, "c1": ca, "v2": vb, "c2": cb, "H": H, "exaequo": np.nan,
                                   "rech_n": mr["n"], "rech_moy": mr["moy"],
                                   "tri_n": mt["n"], "tri_moy": mt.get("moy", np.nan),
                                   "test_n": ms["n"], "test_moy": ms.get("moy", np.nan),
                                   "test_med": ms.get("med", np.nan), "test_gagn": ms.get("gagn", np.nan),
                                   "test_cata": ms.get("cata", np.nan), "test_sans3": ms.get("sans3", np.nan),
                                   "test_sans5pc": ms.get("sans5pc", np.nan),
                                   "test_m1": ms.get("m1", np.nan), "test_m2": ms.get("m2", np.nan)})
    paires = pd.DataFrame(lignes)
    if verbeux:
        print("   paires   : %d variables croisees, %d evaluations" % (len(top), len(paires)), flush=True)
    return pd.concat([uni, paires], ignore_index=True), top


def selection(res: pd.DataFrame) -> pd.DataFrame:
    """Choisie sur RECHERCHE + TRI, jamais sur TEST : positive sur les deux, effectifs suffisants."""
    ok = (res["rech_moy"] > 0) & (res["tri_moy"] > 0) & (res["tri_n"] >= N_MIN_TRI) & (res["test_n"] >= N_MIN_TEST)
    return res[ok].sort_values(["rech_moy", "tri_moy"], ascending=False)


def main() -> None:
    df = pd.read_pickle(os.path.join(DOSSIER, "table.pkl"))
    variables = [v for v in df.attrs["VARIABLES"] if v not in EXCLUES]
    cibles = list(df.attrs["CIBLES"])
    df = df[df["eligible"] == 1].sort_values("t_dec").reset_index(drop=True)
    n = len(df)
    tranche = np.zeros(n, dtype=int)
    tranche[int(n * 0.40):] = 1
    tranche[int(n * 0.70):] = 2
    Hs = [int(c.split("_")[1]) for c in cibles if c.startswith("ret_")]
    Y = {H: net(pd.to_numeric(df["ret_%d" % H], errors="coerce").to_numpy(dtype=float)) for H in Hs}
    print("TABLE : %d tickets executables · %d variables · horizons %s · cout %.2f pt"
          % (n, len(variables), Hs, 100 * COUT))
    print("tranches : RECHERCHE %d · TRI %d · TEST %d" % ((tranche == 0).sum(), (tranche == 1).sum(), (tranche == 2).sum()))
    print()
    print("TEMOIN (tout prendre), net sur TEST :")
    for H in Hs:
        m = mesures(Y[H][tranche == 2])
        print("   H=%3d  n=%4d  moy %+6.2f %%  med %+6.2f %%  gagnants %4.1f %%  catastrophes %4.1f %%"
              % (H, m["n"], 100 * m["moy"], 100 * m["med"], 100 * m["gagn"], 100 * m["cata"]))
    print()

    print("BALAYAGE REEL")
    res, top = balayer(df, variables, Y, tranche)
    res.to_csv(os.path.join(DOSSIER, "balayage.csv"), index=False)
    n_tests = len(res)
    sel = selection(res)
    print("   %d evaluations au total · %d passent RECHERCHE>0 ET TRI>0 (n suffisants)" % (n_tests, len(sel)))
    print()

    # ------------------------------------------------------------------ la loi du maximum
    barre = np.nan
    if NULLS > 0:
        print("LOI DU MAXIMUM : %d balayages complets sur des cibles MELANGEES" % NULLS, flush=True)
        maxs = []
        for k in range(NULLS):
            perm = rng.permutation(n)
            Yp = {H: y[perm] for H, y in Y.items()}
            rp, _ = balayer(df, variables, Yp, tranche, verbeux=False)
            sp = selection(rp)
            maxs.append(float(sp["test_moy"].max()) if len(sp) else -9.0)
            print("   hasard %2d/%d : meilleur TEST %+6.2f %%" % (k + 1, NULLS, 100 * maxs[-1]), flush=True)
        barre = float(np.quantile(maxs, 0.95))
        print("   -> BARRE (95e centile des meilleurs-du-hasard) : %+.2f %%" % (100 * barre))
        print()

    # ------------------------------------------------------------------ le rapport
    print("LES 25 MEILLEURES REGLES SUR TEST, parmi celles choisies sur RECHERCHE + TRI")
    print("   (une regle ne VAUT que si TEST > barre, sans3 > 0, et les deux moities de TEST > 0)")
    print()
    print("   %-58s %4s %6s %7s %7s %7s %6s %6s %5s %6s %5s" % (
        "regle", "H", "n", "TEST", "sans3", "m1/m2", "gagn", "cata", "exaeq", "TRI", "verd"))
    if len(sel):
        top25 = sel.sort_values("test_moy", ascending=False).head(25)
        for _, r in top25.iterrows():
            tient = (r["test_moy"] > (barre if not np.isnan(barre) else 0)) and r["test_sans3"] > 0 \
                and r["test_m1"] > 0 and r["test_m2"] > 0
            print("   %-58s %4d %6d %+6.2f%% %+6.2f%% %+3.0f/%+3.0f %5.0f%% %5.0f%% %4.0f%% %+5.1f%% %5s" % (
                r["regle"][:58], r["H"], r["test_n"], 100 * r["test_moy"], 100 * r["test_sans3"],
                100 * r["test_m1"], 100 * r["test_m2"], 100 * r["test_gagn"], 100 * r["test_cata"],
                100 * (r["exaequo"] if not np.isnan(r["exaequo"]) else 0), 100 * r["tri_moy"],
                "TIENT" if tient else "non"))
    print()

    # la distribution : quelle regle reduit le plus les CATASTROPHES sur TEST, a effectif egal ?
    print("L IDEE DE LA DISTRIBUTION : les regles qui font le moins de catastrophes sur TEST (n >= 100)")
    cat = res[(res["test_n"] >= 100) & (res["H"] == 240)].sort_values("test_cata").head(10)
    tem = mesures(Y[240][tranche == 2])
    print("   temoin : catastrophes %.1f %% · moyenne %+.2f %% · sans 5 %% pires %+.2f %%"
          % (100 * tem["cata"], 100 * tem["moy"], 100 * tem["sans5pc"]))
    for _, r in cat.iterrows():
        print("   %-58s n=%4d  cata %4.1f %%  moy %+6.2f %%  sans5pc %+6.2f %%" % (
            r["regle"][:58], r["test_n"], 100 * r["test_cata"], 100 * r["test_moy"], 100 * r["test_sans5pc"]))
    print()
    if not np.isnan(barre):
        vrai = float(sel["test_moy"].max()) if len(sel) else np.nan
        print("VERDICT : meilleur TEST reel %+.2f %% contre barre du hasard %+.2f %% -> %s"
              % (100 * vrai, 100 * barre,
                 "AU-DESSUS, a examiner" if vrai > barre else "EN DESSOUS : le balayage n a rien trouve que le hasard ne produise"))


if __name__ == "__main__":
    main()
