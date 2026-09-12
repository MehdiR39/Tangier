"""Le flux acheteur/vendeur est-il un signal ? La version en ARGENT, pas en nombre.

Question de l operateur le 10/09, en regardant l onglet Txns de DexScreener : on y voit chaque
echange, son sens et son montant en dollars. Est-ce que ca dit quelque chose ?

DEUX VERSIONS DE LA QUESTION, et une seule a ete testee :

  1. LE NOMBRE d echanges. `buys_h1` et le rapport achats/ventes a T+1 h : passes dans les 36 regles
     de §3.69, aucune ne tient. C est attendu -- cent achats d un dollar coutent un dollar de frais
     et fabriquent une belle colonne verte.

  2. LE MONTANT. Un achat de 435 $ et un achat de 4 $ comptent pareil dans le nombre, et pas du tout
     dans le carnet. Le montant coute ce qu il pese, il est donc bien plus difficile a simuler.
     JAMAIS TESTE -- DexScreener ne separe pas le volume par sens.

ON LE CALCULE A LA SOURCE. `solana_prix_chaine` lit les DEUX reserves du pool toutes les dix
secondes des T+12 s. Entre deux releves :

    reserve SOL monte ET reserve jeton baisse   -> un ACHAT est passe, de ce montant en SOL
    reserve SOL baisse ET reserve jeton monte   -> une VENTE
    les deux bougent dans le MEME sens          -> depot ou retrait de liquidite, pas un echange

Le troisieme cas est ce qui separe un flux d un mouvement de liquidite, et il faut l ecarter : un
retrait de liquidite ressemble a une vente geante quand on ne regarde qu un cote du pool.

CE QUE LA RESOLUTION PERMET ET NE PERMET PAS. Plusieurs echanges dans la meme fenetre de dix
secondes se compensent avant d etre vus. Le FLUX NET sur les quatre-vingt-dix secondes reste donc
exact -- il se telescope, les compensations internes s annulent de toute facon -- mais le VOLUME
BRUT et le nombre d echanges sont des bornes inferieures. On ne conclut donc rien du nombre ici ;
c est le net qui est mesure.

DISCIPLINE : moitie de recherche / moitie de jugement par date de naissance, test en avant sur les
courbes nees apres la coupure du 09/09 21h39, peage de 2 % deduit, comparaison contre le hasard.

Usage :
    python -m intel.research.flux
    python -m intel.research.flux --avant
"""
from __future__ import annotations

import argparse
import random
import sqlite3
import statistics as st
import sys

sys.path.insert(0, "/app")

TICKET, PEAGE = 20.0, 0.98
T_DECISION = 90
T_FIN = 900
COUPURE = 1788989940
MIN_MOUVEMENT = 1e-9          # sous ce seuil une reserve n a pas bouge : bruit d arrondi


def flux(db: str, depuis: int = 0) -> list[dict]:
    """Une entree par pool : le flux d argent avant T+90 s, et ce qui arrive apres."""
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
        avant = [p for p in pts if p[0] <= T_DECISION]
        apres = [p for p in pts if T_DECISION < p[0] <= T_FIN]
        if len(avant) < 4 or avant[0][0] > 45 or len(apres) < 6:
            continue
        p0 = avant[0][1]
        if p0 <= 0:
            continue

        achats = ventes = liq_ajout = liq_retrait = 0.0
        n_a = n_v = 0
        for (a1, _p1, rb1, rs1), (_a2, _p2, rb2, rs2) in zip(avant, avant[1:]):
            d_base, d_sol = rb2 - rb1, rs2 - rs1
            if abs(d_sol) < MIN_MOUVEMENT:
                continue
            if d_sol > 0 and d_base < 0:            # du SOL entre, du jeton sort : un achat
                achats += d_sol
                n_a += 1
            elif d_sol < 0 and d_base > 0:          # l inverse : une vente
                ventes += -d_sol
                n_v += 1
            elif d_sol > 0:                          # les deux montent : depot de liquidite
                liq_ajout += d_sol
            else:                                    # les deux baissent : retrait
                liq_retrait += -d_sol

        volume = achats + ventes
        pv = [p[1] / p0 for p in avant]
        pa = [p[1] / p0 for p in apres]
        ra = [p[3] for p in apres]
        rv = [p[3] for p in avant]
        out.append(dict(
            pair_id=pid, ne=debuts.get(pid, 0),
            # ce qu on VOIT avant de decider -- en argent
            flux_net=achats - ventes,
            desequilibre=((achats - ventes) / volume) if volume > 0 else None,
            volume_sol=volume,
            achats_sol=achats, ventes_sol=ventes,
            part_achats=(achats / volume) if volume > 0 else None,
            n_achats=n_a, n_ventes=n_v,
            ratio_nombre=(n_a / max(n_v, 1)) if (n_a + n_v) > 0 else None,
            taille_moy=(volume / (n_a + n_v)) if (n_a + n_v) > 0 else None,
            liq_ajout=liq_ajout, liq_retrait=liq_retrait,
            liq_debut=rv[0],
            # rapporte a la taille du pool : 5 SOL de flux net sur un pool de 10 SOL n est pas
            # la meme chose que 5 SOL sur un pool de 500
            flux_relatif=((achats - ventes) / rv[0]) if rv[0] > 0 else None,
            volume_relatif=(volume / rv[0]) if rv[0] > 0 else None,
            # ce qui ARRIVE ensuite
            suite=pa[-1] / pv[-1] - 1.0,
            suite_pic=max(pa) / pv[-1] - 1.0,
            rug=int(min(ra) < 0.2 * rv[-1]) if rv[-1] > 0 else 0,
        ))
    out.sort(key=lambda x: x["ne"])
    return out


