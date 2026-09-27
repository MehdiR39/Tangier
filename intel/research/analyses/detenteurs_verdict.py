"""Verdict du filtre « detenteurs » -- regles FIGEES le 15/09 avant d avoir les donnees.

LA QUESTION (§3.81). Le carnet propre perd parce que 15,2 % de ses jetons se font vider (-81 %)
quand les autres gagnent +11 %. Point mort a 11,9 % de vidages ; l objectif de l operateur,
50 EUR par jour, demande environ +1,1 % net par ticket, soit ~10,7 % de vidages. Un vidage commence
par un portefeuille qui vend un gros stock : ce stock se voit-il a T+60 s, et l ecarter suffit-il ?

CE QUI EST FIGE ICI, ET NE SE REGLE PAS APRES AVOIR VU LE RESULTAT
  population   les tickets PAPIER du moteur (propre, telegram), joints au releve des detenteurs
               pris au plus tard 20 s apres la decision -- ce que le moteur pouvait savoir.
  issue        gain papier corrige du cout d execution REEL mesure en chaine (§3.81) :
               propre -0,010, telegram -0,079 par euro, au lieu du peage suppose de 2 %.
  filtre       ecarter si (plus gros portefeuille >= S) ou (au moins 2 portefeuilles a solde
               identique >= 1 % de l offre). S parmi {5, 10, 15, 20, 30 %}, choisi sur la moitie de
               RECHERCHE, juge sur la moitie de JUGEMENT, par ordre d entree.
  decision     GO seulement si, sur la moitie de JUGEMENT : niveau garde > 0 apres cout, niveau
               garde sans son meilleur ticket > 0, taux de vidage garde < 11,9 %. Et au moins 100
               tickets dans cette moitie. Sinon : NON, ou TROP TOT.
               Un GO ne met pas d argent : il ouvre deux jours de confirmation en papier.

Aussi : pouvoir separateur des variables sur TOUS les lancements releves (AUC pour le vidage a
+240 s), pour savoir si l information existe meme quand le carnet est trop petit pour conclure.

Lancement : python -m intel.research.detenteurs_verdict
"""
from __future__ import annotations

import os
import random
import sqlite3
import statistics as st

BASE_MOTEUR = os.environ.get("INTEL_DB", "/app/db/intel.sqlite")
BASE_DET = os.environ.get("DETENTEURS_DB", "/app/db/detenteurs.sqlite")
PEAGE_PAPIER = 0.02                          # telegram_rapide.peage_pct par defaut
COUT_REEL = {"propre": 0.010, "telegram": 0.079}
SEUILS = (0.05, 0.10, 0.15, 0.20, 0.30)
POINT_MORT_VIDAGE = 0.119
MIN_JUGEMENT = 100
MISE = 30.0


def ecarte(t, seuil) -> bool:
    return (t["top1"] or 0) >= seuil or (t["identiques"] or 0) >= 2


def tickets_papier(m, d):
    rel = {r[0]: {"ts": r[1], "top1": r[2], "top5": r[3], "identiques": r[4]}
           for r in d.execute("SELECT mint, ts, top1, top5, identiques FROM releve WHERE erreur IS NULL")}
    out = []
    for mint, meth, ts, mise, gain in m.execute(
            "SELECT mint, methode, ts_entree, mise_eur, gain_eur FROM tg_lignes"
            " WHERE mode='paper' AND gain_eur IS NOT NULL AND methode IN ('propre','telegram')"
            " ORDER BY ts_entree"):
        r = rel.get(mint)
        if not r or r["ts"] > ts + 20:
            continue
        ratio = (gain / mise + 1) / (1 - PEAGE_PAPIER)
        out.append(dict(r, mint=mint, meth=meth, ts_entree=ts, r=ratio - 1 - COUT_REEL[meth]))
    return out


def resume(v):
    if not v:
        return None
    s = sorted(v, reverse=True)
    return dict(n=len(v), moy=st.mean(v), sans_best=st.mean(s[1:]) if len(s) > 1 else float("nan"),
                vides=sum(1 for x in v if x <= -0.5) / len(v))


def auc(x, y):
    paires = [(a, b) for a, b in zip(x, y) if a is not None]
    n1 = sum(1 for _, b in paires if b)
    n0 = len(paires) - n1
    if n1 < 5 or n0 < 5:
        return None
    rang = {}
    tri = sorted(paires, key=lambda p: p[0])
    i = 0
    while i < len(tri):
        j = i
        while j < len(tri) and tri[j][0] == tri[i][0]:
            j += 1
        for k in range(i, j):
            rang[k] = (i + j + 1) / 2
        i = j
    s1 = sum(rang[k] for k, p in enumerate(tri) if p[1])
    return (s1 - n1 * (n1 + 1) / 2) / (n1 * n0)


