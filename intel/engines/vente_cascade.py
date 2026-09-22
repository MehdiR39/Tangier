"""Vendre dans la seconde quand le pool d une position ouverte s effondre.

POURQUOI. Mesure du 15/09 sur le carnet reel (145 tickets propres, 82 Telegram, prix lus en chaine) :

  - les VIDAGES (ticket a -50 % ou pire) font l essentiel de la perte : 22 tickets propres sur 145,
    86 % de la perte de la nuit du 14 au 15 ;
  - au moment d acheter, AUCUNE des 18 variables mesurees ne les distingue (la meilleure est a 13 %
    de hasard). On ne peut pas les eviter a l entree ;
  - juste avant le crash le jeton est AU-DESSUS de notre prix d achat (+1,2 % en mediane) : il ne se
    degrade pas, il tombe ;
  - mais un vidage n est pas UNE vente, c est une CASCADE. La premiere grosse vente fait -24 %, puis
    4 a 22 vendeurs suivent en quelques secondes. Prix obtenu selon le delai de notre vente :

        delai            0,8 s    1,6 s    3,2 s    10 s
        propre            -23 %    -46 %    -49 %    -68 %
        telegram          -33 %    -33 %    -68 %    -86 %

  - le moteur lit le pool toutes les 10 s et ne vend qu a 240 s : il encaisse toute la cascade.
    Quinze regles de stop rejouees sur les lectures a 10 s n aident pas -- a cette cadence une
    respiration normale et un crash se ressemblent. Ce qui change ici, c est la CADENCE.

CE QUI RESTE A MESURER : combien de fois ce declencheur ferait sortir un jeton qui allait bien finir.
Le mode `papier` ecrit ce qu il aurait fait dans `tg_cascade` sans rien vendre ; le mode `live`
vend par le chemin de vente habituel, avec plus de glissement et plus de priorite.

CE MODULE NE SIGNE RIEN LUI-MEME. En mode live il appelle `TelegramRapide._vendre_reel`, qui garde
ses protections : solde lu en chaine, une seule vente a la fois par jeton.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import time
from collections import deque
from typing import Any

import base58

log = logging.getLogger(__name__)

PAMM = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
OFF_BASE_TA = 43 + 32 * 3          # meme disposition que prix_chaine.py : base_ta puis quote_ta


def chute(historique, prix: float, now: float, fenetre_s: float) -> tuple[float, float]:
    """Chute du prix courant par rapport au PLUS HAUT des `fenetre_s` dernieres secondes.

    Rend (chute, reference), chute <= 0. Le plus haut, pas la derniere lecture : une cascade peut
    s etaler sur plusieurs lectures, et chacune ne ferait qu une partie du chemin.
    """
    recents = [p for t, p in historique if now - t <= fenetre_s]
    ref = max(recents + [prix])
    return (prix / ref - 1.0 if ref > 0 else 0.0), ref


class GuetCascade:
    """Surveille les positions ouvertes de `TelegramRapide` a la seconde."""

    def __init__(self, moteur) -> None:
        self.m = moteur
        self.pools: dict[str, tuple[str, str] | None] = {}   # pair_id -> (base_ta, quote_ta)
        self.virtuelles: dict[str, float] = {}                # pair_id -> reserve virtuelle (SOL)
        self.hist: dict[str, deque] = {}                      # mint -> [(t, prix)]
        self.essais: dict[str, int] = {}                      # mint -> declenchements
        self.dernier: dict[str, float] = {}                   # mint -> t du dernier declenchement

    def _cfg(self, cle: str, defaut):
        return self.m.ctx.config.get("telegram_rapide.vente_cascade." + cle, defaut)

    def mode(self) -> str:
        m = str(self._cfg("mode", "off") or "off").lower()
        return m if m in ("papier", "live") else "off"

    # ------------------------------------------------------------------ lecture
    async def _rpc(self, methode: str, params: list) -> Any:
        from intel.execution import solana as sol
        r = await self.m.client.post(sol.rpc_url(), json={
            "jsonrpc": "2.0", "id": 1, "method": methode, "params": params},
            timeout=float(self._cfg("delai_rpc_s", 4.0)))
        j = r.json() or {}
        # Une erreur n est pas un resultat vide (§6) : on la fait remonter au lieu de lire « rien ».
        if "error" in j:
            raise RuntimeError(str(j["error"])[:120])
        return j.get("result")

    async def _comptes(self, pair: str) -> tuple[str, str] | None:
        if pair in self.pools:
            return self.pools[pair]
        res = await self._rpc("getAccountInfo", [pair, {"encoding": "base64"}])
        v = (res or {}).get("value")
        compte = None
        if v and v.get("owner") == PAMM:
            d = base64.b64decode(v["data"][0])
            from intel.engines.prix_chaine import reserve_virtuelle
            self.virtuelles[pair] = reserve_virtuelle(d)
            if len(d) >= OFF_BASE_TA + 64:
                compte = (base58.b58encode(d[OFF_BASE_TA:OFF_BASE_TA + 32]).decode(),
                          base58.b58encode(d[OFF_BASE_TA + 32:OFF_BASE_TA + 64]).decode())
        if compte is None:
            log.warning("cascade: %s n est pas un pool PumpSwap lisible, position non surveillee", pair[:12])
        self.pools[pair] = compte
        return compte

    async def lire(self, lignes) -> dict[str, float]:
        """Prix courant (reserve quote / reserve base) de chaque position, en UN appel groupe."""
        paires = {}
        pool_de = {}
        for l in lignes:
            if l["pair_id"]:
                c = await self._comptes(l["pair_id"])
                if c:
                    paires[l["mint"]] = c
                    pool_de[l["mint"]] = l["pair_id"]
        comptes = [a for c in paires.values() for a in c]
        if not comptes:
            return {}
        res = await self._rpc("getMultipleAccounts",
                              [comptes, {"encoding": "jsonParsed", "commitment": "processed"}])
        montants = {}
        for a, v in zip(comptes, (res or {}).get("value") or []):
            try:
                montants[a] = float(v["data"]["parsed"]["info"]["tokenAmount"]["uiAmountString"])
            except Exception:  # noqa: BLE001
                continue
        prix = {}
        for mint, (b, q) in paires.items():
            xb, xq = montants.get(b), montants.get(q)
            if xb and xq and xb > 0:
                # prix ECHANGEABLE : la reserve virtuelle du pool compte (§3.83)
                prix[mint] = (xq + self.virtuelles.get(pool_de.get(mint), 0.0)) / xb
        return prix

    # ------------------------------------------------------------------- decision
    async def tour(self, now: float | None = None) -> int:
        mode = self.mode()
        if mode == "off":
            return 0
        lignes = self.m.ctx.db.query("SELECT * FROM tg_lignes WHERE statut='OUVERTE'")
        ouvertes = {l["mint"] for l in lignes}
        for mint in [k for k in self.hist if k not in ouvertes]:
            self.hist.pop(mint, None)
            self.essais.pop(mint, None)
            self.dernier.pop(mint, None)
        if not lignes:
            return 0
        prix = await self.lire(lignes)
        now = time.time() if now is None else now
        seuil = float(self._cfg("seuil_pct", 15.0)) / 100.0
        fenetre = float(self._cfg("fenetre_s", 5.0))
        faits = 0
        for l in lignes:
            p = prix.get(l["mint"])
            if not p:
                continue
            h = self.hist.setdefault(l["mint"], deque(maxlen=900))
            c, ref = chute(h, p, now, fenetre)
            h.append((now, p))
            if c <= -seuil:
                faits += await self._declencher(l, p, ref, c, now, mode)
        return faits

    async def _declencher(self, l, prix: float, ref: float, c: float, now: float, mode: str) -> int:
        mint = l["mint"]
        k = self.essais.get(mint, 0)
        if k >= int(self._cfg("max_essais", 5)):
            return 0
        if k and now - self.dernier.get(mint, 0.0) < float(self._cfg("reessai_s", 2.0)):
            return 0
        self.essais[mint] = k + 1
        self.dernier[mint] = now
        age = now - float(l["ts_entree"] or now)
        self._noter(l, prix, ref, c, now, mode, age, k + 1)
        if mode != "live":
            if k == 0:
                log.info("cascade: %s AURAIT ETE VENDU (papier) - %+.1f %% sous le plus haut, a T+%.0f s",
                         l["symbole"], 100 * c, age)
            self.essais[mint] = int(self._cfg("max_essais", 5))    # une seule note par position
            return 0
        motif = "cascade : %+.0f %% sous le plus haut a T+%.0f s" % (100 * c, age)
        log.warning("cascade: %s VENTE IMMEDIATE (essai %d) - %s", l["symbole"], k + 1, motif)
        if l["mode"] != "live":
            return self.m._fermer_papier(l, int(now), prix, motif)
        return await self.m._vendre_reel(l, int(now), prix, motif=motif, cascade=True)

    def _noter(self, l, prix, ref, c, now, mode, age, essai) -> None:
        try:
            self.m.ctx.db.execute(
                "CREATE TABLE IF NOT EXISTS tg_cascade(ts REAL, mint TEXT, symbole TEXT, mode TEXT,"
                " mode_ligne TEXT, age_s REAL, prix_ref REAL, prix REAL, chute REAL, essai INTEGER)")
            self.m.ctx.db.execute(
                "INSERT INTO tg_cascade VALUES(?,?,?,?,?,?,?,?,?,?)",
                (now, l["mint"], l["symbole"], mode, l["mode"], age, ref, prix, c, essai))
        except Exception as exc:  # noqa: BLE001
            log.info("cascade: note non ecrite (%s)", str(exc)[:80])

    # --------------------------------------------------------------------- boucle
    async def boucle(self) -> None:
        """Tourne tant que le moteur vit. Une erreur coute un tour, jamais la boucle."""
        while True:
            debut = time.monotonic()
            try:
                await self.tour()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.warning("cascade: tour rate (%s)", str(exc)[:120])
            periode = float(self._cfg("periode_s", 1.0))
            await asyncio.sleep(max(0.2, periode - (time.monotonic() - debut)))
