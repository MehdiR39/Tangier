"""Qu est-ce qui fait qu une journee est bonne ou mauvaise ? Mesure, pas intuition.

L operateur, le 14/09 : « pour une journee meilleure qu une autre c est quoi le driver ? le marche
crypto ? le BTC ? le ETH ? les createurs ? »

Le carnet reel ne compte que trois jours -- impossible d y correler quoi que ce soit. Mais on a
cinq jours de prix sur TOUS les jetons gradues, ce qui permet de construire une serie HORAIRE de
« ce que rend la strategie » sur des centaines d observations au lieu de trois.

On teste quatre familles de causes :
  1. le marche memecoin lui-meme -- ce que rendent tous les jetons, y compris ceux qu on n achete pas ;
  2. BTC et SOL, en niveau et en variation horaire (Binance, bougies 1 h) ;
  3. le FLUX -- nombre de migrations et de creations dans l heure ;
  4. les createurs -- un createur revient-il, et ses jetons se ressemblent-ils ?

La correlation est mesuree sur les rangs (Spearman) : elle ne suppose pas de relation lineaire et
resiste aux valeurs extremes, ce qui est indispensable sur une distribution a queue epaisse.
"""
import sqlite3, statistics as st, json, urllib.request, time, math

PEAGE, IMPACT, MISE_SOL = 0.024, 0.15, 50.0 / 94.06
c = sqlite3.connect("file:/app/db/intel.sqlite?mode=ro", uri=True)
c.row_factory = sqlite3.Row
marque = {r["mint"]: r["telegram"] for r in c.execute("SELECT mint, telegram FROM tg_juges")}

courbes = {}
for r in c.execute("""SELECT p.mint, p.ts, p.age_s, p.prix_sol, p.reserve_sol
                      FROM solana_prix_chaine p JOIN pool_quote q ON q.pool=p.pair_id AND q.est_sol=1
                      WHERE p.prix_sol>0 ORDER BY p.mint, p.age_s"""):
    courbes.setdefault(r["mint"], []).append(dict(r))

tickets = []
for m, pts in courbes.items():
    e = next((x for x in pts if 55 <= x["age_s"] <= 180), None)
    if not e or e["prix_sol"] <= 0 or not e["reserve_sol"] or MISE_SOL / e["reserve_sol"] > IMPACT:
        continue
    ap = [x for x in pts if x["age_s"] > e["age_s"]]
    if not ap:
        continue
    s = min(ap, key=lambda x: abs(x["age_s"] - (e["age_s"] + 240)))
    if abs(s["age_s"] - (e["age_s"] + 240)) > 45:
        continue
    tickets.append(dict(ts=e["ts"], tg=bool(marque.get(m)),
                        g=(s["prix_sol"] / e["prix_sol"]) * (1 - PEAGE) - 1))
print("  %d tickets simules · dont %d Telegram" % (len(tickets), sum(1 for x in tickets if x["tg"])))

# ---- series horaires ----
H = {}
for x in tickets:
    h = x["ts"] - x["ts"] % 3600
    H.setdefault(h, []).append(x)
heures = sorted(h for h, v in H.items() if len(v) >= 8)
print("  %d heures avec au moins 8 tickets" % len(heures))

def klines(sym):
    u = "https://api.binance.com/api/v3/klines?symbol=%s&interval=1h&limit=200" % sym
    req = urllib.request.Request(u, headers={"user-agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as x:
        return {int(k[0]) // 1000: (float(k[1]), float(k[4])) for k in json.loads(x.read())}

btc, sol = klines("BTCUSDT"), klines("SOLUSDT")

def spearman(a, b):
    n = len(a)
    if n < 8:
        return None
    ra = {v: i for i, v in enumerate(sorted(a))}
    rb = {v: i for i, v in enumerate(sorted(b))}
    x = [ra[v] for v in a]; y = [rb[v] for v in b]
    mx, my = sum(x)/n, sum(y)/n
    num = sum((x[i]-mx)*(y[i]-my) for i in range(n))
    den = math.sqrt(sum((v-mx)**2 for v in x) * sum((v-my)**2 for v in y))
    return num/den if den else None

serie = {"nous (Telegram)": [], "marche (tous jetons)": [], "BTC variation": [],
         "SOL variation": [], "BTC niveau": [], "SOL niveau": [], "flux (tickets/h)": []}
for h in heures:
    v = H[h]
    tg = [x["g"] for x in v if x["tg"]]
    serie["nous (Telegram)"].append(st.median(tg) if tg else None)
    serie["marche (tous jetons)"].append(st.median([x["g"] for x in v]))
    b, s = btc.get(h), sol.get(h)
    serie["BTC variation"].append((b[1]/b[0]-1) if b else None)
    serie["SOL variation"].append((s[1]/s[0]-1) if s else None)
    serie["BTC niveau"].append(b[1] if b else None)
    serie["SOL niveau"].append(s[1] if s else None)
    serie["flux (tickets/h)"].append(float(len(v)))

cible = serie["marche (tous jetons)"]
print()
print("  CE QUI EXPLIQUE LA PERFORMANCE HORAIRE DU MARCHE MEMECOIN")
print("  %-26s %6s %12s" % ("cause candidate", "n", "correlation"))
for nom in ("BTC variation", "SOL variation", "BTC niveau", "SOL niveau", "flux (tickets/h)"):
    paires = [(a, b) for a, b in zip(serie[nom], cible) if a is not None and b is not None]
    if len(paires) < 8:
        print("  %-26s %6d   trop peu" % (nom, len(paires))); continue
    r = spearman([p[0] for p in paires], [p[1] for p in paires])
    print("  %-26s %6d %+12.3f" % (nom, len(paires), r if r is not None else 0))

print()
print("  ET NOUS, SUIVONS-NOUS LE MARCHE ?")
paires = [(a, b) for a, b in zip(serie["marche (tous jetons)"], serie["nous (Telegram)"])
          if a is not None and b is not None]
r = spearman([p[0] for p in paires], [p[1] for p in paires])
print("  correlation entre le marche et notre groupe Telegram : %+.3f sur %d heures"
      % (r if r is not None else 0, len(paires)))
for nom in ("BTC variation", "SOL variation", "flux (tickets/h)"):
    paires = [(a, b) for a, b in zip(serie[nom], serie["nous (Telegram)"])
              if a is not None and b is not None]
    if len(paires) < 8:
        continue
    r = spearman([p[0] for p in paires], [p[1] for p in paires])
    print("  %-26s -> nous : %+.3f sur %d heures" % (nom, r if r is not None else 0, len(paires)))
