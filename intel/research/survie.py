"""Acheter la survie, pas la naissance : que vaut un lancement qui a tenu une heure ?

Tout ce que ce projet a mesure s arretait a T+30 min, et tout y perd. Deux faits du 09/09 disent
que l argent se fait apres : l operateur a tenu un jeton quatre heures pour x3,13 la ou le moteur
sortait a 30 min ; et l ecran de DexScreener montre des jetons a +400 % dix-sept heures apres leur
naissance, tous ayant survecu a la premiere heure ou un lancement sur cinq meurt.

`intel/engines/suivi_long.py` collecte depuis le 09/09 22h38 : 24 h par lancement, prix,
liquidite, capitalisation, volume et flux horaires. Ce fichier pose la question sur ces courbes.

LA STRATEGIE TESTEE. Entrer a T+1 h -- pas avant -- sur un lancement qui remplit une condition de
survie lisible a cet instant ; tenir des heures ; sortir sur un stop suiveur ou a l horizon.

DISCIPLINE, la meme que partout :
  - moitie de recherche / moitie de jugement, decoupees par date de naissance du pool ;
  - le stop suiveur rend le PRIX OBSERVE au releve suivant, jamais le seuil (§3.59) ;
  - peage de 2 % deduit ; la reference est « acheter tout a T+1 h » ; le test est contre le hasard ;
  - la resolution est de 5 min entre 1 h et 6 h, 15 min apres : un stop a 30 % est mesurable, un
    stop a 5 % ne l est pas, et on ne teste que ce qui l est.

Usage :
    python -m intel.research.survie
"""
from __future__ import annotations

import argparse
import random
import sqlite3
import statistics as st
import sys

sys.path.insert(0, "/app")

TICKET, PEAGE = 20.0, 0.98
ENTREE_MIN, ENTREE_MAX = 55, 95          # minutes : « a T+1 h », avec la tolerance du pas de 5 min


