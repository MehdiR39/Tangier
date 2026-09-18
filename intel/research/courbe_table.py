"""Etude de la COURBE pump.fun, etape 1 : la table des decisions. PROTOCOLE FIGE AVANT TOUT RESULTAT (15/09 soir).

DONNEES  data/recherche/courbe/*.jsonl (courbe_collecte.py) : chaque echange reussi sur la courbe, 13/09 00h ->
         15/09 00h UTC. Prix apres chaque transaction = (30 + SOL de la courbe) / (jetons de la courbe + 73 M) :
         verifie a la sonde (prix paye 6,77e-8 = formule) et reverifie ici sur un echantillon (controle imprime).
UNIVERS  tous les jetons CREES dans la fenetre, qu ils meurent ou non : 1re transaction ou la courbe passe de 0 a
         (0,5 ; 1] milliard de jetons (creation avec achat du createur) ou part de 1 milliard. Aucun filtre sur l issue.
         COURBES STANDARD seulement (ajoute le 15/09 apres mesure sur 3 heures, avant tout resultat) : a l instant
         de la decision, au moins 3 echanges de plus de 0,01 SOL et 90 % d entre eux au prix de la formule
         (tolerance 0,5 %). Les 621 jetons sur 1 722 a autres reglages ne depassent quasi jamais 10 SOL.
CREATEUR proprietaires qui recoivent des jetons dans la transaction de creation ; SOL du createur = SOL de la
         courbe apres creation. Creation sans achat : createur inconnu (createur_connu = 0).
DECISION pour chaque niveau S de SOL reel dans la courbe (NIVEAUX), au premier echange qui fait franchir S :
         instant t_d. Entree au prix apres la derniere transaction d heure <= t_d + 2 s. Rien si le jeton est deja
         complet a l entree, ou si l ordre de 0,31 SOL pese plus de 15 % du SOL virtuel (30 + S).
SORTIE   SUR LA COURBE, jamais dans un pool (changement fige le 15/09 avant tout resultat : dans 51 % des pools de
         la collecte, des portefeuilles recurrents injectent des centaines a des milliers de SOL dans le bloc de la
         migration -- ex. 67 SOL deposes puis 2 970 SOL injectes -- et le prix du pool n a plus de rapport avec la
         fin de courbe ; on ne sait pas encore s il est negociable). Instant de sortie = min(t_entree + H, premier
         echange ou la courbe atteint 80 SOL + 2 s) ; prix apres la derniere transaction <= cet instant. Si la
         courbe est complete avant cet instant, prix du dernier echange AVANT la completion et `approx_H` = 1.
         Une sortie apres la fin des donnees = cible vide.
COUT     principal : 2,5 % (0,95 % pump.fun + ~0,30 % createur, par cote, mesures sur 207 echanges) + 0,32 % de
         priorite + 2 x 0,31 / (30 + S_entree) d impact ; prudent : + 1 point (pourboires).
VARIABLES visibles a t_d : S, age du jeton, secondes pour atteindre S, echanges, acheteurs uniques, ventes, SOL
         achete / vendu sur 30 et 60 s, part du plus gros acheteur, createur (acheteur de la transaction de
         creation) : a-t-il vendu, part de ses jetons ; acheteurs du bloc de creation ; bons portefeuilles
         (`bons_R.json`, appris sur les pools AVANT le 12/09 21h) : nombre, SOL, combien ont deja vendu.
TRANCHES par heure de creation : RECHERCHE 60 %, TRI 20 %, TEST FINAL 20 %.
Sortie : data/recherche/courbe/table.pkl. Le verdict est fige dans courbe_verdict.py.
"""
from __future__ import annotations

import glob
import json
import os
import sys
from bisect import bisect_right
from collections import defaultdict

import numpy as np
import pandas as pd

ICI = os.path.dirname(os.path.abspath(__file__))
RACINE = os.path.abspath(os.path.join(ICI, "..", ".."))
DC = os.path.join(RACINE, "data", "recherche", "courbe")
DP = os.path.join(RACINE, "data", "recherche", "copie")
NIVEAUX = (2, 5, 10, 20, 30, 40, 50, 60, 70)
HORIZONS = (30, 60, 120, 300, 600, 1800)
V_SOL, V_TOK, RESERVE_TOK = 30.0, 73_000_000.0, 206_900_000.0
MISE = 0.31
EXEC = 2


