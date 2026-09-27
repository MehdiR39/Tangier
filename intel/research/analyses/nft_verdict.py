"""La rarete se paie-t-elle a la revente ? Verdict NFT.

Mesure du 14/09 : la rarete est pricee dans les LISTINGS de 5 collections sur 7, mais pas dans
claynosaurz (+0,015) ni smb_gen3 (+0,076). Si elle se paie quand meme a la vente, acheter une
piece rare au prix du plancher est un avantage mecanique.

RARETE CALCULEE PAR NOUS, a partir des traits de chaque piece vendue. Score statistique : la somme
des -log(frequence) de chaque trait. Plus c est grand, plus la piece est rare. On prefere calculer
que lire un rang tiers dont on ignore la formule et la date.

LIMITE A DECLARER : les frequences sont estimees sur les pieces VENDUES, pas sur la collection
entiere. Si les pieces rares se vendent plus souvent, leur rarete est sous-estimee -- ce qui
affaiblirait un effet reel, jamais n en creerait un faux.

PEAGE RELEVE AU PASSAGE : royalties 5,0 % (claynosaurz, smb_gen3) et 4,2 % (mad_lads), plus 2 %
de frais Magic Eden. Soit 6 a 7 % a la revente, contre 2,4 % sur nos jetons.
"""
import sqlite3, json, math, statistics as st, collections, random

c = sqlite3.connect("file:/app/db/intel.sqlite?mode=ro", uri=True)
c.row_factory = sqlite3.Row

def spearman(p):
    n = len(p)
    if n < 20:
        return None, None
    ra = {v: i for i, v in enumerate(sorted(x[0] for x in p))}
    rb = {v: i for i, v in enumerate(sorted(x[1] for x in p))}
    a = [ra[x[0]] for x in p]; b = [rb[x[1]] for x in p]
    ma, mb = sum(a)/n, sum(b)/n
    num = sum((a[i]-ma)*(b[i]-mb) for i in range(n))
    den = math.sqrt(sum((v-ma)**2 for v in a)*sum((v-mb)**2 for v in b))
    return (num/den if den else 0), 1.96/math.sqrt(n)

for col in ("claynosaurz", "smb_gen3", "mad_lads"):
    pieces = {r["mint"]: json.loads(r["traits"]) for r in c.execute(
        "SELECT mint, traits FROM nft_traits WHERE collection=?", (col,))}
    if len(pieces) < 40:
        print("  %-16s %d pieces, trop peu" % (col, len(pieces))); continue
    # frequences des traits
    freq = collections.Counter()
    for tr in pieces.values():
        for a in tr:
            freq[(a.get("trait_type"), a.get("value"))] += 1
    n = len(pieces)
    score = {}
    for m, tr in pieces.items():
        s = 0.0
        for a in tr:
            f = freq[(a.get("trait_type"), a.get("value"))] / n
            if f > 0:
                s += -math.log(f)
        score[m] = s
    # prix de vente
    paires = []
    for r in c.execute("SELECT mint, prix FROM nft_ventes WHERE collection=? AND mint IS NOT NULL"
                       " AND type IN ('buyNow','acceptBid')", (col,)):
        if r["mint"] in score and r["prix"]:
            paires.append((score[r["mint"]], float(r["prix"])))
    rho, seuil = spearman(paires)
    print()
    print("  " + "=" * 72)
    print("  %s · %d pieces · %d ventes appariees" % (col, n, len(paires)))
    if rho is None:
        print("     trop peu de ventes appariees"); continue
    print("     correlation rarete/prix de vente : %+.3f  (seuil %.3f)  -> %s"
          % (rho, seuil, "LA RARETE SE PAIE" if abs(rho) > seuil else "elle ne se paie pas"))
    # combien vaut le quart le plus rare contre le quart le plus commun ?
    paires.sort()
    q = len(paires)//4
    if q >= 5:
        commun = [p[1] for p in paires[:q]]
        rare = [p[1] for p in paires[-q:]]
        print("     quart le plus COMMUN : prix median %.2f SOL" % st.median(commun))
        print("     quart le plus RARE   : prix median %.2f SOL  -> ecart %+.0f %%"
              % (st.median(rare), 100*(st.median(rare)/st.median(commun)-1)))
        # le peage mange-t-il l ecart ?
        peage = 7.0
        print("     peage a la revente : %.1f %% (2 %% marche + 5 %% royalties)" % peage)
        ecart = 100*(st.median(rare)/st.median(commun)-1)
        print("     -> %s" % ("ecart SUPERIEUR au peage, il reste quelque chose"
                              if ecart > peage else "le peage mange l ecart"))
