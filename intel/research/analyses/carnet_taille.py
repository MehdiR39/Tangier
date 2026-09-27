"""Combien miser : la seule decision qu on puisse encore ameliorer avec 59 tickets.

Deux mesures du jour disent que le reste est ferme pour l instant :
  - a l instant d acheter, dix variables mesurees ne separent pas les gagnants des perdants ;
  - dix-huit regles de sortie rejouees sur nos propres tickets : la seule qui battait la regle en
    place ne s est pas reproduite sur 55 chemins independants.

Reste la taille de la mise. Elle n a pas besoin d un signal : elle depend seulement de l avantage
et de sa dispersion, et les deux se mesurent sur ce qu on a deja joue.

CRITERE DE KELLY. Il maximise la croissance du capital a long terme. Sur une distribution a queue
epaisse il est connu pour etre AGRESSIF, donc on regarde aussi la demi-Kelly et le quart, et on
affiche la perte maximale historique que chaque taille aurait produite.

ET LE POINT QUI TRANCHE : l avantage lui-meme est incertain (intervalle -0,059 a +0,206). Miser la
taille optimale de l avantage MOYEN quand cet avantage peut etre nul est une erreur. On calcule
donc aussi la taille sur la BORNE BASSE de l intervalle -- ce que la prudence commande tant que
200 tickets n ont pas tranche.
"""
import sqlite3, random, statistics as st

c = sqlite3.connect("file:/app/db/intel.sqlite?mode=ro", uri=True)
c.row_factory = sqlite3.Row
t = [dict(r) for r in c.execute(
    "SELECT symbole, gain_eur, mise_eur, ts_entree FROM tg_lignes"
    " WHERE mode='live' AND gain_eur IS NOT NULL ORDER BY ts_entree")]
g = [x["gain_eur"] / x["mise_eur"] for x in t]
n = len(g)
moy, var = sum(g) / n, st.pvariance(g)
print("  %d tickets · avantage %+.4f par euro · ecart-type %.3f" % (n, moy, var ** 0.5))
print("  pire ticket %+.2f · meilleur %+.2f" % (min(g), max(g)))
print()

random.seed(3)
bs = sorted(sum(random.choices(g, k=n)) / n for _ in range(20000))
lo, hi = bs[1000], bs[19000]
print("  intervalle a 90 %% de l avantage : %+.3f a %+.3f" % (lo, hi))
print()

def kelly(m, v):
    return m / v if v > 0 else 0

k = kelly(moy, var)
k_lo = kelly(lo, var)
print("  TAILLE DE MISE, en part du capital de travail")
print("  %-30s %10s %14s" % ("critere", "fraction", "sur 1 000 EUR"))
for lib, f in (("Kelly sur l avantage mesure", k), ("demi-Kelly", k / 2),
               ("quart de Kelly", k / 4),
               ("Kelly sur la BORNE BASSE", k_lo)):
    print("  %-30s %9.1f %% %13.0f EUR" % (lib, 100 * f, 1000 * f))
print()
print("  Lecture : la borne basse de l avantage est %s." % ("NEGATIVE" if lo < 0 else "positive"))
if lo < 0:
    print("  Tant qu elle l est, aucune taille n est justifiee par le calcul : Kelly dit de ne pas")
    print("  miser sur un avantage qui peut etre nul. Ce qui ne veut pas dire s arreter -- il faut")
    print("  jouer pour apprendre -- mais que la mise doit etre celle qu on accepte de PERDRE pour")
    print("  acheter l information, pas celle qu un avantage prouve justifierait.")
print()
print("  CE QUE CHAQUE TAILLE AURAIT DONNE SUR NOS 59 TICKETS REELS")
print("  %-12s %14s %14s %14s" % ("mise", "resultat", "pire serie", "pire ticket"))
for mise in (10, 20, 30, 50, 80):
    res = [x * mise for x in g]
    cum, bas, pic = 0.0, 0.0, 0.0
    for r in res:
        cum += r
        pic = max(pic, cum)
        bas = min(bas, cum - pic)
    print("  %-12s %+13.2f %+14.2f %+14.2f" % ("%d EUR" % mise, sum(res), bas, min(res)))
print()
print("  (« pire serie » = la plus forte baisse depuis un sommet, ce qu il faut pouvoir encaisser)")
