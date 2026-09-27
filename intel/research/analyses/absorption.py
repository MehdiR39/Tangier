"""Un prix qui se stabilise PENDANT que les achats continuent : signal ou pas ?

Question de l operateur le 10/09, plus fine que les precedentes. Jusqu ici j ai mesure le prix seul
(§3.66) et le flux seul (§3.70). Lui decrit une CONJONCTION : le prix cesse de bouger tandis que
l argent continue d entrer. C est le schema d absorption -- quelqu un encaisse l offre sans laisser
le prix descendre -- et c est un tout autre objet que ses deux composantes prises separement.

Le contraire se lit aussi : prix plat avec flux VENDEUR, c est une distribution, quelqu un sort
sans casser le prix.

CE QU ON MESURE, sur les dix secondes de resolution de `solana_prix_chaine` :

  fenetre d observation   T+180 s a T+300 s   (les deux minutes avant la decision)
  decision                T+300 s
  resultat                T+300 s a T+900 s   (dix minutes)

  amplitude   (max - min) / mediane sur la fenetre         bas = plat
  compression amplitude de la fenetre / amplitude du debut  bas = la volatilite se comprime
  derive      |dernier / premier - 1|                       bas = pas de tendance
  flux        SOL net entre par les echanges sur la fenetre (voir flux.py pour la methode)
  absorption  flux positif ET amplitude basse -- la conjonction demandee

DISCIPLINE : moitie de recherche / moitie de jugement par date de naissance, test en avant sur les
courbes nees apres la coupure du 09/09 21h39, peage de 2 %, comparaison contre le hasard, et pour
toute moyenne le calcul « sans sa meilleure ligne » -- six resultats de la semaine tenaient sur une
seule ligne.

Usage :
    python -m intel.research.absorption
"""
from __future__ import annotations

import argparse
import random
import sqlite3
import statistics as st
import sys

sys.path.insert(0, "/app")

TICKET, PEAGE = 20.0, 0.98
T_DEBUT = 180            # secondes : debut de la fenetre d observation
T_DECISION = 300         # secondes : on decide ici
T_FIN = 900              # secondes : horizon de resultat
COUPURE = 1788989940
MIN_MOUVEMENT = 1e-9


def _flux(seq) -> float:
    """SOL net entre par les ECHANGES sur une suite de (age, prix, reserve_base, reserve_sol).

    Les deux reserves qui bougent dans le meme sens sont un depot ou un retrait de liquidite, pas un
    echange, et sont ecartees : sans cela un retrait ressemble a une vente geante (§3.70).
    """
    net = 0.0
    for (_a1, _p1, rb1, rs1), (_a2, _p2, rb2, rs2) in zip(seq, seq[1:]):
        d_base, d_sol = rb2 - rb1, rs2 - rs1
        if abs(d_sol) < MIN_MOUVEMENT:
            continue
        if d_sol > 0 and d_base < 0:
            net += d_sol
        elif d_sol < 0 and d_base > 0:
            net += d_sol
    return net


def _amplitude(seq) -> float | None:
    px = [p[1] for p in seq]
    if len(px) < 3:
        return None
    m = st.median(px)
    return ((max(px) - min(px)) / m) if m > 0 else None


def cas(db: str, depuis: int = 0) -> list[dict]:
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
        tot = [p for p in pts if p[0] <= T_DECISION]
        fen = [p for p in pts if T_DEBUT <= p[0] <= T_DECISION]
        debut = [p for p in pts if p[0] < T_DEBUT]
        apres = [p for p in pts if T_DECISION < p[0] <= T_FIN]
        if len(fen) < 6 or len(debut) < 6 or len(apres) < 8 or tot[0][0] > 45:
            continue
        amp = _amplitude(fen)
        amp0 = _amplitude(debut)
        if amp is None or amp0 is None:
            continue
        p_dec = fen[-1][1]
        if p_dec <= 0:
            continue
        f = _flux(fen)
        res = fen[0][3]
        pa = [p[1] / p_dec for p in apres]
        ra = [p[3] for p in apres]
        out.append(dict(
            pair_id=pid, ne=debuts.get(pid, 0),
            amplitude=amp, amplitude_debut=amp0,
            compression=(amp / amp0) if amp0 > 0 else None,
            derive=abs(fen[-1][1] / fen[0][1] - 1.0) if fen[0][1] > 0 else None,
            flux=f, flux_relatif=(f / res) if res > 0 else None,
            liq=res,
            # la conjonction demandee : ca achete ET le prix ne bouge presque plus
            absorbe=int(f > 0 and amp is not None),
            suite=pa[-1] - 1.0,
            suite_pic=max(pa) - 1.0,
            rug=int(min(ra) < 0.2 * fen[-1][3]) if fen[-1][3] > 0 else 0,
        ))
    out.sort(key=lambda x: x["ne"])
    return out


def pe(lot) -> float:
    return sum((1 + x["suite"]) * PEAGE - 1 for x in lot) / len(lot) if lot else float("nan")


