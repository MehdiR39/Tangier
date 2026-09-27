"""Verdict historique : ecarter les jetons ou un portefeuille a recu un gros « sac » a la migration.

REGLES FIGEES LE 15/09 AVANT D AVOIR LE RESULTAT (voir premieres_secondes.py pour la mesure).

  variable     sac1 = plus grosse position nette d un PORTEFEUILLE a T+30 s (achat de fin de courbe
               ou transfert a la migration), en part de l offre. Connue avant l entree a T+60 s.
  populations  (1) SIMULEE : tous les jetons du coffre, regle du moteur rejouee -- entree a la lecture
                   la plus proche de T+60 s (45-90 s), sortie a +240 s, cout d execution REEL mesure
                   en chaine (propre 0,010, telegram 0,079 par euro). Groupes propre / telegram.
               (2) REELLE : nos tickets en argent reel, gain lu sur le portefeuille.
  vidage       r <= -0,5.
  coupure      par date de naissance : premiere moitie = RECHERCHE, seconde = JUGEMENT.
  filtre       ecarter si sac1 >= S, S parmi {5, 10, 20, 30, 50, 70 %}, choisi sur la RECHERCHE
               (meilleur niveau apres cout), juge sur le JUGEMENT.
  decision     GO seulement si sur le JUGEMENT : niveau garde > 0, sans son meilleur ticket > 0,
               vidages gardes < 11,9 %. Un GO n engage pas d argent.
  objectif     50 EUR/jour a 30 EUR le ticket : tickets gardes par jour x niveau x 30.
"""
from __future__ import annotations

import json
import os
import sqlite3
import statistics as st

COFFRE = os.environ.get("COFFRE", "/app/data/recherche/archive_solana.sqlite")
SACS = os.environ.get("SACS", "/app/data/recherche/sacs_migration.jsonl")
COUT = {"propre": 0.010, "telegram": 0.079}
SEUILS = (0.05, 0.10, 0.20, 0.30, 0.50, 0.70)
MISE = 30.0


def sacs(c):
    offre = {m: float(o) for m, o in c.execute("SELECT mint, offre FROM mint_offre") if o}
    out = {}
    for ligne in open(SACS, encoding="utf-8"):
        d = json.loads(ligne)
        if d.get("erreur") or not d.get("instants"):
            continue
        s = offre.get(d["mint"], 1e9)
        pos = [q / s for _, q in d["instants"].get("30", [])]
        out[d["mint"]] = {"sac1": max(pos) if pos else 0.0, "naissance": d["naissance"], "tronque": d["tronque"]}
    return out


def simules(c):
    marque = {m: t for m, t in c.execute("SELECT mint, telegram FROM tg_juges")}
    courbes = {}
    for r in c.execute("""SELECT p.mint, p.ts, p.age_s, p.prix_sol, p.reserve_sol FROM solana_prix_chaine p
                          JOIN pool_quote q ON q.pool=p.pair_id AND q.est_sol=1 WHERE p.prix_sol>0
                          ORDER BY p.mint, p.age_s"""):
        if r[0] in marque:
            courbes.setdefault(r[0], []).append(r)
    out = []
    for m, pts in courbes.items():
        av = [x for x in pts if x[2] <= 90]
        e = min((x for x in pts if 45 <= x[2] <= 90), key=lambda x: abs(x[2] - 60), default=None)
        if len(av) < 3 or not e or not e[4] or 0.31 / e[4] > 0.15:
            continue
        p0, l0 = av[0][3], av[0][4] or 0
        signes = (int(e[3] / p0 - 1 >= 0.007) + int(min(x[3] for x in av) / p0 - 1 >= 0)
                  + int(((e[4] / l0 - 1) if l0 > 0 else 0) >= 0.0035))
        groupe = "telegram" if marque[m] else ("propre" if signes == 3 else None)
        if not groupe:
            continue
        s = min((x for x in pts if x[2] > e[2]), key=lambda x: abs(x[2] - (e[2] + 240)), default=None)
        if not s or abs(s[2] - (e[2] + 240)) > 45:
            continue
        out.append({"mint": m, "groupe": groupe, "ts": e[1], "r": s[3] / e[3] - 1 - COUT[groupe]})
    return out


def reels(c):
    return [{"mint": m, "groupe": g or "telegram", "ts": ts, "r": gain / mise, "gain": gain}
            for m, g, ts, gain, mise in c.execute(
                "SELECT mint, methode, ts_entree, gain_eur, mise_eur FROM tg_lignes"
                " WHERE mode='live' AND gain_eur IS NOT NULL AND methode IN ('propre','telegram')")]