def par_euro(lot) -> float:
    return sum((1 + x["suite"]) * PEAGE - 1 for x in lot) / len(lot) if lot else 0.0


def taux_rug(lot) -> float:
    return 100 * sum(x["rug"] for x in lot) / len(lot) if lot else float("nan")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="/app/db/intel.sqlite")
    ap.add_argument("--avant", action="store_true", help="seulement les courbes nees apres la coupure")
    a = ap.parse_args()

    d = flux(a.db, COUPURE if a.avant else 0)
    print("  %d pools%s · reference %+.3f/euro · %.0f %% de vides" % (
        len(d), " (test en avant)" if a.avant else "", par_euro(d), taux_rug(d)))
    if len(d) < 60:
        print("  trop peu pour conclure.")
        return

    print("\n  1. A QUOI RESSEMBLE LE FLUX DES 90 PREMIERES SECONDES")
    for nom, cle, unite in (("flux net", "flux_net", "SOL"), ("volume echange", "volume_sol", "SOL"),
                            ("part des achats", "part_achats", ""), ("taille moyenne", "taille_moy", "SOL"),
                            ("flux / taille du pool", "flux_relatif", "")):
        v = [x[cle] for x in d if x.get(cle) is not None]
        if not v:
            continue
        print("     %-24s mediane %+9.3f %-4s  10e %+9.3f  90e %+9.3f" % (
            nom, st.median(v), unite, sorted(v)[len(v) // 10], sorted(v)[9 * len(v) // 10]))
    pos = 100 * sum(1 for x in d if (x["flux_net"] or 0) > 0) / len(d)
    print("     %-24s %.0f %% des pools ont un flux net ACHETEUR" % ("sens", pos))
    sans = sum(1 for x in d if not x["volume_sol"])
    print("     %-24s %d pools sans aucun echange detecte (%.0f %%)" % ("silence", sans, 100 * sans / len(d)))

    print("\n  2. LE FLUX ANNONCE-T-IL LA SUITE ? (recherche / jugement)")
    n = len(d) // 2
    rech, juge = d[:n], d[n:]
    print("     %-30s %9s %5s %9s %5s %8s" % ("regle", "recherche", "n", "JUGEMENT", "n", "vides"))
    print("     " + "-" * 72)
    print("     %-30s %+9.3f %5d %+9.3f %5d %7.0f %%" % (
        "reference : tout", par_euro(rech), len(rech), par_euro(juge), len(juge), taux_rug(juge)))
    cands = []
    for var in ("flux_net", "desequilibre", "part_achats", "volume_sol", "taille_moy",
                "ratio_nombre", "flux_relatif", "volume_relatif"):
        vals = sorted(x[var] for x in rech if x.get(var) is not None)
        if len(vals) < 40:
            continue
        for q in (0.25, 0.5, 0.75):
            seuil = vals[int(len(vals) * q)]
            for sens in (">=", "<="):
                g = (lambda x, v=var, s=seuil, sn=sens: x.get(v) is not None and
                     (x[v] >= s if sn == ">=" else x[v] <= s))
                r = [x for x in rech if g(x)]
                j = [x for x in juge if g(x)]
                if len(r) < 25 or len(j) < 25:
                    continue
                cands.append((par_euro(r), par_euro(j), "%s %s %.4g" % (var, sens, seuil), len(r), len(j), g))
    cands.sort(key=lambda x: -x[0])
    for pr, pj, nom, nr, nj, g in cands[:10]:
        print("     %-30s %+9.3f %5d %+9.3f %5d %7.0f %%%s" % (
            nom, pr, nr, pj, nj, taux_rug([x for x in juge if g(x)]),
            "  <== positif des deux cotes" if pr > 0 and pj > 0 else ""))
    tient = [c for c in cands if c[0] > 0 and c[1] > 0]
    print("     regles positives des DEUX cotes : %d / %d" % (len(tient), len(cands)))

    if tient:
        pr, pj, nom, nr, nj, g = max(tient, key=lambda c: min(c[0], c[1]))
        lot = [x for x in juge if g(x)]
        random.seed(1)
        ech = [par_euro(random.sample(juge, len(lot))) for _ in range(5000)]
        mieux = sum(1 for e in ech if e >= pj)
        print("\n  3. TEST DU HASARD sur la plus solide : %s" % nom)
        print("     la regle fait %+.3f/euro sur %d tickets" % (pj, len(lot)))
        print("     5000 tirages de %d : mediane %+.3f · decile haut %+.3f" % (
            len(lot), st.median(ech), sorted(ech)[4500]))
        print("     %d/5000 font aussi bien ou mieux (%.1f %%) -> %s" % (
            mieux, 100 * mieux / 5000,
            "DEPASSE le hasard" if mieux < 250 else "ne se distingue pas du hasard"))

    print("\n  4. LE NOMBRE CONTRE LE MONTANT, sur le meme echantillon")
    for nom, cle in (("le NOMBRE (ratio achats/ventes)", "ratio_nombre"),
                     ("le MONTANT (desequilibre en SOL)", "desequilibre")):
        v = [(x[cle], x["suite"]) for x in d if x.get(cle) is not None]
        if len(v) < 40:
            continue
        v.sort()
        q = len(v) // 4
        bas = [s for _k, s in v[:q]]
        haut = [s for _k, s in v[-q:]]
        print("     %-34s quartile bas %+6.1f %%  ·  quartile haut %+6.1f %%  ·  ecart %+6.1f points" % (
            nom, 100 * st.median(bas), 100 * st.median(haut), 100 * (st.median(haut) - st.median(bas))))


if __name__ == "__main__":
    main()
