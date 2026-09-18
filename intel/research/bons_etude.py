"""Pourquoi les bons portefeuilles gagnent : etape 1, la table. PROTOCOLE FIGE AVANT TOUT CALCUL (15/09 soir).

CONTEXTE (journal §3.87). 325 portefeuilles gagnants sur RECHERCHE gardent +8,8 % par pool sur TRI (tous :
-13,5 %), mais les copier perd (-6,25 % au test). 68,5 % de leurs positions sont un achat unique a +10 % : leur
avantage est surtout le CHOIX du jeton et du moment, puis la sortie. Demande de l operateur : « le pourquoi c est
a nous de le trouver, analyse technique, fondamentale, on va tout croiser ».

UNE LIGNE = un pool a un age de decision A (s) parmi AGES. Tout ce qui est dans la ligne etait VISIBLE a A :
  - transactions d age <= A (flux lu par un abonnement en temps reel ; le prix d EXECUTION est pris a A + 2 s) ;
  - qualite des portefeuilles tiree des pools TERMINES (naissance + 900 s) AVANT la naissance du pool courant :
    bon = >= 10 pools et rendement propre moyen > +10 %, perdant = >= 10 pools et moyenne < 0, connu = >= 3 pools ;
  - variables fondamentales et de marche de `balayage/table.pkl`, fusionnees sur (pool, A), deja visibles a A ;
  - regime = moyenne des 50 derniers resultats connus (decision 60 s, sortie 240 s, cout reduit, tous jetons).
VARIABLES DE FLUX calculees ici : n transactions / achats / ventes (depuis 0, 10 s, 30 s), SOL achetes et vendus
  sur 30 s et flux net en part du pool, plus grosse vente et plus gros achat sur 30 s (SOL et part du pool),
  secondes depuis la plus grosse vente des 60 s, acheteurs uniques (depuis 0 et 30 s), part du plus gros acheteur,
  echanges sans acheteur visible (bots atomiques), taille mediane d achat, acheteurs des 2 premieres secondes,
  rendements 5/10/30/60 s, repli depuis le plus haut, secondes depuis le plus haut, volatilite 30 s, croissance
  du coffre SOL ; bons/perdants/connus/neufs acheteurs (nombre, SOL, part), bons ayant deja vendu.
CIBLES : rendement brut de A + 2 a A + 2 + H pour H dans HORIZONS (prix a la derniere transaction), coffre SOL a
  l entree pour le cout ; « un bon achete dans les 10 s » ; sortie « a la premiere vente d un bon deja entre »
  (+ 2 s, plafond 240 s).
Aucune ligne si l ordre de 0,31 SOL pese plus de 15 % du pool, ou si A + 2 + H depasse 900 s (cible vide).

Sortie : data/recherche/copie/etude.pkl. Le verdict et ses familles de tests sont figes dans bons_verdict.py.
"""
from __future__ import annotations

import heapq
import json
import os
import sys
from bisect import bisect_right

import numpy as np
import pandas as pd

ICI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ICI)
import copie_verdict as cv  # noqa: E402
import grand_balayage as gb  # noqa: E402
import combinaison_finale as cf  # noqa: E402

AGES = (20, 30, 45, 60, 90, 120, 180, 300)
HORIZONS = (60, 120, 240, 480)
EXEC = 2.0
SORTIE = os.path.join(cv.D, "etude.pkl")
COURBE: dict[str, bool] = {}


def classes(stats, w):
    s = stats.get(w)
    if not s:
        return "neuf"
    n, somme = s
    if n >= 10:
        m = somme / n
        return "bon" if m > 0.10 else ("perdant" if m < 0 else "connu")
    return "connu" if n >= 3 else "neuf"


