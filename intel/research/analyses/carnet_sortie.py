"""Apprendre par l experience, sur la seule chose dont on ait assez de donnees : LA SORTIE.

L autopsie des 59 tickets dit qu a l instant d acheter, rien ne separe les gagnants des perdants.
C est une information, pas un echec : l entree ne se raffine pas avec 59 observations.

Mais un ticket ne donne pas UN chiffre, il donne une TRAJECTOIRE. Nos 59 achats portent chacun une
dizaine de relevés de prix entre l entree et la sortie -- soit des centaines d observations pour la
question « quand vendre ». C est la que « learning by doing » a assez de matiere.

On rejoue donc chaque ticket reel sous d autres regles de sortie, en n utilisant a chaque instant
que ce qui etait connu a cet instant. Le peage reel de chaque ticket est conserve : on l applique
tel qu il a ete constate, au lieu de le supposer.
"""
import sqlite3, statistics as st

c = sqlite3.connect("file:/app/db/intel.sqlite?mode=ro", uri=True)
c.row_factory = sqlite3.Row
bons = {r[0] for r in c.execute("SELECT pool FROM pool_quote WHERE est_sol=1")}

tickets = []
for r in c.execute("""SELECT mint, symbole, pair_id, ts_entree, ts_sortie, prix_entree,
                             prix_sortie, gain_eur, mise_eur FROM tg_lignes
                      WHERE mode='live' AND gain_eur IS NOT NULL ORDER BY ts_entree"""):
    d = dict(r)
    if d["pair_id"] not in bons or not d["prix_entree"]:
        continue
    chemin = [(x["ts"] - d["ts_entree"], x["prix_sol"]) for x in c.execute(
        "SELECT ts, prix_sol FROM solana_prix_chaine WHERE pair_id=? AND ts>=? AND ts<=?"
        " AND prix_sol>0 ORDER BY ts",
        (d["pair_id"], d["ts_entree"] - 5, d["ts_entree"] + 900))]
    if len(chemin) < 4:
        continue
    # le peage REEL de ce ticket : ce que le prix disait, moins ce qui est arrive au portefeuille
    mq = d["prix_sortie"] / d["prix_entree"] if d["prix_sortie"] else None
    mr = 1 + d["gain_eur"] / d["mise_eur"]
    peage = (1 - mr / mq) if mq and mq > 0 else 0.024
    peage = min(max(peage, 0.0), 0.12)          # borne : un peage negatif n existe pas
    d["chemin"], d["peage"] = chemin, peage
    tickets.append(d)

print("  %d tickets rejouables (trajectoire complete et pool verifie)" % len(tickets))
print("  peage reel median : %.1f %%" % (100 * st.median([t["peage"] for t in tickets])))
print()

def prix_a(t, age):
    c2 = [p for p in t["chemin"] if p[0] <= age]
    return c2[-1][1] if c2 else None

def rejouer(regle):
    g = []
    for t in tickets:
        m = regle(t)
        if m is None:
            continue
        g.append(m * (1 - t["peage"]) - 1)
    return g

def ligne(lib, g):
    if not g:
        return "  %-34s      --" % lib
    b = max(g); sans = [x for x in g if x != b] or g
    return ("  %-34s %4d %+9.3f %+9.3f %+10.3f %8.0f %% %+10.2f"
            % (lib, len(g), sum(g)/len(g), st.median(g), sum(sans)/len(sans),
               100*sum(1 for x in g if x > 0)/len(g), sum(g)*50))

print("  %-34s %4s %9s %9s %10s %9s %11s"
      % ("regle de sortie", "n", "par euro", "mediane", "sans best", "gagnants", "EUR a 50"))

def fixe(age):
    def f(t):
        a, b = prix_a(t, 0), prix_a(t, age)
        return b / a if a and b else None
    return f

for age in (120, 180, 240, 300, 360, 480, 600):
    print(ligne("sortie fixe a %d s%s" % (age, "   <-- EN PLACE" if age == 240 else ""),
                rejouer(fixe(age))))

print()
def objectif(seuil, limite=240):
    """Vendre des que le prix atteint x(1+seuil), sinon a la limite."""
    def f(t):
        a = prix_a(t, 0)
        if not a:
            return None
        for age, p in t["chemin"]:
            if 0 < age <= limite and p / a >= 1 + seuil:
                return p / a
        b = prix_a(t, limite)
        return b / a if b else None
    return f

for s in (0.15, 0.30, 0.50, 1.00):
    print(ligne("objectif +%.0f %% sinon 240 s" % (100*s), rejouer(objectif(s))))

print()
def stop(seuil, limite=240):
    """Couper des que le prix tombe sous x(1-seuil)."""
    def f(t):
        a = prix_a(t, 0)
        if not a:
            return None
        for age, p in t["chemin"]:
            if 0 < age <= limite and p / a <= 1 - seuil:
                return p / a
        b = prix_a(t, limite)
        return b / a if b else None
    return f

for s in (0.15, 0.25, 0.40, 0.60):
    print(ligne("stop a -%.0f %% sinon 240 s" % (100*s), rejouer(stop(s))))

print()
def suiveur(recul, limite=240):
    """Vendre quand le prix retombe de `recul` sous son plus haut depuis l entree."""
    def f(t):
        a = prix_a(t, 0)
        if not a:
            return None
        haut = a
        for age, p in t["chemin"]:
            if age <= 0:
                continue
            haut = max(haut, p)
            if age <= limite and p <= haut * (1 - recul):
                return p / a
        b = prix_a(t, limite)
        return b / a if b else None
    return f

for s in (0.15, 0.25, 0.40):
    print(ligne("suiveur -%.0f %% du plus haut" % (100*s), rejouer(suiveur(s))))
