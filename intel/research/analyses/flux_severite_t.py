"""La severite, jugee correctement : en ECARTS-TYPES, pas en euros bruts.

POURQUOI CE SECOND SCRIPT. `flux_severite.py` compare sept severites en euros par ticket et prend la
meilleure ; sa barre du hasard permute la meme procedure et monte a +2,42. Notre meilleure ligne
(garder 60 %, +0,682) est loin dessous, donc « ca ne passe pas ». Sauf que cette barre est DOMINEE
PAR LA PLUS PETITE CELLULE : garder 5 % ne laisse que 66 tickets, dont le bruit propre est 1,56 EUR
par ticket, contre 0,17 pour la cellule a 80 %. Une procedure qui prend le maximum en euros bruts
parmi des cellules d effectifs si differents choisira presque toujours la plus petite et la plus
bruyante -- c est la procedure qui est mauvaise, pas forcement le resultat.

CE QU IL FAUT COMPARER : chaque severite a SON PROPRE bruit. La comparaison est APPARIEE (les
tickets gardes sont un sous-ensemble de ceux du temoin), donc le bruit d une cellule qui garde k
tickets sur n est sigma x racine(m/(n k)) avec m = n - k, et non sigma/racine(k) -- l erreur que
j avais faite ce matin et qui est notee au journal (§3.155). On prend alors le maximum du rapport
ecart/bruit, et c est CE maximum qu on permute.

Les deux lectures sont donnees cote a cote. Celle en euros repond a « quelle severite rapporte le
plus » ; celle en ecarts-types repond a « y a-t-il quelque chose », et c est la seule des deux qui
peut etre comparee a du hasard.
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
HEURES = 66.0


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
    tz = dt.timezone(dt.timedelta(hours=2))
    DEBUT = dt.datetime(2026, 9, 16, 0, 0, tzinfo=tz)
    FIN = dt.datetime(2026, 9, 18, 18, 0, tzinfo=tz)

    def bruit(n, k):
        """Bruit d une comparaison APPARIEE : k tickets tires parmi les n du temoin."""
        m = n - k
        return sigma * np.sqrt(m / (n * k)) if 0 < k < n else np.inf

    def marche(yv, yn):
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
            ordre = np.argsort(p, kind="stable")
            for g in GARDES:
                k = max(5, int(len(nets) * g))
                tot[g].extend(nets[ordre[:k]].tolist())
        return tot, np.array(tem)

    def stats(tot, tem):
        """(ecart en EUR, ecart en ECARTS-TYPES) pour chaque severite."""
        out = {}
        n = len(tem)
        for g in GARDES:
            v = np.array(tot[g])
            if len(v) < 20:
                continue
            d = MISE * (v.mean() - tem.mean())
            out[g] = (d, d / bruit(n, len(v)))
        return out

    tot, tem = marche(y_vid, y_net)
    vrai = stats(tot, tem)
    print("%d tickets · temoin %d · ecart-type d un ticket %.2f EUR · cout %.2f pt"
          % (len(df), len(tem), sigma, 100 * COUT))
    print()
    print("   %-8s %6s %11s %11s %11s %9s" %
          ("garde", "n", "EUR/tick", "vs temoin", "son bruit", "ecarts-t"))
    for g in GARDES:
        if g not in vrai:
            continue
        k = len(tot[g])
        d, z = vrai[g]
        print("   %-8s %6d %+10.3f %+10.3f %11.3f %+8.2f" %
              ("%.0f %%" % (100 * g), k, MISE * np.array(tot[g]).mean(), d, bruit(len(tem), k), z))
    print()
    print("   Le bruit propre d une cellule explose quand elle se vide : garder 5 %% ne laisse que")
    print("   quelques dizaines de tickets, et 3 EUR d ecart y sont du hasard ordinaire.")

    if NULLS:
        g_eur = max(vrai, key=lambda g: vrai[g][0])
        g_z = max(vrai, key=lambda g: vrai[g][1])
        print()
        print("BARRE DU HASARD : %d marches avant permutees, DEUX lectures du meme tirage" % NULLS)
        rng = np.random.default_rng(31)
        m_eur, m_z = [], []
        for i in range(NULLS):
            perm = rng.permutation(len(y_net))
            tp, rt = marche(y_vid[perm], y_net[perm])
            s = stats(tp, rt)
            if not s:
                continue
            m_eur.append(max(x[0] for x in s.values()))
            m_z.append(max(x[1] for x in s.values()))
            if (i + 1) % 10 == 0:
                print("   %d/%d · max hasard : %+0.3f EUR · %+0.2f ecarts-types"
                      % (i + 1, NULLS, max(m_eur), max(m_z)), flush=True)
        ke = sum(1 for x in m_eur if x >= vrai[g_eur][0])
        kz = sum(1 for x in m_z if x >= vrai[g_z][1])
        print()
        print("   EN EUROS BRUTS   meilleure severite %.0f %% a %+.3f EUR · %d tirages sur %d font aussi bien (p ~ %.3f)"
              % (100 * g_eur, vrai[g_eur][0], ke, len(m_eur), (ke + 1) / (len(m_eur) + 1)))
        print("   EN ECARTS-TYPES  meilleure severite %.0f %% a %+.2f sigma · %d tirages sur %d font aussi bien (p ~ %.3f)"
              % (100 * g_z, vrai[g_z][1], kz, len(m_z), (kz + 1) / (len(m_z) + 1)))
        print()
        print("   La seconde ligne est la reponse a « y a-t-il quelque chose » ; la premiere ne")
        print("   repond qu a « quelle cellule est la plus petite ».")


if __name__ == "__main__":
    main()
