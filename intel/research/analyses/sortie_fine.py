"""Le balayage des sorties, refait sur des donnees qui ne mentent pas.

POURQUOI LE REFAIRE. Le balayage de §3.58 (40 combinaisons objectif x stop) concluait « les
quarante cases perdent ». Il tournait sur DexScreener, dont §3.61 a montre qu il est deux fois trop
pessimiste : 33 s entre deux releves quand le moteur decide toutes les 20 s, une source qui se
rafraichit toutes les 30 a 60 s. Sur les memes tickets il annoncait -0,564/euro la ou le carnet reel
encaissait -0,302. **La conclusion a ete retiree** et jamais refaite.

`solana_prix_chaine` donne dix secondes, lues dans les reserves du pool, sans agregateur. C est la
donnee qu il fallait.

ET SURTOUT, POURQUOI CHERCHER LA. §3.70 a mesure que le groupe AGITE -- prix qui bouge fort dans les
premieres minutes -- a la pire moyenne (-0,319/euro) et le meilleur potentiel : **39 % touchent x1,5
et 15 % touchent x3**, contre 2 % dans le groupe calme. Un groupe qui touche souvent haut et finit
bas n est pas forcement perdant : il est mal SORTI. Tenir dix minutes n est pas une strategie, c est
l absence de strategie, et c est pourtant ainsi que tout a ete juge jusqu ici.

DISCIPLINE
  - la sortie au stop rend LE PRIX OBSERVE au releve suivant, jamais le seuil (§3.59) ;
  - la sortie a l objectif rend le releve suivant aussi : on ne se sert pas au pic ;
  - confirmation sur deux releves consecutifs, soit vingt secondes ici contre soixante-six avant ;
  - peage de 2 % ; moitie de recherche / moitie de jugement ; test en avant apres la coupure ;
  - toute moyenne s accompagne de « sans sa meilleure ligne ».

Usage :
    python -m intel.research.sortie_fine
"""
from __future__ import annotations

import argparse
import random
import sqlite3
import statistics as st
import sys

sys.path.insert(0, "/app")

TICKET, PEAGE = 20.0, 0.98
T_ENTREE = 300           # secondes : on entre ici (fin de la fenetre d observation de §3.70)
T_FIN = 900
COUPURE = 1788989940
MIN_MOUVEMENT = 1e-9


def charger(db: str, depuis: int = 0) -> list[dict]:
    """Une entree par pool : son groupe (calme / agite) et sa courbe APRES l entree, en multiples."""
    c = sqlite3.connect("file:" + db + "?mode=ro", uri=True)
    debuts = {p: t for p, t in c.execute(
        "SELECT pair_id, MIN(ts) FROM solana_prix_chaine GROUP BY pair_id")}
    brut: dict[str, list] = {}
    for pid, age, prix, rb, rs in c.execute(
            "SELECT pair_id, age_s, prix_sol, reserve_base, reserve_sol FROM solana_prix_chaine"
            " WHERE prix_sol > 0 ORDER BY pair_id, age_s"):
        if debuts.get(pid, 0) < depuis:
            continue
        brut.setdefault(pid, []).append((int(age), float(prix), float(rb or 0), float(rs or 0)))

    out = []
    for pid, pts in brut.items():
        fen = [p for p in pts if 180 <= p[0] <= T_ENTREE]
        apres = [p for p in pts if T_ENTREE < p[0] <= T_FIN]
        if len(fen) < 6 or len(apres) < 12 or pts[0][0] > 45:
            continue
        px = [p[1] for p in fen]
        med = st.median(px)
        if med <= 0 or fen[-1][1] <= 0:
            continue
        flux = 0.0
        for (_a1, _p1, rb1, rs1), (_a2, _p2, rb2, rs2) in zip(fen, fen[1:]):
            d_base, d_sol = rb2 - rb1, rs2 - rs1
            if abs(d_sol) >= MIN_MOUVEMENT and ((d_sol > 0) != (d_base > 0)):
                flux += d_sol
        p0 = fen[-1][1]
        out.append(dict(pair_id=pid, ne=debuts.get(pid, 0),
                        amplitude=(max(px) - min(px)) / med, flux=flux,
                        serie=[p[1] / p0 for p in apres]))
    out.sort(key=lambda x: x["ne"])
    return out


