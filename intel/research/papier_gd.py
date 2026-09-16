"""Test PAPIER vers l avant de la regle G+D (§3.95). Gele le 16/09 a 15h40 UTC.

Aucun ordre, aucune cle, aucune ecriture nulle part : ce script ne fait que RELIRE des donnees deja
collectees en continu par trois processus qui tournent depuis plusieurs jours. C est un test vers l avant
parce que la regle et le critere ci-dessous sont ecrits AVANT que les donnees jugees existent.

CE QUI EST TESTE, FIGE AVANT LE DEPART
  population   tout pool PumpSwap enregistre par `v1_enregistreur` (ses 60 premieres secondes, transaction
               par transaction) ET suivi en prix par le moteur, ne au plus tot au GEL, ou notre ordre de
               0,31 SOL pese <= 15 % du coffre a l entree.
  regle G      acheteurs uniques avant 45 s <= 74  ET  coffre a la naissance (SOL + reserve virtuelle) < 100.
  regle D      tendance > 0 = moyenne des 50 derniers resultats CONNUS a l instant de la decision
               (table `ref` de papier_combo.sqlite : decision 60 s, sortie 240 s, tous les pools).
  entree       premiere lecture de prix a >= 47 s d age.
  sortie       premiere lecture >= entree x 1,25, puis on vend a la lecture suivante >= 2 s plus tard
               (delai d execution) ; sinon lecture la plus proche de 287 s. Gain plafonne a +300 %.
  pause        apres un ticket clos a <= -30 %, on n entre plus pendant 30 min.
  cout         2,62 points par ticket (ecart mesure entre le mouvement de prix et le carnet reel sur 236
               tickets, cf. calibration_corrigee.py). Le cout modelise (1,7 % + impact + 0,5 %) est donne
               a cote, en variante prudente.
  TEMOIN       aux memes instants d entree, un pool tire au hasard parmi les eligibles de la demi-heure.
               Mesure sur le passe (15-16/09) : +4,49 % par ticket. C est LUI qu il faut battre, pas zero.
  CRITERE      au bout de 300 tickets G+D ou de 21 jours, selon ce qui arrive en premier :
               moyenne >= +4,5 % par ticket, positive sur les deux moities, positive sans son meilleur
               ticket, et au-dessus du 95e centile du temoin. Sinon la regle est abandonnee.

POURQUOI CE SEUIL. En backtest la regle donne +9,71 % par ticket (126 tickets) et +10,28 % hors
echantillon (33 tickets), mais le temoin « meme instant, jeton au hasard » donne deja +4,49 % : une bonne
part vient de l heure choisie, pas du jeton. Ecart a prouver 5,5 points, ecart-type par ticket 45 points,
donc ~520 tickets pour trancher a 80 % de puissance ; 300 est le compromis assume (puissance ~60 %).

ATTENTION, DIFFERENCE AVEC LE BACKTEST. Ici les prix viennent du moteur (une lecture toutes les ~10 s),
alors que le backtest voyait chaque transaction. La prise de gain a +25 % est donc detectee plus tard et
moins souvent : le chiffre d ici est le chiffre EXECUTABLE, celui du backtest est optimiste.

Rapport : python -m intel.research.papier_gd --rapport
Controle de plomberie sur le passe : python -m intel.research.papier_gd --depuis 2026-09-15T12:34
"""
from __future__ import annotations

import datetime as dt
import glob
import json
import os
import random
import sqlite3
import sys
from bisect import bisect_right

BASE_MOTEUR = os.environ.get("INTEL_DB", "/app/db/intel.sqlite")
BASE_COMBO = os.environ.get("PAPIER_COMBO_DB", "/app/db/papier_combo.sqlite")
V1_DIR = os.environ.get("V1_AVANT_DIR", "/app/data/recherche/v1_avant")

# En UTC. L heure dite a l operateur est celle de Paris (UTC+2) : la premiere version de ce fichier
# portait « 15h40 UTC » qui etait en fait l heure de Paris, soit un gel place 1h30 dans le futur.
GEL = dt.datetime(2026, 9, 16, 14, 10, tzinfo=dt.timezone.utc).timestamp()
FOULE_MAX, COFFRE_MAX = 74, 100.0
A, EXEC_S, FIN_S = 45, 2, 287
TP, PLAFOND, COUT, MISE_EUR, MISE_SOL = 0.25, 3.0, 0.0262, 30.0, 0.31
PAUSE, SEUIL_PAUSE = 1800, -0.30
N_REGIME = 50


