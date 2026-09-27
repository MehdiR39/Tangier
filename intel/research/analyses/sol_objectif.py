"""L objectif de sortie est-il regle trop haut ?

Constat du 09/09 sur les dix derniers tickets : presque tous touchent x1,10 a x1,25, deux seulement
depassent x1,40. L objectif de production est a x1,50. On refuserait donc un gain qui existe pour
attendre un gain qui n arrive presque jamais, et on repartirait au stop.

Ce fichier rejoue les courbes de `solana_suivi` sur une grille objectif x stop. Trois disciplines,
toutes apprises a nos depens :

  1. RECHERCHE SUR LA PREMIERE MOITIE, JUGEMENT SUR LA SECONDE. Un balayage trouve toujours un
     maximum ; seul un echantillon jamais regarde dit s il vaut quelque chose (§3.45).
  2. SORTIE CONFIRMEE SUR DEUX RELEVES CONSECUTIFS. 7 % des ecarts entre deux points depassent
     20 % : un pic isole cree un objectif atteint qui n a jamais existe (§3.54).
  3. PEAGE DE 2 %, fixe, quelle que soit la taille. C est du frais de place, pas de l impact.

Usage :
    python -m intel.research.sol_objectif
"""
from __future__ import annotations

import argparse
import sqlite3
import sys

sys.path.insert(0, "/app")

TICKET = 20.0
PEAGE = 0.98
ENTREE_MIN = 2.0        # minutes : l age auquel le moteur juge et achete
FENETRE = 30.0          # minutes : duree de detention maximale en production


def courbes(db: str) -> list[tuple[int, list[tuple[float, float]]]]:
    """(horodatage d entree, [(age_min, multiple)]) pour chaque lancement suivi."""
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    brut: dict[str, list[tuple[float, float, int]]] = {}
    for pid, age, px, ts in c.execute(
            "SELECT pair_id, age_min, price_usd, ts FROM solana_suivi WHERE price_usd>0 "
            "ORDER BY pair_id, age_min"):
        brut.setdefault(pid, []).append((float(age), float(px), int(ts)))
    out = []
    for pts in brut.values():
        if len(pts) < 8:
            continue
        ent = [p for p in pts if p[0] >= ENTREE_MIN]
        if not ent:
            continue
        a0, px0, ts0 = ent[0]
        if px0 <= 0:
            continue
        serie = [(a, px / px0) for a, px, _ in pts if a0 < a <= a0 + FENETRE]
        if len(serie) >= 3:
            out.append((ts0, serie))
    out.sort(key=lambda x: x[0])
    return out


def rejouer(serie: list[tuple[float, float]], tp: float, sl: float) -> float:
    """Le multiple encaisse, peage non deduit. Sortie confirmee sur deux releves."""
    for i, (_a, m) in enumerate(serie):
        suiv = serie[i + 1][1] if i + 1 < len(serie) else None
        if suiv is None:
            break
        if m >= tp and suiv >= tp:
            return tp                       # on sort a l objectif, pas au pic
        if m <= sl and suiv <= sl:
            return suiv                     # on sort au prix reel, pas au seuil
    return serie[-1][1]


def score(jeu, tp: float, sl: float) -> tuple[float, float, int]:
    """(euros par euro mise, euros totaux, nombre de tickets)."""
    tot = sum((rejouer(s, tp, sl) * PEAGE - 1) * TICKET for _t, s in jeu)
    return tot / (len(jeu) * TICKET), tot, len(jeu)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="/app/db/intel.sqlite")
    a = ap.parse_args()

    jeu = courbes(a.db)
    n = len(jeu) // 2
    rech, juge = jeu[:n], jeu[n:]
    print(f"  {len(jeu)} lancements suivis · recherche {len(rech)} · jugement {len(juge)}\n")

    OBJ = [1.05, 1.10, 1.15, 1.20, 1.25, 1.30, 1.40, 1.50]
    STOP = [0.60, 0.70, 0.75, 0.80, 0.85]

    print("  PAR EURO MISE, SUR LA MOITIE DE RECHERCHE")
    print("  stop \ obj " + "".join(f"{o:>8.2f}" for o in OBJ))
    best = None
    for sl in STOP:
        ligne = f"  {sl:>10.2f} "
        for tp in OBJ:
            v = score(rech, tp, sl)[0]
            ligne += f"{v:>+8.3f}"
            if best is None or v > best[0]:
                best = (v, tp, sl)
        print(ligne)

    v, tp, sl = best
    print(f"\n  meilleur en recherche : objectif x{tp} · stop {sl} · {v:+.3f}/euro")
    print("  -- on le juge maintenant sur la moitie JAMAIS REGARDEE --\n")

    for nom, t, s in (("production actuelle", 1.5, 0.7), ("meilleur trouve", tp, sl)):
        pe, tot, k = score(juge, t, s)
        print(f"  {nom:<22} objectif x{t:<5} stop {s:<5} {pe:+.3f}/euro  {tot:+8.2f} EUR sur {k} tickets")

    print("\n  toute la grille sur la moitie de jugement :")
    print("  stop \ obj " + "".join(f"{o:>8.2f}" for o in OBJ))
    for s in STOP:
        print(f"  {s:>10.2f} " + "".join(f"{score(juge, o, s)[0]:>+8.3f}" for o in OBJ))


if __name__ == "__main__":
    main()