def main():
    m = sqlite3.connect("file:%s?mode=ro" % BASE_MOTEUR, uri=True)
    d = sqlite3.connect("file:%s?mode=ro" % BASE_DET, uri=True)

    # --- A. tous les lancements : l information existe-t-elle ? ---
    lanc = d.execute("SELECT r.top1, r.top5, r.top10, r.n_5pct, r.identiques, r.prix, i.prix"
                     " FROM releve r JOIN issue i ON i.mint=r.mint AND i.delai_s=240"
                     " WHERE r.erreur IS NULL AND r.prix > 0").fetchall()
    y = [(p240 or 0) / p0 <= 0.5 for *_, p0, p240 in lanc]
    print("A. TOUS LES LANCEMENTS RELEVES : %d, dont %d vides a +240 s (%.1f %%)"
          % (len(lanc), sum(y), 100 * sum(y) / max(len(lanc), 1)))
    for k, nom in enumerate(("top1", "top5", "top10", "n_5pct", "identiques")):
        x = [row[k] for row in lanc]
        a = auc(x, y)
        if a is None:
            print("   %-10s trop peu de vidages pour mesurer" % nom)
            continue
        random.seed(k)
        perm = [auc(x, random.sample(y, len(y))) for _ in range(2000)]
        p = sum(1 for b in perm if b is not None and abs(b - .5) >= abs(a - .5)) / 2000
        print("   %-10s AUC %.3f (0,5 = rien) · hasard %.1f %%" % (nom, a, 100 * p))

    # --- B. le carnet papier du moteur : le filtre rapporte-t-il ? ---
    for meth in ("propre", "telegram"):
        T = [t for t in tickets_papier(m, d) if t["meth"] == meth]
        print("\nB. CARNET PAPIER %s : %d tickets releves" % (meth.upper(), len(T)))
        if len(T) < 2 * MIN_JUGEMENT:
            print("   TROP TOT : il en faut %d (%d par moitie). Rien n est conclu." % (2 * MIN_JUGEMENT, MIN_JUGEMENT))
            if T:
                a = resume([t["r"] for t in T])
                print("   (pour information seulement) niveau %+.3f · vides %.1f %%" % (a["moy"], 100 * a["vides"]))
            continue
        moit = len(T) // 2
        rech, jug = T[:moit], T[moit:]
        meilleur = max(SEUILS, key=lambda s: (resume([t["r"] for t in rech if not ecarte(t, s)]) or {"moy": -9})["moy"])
        print("   seuil choisi sur la RECHERCHE : plus gros portefeuille >= %.0f %% ou bundle" % (100 * meilleur))
        heures = max((T[-1]["ts_entree"] - T[0]["ts_entree"]) / 3600, 1e-9)
        for nom, part in (("recherche", rech), ("JUGEMENT", jug)):
            tout = resume([t["r"] for t in part])
            garde = resume([t["r"] for t in part if not ecarte(t, meilleur)])
            jete = resume([t["r"] for t in part if ecarte(t, meilleur)])
            print("   %-9s tout   n=%3d niveau %+.3f vides %4.1f %%" % (nom, tout["n"], tout["moy"], 100 * tout["vides"]))
            if garde:
                print("   %-9s GARDE  n=%3d niveau %+.3f sans best %+.3f vides %4.1f %%"
                      % ("", garde["n"], garde["moy"], garde["sans_best"], 100 * garde["vides"]))
            if jete:
                print("   %-9s jete   n=%3d niveau %+.3f vides %4.1f %%" % ("", jete["n"], jete["moy"], 100 * jete["vides"]))
        g = resume([t["r"] for t in jug if not ecarte(t, meilleur)])
        par_jour = (len([t for t in T if not ecarte(t, meilleur)]) / heures) * 24
        if g:
            print("   projection a %d EUR : %.0f tickets gardes par jour x %+.3f = %+.0f EUR par jour"
                  % (MISE, par_jour, g["moy"], par_jour * g["moy"] * MISE))
        go = g and g["n"] >= MIN_JUGEMENT // 2 and g["moy"] > 0 and g["sans_best"] > 0 and g["vides"] < POINT_MORT_VIDAGE
        print("   VERDICT : %s" % ("GO pour deux jours de confirmation EN PAPIER" if go else "NON"))


if __name__ == "__main__":
    main()
