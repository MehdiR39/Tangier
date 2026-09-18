"""LE CARNET REEL CONTRE SON EQUIVALENT PAPIER, SUR LES MEMES JETONS.

POURQUOI CE FICHIER EXISTE. C est la seule calibration qui compte : pas une simulation contre une
simulation, mais ce que le papier ANNONCAIT contre ce que le portefeuille a REELLEMENT encaisse,
jeton par jeton. Tout le reste du projet repose sur des rendements simules ; si le papier se trompe,
il se trompe partout a la fois, et aucun test gele ne peut le detecter -- ils sont tous simules.

LA QUESTION OUVERTE QU IL SERT A TRANCHER, posee par Mido le 18/09 (« mais tu viens de dire que le
vrai cout est de 3,x et non 2,62, donc c est le cout le probleme ? ») : NON, le cout plat n explique
qu un sixieme de l ecart. A 27 tickets :

    ecart total reel - papier                  -3,74 pt
      dont le cout sous-estime (2,62 -> 3,17)  -0,55 pt   (15 %)
      dont autre chose                         -3,19 pt   (85 %)

Et le reste se concentre entierement sur les GAGNANTS :

    le papier annoncait        n     ecart moyen
    une perte (< 0 %)         11        -0,81 pt
    un petit gain (0 a +20 %)  3        -1,22 pt
    un GROS gain (>= +20 %)   13        -6,81 pt   IC95 [-15,48 ; +1,37]

MECANIQUE PROBABLE : quand un jeton fait +50 % en quatre minutes, le prix bouge de plusieurs
pourcents par SECONDE. On vend quelques secondes apres la lecture que le papier utilise, et notre
vente pousse le prix vers le bas dans un pool qui n a pas grossi. Les deux effets se cumulent, et
ils n existent pas sur un jeton qui stagne. Le cout n est donc pas un NOMBRE mais une FONCTION du
mouvement -- ~1 pt sur les perdants, ~7 pts sur les gros gagnants.

POURQUOI ON NE CORRIGE RIEN ENCORE. n = 27 et l intervalle sur les gros gagnants traverse zero. Le
meme soupcon est apparu deux heures plus tot par une autre voie et s est revele etre un artefact de
soustraction (§3.119) : cette fois la mesure est differente -- deux chiffres INDEPENDANTS sur les
memes jetons, pas une formule derivee -- mais il faut ~100 tickets pour trancher. Ce fichier sert a
savoir, a tout instant, ou on en est.

SI L ECART SE CONFIRME, il faudra remplacer le cout plat par un cout fonction du rendement dans
TOUTES les lignes de la table -- et toutes deviendront moins bonnes, pas meilleures.

Lecture seule sur les deux bases. N ecrit rien, ne decide rien.
"""
from __future__ import annotations

import os
import random
import sqlite3
import statistics as st

COUT_PAPIER = 0.0262          # ce que la table soustrait a tous les tickets
PLAFOND = 3.0
BASE_MOTEUR = os.environ.get("INTEL_DB", "/app/db/intel.sqlite")
BASE_COMBO = os.environ.get("COMBO_DB", "/app/db/papier_combo.sqlite")


def paires(ici: sqlite3.Connection) -> list[tuple[str, float, float, float]]:
    """(jeton, rendement REEL, rendement PAPIER, rendement brut) pour chaque ticket commun."""
    ici.execute("ATTACH DATABASE 'file:%s?mode=ro' AS P" % BASE_COMBO)
    out = []
    for mint, mise, gain, brut in ici.execute(
            "SELECT m.mint, m.mise_eur, m.gain_eur, i.brut_240 FROM mr_lignes m"
            " JOIN P.issue i ON i.pair = m.pair"
            " WHERE m.mode='live' AND m.gain_eur IS NOT NULL AND i.brut_240 IS NOT NULL"
            " AND m.mise_eur > 0 ORDER BY m.ts_entree"):
        out.append((str(mint), gain / mise, min(brut - COUT_PAPIER, PLAFOND), brut))
    return out


