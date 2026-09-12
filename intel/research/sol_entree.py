"""Quels lancements acheter ? Balayage des regles d entree sur donnees propres.

La rejoue des sorties (`sol_objectif`) a montre que sur l ensemble des lancements juges, AUCUN
reglage de vente ne rend le carnet rentable : les quarante cases de la grille perdent. Cela ne dit
rien sur le choix des lancements -- elle les achete tous.

Ce fichier balaye l ENTREE, la sortie restant celle de production (x1,5 / 0,7). Le balayage d entree
avait deja ete fait, mais sur l echantillon biaise par le bug d ordre de tri (§3.57) : le nombre d
acheteurs, qui est le critere central du filtre en place, y etait faux. Il est donc a refaire.

Quatre garde-fous, tous payes cher :

  1. RECHERCHE SUR LA PREMIERE MOITIE, JUGEMENT SUR LA SECONDE (§3.45).
  2. UNE MESURE RATEE N EST PAS UNE VALEUR. `uniq_payers_30s` a 0 avec des echanges dans la meme
     fenetre est un echec d enrichissement, pas une absence d acheteurs ; `liquidity_usd` a 0 est un
     champ absent. Les compter comme des zeros a produit la fausse « meilleure regle »
     `liquidity_usd < 8,83`, qui ne selectionnait que les lignes ou la donnee manque.
  3. UNE REGLE SE JUGE SUR SA COUVERTURE AUTANT QUE SUR SON GAIN. Un filtre qui garde huit tickets
     ne se compare a rien. On exige un minimum de passages dans LES DEUX moities.
  4. LE MEILLEUR SE COMPARE AU HASARD. Un balayage trouve toujours un maximum ; la question est de
     savoir s il depasse ce que donnerait un tirage au sort de meme taille (§3.44).

Usage :
    python -m intel.research.sol_entree
"""
from __future__ import annotations

import argparse
import random
import sqlite3
import statistics as st
import sys

sys.path.insert(0, "/app")

TICKET, PEAGE = 20.0, 0.98
TP, SL = 1.5, 0.7
ENTREE_MIN, FENETRE = 2.0, 30.0
COUVERTURE_MIN = 0.15          # une regle doit garder au moins 15 % de chaque moitie

VARIABLES = ("payers", "trades", "ratio", "market_cap", "liquidity_usd", "age_s", "chg_m5",
             "trades_first_minute", "uniq_payers", "trades_30s", "uniq_payers_30s", "accel")


def jeu(db: str) -> list[dict]:
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row

    brut: dict[str, list[tuple[float, float]]] = {}
    for pid, age, px in c.execute("SELECT pair_id, age_min, price_usd FROM solana_suivi "
                                  "WHERE price_usd>0 ORDER BY pair_id, age_min"):
        brut.setdefault(pid, []).append((float(age), float(px)))

    obs = {r["pair_id"]: dict(r) for r in c.execute("SELECT * FROM solana_observations")}

    out = []
    for j in c.execute("SELECT * FROM solana_judgements"):
        pts = brut.get(j["pair_id"])
        if not pts or len(pts) < 8:
            continue
        ent = [p for p in pts if p[0] >= ENTREE_MIN]
        if not ent or ent[0][1] <= 0:
            continue
        a0, px0 = ent[0]
        serie = [(a, px / px0) for a, px in pts if a0 < a <= a0 + FENETRE]
        if len(serie) < 3:
            continue

        d = dict(j)
        d.update({k: v for k, v in (obs.get(j["pair_id"]) or {}).items()
                  if k in ("trades_first_minute", "uniq_payers", "trades_30s", "uniq_payers_30s")})

        # Garde-fou 2 : separer la vraie valeur de la panne de mesure.
        t30 = d.get("trades_30s") or 0
        if d.get("uniq_payers_30s") == 0 and t30 > 0:
            d["uniq_payers_30s"] = None
        if not d.get("liquidity_usd"):
            d["liquidity_usd"] = None
        p30 = d.get("uniq_payers_30s")
        d["ratio"] = (d.get("trades") or 0) / max(d.get("payers") or 1, 1)
        d["accel"] = (float(d.get("payers") or 0) / p30) if p30 else None
        d["gain"] = (sortie(serie) * PEAGE - 1) * TICKET
        out.append(d)
    out.sort(key=lambda x: x["ts"])
    return out


