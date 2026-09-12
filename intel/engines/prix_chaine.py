"""Le prix lu sur la chaine, des la creation du pool.

RAISON D ETRE. Tout ce que la recherche sait des lancements vient de DexScreener, et deux mesures du
09/09 disent que cette source ne peut pas repondre aux questions qu on lui pose :

  - elle se rafraichit toutes les 30 a 60 s (§3.61), alors que le moteur decide toutes les 20 s. Le
    simulateur bati dessus est deux fois trop pessimiste : sur les memes tickets il annonce
    -0,564/euro la ou le carnet reel encaisse -0,302 ;
  - elle n indexe pas les pools avant ~T+1,5 min. Sur 74 creations vues par le flux en une heure,
    6 seulement y figuraient. Le premier releve des 530 courbes collectees tombe a T+1,28 min au
    plus tot. LA ZONE T+0 A T+1,5 MIN N A DONC JAMAIS ETE OBSERVEE -- et c est precisement celle ou
    agit l argent informe : createur, bundlers, snipers du premier bloc.

Ce module lit le prix a la source : les reserves du pool, dans l etat de la chaine. Pas d
agregateur, pas de retard, cadence libre.

COMMENT. Le flux ecoute les migrations et ecrit le mint dans `solana_stream_launches`. Pour chaque
mint recent :

  1. on resout le pool en UN appel -- `getProgramAccounts` sur le programme PumpSwap, filtre sur la
     taille (301 octets) et sur le mint de base a l offset 43 ; le resultat est mis en cache, la
     resolution ne se fait qu une fois par lancement ;
  2. on lit les deux comptes de reserve en lot (`getMultipleAccounts`, jusqu a 100 par appel) ;
  3. le prix est le rapport des reserves. Valide le 09/09 contre DexScreener sur cinq pools :
     ecarts de -2,4 % a +4,2 %, dans le sens et l ordre de grandeur attendus de son retard.

COUT. Une resolution par lancement (~74/h) et un appel groupe par cycle pour tous les pools suivis.
Sans commune mesure avec la boucle a 5 s qui avait provoque des 429 bloquant les ventes (§3.55) : ce
sont des appels RPC indexes, pas des cotations de routeur, et le chemin de vente n en depend pas.

CE MODULE N ACHETE RIEN, NE VEND RIEN, NE SIGNE RIEN. Il ecrit dans `solana_prix_chaine`.
"""
from __future__ import annotations

import base64
import logging
from typing import Any

import base58

log = logging.getLogger(__name__)

PAMM = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
TAILLE_POOL = 301
OFF_BASE_MINT = 43            # 8 discriminant + 1 bump + 2 index + 32 createur
OFF_BASE_TA = 43 + 32 * 3     # + base_mint + quote_mint + lp_mint