def main():
    pools_ref = json.load(open(os.path.join(cv.D, "pools.json")))
    naiss = np.sort([p["naissance"] for p in pools_ref])
    c1, c2 = naiss[int(0.6 * len(naiss))], naiss[int(0.8 * len(naiss))]
    ordre = []
    with open(os.path.join(cv.D, "echanges.jsonl"), "rb") as f:
        while True:
            pos = f.tell()
            ligne = f.readline()
            if not ligne:
                break
            d = json.loads(ligne)
            if d.get("erreur") or d.get("tronque") or not d.get("echanges"):
                continue
            ordre.append((d["naissance"], pos))
    ordre.sort()
    print("pools utilisables : %d" % len(ordre), flush=True)

    stats: dict[str, list] = {}           # portefeuille -> [n pools termines, somme des rendements propres]
    attente: list = []                     # (fin, id, {portefeuille: rendement})
    lignes = []
    fh = open(os.path.join(cv.D, "echanges.jsonl"), "rb")
    for num, (t0, pos) in enumerate(ordre):
        while attente and attente[0][0] <= t0:
            _, _, res = heapq.heappop(attente)
            for w, r in res.items():
                s = stats.setdefault(w, [0, 0.0])
                s[0] += 1
                s[1] += r
        fh.seek(pos)
        d = json.loads(fh.readline())
        V = d["V"]
        e = [x for x in d["echanges"] if x[0] <= cv.FENETRE and x[2]]
        if len(e) < 5:
            continue
        ages = np.array([x[0] for x in e], float)
        prix = np.array([x[2] for x in e], float)
        q = np.array([x[3] for x in e], float)
        b = np.array([x[5] for x in e], float)
        n = len(e)
        achat_sol = np.zeros(n); vente_sol = np.zeros(n); max_v = np.zeros(n); max_a = np.zeros(n)
        n_ach = np.zeros(n); n_ven = np.zeros(n); sans_part = np.zeros(n)
        tx_parts = []
        for i, x in enumerate(e):
            parts = []
            for o, dt, ds in x[4]:
                if not o or abs(ds) > cv.PART_MAX_SOL or dt == 0:
                    continue
                parts.append((o, dt, ds))
                if dt > 0:
                    achat_sol[i] += -ds; n_ach[i] += 1; max_a[i] = max(max_a[i], -ds)
                else:
                    vente_sol[i] += ds; n_ven[i] += 1; max_v[i] = max(max_v[i], ds)
            if not x[4] and i > 0 and (b[i] - b[i - 1]) * (q[i] - q[i - 1]) < 0:
                sans_part[i] = 1
            tx_parts.append(parts)
        cum = lambda a: np.concatenate([[0.0], np.cumsum(a)])
        C_as, C_vs, C_na, C_nv, C_sp = map(cum, (achat_sol, vente_sol, n_ach, n_ven, sans_part))

        # parcours chronologique : premiers achats par portefeuille, classes figees a la naissance du pool
        classe_de = {}
        premier_achat = {}                 # w -> (age, sol)
        premiere_vente = {}                # w -> index de tx
        position = {}                      # w -> (1re action achat ?, sol achetes, jetons achetes, sol vendus, jetons vendus)
        for i, parts in enumerate(tx_parts):
            for o, dt, ds in parts:
                if o not in classe_de:
                    oc = COURBE.get(o)
                    if oc is None:
                        oc = COURBE[o] = cv.sur_courbe(o)
                    classe_de[o] = classes(stats, o) if oc else "programme"
                if dt > 0 and o not in premier_achat:
                    premier_achat[o] = (ages[i], -ds, i)
                if dt < 0 and o not in premiere_vente:
                    premiere_vente[o] = i
                p = position.get(o)
                if p is None:
                    p = position[o] = [dt > 0, 0.0, 0.0, 0.0, 0.0, ages[i], -ds if dt > 0 else 0.0]
                if dt > 0:
                    p[1] += -ds; p[2] += dt
                else:
                    p[3] += ds; p[4] += -dt
        tri_achats = sorted((a, w, s, i) for w, (a, s, i) in premier_achat.items() if classe_de.get(w) != "programme")
        ages_achats = [z[0] for z in tri_achats]

        # regime et variables de la table au meme (pool, A)
        for A in AGES:
            k = bisect_right(ages, A) - 1
            if k < 2:
                continue
            ke = bisect_right(ages, A + EXEC) - 1
            pe, qe = prix[ke], q[ke]
            if not (pe > 0) or cv.MISE_SOL / (qe + V) > cv.IMPACT_MAX:
                continue
            pA = prix[k]
            at = lambda t: prix[max(bisect_right(ages, t) - 1, 0)]
            j10, j30, j60 = (bisect_right(ages, A - w) for w in (10, 30, 60))
            seg = prix[:k + 1]
            imax = int(np.argmax(seg))
            lr = np.diff(np.log(prix[j30:k + 1])) if k + 1 - j30 >= 3 else np.array([])
            m60 = max_v[j60:k + 1]
            ig = int(np.argmax(m60)) + j60 if len(m60) and m60.max() > 0 else None
            vus = tri_achats[:bisect_right(ages_achats, A)]
            vus30 = [z for z in vus if z[0] > A - 30]
            cl = [classe_de.get(z[1], "neuf") for z in vus]
            sol_cl = {c: sum(z[2] for z, cc in zip(vus, cl) if cc == c) for c in ("bon", "perdant", "connu", "neuf")}
            tot_sol = sum(z[2] for z in vus) or 1.0
            bons_entres = [z[1] for z, cc in zip(vus, cl) if cc == "bon"]
            f = {"pair": d["pair"], "t0": t0, "A": A, "tranche": "R" if t0 < c1 else ("T" if t0 < c2 else "F"),
                 "V": V, "q_e": qe, "qV": qe + V, "qV_A": q[k] + V,   # qV (a A + 2 s) sert au COUT, jamais de variable
                 "ret_naiss": pA / prix[0] - 1, "ret_5": pA / at(A - 5) - 1, "ret_10": pA / at(A - 10) - 1,
                 "ret_30": pA / at(A - 30) - 1, "ret_60": pA / at(A - 60) - 1,
                 "dd_max": pA / seg.max() - 1, "t_depuis_max": A - ages[imax],
                 "vol_30": float(lr.std()) if len(lr) >= 2 else np.nan, "q_croiss": q[k] / q[0] - 1 if q[0] > 0 else np.nan,
                 "n_tx": k + 1, "n_achats": C_na[k + 1], "n_ventes": C_nv[k + 1],
                 "n_achats_10": C_na[k + 1] - C_na[j10], "n_ventes_10": C_nv[k + 1] - C_nv[j10],
                 "n_achats_30": C_na[k + 1] - C_na[j30], "n_ventes_30": C_nv[k + 1] - C_nv[j30],
                 "sol_achats_30": C_as[k + 1] - C_as[j30], "sol_ventes_30": C_vs[k + 1] - C_vs[j30],
                 "flux_net_30": (C_as[k + 1] - C_as[j30] - C_vs[k + 1] + C_vs[j30]) / (q[k] + V),
                 "max_vente_30": max_v[j30:k + 1].max() if k + 1 > j30 else 0.0,
                 "max_vente_30_part": (max_v[j30:k + 1].max() if k + 1 > j30 else 0.0) / (q[k] + V),
                 "max_achat_30": max_a[j30:k + 1].max() if k + 1 > j30 else 0.0,
                 "t_depuis_grosse_vente": (A - ages[ig]) if ig is not None else np.nan,
                 "n_acheteurs": len(vus), "n_acheteurs_30": len(vus30),
                 "part_top_acheteur": (max(z[2] for z in vus) / tot_sol) if vus else np.nan,
                 "n_sans_acheteur": C_sp[k + 1], "achat_median": float(np.median([z[2] for z in vus])) if vus else np.nan,
                 "n_acheteurs_2s": sum(1 for z in vus if z[0] <= 2),
                 "n_bons": cl.count("bon"), "n_perdants": cl.count("perdant"), "n_connus": cl.count("connu"),
                 "n_neufs": cl.count("neuf"), "sol_bons": sol_cl["bon"], "part_bons": sol_cl["bon"] / tot_sol,
                 "part_perdants": sol_cl["perdant"] / tot_sol, "part_neufs": sol_cl["neuf"] / tot_sol,
                 "n_bons_30": sum(1 for z in vus30 if classe_de.get(z[1]) == "bon"),
                 "n_bons_sortis": sum(1 for w in bons_entres if w in premiere_vente and ages[premiere_vente[w]] <= A)}
            # cibles
            for H in HORIZONS:
                if A + EXEC + H > cv.FENETRE:
                    f["brut_%d" % H] = np.nan
                    continue
                ks = bisect_right(ages, A + EXEC + H) - 1
                f["brut_%d" % H] = prix[ks] / pe - 1
            f["bon_achete_10"] = int(any(A < z[0] <= A + 10 and classe_de.get(z[1]) == "bon" for z in tri_achats))
            # sortie « a la premiere vente d un bon deja entre » (+ 2 s, plafond 240 s)
            ventes_bons = [ages[premiere_vente[w]] for w in bons_entres if w in premiere_vente and ages[premiere_vente[w]] > A + EXEC]
            fin = min(min(ventes_bons) + EXEC if ventes_bons else np.inf, A + EXEC + 240)
            f["brut_sortie_bons"] = (prix[bisect_right(ages, fin) - 1] / pe - 1) if (bons_entres and fin <= cv.FENETRE) else np.nan
            lignes.append(f)

        # rendement propre de chaque portefeuille dans ce pool, connu a la fin de sa fenetre
        dernier = prix[-1]
        res = {}
        for w, p in position.items():
            if not p[0] or classe_de.get(w) == "programme" or not (0 <= p[5] <= cv.ACHAT_MAX_AGE) or p[6] < cv.ACHAT_MIN_SOL or p[1] <= 0:
                continue
            res[w] = min((p[3] + max(p[2] - p[4], 0.0) * dernier) / p[1] - 1, gb.PLAFOND)
        heapq.heappush(attente, (t0 + cv.FENETRE, num, res))
        if num % 250 == 0:
            print("  %d/%d pools, %d lignes, %d portefeuilles notes" % (num, len(ordre), len(lignes), len(stats)), flush=True)
    df = pd.DataFrame(lignes)

    # fusion avec la table du balayage (fondamental, marche) et regime
    tab = pd.read_pickle(os.path.join(gb.D, "table.pkl"))
    garde = ["pair", "A", "telegram", "twitter", "site", "n_descr", "createur_prec", "sac1", "n_sacs5",
             "det_a_vide", "fin_a_vide", "lancements_10min", "marche_ret_30min", "marche_vides_30min", "heure"]
    df = df.merge(tab[garde], on=["pair", "A"], how="left")
    tab = gb.tranches(tab.reset_index(drop=True))
    tab["netr_240"] = tab["brut_240"] - (0.0125 + (tab.cout - 0.017) / 2)
    ref = tab[tab.A == 60].dropna(subset=["netr_240"]).copy()
    ref["t_fin"] = ref.naissance + 60 + 2 + 240
    ref["r"] = np.minimum(ref.netr_240, gb.PLAFOND)
    df["regime50"] = cf.indicateur(ref, (df.t0 + df.A).to_numpy(), 50)
    df.to_pickle(SORTIE)
    print("etude : %d lignes, %d pools, %d colonnes -> %s" % (len(df), df.pair.nunique(), df.shape[1], SORTIE))
    print(df.groupby("tranche").pair.nunique().to_string())


if __name__ == "__main__":
    main()
