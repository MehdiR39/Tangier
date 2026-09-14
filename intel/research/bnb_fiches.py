"""Recuperer les liens sociaux des jetons BNB dont on possede un historique de prix horodate.

Les 54 228 relevés du 13/09 portent des prix horodates PAR NOUS -- donc propres -- mais leurs
colonnes sociales sont a zero, la source d alors (DexScreener) ne portant pas l information. On va
chercher ces liens chez four.meme et on les range a part, dans `bnb_social`.

LIMITE A DECLARER : ces liens sont lus AUJOURD HUI pour des jetons nes hier. four.meme les garde
dans sa base et le createur peut les ajouter apres coup, donc une part d entre eux peut etre
posterieure au moment ou l on aurait decide. L ampleur est mesuree : 40,0 % de Telegram sur les
jetons de 8 a 24 h contre 44,4 % au-dela de 24 h, soit environ 4 points de derive par jour. Ce
n est donc pas nul, et tout resultat positif devra etre reconfirme sur la collecte horodatee en
cours avant d etre cru.
"""
import sqlite3, json, time, urllib.request, sys

def fiche(adresse):
    url = "https://four.meme/meme-api/v1/private/token/get?address=" + adresse
    req = urllib.request.Request(url, headers={"user-agent": "Mozilla/5.0",
                                               "accept": "application/json"})
    for _ in range(3):
        try:
            with urllib.request.urlopen(req, timeout=15) as x:
                j = json.loads(x.read()) or {}
                if j.get("code") != 0:
                    return None
                d = j.get("data")
                return d if isinstance(d, dict) else None
        except Exception:
            time.sleep(0.8)
    return None

c = sqlite3.connect("/app/db/intel.sqlite")
c.execute("CREATE TABLE IF NOT EXISTS bnb_social("
          "  jeton TEXT PRIMARY KEY, telegram INTEGER, twitter INTEGER, site INTEGER,"
          "  createur TEXT, cap REAL, lu_le INTEGER)")
c.commit()
deja = {r[0] for r in c.execute("SELECT jeton FROM bnb_social")}
cibles = [r[0] for r in c.execute(
    "SELECT jeton FROM bnb_releves WHERE prix_usd IS NOT NULL"
    " GROUP BY jeton HAVING COUNT(*) >= 2") if r[0] not in deja]
print("  %d jetons a documenter (%d deja)" % (len(cibles), len(deja)), flush=True)
now = int(time.time())
ok = tg = 0
for i, a in enumerate(cibles):
    d = fiche(a)
    if d is None:
        continue
    cap = None
    try:
        cap = float(((d.get("tokenPrice") or {}).get("marketCap")) or 0) or None
    except Exception:
        pass
    c.execute("INSERT OR REPLACE INTO bnb_social VALUES(?,?,?,?,?,?,?)",
              (a, int(bool(d.get("telegramUrl"))), int(bool(d.get("twitterUrl"))),
               int(bool(d.get("webUrl"))), d.get("userAddress"), cap, now))
    ok += 1
    tg += 1 if d.get("telegramUrl") else 0
    if ok % 150 == 0:
        c.commit(); print("    %d / %d lus · %d Telegram" % (ok, len(cibles), tg), flush=True)
c.commit()
r = c.execute("SELECT COUNT(*) n, SUM(telegram) tg, SUM(twitter) tw, SUM(site) st FROM bnb_social").fetchone()
print()
print("  %d fiches · Telegram %d (%.1f %%) · twitter %d (%.1f %%) · site %d (%.1f %%)"
      % (r[0], r[1], 100*r[1]/r[0], r[2], 100*r[2]/r[0], r[3], 100*r[3]/r[0]))
