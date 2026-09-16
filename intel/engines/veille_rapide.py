"""Veille RAPIDE des positions ouvertes : le prix lu dans le pool toutes les 2 s, zero cotation.

POURQUOI (journal §3.95). Mesure appariee sur 3 245 pools -- memes pools, meme regle de sortie, seule
la cadence d observation change : voir le marche toutes les 2 s au lieu de toutes les 20 s vaut
**+1,14 point par ticket [+0,27 ; +2,04]**, et **+2,64 pts [+0,50 ; +4,65]** sur les pools a coffre
< 100 SOL. Rejouee en deux moities : +1,27 puis +1,02 ; les SEPT jours de la periode sont positifs.
La cause est simple : 29 % des pools touchent +25 % entre 47 et 287 s, declenchement median a 93 s ;
a 20 s de cadence on rate le sommet une fois sur deux.

POURQUOI PAS SIMPLEMENT `book_poll_seconds: 2`. On l a deja essaye le 11/09 (§3.55) et ca a coute de
l argent : `run_carnet` demande au ROUTEUR ce que chaque position vaut (`_worth` -> `prepare_sell`),
donc passer a 5 s avait multiplie par quatre les cotations Jupiter, sature le quota gratuit et
**bloque les ventes** -- USELESSLAPTOP, montee a x1,53, a essuye vingt-six refus consecutifs. Un stop
plus reactif qui empeche de vendre est pire que pas de stop du tout.

CE QUE FAIT CETTE BOUCLE, ET CE QU ELLE NE FAIT PAS. Elle lit le prix la ou il est vraiment : dans les
deux comptes de reserve du pool, avec la reserve virtuelle (§3.83), par notre propre RPC. Aucune
cotation, aucune signature, AUCUNE VENTE. Quand un seuil est franchi elle se contente de REVEILLER
`run_carnet`, qui garde toute la decision : cotation du routeur, verification du solde, garde-fous,
verrou anti-double-vente. Le pire cas de charge Jupiter est donc exactement celui d aujourd hui
(`reveil_min_secondes` interdit de reveiller la meme position plus souvent que la cadence actuelle du
carnet), et le meilleur cas est une reaction en 2 s au lieu de 20.

COUT. Une seule lecture `getMultipleAccounts` par passage, et uniquement quand une position est
ouverte : ~120 lectures par ticket, ~4 800 par jour a 40 tickets. Rien a l echelle de notre quota.
"""
from __future__ import annotations

import base64
import logging
from typing import Any

import base58

from intel.engines.prix_chaine import OFF_BASE_TA, TAILLE_POOL, reserve_virtuelle
from intel.utils.timeutil import now_ts

log = logging.getLogger(__name__)


