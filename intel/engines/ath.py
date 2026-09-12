"""Vendre chaque jeton detenu des qu il touche un nouveau sommet historique.

Demande de l operateur le 11/09 : « parmi toutes les crypto dont on dispose, des qu elles
atteignent un nouveau plus haut historique tu vends », PACK excepte, et « un truc qui check en
continu pour pas rater des occasions comme hier ».

CE QU IL FAUT SAVOIR AVANT DE LIRE LE CODE

  - Le sommet doit etre le VRAI sommet, pas le plus haut vu depuis qu on regarde. Sans amorcage, la
    premiere hausse de 1 % serait un « nouveau sommet » et vendrait tout. On amorce donc une fois
    par jeton depuis l historique journalier complet du pool (GeckoTerminal, gratuit), puis on
    entretient le maximum au fil des releves.
  - On ne peut vendre que ce dont on a la CLE. Les portefeuilles Trust sont ceux de l operateur : on
    y alerte, on n y signe rien. MediTrading et les deux portefeuilles du robot sont signables.
    Confondre les deux, ce serait promettre une vente qui n arrivera jamais -- c est exactement ce
    qui s est passe la nuit du 09 au 10/09 (S5.24).
  - Le prix est la MEDIANE des paires ou le jeton est en BASE. La paire la plus profonde peut
    afficher n importe quoi : le 10/09 HYPE valait 419 741 $ sur sa paire la plus liquide contre
    82,8 $ sur les quatre autres, et l inventaire a annonce 14 089 EUR au lieu de 1 500 (S5.30).
    Sur un declencheur de VENTE, un prix aberrant vendrait la position pour de bon.

CE MODULE VEND POUR DE VRAI la ou la cle existe. Il est gouverne par `ath.enabled`.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

DEX = "https://api.dexscreener.com/latest/dex/tokens/"
GECKO = "https://api.geckoterminal.com/api/v2"
RESEAU = {"solana": "solana", "robinhood": "robinhood"}


class Ath:
    def __init__(self, ctx, client) -> None:
        self.ctx, self.client = ctx, client
        self.sans_pool: set[str] = set()      # jetons sans historique : on n amorce pas en boucle

    def _cfg(self, cle: str, defaut):
        return self.ctx.config.get("ath." + cle, defaut)

    # ---------------------------------------------------------------- le sommet
    def _lu(self, jeton: str) -> tuple[float, int] | None:
        r = self.ctx.db.query_one(
            "SELECT sommet, amorce FROM ath_sommets WHERE lower(jeton)=lower(?)", (jeton,))
        return (float(r["sommet"]), int(r["amorce"] or 0)) if r else None

    def _ecrire(self, jeton: str, sommet: float, amorce: int) -> None:
        from intel.utils.timeutil import now_ts
        self.ctx.db.execute(
            "INSERT INTO ath_sommets(jeton, sommet, amorce, maj_ts) VALUES(?,?,?,?) "
            "ON CONFLICT(jeton) DO UPDATE SET sommet=excluded.sommet, amorce=excluded.amorce, "
            "maj_ts=excluded.maj_ts", (jeton.lower(), sommet, amorce, now_ts()))

    def _sommet_local(self, jeton: str) -> float | None:
        """Le plus haut que NOTRE base a deja vu, en dollars. Dernier recours avant le prix du jour.

        Sans cela, un jeton dont l historique public est indisponible serait amorce au prix du
        jour : la premiere hausse serait un « nouveau sommet » et vendrait la position. DOGSHIT en
        est l exemple -- notre base connait un plus haut a 0,00112 quand le prix du jour est
        0,000245, soit quatre fois moins.
        """
        for table, col, cle in (("token_snapshots", "price_usd", "token_address"),
                                ("solana_suivi_long", "price_usd", "mint")):
            try:
                r = self.ctx.db.query_one(
                    "SELECT MAX(%s) AS h, COUNT(*) AS n FROM %s WHERE lower(%s)=lower(?)"
                    % (col, table, cle), (jeton,))
                if r and r["h"] and int(r["n"] or 0) >= 3:
                    return float(r["h"])
            except Exception:  # noqa: BLE001
                continue
        return None

    async def _amorcer(self, jeton: str, reseau: str) -> float | None:
        """Le vrai sommet, depuis l historique journalier complet du pool le plus profond."""
        if jeton.lower() in self.sans_pool:
            return None
        try:
            r = None
            for essai in range(3):
                r = await self.client.get("%s/networks/%s/tokens/%s/pools" % (GECKO, reseau, jeton),
                                          headers={"accept": "application/json"}, timeout=20)
                if r.status_code != 429:
                    break
                # l API publique limite a une trentaine d appels par minute ; on patiente au lieu
                # d abandonner, sinon les jetons amorces en fin de liste ne le sont jamais
                import asyncio as _a
                await _a.sleep(3 + 3 * essai)
            pools = (r.json() or {}).get("data") or [] if (r and r.status_code == 200) else []
            if not pools:
                if r is not None and r.status_code == 200:
                    self.sans_pool.add(jeton.lower())   # vraiment aucun pool : inutile de reessayer
                return None
            p = max(pools, key=lambda x: float((x.get("attributes") or {}).get("reserve_in_usd") or 0))
            adr = (p.get("attributes") or {}).get("address") or str(p.get("id", "")).split("_")[-1]
            o = await self.client.get("%s/networks/%s/pools/%s/ohlcv/day" % (GECKO, reseau, adr),
                                      params={"limit": 1000}, headers={"accept": "application/json"},
                                      timeout=20)
            if o.status_code != 200:
                return None
            lignes = (((o.json() or {}).get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
            hauts = [float(x[2]) for x in lignes if x and x[2]]
            if not hauts:
                self.sans_pool.add(jeton.lower())
                return None
            return max(hauts)
        except Exception:  # noqa: BLE001
            return None

    # ---------------------------------------------------------------- le prix
    async def _prix(self, jeton: str, chaine: str) -> float | None:
        """La MEDIANE des paires ou le jeton est en base. Voir l en-tete : un prix aberrant vend."""
        try:
            r = await self.client.get(DEX + jeton, timeout=15)
            ps = [x for x in ((r.json() or {}).get("pairs") or [])
                  if x.get("chainId") == chaine and x.get("priceUsd")
                  and ((x.get("baseToken") or {}).get("address") or "").lower() == jeton.lower()]
            if not ps:
                return None
            v = sorted(float(x["priceUsd"]) for x in ps)
            n = len(v)
            return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2
        except Exception:  # noqa: BLE001
            return None

    # ---------------------------------------------------------------- ce qu on detient
    async def _avoirs(self) -> list[dict]:
        """(portefeuille, chaine, jeton, quantite, signable) pour tout ce qui vaut la peine."""
        from intel.execution import solana as sol

        out: list[dict] = []
        rpc_sol, rpc_evm = sol.rpc_url(), getattr(self.ctx.settings, "rpc_url", None)
        cle_manuel = self.ctx.config.get("manuel.cle_fichier", "/app/data/.solana_key_manuel")
        signables = {a.lower() for a in filter(None, (
            sol.signer_address(cle_manuel), sol.signer_address(), self._adresse_evm()))}
        for w in (self.ctx.config.get("manuel.portefeuilles", []) or []):
            adr, chaine = w.get("adresse", ""), w.get("chaine", "solana")
            if not adr:
                continue
            signable = adr.lower() in signables
            try:
                if chaine == "solana" and rpc_sol:
                    for prog in ("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
                                 "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"):
                        r = await self.client.post(rpc_sol, json={
                            "jsonrpc": "2.0", "id": 1, "method": "getTokenAccountsByOwner",
                            "params": [adr, {"programId": prog}, {"encoding": "jsonParsed"}]}, timeout=25)
                        for x in ((r.json() or {}).get("result") or {}).get("value", []):
                            i = x["account"]["data"]["parsed"]["info"]
                            q = float(i["tokenAmount"]["uiAmount"] or 0)
                            if q > 0:
                                out.append(dict(portefeuille=w.get("nom", "?"), adresse=adr, chaine="solana",
                                                jeton=i["mint"], quantite=q, signable=signable))
                elif chaine == "robinhood" and rpc_evm:
                    d = await self.ctx.blockscout.get_v2(
                        "addresses/%s/token-balances" % adr, essential=True)
                    for x in (d or []):
                        t = x.get("token") or {}
                        dec = int(t.get("decimals") or 18)
                        q = int(x.get("value") or 0) / (10 ** dec)
                        j = t.get("address_hash") or ""
                        if q > 0 and j:
                            out.append(dict(portefeuille=w.get("nom", "?"), adresse=adr, chaine="robinhood",
                                            jeton=j, quantite=q, signable=signable,
                                            symbole=t.get("symbol") or j[:6]))
            except Exception as exc:  # noqa: BLE001
                log.info("ath: %s illisible (%s)", w.get("nom"), str(exc)[:60])
        return out

    def _adresse_evm(self) -> str | None:
        try:
            from intel.execution.signer import signer_address
            return signer_address()
        except Exception:  # noqa: BLE001
            return None

    # ---------------------------------------------------------------- vendre
    async def _vendre(self, avoir: dict, prix: float, sommet: float) -> str:
        from intel.utils.timeutil import now_ts

        sym = avoir.get("symbole") or avoir["jeton"][:8]
        valeur = avoir["quantite"] * prix / 1.08
        if avoir["chaine"] == "robinhood":
            # On ecrit une DECISION ; l executeur la ramasse a son cycle et la dimensionne sur le
            # solde reel du portefeuille. On ne signe pas ici : un seul chemin de signature EVM.
            self.ctx.db.insert("decisions", {
                "ts": now_ts(), "chain_id": self.ctx.chain_id, "token_address": avoir["jeton"],
                "label": sym, "kind": "SELL_ALL",
                "reason": "nouveau sommet historique : %.9g > %.9g" % (prix, sommet),
                "price": prix, "size_eur": round(valeur, 2), "position_id": None, "sent": 0,
                "model_version": "manuel-evm-v1"})
            return "ordre de vente ecrit, l executeur l envoie"
        from intel.execution import solana as sol
        rpc = sol.rpc_url()
        cle_manuel = self.ctx.config.get("manuel.cle_fichier", "/app/data/.solana_key_manuel")
        cle = cle_manuel if (sol.signer_address(cle_manuel) or "").lower() == avoir["adresse"].lower() else None
        proprio = sol.signer_address(cle)
        solde = await sol.token_balance(self.client, rpc, proprio, avoir["jeton"])
        if solde <= 0:
            return "solde nul, rien envoye"
        r = await sol.prepare_sell(self.client, mint=avoir["jeton"], amount=solde,
                                   slippage_pct=float(self.ctx.config.get("solana.sell_slippage_pct", 25.0)),
                                   proprietaire=proprio,
                                   priorite_lamports=int(self.ctx.config.get("solana.priority_fee_lamports", 0) or 0))
        if r.get("status") != "BUILT" or not r.get("tx"):
            return "vente refusee : %s" % (r.get("refused_reason") or "transaction non assemblee")
        h = await sol.send(self.client, rpc, sol.sign(r["tx"], cle))
        self.ctx.db.insert("executions", {
            "ts": now_ts(), "chain_id": self.ctx.chain_id, "decision_id": None,
            "token_address": avoir["jeton"], "label": sym, "kind": "SELL_ALL",
            "size_eur": round(valeur, 2), "amount_in": str(solde),
            "quoted_amount_out": r.get("quoted_amount_out"), "mode": "live",
            "status": "SUBMITTED", "tx_hash": h, "model_version": "manuel-sol-v1"})
        return "vendu, tx %s" % h[:20]

    async def _prevenir(self, texte: str) -> None:
        from intel.alerts.telegram import TelegramSender
        try:
            await TelegramSender(self.ctx.settings).send(texte)
        except Exception as exc:  # noqa: BLE001
            log.info("ath: alerte non envoyee (%s)", str(exc)[:80])

    # ---------------------------------------------------------------- la boucle
    async def cycle(self) -> dict[str, Any]:
        if not bool(self._cfg("enabled", False)):
            return {"status": "disabled"}
        self.ctx.db.execute(
            "CREATE TABLE IF NOT EXISTS ath_sommets(jeton TEXT PRIMARY KEY, sommet REAL,"
            " amorce INTEGER DEFAULT 0, maj_ts INTEGER)")
        exclus = {str(x).lower() for x in (self._cfg("exclus", []) or [])}
        mini = float(self._cfg("min_eur", 5.0) or 0)
        marge = float(self._cfg("marge_pct", 0.0) or 0) / 100.0

        avoirs = await self._avoirs()
        suivis = vendus = alertes = 0
        for a in avoirs:
            if a["jeton"].lower() in exclus:
                continue
            prix = await self._prix(a["jeton"], a["chaine"])
            if not prix:
                continue
            valeur = a["quantite"] * prix / 1.08
            if valeur < mini:
                continue
            suivis += 1
            connu = self._lu(a["jeton"])
            if connu is None or not connu[1]:
                # jamais amorce : on va chercher le vrai sommet une seule fois
                vrai = await self._amorcer(a["jeton"], RESEAU.get(a["chaine"], a["chaine"]))
                local = None if vrai else self._sommet_local(a["jeton"])
                base = max(vrai or 0.0, local or 0.0, prix, (connu[0] if connu else 0.0))
                # TOUJOURS marque comme amorce. La premiere version ne l ecrivait que si l historique
                # public repondait : les trois jetons dont on a la cle -- ceux qu on peut vendre --
                # se re-amorcaient a chaque passe et n atteignaient donc JAMAIS la comparaison. La
                # regle n aurait jamais vendu, et rien dans le journal ne l aurait dit (S5.31).
                self._ecrire(a["jeton"], base, 1)
                d_ou = ("historique du pool" if vrai else
                        ("notre base" if local else "PRIX DU JOUR, sommet inconnu"))
                log.info("ath: %s amorce a %.9g (%s)", a.get("symbole") or a["jeton"][:8], base, d_ou)
                if not vrai and not local:
                    await self._prevenir(
                        "⚠️ <b>%s</b> suivi sans sommet connu : je prends le prix du jour (%.9g) "
                        "comme reference. La premiere hausse declenchera la vente."
                        % (a.get("symbole") or a["jeton"][:8], base))
                continue
            sommet = connu[0]
            if prix <= sommet * (1 + marge):
                if prix > sommet:
                    self._ecrire(a["jeton"], prix, 1)
                continue
            # NOUVEAU SOMMET
            self._ecrire(a["jeton"], prix, 1)
            sym = a.get("symbole") or a["jeton"][:8]
            if a["signable"]:
                res = await self._vendre(a, prix, sommet)
                vendus += 1
                log.info("ath: %s NOUVEAU SOMMET %.9g > %.9g — %s", sym, prix, sommet, res)
                await self._prevenir(
                    "🔔 <b>%s</b> a fait un NOUVEAU SOMMET\n"
                    "prix %.9g (ancien sommet %.9g)\n"
                    "valeur %.2f EUR · %s\n<i>%s</i>" % (sym, prix, sommet, valeur, a["portefeuille"], res))
            else:
                alertes += 1
                log.info("ath: %s NOUVEAU SOMMET %.9g > %.9g — alerte seule (%s)", sym, prix, sommet, a["portefeuille"])
                await self._prevenir(
                    "🔔 <b>%s</b> a fait un NOUVEAU SOMMET\n"
                    "prix %.9g (ancien sommet %.9g)\n"
                    "valeur %.2f EUR sur <b>%s</b>\n"
                    "<i>Je n ai pas la cle de ce portefeuille : a vendre a la main.</i>"
                    % (sym, prix, sommet, valeur, a["portefeuille"]))
        return {"status": "ok", "avoirs": len(avoirs), "suivis": suivis,
                "vendus": vendus, "alertes": alertes}
