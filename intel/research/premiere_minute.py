"""Que se passe-t-il pendant la premiere minute, et est-ce que ca annonce la suite ?

Question restee sans reponse depuis le debut du projet parce qu aucune donnee ne couvrait cette
periode : DexScreener n indexe pas les pools avant ~T+1,5 min. `intel/engines/prix_chaine.py` lit
desormais les reserves du pool toutes les dix secondes des T+12 s (§3.65), ce qui la rend mesurable.

TROIS QUESTIONS, dans cet ordre :

  1. A QUOI RESSEMBLE LA PREMIERE MINUTE ? Personne dans ce projet ne l a jamais vue. Amplitude,
     sens, vitesse du depot de liquidite.
  2. ANNONCE-T-ELLE LA SUITE ? Correlation entre ce qui se passe avant T+90 s et ce qui se passe
     apres. C est la seule question qui vaut de l argent.
  3. LE RETRAIT DE LIQUIDITE SE VOIT-IL VENIR ? La reserve SOL est lue a chaque releve : un pool
     qui se vide est visible en dix secondes. Le voit-on baisser AVANT l effondrement du prix, ou
     seulement pendant ?

DISCIPLINE, la meme que partout ailleurs dans ce projet :
  - recherche sur la premiere moitie chronologique, jugement sur la seconde jamais regardee ;
  - toute conclusion s accompagne de sa taille d echantillon, et sous ~100 courbes on ecrit
    « on ne conclut pas » ;
  - le peage de 2 % est deduit de tout resultat exprime en argent ;
  - une comparaison se fait contre le hasard, jamais contre zero.

Usage :
    python -m intel.research.premiere_minute
    python -m intel.research.premiere_minute --minimum 100
"""
from __future__ import annotations

import argparse
import random
import sqlite3
import statistics as st
import sys

sys.path.insert(0, "/app")

TICKET, PEAGE = 20.0, 0.98
T_DECISION = 90          # secondes : la frontiere entre « ce qu on voit » et « ce qu on gagne »
T_FIN = 900              # secondes : horizon de resultat

# HORODATAGE DE COUPURE. Le 09/09 a 21h39 j avais regarde les 139 premieres courbes et en avais
# tire une regle : un lancement montrant deux ou trois signes « trop beau » pendant ses quatre-vingt-
# dix premieres secondes -- prix en hausse, aucun creux, liquidite qui gonfle -- se fait vider quatre
# a sept fois plus souvent (§3.66).
#
# Ces 139 courbes sont desormais IN-SAMPLE, definitivement. Toute reprise de la mesure dessus ne
# ferait que retrouver ce que j y ai cherche. `--depuis 1788989940` ne garde que les courbes nees
# apres cet instant : c est le seul echantillon qui puisse confirmer ou infirmer la regle, et il
# faut le dire avant de le regarder, pas apres.
COUPURE = 1788989940     # 2026-09-09 21:39:00 -- fin de l echantillon de decouverte


def courbes(db: str, depuis: int = 0) -> list[dict]:
    """Une entree par pool, avec ce qui precede T_DECISION et ce qui suit.

    `depuis` ne garde que les pools dont le PREMIER releve est posterieur a cet horodatage. Passer
    `COUPURE` donne l echantillon jamais regarde ; passer 0 donne tout, decouverte comprise.
    """
    c = sqlite3.connect("file:" + db + "?mode=ro", uri=True)
    debuts = {p: t for p, t in c.execute(
        "SELECT pair_id, MIN(ts) FROM solana_prix_chaine GROUP BY pair_id")}
    brut: dict[str, list[tuple[int, float, float]]] = {}
    for pid, age, prix, res in c.execute(
            "SELECT pair_id, age_s, prix_sol, reserve_sol FROM solana_prix_chaine"
            " WHERE prix_sol > 0 ORDER BY pair_id, age_s"):
        if debuts.get(pid, 0) < depuis:
            continue
        brut.setdefault(pid, []).append((int(age), float(prix), float(res or 0)))

    out = []
    for pid, pts in brut.items():
        avant = [p for p in pts if p[0] <= T_DECISION]
        apres = [p for p in pts if T_DECISION < p[0] <= T_FIN]
        # il faut avoir REELLEMENT vu la premiere minute, pas juste sa fin
        if len(avant) < 4 or avant[0][0] > 45 or len(apres) < 6:
            continue
        p0 = avant[0][1]
        if p0 <= 0:
            continue
        pv = [p[1] / p0 for p in avant]
        pa = [p[1] / p0 for p in apres]
        rv = [p[2] for p in avant]
        ra = [p[2] for p in apres]
        out.append(dict(
            pair_id=pid, debut_s=avant[0][0], n_avant=len(avant), n_apres=len(apres),
            # ce qu on VOIT avant de decider
            var_avant=pv[-1] - 1.0,
            pic_avant=max(pv) - 1.0,
            creux_avant=min(pv) - 1.0,
            liq_debut=rv[0],
            liq_var_avant=(rv[-1] / rv[0] - 1.0) if rv[0] > 0 else None,
            # ce qui ARRIVE ensuite, rapporte au prix a la decision
            suite=pa[-1] / pv[-1] - 1.0,
            suite_pic=max(pa) / pv[-1] - 1.0,
            suite_creux=min(pa) / pv[-1] - 1.0,
            liq_min_apres=(min(ra) / rv[-1]) if rv[-1] > 0 else None,
            rug=int(min(ra) < 0.2 * rv[-1]) if rv[-1] > 0 else 0,
        ))
    out.sort(key=lambda x: x["debut_s"])
    return out