class VeilleRapide:
    """Surveille le prix des positions ouvertes et reveille le carnet quand un seuil est franchi."""

    def __init__(self, ctx, watcher) -> None:
        self.ctx, self.watcher = ctx, watcher
        self.comptes: dict[str, tuple[str, str, float]] = {}   # pool -> (base_ta, quote_ta, virtuelle)
        self.refs: dict[int, float] = {}                       # position -> prix d entree en SOL
        self.reveils: dict[int, int] = {}                      # position -> dernier reveil (ts)
        self.illisibles: dict[str, int] = {}                   # pool -> echecs de resolution

    def _cfg(self, cle: str, defaut):
        return self.ctx.config.get("solana.veille_rapide." + cle, defaut)

    async def _rpc(self, methode: str, params: list) -> Any:
        from intel.execution import solana as sol
        rpc = sol.rpc_url()
        if not rpc:
            return None
        try:
            r = await self.watcher.client.post(
                rpc, json={"jsonrpc": "2.0", "id": 1, "method": methode, "params": params}, timeout=15)
            return (r.json() or {}).get("result")
        except Exception:  # noqa: BLE001
            return None

    async def _resoudre(self, pool: str) -> tuple[str, str, float] | None:
        """Les deux comptes de reserve du pool et sa reserve virtuelle, lus une fois puis gardes."""
        if pool in self.comptes:
            return self.comptes[pool]
        if self.illisibles.get(pool, 0) >= 3:
            return None
        res = await self._rpc("getAccountInfo", [pool, {"encoding": "base64", "commitment": "processed"}])
        data = ((res or {}).get("value") or {}).get("data")
        if not data:
            self.illisibles[pool] = self.illisibles.get(pool, 0) + 1
            return None
        try:
            d = base64.b64decode(data[0])
            if len(d) < TAILLE_POOL:
                raise ValueError("taille %d" % len(d))
            base_ta = base58.b58encode(d[OFF_BASE_TA:OFF_BASE_TA + 32]).decode()
            quote_ta = base58.b58encode(d[OFF_BASE_TA + 32:OFF_BASE_TA + 64]).decode()
        except Exception:  # noqa: BLE001
            self.illisibles[pool] = 99
            return None
        self.comptes[pool] = (base_ta, quote_ta, reserve_virtuelle(d))
        return self.comptes[pool]

    def _prix_entree(self, pos_id: int, pool: str, ouvert: int) -> float | None:
        """Le prix d entree EN SOL, repris de la serie deja collectee par `prix_chaine`.

        `positions.entry_price` est en dollars (il vient du flux DexScreener) : le comparer a un prix
        lu dans le pool melangerait deux unites. La serie `solana_prix_chaine` porte le meme prix, dans
        la meme unite, pour le meme pool -- on y prend la lecture la plus proche de l ouverture.
        """
        if pos_id in self.refs:
            return self.refs[pos_id]
        try:
            r = self.ctx.db.query(
                "SELECT prix_sol FROM solana_prix_chaine WHERE pair_id=? AND prix_sol>0"
                " ORDER BY ABS(ts - ?) LIMIT 1", (pool, int(ouvert)))
        except Exception:  # noqa: BLE001
            return None
        if r and r[0]["prix_sol"]:
            self.refs[pos_id] = float(r[0]["prix_sol"])
            return self.refs[pos_id]
        return None

    async def cycle(self) -> dict[str, Any]:
        if not self._cfg("enabled", True) or not self.ctx.config.get("solana.enabled", False):
            return {"status": "disabled"}
        from intel.engines.solana_watcher import MODEL_VERSION

        db = self.ctx.db
        try:
            ouvertes = db.query(
                "SELECT id, label, notes, opened_ts, entry_price, peak_price FROM positions"
                " WHERE chain_id=? AND model_version=? AND status='OPEN'",
                (self.ctx.chain_id, MODEL_VERSION))
        except Exception:  # noqa: BLE001
            return {"status": "base indisponible"}
        if not ouvertes:
            self.refs.clear()
            self.reveils.clear()
            return {"status": "ok", "positions": 0}          # aucune lecture : la veille ne coute rien

        plan, comptes = [], []
        for p in ouvertes:
            champs = dict(kv.split(":", 1) for kv in (p["notes"] or "").split() if ":" in kv)
            pool = champs.get("pool")
            if not pool or pool == "None":
                continue
            trouve = await self._resoudre(pool)
            if not trouve:
                continue
            base_ta, quote_ta, v = trouve
            ref = self._prix_entree(int(p["id"]), pool, int(p["opened_ts"] or 0))
            if not ref:
                continue
            plan.append((p, ref, v))
            comptes += [base_ta, quote_ta]
        if not plan:
            return {"status": "ok", "positions": len(ouvertes), "suivies": 0}

        res = await self._rpc("getMultipleAccounts",
                              [comptes, {"encoding": "jsonParsed", "commitment": "processed"}])
        vals = (res or {}).get("value") or []
        tp = float(self.watcher._cfg("take_profit_multiple", 2.0))
        stop = float(self.watcher._cfg("stop_loss_multiple", 0) or 0)
        mini = int(self._cfg("reveil_min_secondes", 20) or 20)
        now = now_ts()
        franchis, lues = [], 0
        for k, (p, ref, v) in enumerate(plan):
            j = 2 * k
            if j + 1 >= len(vals) or not vals[j] or not vals[j + 1]:
                continue
            try:
                from intel.execution.solana import SOL_MINT
                if vals[j + 1]["data"]["parsed"]["info"].get("mint") != SOL_MINT:
                    continue                                  # le second compte n est pas du SOL (§3.82)
                b = float(vals[j]["data"]["parsed"]["info"]["tokenAmount"]["uiAmountString"])
                q = float(vals[j + 1]["data"]["parsed"]["info"]["tokenAmount"]["uiAmountString"])
            except Exception:  # noqa: BLE001
                continue
            if b <= 0:
                continue
            lues += 1
            mult = ((q + v) / b) / ref
            # Le sommet traverse, dans l unite de `positions.peak_price` (dollars, comme l entree).
            if p["entry_price"]:
                sommet = float(p["entry_price"]) * mult
                if p["peak_price"] is None or sommet > float(p["peak_price"]):
                    try:
                        db.execute("UPDATE positions SET peak_price=? WHERE id=?", (sommet, p["id"]))
                    except Exception:  # noqa: BLE001
                        pass
            if not (mult >= tp or (stop > 0 and mult <= stop)):
                continue
            # Un seuil franchi ne vend pas : il reveille le carnet, qui decide sur la cotation du
            # routeur. Et jamais plus souvent que la cadence actuelle du carnet, sinon on refait le
            # 429 du 11/09 : si le routeur n est pas d accord avec le pool, on re-cote en boucle.
            if now - self.reveils.get(int(p["id"]), 0) < mini:
                continue
            self.reveils[int(p["id"])] = now
            franchis.append((p["label"], mult))
        if not franchis:
            return {"status": "ok", "positions": len(ouvertes), "suivies": lues}
        for label, mult in franchis:
            log.info("veille: %s a x%.2f dans le pool · reveil du carnet", label, mult)
        await self.watcher.run_carnet()
        return {"status": "ok", "positions": len(ouvertes), "suivies": lues, "reveils": len(franchis)}
