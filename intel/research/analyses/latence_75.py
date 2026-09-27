"""PEUT-ON DECIDER A 75 s ? La seule question qui commande tout le reste : la LATENCE.

MIDO, 20/09 : « ca c est ton travail d optim, tu le fais et tu me dis ce que tu vas brancher parmi
les strats 75 ; en attendant debranche la prod et travaille ».

LE VERROU. La famille `FORET 75s` est la seule qui gagne (6/6 criteres, 86-91 % de gagnants), et
elle s appuie a **71 % sur le flux d ordres** -- des variables que le moteur ne calcule pas. La
donnee existe : `v1_enregistreur` appelle Helius `getTransactionsForAddress` des qu un pool a 70 s,
sur la fenetre [naissance - 5 s, naissance + 60 s]. Le calendrier colle par construction : l index
a 10-15 s de retard, donc a 70 s les transactions <= 60 s sont surement visibles (§ flux_fraicheur).

MAIS LA DECISION EST A 75 s. Entre l appel (70 s) et la decision (75 s) il y a **5 secondes**. Si
l appel met plus que ca, le ticket est manque -- et toute la piste tombe. Ce script mesure la
latence REELLE sur des pools reels, avant d ecrire une ligne de moteur.

CE QU IL MESURE, et rien d autre :
  - le temps d aller-retour de l appel, en secondes, sur des pools de l heure ecoulee ;
  - le nombre de PAGES : l enregistreur en fait jusqu a 10, et chaque page est un appel de plus.
    Un pool tres actif coute donc plusieurs appels, et c est la queue qui decide, pas la mediane ;
  - le nombre de transactions ramenees, pour savoir si les variables seront calculables.

LECTURE SEULE. Aucun ordre, aucune ecriture, aucune modification du moteur. On mesure d abord.
"""
from __future__ import annotations

import os
import sqlite3
import statistics as st
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import copie_collecte as cc  # noqa: E402

BASE = "/app/db/intel.sqlite"
FENETRE = 60
N_POOLS = int(os.environ.get("N_POOLS", "25"))
BUDGET_S = 5.0                     # ce dont on dispose entre l appel a 70 s et la decision a 75 s


def pools_recents(n: int):
    """Des pools nes dans l heure, assez vieux pour que leurs 60 premieres secondes soient lisibles."""
    c = sqlite3.connect("file:%s?mode=ro" % BASE, uri=True, timeout=60)
    try:
        maintenant = time.time()
        rows = c.execute(
            "SELECT pair_id, MAX(mint), MIN(ts - age_s), MAX(reserve_virtuelle)"
            " FROM solana_prix_chaine WHERE ts >= ? GROUP BY pair_id"
            " HAVING MIN(age_s) <= 20 ORDER BY MIN(ts - age_s) DESC", (maintenant - 3600,)).fetchall()
    finally:
        c.close()
    return [r for r in rows if r[1] and r[2] and (maintenant - r[2]) >= 70][:n]


def une_lecture(pair, t0):
    """Un appel, chronometre. On compte les pages : chacune est un appel reseau de plus."""
    jeton, pages, n, t_debut = None, 0, 0, time.time()
    while pages < 10:
        opts = {"transactionDetails": "full", "sortOrder": "asc", "limit": 1000,
                "encoding": "jsonParsed", "maxSupportedTransactionVersion": 1,
                "filters": {"blockTime": {"gte": int(t0) - 5, "lte": int(t0) + FENETRE},
                            "status": "succeeded"}}
        if jeton:
            opts["paginationToken"] = jeton
        res = cc.rpc({"jsonrpc": "2.0", "id": 1, "method": "getTransactionsForAddress",
                      "params": [pair, opts]}) or {}
        pages += 1
        n += len(res.get("data") or [])
        jeton = res.get("paginationToken")
        if not jeton:
            break
    return time.time() - t_debut, pages, n


def main() -> None:
    P = pools_recents(N_POOLS)
    if not P:
        print("latence_75: aucun pool exploitable dans l heure")
        return
    print("LATENCE DE L APPEL HELIUS, sur %d pools reels · budget disponible %.0f s" % (len(P), BUDGET_S))
    print("   %-14s %9s %7s %9s" % ("pool", "secondes", "pages", "tx"))
    mesures = []
    for pair, mint, t0, _V in P:
        try:
            dt_, pages, n = une_lecture(pair, float(t0))
        except Exception as e:  # noqa: BLE001
            print("   %-14s  ECHEC %s" % (str(pair)[:14], str(e)[:50]))
            continue
        mesures.append((dt_, pages, n))
        print("   %-14s %9.2f %7d %9d" % (str(pair)[:14], dt_, pages, n))
    if not mesures:
        return
    v = sorted(x[0] for x in mesures)
    q = lambda f: v[min(int(f * len(v)), len(v) - 1)]  # noqa: E731
    print()
    print("   mediane %.2f s · q3 %.2f · d9 %.2f · MAX %.2f" % (q(.5), q(.75), q(.9), v[-1]))
    dedans = sum(1 for x in v if x <= BUDGET_S)
    print("   dans le budget de %.0f s : %d sur %d (%.0f %%)"
          % (BUDGET_S, dedans, len(v), 100 * dedans / len(v)))
    print("   pages : mediane %d · max %d  (chaque page est un appel de plus)"
          % (st.median([x[1] for x in mesures]), max(x[1] for x in mesures)))
    print("   transactions ramenees : mediane %d · min %d"
          % (st.median([x[2] for x in mesures]), min(x[2] for x in mesures)))
    print()
    if 100 * dedans / len(v) < 90:
        print("   -> LE BUDGET NE TIENT PAS. Decider a 75 s manquerait %.0f %% des tickets."
              % (100 - 100 * dedans / len(v)))
    else:
        print("   -> le budget tient sur %.0f %% des pools. Reste le quota et la sortie." % (100 * dedans / len(v)))


if __name__ == "__main__":
    main()
