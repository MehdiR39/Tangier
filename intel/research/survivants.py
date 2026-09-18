"""LES SURVIVANTS : trader les jetons qui ont passe une heure, la ou le peage est petit.

MON IDEE, pas une variante de celles de Mido -- 18/09, apres qu il a demande ce a quoi je sers.

LE RAISONNEMENT. Le balayage large a montre que le probleme n est pas la queue mais le CORPS : meme
sans catastrophes, acheter un lancement fait -6 %, parce que le peage de 6,55 pt mange tout. Le
peage est enorme parce que les pools sont minuscules (coffre median 82 SOL) et que la chute est une
falaise. A une heure d age, les pools survivants sont dix a cent fois plus gros : l impact d un
ordre de 20 EUR tombe a quelques dixiemes de point, et le mouvement horaire reste de plusieurs
dizaines de pour cent. Le rapport mouvement / peage change d un ordre de grandeur.

Le projet a teste le MOMENTUM sur jetons etablis (« sans edge a 6 h »). Il n a jamais teste le
RETOUR A LA MOYENNE : acheter apres une chute de X % depuis le plus haut de l heure, revendre a +Y %
ou au bout de H minutes. On teste les DEUX sens dans la meme grille, pour ne pas choisir la
direction apres coup.

DONNEES. `solana_suivi_long` : 4 422 jetons, un releve DexScreener par minute environ, jusqu a
24 h. Prix, liquidite, volume, achats/ventes de l heure.

CONVENTIONS, sans exception :
  - entree au PREMIER releve APRES le signal (jamais au releve qui declenche) ;
  - sortie au PREMIER releve >= cible, VENDU au releve SUIVANT (le prix atteint ne se traite pas,
    §3.101 : le prendre gonflait toute regle de 20 a 40 %) ; sinon au premier releve >= H ;
  - cout par aller-retour = 0,5 pt fixe + 2 x 20 EUR / liquidite USD a l entree (impact) ;
  - un jeton = un trade au plus par regle ;
  - univers : age >= 60 min ET liquidite >= 5 000 USD au signal.

CONTROLES : deux moities chronologiques, sans les 3 meilleurs, et la LOI DU MAXIMUM sur la grille
entiere (instants d entree tires au hasard aux memes ages, 20 grilles completes).
"""
from __future__ import annotations

import itertools
import os
import sqlite3

import numpy as np
import pandas as pd

BASE = os.environ.get("INTEL_DB", "/app/db/intel.sqlite")
MISE = 20.0
FIXE = 0.005
AGE_MIN = 60.0
LIQ_MIN = 5000.0
X = (0.20, 0.30, 0.40, 0.50)
Y = (0.10, 0.20, None)
H = (30, 60, 120, 240)
NULLS = int(os.environ.get("NULLS", "20"))
rng = np.random.default_rng(7)


def charger() -> dict[str, pd.DataFrame]:
    c = sqlite3.connect("file:%s?mode=ro" % BASE, uri=True)
    df = pd.read_sql("SELECT mint, ts, age_min, price_usd, liquidity_usd FROM solana_suivi_long"
                     " WHERE price_usd > 0 AND age_min IS NOT NULL ORDER BY mint, ts", c)
    return {m: g.reset_index(drop=True) for m, g in df.groupby("mint") if len(g) >= 30}


def trade(g: pd.DataFrame, i_sig: int, y: float | None, h: int) -> float | None:
    """Rendement net d un trade signale a la ligne i_sig. None si pas executable."""
    if i_sig + 1 >= len(g):
        return None
    p = g["price_usd"].values
    t = g["ts"].values
    liq = g["liquidity_usd"].values[i_sig]
    if not liq or liq < LIQ_MIN:
        return None
    i0 = i_sig + 1                       # premier releve APRES le signal
    p0 = p[i0]
    fin = t[i0] + h * 60
    cout = FIXE + 2 * MISE / float(liq)
    for j in range(i0 + 1, len(g)):
        if y is not None and p[j] >= p0 * (1 + y):
            if j + 1 < len(g):
                return (p[j + 1] / p0) * (1 - cout) - 1     # vendu au releve SUIVANT
            return None
        if t[j] >= fin:
            return (p[j] / p0) * (1 - cout) - 1
    return None


