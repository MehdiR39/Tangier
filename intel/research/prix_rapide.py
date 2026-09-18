"""COLLECTE DU PRIX A 1 SECONDE, sur la fenetre ou la position est tenue (35-310 s).

POURQUOI. Le moteur voit vite et mesure lentement. `veille_rapide` lit les reserves du pool
TOUTES LES SECONDES depuis le 17/09 pour declencher `take_profit_multiple: 1.5` et
`stop_loss_multiple: 0.7` -- mais il ne garde rien : un `UPDATE positions SET peak_price`, et la
lecture est perdue. Le seul historique de prix qui existe est celui du collecteur d ARCHIVE
(`solana_prix_chaine`), a 10 s : mediane 10,0 s et p90 11 s TOUS LES JOURS depuis le 09/09, dans
les deux bases. Aucune autre source ne descend en dessous : `solana_suivi` est du DexScreener,
`trades` et `swap_events` sont de l EVM arrete le 17/09 a 14 h, `pump_prix` suit la courbe et non
le pool.

CONSEQUENCE, ET C EST LA RAISON D ETRE DE CE FICHIER. Tout ce qui a ete mesure dans ce projet
decrit un bot a SORTIE FIXE (287 s) observant a 10 s. Le moteur reel sort sur SEUILS a 1 s. Ce ne
sont pas les memes machines, et l ecart est mesure : §3.95, meme regle, memes 3 245 pools, seule la
cadence d observation change -- chaque transaction +5,23 %, 2 s +5,48 %, 5 s +4,12 %, 10 s +1,69 %.
Un facteur 3 sur la meme regle. Toute conclusion sur un STOP ou une PRISE DE GAIN batie sur du 10 s
est donc non concluante, y compris la mienne du 18/09 (§3.113), dont j ai retire la force.

CE QU IL COUTE. Mesure avant d ecrire : 3 pools simultanement dans la fenetre en mediane, 13 au
pire. Les reserves se lisent en LOT (`getMultipleAccounts`, jusqu a 100 comptes), donc c est UN
appel par seconde quel que soit le nombre de pools -- le collecteur d archive en fait deja ~1/s.
`commitment: processed` : sans lui le noeud repond en « finalized », 31 slots soit 12,4 s de retard
horodates comme frais (§3.83) -- ce qui detruirait exactement ce qu on vient chercher.

CE QU IL NE FAIT PAS. Il n achete rien, ne vend rien, ne signe rien. Il LIT `intel.sqlite` en
lecture seule et n ecrit que dans sa propre base. Si il tombe, il tombe seul : aucun collecteur en
marche, aucun des quatre tests geles, n en depend.
"""
from __future__ import annotations

import base64
import json
import os
import sqlite3
import time
import urllib.request

from intel.engines.prix_chaine import (OFF_BASE_MINT, OFF_BASE_TA, PAMM, TAILLE_POOL,
                                       reserve_virtuelle)

# `base58` n est utilise que pour decoder les adresses des comptes de reserve, dans le resolveur.
# Importe la-bas et non ici, pour que le module reste testable dans un environnement qui ne l a pas.

BASE_MOTEUR = os.environ.get("INTEL_DB", "/app/db/intel.sqlite")
BASE_ICI = os.environ.get("PRIX_RAPIDE_DB", "/app/db/prix_rapide.sqlite")
SOL_MINT = "So11111111111111111111111111111111111111112"

PAS = 1.0                 # la cadence qu on veut mesurer, celle de `veille_rapide`
AGE_MIN, AGE_MAX = 35, 310    # la fenetre tenue : decision a 45-47 s, sortie fixe a 287 s
MAX_POOLS = 45            # plafond dur : 2 comptes par pool, on reste sous les 100 d un seul lot
TENTATIVES = 20           # comme le moteur : un pool peut n etre visible qu au bloc suivant


def rpc(methode: str, params: list, timeout: float = 10.0):
    """Un appel JSON-RPC. Rend None sur toute erreur : une seconde ratee n est pas un incident."""
    url = os.environ["SOLANA_RPC_URL"]
    corps = json.dumps({"jsonrpc": "2.0", "id": 1, "method": methode, "params": params}).encode()
    try:
        r = urllib.request.urlopen(urllib.request.Request(
            url, data=corps, headers={"Content-Type": "application/json"}), timeout=timeout)
        return (json.loads(r.read().decode()) or {}).get("result")
    except Exception:  # noqa: BLE001
        return None


def schema(c: sqlite3.Connection) -> None:
    c.executescript("""
        CREATE TABLE IF NOT EXISTS prix(
            pair TEXT NOT NULL, mint TEXT, ts REAL NOT NULL, age_s REAL,
            prix_sol REAL, reserve_base REAL, reserve_sol REAL, reserve_virtuelle REAL,
            PRIMARY KEY (pair, ts));
        CREATE INDEX IF NOT EXISTS i_prix_pair ON prix(pair, age_s);
        CREATE TABLE IF NOT EXISTS meta(cle TEXT PRIMARY KEY, valeur TEXT);
    """)
    c.commit()