def sortie(serie: list[tuple[float, float]]) -> float:
    for i, (_a, m) in enumerate(serie):
        suiv = serie[i + 1][1] if i + 1 < len(serie) else None
        if suiv is None:
            break
        if m >= TP and suiv >= TP:
            return TP
        if m <= SL and suiv <= SL:
            return suiv
    return serie[-1][1]


def par_euro(lot: list[dict]) -> float:
    return sum(x["gain"] for x in lot) / (len(lot) * TICKET) if lot else 0.0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="/app/db/intel.sqlite")
    ap.add_argument("--tirages", type=int, default=2000)
    a = ap.parse_args()

    d = jeu(a.db)
    n = len(d) // 2
    rech, juge = d[:n], d[n:]
    print(f"  {len(d)} lancements · recherche {len(rech)} · jugement {len(juge)}")
    print(f"  reference (acheter tout) : recherche {par_euro(rech):+.3f}/euro · "
          f"jugement {par_euro(juge):+.3f}/euro\n")

    candidats = []
    for v in VARIABLES:
        vals = sorted(x[v] for x in rech if x.get(v) is not None)
        if len(vals) < 40:
            print(f"  {v:<20} seulement {len(vals)} valeurs connues -- ecarte")
            continue
        seuils = [vals[int(len(vals) * q)] for q in (.1, .2, .3, .4, .5, .6, .7, .8, .9)]
        for s in sorted(set(seuils)):
            for sens in (">=", "<="):
                garde = (lambda x, v=v, s=s, sens=sens: x.get(v) is not None and
                         (x[v] >= s if sens == ">=" else x[v] <= s))
                r = [x for x in rech if garde(x)]
                g = [x for x in juge if garde(x)]
                if len(r) < COUVERTURE_MIN * len(rech) or len(g) < COUVERTURE_MIN * len(juge):
                    continue
                candidats.append((par_euro(r), f"{v} {sens} {s:g}", garde, len(r), len(g)))

    if not candidats:
        print("\n  aucune regle ne garde assez de tickets dans les deux moities.")
        return
    candidats.sort(key=lambda x: -x[0])

    print("\n  CINQ MEILLEURES EN RECHERCHE, puis leur valeur sur la moitie JAMAIS REGARDEE :\n")
    print("  %-28s %10s %8s %10s %8s" % ("regle", "recherche", "n", "JUGEMENT", "n"))
    print("  " + "-" * 68)
    for pe, nom, garde, nr, ng in candidats[:5]:
        g = [x for x in juge if garde(x)]
        print("  %-28s %+10.3f %8d %+10.3f %8d" % (nom, pe, nr, par_euro(g), ng))

    # Garde-fou 4 : le meilleur depasse-t-il un tirage au sort de meme taille ?
    pe, nom, garde, nr, _ = candidats[0]
    g = [x for x in juge if garde(x)]
    k = len(g)
    tirages = [par_euro(random.sample(juge, k)) for _ in range(a.tirages)]
    mieux = sum(1 for t in tirages if t >= par_euro(g))
    print(f"\n  La meilleure regle garde {k} tickets sur la moitie de jugement.")
    print(f"  {a.tirages} tirages au sort de {k} tickets dans cette meme moitie donnent :")
    print(f"    mediane {st.median(tirages):+.3f}/euro · "
          f"decile haut {sorted(tirages)[int(.9 * a.tirages)]:+.3f} · "
          f"max {max(tirages):+.3f}")
    print(f"  La regle fait {par_euro(g):+.3f}. {mieux}/{a.tirages} tirages au hasard font aussi "
          f"bien ou mieux ({100 * mieux / a.tirages:.1f} %).")
    if mieux > 0.05 * a.tirages:
        print("  => elle ne se distingue pas du hasard. On ne conclut pas.")
    else:
        print("  => elle depasse le hasard. A confirmer en reel avant d y croire.")


if __name__ == "__main__":
    main()
