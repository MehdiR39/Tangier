"""Choisir la fenetre de tendance EN LIGNE, sans que je la regle a la main (16/09, idee de l operateur).

POURQUOI. La tendance filtre les periodes perdantes, mais la bonne fenetre depend du regime : N=50 sur une
periode, N=20 sur une autre. Jusqu ici c est moi qui choisissais apres avoir vu les resultats — le biais qui a
coute cher cette semaine (journal §3.90 : N choisi sur une moitie, perdant sur l autre dans les deux sens).

DEUX METHODES, toutes deux sans regard sur le futur :
  1. AGREGATION D EXPERTS a poids exponentiels avec Fixed Share (Herbster & Warmuth). Experts : tendance sur les
     N derniers resultats connus, N dans {5, 10, 20, 50, 100}, plus « sans filtre ». Apres chaque resultat connu,
     chaque expert est note sur ce qu il aurait gagne ou perdu sur ce ticket ; poids w <- w x exp(eta x gain),
     puis melange alpha vers la moyenne (c est ce melange qui permet de CHANGER d expert quand le regime change).
     On achete si le poids total des experts qui disent « achete » depasse 1/2.
  2. KALMAN : le rendement moyen du marche est un etat cache qui derive (marche aleatoire de variance q),
     observe avec un bruit r estime sur les residus. Le gain de Kalman donne une moyenne mobile dont la vitesse
     s ajuste seule. On achete si l etat estime est > 0.
GARANTIE : l agregation ne promet pas de gagner, seulement de ne pas faire bien pire que le meilleur expert choisi
apres coup (regret en racine de T). Si tous les experts perdent, elle perd aussi.

MESURE : decisions a 45 s (+2 s), sortie 240 s, prix du collecteur, cout reel mesure 2,62 pts, 30 EUR par ticket.
Le resultat d un ticket n est connu qu a 45 + 2 + 240 s : les poids ne sont mis a jour qu a ce moment-la.
Temoins : sans filtre, et la tendance figee N=50.

Usage : `python -m intel.research.tendance_en_ligne [--depuis AAAA-MM-JJ]` (rejoue sur les donnees du collecteur).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sqlite3
import sys
from bisect import bisect_right, insort

import numpy as np

ICI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(os.path.abspath(os.path.join(ICI, "..", "..")), "data", "recherche")
NS = (5, 10, 20, 50, 100)
COUT = 0.0262
MISE_EUR = 30.0
PLAFOND = 3.0
ETA = 2.0          # ardeur de l apprentissage (gains de l ordre de 0,1 : eta x gain reste petit)
ALPHA = 0.02       # part melangee a chaque pas : permet de changer d expert quand le regime change


def decisions(depuis):
    """Une decision par pool : entree 47 s, sortie 287 s, prix (coffre SOL + reserve virtuelle) / jetons."""
    src = os.path.join(D, "v1_prix_frais2.jsonl")
    pools = {}
    if os.path.exists(src):
        for l in open(src, encoding="utf-8"):
            pair, ts, age, p, qv = json.loads(l)
            pools.setdefault(pair, []).append((age, ts, p, qv))
    else:
        c = sqlite3.connect("file:%s/archive_solana.sqlite?mode=ro" % D, uri=True, timeout=120)
        for pair, ts, age, xb, xs, v in c.execute(
                "SELECT pair_id, ts, age_s, reserve_base, reserve_sol, reserve_virtuelle FROM solana_prix_chaine"
                " WHERE ts >= ? AND reserve_base > 0 ORDER BY pair_id, ts", (depuis,)):
            if v is None or not xb:
                continue
            pools.setdefault(pair, []).append((age, ts, (xs + v) / xb, xs + v))
    out = []
    for pair, pts in pools.items():
        pts.sort()
        if pts[0][0] > 20 or len(pts) < 6:
            continue
        ages = [p[0] for p in pts]

        def a_age(cible, tol):
            i = bisect_right(ages, cible)
            best = None
            for j in (i - 1, i):
                if 0 <= j < len(ages) and abs(ages[j] - cible) <= tol and (best is None or abs(ages[j] - cible) < abs(ages[best] - cible)):
                    best = j
            return best

        e, s = a_age(47, 6), a_age(287, 8)
        if e is None or s is None or s <= e or pts[e][2] <= 0 or 0.31 / pts[e][3] > 0.15:
            continue
        t = pts[0][1] - pts[0][0] + 45
        if t < depuis:
            continue
        out.append({"t": t, "fin": t + 242, "net": min(pts[s][2] / pts[e][2] - 1, PLAFOND) - COUT})
    out.sort(key=lambda z: z["t"])
    return out


def rejouer(dec):
    """Rejoue en ligne : a chaque decision on ne connait que les tickets deja termines."""
    poids = np.ones(len(NS) + 1) / (len(NS) + 1)          # experts N..., puis « sans filtre »
    connus: list = []                                      # resultats termines, tries par heure de fin
    attente: list = []                                     # tickets en cours (fin, net)
    x, P, q, r = 0.0, 0.01, 2e-4, 0.05                     # Kalman : etat, variance, bruit d etat, bruit d obs
    res = {"agregation": [], "kalman": [], "sans filtre": [], "N=50 fige": [], "poids": []}
    for d in dec:
        while attente and attente[0][0] <= d["t"]:
            fin, net = attente.pop(0)
            # notation des experts SUR CE TICKET, avec ce qu ils savaient AU MOMENT de cette decision
            gains = np.array([net if a else 0.0 for a in gardes_pour(connus, fin - 242)] + [net])
            insort(connus, (fin, net))
            poids = poids * np.exp(ETA * gains)
            poids = poids / poids.sum()
            poids = (1 - ALPHA) * poids + ALPHA / len(poids)
            P += q
            K = P / (P + r)
            x += K * (net - x)
            P = (1 - K) * P
        gardes = gardes_pour(connus, d["t"]) + [True]
        part = float(poids[np.array(gardes)].sum())
        res["agregation"].append(d["net"] if part > 0.5 else 0.0)
        res["kalman"].append(d["net"] if x > 0 else 0.0)
        res["sans filtre"].append(d["net"])
        res["N=50 fige"].append(d["net"] if gardes[NS.index(50)] else 0.0)
        res["poids"].append(poids.copy())
        attente.append((d["fin"], d["net"]))
        attente.sort()
    return res


def gardes_pour(connus, t):
    """Pour chaque expert N : la moyenne des N derniers resultats connus avant t est-elle > 0 ?"""
    vals = [v for f, v in connus if f <= t]
    out = []
    for N in NS:
        out.append(bool(len(vals) >= N and np.mean(vals[-N:]) > 0))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--depuis", default="2026-09-15")
    a = ap.parse_args()
    depuis = int(dt.datetime.strptime(a.depuis, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc).timestamp())
    dec = decisions(depuis)
    if len(dec) < 50:
        print("pas assez de decisions (%d)" % len(dec))
        return
    res = rejouer(dec)
    print("decisions rejouees : %d · du %s au %s (Paris)" % (
        len(dec), *[dt.datetime.fromtimestamp(z + 7200, dt.timezone.utc).strftime("%d/%m %Hh%M") for z in (dec[0]["t"], dec[-1]["t"])]))
    print("\n%-16s %8s %10s %10s %12s" % ("methode", "tickets", "moyenne", "EUR", "moities EUR"))
    mil = len(dec) // 2
    for nom in ("sans filtre", "N=50 fige", "agregation", "kalman"):
        v = np.array(res[nom])
        n = int((v != 0).sum())
        print("%-16s %8d %9.2f %% %+9.0f %+6.0f / %+6.0f" % (
            nom, n, 100 * (v[v != 0].mean() if n else np.nan), MISE_EUR * v.sum(), MISE_EUR * v[:mil].sum(), MISE_EUR * v[mil:].sum()))
    P = np.array(res["poids"])
    print("\npoids moyens des experts : " + " · ".join("N=%d %.2f" % (N, P[:, i].mean()) for i, N in enumerate(NS))
          + " · sans filtre %.2f" % P[:, -1].mean())
    print("poids en fin de periode  : " + " · ".join("N=%d %.2f" % (N, P[-1, i]) for i, N in enumerate(NS))
          + " · sans filtre %.2f" % P[-1, -1])


if __name__ == "__main__":
    main()
