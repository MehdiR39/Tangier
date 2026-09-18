"""Ou en est la journee ? Une commande, les chiffres du jour, convention EXECUTABLE.

    python -m intel.research.journee            # aujourd hui
    python -m intel.research.journee --jour 15  # le 15 du mois en cours
    python -m intel.research.journee --tout     # toutes les journees disponibles

CE QUI EST CALCULE. Pour chaque pool enregistre par `v1_enregistreur` (ses 60 premieres secondes,
transaction par transaction) et suivi en prix par le moteur :
  entree   derniere lecture de prix <= 47 s ;
  sortie   premiere lecture >= entree x 1,25, puis vente a la premiere lecture au moins 2 s plus tard ;
           sinon lecture la plus proche de 287 s. Gain plafonne a +300 %.
  couts    2,62 points par ticket (calibration sur 236 tickets reels) ;
  ecarte   tout ticket ou notre ordre de 0,31 SOL depasse 15 % du coffre a l entree.

ATTENTION A CE QUE CE CHIFFRE EST. C est un BACKTEST rejoue sur la journee en cours, pas le resultat
d une decision prise en direct. Les tests geles (`papier_gd_direct`) sont les seuls qui prouvent
quelque chose ; celui-ci sert a suivre le marche, pas a valider une regle. Journal §3.96.
"""
from __future__ import annotations

import datetime as dt
import glob
import json
import os
import sqlite3
import sys
from bisect import bisect_right
from collections import defaultdict

BASE = os.environ.get("INTEL_DB", "/app/db/intel.sqlite")
V1_DIR = os.environ.get("V1_AVANT_DIR", "/app/data/recherche/v1_avant")
MISE, COUT, PLAFOND, TP, RETARD, ENTREE, SORTIE = 30.0, 0.0262, 3.0, 0.25, 2.0, 47.0, 287.0
FOULE_MAX, COFFRE_MAX, MISE_SOL, N_REGIME = 74, 100.0, 0.31, 50
PARIS = 7200          # UTC+2 en septembre ; l operateur raisonne en heure de Paris


def issues(serie):
    """(rendement avec prise de gain, rendement a heure fixe) ou None. serie = [(age, prix)] triee."""
    ages = [a for a, p in serie]
    i0, ifin = bisect_right(ages, ENTREE) - 1, bisect_right(ages, SORTIE) - 1
    if i0 < 0 or ifin <= i0 or serie[i0][1] <= 0:
        return None
    p0 = serie[i0][1]
    fixe = min(serie[ifin][1] / p0 - 1, PLAFOND) - COUT
    for k in range(i0 + 1, ifin + 1):
        if serie[k][1] >= p0 * (1 + TP):
            j = next((m for m in range(k, ifin + 1) if ages[m] >= ages[k] + RETARD), ifin)
            return min(serie[j][1] / p0 - 1, PLAFOND) - COUT, fixe
    return fixe, fixe


def charger(depuis):
    """Les tickets exploitables depuis `depuis`, prix lus dans la base du moteur."""
    c = sqlite3.connect("file:%s?mode=ro" % BASE, uri=True, timeout=120)
    prix = defaultdict(list)
    for pair, age, p, xs, v in c.execute(
            "SELECT pair_id, age_s, prix_sol, reserve_sol, reserve_virtuelle FROM solana_prix_chaine"
            " WHERE ts > ? AND reserve_virtuelle IS NOT NULL AND prix_sol > 0 ORDER BY pair_id, age_s",
            (depuis,)):
        prix[pair].append((age, p, (xs or 0.0) + (v or 0.0)))
    c.close()
    out = []
    for f in sorted(glob.glob(os.path.join(V1_DIR, "*.jsonl"))):
        for texte in open(f, encoding="utf-8"):
            o = json.loads(texte)
            if o.get("erreur") or not o.get("tx") or o["naissance"] < depuis:
                continue
            pts = sorted(set(prix.get(o["pair"], [])))
            av = [x for x in o["tx"] if 0 <= x[0] <= 45]
            if len(pts) < 6 or len(av) < 3:
                continue
            i = bisect_right([a for a, p, cf in pts], ENTREE) - 1
            if i < 0 or pts[i][2] <= 0 or MISE_SOL / pts[i][2] > 0.15:
                continue
            r = issues([(a, p) for a, p, cf in pts])
            c0 = next((x[3] for x in o["tx"] if x[3]), None)
            if not r or c0 is None:
                continue
            # de quoi juger AUSSI les autres regles du journal (A a K), avec la meme serie de prix
            pav = [p for a, p, cf in pts if a <= 45]
            pe = pts[i][1]
            flux = lambda a, b: sum(-s for x in av if a <= x[0] < b for p, dj, s in x[2] if dj > 0)
            out.append({"t": o["naissance"] + 45, "fin": o["naissance"] + 289, "r": r[0], "fixe": r[1],
                        "coffre0": c0 + (o.get("V") or 0),
                        "gens": len({p for x in av for p, dj, ds in x[2] if dj > 0 and p}),
                        "n45": len(av), "v1": any(x[1] == 1 for x in av),
                        "monte": (pe / pav[0] - 1) if pav else None,
                        "repli": (pe / max(pav) - 1) if pav else None,
                        "flux": flux(30, 45) >= flux(0, 15)})
    return sorted(out, key=lambda z: z["t"])


