"""Autopsie des 59 tickets reels : qu est-ce qui separe ceux qui ont gagne de ceux qui ont perdu ?

METHODE, et c est elle qui compte. Sur 59 tickets, chercher parmi quinze variables laquelle
separe le mieux GARANTIT de trouver quelque chose : avec quinze essais, une separation au hasard
a 54 % de chances d apparaitre sous le seuil de 5 %. Le carnet reel ne peut donc servir qu a
FORMULER des hypotheses, jamais a les valider.

La validation se fait ailleurs, sur le jeu independant des prix lus aux reserves (986 tickets, dont
55 Telegram), qui n a servi a choisir aucun seuil. C est la seule facon de ne pas se raconter une
histoire sur cinquante-neuf lignes.

Ce fichier fait l etape 1 : decrire chaque ticket par ce qu on SAVAIT a l instant d acheter.
"""
import sqlite3, statistics as st, time

SOL_EUR = 94.06
c = sqlite3.connect("file:/app/db/intel.sqlite?mode=ro", uri=True)
c.row_factory = sqlite3.Row

offres = {r[0]: r[1] for r in c.execute("SELECT mint, offre FROM mint_offre")}
fiches = {r["mint"]: dict(r) for r in c.execute("SELECT mint, telegram, twitter, site FROM tg_juges")}
bons = {r[0] for r in c.execute("SELECT pool FROM pool_quote WHERE est_sol=1")}

lignes = []
for r in c.execute("""SELECT mint, symbole, pair_id, ts_entree, age_entree, age_lecture,
                             prix_entree, prix_sortie, gain_eur, mise_eur, ts_sortie
                      FROM tg_lignes WHERE mode='live' AND gain_eur IS NOT NULL
                      ORDER BY ts_entree"""):
    d = dict(r)
    d["pe"] = d["gain_eur"] / d["mise_eur"]
    d["pool_ok"] = d["pair_id"] in bons
    # l etat du pool a l instant d entrer
    p = c.execute("""SELECT reserve_sol, reserve_base, prix_sol, age_s FROM solana_prix_chaine
                     WHERE pair_id=? AND ts BETWEEN ? AND ? ORDER BY ABS(ts-?) LIMIT 1""",
                  (d["pair_id"], d["ts_entree"] - 90, d["ts_entree"] + 90, d["ts_entree"])).fetchone()
    d["pool"] = p["reserve_sol"] if p and d["pool_ok"] else None
    d["mcap"] = (p["prix_sol"] * offres.get(d["mint"], 0) * SOL_EUR * 1.08
                 if p and d["pool_ok"] and offres.get(d["mint"]) else None)
    d["part_pool"] = (p["reserve_base"] / offres[d["mint"]]
                      if p and d["pool_ok"] and offres.get(d["mint"]) else None)
    # la trajectoire AVANT notre achat : le prix montait-il deja ?
    av = [x[0] for x in c.execute(
        "SELECT prix_sol FROM solana_prix_chaine WHERE pair_id=? AND ts < ? ORDER BY ts",
        (d["pair_id"], d["ts_entree"])) if x[0]]
    d["hausse_avant"] = (av[-1] / av[0] - 1) if len(av) >= 2 and av[0] > 0 else None
    d["n_avant"] = len(av)
    f = fiches.get(d["mint"], {})
    d["twitter"], d["site"] = f.get("twitter"), f.get("site")
    d["heure"] = time.gmtime(d["ts_entree"]).tm_hour
    # combien de lignes etaient ouvertes au moment d acheter
    d["simultanees"] = c.execute(
        "SELECT COUNT(*) FROM tg_lignes WHERE mode='live' AND ts_entree < ? AND ts_sortie > ?",
        (d["ts_entree"], d["ts_entree"])).fetchone()[0]
    lignes.append(d)

print("  %d tickets · %d avec un pool verifie" % (len(lignes), sum(1 for x in lignes if x["pool_ok"])))
print()
g = [x for x in lignes if x["pe"] > 0]
p = [x for x in lignes if x["pe"] <= 0]
print("  %d gagnants (%+.2f EUR) · %d perdants (%+.2f EUR)"
      % (len(g), sum(x["gain_eur"] for x in g), len(p), sum(x["gain_eur"] for x in p)))
print()
print("  CE QUI SEPARE, variable par variable (mediane des gagnants contre celle des perdants)")
print("  %-18s %14s %14s %10s %6s" % ("variable", "GAGNANTS", "PERDANTS", "ecart", "n"))
for cle, lib, fmt in (("pool", "pool a l entree", "%.1f SOL"), ("mcap", "capitalisation", "%.0f $"),
                      ("part_pool", "part offre pool", "%.3f"), ("age_entree", "age a l achat", "%.0f s"),
                      ("age_lecture", "fraicheur prix", "%.0f s"), ("hausse_avant", "hausse avant", "%+.3f"),
                      ("n_avant", "relevés avant", "%.0f"), ("heure", "heure UTC", "%.0f h"),
                      ("simultanees", "lignes ouvertes", "%.1f"), ("mise_eur", "mise", "%.0f EUR")):
    a = [x[cle] for x in g if x.get(cle) is not None]
    b = [x[cle] for x in p if x.get(cle) is not None]
    if len(a) < 5 or len(b) < 5:
        print("  %-18s %14s" % (lib, "trop peu")); continue
    ma, mb = st.median(a), st.median(b)
    ec = (ma / mb) if mb else float("nan")
    print("  %-18s %14s %14s %9.2fx %6d"
          % (lib, fmt % ma, fmt % mb, ec, len(a) + len(b)))
print()
print("  LES DIX PLUS GROS GAINS ET LES DIX PLUS GROSSES PERTES")
tri = sorted(lignes, key=lambda x: -x["pe"])
print("  %-12s %8s %9s %9s %8s %7s %6s %5s" % ("", "EUR", "pool", "mcap $", "hausse", "age", "heure", "tw/st"))
for x in tri[:10] + [None] + tri[-10:]:
    if x is None:
        print("  " + "-" * 66); continue
    print("  %-12s %+8.2f %9s %9s %8s %6ds %5dh %s/%s"
          % (x["symbole"][:12], x["gain_eur"],
             ("%.1f" % x["pool"]) if x["pool"] else "-",
             ("%.0f" % x["mcap"]) if x["mcap"] else "-",
             ("%+.2f" % x["hausse_avant"]) if x["hausse_avant"] is not None else "-",
             x["age_entree"], x["heure"], x["twitter"], x["site"]))