def lire_pools(depuis):
    """Les pools nes apres `depuis`, avec leurs 60 premieres secondes transaction par transaction."""
    out = {}
    for f in sorted(glob.glob(os.path.join(V1_DIR, "*.jsonl"))):
        for l in open(f, encoding="utf-8"):
            d = json.loads(l)
            if d.get("erreur") or not d.get("tx") or d["naissance"] < depuis:
                continue
            av = [x for x in d["tx"] if 0 <= x[0] <= A]
            if len(av) < 3:
                continue
            q0 = next((x[3] for x in d["tx"] if x[3]), None)
            if q0 is None:
                continue
            out[d["pair"]] = {"mint": d.get("mint"), "naissance": d["naissance"],
                              "acheteurs": len({o for x in av for o, dtk, s in x[2] if dtk > 0}),
                              "q0": q0 + (d.get("V") or 0)}
    return out


def chemins(moteur, pairs, depuis):
    """Pour chaque pool : [(age, prix, coffre)] trie, tel que le MOTEUR l a vu (≈ 1 lecture / 10 s)."""
    ch = {}
    for pair, age, p, xs, v in moteur.execute(
            "SELECT pair_id, age_s, prix_sol, reserve_sol, reserve_virtuelle FROM solana_prix_chaine"
            " WHERE ts > ? AND reserve_virtuelle IS NOT NULL AND prix_sol > 0 ORDER BY pair_id, age_s",
            (depuis,)):
        if pair in pairs:
            ch.setdefault(pair, []).append((age, p, (xs or 0.0) + (v or 0.0)))
    return ch


def ticket(pts):
    """Entree a >= 47 s, sortie sur prise de gain (+ delai) ou a 287 s. Rend (rendement brut, coffre a l entree)."""
    e = next((i for i, x in enumerate(pts) if x[0] >= A + EXEC_S), None)
    if e is None or pts[e][1] <= 0:
        return None
    fin = max((i for i, x in enumerate(pts) if x[0] <= FIN_S + 20), default=None)
    if fin is None or fin <= e:
        return None
    pe = pts[e][1]
    for i in range(e + 1, fin + 1):
        if pts[i][1] >= pe * (1 + TP):
            j = next((k for k in range(i, fin + 1) if pts[k][0] >= pts[i][0] + EXEC_S), fin)
            return min(pts[j][1] / pe - 1, PLAFOND), pts[e][2]
    return min(pts[fin][1] / pe - 1, PLAFOND), pts[e][2]


def tendance(refs_t, refs_cum, t):
    k = bisect_right(refs_t, t)
    return (refs_cum[k] - refs_cum[k - N_REGIME]) / N_REGIME if k >= N_REGIME else None


def construire(depuis):
    pools = lire_pools(depuis)
    moteur = sqlite3.connect("file:%s?mode=ro" % BASE_MOTEUR, uri=True, timeout=60)
    combo = sqlite3.connect("file:%s?mode=ro" % BASE_COMBO, uri=True, timeout=60)
    refs = combo.execute("SELECT t_fin, r FROM ref ORDER BY t_fin").fetchall()
    refs_t = [x[0] for x in refs]
    refs_cum, s = [0.0], 0.0
    for _, r in refs:
        s += r
        refs_cum.append(s)
    ch = chemins(moteur, set(pools), depuis - 600)
    tk = []
    for pair, d in pools.items():
        pts = sorted(ch.get(pair, []))
        if len(pts) < 6:
            continue
        r = ticket(pts)
        if r is None:
            continue
        brut, q_entree = r
        if q_entree <= 0 or MISE_SOL / q_entree > 0.15:      # non executable : ecarte
            continue
        t_dec = d["naissance"] + A
        tk.append({"pair": pair, "t": t_dec, "fin": d["naissance"] + FIN_S + EXEC_S,
                   "r": brut - COUT, "r_modele": brut - (0.017 + 2 * MISE_SOL / q_entree + 0.005),
                   "acheteurs": d["acheteurs"], "q0": d["q0"], "tend": tendance(refs_t, refs_cum, t_dec)})
    return sorted(tk, key=lambda z: z["t"]), len(pools)


