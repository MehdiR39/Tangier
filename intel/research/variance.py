"""Pourquoi 53 % de gagnants ne donne PAS 53 % de bonnes journees.

Question de l operateur, le 14/09 : « si la strat est gagnante a 53 % pour moi c est qu en moyenne
on doit avoir 53 % par jour, mais la c est une journee bien et une journee qui bouffe tout. Un coup
de chance sur une dizaine de positions ? »

La reponse tient a la FORME de la distribution, pas au taux de gagnants. Le taux dit combien de
tickets finissent au-dessus de zero ; il ne dit rien de COMBIEN. Ici la mediane est proche de zero
et tout se joue dans les queues : une poignee de tickets fait la journee, dans un sens ou dans
l autre.

On le mesure en tirant au sort des journees entieres dans la distribution reellement observee.
"""
import sqlite3, random, statistics as st

c = sqlite3.connect("file:/app/db/intel.sqlite?mode=ro", uri=True)
c.row_factory = sqlite3.Row
t = [dict(r) for r in c.execute(
    "SELECT gain_eur, mise_eur FROM tg_lignes WHERE mode='live' AND gain_eur IS NOT NULL")]
g = [x["gain_eur"] / x["mise_eur"] for x in t]
n = len(g)
print("  %d tickets reels · %.0f %% de gagnants · mediane %+.3f · moyenne %+.4f"
      % (n, 100*sum(1 for v in g if v > 0)/n, st.median(g), sum(g)/n))
print()
print("  OU SE TROUVE L ARGENT ? part du resultat total portee par chaque tranche")
tri = sorted(g)
tot = sum(g)
for lib, sous in (("les 3 pires tickets", tri[:3]), ("les 10 pires", tri[:10]),
                  ("le milieu (ni top ni flop 10)", tri[10:-10]),
                  ("les 10 meilleurs", tri[-10:]), ("les 3 meilleurs", tri[-3:])):
    print("    %-30s somme %+8.3f" % (lib, sum(sous)))
print("    %-30s somme %+8.3f" % ("TOTAL", tot))
print()
print("  Autrement dit : 20 tickets sur %d font tout le resultat, les %d autres s annulent." % (n, n-20))

print()
print("  DES JOURNEES TIREES AU SORT DANS CETTE MEME DISTRIBUTION")
print("  %-16s %10s %12s %12s %12s" % ("tickets/jour", "jours -", "mediane", "pire 5 %", "meilleur 5 %"))
random.seed(11)
for k in (5, 12, 20, 40, 100, 200):
    jours = sorted(sum(random.choices(g, k=k)) / k for _ in range(40000))
    perdants = sum(1 for x in jours if x < 0) / len(jours)
    print("  %-16d %9.0f %% %+12.3f %+12.3f %+12.3f"
          % (k, 100*perdants, jours[20000], jours[2000], jours[38000]))
print()
print("  A 18 TICKETS PAR JOUR -- notre rythme -- ce que donne une journee, en EUROS a 120 EUR")
random.seed(13)
jours = sorted(sum(random.choices(g, k=18)) * 120 for _ in range(40000))
for p, lib in ((1, "1 jour sur 100 est pire que"), (5, "1 jour sur 20 est pire que"),
               (25, "1 jour sur 4 est pire que"), (50, "la journee mediane vaut"),
               (75, "1 jour sur 4 est meilleur que"), (95, "1 jour sur 20 depasse"),
               (99, "1 jour sur 100 depasse")):
    print("    %-32s %+10.2f EUR" % (lib, jours[int(p/100*len(jours))]))
print()
reel = -258.42 / (69/120)      # ramene a la mise de 120 pour comparer
pire = sum(1 for x in jours if x <= reel) / len(jours)
print("  NOTRE JOURNEE D AUJOURD HUI, ramenee a 120 EUR par ticket : %+.2f EUR" % reel)
print("  Une journee au moins aussi mauvaise arrive %.1f %% du temps, soit environ 1 jour sur %.0f."
      % (100*pire, 1/pire if pire else 0))
