"""The T+1 book on Solana: discover a launch, judge its first minute, buy, sell on the clock.

Same shape as the Robinhood watcher, same book, same exit rule, and deliberately NOT the same
thresholds. A Robinhood launch that clears the bar trades 27 to 60 times in its first minute; the
first Solana measurements, taken 2026-09-07, run from 186 to 2 834. Carrying those numbers across
would either buy everything or nothing, which is the mistake that cost real money that morning.

So the entry rule here is expressed in the terms Solana actually offers, and its thresholds start
deliberately impossible: `solana.min_buyers` at 0 buys nothing. They are meant to be set from the
measurement running in intel/research/solana_watch.py, not from judgement.

What Solana gives that Robinhood never could: the payer of every transaction, in plain sight. On
Robinhood the swap `sender` is a router for 98 % of trades, so "how many distinct people are
buying" was unknowable and no filter could separate a bundle from a crowd. Here the first readings
already show the gap -- 2 834 trades between 40 wallets on one launchpad against 343 trades
between 139 on another -- and that ratio is the rule this engine is built to test.

It never signs unless two separate acts have been taken: a key in SOLANA_PRIVATE_KEY and
`solana.mode` set to live. Neither is done here.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import httpx

from intel.context import IntelContext
from intel.execution import solana as sol
from intel.utils.timeutil import now_ts

log = logging.getLogger(__name__)
MODEL_VERSION = "sol-t1-v0.1"
DISCOVERY = (
    "https://api.dexscreener.com/token-profiles/latest/v1",
    "https://api.dexscreener.com/token-boosts/latest/v1",
)
PAIRS_URL = "https://api.dexscreener.com/latest/dex/tokens/"


class SolanaWatcher:
    def __init__(self, ctx: IntelContext) -> None:
        self.ctx = ctx
        self.client = httpx.AsyncClient(headers={"User-Agent": "tangier-intel/solana"})
        self.judged: dict[str, int] = {}          # pair -> ts, so a launch is judged once
        self.sent_ts: list[int] = []
        self.annonces: set[str] = set()           # jetons du flux deja annonces, pour ne pas repeter
        # Un seul passage de carnet a la fois : la boucle rapide et le cycle de decouverte appellent
        # tous deux `run_carnet`, et deux passages simultanes vendraient deux fois la meme ligne.
        self._garde = asyncio.Lock()

    def _cfg(self, key: str, default: Any) -> Any:
        return self.ctx.config.get(f"solana.{key}", default)

    async def close(self) -> None:
        await self.client.aclose()

    # ---------------------------------------------------------------- cycle
    async def run_cycle(self) -> dict[str, Any]:
        if not self._cfg("enabled", False):
            return {"status": "disabled"}
        rpc = sol.rpc_url()
        if not rpc:
            return {"status": "disabled", "reason": "SOLANA_RPC_URL absent"}
        try:
            pairs = await self._discover()
        except Exception as exc:  # noqa: BLE001
            log.info("solana: decouverte refusee (%s)", str(exc)[:80])
            return {"status": "skipped", "error": str(exc)[:120]}
        # Un jeton gradue possede plusieurs pools -- sa courbe de bonding et le nouveau -- et les
        # juger separement donne deux verdicts contradictoires sur le meme lancement : BIPOLAR a
        # ete mesure a 162 echanges pour 84 acheteurs sur l un et 786 pour 114 sur l autre, le
        # premier passant la regle et le second non. On ne garde donc qu un pool par jeton, le plus
        # profond, qui est celui ou le negoce a lieu.
        meilleurs: dict[str, dict[str, Any]] = {}
        for p in pairs:
            mint = (p.get("baseToken") or {}).get("address")
            if not mint:
                continue
            liq = float((p.get("liquidity") or {}).get("usd") or 0)
            garde = meilleurs.get(mint)
            if garde is None or liq > float((garde.get("liquidity") or {}).get("usd") or 0):
                meilleurs[mint] = p
        pairs = list(meilleurs.values())

        judged = bought = 0
        for p in pairs:
            pid = p.get("pairAddress")
            created = p.get("pairCreatedAt")
            if not pid or not created or pid in self.judged:
                continue
            age_s = time.time() - created / 1000.0
            if age_s < 75 or age_s > float(self._cfg("max_age_seconds", 600)):
                continue                                   # judged once its first minute is complete
            self.judged[pid] = now_ts()
            judged += 1
            if await self._decide(rpc, p):
                bought += 1
        self._forget()
        await self.run_carnet()
        return {"status": "ok", "seen": len(pairs), "judged": judged, "decisions": bought}

    async def run_carnet(self) -> dict[str, Any]:
        """Executer les decisions et surveiller les positions ouvertes. Boucle rapide, a part.

        Ce travail etait la queue de `run_cycle`, donc il ne passait qu APRES la decouverte et le
        jugement des lancements -- soit toutes les 35 a 95 secondes, mesure le 09/09/2026. Pour un
        stop de perte c est une eternite : AMDuck, ouverte a 23:57:56 et fermee a 00:03:44, a un
        sommet a x1,11 et une sortie a x0,06 alors que le stop coupe a x0,7. Le stop a bien
        declenche -- la ligne se ferme en 5 minutes, pas en 15 -- mais le prix avait deja traverse
        toute la chute entre deux relevés.

        Ces effondrements ne sont pas un detail, ils sont TOUT le deficit : sur les 28 tickets
        Solana, sept pertes de plus de la moitie du ticket coutent 110 EUR, et les vingt et un
        autres rapportent entre +0,10 et +0,14 par euro (§3.34).

        La surveillance tourne donc dans sa propre boucle, et le verrou garantit qu un passage lance
        par la decouverte et un passage lance par la boucle rapide ne se chevauchent jamais : deux
        passages simultanes vendraient deux fois la meme ligne, et c est exactement le genre de
        collision qui a fait payer BIPOLAR deux fois le 08/09.
        """
        rpc = sol.rpc_url()
        if not rpc or not self._cfg("enabled", False):
            return {"status": "disabled"}
        if self._garde.locked():
            return {"status": "occupe"}
        async with self._garde:
            await self._book(rpc)
            mode = str(self._cfg("mode", "dry_run"))
            if mode == "live":
                await self._reconcile(rpc)
            await self._positions(rpc, mode)
        return {"status": "ok"}

    async def _discover(self) -> list[dict[str, Any]]:
        tokens: list[str] = []
        for url in DISCOVERY:
            r = await self.client.get(url, timeout=25)
            for x in r.json() if isinstance(r.json(), list) else []:
                if x.get("chainId") == "solana" and x.get("tokenAddress"):
                    tokens.append(x["tokenAddress"])
        tokens = list(dict.fromkeys(tokens))
        # La seconde source : les creations de pool ecoutees en direct (intel/engines/solana_stream).
        # Elle vient EN PLUS de DexScreener, jamais a sa place, et chaque jeton garde la trace de
        # savoir si l autre source l avait aussi. Sans cette trace on ne pourrait pas dire ce que
        # le flux apporte vraiment -- 4,3 graduations PumpSwap par heure vues aujourd hui contre
        # une vingtaine qui se produisent.
        du_flux: list[str] = []
        try:
            connus = set(tokens)
            for r in self.ctx.db.query(
                    "SELECT mint FROM solana_stream_launches WHERE ts > ? ORDER BY ts DESC LIMIT 60",
                    (now_ts() - 900,)):
                m = r["mint"]
                if m in connus:
                    self.ctx.db.execute(
                        "UPDATE solana_stream_launches SET vu_par_dexscreener=1 WHERE mint=?", (m,))
                elif m not in du_flux:
                    du_flux.append(m)
        except Exception as exc:  # noqa: BLE001
            log.info("solana: flux non consulte (%s)", str(exc)[:70])
        # On garde le jeton dans la liste pendant un quart d heure -- le temps que DexScreener
        # indexe sa paire, ce qui prend environ une minute -- mais on ne le dit qu une fois.
        neufs = [m for m in du_flux if m not in self.annonces]
        if neufs:
            log.info("solana: %d jeton(s) que seul le flux a vus", len(neufs))
            self.annonces.update(neufs)
        tokens = list(dict.fromkeys(tokens + du_flux))

        out: list[dict[str, Any]] = []
        for i in range(0, len(tokens), 25):
            r = await self.client.get(PAIRS_URL + ",".join(tokens[i: i + 25]), timeout=25)
            out.extend((r.json() or {}).get("pairs") or [])
        return [p for p in out if p.get("chainId") == "solana"]

    async def _first_minute(self, rpc: str, pair_id: str, created_ms: int) -> tuple[int, int]:
        """(trades, distinct payers) in the pool's first sixty seconds."""
        start = created_ms // 1000
        sigs: list[dict[str, Any]] = []
        before = None
        # On remonte l historique du plus recent vers le plus ancien. Tant qu on n a pas franchi
        # l instant de creation, la fenetre est INCOMPLETE : ce qu on a sous la main n est pas la
        # premiere minute, c est la fin de la periode observee. Le compte serait alors trop petit,
        # et trop petit dans le sens qui fait passer un jeton.
        #
        # C est exactement ce qui a coute NASFROG le 08/09/2026. Mesure a 20:54:27, la remontee
        # atteignait encore la creation : 1 387 echanges, au-dessus du plafond de 600, ecarte. Six
        # minutes plus tard le pool avait grossi, la meme remontee n atteignait plus le debut et ne
        # rapportait que 258 echanges -- sous le plafond, donc achete, a 2,374e-06 contre 6,194e-05
        # mesures six minutes plus tot. Une chute de 96 % entre la mesure et l achat. Le filtre
        # anti-pompe a ete contourne par sa propre mesure : plus le lancement est violent, plus vite
        # la remontee cesse de l atteindre, donc plus il a de chances de passer.
        #
        # Une mesure qui ne sait pas ce qu elle n a pas vu ne vaut rien. On rend -1 pour dire
        # "je n ai pas pu mesurer", et l appelant refuse d acheter. Un refus se compte et se lit ;
        # un chiffre faux ne se voit pas.
        atteint = False
        for _ in range(int(self._cfg("signature_pages", 12) or 12)):
            params: dict[str, Any] = {"limit": 1000}
            if before:
                params["before"] = before
            r = await self.client.post(rpc, json={"jsonrpc": "2.0", "id": 1, "method": "getSignaturesForAddress",
                                                  "params": [pair_id, params]}, timeout=40)
            got = (r.json() or {}).get("result") or []
            if not got:
                atteint = True          # l historique est epuise : on a bien tout vu
                break
            sigs.extend(got)
            before = got[-1]["signature"]
            if (got[-1].get("blockTime") or 0) <= start:
                atteint = True
                break
        if not atteint:
            return -1, -1
        window = [g for g in sigs if g.get("blockTime") and start <= g["blockTime"] <= start + 60]
        if not window:
            return 0, 0
        payers: set[str] = set()
        payers30: set[str] = set()
        key = rpc.split("api-key=")[-1] if "api-key=" in rpc else ""
        if key:
            # Buyers are counted on the first 300 transactions, trades on the whole minute, so the
            # ratio below has a full numerator and a sampled denominator. That is a real bias --
            # 46 % of launches exceed 300 trades and their ratio is inflated -- and it is DELIBERATE
            # from here on: measured on the 142 observed launches, the biased ratio filters better
            # than the unbiased one (<=15 biased: 110 lines, 62 % winners, +0.221 per euro; the
            # unbiased ratio at equal selectivity: 60 % and +0.193). It filters better because it
            # carries density as well as concentration, and density has an optimum of its own --
            # 300 to 600 trades in the first minute returns +0.390 per euro, above 600 it turns
            # negative. Raising this cap "to be correct" would quietly degrade the entry rule.
            # The collector in intel/research/solana_watch.py samples identically on purpose: the
            # thresholds were fitted on this quantity and must keep measuring the same thing.
            # La signature est retenue avec son payeur, pour pouvoir recompter sur une fenetre plus
            # courte sans rien redemander au reseau.
            sig30 = {g["signature"] for g in window if (g.get("blockTime") or 0) <= start + 30}
            for i in range(0, min(len(window), 300), 100):
                try:
                    r = await self.client.post(f"https://api.helius.xyz/v0/transactions/?api-key={key}",
                                               json={"transactions": [w["signature"] for w in window[i: i + 100]]},
                                               timeout=50)
                    for tx in r.json() or []:
                        p = tx.get("feePayer")
                        if not p:
                            continue
                        payers.add(p)
                        if tx.get("signature") in sig30:
                            payers30.add(p)
                except Exception:  # noqa: BLE001
                    break
        # La meme mesure a trente secondes, gratuite : les signatures sont deja la, on les compte
        # deux fois. Elle ne sert a aucune decision aujourd hui -- elle sert a repondre demain a une
        # question qu on ne peut pas trancher avec ce qu on a.
        #
        # La question, posee par l operateur le 08/09/2026 devant BabyQQQ : on achete a T+1,9 min,
        # donc a un prix qui contient deja toute la montee de la premiere minute. Ce jeton avait
        # fait +116 % avant notre entree et on a paye pres du sommet. Juger a trente secondes
        # donnerait un meilleur prix contre moins d information sur la foule ; personne ne sait
        # laquelle des deux l emporte, et une collecte a la minute ne permet pas de le savoir.
        self._demi = (len([g for g in window if (g.get("blockTime") or 0) <= start + 30]), len(payers30))
        return len(window), len(payers)

    async def _decide(self, rpc: str, p: dict[str, Any]) -> bool:
        pid = p["pairAddress"]
        mint = (p.get("baseToken") or {}).get("address")
        symbol = (p.get("baseToken") or {}).get("symbol") or mint[:8]
        if not mint:
            return False
        trades, payers = await self._first_minute(rpc, pid, p["pairCreatedAt"])
        if trades < 0:
            # Mesure incomplete : la remontee n a pas atteint la creation du pool. On ne sait pas ce
            # qui s est passe dans la premiere minute, donc on n achete pas. Voir _first_minute.
            log.info("solana: %s ecarte — premiere minute hors de portee (pool trop actif pour "
                     "etre remonte), aucune mesure fiable", symbol)
            return False
        liq = float((p.get("liquidity") or {}).get("usd") or 0)
        ratio = trades / max(payers, 1)
        self._observe(pid, mint, symbol, p.get("dexId"), trades, payers, liq, float(p.get("priceUsd") or 0) or None)
        min_buyers = int(self._cfg("min_buyers", 0))
        max_ratio = float(self._cfg("max_trades_per_buyer", 0) or 0)
        max_trades = int(self._cfg("max_trades_first_minute", 0) or 0)
        min_liq = float(self._cfg("min_liquidity_usd", 5000))
        # La capitalisation a l entree, hypothese de l operateur le 08/09/2026 devant LAPTOP :
        # un jeton deja gros ne bouge plus assez pour couvrir les frais. Verifie, et nettement --
        # au-dessus de 50 k$ la strategie PERD (-0,074 par euro, 50 % de gagnants), en dessous elle
        # gagne (+0,169, 71 %). Le balayage est monotone : sans plafond la robustesse est negative
        # (-0,005), a 50 k elle passe a +0,042, a 25 k a +0,155. C est la monotonie qui rend le
        # resultat credible, pas le meilleur chiffre du balayage.
        max_mcap = float(self._cfg("max_market_cap_usd", 0) or 0)
        mcap = float(p.get("marketCap") or p.get("fdv") or 0)
        why = None
        if not min_buyers:
            why = "regle non calibree (solana.min_buyers = 0)"
        elif payers < min_buyers:
            why = f"{payers} acheteurs distincts < {min_buyers}"
        elif max_trades and trades >= max_trades:
            # Density has an optimum of its own, and it is NOT the same thing as the buyer floor:
            # at 100 buyers, keeping only the launches under 600 trades in the first minute lifts
            # every measure at once -- 75 % winners against 69, +0.437 per euro against +0.348,
            # median +0.630 against +0.459, and +0.371 against +0.266 once the best tenth is
            # removed. It costs 12 % of the opportunities (1.50/h against 1.70). Measured on the
            # 254 observed launches, 2026-09-08.
            why = f"{trades} echanges dans la minute >= {max_trades} (trop dense)"
        elif max_ratio and ratio > max_ratio:
            why = f"{ratio:.0f} echanges par acheteur > {max_ratio:.0f} (bundle probable)"
        elif liq < min_liq:
            why = f"liquidite {liq:,.0f} $ < {min_liq:,.0f} $"
        elif max_mcap and mcap and mcap >= max_mcap:
            why = f"capitalisation {mcap:,.0f} $ >= {max_mcap:,.0f} $ (trop gros pour bouger)"
        self._jugement(pid, mint, symbol, p, trades, payers, liq, why)
        if why:
            log.info("solana: %s ecarte — %s (%d echanges, %d acheteurs)", symbol, why, trades, payers)
            return False
        now = now_ts()
        # A ticket is worthless if the wallet cannot fund it. Impact is linear and tiny here
        # (0.37 % at 20 EUR, 1.10 % at 50), so size is not the constraint -- the balance is, and
        # nothing checked it: four concurrent tickets already exhaust a 98 EUR wallet.
        # One mint, one line. A sale empties the WALLET, not a line: with two positions open on the
        # same token the first SELL_ALL takes both stakes' tokens, and the second reads a zero
        # balance. That is how RWA and ANSEMCOIN were each paid for twice and sold once on
        # 2026-09-08 -- two stakes out, one credited back.
        seen = self.ctx.db.scalar(
            "SELECT COUNT(*) FROM positions WHERE chain_id=? AND model_version=? AND status='OPEN' "
            "AND lower(token_address)=lower(?)",
            (self.ctx.chain_id, MODEL_VERSION, mint), 0)
        if not seen:
            seen = self.ctx.db.scalar(
                "SELECT COUNT(*) FROM executions WHERE chain_id=? AND model_version=? AND kind='BUY' "
                "AND lower(token_address)=lower(?) AND status IN ('SUBMITTED','CONFIRMED') AND ts>?",
                (self.ctx.chain_id, MODEL_VERSION, mint, now_ts() - 3600), 0)
        if seen:
            log.info("solana: %s passe la regle mais une ligne est deja engagee sur ce jeton", symbol)
            return False
        # Le jeton vient-il de s effondrer ? Le plafond de capitalisation n a ni plancher ni memoire :
        # il laisse passer un jeton a 5 k$ sans pouvoir dire s il est petit ou s il valait 50 k il y a
        # une minute. Deux cas mesures le 08/09/2026, a une heure d intervalle :
        #   NASFROG : cote 6,194e-05 a 20:54 (ecarte, trop dense), achete 2,374e-06 a 21:00 -- 26x
        #             moins cher, apres une chute de 96 %.
        #   WTW     : meme mint 219jMr4PyMdj..., pool 89qz8256 le cote 2,183e-05 et l ecarte (1 139
        #             echanges, +458 %), pool 7WPSkNyM le cote 4,967e-06 onze secondes plus tard et
        #             l achete -- 4,4x moins cher, -88 % sur cinq minutes.
        # Le prix est une propriete du JETON, l activite se mesure par POOL : c est cet ecart qui
        # laisse un mint ecarte revenir par une autre porte. On compare donc le prix propose au
        # meilleur prix vu recemment sur le meme mint, tous pools confondus.
        fenetre = int(self._cfg("collapse_memory_seconds", 900) or 0)
        chute_max = float(self._cfg("max_collapse_ratio", 2.0) or 0)
        prix = float(p.get("priceUsd") or 0)
        if fenetre and chute_max > 1 and prix > 0:
            haut = self.ctx.db.scalar(
                "SELECT MAX(price_usd) FROM solana_judgements WHERE mint=? AND pair_id<>? AND ts>? "
                "AND price_usd IS NOT NULL", (mint, pid, now - fenetre))
            if haut and float(haut) / prix >= chute_max:
                log.info("solana: %s ecarte — vu a %.3e il y a moins de %d min, propose a %.3e "
                         "(%.1fx moins cher) : le jeton s est effondre, on n achete pas la chute",
                         symbol, float(haut), fenetre // 60, prix, float(haut) / prix)
                return False
        # Et la meme question posee au PORTEFEUILLE, qui ne peut pas mentir. Les deux controles
        # ci-dessus lisent le journal, et le journal s est trompe le 08/09/2026 : un refus ecrit
        # par l executeur de l autre chaine a masque un achat parti en chaine, la garde n a rien vu
        # et BIPOLAR a ete paye deux fois, 40 EUR au lieu de 20. Detenir le jeton est un fait ;
        # ce qu on a ecrit a son sujet est une opinion.
        try:
            deja = await sol.token_balance(self.client, rpc, sol.signer_address() or "", mint)
        except Exception as exc:  # noqa: BLE001
            log.info("solana: solde de %s illisible avant achat (%s), achat refuse par prudence",
                     symbol, str(exc)[:60])
            return False
        if deja > 0:
            log.warning("solana: %s passe la regle mais le portefeuille en detient deja %d "
                        "-- le journal ne le disait pas", symbol, deja)
            return False
        max_open = int(self._cfg("max_open_positions", 4))
        n_open = self.ctx.db.scalar(
            "SELECT COUNT(*) FROM positions WHERE chain_id=? AND model_version=? AND status='OPEN'",
            (self.ctx.chain_id, MODEL_VERSION), 0)
        if n_open >= max_open:
            log.info("solana: %s passe la regle mais %d positions sont deja ouvertes (plafond %d)",
                     symbol, n_open, max_open)
            return False
        self.sent_ts = [t for t in self.sent_ts if now - t < 3600]
        # 0 = aucun plafond horaire. Etait a 6, retire le 08/09 : l operateur ne veut aucune limite
        # portant sur le NOMBRE de tickets. Le frein reel reste le portefeuille -- quatre tickets de
        # 20 EUR simultanes epuisent les 98 EUR disponibles (`max_open_positions`).
        par_heure = int(self._cfg("max_per_hour", 10) or 0)
        if par_heure and len(self.sent_ts) >= par_heure:
            log.info("solana: %s passe la regle mais le plafond horaire est atteint", symbol)
            return False
        # Une limite de PERTE, pas un compteur de tickets. Un compteur arrete aussi une serie
        # gagnante et ne protege de rien quand la serie perd vite ; une limite de perte ne coupe
        # que si ca perd vraiment, et laisse courir tant que ca marche. Le `buy_budget` inscrit
        # dans la configuration n a d ailleurs jamais ete lu par ce moteur : il ne protegeait rien.
        perte_max = float(self._cfg("max_daily_loss_eur", 0) or 0)
        if perte_max > 0:
            jour = now - (now % 86400)
            perdu = -float(self.ctx.db.scalar(
                # kind='PORTFOLIO' : la table melange carnet reel et carnet a blanc sous le meme
                # model_version, et un plafond qui compte des pertes fictives se declenche sur de
                # l argent qui n existe pas. Voir §3.27.
                "SELECT COALESCE(SUM(realized_eur), 0) FROM positions WHERE chain_id=? "
                "AND model_version=? AND kind='PORTFOLIO' AND closed_ts>=? AND realized_eur IS NOT NULL",
                (self.ctx.chain_id, MODEL_VERSION, jour), 0.0) or 0.0)
            if perdu >= perte_max:
                if not getattr(self, "_stop_perte", False):
                    self._stop_perte = True
                    log.warning("solana: %.2f EUR perdus aujourd hui, au-dela de la limite de "
                                "%.0f EUR -- plus aucun achat jusqu a demain", perdu, perte_max)
                return False
        self.ctx.db.insert("decisions", {
            "ts": now, "chain_id": self.ctx.chain_id, "token_address": mint, "label": symbol,
            "kind": "BUY", "reason": f"Solana T+1 · {trades} echanges, {payers} acheteurs distincts",
            "price": float(p.get("priceUsd") or 0) or None, "size_eur": float(self._cfg("size_eur", 5.0)),
            "position_id": None, "sent": 0,
            "metrics_json": json.dumps({"pair": pid, "dex": p.get("dexId"), "trades_first_minute": trades,
                                        "uniq_payers": payers, "liquidity_usd": liq, "chain": "solana"}),
            "model_version": MODEL_VERSION,
        })
        self.sent_ts.append(now)
        log.info("solana ACHAT %s · %d echanges, %d acheteurs · %.0f EUR", symbol, trades, payers,
                 float(self._cfg("size_eur", 5.0)))
        return True

    def _observe(self, pid: str, mint: str, symbol: str, dex: str | None, trades: int, payers: int, liq: float, price: float | None = None) -> None:
        """One row per judged launch, bought or not: the series any calibration will be built from."""
        try:
            self.ctx.db.execute(
                "CREATE TABLE IF NOT EXISTS solana_observations("
                "  ts INTEGER NOT NULL, pair_id TEXT PRIMARY KEY, mint TEXT, symbol TEXT, dex TEXT,"
                "  trades_first_minute INTEGER, uniq_payers INTEGER, liquidity_usd REAL)")
            # Les deux colonnes a trente secondes sont ajoutees apres coup : la table existe deja
            # sur les installations en cours, et une migration ratee coute plus cher que deux
            # colonnes manquantes.
            for col in ("trades_30s INTEGER", "uniq_payers_30s INTEGER", "price_usd REAL"):
                try:
                    self.ctx.db.execute(f"ALTER TABLE solana_observations ADD COLUMN {col}")
                except Exception:  # noqa: BLE001
                    pass
            t30, p30 = getattr(self, "_demi", (None, None))
            self.ctx.db.execute(
                "INSERT OR IGNORE INTO solana_observations"
                "(ts, pair_id, mint, symbol, dex, trades_first_minute, uniq_payers, liquidity_usd,"
                " trades_30s, uniq_payers_30s, price_usd) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (now_ts(), pid, mint, symbol, dex, trades, payers, liq, t30, p30, price))
        except Exception as exc:  # noqa: BLE001
            log.info("solana: observation non enregistree (%s)", str(exc)[:80])

    def _jugement(self, pid: str, mint: str, symbol: str, p: dict[str, Any], trades: int, payers: int,
                  liq: float, verdict: str | None) -> None:
        """Une ligne par PASSAGE, verdict compris -- pas une par paire.

        `solana_observations` a une cle primaire sur `pair_id` et un INSERT OR IGNORE : elle garde
        le premier jugement et jette les suivants. C est ce qui a rendu NASFROG illisible le
        08/09/2026 -- la mesure de 20:54 qui l ecartait etait enregistree, celle de 21:00 qui l a
        fait acheter n existait nulle part, et il a fallu recouper le journal texte pour comprendre.
        Cette table-ci ne remplace rien : elle s ajoute, pour que les series de calibration existantes
        continuent de mesurer la meme chose.

        Trois champs nouveaux, tous gratuits (deja dans la reponse DexScreener), tous la pour
        repondre plus tard a une question qu on ne peut pas trancher aujourd hui : le plafond de
        capitalisation ne distingue pas un jeton PETIT d un jeton QUI VIENT DE S EFFONDRER. NASFROG
        est entre a 2,4 k$ de capitalisation apres une chute de 96 % -- tres loin sous le plafond de
        50 k, donc accepte sans reserve. `chg_m5` dit si le prix vient de tomber, `age_s` dit avec
        quel retard on juge. Aucun des deux ne filtre quoi que ce soit aujourd hui : on collecte
        d abord, on tranchera sur des donnees.
        """
        try:
            self.ctx.db.execute(
                "CREATE TABLE IF NOT EXISTS solana_judgements("
                "  id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, pair_id TEXT, mint TEXT,"
                "  symbol TEXT, dex TEXT, trades INTEGER, payers INTEGER, liquidity_usd REAL,"
                "  price_usd REAL, market_cap REAL, chg_m5 REAL, age_s INTEGER, verdict TEXT)")
            created = p.get("pairCreatedAt") or 0
            self.ctx.db.execute(
                "INSERT INTO solana_judgements(ts, pair_id, mint, symbol, dex, trades, payers,"
                " liquidity_usd, price_usd, market_cap, chg_m5, age_s, verdict) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (now_ts(), pid, mint, symbol, p.get("dexId"), trades, payers, liq,
                 float(p.get("priceUsd") or 0) or None,
                 float(p.get("marketCap") or p.get("fdv") or 0) or None,
                 float((p.get("priceChange") or {}).get("m5") or 0) or None,
                 int(now_ts() - created / 1000.0) if created else None,
                 verdict or "achete"))
        except Exception as exc:  # noqa: BLE001
            log.info("solana: jugement non enregistre (%s)", str(exc)[:80])

    # ----------------------------------------------------------------- book
    async def _book(self, rpc: str) -> None:
        """Execute pending Solana decisions, then close positions on the same clock as Robinhood."""
        mode = str(self._cfg("mode", "dry_run"))
        db = self.ctx.db
        sol_eur = await sol.sol_eur(self.client)
        for d in db.query(
                "SELECT d.* FROM decisions d LEFT JOIN executions e ON e.chain_id=d.chain_id AND e.decision_id=d.id "
                "WHERE d.chain_id=? AND d.model_version=? AND e.id IS NULL ORDER BY d.id LIMIT 5",
                (self.ctx.chain_id, MODEL_VERSION)):
            res = await sol.prepare_buy(self.client, mint=d["token_address"], size_eur=float(d["size_eur"] or 5.0),
                                        sol_eur=sol_eur, slippage_pct=float(self._cfg("slippage_pct", 5.0)),
                                        max_impact_pct=float(self._cfg("max_impact_pct", 10.0)))
            tx_b64 = res.pop("tx", None)
            status = res.pop("status")
            route = res.pop("route", None)          # journal only: `executions` has no such column
            row = {"ts": now_ts(), "chain_id": self.ctx.chain_id, "decision_id": d["id"],
                   "token_address": d["token_address"], "label": d["label"], "kind": "BUY",
                   "size_eur": d["size_eur"], "mode": mode, "status": status,
                   "model_version": MODEL_VERSION, **res}
            if status == "BUILT" and mode == "live" and tx_b64:
                try:
                    sig = await sol.send(self.client, rpc, sol.sign(tx_b64))
                    row.update({"status": "SUBMITTED", "tx_hash": sig})
                    log.info("solana ordre envoye %s tx=%s", d["label"], sig[:16])
                except sol.SolanaRefused as exc:
                    row.update({"status": "FAILED", "error": str(exc)[:400]})
                    log.warning("solana ordre non envoye %s : %s", d["label"], str(exc)[:160])
            elif status == "BUILT":
                log.info("solana ordre construit a blanc %s · %s · impact %.2f %%", d["label"],
                         route, float(res.get("slippage_pct") or 0))
            else:
                log.info("solana ordre refuse %s : %s", d["label"], res.get("refused_reason"))
            db.insert("executions", row)

    async def _reconcile(self, rpc: str) -> None:
        """Turn sent orders into confirmed or failed ones, from their receipts.

        Without this a Solana order stays "in flight" for ever: the book would count a purchase
        the chain rejected, and every screen would show a state that stopped being true seconds
        after it was written.
        """
        rows = self.ctx.db.query(
            "SELECT id, ts, tx_hash, kind, token_address, decision_id FROM executions WHERE chain_id=? AND model_version=? "
            "AND status='SUBMITTED' AND tx_hash IS NOT NULL AND ts>?",
            (self.ctx.chain_id, MODEL_VERSION, now_ts() - 6 * 3600))
        for e in rows:
            try:
                r = await self.client.post(rpc, json={"jsonrpc": "2.0", "id": 1, "method": "getSignatureStatuses",
                                                      "params": [[e["tx_hash"]], {"searchTransactionHistory": True}]},
                                           timeout=25)
                st = (((r.json() or {}).get("result") or {}).get("value") or [None])[0]
            except Exception:  # noqa: BLE001
                continue
            if not st or not st.get("confirmationStatus"):
                # A Solana transaction is only valid while its blockhash is, about ninety seconds.
                # Once the network has had four minutes and still shows nothing, it never landed
                # and never will; leaving it SUBMITTED would count a position the wallet does not
                # hold, and hold a slot under the ceiling for ever.
                if now_ts() - int(e["ts"] or 0) > 240:
                    self.ctx.db.execute("UPDATE executions SET status='FAILED', error=? WHERE id=?",
                                        ("jamais confirmee : blockhash expire", e["id"]))
                    log.warning("solana ordre %s jamais confirme, abandonne · tx %s",
                                e["kind"], str(e["tx_hash"])[:14])
                continue                                    # still travelling
            ok = st.get("err") is None
            self.ctx.db.execute("UPDATE executions SET status=?, error=? WHERE id=?",
                                ("CONFIRMED" if ok else "FAILED",
                                 None if ok else str(st.get("err"))[:200], e["id"]))
            log.info("solana ordre %s %s en chaine · tx %s", e["kind"],
                     "confirme" if ok else "REJETE", str(e["tx_hash"])[:14])
            if ok and e["kind"] == "SELL_ALL" and e["token_address"]:
                await self._settle(rpc, e["token_address"])

    async def _settle(self, rpc: str, mint: str) -> None:
        """Price a closed line from the wallet itself: SOL paid on the buy, SOL back on the sale.

        Everything else is an estimate. The quote taken a second before a sale reported +5.05 EUR
        on a line the chain paid +2.54 for, and three lines that did return money were booked at
        zero because the balance had already emptied when they were read. The wallet is the only
        witness that cannot drift.
        """
        db = self.ctx.db
        p = db.query_one(
            "SELECT id, label, opened_ts FROM positions WHERE chain_id=? AND model_version=? "
            "AND lower(token_address)=lower(?) AND status='CLOSED' ORDER BY closed_ts DESC LIMIT 1",
            (self.ctx.chain_id, MODEL_VERSION, mint))
        if p is None:
            return
        owner = sol.signer_address() or ""
        net, has_buy, has_sell = 0.0, False, False
        for r in db.query("SELECT kind, tx_hash FROM executions WHERE chain_id=? AND model_version=? "
                          "AND lower(token_address)=lower(?) AND status='CONFIRMED' AND tx_hash IS NOT NULL "
                          "AND ts>=?", (self.ctx.chain_id, MODEL_VERSION, mint, int(p["opened_ts"]) - 300)):
            d = await sol.sol_delta(self.client, rpc, r["tx_hash"], owner)
            if d is None:
                return                              # incomplete: better no number than a wrong one
            net += d
            has_buy = has_buy or r["kind"] == "BUY"
            has_sell = has_sell or r["kind"] == "SELL_ALL"
        if not (has_buy and has_sell):
            return
        eur = net * await sol.sol_eur(self.client)
        db.execute("UPDATE positions SET realized_eur=? WHERE id=?", (eur, p["id"]))
        log.info("solana ligne soldee sur la chaine · %s · %+.2f EUR", p["label"], eur)

    async def _positions(self, rpc: str, mode: str) -> None:
        """Open a line on a confirmed buy, then close it on the rule: x2, or the holding window.

        Chosen on 235 launches observed over 12 h (intel/research/solana_backtest.py). The holding
        sweep has a clear peak at a quarter of an hour, and it wins on all four counts at once:
        +1.06 EUR per ticket, 61 % winners, near-identical on both halves of the period (+1.08 then
        +1.04), and 80 % of the profit survives removing the five best trades. Past it the decay is
        steady -- +0.64 at an hour, +0.37 at two, robustness down to 42 % -- which says what is left
        to gain out there sits in a few rare trades. Below it, T+5 returns only +0.72.

        The opposite of the other chain, where holding past ten minutes destroyed the book: there
        the liquidity is pulled within minutes, here a bonding curve cannot be withdrawn and the
        price is given time to move.
        """
        db = self.ctx.db
        accepted = ("BUILT",) if mode != "live" else ("SUBMITTED", "CONFIRMED")
        ph = ",".join("?" * len(accepted))
        now = now_ts()
        for r in db.query(
                "SELECT d.id, d.token_address, d.label, d.price, d.size_eur, e.ts ets FROM decisions d "
                "JOIN executions e ON e.chain_id=d.chain_id AND e.decision_id=d.id "
                f"WHERE d.chain_id=? AND d.model_version=? AND d.kind='BUY' AND d.ts>? AND e.status IN ({ph}) "
                "AND NOT EXISTS (SELECT 1 FROM positions p WHERE p.chain_id=d.chain_id AND p.notes LIKE ('sol:' || d.id || ' %'))",
                (self.ctx.chain_id, MODEL_VERSION, now - 6 * 3600, *accepted)):
            db.insert("positions", {
                "chain_id": self.ctx.chain_id, "token_address": r["token_address"], "label": r["label"],
                "kind": "VIRTUAL" if mode != "live" else "PORTFOLIO", "opened_ts": int(r["ets"] or now),
                "entry_price": r["price"], "size_eur": r["size_eur"], "status": "OPEN", "peak_price": r["price"],
                "model_version": MODEL_VERSION, "notes": f"sol:{r['id']} mint:{r['token_address']}",
            })
            log.info("solana position ouverte %s · %.0f EUR", r["label"], float(r["size_eur"] or 0))

        tp = float(self._cfg("take_profit_multiple", 2.0))
        hold = int(self._cfg("max_hold_seconds", 900))
        for p in db.query("SELECT * FROM positions WHERE chain_id=? AND model_version=? AND status='OPEN'",
                          (self.ctx.chain_id, MODEL_VERSION)):
            mint = dict(kv.split(":", 1) for kv in (p["notes"] or "").split() if ":" in kv).get("mint")
            if not mint:
                continue
            age = now_ts() - int(p["opened_ts"])
            amount = 0
            if mode == "live":
                try:
                    amount = await sol.token_balance(self.client, rpc, sol.signer_address() or "", mint)
                except Exception as exc:  # noqa: BLE001
                    log.info("solana: solde de %s illisible (%s), vente reportee", p["label"], str(exc)[:60])
                    continue
                if amount <= 0:
                    # An indexed RPC publishes a brand-new token account seconds after the block
                    # that created it, and reading the balance inside that gap returns zero. The
                    # line used to be written off at zero euros on the spot, while the tokens
                    # landed a moment later and stayed in the wallet -- unmanaged and never sold,
                    # because nothing looks at a CLOSED position again. Dukky, 20 EUR, 2026-09-08.
                    settle = int(self._cfg("settle_seconds", 300))
                    if age < settle:
                        log.info("solana: %s pas encore visible en portefeuille (T+%d s), on attend",
                                 p["label"], age)
                        continue
                    db.execute("UPDATE positions SET status='CLOSED', closed_ts=?, close_reason=?, realized_eur=? WHERE id=?",
                               (now_ts(), "jetons jamais recus", -float(p["size_eur"] or 0), p["id"]))
                    log.warning("solana: %s achete mais aucun jeton recu apres %d s · mise perdue %.2f EUR",
                                p["label"], age, float(p["size_eur"] or 0))
                    continue
            # What the position is worth is what selling it would RETURN, not what a price feed
            # prints. On 2026-09-08 haMSTR read x1.66 from DexScreener while the chain would pay
            # 4.31 EUR on a 5 EUR stake -- a loss shown as a gain, and a take-profit that would
            # have fired on a doubling that never existed. Impact was 0.6 %, so the gap was the
            # entry price: taken from a feed at decision time, not from the trade that happened.
            px = None                       # bound per line: it is written to close_price below
            mult, value = await self._worth(rpc, mint, amount, float(p["size_eur"] or 5.0))
            if mult is None:
                px = await self._price(mint)
                mult = (px / float(p["entry_price"])) if (px and p["entry_price"]) else None
            # Le sommet traverse, garde sous forme de prix pour rester comparable a l entree.
            # Sans lui, impossible de dire ce qu on laisse sur la table : CPU est passee par x1,8
            # le 08/09 et a ete vendue a x1,18 a l echeance, ce que seul l ecran Telegram a vu.
            # C est la mesure qui permettra un jour de trancher la hauteur de l objectif sur du
            # reel plutot que sur un backtest.
            if mult is not None and p["entry_price"]:
                sommet = float(p["entry_price"]) * mult
                if p["peak_price"] is None or sommet > float(p["peak_price"]):
                    db.execute("UPDATE positions SET peak_price=? WHERE id=?", (sommet, p["id"]))
            # Trois sorties, et le stop de perte est celle qui manquait. Le carnet avait un
            # objectif de gain et une limite de temps, mais rien pour couper une position qui
            # tombe : le 08/09/2026, DLSS5 a ete tenue jusqu a l echeance pour x0,11, ZAPE pour
            # x0,04 et FTFS pour x0,01 apres une chute de 99 % en cinq minutes -- verifiee par le
            # routeur ET par DexScreener, avec 1 786 ventes contre 513 achats. Environ 40 EUR
            # perdus sur trois lignes qu un stop a -30 % aurait limitees a 6 EUR chacune.
            # Mesure sur les 47 lancements de reference : a objectif egal, le stop porte le gain
            # par euro de +0,123 a +0,183 et la robustesse de +0,079 a +0,147. C est le seul
            # reglage teste aujourd hui sur lequel le backtest et le reel disent la meme chose.
            stop = float(self._cfg("stop_loss_multiple", 0) or 0)
            touche_stop = stop > 0 and mult is not None and mult <= stop
            if not touche_stop and not (mult is not None and mult >= tp) and age < hold:
                continue
            res = await sol.prepare_sell(self.client, mint=mint, amount=amount or 1,
                                         slippage_pct=float(self._cfg("sell_slippage_pct", 25.0)))
            tx = res.pop("tx", None)
            res.pop("route", None)
            # No decision id on a sale: the journal holds one execution per decision, and the
            # purchase already occupies that pair. The line is found again by its mint, which one
            # position at a time on a token makes unambiguous.
            row = {"ts": now_ts(), "chain_id": self.ctx.chain_id, "token_address": mint, "label": p["label"],
                   "kind": "SELL_ALL", "size_eur": p["size_eur"], "mode": mode, "status": res.pop("status"),
                   "model_version": MODEL_VERSION, **res}
            if row["status"] == "BUILT" and mode == "live" and tx:
                try:
                    row.update({"status": "SUBMITTED", "tx_hash": await sol.send(self.client, rpc, sol.sign(tx))})
                except sol.SolanaRefused as exc:
                    row.update({"status": "FAILED", "error": str(exc)[:400]})
            db.insert("executions", row)
            if row["status"] in ("SUBMITTED", "CONFIRMED") or (mode != "live" and row["status"] == "BUILT"):
                realized = (float(p["size_eur"]) * (mult - 1.0)) if (mult is not None and p["size_eur"]) else None
                db.execute("UPDATE positions SET status='CLOSED', closed_ts=?, close_price=?, close_reason=?, realized_eur=? WHERE id=?",
                           (now_ts(), px, f"vendu x{mult:.2f}" if mult is not None else "vendu", realized, p["id"]))
                # Le sommet est dit a chaque vente : c est ce qu on a laisse passer, et sans le
                # journaliser on ne le sait qu en regardant l ecran au bon moment.
                sommet = None
                if p["entry_price"] and p["peak_price"]:
                    sommet = float(p["peak_price"]) / float(p["entry_price"])
                log.info("solana VENTE %s · %s · %s%s", p["label"],
                         f"x{mult:.2f}" if mult is not None else "multiple inconnu",
                         ("objectif atteint" if (mult is not None and mult >= tp)
                          else ("STOP de perte" if touche_stop else f"T+{age // 60} min")),
                         f" · sommet traverse x{sommet:.2f}" if (sommet and sommet > (mult or 0) * 1.02) else "")

    async def _worth(self, rpc: str, mint: str, amount: int, stake_eur: float) -> tuple[float | None, float | None]:
        """(multiple, euros) the position would actually fetch, asked to the router itself."""
        if amount <= 0 or stake_eur <= 0:
            return None, None
        try:
            r = await sol.prepare_sell(self.client, mint=mint, amount=amount, slippage_pct=25.0)
        except Exception:  # noqa: BLE001
            return None, None
        out = int(r.get("quoted_amount_out") or 0)
        if out <= 0:
            return None, None
        eur = out / 1e9 * await sol.sol_eur(self.client)
        return eur / stake_eur, eur

    async def _price(self, mint: str) -> float | None:
        try:
            r = await self.client.get(PAIRS_URL + mint, timeout=20)
            pairs = (r.json() or {}).get("pairs") or []
            best = max((p for p in pairs if p.get("priceUsd")), key=lambda p: float((p.get("liquidity") or {}).get("usd") or 0), default=None)
            return float(best["priceUsd"]) if best else None
        except Exception:  # noqa: BLE001
            return None

    def _forget(self) -> None:
        cutoff = now_ts() - 6 * 3600
        for pid in [k for k, v in self.judged.items() if v < cutoff]:
            del self.judged[pid]
        # La liste des annonces ne sert qu a ne pas repeter un message ; au-dela de quelques
        # milliers elle ne dit plus rien d utile et n a pas de raison de grossir sans fin.
        if len(self.annonces) > 5000:
            self.annonces.clear()
