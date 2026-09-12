"""Croiser TOUT : reseaux sociaux x forme du prix x sortie. Chercher ce qui gagne, pas ce qui survit.

L operateur, le 12/09 : « je veux chercher un truc qui gagne de l argent, Telegram fonctionne sur une
duree de vie limitee ou un truc comme ca, croise tout ».

L indice est dans les chiffres de S3.72, et je ne l avais pas suivi :

    nb reseaux    n      vides   x>=1,5   x>=3
        0       1 288     11 %    23 %     9 %
        3         142     51 %    49 %    13 %

Les jetons AVEC reseaux touchent x1,5 deux fois plus souvent, et meurent deux fois plus. Ils montent
puis s effondrent. Juges sur « tenir quinze minutes » ils sont catastrophiques (-0,394/euro) -- mais
tenir n est pas une strategie, c est l absence de strategie. Avec une sortie rapide, le meme groupe
pourrait etre le meilleur.

Ce fichier balaye la grille complete : presence sociale x forme du prix x objectif x stop, sur les
courbes a dix secondes, avec la discipline du projet :

  - toute sortie rend le PRIX OBSERVE au releve suivant, jamais le seuil franchi (S3.59) ;
  - confirmation sur deux releves consecutifs -- vingt secondes ici ;
  - peage de 2 % ; moitie de recherche / moitie de jugement par date de naissance ;
  - toute moyenne s accompagne de « sans sa meilleure ligne », six resultats de la semaine tenant
    sur une seule.

Usage :
    python -m intel.research.croise
"""
from __future__ import annotations

import argparse
import sqlite3
import statistics as st
import sys

sys.path.insert(0, "/app")

PEAGE = 0.98
T_DECISION = 90
T_FIN = 900


