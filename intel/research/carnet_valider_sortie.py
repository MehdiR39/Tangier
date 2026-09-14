"""Valider « prendre le gain a x2, sinon sortir a 240 s » sur un jeu qui ne l a pas suggeree.

L hypothese vient du rejeu de 29 tickets reels, ou 18 regles ont ete essayees. Avec 18 essais sur
29 observations, trouver une gagnante ne prouve rien : c est une HYPOTHESE, et elle doit etre jugee
sur des donnees qui n ont pas servi a la formuler.

Le jeu de jugement : les prix lus aux reserves des pools (`solana_prix_chaine`), pools verifies,
contrainte d execution appliquee avant mesure. On teste sur le groupe Telegram -- celui qu on trade
-- et on coupe en deux moities par date de naissance pour voir si l effet tient des deux cotes.
"""
import sqlite3, statistics as st, random

PEAGE, IMPACT, MISE_SOL = 0.024, 0.15, 50.0 / 94.06
c = sqlite3.connect("file:/app/db/intel.sqlite?mode=ro", uri=True)
c.row_factory = sqlite3.Row
marque = {r["mint"]: r["telegram"] for r in c.execute("SELECT mint, telegram FROM tg_juges")}

courbes = {}
for r in c.execute("""SELECT p.mint, p.ts, p.age_s, p.prix_sol, p.reserve_sol
                      FROM solana_prix_chaine p JOIN pool_quote q ON q.pool=p.pair_id AND q.est_sol=1
                      WHERE p.prix_sol>0 ORDER BY p.mint, p.age_s"""):
    if r["mint"] in marque:
        courbes.setdefault(r["mint"], []).append(dict(r))

def chemins(tg_only):
    out = []
    for m, pts in courbes.items():
        if tg_only and not marque[m]:
            continue
        if not tg_only and marque[m]:
            continue
        e = next((x for x in pts if 55 <= x["age_s"] <= 180), None)
        if not e or e["prix_sol"] <= 0 or not e["reserve_sol"] or MISE_SOL / e["reserve_sol"] > IMPACT:
            continue
        suite = [(x["age_s"] - e["age_s"], x["prix_sol"]) for x in pts if x["age_s"] > e["age_s"]]
        if len(suite) < 3 or max(a for a, _ in suite) < 200:
            continue
        out.append(dict(mint=m, ts=e["ts"], p0=e["prix_sol"], suite=suite))
    out.sort(key=lambda d: d["ts"])
    return out

def jouer(ch, objectif, limite=240):
    g = []
    for t in ch:
        m = None
        for age, p in t["suite"]:
            if age > limite:
                break
            if objectif and p / t["p0"] >= 1 + objectif:
                m = p / t["p0"]
                break
        if m is None:
            avant = [p for a, p in t["suite"] if a <= limite]
            if not avant:
                continue
            m = avant[-1] / t["p0"]
        g.append(m * (1 - PEAGE) - 1)
    return g

def ligne(lib, g):
    if len(g) < 6:
        return "  %-32s      --" % lib
    b = max(g); sans = [x for x in g if x != b] or g
    return ("  %-32s %4d %+9.3f %+9.3f %+10.3f %8.0f %%"
            % (lib, len(g), sum(g)/len(g), st.median(g), sum(sans)/len(sans),
               100*sum(1 for x in g if x > 0)/len(g)))

for lib, tg in (("JETONS TELEGRAM (ce qu on trade)", True), ("les autres (controle)", False)):
    ch = chemins(tg)
    if len(ch) < 12:
        print("  %s : %d chemins, trop peu" % (lib, len(ch))); continue
    mi = len(ch) // 2
    print("=" * 86)
    print("  %s · %d chemins complets" % (lib, len(ch)))
    print("  %-32s %4s %9s %9s %10s %9s" % ("", "n", "par euro", "mediane", "sans best", "gagnants"))
    for obj, nom in ((None, "sortie a 240 s  <-- EN PLACE"), (1.00, "objectif x2 sinon 240 s"),
                     (0.50, "objectif +50 % sinon 240 s"), (2.00, "objectif x3 sinon 240 s")):
        print(ligne(nom + "  (tout)", jouer(ch, obj)))
        if tg:
            print(ligne(nom + "  rech", jouer(ch[:mi], obj)))
            print(ligne(nom + "  JUG", jouer(ch[mi:], obj)))
    print()
