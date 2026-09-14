"""Le filtre « trop propre » croise avec Telegram, sur donnees assainies.

S3.66 : trois signes mesures avant T+90 s -- le prix au-dessus de son depart, jamais baisse, la
liquidite qui grossit -- designent les lancements qui se font vider cinq fois plus. Esperance
-0,244/euro pour 2-3 signes contre +0,006 pour 0-1.

MAIS la note de discipline du 13/09 dit que ce filtre s INVERSE chez les jetons Telegram : le meme
groupe « propre » y gagne (+0,156/euro, 76 % de gagnants). Cela n a jamais ete remesure depuis que
les pools sont verifies et que la colonne reserve_sol est corrigee.

C est le seul croisement serieux qui restait non teste. Un filtre qui separe dans le sous-groupe
qu on trade vaudrait de l argent : les signes se calculent sur des donnees qu on collecte deja,
donc zero appel supplementaire et zero latence.

Coupure recherche / jugement sur la date de naissance, resultat prive de son meilleur ticket.
"""
import sqlite3, statistics as st, random

PEAGE, IMPACT, MISE_SOL = 0.024, 0.15, 20.0/94.06
c = sqlite3.connect("file:/app/db/intel.sqlite?mode=ro", uri=True)
c.row_factory = sqlite3.Row
marque = {r["mint"]: r["telegram"] for r in c.execute("SELECT mint, telegram FROM tg_juges")}
courbes = {}
for r in c.execute("""SELECT p.mint,p.ts,p.age_s,p.prix_sol,p.reserve_sol FROM solana_prix_chaine p
                      JOIN pool_quote q ON q.pool=p.pair_id AND q.est_sol=1
                      WHERE p.prix_sol>0 ORDER BY p.mint,p.age_s"""):
    courbes.setdefault(r["mint"], []).append(dict(r))

T = []
for m, pts in courbes.items():
    avant = [x for x in pts if x["age_s"] <= 90]
    if len(avant) < 3:
        continue
    e = min((x for x in pts if 45 <= x["age_s"] <= 90), key=lambda x: abs(x["age_s"]-60), default=None)
    if not e or e["prix_sol"] <= 0 or not e["reserve_sol"] or MISE_SOL/e["reserve_sol"] > IMPACT:
        continue
    p0 = avant[0]["prix_sol"]
    l0 = avant[0]["reserve_sol"] or 0
    if p0 <= 0:
        continue
    var = e["prix_sol"]/p0 - 1
    creux = min(x["prix_sol"] for x in avant)/p0 - 1
    liq = (e["reserve_sol"]/l0 - 1) if l0 > 0 else 0
    signes = int(var >= 0.007) + int(creux >= 0) + int(liq >= 0.0035)
    ap = [x for x in pts if x["age_s"] > e["age_s"]]
    if not ap:
        continue
    s = min(ap, key=lambda x: abs(x["age_s"]-(e["age_s"]+240)))
    if abs(s["age_s"]-(e["age_s"]+240)) > 45:
        continue
    T.append(dict(ts=e["ts"], tg=bool(marque.get(m)), signes=signes,
                  g=(s["prix_sol"]/e["prix_sol"])*(1-PEAGE)-1))
T.sort(key=lambda d: d["ts"])
tg = [x for x in T if x["tg"]]
print("  %d tickets · %d Telegram" % (len(T), len(tg)))

def stat(g):
    if len(g) < 8:
        return None
    v = [x["g"] for x in g]
    b = max(v); sans = [x for x in v if x != b] or v
    return (len(v), sum(v)/len(v), st.median(v), sum(sans)/len(sans),
            sum(1 for x in v if x > 0)/len(v))

def l(lib, s):
    if not s:
        return "  %-28s      --" % lib
    return "  %-28s %5d %+9.3f %+9.3f %+10.3f %8.0f %%" % ((lib,) + s[:4] + (100*s[4],))

for nom, groupe in (("TOUS LES JETONS", T), ("JETONS TELEGRAM (ce qu on trade)", tg)):
    print()
    print("  " + "=" * 76)
    print("  %s · %d tickets" % (nom, len(groupe)))
    print("  %-28s %5s %9s %9s %10s %9s" % ("", "n", "par euro", "mediane", "sans best", "gagn."))
    for k in (0, 1, 2, 3):
        print(l("%d signe(s) « trop propre »" % k, stat([x for x in groupe if x["signes"] == k])))
    print("  --- regroupe ---")
    print(l("0-1 signe (sale)", stat([x for x in groupe if x["signes"] <= 1])))
    print(l("2-3 signes (TROP PROPRE)", stat([x for x in groupe if x["signes"] >= 2])))

print()
print("  LES DEUX MOITIES, sur les jetons Telegram -- le seul juge")
mi = len(tg)//2
for lib, f in (("0-1 signe", lambda x: x["signes"] <= 1), ("2-3 signes", lambda x: x["signes"] >= 2)):
    r1, r2 = stat([x for x in tg[:mi] if f(x)]), stat([x for x in tg[mi:] if f(x)])
    print("  %-22s recherche %s   JUGEMENT %s"
          % (lib, ("%+.3f (n=%d)" % (r1[1], r1[0])) if r1 else "   --     ",
             ("%+.3f (n=%d)" % (r2[1], r2[0])) if r2 else "   --"))

print()
print("  TEST DU HASARD sur le meilleur groupe Telegram (moitie de jugement)")
best = max(((k, [x for x in tg[mi:] if (x["signes"] <= 1 if k == "0-1" else x["signes"] >= 2)])
            for k in ("0-1", "2-3")), key=lambda z: (sum(y["g"] for y in z[1])/len(z[1])) if z[1] else -9)
k, g = best
if len(g) >= 8:
    cible = sum(x["g"] for x in g)/len(g)
    v = [x["g"] for x in tg[mi:]]
    random.seed(21)
    p = sum(1 for _ in range(20000) if sum(random.sample(v, len(g)))/len(g) >= cible)/20000
    print("     groupe %s : %+.3f sur %d tickets · %.1f %% des tirages font aussi bien"
          % (k, cible, len(g), 100*p))
