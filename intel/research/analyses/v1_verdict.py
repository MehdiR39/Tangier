"""Verdict de la piste « transactions version 1 », PRE-ENREGISTRE le 15/09 a 23h (journal §3.90), avant toute donnee du 16/09.

REGLES, figees : sur les pools nes apres le 16/09 00h (Paris), enregistres par `v1_enregistreur.py` (60 premieres
secondes, `maxSupportedTransactionVersion: 1`) :
  A  au moins une transaction reussie de version 1 sur le pool AVANT 45 s ;
  B  A ET au moins 257 echanges avant 45 s (le tiers le plus actif du 15/09) ;
  C  A ET tendance > 0 (moyenne des 50 derniers resultats connus), comparee a « tendance seule ».
RENDEMENT  prix du collecteur (correlation 0,987 avec les transactions, verifiee le 15/09) : entree a la lecture la
  plus proche de 47 s, sortie a 287 s, ordre de 0,31 SOL refuse au-dela de 15 % du pool.
COUT  reel mesure sur les 236 tickets du bot : 2,62 points par ticket. Mise 30 EUR.
VERDICT quand A atteint 150 pools : GO si moyenne >= +1,1 %, sans le meilleur > 0, et les deux moities (par date)
  positives. Le temoin « sans version 1 » est donne a cote. Tout en euros, tous frais compris.
"""
from __future__ import annotations

import datetime as dt
import glob
import json
import os
import sqlite3
import sys
from bisect import bisect_right

import numpy as np

ICI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RACINE = os.path.abspath(os.path.join(ICI, "..", ".."))
D = os.path.join(RACINE, "data", "recherche")
COUT = 0.0262
MISE_EUR = 30.0
MISE_SOL = 0.31
PLAFOND = 3.0
SEUIL_A = 150


def lectures():
    """Prix du collecteur. On prend l export frais de la base du moteur s il existe (l archive n est ecrite qu une
    fois par heure, ce qui retardait le verdict d autant), sinon l archive."""
    frais = os.path.join(D, "v1_prix_frais.jsonl")
    par = {}
    if os.path.exists(frais) and os.path.getmtime(frais) > os.path.getmtime(os.path.join(D, "archive_solana.sqlite")):
        for l in open(frais, encoding="utf-8"):
            pair, age, p, qv = json.loads(l)
            par.setdefault(pair, []).append((age, p, qv))
        return par
    c = sqlite3.connect("file:%s/archive_solana.sqlite?mode=ro" % D, uri=True, timeout=120)
    debut = int(dt.datetime(2026, 9, 15, 12, 0, tzinfo=dt.timezone.utc).timestamp())
    for pair, ts, age, xb, xs, v in c.execute(
            "SELECT pair_id, ts, age_s, reserve_base, reserve_sol, reserve_virtuelle FROM solana_prix_chaine"
            " WHERE ts >= ? AND reserve_base > 0 ORDER BY pair_id, ts", (debut,)):
        if v is None:
            continue
        par.setdefault(pair, []).append((age, (xs + v) / xb, xs + v))
    return par


def a_age(ages, cible, tol):
    i = bisect_right(ages, cible)
    best = None
    for j in (i - 1, i):
        if 0 <= j < len(ages) and abs(ages[j] - cible) <= tol and (best is None or abs(ages[j] - cible) < abs(ages[best] - cible)):
            best = j
    return best


def stats(v, t):
    v = np.asarray(v, float)
    if len(v) < 2:
        return None
    s = np.sort(v)[::-1]
    mil = np.median(t)
    h1, h2 = v[np.asarray(t) < mil], v[np.asarray(t) >= mil]
    return {"n": len(v), "moy": v.mean(), "sb1": s[1:].mean(), "eur": MISE_EUR * v.sum(),
            "h1": h1.mean() if len(h1) else np.nan, "h2": h2.mean() if len(h2) else np.nan,
            "gagnants": float((v > 0).mean())}


def dire(nom, s):
    if not s:
        print("  %-34s aucun" % nom)
        return
    print("  %-34s %3d pools · %+6.2f %% · sans le meilleur %+6.2f %% · gagnants %3.0f %% · moities %+6.2f / %+6.2f %% · %+6.0f EUR"
          % (nom, s["n"], 100 * s["moy"], 100 * s["sb1"], 100 * s["gagnants"], 100 * s["h1"], 100 * s["h2"], s["eur"]))


def main():
    par = lectures()
    lignes = []
    for f in sorted(glob.glob(os.path.join(D, "v1_avant", "*.jsonl"))):
        for l in open(f, encoding="utf-8"):
            d = json.loads(l)
            if d.get("erreur"):
                continue
            pts = par.get(d["pair"])
            if not pts:
                continue
            ages = [p[0] for p in pts]
            e, s = a_age(ages, 47, 6), a_age(ages, 287, 8)
            if e is None or s is None or s <= e or pts[e][1] <= 0:
                continue
            if MISE_SOL / pts[e][2] > 0.15:
                continue
            avant = [t for t in d["tx"] if t[0] <= 45]
            lignes.append({"t0": d["naissance"], "r": min(pts[s][1] / pts[e][1] - 1, PLAFOND) - COUT,
                           "A": any(t[1] == 1 for t in avant), "n_ech": sum(1 for t in avant if t[2])})
    if not lignes:
        print("aucun pool exploitable")
        return
    lignes.sort(key=lambda z: z["t0"])
    t = [z["t0"] for z in lignes]
    A = [z for z in lignes if z["A"]]
    print("pools enregistres et jugeables : %d · regle A : %d (seuil %d)" % (len(lignes), len(A), SEUIL_A))
    if len(A) < SEUIL_A:
        print("VERDICT PAS ENCORE : il manque %d pools pour la regle A." % (SEUIL_A - len(A)))
    groupes = [("A · version 1 avant 45 s", [z for z in lignes if z["A"]]),
               ("temoin · sans version 1", [z for z in lignes if not z["A"]]),
               ("B · A et >= 257 echanges", [z for z in lignes if z["A"] and z["n_ech"] >= 257]),
               ("temoin · >= 257 echanges sans v1", [z for z in lignes if not z["A"] and z["n_ech"] >= 257]),
               ("tous les pools", lignes)]
    print("\nentree 47 s, sortie 287 s, cout reel 2,62 pts, 30 EUR par ticket")
    res = {}
    for nom, g in groupes:
        s = stats([z["r"] for z in g], [z["t0"] for z in g]) if g else None
        res[nom] = s
        dire(nom, s)
    sA = res["A · version 1 avant 45 s"]
    if sA and len(A) >= SEUIL_A:
        go = sA["n"] >= SEUIL_A and sA["moy"] >= 0.011 and sA["sb1"] > 0 and sA["h1"] > 0 and sA["h2"] > 0
        print("\nVERDICT REGLE A : %s (moyenne %+.2f %%, sans le meilleur %+.2f %%, moities %+.2f / %+.2f %%)"
              % ("GO" if go else "NON", 100 * sA["moy"], 100 * sA["sb1"], 100 * sA["h1"], 100 * sA["h2"]))


if __name__ == "__main__":
    main()
