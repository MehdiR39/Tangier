"""Y a-t-il vraiment des SEQUENCES, ou notre oeil en fabrique-t-il ?

L operateur, le 14/09 : « ce que j arrive pas a comprendre c est la sequentialite, une sequence de
positions gagnantes et une sequence de positions perdantes, je m attends a un truc plus homogene ».

C est une question a enjeu : si les resultats se groupent vraiment, alors s arreter apres N pertes
rapporterait de l argent. Si au contraire c est la forme normale du hasard, toute regle de ce type
coute des tickets sans rien gagner.

TROIS TESTS, du plus simple au plus fin :
  1. le test des SUITES (Wald-Wolfowitz) : compter les blocs consecutifs de gagnants ou de perdants
     et comparer a ce qu un tirage au hasard produit. Moins de blocs = ca se groupe vraiment ;
  2. l autocorrelation des rendements, aux decalages 1, 2, 3 ;
  3. la question directe : apres une perte, le ticket suivant est-il different ?

On le fait sur nos 65 tickets reels ET sur les 2 734 tickets simules du jeu de prix chaine, parce
que 65 observations ne peuvent pas detecter un groupement modere.
"""
import sqlite3, random, statistics as st, math

PEAGE, IMPACT, MISE_SOL = 0.024, 0.15, 50.0/94.06

def suites(signes):
    """Nombre de blocs consecutifs, et ce qu on en attend au hasard."""
    n1 = sum(1 for s in signes if s > 0)
    n2 = len(signes) - n1
    if n1 < 2 or n2 < 2:
        return None
    r = 1 + sum(1 for i in range(1, len(signes)) if (signes[i] > 0) != (signes[i-1] > 0))
    att = 1 + 2*n1*n2/(n1+n2)
    var = (2*n1*n2*(2*n1*n2-n1-n2))/(((n1+n2)**2)*(n1+n2-1))
    z = (r - att)/math.sqrt(var) if var > 0 else 0
    return r, att, z

def autocorr(v, k):
    n = len(v) - k
    if n < 10:
        return None
    a, b = v[:-k], v[k:]
    ma, mb = sum(a)/len(a), sum(b)/len(b)
    num = sum((a[i]-ma)*(b[i]-mb) for i in range(n))
    den = math.sqrt(sum((x-ma)**2 for x in a)*sum((x-mb)**2 for x in b))
    return num/den if den else None

def analyse(nom, v):
    print()
    print("  " + "=" * 76)
    print("  %s · %d tickets · %.0f %% de gagnants" % (nom, len(v), 100*sum(1 for x in v if x > 0)/len(v)))
    s = suites(v)
    if s:
        r, att, z = s
        verdict = ("SE GROUPENT vraiment" if z < -1.96 else
                   "alternent trop (anti-groupement)" if z > 1.96 else
                   "exactement ce que donne le hasard")
        print("    suites observees %d · attendues au hasard %.1f · ecart %+.2f sigma -> %s"
              % (r, att, z, verdict))
    print("    autocorrelation :", end="")
    for k in (1, 2, 3):
        a = autocorr(v, k)
        seuil = 1.96/math.sqrt(len(v)-k)
        print("  decalage %d : %+.3f (seuil %.3f%s)"
              % (k, a if a is not None else 0, seuil,
                 ", SIGNIFICATIF" if a is not None and abs(a) > seuil else ""), end="")
    print()
    apres_perte = [v[i] for i in range(1, len(v)) if v[i-1] <= 0]
    apres_gain = [v[i] for i in range(1, len(v)) if v[i-1] > 0]
    if len(apres_perte) >= 10 and len(apres_gain) >= 10:
        print("    apres une PERTE  : %+.4f par euro sur %d tickets (%.0f %% gagnants)"
              % (sum(apres_perte)/len(apres_perte), len(apres_perte),
                 100*sum(1 for x in apres_perte if x > 0)/len(apres_perte)))
        print("    apres un GAIN    : %+.4f par euro sur %d tickets (%.0f %% gagnants)"
              % (sum(apres_gain)/len(apres_gain), len(apres_gain),
                 100*sum(1 for x in apres_gain if x > 0)/len(apres_gain)))
    # la plus longue serie observee, contre ce que le hasard produit
    def plus_longue(x):
        best = cur = 0
        for g in x:
            cur = cur+1 if g <= 0 else 0
            best = max(best, cur)
        return best
    pl = plus_longue(v)
    random.seed(3)
    tirs = [plus_longue(random.sample(v, len(v))) for _ in range(5000)]
    tirs.sort()
    p = sum(1 for t in tirs if t >= pl)/len(tirs)
    print("    plus longue serie de perdants : %d · au hasard on en voit %d ou plus dans %.0f %% des cas"
          % (pl, pl, 100*p))

c = sqlite3.connect("file:/app/db/intel.sqlite?mode=ro", uri=True)
c.row_factory = sqlite3.Row
reel = [r[0]/r[1] for r in c.execute(
    "SELECT gain_eur, mise_eur FROM tg_lignes WHERE mode='live' AND gain_eur IS NOT NULL"
    " ORDER BY ts_entree")]
analyse("NOTRE CARNET REEL", reel)

marque = {r["mint"]: r["telegram"] for r in c.execute("SELECT mint, telegram FROM tg_juges")}
courbes = {}
for r in c.execute("""SELECT p.mint,p.ts,p.age_s,p.prix_sol,p.reserve_sol FROM solana_prix_chaine p
                      JOIN pool_quote q ON q.pool=p.pair_id AND q.est_sol=1
                      WHERE p.prix_sol>0 ORDER BY p.mint,p.age_s"""):
    courbes.setdefault(r["mint"], []).append(dict(r))
T = []
for m, pts in courbes.items():
    e = next((x for x in pts if 55 <= x["age_s"] <= 180), None)
    if not e or e["prix_sol"] <= 0 or not e["reserve_sol"] or MISE_SOL/e["reserve_sol"] > IMPACT:
        continue
    ap = [x for x in pts if x["age_s"] > e["age_s"]]
    if not ap:
        continue
    s = min(ap, key=lambda x: abs(x["age_s"]-(e["age_s"]+240)))
    if abs(s["age_s"]-(e["age_s"]+240)) > 45:
        continue
    T.append((e["ts"], (s["prix_sol"]/e["prix_sol"])*(1-PEAGE)-1))
T.sort()
analyse("TOUS LES JETONS (jeu de prix chaine, pour la puissance)", [g for _, g in T])
