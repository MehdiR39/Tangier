"""Ecoute les creations de pool sur la chaine, en direct, et les depose pour le carnet Solana.

La decouverte actuelle lit deux flux PROMOTIONNELS de DexScreener -- des jetons dont le createur a
paye une fiche ou une mise en avant. Mesure du 08/09/2026 : 4,3 lancements PumpSwap par heure y
apparaissent dans la fenetre achetable, alors que la chaine en gradue environ 20. On en rate donc
plus des trois quarts, et le rythme est ce qui empeche de savoir si la strategie gagne.

Ce module ouvre une connexion SORTANTE vers `transactionSubscribe` (plan Developpeur Helius) et
retient les transactions de migration : le moment exact ou un jeton graduee cree son pool. Il
n achete rien, ne signe rien, et n appelle pas le carnet. Il ecrit dans `solana_stream_launches`,
que la decouverte va lire en plus de DexScreener.

Deux precautions delibereees :

  - **Les deux sources restent separees.** Chaque jeton porte sa provenance, pour qu on puisse
    mesurer ce que le flux apporte vraiment. Remplacer DexScreener d un coup rendrait impossible de
    savoir si une amelioration vient du flux ou du hasard.
  - **Le volume est surveille.** La facturation est au volume : 2 credits par 0,1 Mo, 10 millions
    de credits par mois, soit 500 Go. Mesure du 08/09 : PumpSwap entier vaut 448 M de credits par
    mois (exclu), pump.fun entier 45,6 M (trop cher), leur croisement 0,6 M mais ne porte aucun
    lancement. Le compteur ci-dessous coupe la connexion avant de bruler le forfait.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any

from intel.context import IntelContext
from intel.utils.timeutil import now_ts

log = logging.getLogger(__name__)

WS_HOST = "wss://atlas-mainnet.helius-rpc.com"
SOL_MINT = "So11111111111111111111111111111111111111112"
CREDITS_PAR_MO = 20.0


class SolanaStream:
    """Une connexion, un filtre, une table. Rien d autre."""

    def __init__(self, ctx: IntelContext) -> None:
        self.ctx = ctx
        self.octets = 0
        self.recus = 0
        self.deposes = 0
        self.depuis = now_ts()

    def _cfg(self, key: str, default: Any) -> Any:
        return self.ctx.config.get(f"solana.stream.{key}", default)

    def _table(self) -> None:
        self.ctx.db.execute(
            "CREATE TABLE IF NOT EXISTS solana_stream_launches("
            "  mint TEXT PRIMARY KEY, ts INTEGER NOT NULL, signature TEXT,"
            "  instruction TEXT, source TEXT DEFAULT 'stream', vu_par_dexscreener INTEGER DEFAULT 0)")

    def _cle(self) -> str:
        from intel.execution import solana as sol
        u = sol.rpc_url() or os.environ.get("SOLANA_RPC_URL", "")
        return u.split("api-key=")[-1].strip() if "api-key=" in u else ""

    # ------------------------------------------------------------------ flux
    async def run_cycle(self) -> dict[str, Any]:
        """Ouvre la connexion et ecoute pendant une tranche, puis rend la main.

        Ecouter par tranches plutot qu en continu n est pas qu une precaution de quota : ca permet
        aussi de couper net si le filtre se revele trop large, sans avoir a tuer le moteur.
        """
        if not self._cfg("enabled", False):
            return {"status": "disabled"}
        comptes = list(self._cfg("accounts", []) or [])
        if not comptes:
            return {"status": "disabled", "reason": "solana.stream.accounts vide"}
        cle = self._cle()
        if not cle:
            return {"status": "disabled", "reason": "aucune cle Helius"}
        try:
            import websockets
        except ImportError:
            log.warning("solana stream: bibliotheque websockets absente")
            return {"status": "skipped", "reason": "websockets absent"}

        self._table()
        duree = int(self._cfg("seconds_per_cycle", 60))
        plafond_mo = float(self._cfg("max_mb_per_cycle", 30.0))
        sub = {"jsonrpc": "2.0", "id": 1, "method": "transactionSubscribe",
               "params": [{"failed": False, "accountRequired": comptes},
                          {"commitment": "confirmed", "encoding": "jsonParsed",
                           "transactionDetails": "full", "maxSupportedTransactionVersion": 0}]}
        vus = 0
        octets = 0
        nouveaux = 0
        try:
            async with websockets.connect(f"{WS_HOST}/?api-key={cle}", open_timeout=25,
                                          max_size=30_000_000) as ws:
                await ws.send(json.dumps(sub))
                rep = json.loads(await asyncio.wait_for(ws.recv(), timeout=25))
                if "error" in rep:
                    log.warning("solana stream refuse : %s", str(rep["error"])[:140])
                    return {"status": "error", "error": str(rep["error"])[:200]}
                fin = time.time() + duree
                while time.time() < fin:
                    reste = fin - time.time()
                    if reste <= 0:
                        break
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=reste)
                    except asyncio.TimeoutError:
                        break
                    octets += len(msg)
                    vus += 1
                    if octets / 1024 / 1024 > plafond_mo:
                        log.warning("solana stream: %.0f Mo en %d s, au-dela du plafond de %.0f Mo "
                                    "-- filtre trop large, coupure", octets / 1024 / 1024,
                                    duree, plafond_mo)
                        break
                    nouveaux += self._retiens(msg)
        except Exception as exc:  # noqa: BLE001
            log.info("solana stream: connexion interrompue (%s)", str(exc)[:100])
            return {"status": "skipped", "error": str(exc)[:160]}

        self.octets += octets
        self.recus += vus
        self.deposes += nouveaux
        mo = octets / 1024 / 1024
        # Extrapolation honnete du cout si l on ecoutait en continu a ce debit.
        credits_mois = mo * (86400 * 30 / max(duree, 1)) * CREDITS_PAR_MO
        return {"status": "ok", "vus": vus, "nouveaux": nouveaux, "mo": round(mo, 2),
                "credits_mois_si_continu": int(credits_mois)}

    # --------------------------------------------------------------- extraction
    def _retiens(self, msg: str) -> int:
        """Garde le jeton qu une migration fait passer sur PumpSwap.

        Premiere version fausse : elle cherchait un mint present APRES et absent AVANT, en croyant
        qu une migration cree un jeton. Elle n en cree pas -- le jeton vit deja sur sa courbe de
        bonding depuis son lancement, c est le POOL qui est neuf. Quatre migrations sont passees
        sans rien deposer avant que ca se voie.

        On prend donc, sur une transaction portant une instruction de migration, tous les jetons
        qu elle manipule hors SOL. La table a une cle primaire sur le mint, donc un jeton deja
        connu ne peut pas etre depose deux fois.
        """
        try:
            d = json.loads(msg)
        except Exception:  # noqa: BLE001
            return 0
        res = (d.get("params") or {}).get("result") or {}
        tx = res.get("transaction") or {}
        meta = tx.get("meta") or {}
        noms = [l.split("Instruction:")[-1].strip()
                for l in (meta.get("logMessages") or []) if "Instruction:" in l]
        motifs = tuple(self._cfg("instructions", ["Migrate", "CreatePool", "Initialize2"]) or [])
        if motifs and not any(any(m in x for m in motifs) for x in noms):
            return 0
        vus = {b.get("mint") for b in (meta.get("preTokenBalances") or [])}
        vus |= {b.get("mint") for b in (meta.get("postTokenBalances") or [])}
        sig = str(res.get("signature") or "")
        instr = next((x for x in noms if any(m in x for m in motifs)), noms[0] if noms else "?")
        n = 0
        for mint in vus:
            if not mint or mint == SOL_MINT:
                continue
            try:
                self.ctx.db.execute(
                    "INSERT OR IGNORE INTO solana_stream_launches(mint, ts, signature, instruction) "
                    "VALUES(?,?,?,?)", (mint, now_ts(), sig, instr[:40]))
                n += 1
            except Exception as exc:  # noqa: BLE001
                log.info("solana stream: depot refuse (%s)", str(exc)[:80])
        if n:
            log.info("solana stream: %d lancement(s) deposes via %s", n, instr[:24])
        return n
