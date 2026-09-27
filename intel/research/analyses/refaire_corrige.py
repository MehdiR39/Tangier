"""Refaire les tests qui comptent, avec les prix CORRIGES (15/09).

Prix = (reserve_sol + reserve virtuelle) / reserve_base, lectures decalees de 12 s (voir
calibration_corrigee.py). Simulateur calibre sur 236 tickets reels : ecart reel - corrige = -2,4
points par ticket en mediane. Couts appliques : 2,5 points (le bot tel qu il est) et 2,0 points
(depot du compte de jetons recupere).

Le moteur decide a T+A avec ce qu il voit (lectures etiquetees <= T+A, donc l etat de T+A-12 s), et
son ordre s execute vers T+A+2 s : prix d entree = etat de T+A+2, lu sur l etiquette T+A+14.

REGLE DE DECISION, identique a tous les tests du jour : sur la moitie de JUGEMENT (par date de
naissance) niveau apres cout >= +0,011, sans son meilleur ticket > 0, et niveau > 0 sur la RECHERCHE.
La grille (groupe x age d entree x duree) est petite et affichee en entier : on lit la ligne
« en place » (60 s, 240 s) d abord, le reste est exploratoire.
"""
from __future__ import annotations

import json
import os
import sqlite3
import statistics as st
from collections import defaultdict

D = "/app/data/recherche"
RETARD_S = 12
EXEC_S = 2
V_PUMP = 17.5845
COUTS = (0.025, 0.020)
AGES = (30, 60, 90)
DUREES = (60, 120, 240, 480)


def charger():
    c = sqlite3.connect("file:%s?mode=ro" % os.path.join(D, "archive_solana.sqlite"), uri=True, timeout=60)
    V = json.load(open(os.path.join(D, "reserve_virtuelle.json")))
    marque = {m: t for m, t in c.execute("SELECT mint, telegram FROM tg_juges")}
    chemins = defaultdict(list)
    for pair, mint, ts, age, xb, xs in c.execute(
            "SELECT p.pair_id, p.mint, p.ts, p.age_s, p.reserve_base, p.reserve_sol FROM solana_prix_chaine p"
            " JOIN pool_quote q ON q.pool=p.pair_id AND q.est_sol=1 WHERE p.prix_sol > 0 ORDER BY p.pair_id, p.ts"):
        v = V.get(pair)
        if v is None or (v != 0 and abs(v - V_PUMP) > 0.001) or not xb:
            continue
        chemins[pair].append({"mint": mint, "ts": ts, "vrai_age": age - RETARD_S, "p": (xs + v) / xb, "xs": xs})
    return marque, chemins


def proche(pts, age, tol=8):
    r = min(pts, key=lambda x: abs(x["vrai_age"] - age), default=None)
    return r if r and abs(r["vrai_age"] - age) <= tol else None


def tickets(marque, chemins, age_decision, duree):
    out = []
    for pair, pts in chemins.items():
        mint = pts[0]["mint"]
        if mint not in marque or pts[0]["vrai_age"] > 20:
            continue
        vus = [x for x in pts if x["vrai_age"] <= age_decision - RETARD_S]     # ce que le moteur voit
        if len(vus) < 3:
            continue
        p0, l0, pe_vu = vus[0]["p"], vus[0]["xs"] or 0, vus[-1]
        signes = (int(pe_vu["p"] / p0 - 1 >= 0.007) + int(min(x["p"] for x in vus) / p0 - 1 >= 0)
                  + int(((pe_vu["xs"] / l0 - 1) if l0 > 0 else 0) >= 0.0035))
        groupe = "telegram" if marque[mint] else ("propre" if signes == 3 else "autre")
        e = proche(pts, age_decision + EXEC_S)
        s = proche(pts, age_decision + EXEC_S + duree, tol=12)
        if not e or not s or not e["xs"] or 0.31 / e["xs"] > 0.15:
            continue
        out.append({"g": groupe, "nais": pts[0]["ts"] - pts[0]["vrai_age"], "r": s["p"] / e["p"] - 1})
    return sorted(out, key=lambda t: t["nais"])


def ligne(v, cout):
    if len(v) < 20:
        return None
    s = sorted((x - cout for x in v), reverse=True)
    return st.mean(s), st.mean(s[1:]), sum(1 for x in v if x <= -0.5) / len(v)


def main():
    marque, chemins = charger()
    print("pools a prix corrige : %d" % len(chemins))
    for groupe in ("propre", "telegram", "autre"):
        print("\n" + "=" * 110 + "\n%s" % groupe.upper())
        print("  %-5s %-6s %5s %9s  %-28s %-28s %-8s %s" % ("age", "duree", "n/j", "brut", "RECHERCHE (cout 2,5 / 2,0)", "JUGEMENT (cout 2,5 / 2,0)", "vides", "verdict (cout 2,0)"))
        for age in AGES:
            for duree in DUREES:
                T = [t for t in tickets(marque, chemins, age, duree) if t["g"] == groupe]
                if len(T) < 60:
                    continue
                h = len(T) // 2
                jours = max((T[-1]["nais"] - T[0]["nais"]) / 86400, 1e-9)
                R = [t["r"] for t in T[:h]]
                J = [t["r"] for t in T[h:]]
                r25, r20, j25, j20 = ligne(R, .025), ligne(R, .020), ligne(J, .025), ligne(J, .020)
                ok = r20 and j20 and j20[0] >= 0.011 and j20[1] > 0 and r20[0] > 0
                marque_ligne = "  <- EN PLACE" if (age == 60 and duree == 240) else ""
                print("  %4ds %5ds %5.0f %+9.4f  %+.4f / %+.4f (sb %+.3f)   %+.4f / %+.4f (sb %+.3f)   %4.1f %%   %s%s" % (
                    age, duree, len(T) / jours, st.mean(t["r"] for t in T), r25[0], r20[0], r20[1], j25[0], j20[0], j20[1],
                    100 * sum(1 for t in T if t["r"] <= -0.5) / len(T), "ATTEINT" if ok else "non", marque_ligne))


if __name__ == "__main__":
    main()
