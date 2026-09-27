"""Collecter les VENTES NFT avec leur rang de rarete. N ACHETE RIEN.

Premiere tentative ratee, et la cause valait la peine d etre trouvee : le flux d activites est a
99,7 % des offres et des listings -- 0,3 % de ventes. Il aurait fallu 260 pages par collection.
L API accepte `type=buyNow`, qui ramene 100 % de ventes. Deux autres orthographes (`activityType`,
`kind`) sont acceptees SANS effet : elles renvoient le flux non filtre, ce qui aurait produit une
collecte silencieusement inutile.

Question a trancher : la rarete est non pricee dans les listings de claynosaurz (+0,015) et
smb_gen3 (+0,076), pricee ailleurs. Se paie-t-elle a la revente ? Si oui, acheter une piece rare
au prix du plancher est un avantage mecanique. Si non, le marche a raison de l ignorer.
"""
import json, sqlite3, time, urllib.request

B = "https://api-mainnet.magiceden.dev/v2"
COLS = ["claynosaurz", "smb_gen3", "mad_lads", "okay_bears", "cets_on_creck",
        "famous_fox_federation", "solana_monkey_business"]
CIBLE = 500          # ventes voulues par collection

def g(url, essais=4):
    for i in range(essais):
        try:
            req = urllib.request.Request(url, headers={"user-agent": "Mozilla/5.0",
                                                       "accept": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as x:
                return json.loads(x.read())
        except Exception as e:
            time.sleep(4 * (i + 1) if "429" in str(e) else 2)
    return None

def rang(x):
    r = x.get("rarity") or {}
    for src in ("moonrank", "howrare"):
        v = (r.get(src) or {}).get("rank")
        if v:
            return float(v)
    return None

c = sqlite3.connect("/app/db/intel.sqlite")
c.execute("CREATE TABLE IF NOT EXISTS nft_ventes("
          "  signature TEXT PRIMARY KEY, collection TEXT, mint TEXT, type TEXT,"
          "  prix REAL, rang REAL, ts INTEGER)")
c.commit()

for s in COLS:
    for typ in ("buyNow", "acceptBid"):
        for page in range(0, 12):
            a = g("%s/collections/%s/activities?offset=%d&limit=500&type=%s"
                  % (B, s, page * 500, typ))
            if not isinstance(a, list) or not a:
                break
            # garde-fou : si le filtre est ignore, on le voit et on s arrete
            vrais = [x for x in a if x.get("type") == typ]
            if len(vrais) < len(a) * 0.5:
                print("    %s/%s : filtre ignore par l API, on abandonne ce type" % (s, typ), flush=True)
                break
            for x in vrais:
                if not x.get("signature") or not x.get("price"):
                    continue
                try:
                    c.execute("INSERT OR IGNORE INTO nft_ventes VALUES(?,?,?,?,?,?,?)",
                              (x["signature"], s, x.get("tokenMint"), x.get("type"),
                               float(x["price"]), rang(x), int(x.get("blockTime") or 0)))
                except Exception:
                    pass
            c.commit()
            n = c.execute("SELECT COUNT(*) FROM nft_ventes WHERE collection=?"
                          " AND type IN ('buyNow','acceptBid')", (s,)).fetchone()[0]
            if n >= CIBLE or len(a) < 500:
                break
            time.sleep(1.2)
    r = c.execute("SELECT COUNT(*) n, SUM(CASE WHEN rang IS NOT NULL THEN 1 ELSE 0 END) k,"
                  " MIN(ts) a, MAX(ts) b FROM nft_ventes WHERE collection=?"
                  " AND type IN ('buyNow','acceptBid')", (s,)).fetchone()
    duree = (r[3]-r[2])/86400 if r[2] and r[3] and r[3] > r[2] else 0
    print("  %-26s %5d ventes · %5d avec rarete · %.1f jours couverts"
          % (s, r[0], r[1] or 0, duree), flush=True)
