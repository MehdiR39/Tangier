"""Portefeuille a blanc sur BNB : toutes les combinaisons, jugees avec la meme discipline.

DONNEES. 617 jetons four.meme dont nous possedons un historique de prix HORODATE PAR NOUS
(bnb_releves du 13/09), croise avec leurs liens sociaux lus chez four.meme (bnb_social).

DISCIPLINE, identique a celle qui a tue quatre fausses decouvertes cette semaine :
  - coupure recherche / JUGEMENT sur la date de naissance du jeton ;
  - resultat prive de son meilleur ticket (`sans best`) ;
  - test du hasard sur la moitie de jugement ;
  - seuil corrige pour le test multiple : on compte les cellules essayees.

LIMITE DECLAREE : les liens sociaux sont lus aujourd hui pour des jetons d hier, et four.meme
permet de les ajouter apres coup (derive mesuree ~4 points par jour). Tout survivant devra etre
reconfirme sur la collecte horodatee en cours.
"""
import sqlite3, statistics as st, random, itertools

PEAGE = 0.03
c = sqlite3.connect("file:/app/db/intel.sqlite?mode=ro", uri=True)
c.row_factory = sqlite3.Row

soc = {r["jeton"]: dict(r) for r in c.execute("SELECT * FROM bnb_social")}
naiss = {r["jeton"]: r["ts_vu"] for r in c.execute("SELECT jeton, ts_vu FROM bnb_lancements")}
series = {}
for r in c.execute("SELECT jeton, age_s, prix_usd FROM bnb_releves"
                   " WHERE prix_usd IS NOT NULL AND prix_usd > 0 ORDER BY jeton, age_s"):
    if r["jeton"] in soc:
        series.setdefault(r["jeton"], []).append((r["age_s"], r["prix_usd"]))

ages = sorted(a for s in series.values() for a, _ in s)
print("  %d jetons · %d relevés · age des relevés : p10 %ds · median %ds · p90 %ds · max %ds"
      % (len(series), len(ages), ages[len(ages)//10], ages[len(ages)//2],
         ages[9*len(ages)//10], ages[-1]))

def tickets(entree, tenue):
    out = []
    for j, s in series.items():
        e = next((p for p in s if p[0] >= entree), None)
        if not e:
            continue
        ap = [p for p in s if p[0] > e[0]]
        if not ap:
            continue
        x = min(ap, key=lambda p: abs(p[0] - (e[0] + tenue)))
        if abs(x[0] - (e[0] + tenue)) > max(60, tenue * 0.4):
            continue
        out.append(dict(j=j, ts=naiss.get(j, 0), **soc[j],
                        gain=(x[1] / e[1]) * (1 - PEAGE) - 1))
    out.sort(key=lambda d: d["ts"])
    return out

FILTRES = {
    "tout":                 lambda d: True,
    "telegram":             lambda d: d["telegram"],
    "SANS telegram":        lambda d: not d["telegram"],
    "twitter":              lambda d: d["twitter"],
    "site":                 lambda d: d["site"],
    "telegram+site":        lambda d: d["telegram"] and d["site"],
    "telegram sans twitter": lambda d: d["telegram"] and not d["twitter"],
    "les trois":            lambda d: d["telegram"] and d["twitter"] and d["site"],
    "aucun reseau":         lambda d: not (d["telegram"] or d["twitter"] or d["site"]),
}

def stat(g):
    if len(g) < 12:
        return None
    v = [x["gain"] for x in g]
    b = max(v); sans = [x for x in v if x != b] or v
    return dict(n=len(v), pe=sum(v)/len(v), med=st.median(v), sans=sum(sans)/len(sans),
                win=sum(1 for x in v if x > 0)/len(v))

def hasard(tous, k, cible, n=20000, seed=17):
    v = [x["gain"] for x in tous]
    if k < 5 or k >= len(v):
        return None
    random.seed(seed)
    return sum(1 for _ in range(n) if sum(random.sample(v, k))/k >= cible)/n

ENTREES = (60, 120, 240, 420)
TENUES = (120, 300, 600, 1200)
cellules = []
print()
print("  BALAYAGE : %d entrees x %d tenues x %d filtres = %d cellules"
      % (len(ENTREES), len(TENUES), len(FILTRES), len(ENTREES)*len(TENUES)*len(FILTRES)))
print("  seuil corrige pour le test multiple : %.4f %%" % (100*0.05/(len(ENTREES)*len(TENUES)*len(FILTRES))))
print()
print("  %-22s %-6s %-6s %5s %9s %9s %10s %8s" % ("filtre","entree","tenue","n","recherche","JUGEMENT","sans best","gagn."))
for entree, tenue in itertools.product(ENTREES, TENUES):
    T = tickets(entree, tenue)
    if len(T) < 40:
        continue
    mi = len(T)//2
    for nom, f in FILTRES.items():
        R = [x for x in T[:mi] if f(x)]
        J = [x for x in T[mi:] if f(x)]
        sr, sj = stat(R), stat(J)
        if not sr or not sj:
            continue
        cellules.append(dict(nom=nom, e=entree, t=tenue, sr=sr, sj=sj, J=J, T=T[mi:]))
        print("  %-22s T+%-4d %-6d %5d %+9.3f %+9.3f %+10.3f %7.0f %%"
              % (nom, entree, tenue, sj["n"], sr["pe"], sj["pe"], sj["sans"], 100*sj["win"]))

print()
print("=" * 92)
print("  CE QUI SURVIT : positif dans les DEUX moities, ET sans son meilleur ticket")
gagnants = [x for x in cellules if x["sr"]["pe"] > 0 and x["sj"]["pe"] > 0 and x["sj"]["sans"] > 0]
if not gagnants:
    print("    AUCUNE cellule sur %d." % len(cellules))
else:
    seuil = 0.05/len(cellules)
    print("    %d cellules sur %d. Test du hasard, seuil corrige %.4f %%:" % (len(gagnants), len(cellules), 100*seuil))
    for x in sorted(gagnants, key=lambda y: -y["sj"]["pe"]):
        h = hasard(x["T"], x["sj"]["n"], x["sj"]["pe"])
        v = "RETENU" if h is not None and h < seuil else "rejete (hasard)"
        print("      %-22s T+%-4d %-5d  JUG %+.3f  sans best %+.3f  hasard %6.3f %%  -> %s"
              % (x["nom"], x["e"], x["t"], x["sj"]["pe"], x["sj"]["sans"],
                 100*h if h is not None else -1, v))