def courbes(db: str):
    c = sqlite3.connect("file:" + db + "?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    brut: dict[str, list] = {}
    for r in c.execute("SELECT pair_id, ts, age_min, price_usd, liquidity_usd, market_cap, volume_h1,"
                       " buys_h1, sells_h1, chg_h1 FROM solana_suivi_long WHERE price_usd > 0 ORDER BY pair_id, age_min"):
        brut.setdefault(r["pair_id"], []).append(dict(r))
    out = []
    for pid, pts in brut.items():
        ent = [p for p in pts if ENTREE_MIN <= p["age_min"] <= ENTREE_MAX]
        if not ent:
            continue
        e = ent[0]
        apres = [p for p in pts if p["age_min"] > e["age_min"]]
        if len(apres) < 6 or apres[-1]["age_min"] < e["age_min"] + 120:
            continue                       # il faut au moins deux heures de suite observee
        p0 = float(e["price_usd"])
        serie = [(float(p["age_min"]) - float(e["age_min"]), float(p["price_usd"]) / p0) for p in apres]
        out.append(dict(
            pair_id=pid, ne=int(e["ts"]), duree_h=serie[-1][0] / 60,
            # ce qu on VOIT a T+1 h
            liq=float(e["liquidity_usd"] or 0), cap=float(e["market_cap"] or 0),
            vol_h1=float(e["volume_h1"] or 0), buys=int(e["buys_h1"] or 0), sells=int(e["sells_h1"] or 0),
            chg_h1=float(e["chg_h1"]) if e["chg_h1"] is not None else None,
            ratio_ba=(int(e["buys_h1"] or 0) / max(int(e["sells_h1"] or 0), 1)),
            serie=serie,
        ))
    out.sort(key=lambda x: x["ne"])
    return out


def a_horizon(serie, heures):
    pts = [m for a, m in serie if a <= heures * 60]
    return pts[-1] if pts else serie[-1][1]


def pic(serie, heures):
    return max([m for a, m in serie if a <= heures * 60] or [1.0])


def stop_suiveur(serie, retrait, heures):
    """Sortir quand le prix a perdu `retrait` depuis son plus haut, au prix du releve suivant."""
    haut = 1.0
    fen = [(a, m) for a, m in serie if a <= heures * 60]
    for i, (a, m) in enumerate(fen):
        haut = max(haut, m)
        if m <= haut * (1 - retrait):
            return fen[i + 1][1] if i + 1 < len(fen) else m
    return fen[-1][1] if fen else 1.0


def par_euro(lot, sortie):
    return sum((sortie(x["serie"]) * PEAGE - 1) for x in lot) / len(lot) if lot else 0.0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="/app/db/intel.sqlite")
    a = ap.parse_args()
    d = courbes(a.db)
    print("  %d lancements entres a T+1 h avec au moins 2 h de suite · duree mediane suivie %.1f h" % (
        len(d), st.median([x["duree_h"] for x in d]) if d else 0))
    if len(d) < 60:
        print("  trop peu pour conclure.")
        return
    n = len(d) // 2
    rech, juge = d[:n], d[n:]

    print("\n  1. QUE DEVIENT UN LANCEMENT QUI A TENU UNE HEURE ? (tous, depuis le prix a T+1 h)")
    for h in (2, 3, 6, 12):
        lot = [x for x in d if x["duree_h"] >= h]
        if len(lot) < 30:
            continue
        fins = [a_horizon(x["serie"], h) for x in lot]
        pics = [pic(x["serie"], h) for x in lot]
        print("     T+%2dh  n=%-4d fin mediane x%.2f · x>=1.5 %2.0f %% · x>=2 %2.0f %% · x>=3 %2.0f %% · <x0.5 %2.0f %% · par euro (tenir) %+.3f" % (
            h, len(lot), st.median(fins), 100 * sum(p >= 1.5 for p in pics) / len(pics),
            100 * sum(p >= 2 for p in pics) / len(pics), 100 * sum(p >= 3 for p in pics) / len(pics),
            100 * sum(f < 0.5 for f in fins) / len(fins), sum(f * PEAGE - 1 for f in fins) / len(fins)))

    print("\n  2. SORTIES, sur tous (recherche / jugement)")
    sorties = {
        "tenir 3 h": lambda s: a_horizon(s, 3), "tenir 6 h": lambda s: a_horizon(s, 6),
        "tenir 12 h": lambda s: a_horizon(s, 12),
        "stop 30 % / 6 h": lambda s: stop_suiveur(s, 0.30, 6), "stop 40 % / 6 h": lambda s: stop_suiveur(s, 0.40, 6),
        "stop 30 % / 12 h": lambda s: stop_suiveur(s, 0.30, 12), "stop 50 % / 12 h": lambda s: stop_suiveur(s, 0.50, 12),
    }
    for nom, f in sorties.items():
        print("     %-18s recherche %+.3f   jugement %+.3f" % (nom, par_euro(rech, f), par_euro(juge, f)))

    print("\n  3. CONDITIONS D ENTREE a T+1 h, sortie « stop 30 % / 6 h » (recherche / jugement, n)")
    sortie = sorties["stop 30 % / 6 h"]
    ref_r, ref_j = par_euro(rech, sortie), par_euro(juge, sortie)
    print("     %-28s %+.3f / %+.3f  (%d / %d)" % ("reference : tout", ref_r, ref_j, len(rech), len(juge)))
    cands = []
    for var in ("liq", "cap", "vol_h1", "buys", "ratio_ba", "chg_h1"):
        vals = sorted(x[var] for x in rech if x.get(var) is not None)
        if len(vals) < 40:
            continue
        for q in (0.3, 0.5, 0.7):
            s = vals[int(len(vals) * q)]
            for sens in (">=", "<="):
                g = (lambda x, v=var, s=s, sn=sens: x.get(v) is not None and (x[v] >= s if sn == ">=" else x[v] <= s))
                r = [x for x in rech if g(x)]; j = [x for x in juge if g(x)]
                if len(r) < 25 or len(j) < 25:
                    continue
                cands.append((par_euro(r, sortie), par_euro(j, sortie), "%s %s %.3g" % (var, sens, s), len(r), len(j), g))
    cands.sort(key=lambda x: -x[0])
    for pr, pj, nom, nr, nj, _ in cands[:8]:
        print("     %-28s %+.3f / %+.3f  (%d / %d)%s" % (nom, pr, pj, nr, nj, "  <== positif des deux cotes" if pr > 0 and pj > 0 else ""))
    tient = [c for c in cands if c[0] > 0 and c[1] > 0]
    print("     regles positives des deux cotes : %d / %d" % (len(tient), len(cands)))
    if tient:
        pr, pj, nom, nr, nj, g = max(tient, key=lambda c: min(c[0], c[1]))
        lot = [x for x in juge if g(x)]
        random.seed(1)
        ech = [par_euro(random.sample(juge, len(lot)), sortie) for _ in range(3000)]
        mieux = sum(1 for e in ech if e >= pj)
        print("     test du hasard sur la plus solide (%s) : %d/3000 tirages de %d font mieux (%.1f %%)" % (
            nom, mieux, len(lot), 100 * mieux / 3000))


if __name__ == "__main__":
    main()
