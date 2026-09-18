"""Sortir sur le FLUX plutot qu a l heure fixe, dans le sous-ensemble « tendance + pool non gonfle » (16/09).

POURQUOI. Toutes nos regles vendent a heure fixe. Or les effondrements sont concentres : tenir 8 min au lieu de
4 fait passer le meme sous-ensemble de +210 EUR a -1 649 EUR (balayage du 16/09). La question jamais testee ici :
sortir des qu une GROSSE VENTE arrive, ou des que le prix decroche de son plus haut, fait-il mieux que 4 min ?

DONNEES : data/recherche/copie/echanges.jsonl — chaque echange des 900 premieres secondes de 2 979 pools
(09/09 -> 15/09 05h47), prix a la transaction (verifie : correlation 0,987 avec le collecteur).
REGLES  entree au prix de la derniere transaction <= 47 s ; sous-ensemble : coffre (SOL + reserve virtuelle) a la
        premiere transaction < 100 SOL, et tendance > 0 = moyenne des 50 derniers resultats connus (decisions a
        60 s, sortie 302 s, cout reduit), tout calcule sur les memes donnees.
SORTIES comparees, toutes plafonnees a 287 s et executees a la transaction suivante + 2 s :
        - heure fixe 287 s (reference) ;
        - grosse vente : une vente unique >= X % du coffre (X = 2, 3, 5 %) ;
        - decrochage : prix <= -Y % du plus haut depuis l entree (Y = 15, 25, 40 %) ;
        - prise de gain : prix >= +Z % (Z = 20, 30, 50 %).
COUT    reel mesure sur les tickets du bot : 2,62 points. Mise 30 EUR. Rendements plafonnes a +300 %.
EXPLORATOIRE : meme periode que la decouverte. Toute regle qui sort d ici doit etre jugee sur des jours neufs.
"""
from __future__ import annotations

import json
import os
from bisect import bisect_right

import numpy as np

ICI = os.path.dirname(os.path.abspath(__file__))
D = os.path.join(os.path.abspath(os.path.join(ICI, "..", "..")), "data", "recherche", "copie")
COUT = 0.0262
MISE = 30.0
PLAFOND = 3.0
ENTREE, SORTIE_MAX, EXEC = 47.0, 287.0, 2.0
COFFRE_MAX = 100.0


def charger():
    pools = []
    for ligne in open(os.path.join(D, "echanges.jsonl"), encoding="utf-8"):
        d = json.loads(ligne)
        if d.get("erreur") or not d.get("echanges"):
            continue
        e = [x for x in d["echanges"] if x[2] and x[0] <= SORTIE_MAX + 20]
        if len(e) < 5:
            continue
        ages = np.array([x[0] for x in e], float)
        prix = np.array([x[2] for x in e], float)
        q = np.array([x[3] for x in e], float) + d["V"]
        vente = np.array([max([s for o, dt_, s in x[4] if dt_ < 0 and s > 0] or [0.0]) for x in e], float)
        pools.append({"naissance": d["naissance"], "ages": ages, "prix": prix, "q": q, "vente": vente})
    return pools


def a(ages, t):
    i = bisect_right(ages, t) - 1
    return i if i >= 0 else None


def main():
    pools = charger()
    print("pools lus : %d" % len(pools))
    # reference de tendance : decision 60 s, sortie 302 s, cout reduit, TOUS les pools
    ref = []
    for p in pools:
        e, s = a(p["ages"], 62), a(p["ages"], 302)
        if e is None or s is None or s <= e or p["prix"][e] <= 0 or 0.31 / p["q"][e] > 0.15:
            continue
        brut = min(p["prix"][s] / p["prix"][e] - 1, PLAFOND)
        ref.append((p["naissance"] + 302, brut - (0.0125 + 0.31 / p["q"][e])))
    ref.sort()
    fins = [r[0] for r in ref]
    cum = np.concatenate([[0.0], np.cumsum([r[1] for r in ref])])

    def reg(t, N=50):
        k = bisect_right(fins, t)
        return (cum[k] - cum[k - N]) / N if k >= N else np.nan

    sujets = []
    for p in pools:
        e = a(p["ages"], ENTREE)
        if e is None or p["prix"][e] <= 0 or 0.31 / p["q"][e] > 0.15:
            continue
        if p["q"][0] >= COFFRE_MAX:
            continue
        if not (reg(p["naissance"] + 45) > 0):
            continue
        sujets.append((p, e))
    print("tickets du sous-ensemble : %d" % len(sujets))

    def sortie(p, e, cond):
        """cond(i) -> True quand on veut sortir a la transaction i ; execution a la transaction suivante + 2 s."""
        fin = a(p["ages"], SORTIE_MAX)
        pe = p["prix"][e]
        haut = pe
        for i in range(e + 1, (fin or e) + 1):
            haut = max(haut, p["prix"][i])
            if cond(p, i, pe, haut):
                j = a(p["ages"], p["ages"][i] + EXEC) or i
                return min(p["prix"][min(j, fin or j)] / pe - 1, PLAFOND)
        return min(p["prix"][fin] / pe - 1, PLAFOND) if fin is not None and fin > e else np.nan

    regles = [("heure fixe 287 s", lambda p, i, pe, h: False)]
    for X in (0.02, 0.03, 0.05):
        regles.append(("grosse vente >= %d %% du coffre" % (100 * X), lambda p, i, pe, h, X=X: p["vente"][i] >= X * p["q"][i]))
    for Y in (0.15, 0.25, 0.40):
        regles.append(("decrochage -%d %% du plus haut" % (100 * Y), lambda p, i, pe, h, Y=Y: p["prix"][i] <= h * (1 - Y)))
    for Z in (0.20, 0.30, 0.50):
        regles.append(("prise de gain +%d %%" % (100 * Z), lambda p, i, pe, h, Z=Z: p["prix"][i] >= pe * (1 + Z)))
    print("\n%-34s %10s %10s %12s %10s" % ("sortie", "tickets", "moyenne", "sans best", "EUR"))
    for nom, cond in regles:
        y = np.array([r for r in (sortie(p, e, cond) for p, e in sujets) if not np.isnan(r)]) - COUT
        if len(y) < 20:
            continue
        sb = np.sort(y)[::-1]
        print("%-34s %10d %9.2f %% %11.2f %% %+9.0f" % (nom, len(y), 100 * y.mean(), 100 * sb[1:].mean(), MISE * y.sum()))