def prix(lam, tok):
    return (V_SOL + lam / 1e9) / (tok + V_TOK)


def charger():
    fichiers = sorted(glob.glob(os.path.join(DC, "2026*.jsonl")))
    wid: dict[str, int] = {}
    par_jeton = defaultdict(list)
    for fch in fichiers:
        for ligne in open(fch, encoding="utf-8"):
            bt, slot, m, lam, tok, dlam, dtok, parts, _ = json.loads(ligne)
            if bt is None:
                continue
            pp = tuple((wid.setdefault(o, len(wid)), d, s) for o, d, s in parts)
            par_jeton[m].append((bt, slot, lam, tok, dlam, dtok, pp))
    fin = max(x[0] for v in par_jeton.values() for x in v[-1:])
    return par_jeton, wid, fin


def prix_pools(mints):
    """Chemins de prix des pools PumpSwap des jetons migres, s ils sont dans la collecte des pools."""
    pools = json.load(open(os.path.join(DP, "pools.json")))
    pair_de = {p["pair"]: p["mint"] for p in pools if p["mint"] in mints}
    out = {}
    for ligne in open(os.path.join(DP, "echanges.jsonl"), encoding="utf-8"):
        debut = ligne[:80]
        pair = next((p for p in pair_de if p in debut), None)
        if not pair:
            continue
        d = json.loads(ligne)
        if d.get("erreur") or not d.get("echanges"):
            continue
        e = [x for x in d["echanges"] if x[2]]
        out[pair_de[pair]] = (d["naissance"], np.array([x[0] for x in e], float), np.array([x[2] for x in e], float))
    return out