def tendance_de(tk):
    pf = sorted(tk, key=lambda z: z["fin"])
    fins = [x["fin"] for x in pf]
    cum = [0.0]
    for x in pf:
        cum.append(cum[-1] + x["fixe"])

    def tend(t):
        k = bisect_right(fins, t)
        return (cum[k] - cum[k - N_REGIME]) / N_REGIME if k >= N_REGIME else None
    return tend


def pause30(sel):
    pris, att, bl = [], [], 0.0
    for l in sel:
        att.sort(key=lambda z: z["fin"])
        while att and att[0]["fin"] <= l["t"]:
            f = att.pop(0)
            if f["r"] <= -0.30:
                bl = max(bl, f["fin"] + 1800)
        if l["t"] >= bl:
            pris.append(l)
        att.append(l)
    return pris


def afficher(nom, lot, tend):
    G = lambda x: x["gens"] <= FOULE_MAX and x["coffre0"] < COFFRE_MAX
    D = lambda x: (tend(x["t"]) or 0) > 0 and x["coffre0"] < COFFRE_MAX
    # Toutes les regles du journal, pour voir si une bonne journee l est pour tout le monde ou
    # seulement pour les notres. H (gros detenteur) est absente : la colonne `part` n existe pas
    # dans l archive, on ne peut pas la calculer honnetement.
    regles = [("temoin sans filtre", lambda x: True, False),
              ("E  prise de gain +25 %", lambda x: True, False),
              ("F  E + pause 30 min", lambda x: True, True),
              ("A  version 1 avant 45 s", lambda x: x["v1"], False),
              ("B  A + tres actif", lambda x: x["v1"] and x["n45"] >= 257, False),
              ("C  A + tendance", lambda x: x["v1"] and (tend(x["t"]) or 0) > 0, False),
              ("D  tendance + coffre", D, False),
              ("G  foule + coffre", G, True),
              ("I  repli apres course", lambda x: (x["monte"] or 0) >= 0.30 and (x["repli"] or 0) <= -0.15, True),
              ("J  G + flux soutenu", lambda x: G(x) and x["flux"], True),
              ("K  prix sous l ouverture", lambda x: (x["monte"] or 0) < 0, True),
              ("D+F  D + pause", D, True),
              ("G+D  melange", lambda x: G(x) and (tend(x["t"]) or 0) > 0, True)]
    if not lot:
        print("%-9s aucun ticket" % nom)
        return
    der = max(x["t"] for x in lot)
    print("%s · %d tickets · dernier a %s Paris"
          % (nom, len(lot), dt.datetime.fromtimestamp(der + PARIS, dt.timezone.utc).strftime("%H:%M")))
    for etiq, f, pause in regles:
        sel = [x for x in lot if f(x)]
        cle = "fixe" if etiq.startswith("temoin") else "r"      # le temoin sort a l heure, sans objectif
        pris = pause30(sel) if pause else sel
        if not pris:
            print("   %-24s aucun ticket" % etiq)
            continue
        y = [x[cle] for x in pris]
        s = sorted(y, reverse=True)
        sans = (100 * sum(s[1:]) / (len(s) - 1)) if len(s) > 1 else float("nan")
        print("   %-24s n=%4d · %+7.0f EUR · %+6.2f %% · sans best %+6.2f %% · gagnants %3.0f %%"
              % (etiq, len(y), MISE * sum(y), 100 * sum(y) / len(y), sans,
                 100 * sum(1 for x in y if x > 0) / len(y)))


def main():
    jour = None
    if "--jour" in sys.argv:
        jour = int(sys.argv[sys.argv.index("--jour") + 1])
    tout = "--tout" in sys.argv
    # 10 jours d historique suffisent : l enregistreur v1 ne remonte pas plus loin.
    tk = charger(dt.datetime.now(dt.timezone.utc).timestamp() - 10 * 86400)
    if not tk:
        print("aucun ticket : verifier que v1_enregistreur tourne et que la base a des prix")
        return
    tend = tendance_de(tk)
    par = defaultdict(list)
    for x in tk:
        par[dt.datetime.fromtimestamp(x["t"] + PARIS, dt.timezone.utc).strftime("%d/%m")].append(x)
    if tout:
        for j in sorted(par, key=lambda z: (z[3:], z[:2])):
            afficher(j, par[j], tend)
        return
    cible = ("%02d/%02d" % (jour, dt.datetime.now().month) if jour
             else dt.datetime.now(dt.timezone.utc).strftime("%d/%m"))
    afficher(cible, par.get(cible, []), tend)
    print("\nChiffres REJOUES sur la journee, pas des decisions prises en direct. Les tests geles"
          " (papier_gd_direct --rapport) sont les seuls qui prouvent quelque chose.")


if __name__ == "__main__":
    main()
