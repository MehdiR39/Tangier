"""La phase AVANT graduation : 30 600 jetons crees par jour, dont 1 100 graduent. N ACHETE RIEN.

POURQUOI. Depuis le 12/09 nous ne touchons que les DIPLOMES -- les jetons qui ont fini leur courbe
de bonding et ouvert un pool PumpSwap. Ils sont 1 100 par jour. Or pump.fun en cree **30 600 par
jour** (mesure du 13/09 sur 120 blocs), soit vingt-huit fois plus.

Et surtout, c est la que l effet publie s applique DANS LE BON SENS. Kamat 2026 mesure sur 832 941
lancements que la presence d un canal Telegram multiplie par 8,94 le taux de GRADUATION (1,485 %
contre 0,166 %). Nous, nous n observons que des diplomes : nous mesurons ce qui se passe APRES la
graduation, jamais la graduation elle-meme. C est pour cela que le signal social nous apparaissait
d abord a l envers (S3.72).

LA PREMIERE MESURE, et elle ne demande aucun suivi de prix. On sait deja que **6,5 % des jetons qui
graduent portent un Telegram**. Il suffit de savoir quelle part des jetons CREES en portent un :

    part chez les crees  ->  6,5 % / part  =  le multiplicateur de graduation

Sondage du 13/09 sur 45 creations : 2,2 % (1 sur 45), donc un multiplicateur de 2,9. Le chiffre va
dans le sens du papier mais un jeton sur quarante-cinq ne prouve rien. Ce module collecte en continu
pour le rendre solide, puis pour lier chaque creation a sa graduation eventuelle -- les graduations,
elles, sont deja captees a 100 % dans `solana_stream_launches`.

COMMENT. pump.fun emet une instruction `Create` par lancement. Les journaux de la transaction la
nomment, et le nouveau mint est le seul compte dont l adresse finit par `pump`. On lit ensuite sa
metadonnee, gelee a la creation comme pour les diplomes.

CE MODULE N ACHETE RIEN, NE VEND RIEN, NE SIGNE RIEN. Il ecrit dans `pump_creations`.

IL SUIT AUSSI LE PRIX SUR LA COURBE, pour l echantillon dont il a lu la metadonnee. La courbe est
un compte derive du mint et son etat porte les reserves virtuelles : prix = SOL virtuel divise par
jetons virtuels. Cent comptes par appel, donc suivre cinquante jetons en parallele ne coute rien.

UNE PROPRIETE QUI CHANGE TOUT par rapport aux diplomes : sur la courbe la liquidite est
ALGORITHMIQUE. On peut toujours ressortir, a un prix qui peut etre mauvais mais qui existe. Apres
graduation, cinq pools sur vingt-cinq sont invendables a notre taille (S3.36) et c est la cause de
25 % des tickets aneantis. Ce risque-la disparait ici.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

log = logging.getLogger(__name__)

PUMP = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
_INVOKE = re.compile(r"Program (\S+) invoke")


class PumpCourbe:
    def __init__(self, ctx, client) -> None:
        self.ctx, self.client = ctx, client
        self.dernier_slot: int | None = None

    def _cfg(self, cle: str, defaut):
        return self.ctx.config.get("pump_courbe." + cle, defaut)

    def _table(self) -> None:
        self.ctx.db.execute(
            "CREATE TABLE IF NOT EXISTS pump_creations("
            "  mint TEXT PRIMARY KEY, ts INTEGER, slot INTEGER,"
            "  telegram INTEGER, twitter INTEGER, site INTEGER, n_descr INTEGER, lu INTEGER)")
        # Le prix SUR LA COURBE, avant toute graduation. La courbe est un compte derive du mint et
        # son etat porte les reserves virtuelles : prix = SOL virtuel / jetons virtuels. Rien a
        # deviner, rien a interroger chez un tiers -- et la liquidite y est algorithmique, donc on
        # peut toujours ressortir, ce qui n est pas vrai apres graduation.
        self.ctx.db.execute(
            "CREATE TABLE IF NOT EXISTS pump_prix("
            "  mint TEXT NOT NULL, ts INTEGER NOT NULL, age_s INTEGER,"
            "  prix_sol REAL, sol_reel REAL, complet INTEGER,"
            "  PRIMARY KEY (mint, ts))")

    async def _rpc(self, methode: str, params: list) -> Any:
        """Une erreur est JOURNALISEE, jamais rendue comme un resultat vide (S3.74)."""
        from intel.execution import solana as sol
        rpc = sol.rpc_url()
        if not rpc:
            return None
        try:
            r = await self.client.post(rpc, json={"jsonrpc": "2.0", "id": 1,
                                                  "method": methode, "params": params}, timeout=60)
            j = r.json() or {}
        except Exception as exc:  # noqa: BLE001
            log.info("courbe: %s injoignable (%s)", methode, str(exc)[:70])
            return None
        if j.get("error"):
            log.info("courbe: %s refuse (%s)", methode, str(j["error"])[:100])
            return None
        return j.get("result")

    def _mints_du_bloc(self, b: dict) -> list[str]:
        """Les mints crees dans ce bloc. Un `Create` invoque DIRECTEMENT par pump.fun, et le mint
        est le seul compte de la transaction dont l adresse finit par `pump`."""
        out: list[str] = []
        for t in (b.get("transactions") or []):
            pile: list[str] = []
            cree = False
            for l in (((t.get("meta") or {}).get("logMessages")) or []):
                m = _INVOKE.match(l)
                if m:
                    pile.append(m.group(1))
                    continue
                if l.startswith("Program ") and l.endswith("success") and pile:
                    pile.pop()
                    continue
                if "Instruction: Create" in l and pile and pile[-1] == PUMP:
                    cree = True
            if not cree:
                continue
            for k in ((((t.get("transaction") or {}).get("message") or {}).get("accountKeys")) or []):
                a = k if isinstance(k, str) else k.get("pubkey")
                if a and a.endswith("pump"):
                    out.append(a)
                    break
        return out

    async def _lire_social(self, mints: list[str]) -> int:
        """La metadonnee de chaque nouveau mint. Gelee a la creation, donc lisible plus tard aussi --
        mais on la lit tout de suite pour que l horodatage du releve soit le notre."""
        from intel.execution import solana as sol
        from intel.research.social import _fiche, _meta
        rpc = sol.rpc_url()
        if not rpc:
            return 0

        async def un(i: int, m: str):
            meta = await _meta(self.client, rpc, m)
            if not meta:
                return m, None
            return m, await _fiche(self.client, meta.get("uri") or "", depart=i)

        faits = 0
        for i in range(0, len(mints), 12):
            lot = mints[i:i + 12]
            for m, j in await asyncio.gather(*[un(k, x) for k, x in enumerate(lot)]):
                try:
                    if j is None:
                        # Lecture ratee : `lu` reste a 0, on ne la compte pas comme « sans
                        # Telegram ». Confondre les deux fausserait la proportion cherchee.
                        continue
                    self.ctx.db.execute(
                        "UPDATE pump_creations SET telegram=?, twitter=?, site=?, n_descr=?, lu=1"
                        " WHERE mint=?",
                        (int(bool(j.get("telegram"))), int(bool(j.get("twitter"))),
                         int(bool(j.get("website"))), len(j.get("description") or ""), m))
                    faits += 1
                except Exception:  # noqa: BLE001
                    pass
        return faits

    async def _suivre_prix(self, now: int) -> int:
        """Le prix sur la courbe des jetons encore jeunes, lu en lots de cent.

        On ne suit que ceux dont la metadonnee a ete lue : ce sont les seuls sur lesquels une
        mesure sera possible, puisqu il faudra croiser le prix avec la presence d un Telegram.
        """
        import base64
        import struct

        from solders.pubkey import Pubkey
        fenetre = int(self._cfg("suivi_minutes", 15)) * 60
        cibles = self.ctx.db.query(
            "SELECT mint, ts FROM pump_creations WHERE lu=1 AND ts >= ? ORDER BY ts DESC LIMIT 300",
            (now - fenetre,))
        if not cibles:
            return 0
        prog = Pubkey.from_string(PUMP)
        pdas: dict[str, tuple[str, int]] = {}
        for c in cibles:
            try:
                pda, _ = Pubkey.find_program_address(
                    [b"bonding-curve", bytes(Pubkey.from_string(c["mint"]))], prog)
            except Exception:  # noqa: BLE001
                continue
            pdas[str(pda)] = (c["mint"], int(c["ts"]))
        cles = list(pdas)
        ecrits = 0
        for i in range(0, len(cles), 100):
            lot = cles[i:i + 100]
            res = await self._rpc("getMultipleAccounts", [lot, {"encoding": "base64"}])
            for k, v in zip(lot, (res or {}).get("value") or []):
                if not v:
                    continue
                try:
                    d = base64.b64decode(v["data"][0])
                    vt, vs, _rt, rs, _tot = struct.unpack_from("<QQQQQ", d, 8)
                    if vt <= 0:
                        continue
                    prix = (vs / 1e9) / (vt / 1e6)
                    complet = int(bool(d[8 + 40])) if len(d) > 48 else 0
                except Exception:  # noqa: BLE001
                    continue
                mint, ne = pdas[k]
                try:
                    self.ctx.db.execute(
                        "INSERT OR IGNORE INTO pump_prix(mint, ts, age_s, prix_sol, sol_reel,"
                        " complet) VALUES(?,?,?,?,?,?)",
                        (mint, now, now - ne, prix, rs / 1e9, complet))
                    ecrits += 1
                except Exception:  # noqa: BLE001
                    pass
        return ecrits

    async def cycle(self) -> dict[str, Any]:
        if not bool(self._cfg("enabled", False)):
            return {"status": "disabled"}
        self._table()
        now = int(time.time())
        tete = await self._rpc("getSlot", [])
        if not tete:
            return {"status": "pas de slot"}
        depart = self.dernier_slot + 1 if self.dernier_slot else tete - 20
        # Apres un arret on ne rattrape pas indefiniment : la mesure est un SONDAGE, pas un
        # recensement. Rater une heure ne biaise rien tant qu on ne choisit pas quoi rater.
        depart = max(depart, tete - int(self._cfg("max_slots", 300)))
        lot = int(self._cfg("slots_par_cycle", 40))
        fin = min(tete - 2, depart + lot)
        if fin < depart:
            return {"status": "ok", "crees": 0}

        neufs: list[str] = []
        res = await asyncio.gather(*[self._rpc("getBlock", [
            s, {"encoding": "json", "maxSupportedTransactionVersion": 0,
                "transactionDetails": "full", "rewards": False}]) for s in range(depart, fin + 1)])
        for s, b in zip(range(depart, fin + 1), res):
            if not b:
                continue
            for m in self._mints_du_bloc(b):
                try:
                    self.ctx.db.execute(
                        "INSERT OR IGNORE INTO pump_creations(mint, ts, slot, lu) VALUES(?,?,?,0)",
                        (m, now, s))
                    neufs.append(m)
                except Exception:  # noqa: BLE001
                    pass
        self.dernier_slot = fin

        # On ne lit la metadonnee que d un ECHANTILLON : 30 600 lectures par jour satureraient les
        # passerelles IPFS, et un sondage suffit pour une proportion.
        part = float(self._cfg("part_lue", 0.35))
        a_lire = [m for i, m in enumerate(neufs) if (hash(m) % 100) < part * 100]
        lus = await self._lire_social(a_lire) if a_lire else 0
        prix = await self._suivre_prix(now)
        return {"status": "ok", "crees": len(neufs), "lus": lus, "prix": prix,
                "total": self.ctx.db.scalar("SELECT COUNT(*) FROM pump_creations", (), 0) or 0}
