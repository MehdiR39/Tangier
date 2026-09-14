"""Le filtre « 3 signes », explique et chiffre jour par jour.

LES TROIS SIGNES, tous mesures AVANT T+90 s sur les reserves du pool qu on lit deja :
  1. le prix a l entree est au-dessus de son premier releve, d au moins +0,7 % ;
  2. le prix n est JAMAIS descendu sous ce premier releve depuis le debut ;
  3. la liquidite du pool a grossi d au moins +0,35 % sur la meme periode.
On n achete que si les TROIS sont vrais.

L INVERSION EST LE POINT INTERESSANT. Sur la population generale (S3.66), ces memes signes
designent les lancements qui se font VIDER cinq fois plus : un jeton qui monte tout droit sans
jamais reculer, avec de la liquidite qui arrive, ressemble a une mise en scene. Mais chez les
jetons porteurs d un Telegram, le meme profil designe les BONS. Deux populations, deux sens.
"""
import sqlite3, statistics as st, time

c = sqlite3.connect("file:/app/db/intel.sqlite?mode=ro", uri=True)
c.row_factory = sqlite3.Row
bons = {r[0] for r in c.execute("SELECT pool FROM pool_quote WHERE est_sol=1")}

def signes(av, e):
    p0 = av[0]["prix_sol"]; l0 = av[0]["reserve_sol"] or 0
    if p0 <= 0:
        return None, None
    s1 = e["prix_sol"]/p0 - 1 >= 0.007
    s2 = min(x["prix_sol"] for x in av)/p0 - 1 >= 0
    s3 = (e["reserve_sol"]/l0 - 1 if l0 > 0 else 0) >= 0.0035
    return int(s1)+int(s2)+int(s3), (s1, s2, s3)

L = []
for r in c.execute("""SELECT symbole,mint,pair_id,ts_entree,ts_sortie,gain_eur,mise_eur
                      FROM tg_lignes WHERE mode='live' AND gain_eur IS NOT NULL ORDER BY ts_entree"""):
    d = dict(r)
    d["jour"] = time.strftime("%d/%m", time.gmtime(d["ts_sortie"]))
    d["sg"] = None
    if d["pair_id"] in bons:
        av = [dict(x) for x in c.execute(
            "SELECT prix_sol,reserve_sol FROM solana_prix_chaine WHERE pair_id=? AND ts<=? AND prix_sol>0"
            " ORDER BY ts", (d["pair_id"], d["ts_entree"]))]
        if len(av) >= 3:
            d["sg"], d["detail"] = signes(av, av[-1])
    L.append(d)

print("  EFFET DU FILTRE, JOUR PAR JOUR")
print("  %-8s %6s %10s %8s %12s %12s %12s"
      % ("jour", "achats", "gardes", "part", "sans filtre", "AVEC filtre", "difference"))
for j in sorted({x["jour"] for x in L}):
    g = [x for x in L if x["jour"] == j]
    k = [x for x in g if x["sg"] == 3]
    sans = sum(x["gain_eur"] for x in g)
    avec = sum(x["gain_eur"] for x in k)
    print("  %-8s %6d %10d %7.0f %% %+11.2f %+12.2f %+12.2f"
          % (j, len(g), len(k), 100*len(k)/len(g), sans, avec, avec-sans))
tot = sum(x["gain_eur"] for x in L)
totf = sum(x["gain_eur"] for x in L if x["sg"] == 3)
nk = sum(1 for x in L if x["sg"] == 3)
print("  %-8s %6d %10d %7.0f %% %+11.2f %+12.2f %+12.2f"
      % ("TOTAL", len(L), nk, 100*nk/len(L), tot, totf, totf-tot))

print()
print("  COMBIEN D ACHATS EN MOINS ? (le flux perdu)")
print("     %.0f %% des achats seraient conserves, soit %.1f par jour au lieu de %.1f"
      % (100*nk/len(L), nk/3.0, len(L)/3.0))

print()
print("  QUEL SIGNE FAIT LE TRI ? (part des achats ou chaque signe est vrai)")
vus = [x for x in L if x.get("detail")]
for i, lib in enumerate(("prix au-dessus du depart", "jamais descendu sous le depart",
                         "liquidite en hausse")):
    k = sum(1 for x in vus if x["detail"][i])
    print("     %-34s %3d / %d = %.0f %%" % (lib, k, len(vus), 100*k/len(vus)))

print()
print("  LES TICKETS QUE LE FILTRE AURAIT REFUSES AUJOURD HUI")
for x in L:
    if x["jour"] == "14/09" and x["sg"] != 3:
        print("     %-12s %2s signe(s) · %+8.2f EUR"
              % (x["symbole"][:12], x["sg"] if x["sg"] is not None else "?", x["gain_eur"]))