def pause_30(tk, cle="r"):
    pris, att, jusqu = [], [], 0.0
    for t in tk:
        while att and att[0]["fin"] <= t["t"]:
            r = att.pop(0)
            if r[cle] <= SEUIL_PAUSE:
                jusqu = max(jusqu, r["fin"] + PAUSE)
        if t["t"] >= jusqu:
            pris.append(t)
        att.append(t)
        att.sort(key=lambda z: z["fin"])
    return pris


def ligne(nom, v, jours, marque=""):
    if not v:
        print("   %-30s aucun ticket" % nom)
        return
    s = sorted(v, reverse=True)
    moit = len(v) // 2
    m1 = sum(v[:moit]) / moit if moit else float("nan")
    m2 = sum(v[moit:]) / (len(v) - moit)
    print("   %-30s n=%4d · %+6.2f %% · sans best %+6.2f %% · moities %+6.2f / %+6.2f · %+7.0f EUR · %+6.0f EUR/j%s"
          % (nom, len(v), 100 * sum(v) / len(v), 100 * sum(s[1:]) / (len(s) - 1) if len(s) > 1 else float("nan"),
             100 * m1, 100 * m2, MISE_EUR * sum(v), MISE_EUR * sum(v) / max(jours, 1e-9), marque))


def rapport(depuis):
    tk, n_pools = construire(depuis)
    if not tk:
        print("papier_gd: aucun ticket depuis le %s (pools lus : %d)"
              % (dt.datetime.fromtimestamp(depuis, dt.timezone.utc).strftime("%d/%m %H:%M UTC"), n_pools))
        return
    jours = (max(t["t"] for t in tk) - depuis) / 86400
    print("papier_gd: depuis le %s · %.2f jour(s) · %d pools lus · %d tickets executables"
          % (dt.datetime.fromtimestamp(depuis, dt.timezone.utc).strftime("%d/%m %H:%M UTC"), jours, n_pools, len(tk)))
    connus = [t for t in tk if t["tend"] is not None]
    print("   tendance connue pour %d tickets sur %d" % (len(connus), len(tk)))
    G = lambda t: t["acheteurs"] <= FOULE_MAX and t["q0"] < COFFRE_MAX
    for nom, f, pause in (("temoin · tous les tickets", lambda t: True, False),
                          ("G · foule + coffre", G, True),
                          ("D · tendance + coffre", lambda t: t["tend"] is not None and t["tend"] > 0 and t["q0"] < COFFRE_MAX, False),
                          ("G + D  <- CRITERE", lambda t: G(t) and t["tend"] is not None and t["tend"] > 0, True)):
        sel = [t for t in tk if f(t)]
        pris = pause_30(sel) if pause else sel
        ligne(nom, [t["r"] for t in pris], jours, "   <- CRITERE" if "CRITERE" in nom else "")
        if "CRITERE" in nom and pris:
            ligne("   ... au cout modelise", [t["r_modele"] for t in pris], jours)
            # temoin : memes instants, pool tire au hasard dans la demi-heure
            rng = random.Random(16)
            tirs = []
            for _ in range(2000):
                s = 0.0
                for t in pris:
                    cand = [k for k in tk if abs(k["t"] - t["t"]) < 1800]
                    s += rng.choice(cand)["r"]
                tirs.append(s / len(pris))
            tirs.sort()
            moy = sum(t["r"] for t in pris) / len(pris)
            cent = 100 * sum(1 for x in tirs if x < moy) / len(tirs)
            print("   temoin meme instant : %+6.2f %% (95e centile %+6.2f %%) · G+D au %.0f e centile"
                  % (100 * sum(tirs) / len(tirs), 100 * tirs[int(0.95 * len(tirs))], cent))


def main():
    depuis = GEL
    if "--depuis" in sys.argv:
        depuis = dt.datetime.fromisoformat(sys.argv[sys.argv.index("--depuis") + 1]).replace(
            tzinfo=dt.timezone.utc).timestamp()
    rapport(depuis)


if __name__ == "__main__":
    main()