def main():
    par_jeton, wid, fin_donnees = charger()
    bons = {b["wallet"] for b in json.load(open(os.path.join(DP, "bons_R.json")))}
    bons_id = {wid[w] for w in bons if w in wid}
    # controle de la formule : le prix paye tombe-t-il entre le prix avant et apres ?
    dedans, total = 0, 0
    for m, L in list(par_jeton.items())[:3000]:
        L.sort(key=lambda x: (x[1], x[0]))
        for a, b in zip(L, L[1:]):
            if b[6] and b[5] and b[4] and abs(b[4]) > 1e7:
                p0, p1, pe = prix(a[2], a[3]), prix(b[2], b[3]), abs(b[4] / 1e9) / abs(b[5])
                lo, hi = min(p0, p1), max(p0, p1)
                total += 1
                dedans += lo * 0.995 <= pe <= hi * 1.005
    print("controle formule : prix paye dans [avant, apres] (tolerance 0,5 %%) : %d / %d" % (dedans, total), flush=True)

    crees, completes = {}, set()
    for m, L in par_jeton.items():
        L.sort(key=lambda x: (x[1], x[0]))
        premier = L[0]
        avant = premier[3] - premier[5]
        if (abs(avant) < 1.0 and 5e8 < premier[3] <= 1e9 + 1) or abs(avant - 1e9) < 1.0:
            crees[m] = premier[0]
        if min(x[3] for x in L) <= RESERVE_TOK + 1:
            completes.add(m)
    print("jetons touches %d · crees dans la fenetre %d · completes %d" % (len(par_jeton), len(crees), len(completes & set(crees))), flush=True)

    t_crea = np.sort(list(crees.values()))
    c1, c2 = t_crea[int(0.6 * len(t_crea))], t_crea[int(0.8 * len(t_crea))]
    lignes = []
    exclus_reglage: dict[int, int] = {}
    for m, t0 in crees.items():
        L = par_jeton[m]
        bts = np.array([x[0] for x in L], float)
        lam = np.array([x[2] for x in L], float)
        tok = np.array([x[3] for x in L], float)
        px = prix(lam, tok)
        sol = lam / 1e9
        i_comp = next((i for i, x in enumerate(L) if x[3] <= RESERVE_TOK + 1), None)
        t_comp = bts[i_comp] if i_comp is not None else np.inf
        createur = {w for w, d, s in L[0][6] if d > 0} if abs(L[0][3] - L[0][5]) < 1.0 else set()
        sol_createur = L[0][2] / 1e9 if createur else 0.0
        slot0 = L[0][1]
        n_bloc0 = len({w for x in L if x[1] == slot0 for w, d, s in x[6] if d > 0})
        # conformite a la formule, cumulee echange par echange (visible a l instant)
        conf_ok = np.zeros(len(L)); conf_n = np.zeros(len(L))
        for k in range(1, len(L)):
            x = L[k]
            conf_ok[k], conf_n[k] = conf_ok[k - 1], conf_n[k - 1]
            if x[6] and x[4] * x[5] < 0 and abs(x[4]) > 1e7:
                p0, p1 = prix(x[2] - x[4], x[3] - x[5]), prix(x[2], x[3])
                pe = abs(x[4] / 1e9) / abs(x[5])
                conf_n[k] += 1
                conf_ok[k] += min(p0, p1) * 0.995 <= pe <= max(p0, p1) * 1.005
        for S in NIVEAUX:
            i = next((k for k in range(len(L)) if sol[k] >= S), None)
            if i is None:
                break
            if conf_n[i] < 3 or conf_ok[i] / conf_n[i] < 0.9:
                exclus_reglage[S] = exclus_reglage.get(S, 0) + 1
                continue
            t_d = bts[i]
            ke = bisect_right(bts, t_d + EXEC) - 1
            if bts[ke] >= t_comp or tok[ke] <= RESERVE_TOK + 1:
                continue
            S_e = sol[ke]
            if MISE / (V_SOL + S_e) > 0.15:
                continue
            pe = px[ke]
            vus = L[:i + 1]
            acheteurs, vendeurs, sol_w = set(), set(), defaultdict(float)
            for x in vus:
                for w, d, s in x[6]:
                    if d > 0:
                        acheteurs.add(w)
                        sol_w[w] += -s
                    elif d < 0:
                        vendeurs.add(w)
            j30, j60 = bisect_right(bts, t_d - 30), bisect_right(bts, t_d - 60)
            ach = lambda j: sum(-s for x in L[j:i + 1] for w, d, s in x[6] if d > 0)
            ven = lambda j: sum(s for x in L[j:i + 1] for w, d, s in x[6] if d < 0)
            for w in createur:
                sol_w[w] += sol_createur / len(createur)
            tot_sol = sum(sol_w.values()) or 1.0
            bons_ici = [w for w in acheteurs if w in bons_id]
            f = {"mint": m, "t0": t0, "S": S, "tranche": "R" if t0 < c1 else ("T" if t0 < c2 else "F"),
                 "S_e": S_e, "age": t_d - t0, "n_echanges": i + 1, "n_acheteurs": len(acheteurs), "n_vendeurs": len(vendeurs),
                 "sol_achete_30": ach(j30), "sol_vendu_30": ven(j30), "sol_achete_60": ach(j60), "sol_vendu_60": ven(j60),
                 "part_top": max(sol_w.values()) / tot_sol if sol_w else np.nan,
                 "createur_connu": int(bool(createur)), "createur_vendu": int(bool(createur & vendeurs)),
                 "part_createur": sum(sol_w[w] for w in createur) / tot_sol,
                 "n_bloc_creation": n_bloc0, "n_bons": len(bons_ici), "sol_bons": sum(sol_w[w] for w in bons_ici),
                 "n_bons_vendu": len(set(bons_ici) & vendeurs), "complet_final": int(m in completes)}
            j80 = next((k for k in range(ke + 1, len(L)) if sol[k] >= 80), None)
            t_cap = bts[j80] + EXEC if j80 is not None else np.inf
            for H in HORIZONS:
                t_s = min(bts[ke] + H, t_cap)
                if t_s > fin_donnees:
                    f["brut_%d" % H] = np.nan
                    continue
                k = bisect_right(bts, t_s) - 1
                if i_comp is not None and k >= i_comp:
                    k = i_comp - 1
                    f["approx_%d" % H] = 1
                else:
                    f["approx_%d" % H] = 0
                f["brut_%d" % H] = px[max(k, ke)] / pe - 1
            lignes.append(f)
    df = pd.DataFrame(lignes)
    df.to_pickle(os.path.join(DC, "table.pkl"))
    print("table : %d decisions, %d jetons -> %s" % (len(df), df.mint.nunique(), os.path.join(DC, "table.pkl")))
    print("decisions ecartees (courbe non standard a l instant) par niveau : %s" % exclus_reglage)
    print(df.groupby(["tranche", "S"]).size().unstack(0).to_string())


if __name__ == "__main__":
    main()