def resume(v):
    if not v:
        return None
    s = sorted(v, reverse=True)
    return {"n": len(v), "moy": st.mean(v), "sb": st.mean(s[1:]) if len(s) > 1 else float("nan"),
            "vides": sum(1 for x in v if x <= -0.5) / len(v)}


def auc(x, y):
    n1 = sum(y)
    n0 = len(y) - n1
    if n1 < 5 or n0 < 5:
        return None
    ordre = sorted(range(len(x)), key=lambda i: x[i])
    rangs = [0.0] * len(x)
    i = 0
    while i < len(ordre):
        j = i
        while j < len(ordre) and x[ordre[j]] == x[ordre[i]]:
            j += 1
        for k in range(i, j):
            rangs[ordre[k]] = (i + j + 1) / 2
        i = j
    return (sum(r for r, b in zip(rangs, y) if b) - n1 * (n1 + 1) / 2) / (n1 * n0)


def juger(nom, T, S):
    T = sorted([dict(t, **S[t["mint"]]) for t in T if t["mint"] in S], key=lambda t: t["naissance"])
    print("\n" + "=" * 96)
    print("%s : %d jetons avec leur sac reconstruit" % (nom, len(T)))
    if len(T) < 40:
        print("   trop peu")
        return
    y = [t["r"] <= -0.5 for t in T]
    a = auc([t["sac1"] for t in T], y)
    print("   vidages %d (%.1f %%) · AUC du sac1 pour le vidage : %s" % (sum(y), 100 * sum(y) / len(T), ("%.3f" % a) if a else "n/a"))
    print("   sac1 median : vides %.1f %% · autres %.1f %%" % (
        100 * st.median([t["sac1"] for t in T if t["r"] <= -0.5] or [0]), 100 * st.median([t["sac1"] for t in T if t["r"] > -0.5] or [0])))
    moit = len(T) // 2
    rech, jug = T[:moit], T[moit:]
    choix = max(SEUILS, key=lambda s: (resume([t["r"] for t in rech if t["sac1"] < s]) or {"moy": -9})["moy"])
    print("   seuil choisi sur la RECHERCHE : ecarter si sac1 >= %.0f %%" % (100 * choix))
    for lib, part in (("recherche", rech), ("JUGEMENT", jug)):
        tout, garde, jete = (resume([t["r"] for t in part]), resume([t["r"] for t in part if t["sac1"] < choix]),
                             resume([t["r"] for t in part if t["sac1"] >= choix]))
        print("   %-9s tout  n=%4d niveau %+.3f vides %4.1f %%" % (lib, tout["n"], tout["moy"], 100 * tout["vides"]))
        if garde:
            print("   %-9s GARDE n=%4d niveau %+.3f sans best %+.3f vides %4.1f %%" % ("", garde["n"], garde["moy"], garde["sb"], 100 * garde["vides"]))
        if jete:
            print("   %-9s jete  n=%4d niveau %+.3f vides %4.1f %%" % ("", jete["n"], jete["moy"], 100 * jete["vides"]))
    g = resume([t["r"] for t in jug if t["sac1"] < choix])
    jours = max((T[-1]["naissance"] - T[0]["naissance"]) / 86400, 1e-9)
    n_jour = len([t for t in T if t["sac1"] < choix]) / jours
    if g:
        print("   projection : %.0f tickets gardes par jour x %+.3f x %d EUR = %+.0f EUR par jour" % (n_jour, g["moy"], MISE, n_jour * g["moy"] * MISE))
    go = bool(g) and g["moy"] > 0 and g["sb"] > 0 and g["vides"] < 0.119
    print("   VERDICT : %s" % ("GO pour confirmation EN PAPIER" if go else "NON"))
    if "gain" in T[0]:
        tot = sum(t["gain"] for t in T)
        garde = sum(t["gain"] for t in T if t["sac1"] < choix)
        print("   argent reel de ces tickets : %+.2f EUR · avec le filtre : %+.2f EUR" % (tot, garde))


def main():
    c = sqlite3.connect("file:%s?mode=ro" % COFFRE, uri=True, timeout=60)
    S = sacs(c)
    print("sacs reconstruits : %d" % len(S))
    sim = simules(c)
    for g in ("propre", "telegram"):
        juger("SIMULE %s" % g.upper(), [t for t in sim if t["groupe"] == g], S)
    re = reels(c)
    for g in ("propre", "telegram"):
        juger("REEL %s" % g.upper(), [t for t in re if t["groupe"] == g], S)


if __name__ == "__main__":
    main()
