"""L usure : savoir que la strategie meurt AVANT qu elle coute cher.

L operateur, le 13/09 : « on n est pas a l abri que notre strategie ne fonctionne plus un jour ».
C est la bonne inquietude, et elle merite un instrument plutot qu une surveillance a l oeil.

POURQUOI CE N EST PAS EVIDENT. Un avantage de +0,12 par euro avec un ticket median a +0,5 % et des
extremes a x3 ne se voit pas sur dix tickets, ni sur cinquante. Sur cette distribution, une serie de
vingt perdants d affilee arrive REGULIEREMENT sans que rien ne soit casse -- et inversement, une
strategie deja morte peut afficher trois beaux tickets. L oeil ne peut pas trancher, le calcul si.

CE QUE MESURE CE FICHIER, sur nos propres tickets reels :

  1. le resultat par euro sur une fenetre glissante, avec son intervalle de confiance obtenu par
     reechantillonnage -- pas une moyenne nue, qui ne dit rien sans sa largeur ;
  2. la comparaison avec l esperance de reference (+0,116 par euro, moitie de jugement, peage reel) ;
  3. le nombre de tickets qu il FAUDRAIT pour distinguer « ca marche encore » de « c est mort ».

LE TROISIEME POINT EST LE PLUS UTILE et le plus inconfortable : il dit combien de temps on reste
aveugle. Le savoir evite deux erreurs symetriques -- couper une strategie vivante sur une mauvaise
semaine, et laisser tourner une strategie morte parce qu on attend une preuve qui ne viendra jamais.

Usage :
    python -m intel.research.usure
"""
from __future__ import annotations

import argparse
import random
import sqlite3
import statistics as st
import sys

sys.path.insert(0, "/app")

REFERENCE = 0.116          # par euro, moitie de jugement, peage reel de 2,4 %


def tickets(db: str) -> list[dict]:
    c = sqlite3.connect("file:" + db + "?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return [dict(r) for r in c.execute(
        "SELECT symbole, ts_sortie, gain_eur, mise_eur FROM tg_lignes"
        " WHERE mode='live' AND gain_eur IS NOT NULL AND mise_eur > 0"
        " ORDER BY ts_sortie")]


def intervalle(g: list[float], n: int = 20000, seed: int = 1) -> tuple[float, float, float]:
    """La moyenne et son intervalle a 90 %, par reechantillonnage. Une moyenne sans sa largeur sur
    une distribution a queue epaisse n est pas une mesure, c est une impression."""
    if not g:
        return float("nan"), float("nan"), float("nan")
    random.seed(seed)
    bs = sorted(sum(random.choices(g, k=len(g))) / len(g) for _ in range(n))
    return sum(g) / len(g), bs[int(0.05 * n)], bs[int(0.95 * n)]


def combien_faut_il(g: list[float], cible: float = 0.0, seed: int = 2) -> int:
    """Combien de tickets pour que l intervalle a 90 % cesse de contenir `cible` ?

    Autrement dit : a partir de quand saurait-on que l avantage n est pas nul, si la distribution
    observee est la vraie ? C est la mesure de notre aveuglement."""
    if len(g) < 5:
        return -1
    random.seed(seed)
    for n in (25, 50, 100, 200, 400, 800, 1600):
        bs = sorted(sum(random.choices(g, k=n)) / n for _ in range(4000))
        if bs[200] > cible or bs[3800] < cible:
            return n
    return -1


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="/app/db/intel.sqlite")
    a = ap.parse_args()
    t = tickets(a.db)
    if not t:
        print("  aucun ticket reel")
        return
    par_euro = [x["gain_eur"] / x["mise_eur"] for x in t]
    print("  %d tickets reels · %+.2f EUR sur %.0f EUR engages"
          % (len(t), sum(x["gain_eur"] for x in t), sum(x["mise_eur"] for x in t)))

    print()
    print("  RESULTAT PAR EURO, SUR FENETRE GLISSANTE")
    print("  %-16s %6s %10s %22s %10s" % ("fenetre", "n", "par euro", "intervalle a 90 %", "gagnants"))
    for lib, k in (("tout", len(par_euro)), ("100 derniers", 100), ("50 derniers", 50),
                   ("25 derniers", 25)):
        g = par_euro[-k:]
        if len(g) < 10:
            print("  %-16s %6d   trop peu" % (lib, len(g)))
            continue
        m, lo, hi = intervalle(g)
        print("  %-16s %6d %+10.3f   %+7.3f a %+7.3f %9.0f %%"
              % (lib, len(g), m, lo, hi, 100 * sum(1 for v in g if v > 0) / len(g)))

    print()
    m, lo, hi = intervalle(par_euro)
    print("  LA REFERENCE EST %+.3f PAR EURO (moitie de jugement, peage reel)" % REFERENCE)
    if lo > REFERENCE:
        verdict = "AU-DESSUS de la reference, et l intervalle ne la contient pas"
    elif hi < 0:
        verdict = "NEGATIF, et l intervalle exclut zero -- la strategie ne gagne plus"
    elif hi < REFERENCE:
        verdict = "SOUS la reference, et l intervalle l exclut : l avantage s est reduit"
    elif lo > 0:
        verdict = "positif, et l intervalle exclut zero"
    else:
        verdict = "compatible avec zero ET avec la reference : on ne sait pas encore"
    print("  Le carnet reel est %s." % verdict)

    print()
    n = combien_faut_il(par_euro, 0.0)
    print("  COMBIEN DE TICKETS POUR SAVOIR ?")
    print("    pour distinguer l avantage de ZERO : %s"
          % ("%d tickets" % n if n > 0 else "plus de 1 600 -- la variance est trop forte"))
    n2 = combien_faut_il(par_euro, REFERENCE)
    print("    pour detecter une chute sous la reference : %s"
          % ("%d tickets" % n2 if n2 > 0 else "plus de 1 600"))
    par_jour = 40
    if n > 0:
        print("    a %d tickets par jour, cela fait %.1f jours" % (par_jour, n / par_jour))

    print()
    print("  LES DIX DERNIERS TICKETS")
    for x in t[-10:]:
        print("    %-12s %+8.2f EUR  (%+.3f par euro)"
              % (x["symbole"][:12], x["gain_eur"], x["gain_eur"] / x["mise_eur"]))


if __name__ == "__main__":
    main()