def jeu(db: str) -> list[dict]:
    c = sqlite3.connect("file:" + db + "?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    brut: dict[str, list] = {}
    mint: dict[str, str] = {}
    naiss: dict[str, int] = {}
    for r in c.execute("SELECT pair_id, mint, ts, age_s, prix_sol, reserve_sol FROM solana_prix_chaine"
                       " WHERE prix_sol > 0 ORDER BY pair_id, age_s"):
        brut.setdefault(r["pair_id"], []).append((int(r["age_s"]), float(r["prix_sol"]), float(r["reserve_sol"] or 0)))
        mint[r["pair_id"]] = r["mint"]
        naiss[r["pair_id"]] = min(naiss.get(r["pair_id"], 1 << 40), int(r["ts"]))
    soc = {r["mint"]: dict(r) for r in c.execute("SELECT * FROM solana_social WHERE lu=1")}

    out = []
    for pid, pts in brut.items():
        s = soc.get(mint.get(pid))
        if not s:
            continue
        avant = [p for p in pts if p[0] <= T_DECISION]
        apres = [p for p in pts if T_DECISION < p[0] <= T_FIN]
        if len(avant) < 4 or avant[0][0] > 45 or len(apres) < 6:
            continue
        p0 = avant[0][1]
        pv = [p[1] / p0 for p in avant]
        pd = avant[-1][1]
        if pd <= 0:
            continue
        out.append(dict(
            pair_id=pid, ne=naiss.get(pid, 0),
            reseaux=int(s["twitter"] or 0) + int(s["telegram"] or 0) + int(s["site"] or 0),
            telegram=int(s["telegram"] or 0), twitter=int(s["twitter"] or 0),
            signes=int(pv[-1] - 1 >= 0.007) + int(min(pv) - 1 >= 0) +
                   int(((avant[-1][2] / avant[0][2] - 1) if avant[0][2] > 0 else 0) >= 0.0035),
            serie=[(p[0] - T_DECISION, p[1] / pd) for p in apres],
        ))
    out.sort(key=lambda x: x["ne"])
    return out


def sortie(serie, tp: float, sl: float, minutes: float) -> float:
    """Le multiple encaisse. Toute sortie rend le releve SUIVANT, jamais le seuil."""
    fen = [(a, m) for a, m in serie if a <= minutes * 60]
    for i, (_a, m) in enumerate(fen):
        suiv = fen[i + 1][1] if i + 1 < len(fen) else None
        if suiv is None:
            break
        if sl and m <= sl and suiv <= sl:
            return suiv
        if tp and m >= tp and suiv >= tp:
            return suiv
    return fen[-1][1] if fen else 1.0


def pe(lot, tp, sl, mn) -> float:
    return sum(sortie(x["serie"], tp, sl, mn) * PEAGE - 1 for x in lot) / len(lot) if lot else float("nan")


def sans_best(lot, tp, sl, mn) -> float:
    v = sorted(sortie(x["serie"], tp, sl, mn) for x in lot)[:-1]
    return sum(m * PEAGE - 1 for m in v) / len(v) if v else float("nan")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="/app/db/intel.sqlite")
    a = ap.parse_args()
    d = jeu(a.db)
    print("  %d lancements avec courbe ET fiche sociale" % len(d))
    if len(d) < 300:
        print("  trop peu"); return
    n = len(d) // 2
    rech, juge = d[:n], d[n:]

    GROUPES = {
        "0 reseau": lambda x: x["reseaux"] == 0,
        "1 reseau": lambda x: x["reseaux"] == 1,
        "2-3 reseaux": lambda x: x["reseaux"] >= 2,
        "telegram": lambda x: x["telegram"] == 1,
        "0 res. + 0-1 signe": lambda x: x["reseaux"] == 0 and x["signes"] < 2,
        "2-3 res. + 2-3 signes": lambda x: x["reseaux"] >= 2 and x["signes"] >= 2,
    }
    SORTIES = [("tenir 15 min", 0, 0, 15), ("tenir 5 min", 0, 0, 5), ("tenir 2 min", 0, 0, 2),
               ("obj x1,2 / 15 min", 1.2, 0, 15), ("obj x1,3 / 15 min", 1.3, 0, 15),
               ("obj x1,5 / 15 min", 1.5, 0, 15), ("obj x2 / 15 min", 2.0, 0, 15),
               ("obj x1,3 stop 0,7", 1.3, 0.7, 15), ("obj x1,5 stop 0,7", 1.5, 0.7, 15),
               ("obj x1,5 stop 0,5", 1.5, 0.5, 15), ("obj x1,2 / 5 min", 1.2, 0, 5),
               ("obj x1,5 / 5 min", 1.5, 0, 5)]

    print("\n  PAR EURO — recherche / JUGEMENT (n recherche)")
    print("  %-22s" % "" + "".join("%-15s" % g[:14] for g in GROUPES))
    print("  " + "-" * (22 + 15 * len(GROUPES)))
    gagnants = []
    for nom, tp, sl, mn in SORTIES:
        ligne = "  %-22s" % nom
        for gn, gf in GROUPES.items():
            r = [x for x in rech if gf(x)]
            j = [x for x in juge if gf(x)]
            if len(r) < 30 or len(j) < 30:
                ligne += "%-15s" % "  -"
                continue
            a_, b_ = pe(r, tp, sl, mn), pe(j, tp, sl, mn)
            ligne += "%-15s" % ("%+.2f/%+.2f" % (a_, b_))
            if a_ > 0 and b_ > 0:
                gagnants.append((min(a_, b_), nom, gn, a_, b_, gf, tp, sl, mn, len(r), len(j)))
        print(ligne)

    print("\n  COMBINAISONS POSITIVES DES DEUX COTES : %d" % len(gagnants))
    gagnants.sort(reverse=True)
    for _k, nom, gn, a_, b_, gf, tp, sl, mn, nr, nj in gagnants[:8]:
        j = [x for x in juge if gf(x)]
        print("    %-22s %-20s recherche %+.3f (n=%d) · JUGEMENT %+.3f (n=%d) · sans best %+.3f"
              % (nom, gn, a_, nr, b_, nj, sans_best(j, tp, sl, mn)))


if __name__ == "__main__":
    main()