class PrixChaine:
    """Suit le prix des lancements recents en lisant les reserves des pools."""

    def __init__(self, ctx, client) -> None:
        self.ctx, self.client = ctx, client
        self.pools: dict[str, tuple[str, str, str]] = {}     # mint -> (pool, base_ta, quote_ta)
        self.introuvables: dict[str, int] = {}               # mint -> nombre de tentatives

    def _cfg(self, cle: str, defaut):
        return self.ctx.config.get("solana.prix_chaine." + cle, defaut)

    def _url(self) -> str | None:
        from intel.execution import solana as sol
        return sol.rpc_url()

    async def _rpc(self, methode: str, params: list) -> Any:
        rpc = self._url()
        if not rpc:
            return None
        try:
            r = await self.client.post(rpc, json={"jsonrpc": "2.0", "id": 1,
                                                  "method": methode, "params": params}, timeout=30)
            return (r.json() or {}).get("result")
        except Exception:  # noqa: BLE001
            return None

    async def _depuis_migration(self, mint: str, signature: str) -> tuple[str, str, str] | None:
        """Le pool et ses deux reserves, lus DANS la transaction de migration.

        C est le chemin principal depuis le 12/09. Chercher le pool par `getProgramAccounts` oblige
        a attendre que l index du fournisseur rattrape la chaine, et cette attente coutait du flux :
        audit du meme jour, 10 lancements sur 153 n avaient jamais ete juges, et leurs 10 pools
        EXISTAIENT -- simplement indexes apres la fermeture de la fenetre d entree. Or la
        transaction de migration, qu on recoit deja et dont on garde la signature, contient tout :

            postTokenBalances  ->  l entree de NOTRE mint avec un solde non nul
                                   son `owner` EST le pool
                                   son compte est la reserve en jetons
                               ->  l entree WSOL du meme `owner` est la reserve en SOL

        Une lecture, zero attente. L ancienne recherche reste en secours quand la signature manque
        ou que la transaction n est pas encore servie par le noeud.

        Le solde non nul est la condition qui distingue : la migration laisse aussi une entree a
        zero pour l ancienne courbe de bonding, avec un autre proprietaire.
        """
        from intel.execution.solana import SOL_MINT
        res = await self._rpc("getTransaction",
                              [signature, {"maxSupportedTransactionVersion": 0,
                                           "encoding": "jsonParsed"}])
        if not res:
            return None
        try:
            meta = res.get("meta") or {}
            if meta.get("err"):
                return None
            keys = [k["pubkey"] if isinstance(k, dict) else k
                    for k in res["transaction"]["message"]["accountKeys"]]
            soldes = meta.get("postTokenBalances") or []
            pool = base_ta = quote_ta = None
            for b in soldes:
                if b.get("mint") != mint:
                    continue
                if float(b["uiTokenAmount"]["uiAmountString"] or 0) <= 0:
                    continue
                pool, base_ta = b.get("owner"), keys[int(b["accountIndex"])]
            if not pool or not base_ta:
                return None
            for b in soldes:
                if b.get("mint") == SOL_MINT and b.get("owner") == pool:
                    quote_ta = keys[int(b["accountIndex"])]
            if not quote_ta:
                return None
        except Exception:  # noqa: BLE001
            return None
        return pool, base_ta, quote_ta

    async def _resoudre(self, mint: str, signature: str | None = None) -> tuple[str, str, str] | None:
        """Le pool PumpSwap d un jeton et ses deux comptes de reserve. Un seul appel, mis en cache.

        Un pool absent ne l est pas forcement pour toujours : la migration vient d etre emise et le
        compte peut n etre visible qu au bloc suivant. On retente donc quelques fois avant
        d abandonner, sinon on perdrait justement les premieres secondes qu on cherche a observer.
        """
        if mint in self.pools:
            return self.pools[mint]
        if self.introuvables.get(mint, 0) >= int(self._cfg("tentatives", 6) or 6):
            return None
        # D abord la transaction de migration : elle porte le pool, sans attendre aucun index.
        if signature:
            trouve = await self._depuis_migration(mint, signature)
            if trouve:
                self.introuvables.pop(mint, None)
                self.pools[mint] = trouve
                return trouve
        res = await self._rpc("getProgramAccounts", [PAMM, {
            "encoding": "base64",
            "filters": [{"dataSize": TAILLE_POOL},
                        {"memcmp": {"offset": OFF_BASE_MINT, "bytes": mint}}]}])
        if not res:
            self.introuvables[mint] = self.introuvables.get(mint, 0) + 1
            return None
        try:
            d = base64.b64decode(res[0]["account"]["data"][0])
            base_ta = base58.b58encode(d[OFF_BASE_TA:OFF_BASE_TA + 32]).decode()
            quote_ta = base58.b58encode(d[OFF_BASE_TA + 32:OFF_BASE_TA + 64]).decode()
        except Exception:  # noqa: BLE001
            self.introuvables[mint] = 99
            return None
        self.pools.pop(mint, None)
        self.introuvables.pop(mint, None)
        self.pools[mint] = (res[0]["pubkey"], base_ta, quote_ta)
        return self.pools[mint]

    async def cycle(self) -> dict[str, Any]:
        from intel.utils.timeutil import now_ts

        db = self.ctx.db
        db.execute("CREATE TABLE IF NOT EXISTS solana_prix_chaine("
                   "  pair_id TEXT NOT NULL, mint TEXT, ts INTEGER NOT NULL, age_s INTEGER,"
                   "  prix_sol REAL, reserve_base REAL, reserve_sol REAL,"
                   "  PRIMARY KEY (pair_id, ts))")
        fenetre = int(self._cfg("fenetre_minutes", 15) or 15)
        now = now_ts()
        lancements = db.query(
            "SELECT mint, ts, signature FROM solana_stream_launches WHERE ts > ? ORDER BY ts DESC LIMIT 40",
            (now - fenetre * 60,))
        if not lancements:
            return {"status": "ok", "suivis": 0}

        comptes: list[str] = []
        plan: list[tuple[str, str, int]] = []      # (pool, mint, ts de creation)
        for l in lancements:
            m = l["mint"]
            if not m:
                continue
            trouve = await self._resoudre(m, l["signature"] if "signature" in l.keys() else None)
            if not trouve:
                continue
            pool, base_ta, quote_ta = trouve
            plan.append((pool, m, int(l["ts"])))
            comptes += [base_ta, quote_ta]
        if not plan:
            return {"status": "ok", "suivis": 0, "resolus": 0}

        ecrits = 0
        for i in range(0, len(comptes), 100):
            lot = comptes[i:i + 100]
            res = await self._rpc("getMultipleAccounts", [lot, {"encoding": "jsonParsed"}])
            vals = (res or {}).get("value") or []
            for j in range(0, len(lot) - 1, 2):
                k = (i + j) // 2
                if k >= len(plan) or j + 1 >= len(vals) or not vals[j] or not vals[j + 1]:
                    continue
                pool, mint, cree = plan[k]
                try:
                    b = float(vals[j]["data"]["parsed"]["info"]["tokenAmount"]["uiAmountString"])
                    q = float(vals[j + 1]["data"]["parsed"]["info"]["tokenAmount"]["uiAmountString"])
                except Exception:  # noqa: BLE001
                    continue
                if b <= 0:
                    continue
                try:
                    db.execute(
                        "INSERT OR IGNORE INTO solana_prix_chaine"
                        "(pair_id, mint, ts, age_s, prix_sol, reserve_base, reserve_sol)"
                        " VALUES(?,?,?,?,?,?,?)",
                        (pool, mint, now, now - cree, q / b, b, q))
                    ecrits += 1
                except Exception:  # noqa: BLE001
                    pass
        return {"status": "ok", "suivis": len(plan), "ecrits": ecrits,
                "pools": len(self.pools), "non_resolus": len(self.introuvables)}