if __name__ == "__main__":
    main()


def general():
    """La prise de gain marche-t-elle hors du sous-ensemble ? Trois populations x trois sorties, plus le jour par jour."""
    import datetime as dt
    from collections import defaultdict
    pools = charger()
    ref = []
    for p in pools:
        e, s = a(p["ages"], 62), a(p["ages"], 302)
        if e is None or s is None or s <= e or p["prix"][e] <= 0 or 0.31 / p["q"][e] > 0.15:
            continue
        ref.append((p["naissance"] + 302, min(p["prix"][s] / p["prix"][e] - 1, PLAFOND) - (0.0125 + 0.31 / p["q"][e])))
    ref.sort()
    fins = [r[0] for r in ref]
    cum = np.concatenate([[0.0], np.cumsum([r[1] for r in ref])])

    def reg(t, N=50):
        k = bisect_right(fins, t)
        return (cum[k] - cum[k - N]) / N if k >= N else np.nan

    base = []
    for p in pools:
        e = a(p["ages"], ENTREE)
        if e is None or p["prix"][e] <= 0 or 0.31 / p["q"][e] > 0.15:
            continue
        base.append((p, e, bool(reg(p["naissance"] + 45) > 0), p["q"][0] < COFFRE_MAX))

    def res(sujets, cond):
        y = np.array([r for r in (sortie(p, e, cond) for p, e, _, _ in sujets) if not np.isnan(r)]) - COUT
        if len(y) < 20:
            return None
        sb = np.sort(y)[::-1]
        return len(y), 100 * y.mean(), 100 * sb[1:].mean(), MISE * y.sum()

    def sortie(p, e, cond):
        fin = a(p["ages"], SORTIE_MAX)
        pe = p["prix"][e]
        haut = pe
        for i in range(e + 1, (fin or e) + 1):
            haut = max(haut, p["prix"][i])
            if cond(p, i, pe, haut):
                j = a(p["ages"], p["ages"][i] + EXEC) or i
                return min(p["prix"][min(j, fin or j)] / pe - 1, PLAFOND)
        return min(p["prix"][fin] / pe - 1, PLAFOND) if fin is not None and fin > e else np.nan

    sorties = [("heure fixe 287 s", lambda p, i, pe, h: False),
               ("prise de gain +20 %", lambda p, i, pe, h: p["prix"][i] >= pe * 1.20),
               ("prise de gain +30 %", lambda p, i, pe, h: p["prix"][i] >= pe * 1.30)]
    pops = [("tous les pools", lambda s: True),
            ("tendance seule", lambda s: s[2]),
            ("coffre < 100 SOL seul", lambda s: s[3]),
            ("tendance + coffre < 100", lambda s: s[2] and s[3])]
    print("\n%-26s %-22s %10s %10s %11s %9s" % ("population", "sortie", "tickets", "moyenne", "sans best", "EUR"))
    for nomp, f in pops:
        sujets = [s for s in base if f(s)]
        for noms, cond in sorties:
            r = res(sujets, cond)
            if r:
                print("%-26s %-22s %10d %9.2f %% %10.2f %% %+9.0f" % (nomp, noms, *r))
    print("\nJOUR PAR JOUR : tendance + coffre < 100 SOL, prise de gain +20 %")
    sujets = [s for s in base if s[2] and s[3]]
    par_jour = defaultdict(list)
    for p, e, _, _ in sujets:
        r = sortie(p, e, lambda pp, i, pe, h: pp["prix"][i] >= pe * 1.20)
        if not np.isnan(r):
            par_jour[dt.datetime.fromtimestamp(p["naissance"] + 7200, dt.timezone.utc).strftime("%d/%m")].append(r - COUT)
    for j in sorted(par_jour, key=lambda s: (s[3:], s[:2])):
        v = np.array(par_jour[j])
        sb = np.sort(v)[::-1]
        print("  %-6s %+6.0f EUR (%3d tickets) · moyenne %+5.2f %% · sans best %+5.2f %%" % (
            j, MISE * v.sum(), len(v), 100 * v.mean(), 100 * sb[1:].mean() if len(v) > 1 else np.nan))


if __name__ == "__main__" and os.environ.get("SORTIES_GENERAL"):
    general()
