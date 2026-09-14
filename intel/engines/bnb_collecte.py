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
# DexScreener ne porte aucun bloc `info` pour un jeton four.meme sur courbe : ni prix, ni
# liquidite, ni reseaux. Verifie le 14/09 champ par champ. On interroge donc four.meme.
FOURMEME_API = "https://four.meme/meme-api/v1/private/token/get?address="

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
        """Les liens sociaux et le prix, horodates PAR NOUS. C est tout l interet du module.

        LA SOURCE A CHANGE LE 14/09, et le premier choix etait faux. On interrogeait DexScreener :
        pour un jeton four.meme encore sur sa courbe il renvoie bien une paire, mais AUCUN bloc
        `info` -- ni prix, ni liquidite, ni reseaux. D ou 0 Telegram sur 54 228 relevés, un chiffre
        que j avais pris pour un fait sur la chaine alors qu il ne disait que « cette source ne
        porte pas cette information ». Verifie champ par champ sur la reponse complete : les cles
        sont exactement baseToken, chainId, dexId, pairAddress, pairCreatedAt, priceChange,
        priceNative, quoteToken, txns, url, volume. Pas d `info`, jamais.

        L API de four.meme, elle, porte tout, et un appel par jeton :
            /meme-api/v1/private/token/get?address=<adresse>
            -> telegramUrl, twitterUrl, webUrl, tokenPrice.price, tokenPrice.marketCap

        Sondage du 14/09 sur 90 jetons : Telegram 40 a 44 %, twitter 87 a 89 %, site 64 a 71 %.
        Sans commune mesure avec Solana (3,7 %, 42 %, 20 %) -- ce qui CHANGE la nature du signal :
        un lien present sur 40 % des jetons ne trie presque rien, la ou sa rarete faisait sa force.
        C est precisement ce que la collecte horodatee doit trancher.

        POURQUOI HORODATER RESTE VITAL : ces liens sont dans la base de four.meme, donc modifiables
        apres coup. L ecart mesure entre 8-24 h (40,0 %) et plus de 24 h (44,4 %) est faible mais
        non nul, et la tranche qui compte -- moins de 2 h -- manquait faute de collecte. Lire
        aujourd hui un jeton d hier reviendrait a lire le futur.
        """
        cibles = self.ctx.db.query(
            "SELECT jeton, ts_vu FROM bnb_lancements WHERE ts_vu <= ? AND ts_vu >= ?"
            " ORDER BY ts_vu DESC LIMIT 30", (now - AGE_RELEVE, now - AGE_LIMITE))
        if not cibles:
            return 0
        faits = 0
        for x in cibles:
            try:
                r = await self.client.get(FOURMEME_API + x["jeton"], timeout=20,
                                          headers={"accept": "application/json",
                                                   "user-agent": "Mozilla/5.0"})
                j = r.json() or {}
            except Exception as exc:  # noqa: BLE001
                log.info("bnb: four.meme muet (%s)", str(exc)[:70])
                continue
            # LIRE L ERREUR AVANT LE RESULTAT. `j.get("data") or {}` effacerait la difference entre
            # « ce jeton n a pas de Telegram » et « l API a refuse » -- la famille d erreurs qui a
            # deja produit trois conclusions fausses cette semaine.
            if j.get("code") != 0:
                continue
            d = j.get("data")
            if not isinstance(d, dict):
                continue
            prix = None
            try:
                prix = float(((d.get("tokenPrice") or {}).get("price")) or 0) or None
            except Exception:  # noqa: BLE001
                pass
            cap = None
            try:
                cap = float(((d.get("tokenPrice") or {}).get("marketCap")) or 0) or None
            except Exception:  # noqa: BLE001
                pass
            try:
                self.ctx.db.execute(
                    "INSERT OR IGNORE INTO bnb_releves(jeton, ts, age_s, telegram, twitter,"
                    " site, prix_usd, liquidite_usd, paire) VALUES(?,?,?,?,?,?,?,?,?)",
                    (x["jeton"], now, now - int(x["ts_vu"]),
                     int(bool(d.get("telegramUrl"))), int(bool(d.get("twitterUrl"))),
                     int(bool(d.get("webUrl"))), prix, cap, d.get("dexType")))
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
