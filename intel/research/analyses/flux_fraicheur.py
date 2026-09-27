"""A PARTIR DE QUAND l index des transactions est-il complet ? Le retard, mesure.

CE QUE LE PREMIER TEST A MONTRE (19/09, `flux_latence.py`). L appel par transaction est RAPIDE
(0,47 s median) mais, interroge a 45 s sur la fenetre [naissance-5 s, naissance+45 s], il ne rend pas
tout : 5 pools sur 6 incomplets, 122 transactions manquantes en median, 331 au pire. La meme fenetre
relue a 140 s en rend davantage. Ce n est donc pas du trafic en plus -- c est l index qui retarde.

L INDICE. Le seul pool complet du lot avait ete lu a **55 s** pour une fenetre s arretant a 45 s,
soit 10 s de marge ; les cinq incomplets avaient ete lus a 40-44 s, soit zero marge. Le retard
ressemble a une dizaine de secondes. Mais c est UN cas, et une hypothese batie sur un cas n est pas
une mesure (regle 8) : il faut la marge, pas l age.

CE QU ON MESURE ICI. Pour chaque pool vivant, on relit LA MEME fenetre [naissance-5 s,
naissance+45 s] a plusieurs MARGES successives -- 0 s, 5 s, 10 s, 15 s, 25 s, 45 s, 95 s apres la fin
de la fenetre -- et on compte les transactions a chaque fois. La derniere lecture sert de reference.
On obtient la part reellement visible en fonction de la marge, donc la reponse a la seule question
qui compte pour le moteur : **de combien faut-il retarder la decision pour voir tout ce que la foret
a appris**, et ce que coute chaque seconde d attente en information manquante.

CE QUE LA REPONSE DECIDE :
  marge nulle suffisante   -> on decide a 45 s comme aujourd hui, rien ne change
  marge de ~10 s           -> decider a 55 s, donc entrer vers 64 s au lieu de 54 : il faudra
                              remesurer le cout, car le prix bouge (§3.152)
  marge longue             -> la foret de flux ne peut pas servir a 45 s ; il faudrait la
                              reentrainer sur la vue TRONQUEE, telle que l appel la rend vraiment
Lecture seule, aucune signature, aucune cle touchee.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import time

import numpy as np

sys.path.insert(0, "/app/intel/research")
import copie_collecte as cc  # noqa: E402

cc.VERSION_MAX = 1
BASE = os.environ.get("INTEL_DB", "/app/db/intel.sqlite")
FENETRE = 45
MARGES = [0, 5, 10, 15, 25, 45, 95]          # secondes APRES la fin de la fenetre
N_POOLS = int(os.environ.get("N_POOLS", "8"))
ATTENTE_MAX = int(os.environ.get("ATTENTE_MAX", "1200"))


def jeunes(age_max=44):
    c = sqlite3.connect("file:%s?mode=ro" % BASE, uri=True, timeout=60)
    try:
        rows = c.execute(
            "SELECT pair_id, MAX(mint), MIN(ts - age_s), MAX(reserve_virtuelle)"
            " FROM solana_prix_chaine WHERE ts >= ? GROUP BY pair_id HAVING MIN(age_s) <= 20",
            (time.time() - 1800,)).fetchall()
    finally:
        c.close()
    now = time.time()
    return [{"pair": p, "mint": m, "naissance": float(t0), "V": float(v or 17.5845)}
            for p, m, t0, v in rows if 0 < now - float(t0) <= age_max]


def main() -> None:
    cc.FENETRE_S = FENETRE
    print("RETARD DE L INDEX · fenetre [naissance-5 s, naissance+%d s] relue a plusieurs marges" % FENETRE)
    print("marges testees (s apres la fin de la fenetre) : %s" % ", ".join(str(m) for m in MARGES))
    print()
    suivis, debut = {}, time.time()
    while len(suivis) < N_POOLS and time.time() - debut < ATTENTE_MAX:
        for p in jeunes():
            if p["pair"] in suivis or len(suivis) >= N_POOLS:
                continue
            suivis[p["pair"]] = {"p": p, "n": {}}
            print("   suivi %s... (ne le %.0f s)" % (p["pair"][:8], time.time() - p["naissance"]), flush=True)
        # a chaque tour, lire ceux dont une marge est echue
        for v in suivis.values():
            cible = v["p"]["naissance"] + FENETRE
            for m in MARGES:
                if m in v["n"] or time.time() < cible + m:
                    continue
                if any(mm > m and mm in v["n"] for mm in MARGES):
                    v["n"][m] = None            # marge ratee, on ne triche pas en la lisant plus tard
                    continue
                try:
                    v["n"][m] = cc.lire_pool(v["p"])["n_tx"]
                except Exception as e:
                    v["n"][m] = None
                    print("   %s... marge %ds ECHEC %s" % (v["p"]["pair"][:8], m, str(e)[:50]), flush=True)
        if suivis and all(MARGES[-1] in v["n"] for v in suivis.values()) and len(suivis) >= N_POOLS:
            break
        time.sleep(2)

    faits = [v for v in suivis.values() if v["n"].get(MARGES[-1])]
    if not faits:
        print("\n   aucun pool suivi jusqu au bout -- rien a conclure")
        return
    print()
    print("   %-11s %s" % ("pool", "".join("%9s" % ("+%ds" % m) for m in MARGES)))
    parts = {m: [] for m in MARGES}
    for v in faits:
        ref = v["n"][MARGES[-1]]
        ligne = ""
        for m in MARGES:
            x = v["n"].get(m)
            if x is None or not ref:
                ligne += "%9s" % "-"
            else:
                parts[m].append(x / ref)
                ligne += "%9s" % ("%d (%.0f%%)" % (x, 100 * x / ref))
        print("   %-11s %s" % (v["p"]["pair"][:8] + "..", ligne))
    print()
    print("PART VISIBLE selon la marge (1,00 = tout ce que la fenetre contiendra)")
    seuil = None
    for m in MARGES:
        if not parts[m]:
            continue
        a = np.array(parts[m])
        drapeau = ""
        if seuil is None and a.min() >= 0.995:
            seuil = m
            drapeau = "   <- complet des ce point, sur %d pools" % len(a)
        print("   marge +%2ds (decision a %2d s) : median %.0f %% · pire %.0f %% · %d pools%s"
              % (m, FENETRE + m, 100 * np.median(a), 100 * a.min(), len(a), drapeau))
    print()
    if seuil == 0:
        print("   -> l index est a jour des 45 s : on decide comme aujourd hui, rien a changer.")
    elif seuil is not None:
        print("   -> il faut %d s de marge : decider a %d s, donc entrer vers %d s au lieu de 54."
              % (seuil, FENETRE + seuil, 54 + seuil))
        print("      Avant de bouger quoi que ce soit il faudra REMESURER LE COUT a cette entree-la :")
        print("      le prix bouge, et c est ce qui a coute 150 EUR a etablir (§3.152).")
    else:
        print("   -> meme a +%ds la vue n est pas stable : la foret de flux ne peut pas servir a 45 s."
              % MARGES[-2])
        print("      Il faudrait l entrainer sur la vue TRONQUEE, telle que l appel la rend vraiment.")


if __name__ == "__main__":
    main()
