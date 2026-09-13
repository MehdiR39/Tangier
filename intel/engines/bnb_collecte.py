"""Collecter BNB Chain pour pouvoir un jour y tester la regle Telegram. N ACHETE RIEN.

POURQUOI CE MODULE EXISTE. L operateur, le 13/09 : « en parallele sans casser ce qu on a fait il
faut explorer les autres chaines », puis « faut pas juste backtester la strategie sur binance ? ».

Justement non, et c est tout le probleme. Sur Solana le lien Telegram est grave DANS le jeton a sa
creation et personne ne peut le changer (`updateAuthority: None`, verifie 40 fois sur 40) : le lire
aujourd hui prouve qu il etait la a la seconde zero. Sur BNB rien de tel -- four.meme garde les
liens dans SA base de donnees, que le createur remplit quand il veut. Rejouer l historique y
montrerait probablement un magnifique resultat, entierement faux : les jetons qui ont monte ont pu
recevoir leur Telegram APRES la montee, et on croirait l avoir predit. C est la fuite du futur, et
elle est deja mesuree sur Robinhood Chain (part des jetons avec reseaux : 58 % sous 2 h, 83 % apres
7 jours).

LA SEULE SORTIE est de fabriquer la donnee propre : voir la creation sur la chaine, puis relever les
liens NOUS-MEMES a T+60 et horodater ce relevé. Apres deux ou trois jours, l historique ainsi
constitue est honnete et le test devient valide. C est ce que fait ce fichier, et rien d autre.

COMMENT. four.meme emet ses creations depuis `0x5c9520...`, et l evenement porte tout :

    mot 0   adresse du createur
    mot 1   adresse du NOUVEAU JETON
    mot 3   decalage vers le nom      -> chaine
    mot 4   decalage vers le symbole  -> chaine

Decode et verifie le 13/09 : sept creations en quarante-cinq secondes, noms lisibles
(« DeepFuckingValue », « Smoky Franklin »...). Le noeud public `bsc.publicnode.com` suffit --
`bsc-dataseed` refuse `eth_getLogs` avec `limit exceeded`, et il faut LIRE cette erreur au lieu de
la confondre avec une liste vide.

CE QUE CE MODULE NE FAIT PAS. Il n achete rien, ne vend rien, ne signe rien, n a aucune cle BNB, et
ne touche a aucune table du moteur Solana. Il ecrit dans `bnb_lancements` et `bnb_releves`.

UNE DIFFERENCE A NE PAS OUBLIER quand viendra le test : ces evenements sont des CREATIONS sur la
courbe de bonding, pas des graduations. Sur Solana nous ne tradons que des jetons deja gradues. Les
deux populations ne sont pas comparables, et il faudra soit suivre les graduations BNB, soit
assumer qu on mesure autre chose.
"""
from __future__ import annotations

import logging
import time
from typing import Any

log = logging.getLogger(__name__)

RPC_DEFAUT = "https://bsc.publicnode.com"
FOUR_MEME = "0x5c952063c7fc8610ffdb798152d69f0b9550762b"
DEXS = "https://api.dexscreener.com/latest/dex/tokens/"

AGE_RELEVE = 45          # s : premier relevé, au plus tot
AGE_LIMITE = 900         # s : au-dela on cesse de suivre un lancement


def _mot(d: str, i: int) -> str:
    return d[i * 64:(i + 1) * 64]


