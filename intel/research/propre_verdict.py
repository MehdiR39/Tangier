"""Le filtre « 3 signes » : verdict unique, en pesant toutes les preuves ensemble.

ERREUR A CORRIGER. J ai presente ce filtre comme positif sur nos 35 tickets reels, puis je l ai
ecarte parce que 13 tickets SIMULES de la moitie de jugement donnaient -0,015. C est peser 13
observations simulees au-dessus de 35 observations de vrai argent -- exactement l inverse de ce
qu il faut.

On refait donc le test correctement :
  1. le CONTRASTE (3 signes contre le reste) est-il du meme signe partout ? Un filtre se juge sur
     l ecart entre ce qu il garde et ce qu il jette, pas sur le niveau absolu du groupe garde, qui
     bouge avec la periode ;
  2. toutes les preuves reunies, avec leur poids : 66 tickets reels + 62 simules ;
  3. un test du hasard sur le contraste, pas sur le groupe.
"""
import sqlite3, statistics as st, random

PEAGE, IMPACT, MISE_SOL = 0.024, 0.15, 20.0/94.06
c = sqlite3.connect("file:/app/db/intel.sqlite?mode=ro", uri=True)
c.row_factory = sqlite3.Row
bons = {r[0] for r in c.execute("SELECT pool FROM pool_quote WHERE est_sol=1")}

def signes(av, e):
    p0 = av[0]["prix_sol"]; l0 = av[0]["reserve_sol"] or 0
    if p0 <= 0:
        return None
    return (int(e["prix_sol"]/p0 - 1 >= 0.007)
            + int(min(x["prix_sol"] for x in av)/p0 - 1 >= 0)
            + int((e["reserve_sol"]/l0 - 1 if l0 > 0 else 0) >= 0.0035))

# ---- A. nos tickets reels ----
reels = []
for r in c.execute("""SELECT symbole,pair_id,ts_entree,gain_eur,mise_eur FROM tg_lignes
                      WHERE mode='live' AND gain_eur IS NOT NULL ORDER BY ts_entree"""):
    d = dict(r)
    if d["pair_id"] not in bons:
        continue
    av = [dict(x) for x in c.execute(
        "SELECT prix_sol,reserve_sol FROM solana_prix_chaine WHERE pair_id=? AND ts<=? AND prix_sol>0"
        " ORDER BY ts", (d["pair_id"], d["ts_entree"]))]
    if len(av) < 3:
        continue
    s = signes(av, av[-1])
    if s is None:
        continue
    reels.append(dict(src="reel", sg=s, g=d["gain_eur"]/d["mise_eur"]))

# ---- B. les tickets simules, jetons Telegram ----
marque = {r["mint"]: r["telegram"] for r in c.execute("SELECT mint, telegram FROM tg_juges")}
courbes = {}
for r in c.execute("""SELECT p.mint,p.ts,p.age_s,p.prix_sol,p.reserve_sol FROM solana_prix_chaine p
                      JOIN pool_quote q ON q.pool=p.pair_id AND q.est_sol=1
                      WHERE p.prix_sol>0 ORDER BY p.mint,p.age_s"""):
    if marque.get(r["mint"]):
        courbes.setdefault(r["mint"], []).append(dict(r))
sim = []
for m, pts in courbes.items():
    av = [x for x in pts if x["age_s"] <= 90]
    e = min((x for x in pts if 45 <= x["age_s"] <= 90), key=lambda x: abs(x["age_s"]-60), default=None)
    if len(av) < 3 or not e or e["prix_sol"] <= 0 or not e["reserve_sol"]:
        continue
    if MISE_SOL/e["reserve_sol"] > IMPACT:
        continue
    s = signes(av, e)
    ap = [x for x in pts if x["age_s"] > e["age_s"]]
    if s is None or not ap:
        continue
    x = min(ap, key=lambda y: abs(y["age_s"]-(e["age_s"]+240)))
    if abs(x["age_s"]-(e["age_s"]+240)) > 45:
        continue
    sim.append(dict(src="simule", sg=s, g=(x["prix_sol"]/e["prix_sol"])*(1-PEAGE)-1))

def ecart(ech, lib):
    a = [x["g"] for x in ech if x["sg"] == 3]
    b = [x["g"] for x in ech if x["sg"] < 3]
    if len(a) < 5 or len(b) < 5:
        return
    print("  %-24s garde %2d a %+.3f · jette %2d a %+.3f · CONTRASTE %+.3f"
          % (lib, len(a), sum(a)/len(a), len(b), sum(b)/len(b), sum(a)/len(a) - sum(b)/len(b)))

print("  LE CONTRASTE, echantillon par echantillon")
ecart(reels, "nos tickets REELS")
ecart(sim, "simules (Telegram)")
mi = len(sim)//2
ecart(sim[:mi], "  dont recherche")
ecart(sim[mi:], "  dont jugement")
tout = reels + sim
ecart(tout, "TOUT REUNI")

print()
print("  TEST DU HASARD SUR LE CONTRASTE (et non sur le groupe garde)")
for lib, ech in (("nos tickets reels", reels), ("tout reuni", tout)):
    a = [x["g"] for x in ech if x["sg"] == 3]
    v = [x["g"] for x in ech]
    if len(a) < 5 or len(a) >= len(v):
        continue
    cible = sum(a)/len(a)
    random.seed(41)
    p = sum(1 for _ in range(20000) if sum(random.sample(v, len(a)))/len(a) >= cible)/20000
    print("     %-22s %.1f %% des tirages de %d tickets font aussi bien" % (lib, 100*p, len(a)))

print()
print("  CE QUE LE FILTRE AURAIT CHANGE SUR NOTRE ARGENT")
c2 = sqlite3.connect("file:/app/db/intel.sqlite?mode=ro", uri=True)
c2.row_factory = sqlite3.Row
tot = garde = 0.0
ng = 0
for r in c2.execute("""SELECT pair_id,ts_entree,gain_eur FROM tg_lignes
                       WHERE mode='live' AND gain_eur IS NOT NULL"""):
    d = dict(r)
    tot += d["gain_eur"]
    if d["pair_id"] not in bons:
        continue
    av = [dict(x) for x in c2.execute(
        "SELECT prix_sol,reserve_sol FROM solana_prix_chaine WHERE pair_id=? AND ts<=? AND prix_sol>0"
        " ORDER BY ts", (d["pair_id"], d["ts_entree"]))]
    if len(av) < 3:
        continue
    if signes(av, av[-1]) == 3:
        garde += d["gain_eur"]
        ng += 1
print("     sans filtre : %+8.2f EUR sur %d tickets" % (tot, len(list(c2.execute(
    "SELECT 1 FROM tg_lignes WHERE mode='live' AND gain_eur IS NOT NULL")))))
print("     avec filtre : %+8.2f EUR sur %d tickets" % (garde, ng))