def rejouer(serie, tp: float, sl: float, suiveur: float | None = None) -> float:
    """Le multiple encaisse. Toute sortie rend le releve SUIVANT, jamais le seuil franchi."""
    haut = 1.0
    for i, m in enumerate(serie):
        suiv = serie[i + 1] if i + 1 < len(serie) else None
        haut = max(haut, m)
        if suiv is None:
            break
        if sl and m <= sl and suiv <= sl:
            return suiv
        if suiveur and m <= haut * (1 - suiveur) and suiv <= haut * (1 - suiveur):
            return suiv
        if tp and m >= tp and suiv >= tp:
            return suiv
    return serie[-1]


def pe(lot, f) -> float:
    return sum(f(x["serie"]) * PEAGE - 1 for x in lot) / len(lot) if lot else float("nan")


def pe_sans_best(lot, f) -> float:
    if len(lot) < 2:
        return float("nan")
    v = sorted(f(x["serie"]) for x in lot)[:-1]
    return sum(m * PEAGE - 1 for m in v) / len(v)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="/app/db/intel.sqlite")
    a = ap.parse_args()
    d = charger(a.db)
    if len(d) < 80:
        print("  %d pools : trop peu." % len(d))
        return
    med = st.median([x["amplitude"] for x in d])
    calme = [x for x in d if x["amplitude"] <= med]
    agite = [x for x in d if x["amplitude"] > med]
    print("  %d pools · entree a T+%ds · resolution 10 s · %d calmes / %d agites" % (
        len(d), T_ENTREE, len(calme), len(agite)))
    print("  tenir sans rien faire : tout %+.3f · calme %+.3f · agite %+.3f" % (
        pe(d, lambda s: s[-1]), pe(calme, lambda s: s[-1]), pe(agite, lambda s: s[-1])))

    grilles = []
    for tp in (1.15, 1.25, 1.4, 1.6, 2.0, 3.0, 0):
        for sl in (0.6, 0.7, 0.8, 0.85, 0):
            grilles.append(("obj x%.2f / stop %.2f" % (tp, sl) if tp else "stop %.2f seul" % sl,
                            (lambda s, t=tp, l=sl: rejouer(s, t, l))))
    for sv in (0.15, 0.25, 0.35):
        for tp in (0, 2.0):
            grilles.append(("suiveur %.0f %%%s" % (100 * sv, " + obj x2" if tp else ""),
                            (lambda s, t=tp, v=sv: rejouer(s, t, 0, v))))

    for nom_g, lot in (("AGITE  (39 % touchent x1,5)", agite), ("CALME", calme)):
        print("\n  === %s : n=%d ===" % (nom_g, len(lot)))
        n = len(lot) // 2
        rech, juge = lot[:n], lot[n:]
        res = []
        for nom, f in grilles:
            res.append((pe(rech, f), pe(juge, f), pe_sans_best(juge, f), nom, f))
        res.sort(key=lambda x: -x[0])
        print("     %-26s %10s %10s %10s" % ("sortie", "recherche", "JUGEMENT", "sans best"))
        print("     " + "-" * 60)
        for pr, pj, ps, nom, _f in res[:6]:
            print("     %-26s %+10.3f %+10.3f %+10.3f%s" % (
                nom, pr, pj, ps, "  <==" if pr > 0 and pj > 0 else ""))
        tient = [r for r in res if r[0] > 0 and r[1] > 0]
        print("     positives des DEUX cotes : %d / %d" % (len(tient), len(res)))
        if tient:
            pr, pj, ps, nom, f = max(tient, key=lambda r: min(r[0], r[1]))
            print("     la plus solide : %s  (%+.3f / %+.3f, sans best %+.3f)" % (nom, pr, pj, ps))

    print("\n  === TEST EN AVANT, courbes nees apres la coupure ===")
    av = charger(a.db, COUPURE)
    if len(av) < 60:
        print("     %d pools : on ne conclut pas." % len(av))
        return
    ag = [x for x in av if x["amplitude"] > med]
    ca = [x for x in av if x["amplitude"] <= med]
    print("     %d pools (%d agites / %d calmes)" % (len(av), len(ag), len(ca)))
    print("     %-26s %10s %10s %10s %9s" % ("sortie", "agite", "sans best", "calme", "hasard"))
    print("     " + "-" * 70)
    random.seed(1)
    interessantes = [g for g in grilles if any(k in g[0] for k in ("x1.25", "x1.40", "x1.60", "suiveur", "x2.00"))][:8]
    for nom, f in interessantes:
        v = pe(ag, f)
        ech = [pe(random.sample(av, len(ag)), f) for _ in range(1500)]
        m = sum(1 for e in ech if e >= v)
        print("     %-26s %+10.3f %+10.3f %+10.3f %8.1f %%" % (
            nom, v, pe_sans_best(ag, f), pe(ca, f), 100 * m / 1500))


if __name__ == "__main__":
    main()