def par_euro(lot: list[dict]) -> float:
    return sum((1 + x["suite"]) * PEAGE - 1 for x in lot) / len(lot) if lot else 0.0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="/app/db/intel.sqlite")
    ap.add_argument("--minimum", type=int, default=100)
    ap.add_argument("--depuis", type=int, default=0,
                    help="ne garder que les courbes nees apres cet horodatage ; "
                         "%d = l echantillon jamais regarde" % COUPURE)
    ap.add_argument("--avant", action="store_true",
                    help="raccourci pour --depuis COUPURE : le test en avant")
    a = ap.parse_args()

    depuis = COUPURE if a.avant else a.depuis
    if depuis:
        print("  echantillon restreint aux courbes nees apres %d (test en avant)" % depuis)
    d = courbes(a.db, depuis)
    print("  %d pools observes depuis la premiere minute" % len(d))
    if not d:
        print("  rien a mesurer : le collecteur n a pas encore de courbe complete.")
        return
    if len(d) < a.minimum:
        print("  ON NE CONCLUT PAS : %d courbes pour un minimum de %d." % (len(d), a.minimum))
        print("  Au rythme actuel il faut encore quelques heures. Ce qui suit est descriptif.")
    print()

    print("  1. A QUOI RESSEMBLE LA PREMIERE MINUTE")
    for nom, cle in (("variation a T+90s", "var_avant"), ("pic", "pic_avant"), ("creux", "creux_avant")):
        v = [x[cle] for x in d]
        print("     %-20s mediane %+6.1f %%   10e %+7.1f %%   90e %+7.1f %%" % (
            nom, 100 * st.median(v), 100 * sorted(v)[len(v) // 10], 100 * sorted(v)[9 * len(v) // 10]))
    liq = [x["liq_debut"] for x in d]
    print("     %-20s mediane %8.1f SOL" % ("liquidite au depart", st.median(liq)))
    monte = 100 * sum(1 for x in d if x["var_avant"] > 0) / len(d)
    print("     %-20s %.0f %% des pools montent pendant la premiere minute" % ("sens", monte))
    print()

    print("  2. LA PREMIERE MINUTE ANNONCE-T-ELLE LA SUITE ?")
    n = len(d) // 2
    rech, juge = d[:n], d[n:]
    print("     reference : suite mediane %+.1f %% · par euro %+.3f (peage deduit)" % (
        100 * st.median([x["suite"] for x in d]), par_euro(d)))
    if len(juge) >= 20:
        for cle in ("var_avant", "pic_avant", "creux_avant", "liq_var_avant", "liq_debut"):
            vals = sorted(x[cle] for x in rech if x.get(cle) is not None)
            if len(vals) < 20:
                continue
            for q, lab in ((0.5, "median"),):
                seuil = vals[int(len(vals) * q)]
                for sens in (">=", "<="):
                    sel = (lambda x, c=cle, s=seuil, sn=sens: x.get(c) is not None and
                           (x[c] >= s if sn == ">=" else x[c] <= s))
                    r = [x for x in rech if sel(x)]
                    g = [x for x in juge if sel(x)]
                    if len(r) < 10 or len(g) < 10:
                        continue
                    print("     %-16s %s %-9.4g  recherche %+.3f (n=%d)   JUGEMENT %+.3f (n=%d)" % (
                        cle, sens, seuil, par_euro(r), len(r), par_euro(g), len(g)))
    else:
        print("     pas encore assez de courbes pour couper en deux moities.")
    print()

    print("  3. LE RETRAIT DE LIQUIDITE SE VOIT-IL VENIR ?")
    rugs = [x for x in d if x["rug"]]
    sains = [x for x in d if not x["rug"]]
    print("     %d pools vides sur %d (%.0f %%)" % (len(rugs), len(d), 100 * len(rugs) / len(d)))
    if len(rugs) >= 8 and len(sains) >= 8:
        for nom, cle in (("variation a T+90s", "var_avant"), ("liquidite au depart", "liq_debut"),
                         ("variation de liquidite", "liq_var_avant")):
            a_ = [x[cle] for x in rugs if x.get(cle) is not None]
            b_ = [x[cle] for x in sains if x.get(cle) is not None]
            if len(a_) < 5 or len(b_) < 5:
                continue
            print("     %-24s vides %+8.3f   sains %+8.3f" % (nom, st.median(a_), st.median(b_)))
        random.seed(1)
        print("     (a confirmer contre le hasard des que l echantillon depasse %d)" % a.minimum)
    else:
        print("     trop peu de pools vides pour comparer.")


if __name__ == "__main__":
    main()
