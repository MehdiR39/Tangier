"""Recuperer les TRAITS de chaque piece vendue, pour calculer la rarete nous-memes.

L API Magic Eden ne donne un rang de rarete que dans les listings, pas dans l historique des
ventes. Mais elle donne les ATTRIBUTS de chaque piece (`/v2/tokens/<mint>`), ce qui permet de
calculer la rarete statistique soi-meme -- et c est preferable : un rang tiers est une boite noire
dont on ignore la formule et la date de calcul.

RARETE STATISTIQUE : pour chaque trait, sa frequence dans la collection observee. La rarete d une
piece est le produit des frequences de ses traits (plus c est petit, plus la piece est rare). On
n utilise que les pieces VENDUES, donc l echantillon est celui qui nous interesse.

On recupere aussi `sellerFeeBasisPoints` : les royalties, qui manquaient au calcul du peage.

N ACHETE RIEN.
"""
import json, sqlite3, time, urllib.request

B = "https://api-mainnet.magiceden.dev/v2/tokens/"
COLS = ["claynosaurz", "smb_gen3", "mad_lads"]     # 2 non pricees + 1 temoin pricee

def g(url, essais=3):
    for i in range(essais):
        try:
            req = urllib.request.Request(url, headers={"user-agent": "Mozilla/5.0",
                                                       "accept": "application/json"})
            with urllib.request.urlopen(req, timeout=25) as x:
                return json.loads(x.read())
        except Exception as e:
            time.sleep(4 if "429" in str(e) else 1.5)
    return None

c = sqlite3.connect("/app/db/intel.sqlite")
c.execute("CREATE TABLE IF NOT EXISTS nft_traits("
          "  mint TEXT PRIMARY KEY, collection TEXT, traits TEXT, royalties INTEGER)")
c.commit()
deja = {r[0] for r in c.execute("SELECT mint FROM nft_traits")}

for s in COLS:
    mints = [r[0] for r in c.execute(
        "SELECT DISTINCT mint FROM nft_ventes WHERE collection=? AND mint IS NOT NULL", (s,))
        if r[0] not in deja]
    print("  %s : %d pieces a documenter" % (s, len(mints)), flush=True)
    ok = 0
    for i, m in enumerate(mints):
        d = g(B + m)
        if not isinstance(d, dict):
            continue
        attrs = d.get("attributes")
        if not isinstance(attrs, list) or not attrs:
            continue
        try:
            c.execute("INSERT OR REPLACE INTO nft_traits VALUES(?,?,?,?)",
                      (m, s, json.dumps(attrs), d.get("sellerFeeBasisPoints")))
            ok += 1
        except Exception:
            pass
        if ok % 100 == 0 and ok:
            c.commit()
            print("    %s : %d / %d" % (s, i + 1, len(mints)), flush=True)
        time.sleep(0.55)
    c.commit()
    n = c.execute("SELECT COUNT(*) FROM nft_traits WHERE collection=?", (s,)).fetchone()[0]
    roy = c.execute("SELECT royalties FROM nft_traits WHERE collection=? AND royalties IS NOT NULL"
                    " LIMIT 1", (s,)).fetchone()
    print("  %-22s %d pieces documentees · royalties %s"
          % (s, n, ("%.1f %%" % (roy[0]/100)) if roy else "?"), flush=True)
print()
print("  COLLECTE DES TRAITS TERMINEE")
