"""Entrons-nous au sommet ? La forme moyenne du prix autour de notre achat.

L operateur, le 14/09 : « on rentre au moment ou ca se crashe ». C est une hypothese precise et
elle se mesure : il suffit de regarder ou se situe le prix de notre entree PAR RAPPORT a tout ce
qui s est passe avant et apres.

Si l accusation est juste, on doit voir trois choses :
  1. le prix a T+60 est proche du PLUS HAUT de la periode 0-60 s ;
  2. le profil moyen monte avant l entree et descend apres ;
  3. entrer plus tard, apres la retombee, ferait mieux.

Le troisieme point est le seul qui vaut de l argent, et il a deja ete balaye le 12/09 (entree
T+90 -> T+60). On le refait sur les donnees d aujourd hui, capteur different.
"""
import sqlite3, statistics as st

PEAGE, IMPACT, MISE_SOL = 0.024, 0.15, 20.0/94.06
c = sqlite3.connect("file:/app/db/intel.sqlite?mode=ro", uri=True)
c.row_factory = sqlite3.Row
marque = {r["mint"]: r["telegram"] for r in c.execute("SELECT mint, telegram FROM tg_juges")}
courbes = {}
for r in c.execute("""SELECT p.mint,p.ts,p.age_s,p.prix_sol,p.reserve_sol FROM solana_prix_chaine p
                      JOIN pool_quote q ON q.pool=p.pair_id AND q.est_sol=1
                      WHERE p.prix_sol>0 ORDER BY p.mint,p.age_s"""):
    courbes.setdefault(r["mint"], []).append(dict(r))

tg = {m: p for m, p in courbes.items() if marque.get(m)}
print("  %d jetons Telegram avec une courbe" % len(tg))

print()
print("  1. LE PROFIL MOYEN DU PRIX, rapporte au prix a T+60 s")
print("  %-10s %6s %10s %10s %10s" % ("age", "n", "median", "p25", "p75"))
for age in (20, 40, 60, 80, 100, 140, 180, 240, 300, 360, 480, 600):
    v = []
    for m, pts in tg.items():
        ref = min((x for x in pts if 45 <= x["age_s"] <= 90), key=lambda x: abs(x["age_s"]-60), default=None)
        p = min((x for x in pts if abs(x["age_s"]-age) <= 25), key=lambda x: abs(x["age_s"]-age), default=None)
        if ref and p and ref["prix_sol"] > 0:
            v.append(p["prix_sol"]/ref["prix_sol"])
    if len(v) < 10:
        continue
    s = sorted(v); n = len(s)
    marque_ = "  <-- NOTRE ENTREE" if age == 60 else ""
    print("  T+%-8d %6d %10.3f %10.3f %10.3f%s" % (age, n, s[n//2], s[n//4], s[3*n//4], marque_))

print()
print("  2. NOTRE ENTREE EST-ELLE AU PLUS HAUT DE CE QUI PRECEDE ?")
rangs = []
for m, pts in tg.items():
    av = [x["prix_sol"] for x in pts if x["age_s"] <= 60 and x["prix_sol"] > 0]
    e = min((x for x in pts if 45 <= x["age_s"] <= 90), key=lambda x: abs(x["age_s"]-60), default=None)
    if len(av) >= 3 and e:
        rangs.append(sum(1 for p in av if p <= e["prix_sol"])/len(av))
if rangs:
    s = sorted(rangs)
    print("     sur %d jetons, notre prix d entree se situe au %.0f-ieme centile de ce qui precede"
          % (len(s), 100*s[len(s)//2]))
    print("     (50 = au milieu · 100 = au plus haut · au hasard on attendrait 50)")
    print("     part des cas ou on entre au PLUS HAUT vu jusque-la : %.0f %%"
          % (100*sum(1 for x in s if x >= 0.99)/len(s)))

print()
print("  3. ENTRER PLUS TARD FERAIT-IL MIEUX ? (sortie toujours 4 min apres l entree)")
print("  %-16s %5s %10s %10s %11s %9s" % ("entree", "n", "par euro", "mediane", "sans best", "gagnants"))
for entree in (60, 90, 120, 180, 240, 300):
    g = []
    for m, pts in tg.items():
        e = min((x for x in pts if abs(x["age_s"]-entree) <= 30), key=lambda x: abs(x["age_s"]-entree), default=None)
        if not e or e["prix_sol"] <= 0 or not e["reserve_sol"] or MISE_SOL/e["reserve_sol"] > IMPACT:
            continue
        ap = [x for x in pts if x["age_s"] > e["age_s"]]
        if not ap:
            continue
        s2 = min(ap, key=lambda x: abs(x["age_s"]-(e["age_s"]+240)))
        if abs(s2["age_s"]-(e["age_s"]+240)) > 45:
            continue
        g.append((s2["prix_sol"]/e["prix_sol"])*(1-PEAGE)-1)
    if len(g) < 10:
        print("  %-16s %5d   trop peu" % ("T+%ds" % entree, len(g))); continue
    b = max(g); sans = [x for x in g if x != b] or g
    print("  T+%-14d %5d %+10.3f %+10.3f %+11.3f %8.0f %%"
          % (entree, len(g), sum(g)/len(g), st.median(g), sum(sans)/len(sans),
             100*sum(1 for x in g if x > 0)/len(g)))
