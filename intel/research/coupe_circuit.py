"""Coupe-circuit reactif : apres une grosse perte, on s arrete un moment, puis on revient (idee de l operateur, 16/09).

Difference avec le filtre de tendance : celui-ci moyenne les 50 derniers resultats et met une a deux heures a
changer d avis (§3.90). Ici on reagit au DERNIER resultat connu, donc en cinq minutes.

DONNEES  transactions des 2 979 pools (09 -> 15/09) + collecteur pour le 15-16/09 n est PAS inclus ici : on juge
         sur les transactions reelles, tous les pools, entree 47 s.
SORTIES  heure fixe 287 s, et prise de gain +25 % (vente 2 s apres le declenchement), cout reel 2,62 pts, 30 EUR.
REGLES   un resultat n est connu qu a l instant naissance + 47 + 240 + 2 s. Quand un resultat arrive :
         - « grosse perte » : si net <= -Z % (Z = 30, 50), on ne prend plus de decision pendant P minutes ;
         - « series » : si les k derniers resultats connus sont negatifs (k = 2, 3), pause de P minutes.
         P dans {10, 30, 60} minutes. Temoins : sans coupe-circuit, et filtre de tendance N=50.
MESURE   3 premiers jours (09-11/09) et 3 derniers (13-15/09) separement, pour voir si la regle tient quand le
         marche se degrade.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from bisect import bisect_right

import numpy as np

ICI = os.path.dirname(os.path.abspath(__file__))
D = os.path.join(os.path.abspath(os.path.join(ICI, "..", "..")), "data", "recherche", "copie")
COUT, MISE, PLAFOND, TP, RETARD = 0.0262, 30.0, 3.0, 0.25, 2.0


def charger():
    tickets = []
    for ligne in open(os.path.join(D, "echanges.jsonl"), encoding="utf-8"):
        d = json.loads(ligne)
        if d.get("erreur") or not d.get("echanges"):
            continue
        e = [x for x in d["echanges"] if x[2] and x[0] <= 320]
        if len(e) < 5:
            continue
        ages = [x[0] for x in e]
        prix = [x[2] for x in e]
        q = [x[3] + d["V"] for x in e]

        def idx(t):
            i = bisect_right(ages, t) - 1
            return i if i >= 0 else None

        i0, fin = idx(47), idx(287)
        if i0 is None or fin is None or fin <= i0 or prix[i0] <= 0 or 0.31 / q[i0] > 0.15:
            continue
        pe = prix[i0]
        fixe = min(prix[fin] / pe - 1, PLAFOND) - COUT
        tp = None
        for i in range(i0 + 1, fin + 1):
            if prix[i] >= pe * (1 + TP):
                j = idx(ages[i] + RETARD)
                j = min(j if j is not None else i, fin)
                tp = min(prix[j] / pe - 1, PLAFOND) - COUT
                break
        if tp is None:
            tp = fixe
        tickets.append({"t": d["naissance"] + 45, "fin": d["naissance"] + 289, "fixe": fixe, "tp": tp,
                        "jour": dt.datetime.fromtimestamp(d["naissance"] + 7200, dt.timezone.utc).strftime("%d/%m")})
    tickets.sort(key=lambda z: z["t"])
    return tickets


def rejouer(tickets, cle, decl, pause_s):
    """Rejeu chronologique : on connait un resultat a `fin`, la pause s applique aux decisions suivantes."""
    pris, attente, connus = [], [], []
    pause_jusqu_a = 0.0
    i = 0
    for tk in tickets:
        while i < len(attente):
            break
        # resultats devenus connus avant cette decision
        while attente and attente[0]["fin"] <= tk["t"]:
            r = attente.pop(0)
            connus.append(r[cle])
            if decl(connus):
                pause_jusqu_a = max(pause_jusqu_a, r["fin"] + pause_s)
        if tk["t"] >= pause_jusqu_a:
            pris.append(tk)
        attente.append(tk)
        attente.sort(key=lambda z: z["fin"])
    return pris


def stats(v, cle):
    y = np.array([t[cle] for t in v], float)
    if len(y) < 10:
        return "%4d tickets · -" % len(y)
    sb = np.sort(y)[::-1]
    return "%4d tickets · %+6.2f %% · %+6.0f EUR · sans best %+6.2f %%" % (
        len(y), 100 * y.mean(), MISE * y.sum(), 100 * sb[1:].mean())


def main():
    tickets = charger()
    debut = [t for t in tickets if t["jour"] in ("09/09", "10/09", "11/09")]
    fin = [t for t in tickets if t["jour"] in ("13/09", "14/09", "15/09")]
    print("tickets : %d (3 premiers jours %d · 3 derniers %d)" % (len(tickets), len(debut), len(fin)))
    regles = [("sans coupe-circuit", lambda c: False, 0)]
    for Z in (0.30, 0.50):
        for P in (10, 30, 60):
            regles.append(("perte <= -%d %% -> pause %d min" % (100 * Z, P), lambda c, Z=Z: c and c[-1] <= -Z, P * 60))
    for k in (2, 3):
        for P in (10, 30, 60):
            regles.append(("%d pertes de suite -> pause %d min" % (k, P), lambda c, k=k: len(c) >= k and all(x < 0 for x in c[-k:]), P * 60))
    for cle in ("fixe", "tp"):
        print("\nSORTIE %s" % ("heure fixe 287 s" if cle == "fixe" else "prise de gain +25 %"))
        print("  %-34s %-46s %-46s" % ("regle", "3 PREMIERS JOURS", "3 DERNIERS JOURS"))
        for nom, decl, pause in regles:
            pd_ = rejouer(debut, cle, decl, pause)
            pf_ = rejouer(fin, cle, decl, pause)
            print("  %-34s %-46s %-46s" % (nom, stats(pd_, cle), stats(pf_, cle)))


if __name__ == "__main__":
    main()


def combinaisons():
    """Les trois effets ensemble : prise de gain, pause apres grosse perte, et jetons peu encombres."""
    import datetime as dt
    tickets = charger_riches()
    debut = [t for t in tickets if t["jour"] in ("09/09", "10/09", "11/09")]
    fin = [t for t in tickets if t["jour"] in ("13/09", "14/09", "15/09")]
    pause = lambda c: bool(c) and c[-1] <= -0.30
    combos = [("tout, heure fixe", lambda t: True, "fixe", None),
              ("tout, prise de gain", lambda t: True, "tp", None),
              ("+ pause 30 min", lambda t: True, "tp", pause),
              ("+ peu encombre (<= 74 acheteurs)", lambda t: t["acheteurs"] <= 74, "tp", pause),
              ("+ tres calme (<= 25 acheteurs)", lambda t: t["acheteurs"] <= 25, "tp", pause),
              ("+ coffre < 100 SOL", lambda t: t["acheteurs"] <= 74 and t["q0"] < 100, "tp", pause)]
    print("\nCOMBINAISONS (cout reel, 30 EUR par ticket)")
    print("  %-36s %-34s %-34s" % ("regle", "3 PREMIERS JOURS", "3 DERNIERS JOURS"))
    for nom, filtre, cle, decl in combos:
        sorties = []
        for periode in (debut, fin):
            sel = [t for t in periode if filtre(t)]
            pris = rejouer(sel, cle, decl, 1800) if decl else sel
            y = np.array([t[cle] for t in pris], float)
            sorties.append("%4d tickets · %+6.2f %% · %+6.0f EUR" % (len(y), 100 * y.mean() if len(y) else np.nan,
                                                                    MISE * y.sum() if len(y) else 0))
        print("  %-36s %-34s %-34s" % (nom, *sorties))


def charger_riches():
    tickets = []
    for ligne in open(os.path.join(D, "echanges.jsonl"), encoding="utf-8"):
        d = json.loads(ligne)
        if d.get("erreur") or not d.get("echanges"):
            continue
        e = [x for x in d["echanges"] if x[2] and x[0] <= 320]
        if len(e) < 5:
            continue
        ages = [x[0] for x in e]
        prix = [x[2] for x in e]
        q = [x[3] + d["V"] for x in e]

        def idx(t):
            i = bisect_right(ages, t) - 1
            return i if i >= 0 else None

        i0, fin_ = idx(47), idx(287)
        if i0 is None or fin_ is None or fin_ <= i0 or prix[i0] <= 0 or 0.31 / q[i0] > 0.15:
            continue
        pe = prix[i0]
        fixe = min(prix[fin_] / pe - 1, PLAFOND) - COUT
        tp = None
        for i in range(i0 + 1, fin_ + 1):
            if prix[i] >= pe * (1 + TP):
                j = idx(ages[i] + RETARD)
                j = min(j if j is not None else i, fin_)
                tp = min(prix[j] / pe - 1, PLAFOND) - COUT
                break
        if tp is None:
            tp = fixe
        tickets.append({"t": d["naissance"] + 45, "fin": d["naissance"] + 289, "fixe": fixe, "tp": tp,
                        "q0": q[0], "acheteurs": len({o for x in e[:i0 + 1] for o, dt_, s in x[4] if dt_ > 0}),
                        "jour": dt.datetime.fromtimestamp(d["naissance"] + 7200, dt.timezone.utc).strftime("%d/%m")})
    tickets.sort(key=lambda z: z["t"])
    return tickets
