"""Le passe d un createur predit-il son prochain jeton ?

C est la seule des quatre hypotheses de l operateur qui vienne de devenir testable : 562 createurs
sur 4 625 ont lance plusieurs jetons, contre une vingtaine il y a trois jours.

L interet pratique est direct : l adresse du createur est connue AVANT d acheter. Si son historique
separe, c est un filtre gratuit -- aucun appel de plus, aucune latence.

TROIS QUESTIONS, dans l ordre :
  1. un createur recidiviste fait-il mieux ou moins bien qu un debutant ?
  2. le resultat de son jeton PRECEDENT predit-il le suivant ?
  3. un createur dont un jeton a deja gradue recommence-t-il ?

Regle absolue ici : pour juger le jeton k d un createur, on n utilise QUE ses jetons 1..k-1. Toute
autre construction lit le futur.
"""
import sqlite3, statistics as st, random

PEAGE, IMPACT, MISE_SOL = 0.024, 0.15, 50.0 / 94.06
c = sqlite3.connect("file:/app/db/intel.sqlite?mode=ro", uri=True)
c.row_factory = sqlite3.Row
createur = {r["mint"]: r["createur"] for r in c.execute("SELECT mint, createur FROM sol_createur")}
marque = {r["mint"]: r["telegram"] for r in c.execute("SELECT mint, telegram FROM tg_juges")}

courbes = {}
for r in c.execute("""SELECT p.mint, p.ts, p.age_s, p.prix_sol, p.reserve_sol
                      FROM solana_prix_chaine p JOIN pool_quote q ON q.pool=p.pair_id AND q.est_sol=1
                      WHERE p.prix_sol>0 ORDER BY p.mint, p.age_s"""):
    courbes.setdefault(r["mint"], []).append(dict(r))

T = []
for m, pts in courbes.items():
    if m not in createur:
        continue
    e = next((x for x in pts if 55 <= x["age_s"] <= 180), None)
    if not e or e["prix_sol"] <= 0 or not e["reserve_sol"] or MISE_SOL / e["reserve_sol"] > IMPACT:
        continue
    ap = [x for x in pts if x["age_s"] > e["age_s"]]
    if not ap:
        continue
    s = min(ap, key=lambda x: abs(x["age_s"] - (e["age_s"] + 240)))
    if abs(s["age_s"] - (e["age_s"] + 240)) > 45:
        continue
    T.append(dict(mint=m, ts=e["ts"], cre=createur[m], tg=bool(marque.get(m)),
                  g=(s["prix_sol"] / e["prix_sol"]) * (1 - PEAGE) - 1))
T.sort(key=lambda d: d["ts"])
print("  %d jetons avec un createur connu et un rendement mesurable" % len(T))

# historique construit dans l ordre du temps : jamais de futur
hist = {}
for x in T:
    h = hist.get(x["cre"], [])
    x["n_avant"] = len(h)
    x["dernier"] = h[-1] if h else None
    x["moy_avant"] = (sum(h) / len(h)) if h else None
    hist.setdefault(x["cre"], []).append(x["g"])

def stat(g):
    if len(g) < 10:
        return None
    b = max(g); sans = [v for v in g if v != b] or g
    return (len(g), sum(g)/len(g), st.median(g), sum(sans)/len(sans),
            sum(1 for v in g if v > 0)/len(g))

def l(lib, s):
    if not s:
        return "  %-30s      --" % lib
    return "  %-30s %5d %+9.3f %+9.3f %+10.3f %8.0f %%" % ((lib,) + s[:4] + (100*s[4],))

print()
print("  1. RECIDIVISTE CONTRE DEBUTANT")
print("  %-30s %5s %9s %9s %10s %9s" % ("", "n", "par euro", "mediane", "sans best", "gagnants"))
print(l("premier jeton du createur", stat([x["g"] for x in T if x["n_avant"] == 0])))
print(l("il en a deja fait 1", stat([x["g"] for x in T if x["n_avant"] == 1])))
print(l("il en a deja fait 2 ou plus", stat([x["g"] for x in T if x["n_avant"] >= 2])))

print()
print("  2. LE JETON PRECEDENT PREDIT-IL LE SUIVANT ?")
suite = [x for x in T if x["dernier"] is not None]
print("     %d jetons ont un predecesseur" % len(suite))
print(l("precedent GAGNANT", stat([x["g"] for x in suite if x["dernier"] > 0])))
print(l("precedent perdant", stat([x["g"] for x in suite if x["dernier"] <= 0])))
print(l("precedent au-dessus de +50 %", stat([x["g"] for x in suite if x["dernier"] > 0.5])))
print(l("precedent sous -50 %", stat([x["g"] for x in suite if x["dernier"] < -0.5])))

print()
print("  3. LE MEME, EN NE GARDANT QUE LES JETONS TELEGRAM (ce qu on achete)")
tg = [x for x in suite if x["tg"]]
print("     %d jetons Telegram avec un predecesseur" % len(tg))
print(l("precedent gagnant", stat([x["g"] for x in tg if x["dernier"] > 0])))
print(l("precedent perdant", stat([x["g"] for x in tg if x["dernier"] <= 0])))

print()
print("  4. UN CREATEUR PRODUIT-IL DES TELEGRAM DE FACON REGULIERE ?")
par = {}
for x in T:
    par.setdefault(x["cre"], []).append(1 if x["tg"] else 0)
multi = {k: v for k, v in par.items() if len(v) >= 2}
if multi:
    tous_tg = sum(1 for v in multi.values() if all(v))
    aucun = sum(1 for v in multi.values() if not any(v))
    mixte = len(multi) - tous_tg - aucun
    print("     %d createurs avec au moins 2 jetons : %d toujours Telegram · %d jamais · %d melanges"
          % (len(multi), tous_tg, aucun, mixte))
    base = sum(1 for x in T if x["tg"]) / len(T)
    attendu = len(multi) * base * base
    print("     si c etait au hasard on en attendrait %.1f « toujours Telegram », on en voit %d"
          % (attendu, tous_tg))