def _ic(v: list[float], tirages: int = 5000) -> tuple[float, float]:
    """Intervalle de confiance a 95 % par bootstrap. Rend (bas, haut)."""
    if len(v) < 3:
        return (float("nan"), float("nan"))
    bs = sorted(st.mean(random.choice(v) for _ in v) for _ in range(tirages))
    return (bs[int(0.025 * tirages)], bs[int(0.975 * tirages)])


def rapport(ici: sqlite3.Connection) -> None:
    random.seed(20260918)
    R = paires(ici)
    print("\nCALIBRATION REEL vs PAPIER · %d ticket(s) sur les memes jetons" % len(R))
    if len(R) < 5:
        print("   trop peu pour dire quoi que ce soit (il en faut ~100 pour trancher)")
        return
    reel = [x[1] for x in R]
    pap = [x[2] for x in R]
    d = [a - b for a, b in zip(reel, pap)]
    print("   %-24s %12s %12s" % ("", "REEL", "PAPIER"))
    print("   %-24s %+11.2f %% %+11.2f %%" % ("moyenne par ticket", 100 * st.mean(reel), 100 * st.mean(pap)))
    print("   %-24s %+11.2f %% %+11.2f %%" % ("mediane", 100 * st.median(reel), 100 * st.median(pap)))
    print("   %-24s %11.0f %% %11.0f %%"
          % ("gagnants", 100 * sum(1 for x in reel if x > 0) / len(reel),
             100 * sum(1 for x in pap if x > 0) / len(pap)))
    b, h = _ic(d)
    verdict = ("le papier est OPTIMISTE" if h < 0 else
               ("le papier est PESSIMISTE" if b > 0 else "aucun ecart demontrable"))
    print("\n   ECART MOYEN reel - papier : %+.2f pt · IC95 [%+.2f ; %+.2f] -> %s"
          % (100 * st.mean(d), 100 * b, 100 * h, verdict))

    # LA DECOMPOSITION QUI COMPTE : un cout plat mal regle deplacerait TOUT le monde de la meme
    # facon. Un ecart concentre sur les gagnants dit que le cout depend du MOUVEMENT, ce qui est
    # bien plus grave -- c est la queue droite qui porte tout le resultat.
    print("\n   OU SE CONCENTRE L ECART ?")
    print("   %-28s %5s %14s %s" % ("le papier annoncait", "n", "ecart moyen", "IC95"))
    for nom, sel in (("une perte (< 0 %)", lambda p: p < 0),
                     ("un petit gain (0 a +20 %)", lambda p: 0 <= p < 0.20),
                     ("un gros gain (>= +20 %)", lambda p: p >= 0.20)):
        s = [a - p for a, p in zip(reel, pap) if sel(p)]
        if len(s) < 3:
            print("   %-28s %5d   trop peu" % (nom, len(s)))
            continue
        lo, hi = _ic(s)
        print("   %-28s %5d %+13.2f pt  [%+.2f ; %+.2f]" % (nom, len(s), 100 * st.mean(s), 100 * lo, 100 * hi))

    # ET SI LE COUT PLAT ETAIT SEULEMENT MAL REGLE ? On le recale sur l ecart observe et on regarde
    # ce qui SUBSISTE. Ce qui subsiste n est, par construction, pas une question de niveau.
    cal = COUT_PAPIER - st.mean(d)
    d2 = [a - min(br - cal, PLAFOND) for a, _, br in ((x[1], x[2], x[3]) for x in R)]
    lo2, hi2 = _ic(d2)
    print("\n   AVEC UN COUT PLAT RECALE A %.2f pts : ecart %+.2f pt · IC95 [%+.2f ; %+.2f]"
          % (100 * cal, 100 * st.mean(d2), 100 * lo2, 100 * hi2))
    print("   (un ecart qui SUBSISTE apres recalage ne peut pas etre une question de niveau)")
    print("\n   Il faut ~100 tickets pour trancher. Ne rien corriger avant.")


if __name__ == "__main__":
    rapport(sqlite3.connect("file:%s?mode=ro" % BASE_MOTEUR, uri=True, timeout=60))