def pe_sans_meilleur(lot) -> float:
    if len(lot) < 2:
        return float("nan")
    s = sorted(x["suite"] for x in lot)[:-1]
    return sum((1 + v) * PEAGE - 1 for v in s) / len(s)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="/app/db/intel.sqlite")
    a = ap.parse_args()
    d = cas(a.db)
    print("  %d pools observes de T+%ds a T+%ds, resultat jusqu a T+%ds" % (len(d), T_DEBUT, T_DECISION, T_FIN))
    if len(d) < 60:
        print("  trop peu pour conclure.")
        return
    print("  reference : %+.3f/euro · mediane %+.1f %% · %.0f %% de vides" % (
        pe(d), 100 * st.median([x["suite"] for x in d]), 100 * sum(x["rug"] for x in d) / len(d)))

    print("\n  1. LA CONJONCTION : prix plat ET flux acheteur")
    med_amp = st.median([x["amplitude"] for x in d])
    print("     amplitude mediane de la fenetre : %.1f %% (seuil « plat » = sous la mediane)" % (100 * med_amp))
    print("     %-26s %5s %10s %10s %8s %8s" % ("groupe", "n", "moy /euro", "sans best", "mediane", "x>=1.5"))
    print("     " + "-" * 74)
    groupes = {
        "plat + achete  (absorption)": lambda x: x["amplitude"] <= med_amp and x["flux"] > 0,
        "plat + vend  (distribution)": lambda x: x["amplitude"] <= med_amp and x["flux"] <= 0,
        "bouge + achete": lambda x: x["amplitude"] > med_amp and x["flux"] > 0,
        "bouge + vend": lambda x: x["amplitude"] > med_amp and x["flux"] <= 0,
    }
    for nom, g in groupes.items():
        lot = [x for x in d if g(x)]
        if len(lot) < 15:
            print("     %-26s %5d  (trop peu)" % (nom, len(lot)))
            continue
        p = [1 + x["suite_pic"] for x in lot]
        print("     %-26s %5d %+10.3f %+10.3f %+8.1f %% %7.0f %%" % (
            nom, len(lot), pe(lot), pe_sans_meilleur(lot),
            100 * st.median([x["suite"] for x in lot]),
            100 * sum(1 for v in p if v >= 1.5) / len(p)))

    print("\n  2. LA MEME CONJONCTION, MOITIE PAR MOITIE (la question qui tranche)")
    n = len(d) // 2
    rech, juge = d[:n], d[n:]
    med_r = st.median([x["amplitude"] for x in rech])          # seuil pris sur la recherche seule
    print("     %-26s %10s %5s %10s %5s %10s" % ("groupe", "recherche", "n", "JUGEMENT", "n", "sans best"))
    print("     " + "-" * 74)
    for nom, g in groupes.items():
        gr = (lambda x, g=g, m=med_r: (x["amplitude"] <= m) == (x["amplitude"] <= med_amp) and g(x))
        r = [x for x in rech if g(x)]
        j = [x for x in juge if g(x)]
        if len(r) < 12 or len(j) < 12:
            continue
        print("     %-26s %+10.3f %5d %+10.3f %5d %+10.3f%s" % (
            nom, pe(r), len(r), pe(j), len(j), pe_sans_meilleur(j),
            "  <== positif des deux cotes" if pe(r) > 0 and pe(j) > 0 else ""))

    print("\n  3. CHAQUE COMPOSANTE SEULE, pour voir si la conjonction apporte quelque chose")
    for var, sens in (("amplitude", "<="), ("compression", "<="), ("derive", "<="),
                      ("flux", ">="), ("flux_relatif", ">=")):
        vals = sorted(x[var] for x in rech if x.get(var) is not None)
        if len(vals) < 40:
            continue
        s = vals[len(vals) // 2]
        g = (lambda x, v=var, s=s, sn=sens: x.get(v) is not None and (x[v] >= s if sn == ">=" else x[v] <= s))
        r = [x for x in rech if g(x)]
        j = [x for x in juge if g(x)]
        if len(r) < 15 or len(j) < 15:
            continue
        print("     %-26s %+10.3f %5d %+10.3f %5d" % ("%s %s %.4g" % (var, sens, s), pe(r), len(r), pe(j), len(j)))

    print("\n  4. TEST EN AVANT (courbes nees apres la coupure, jamais regardees)")
    av = cas(a.db, COUPURE)
    if len(av) < 40:
        print("     %d pools seulement : on ne conclut pas." % len(av))
        return
    med_av = med_amp
    print("     reference %+.3f/euro (n=%d)" % (pe(av), len(av)))
    for nom, g in groupes.items():
        lot = [x for x in av if g(x)]
        if len(lot) < 12:
            continue
        random.seed(1)
        ech = [pe(random.sample(av, len(lot))) for _ in range(3000)]
        m = sum(1 for e in ech if e >= pe(lot))
        print("     %-26s %+.3f/euro (n=%d) · sans best %+.3f · hasard %.1f %%" % (
            nom, pe(lot), len(lot), pe_sans_meilleur(lot), 100 * m / 3000))


if __name__ == "__main__":
    main()