def signaux(g: pd.DataFrame, sens: str, x: float) -> list[int]:
    """Indices des releves ou le signal se declenche (age >= 60 min, une seule fois par jeton)."""
    p = g["price_usd"].values
    a = g["age_min"].values
    t = g["ts"].values
    out = []
    for i in range(len(g)):
        if a[i] < AGE_MIN:
            continue
        w = p[(t >= t[i] - 3600) & (t <= t[i])]
        if len(w) < 5:
            continue
        if sens == "reversion" and p[i] <= w.max() * (1 - x):
            out.append(i)
            break                        # un trade par jeton
        if sens == "momentum" and p[i] >= w.min() * (1 + x):
            out.append(i)
            break
    return out


def grille(series: dict[str, pd.DataFrame], hasard: bool = False) -> pd.DataFrame:
    lignes = []
    # les signaux se calculent une fois par (sens, x) ; en mode hasard on tire un instant au meme
    # age, sur le meme jeton, pour garder la structure du marche et ne melanger que le declencheur
    for sens, x in itertools.product(("reversion", "momentum"), X):
        sig = {}
        for m, g in series.items():
            s = signaux(g, sens, x)
            if not s:
                continue
            i = s[0]
            if hasard:
                cand = np.where(g["age_min"].values >= AGE_MIN)[0]
                if len(cand) == 0:
                    continue
                i = int(rng.choice(cand))
            sig[m] = i
        for y, h in itertools.product(Y, H):
            r = []
            for m, i in sig.items():
                v = trade(series[m], i, y, h)
                if v is not None:
                    r.append((series[m]["ts"].values[i], v))
            if len(r) < 30:
                continue
            r.sort()
            v = np.array([z for _, z in r])
            hh = len(v) // 2
            lignes.append({"sens": sens, "x": x, "y": y, "h": h, "n": len(v), "moy": v.mean(),
                           "med": float(np.median(v)), "gagn": float((v > 0).mean()),
                           "sans3": float(np.sort(v)[:-3].mean()), "m1": v[:hh].mean(), "m2": v[hh:].mean()})
    return pd.DataFrame(lignes)


def main() -> None:
    series = charger()
    print("%d jetons avec >= 30 releves" % len(series))
    res = grille(series)
    print("%d regles evaluees (n >= 30)" % len(res))
    print()
    print("LA GRILLE, triee par moyenne nette")
    print("   %-10s %5s %5s %4s %5s %8s %8s %8s %6s %8s" % ("sens", "x", "y", "h", "n", "moy", "med", "sans3", "gagn", "m1/m2"))
    for _, r in res.sort_values("moy", ascending=False).head(15).iterrows():
        print("   %-10s %5.0f%% %5s %4d %5d %+7.2f%% %+7.2f%% %+7.2f%% %5.0f%% %+4.0f/%+4.0f" % (
            r["sens"], 100 * r["x"], ("%.0f%%" % (100 * r["y"])) if r["y"] else "H", r["h"], r["n"],
            100 * r["moy"], 100 * r["med"], 100 * r["sans3"], 100 * r["gagn"], 100 * r["m1"], 100 * r["m2"]))
    print()
    if NULLS:
        print("LOI DU MAXIMUM : %d grilles sur des instants d entree tires au hasard" % NULLS)
        maxs = []
        for k in range(NULLS):
            rh = grille(series, hasard=True)
            maxs.append(float(rh["moy"].max()) if len(rh) else -9)
            print("   hasard %2d : meilleure regle %+.2f %%" % (k + 1, 100 * maxs[-1]), flush=True)
        barre = float(np.quantile(maxs, 0.95))
        vrai = float(res["moy"].max())
        print()
        print("VERDICT : meilleure regle reelle %+.2f %% contre barre du hasard %+.2f %% -> %s"
              % (100 * vrai, 100 * barre, "AU-DESSUS" if vrai > barre else "EN DESSOUS"))


if __name__ == "__main__":
    main()