def _chaine(d: str, offset_octets: int) -> str:
    """Une chaine ABI : un mot de longueur, puis les octets."""
    i = offset_octets // 32
    n = int(_mot(d, i), 16)
    if n <= 0 or n > 200:
        return ""
    brut = bytes.fromhex("".join(_mot(d, i + 1 + k) for k in range((n + 31) // 32)))[:n]
    return brut.decode("utf-8", "ignore")


class BnbCollecte:
    def __init__(self, ctx, client) -> None:
        self.ctx, self.client = ctx, client
        self.dernier_bloc: int | None = None

    def _cfg(self, cle: str, defaut):
        return self.ctx.config.get("bnb_collecte." + cle, defaut)

    def _tables(self) -> None:
        self.ctx.db.execute(
            "CREATE TABLE IF NOT EXISTS bnb_lancements("
            "  jeton TEXT PRIMARY KEY, nom TEXT, symbole TEXT, createur TEXT,"
            "  bloc INTEGER, ts_vu INTEGER)")
        self.ctx.db.execute(
            "CREATE TABLE IF NOT EXISTS bnb_releves("
            "  jeton TEXT NOT NULL, ts INTEGER NOT NULL, age_s INTEGER,"
            "  telegram INTEGER, twitter INTEGER, site INTEGER,"
            "  prix_usd REAL, liquidite_usd REAL, paire TEXT,"
            "  PRIMARY KEY (jeton, ts))")

    async def _rpc(self, methode: str, params: list) -> Any:
        """Un appel JSON-RPC. Une ERREUR est journalisee, jamais rendue comme un resultat vide.

        C est la regle que j ai violee le 13/09 : `reponse.get('result') or []` transforme un refus
        en absence, et j en ai conclu qu un contrat de vingt millions de transactions n emettait
        rien.
        """
        rpc = str(self._cfg("rpc", RPC_DEFAUT))
        try:
            r = await self.client.post(rpc, json={"jsonrpc": "2.0", "id": 1,
                                                  "method": methode, "params": params}, timeout=30)
            j = r.json() or {}
        except Exception as exc:  # noqa: BLE001
            log.info("bnb: %s injoignable (%s)", methode, str(exc)[:80])
            return None
        if j.get("error"):
            log.info("bnb: %s refuse par le noeud (%s)", methode, str(j["error"])[:120])
            return None
        return j.get("result")

    # ------------------------------------------------------------ les creations
    async def _lire_creations(self, now: int) -> int:
        tete = await self._rpc("eth_blockNumber", [])
        if not tete:
            return 0
        tete = int(tete, 16)
        # on ne remonte jamais plus loin que `max_blocs` : apres un arret, rattraper des heures
        # couterait des centaines d appels pour des lancements deja hors fenetre.
        depart = self.dernier_bloc + 1 if self.dernier_bloc else tete - 30
        depart = max(depart, tete - int(self._cfg("max_blocs", 200)))
        neufs = 0
        b = depart
        while b <= tete:
            fin = min(b + 1, tete)
            logs = await self._rpc("eth_getLogs", [{"address": FOUR_MEME,
                                                    "fromBlock": hex(b), "toBlock": hex(fin)}])
            if logs is None:
                break                      # le noeud refuse : on reessaiera, sans avancer
            for lg in logs:
                d = (lg.get("data") or "")[2:]
                if len(d) < 700:
                    continue
                try:
                    createur = "0x" + _mot(d, 0)[24:]
                    jeton = "0x" + _mot(d, 1)[24:]
                    nom = _chaine(d, int(_mot(d, 3), 16))
                    sym = _chaine(d, int(_mot(d, 4), 16))
                except Exception:  # noqa: BLE001
                    continue
                if not sym or jeton.startswith("0x" + "0" * 8):
                    continue
                try:
                    self.ctx.db.execute(
                        "INSERT OR IGNORE INTO bnb_lancements"
                        "(jeton, nom, symbole, createur, bloc, ts_vu) VALUES(?,?,?,?,?,?)",
                        (jeton, nom[:80], sym[:32], createur, int(lg["blockNumber"], 16), now))
                    neufs += 1
                except Exception:  # noqa: BLE001
                    pass
            self.dernier_bloc = fin
            b = fin + 1
        return neufs

    # -------------------------------------------------------------- les relevés
    async def _relever(self, now: int) -> int:
        """Les liens sociaux et le prix, horodates PAR NOUS. C est tout l interet du module."""
        cibles = self.ctx.db.query(
            "SELECT jeton, ts_vu FROM bnb_lancements WHERE ts_vu <= ? AND ts_vu >= ?"
            " ORDER BY ts_vu DESC LIMIT 30", (now - AGE_RELEVE, now - AGE_LIMITE))
        if not cibles:
            return 0
        faits = 0
        for i in range(0, len(cibles), 25):
            lot = cibles[i:i + 25]
            try:
                r = await self.client.get(DEXS + ",".join(x["jeton"] for x in lot), timeout=25)
                paires = (r.json() or {}).get("pairs") or []
            except Exception as exc:  # noqa: BLE001
                log.info("bnb: dexscreener muet (%s)", str(exc)[:70])
                continue
            vu: dict[str, dict] = {}
            for p in paires:
                a = ((p.get("baseToken") or {}).get("address") or "").lower()
                liq = float((p.get("liquidity") or {}).get("usd") or 0)
                if a and liq >= float(vu.get(a, {}).get("liq", -1)):
                    vu[a] = {"p": p, "liq": liq}
            for x in lot:
                e = vu.get(x["jeton"].lower())
                if not e:
                    continue
                p = e["p"]
                soc = {s.get("type") for s in ((p.get("info") or {}).get("socials") or [])}
                try:
                    self.ctx.db.execute(
                        "INSERT OR IGNORE INTO bnb_releves(jeton, ts, age_s, telegram, twitter,"
                        " site, prix_usd, liquidite_usd, paire) VALUES(?,?,?,?,?,?,?,?,?)",
                        (x["jeton"], now, now - int(x["ts_vu"]),
                         int("telegram" in soc), int("twitter" in soc),
                         int(bool((p.get("info") or {}).get("websites"))),
                         float(p.get("priceUsd") or 0) or None, e["liq"], p.get("pairAddress")))
                    faits += 1
                except Exception:  # noqa: BLE001
                    pass
        return faits

    async def cycle(self) -> dict[str, Any]:
        if not bool(self._cfg("enabled", False)):
            return {"status": "disabled"}
        self._tables()
        now = int(time.time())
        neufs = await self._lire_creations(now)
        releves = await self._relever(now)
        return {"status": "ok", "creations": neufs, "releves": releves,
                "connus": self.ctx.db.scalar("SELECT COUNT(*) FROM bnb_lancements", (), 0) or 0}