class Resolveur:
    """mint -> (pool, compte de reserve base, compte de reserve SOL). Un appel, mis en cache."""

    def __init__(self) -> None:
        self.pools: dict[str, tuple[str, str, str]] = {}
        self.virtuelles: dict[str, float] = {}
        self.echecs: dict[str, int] = {}

    def __call__(self, mint: str):
        if mint in self.pools:
            return self.pools[mint]
        if self.echecs.get(mint, 0) >= TENTATIVES:
            return None
        res = rpc("getProgramAccounts", [PAMM, {
            "encoding": "base64",
            "filters": [{"dataSize": TAILLE_POOL},
                        {"memcmp": {"offset": OFF_BASE_MINT, "bytes": mint}}]}], timeout=15.0)
        if not res:
            self.echecs[mint] = self.echecs.get(mint, 0) + 1
            return None
        try:
            import base58
            d = base64.b64decode(res[0]["account"]["data"][0])
            pool = res[0]["pubkey"]
            base_ta = base58.b58encode(d[OFF_BASE_TA:OFF_BASE_TA + 32]).decode()
            quote_ta = base58.b58encode(d[OFF_BASE_TA + 32:OFF_BASE_TA + 64]).decode()
        except Exception:  # noqa: BLE001
            self.echecs[mint] = TENTATIVES          # illisible : inutile d insister
            return None
        self.virtuelles[pool] = reserve_virtuelle(d)
        self.pools[mint] = (pool, base_ta, quote_ta)
        self.echecs.pop(mint, None)
        return self.pools[mint]


def a_suivre(moteur: sqlite3.Connection, now: float) -> list[tuple[str, float]]:
    """(mint, instant de creation) des lancements dont l age tombe dans la fenetre tenue."""
    rows = moteur.execute(
        "SELECT mint, ts FROM solana_stream_launches WHERE ts BETWEEN ? AND ? ORDER BY ts DESC",
        (now - AGE_MAX, now - AGE_MIN)).fetchall()
    return [(m, float(t)) for m, t in rows if m][:MAX_POOLS]


def tour(ici: sqlite3.Connection, moteur: sqlite3.Connection, res: Resolveur) -> int:
    now = time.time()
    plan, comptes = [], []
    for mint, cree in a_suivre(moteur, now):
        trouve = res(mint)
        if not trouve:
            continue
        pool, base_ta, quote_ta = trouve
        plan.append((pool, mint, cree))
        comptes += [base_ta, quote_ta]
    if not plan:
        return 0

    ecrits = 0
    for i in range(0, len(comptes), 100):
        lot = comptes[i:i + 100]
        vals = ((rpc("getMultipleAccounts",
                     [lot, {"encoding": "jsonParsed", "commitment": "processed"}]) or {}).get("value")
                or [])
        lu = time.time()
        for j in range(0, len(lot) - 1, 2):
            k = (i + j) // 2
            if k >= len(plan) or j + 1 >= len(vals) or not vals[j] or not vals[j + 1]:
                continue
            pool, mint, cree = plan[k]
            try:
                # Le second compte DOIT etre du WSOL : le 14/09, 36 % des releves annonçaient des
                # pools a plus de 200 SOL parce que ce n en etait pas (§ collecte d archive).
                if vals[j + 1]["data"]["parsed"]["info"].get("mint") != SOL_MINT:
                    continue
                b = float(vals[j]["data"]["parsed"]["info"]["tokenAmount"]["uiAmountString"])
                q = float(vals[j + 1]["data"]["parsed"]["info"]["tokenAmount"]["uiAmountString"])
            except Exception:  # noqa: BLE001
                continue
            if b <= 0:
                continue
            v = float(res.virtuelles.get(pool, 0.0) or 0.0)
            try:
                ici.execute("INSERT OR IGNORE INTO prix(pair, mint, ts, age_s, prix_sol,"
                            " reserve_base, reserve_sol, reserve_virtuelle) VALUES(?,?,?,?,?,?,?,?)",
                            (pool, mint, lu, lu - cree, (q + v) / b, b, q, v))
                ecrits += 1
            except Exception:  # noqa: BLE001
                pass
    ici.commit()
    return ecrits


def main() -> None:
    ici = sqlite3.connect(BASE_ICI, timeout=30)
    schema(ici)
    moteur = sqlite3.connect("file:%s?mode=ro" % BASE_MOTEUR, uri=True, timeout=30)
    res = Resolveur()
    print("prix_rapide: demarre · %.0f s de cadence · fenetre %d-%d s · base %s"
          % (PAS, AGE_MIN, AGE_MAX, BASE_ICI), flush=True)
    dernier_bilan = 0.0
    while True:
        t0 = time.time()
        try:
            tour(ici, moteur, res)
        except Exception as exc:  # noqa: BLE001
            print("prix_rapide: tour rate (%s)" % str(exc)[:160], flush=True)
        if t0 - dernier_bilan >= 300:
            dernier_bilan = t0
            n, p = ici.execute("SELECT COUNT(*), COUNT(DISTINCT pair) FROM prix").fetchone()
            print("prix_rapide: %d lignes · %d pools" % (n, p), flush=True)
        # cadence FIXE : on dort ce qui reste, jamais PAS de plus. Sinon la cadence derive avec le
        # temps de reponse du RPC et on ne mesure plus 1 s.
        time.sleep(max(0.0, PAS - (time.time() - t0)))


if __name__ == "__main__":
    main()
