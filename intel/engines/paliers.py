"""Vendre une ligne par tranches, a des multiples du prix d entree.

Demande de l operateur le 11/09 : sur STOCKLANA seulement, « tu vends 75 % a x3 et le reste a x4 »,
« tu verifies toutes les 5 s ». Il remplace la regle du plus haut historique (`ath`), coupee.

CE QUI REND CE MODULE DIFFERENT DU RESTE

  - Le multiple se mesure sur le PRIX DE SORTIE REEL, pas sur un prix affiche. On demande au routeur
    ce qu il donne pour la tranche qu on s apprete a vendre ; le rapport « SOL recu / jetons vendus »
    inclut donc l impact de notre propre ordre. x3 veut dire qu on encaisse vraiment trois fois la
    mise par jeton, pas qu un ecran affiche x3 -- toute la difference entre annoncer et recevoir
    (S5.1). DexScreener ne sert a rien ici : il se rafraichit toutes les 30 a 60 s (S3.61), donc
    verifier a 5 s sur sa cotation reviendrait a relire douze fois la meme valeur perimee.
  - Chaque tranche ne part QU UNE FOIS, et le fait est ecrit avant l envoi. Un ordre passe deux fois
    vend deux fois.
  - La part se calcule sur le solde REEL au moment de vendre, jamais sur ce que le livre croit
    detenir (S5.1).

CE MODULE VEND POUR DE VRAI. Il ne touche que les jetons nommes dans `paliers_vente.lignes`, et
seulement sur un portefeuille dont on a la cle.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


class Paliers:
    def __init__(self, ctx, client) -> None:
        self.ctx, self.client = ctx, client

    def _cfg(self, cle: str, defaut):
        return self.ctx.config.get("paliers_vente." + cle, defaut)

    def _faits(self, jeton: str) -> set[float]:
        try:
            rows = self.ctx.db.query(
                "SELECT multiple FROM paliers_faits WHERE lower(jeton)=lower(?)", (jeton,))
            return {float(r["multiple"]) for r in rows}
        except Exception:  # noqa: BLE001
            return set()

    def _marquer(self, jeton: str, multiple: float, note: str) -> None:
        from intel.utils.timeutil import now_ts
        self.ctx.db.execute(
            "INSERT OR IGNORE INTO paliers_faits(jeton, multiple, ts, note) VALUES(?,?,?,?)",
            (jeton.lower(), float(multiple), now_ts(), note[:200]))

    async def _prevenir(self, texte: str) -> None:
        from intel.alerts.telegram import TelegramSender
        try:
            await TelegramSender(self.ctx.settings).send(texte)
        except Exception as exc:  # noqa: BLE001
            log.info("paliers: alerte non envoyee (%s)", str(exc)[:80])

    async def cycle(self) -> dict[str, Any]:
        if not bool(self._cfg("enabled", False)):
            return {"status": "disabled"}
        self.ctx.db.execute(
            "CREATE TABLE IF NOT EXISTS paliers_faits(jeton TEXT NOT NULL, multiple REAL NOT NULL,"
            " ts INTEGER, note TEXT, PRIMARY KEY(jeton, multiple))")
        from intel.execution import solana as sol

        rpc = sol.rpc_url()
        if not rpc:
            return {"status": "pas de rpc"}
        cle_manuel = self.ctx.config.get("manuel.cle_fichier", "/app/data/.solana_key_manuel")
        suivis = vendus = 0
        for ligne in (self._cfg("lignes", []) or []):
            jeton = ligne.get("jeton")
            entree = float(ligne.get("entree_sol_par_jeton") or 0)
            tranches = sorted((ligne.get("tranches") or []), key=lambda t: float(t.get("multiple", 0)))
            if not jeton or entree <= 0 or not tranches:
                continue
            faits = self._faits(jeton)
            restantes = [t for t in tranches if float(t["multiple"]) not in faits]
            if not restantes:
                continue
            suivis += 1
            # la cle du portefeuille qui detient : on cherche, on ne suppose pas
            solde, proprio, cle = 0, None, None
            for f in (cle_manuel, None):
                a = sol.signer_address(f)
                if not a:
                    continue
                try:
                    b = await sol.token_balance(self.client, rpc, a, jeton)
                except Exception:  # noqa: BLE001
                    continue
                if b > solde:
                    solde, proprio, cle = b, a, f
            if solde <= 0 or not proprio:
                continue

            t = restantes[0]
            mult = float(t["multiple"])
            part = float(t.get("part_pct", 100)) / 100.0
            derniere = (t is tranches[-1]) or part >= 1.0
            montant = solde if derniere else int(solde * part)
            if montant <= 0:
                continue
            try:
                q = await sol.quote(self.client, input_mint=jeton, output_mint=sol.SOL_MINT,
                                    amount=montant,
                                    slippage_bps=int(float(self.ctx.config.get("solana.sell_slippage_pct", 25.0)) * 100))
            except Exception as exc:  # noqa: BLE001
                log.info("paliers: cotation refusee pour %s (%s)", jeton[:10], str(exc)[:60])
                continue
            if not q.usable:
                continue
            # le multiple REELLEMENT encaissable, impact de notre ordre compris
            par_jeton = (q.out_amount / 1e9) / (montant / (10 ** int(ligne.get("decimales", 6))))
            atteint = par_jeton / entree
            if atteint < mult:
                continue

            # LE PALIER EST ATTEINT. On le marque AVANT d envoyer : un envoi qui reussit mais dont
            # la trace se perd ferait revendre la meme tranche au cycle suivant.
            self._marquer(jeton, mult, "atteint x%.2f, envoi en cours" % atteint)
            try:
                tx = await sol.prepare_sell(
                    self.client, mint=jeton, amount=montant,
                    slippage_pct=float(self.ctx.config.get("solana.sell_slippage_pct", 25.0)),
                    proprietaire=proprio,
                    priorite_lamports=int(self.ctx.config.get("solana.priority_fee_lamports", 0) or 0))
                if tx.get("status") != "BUILT" or not tx.get("tx"):
                    raise RuntimeError(tx.get("refused_reason") or "transaction non assemblee")
                h = await sol.send(self.client, rpc, sol.sign(tx["tx"], cle))
            except Exception as exc:  # noqa: BLE001
                log.warning("paliers: %s x%.2f atteint mais VENTE ECHOUEE : %s", jeton[:10], mult, str(exc)[:120])
                await self._prevenir(
                    "⚠️ <b>%s</b> a atteint <b>x%.2f</b> mais la vente a echoue\n<code>%s</code>\n"
                    "<i>A vendre a la main.</i>" % (ligne.get("nom") or jeton[:10], atteint, str(exc)[:120]))
                continue
            from intel.utils.timeutil import now_ts
            self.ctx.db.insert("executions", {
                "ts": now_ts(), "chain_id": self.ctx.chain_id, "decision_id": None,
                "token_address": jeton, "label": ligne.get("nom") or jeton[:10],
                "kind": "SELL_ALL" if derniere else "SELL_HALF",
                "size_eur": None, "amount_in": str(montant),
                "quoted_amount_out": str(q.out_amount), "mode": "live", "status": "SUBMITTED",
                "tx_hash": h, "model_version": "manuel-sol-v1"})
            vendus += 1
            log.info("paliers: %s x%.2f atteint (cible x%.2f) — %d%% vendus, tx %s",
                     ligne.get("nom") or jeton[:10], atteint, mult, int(100 * (1 if derniere else part)), h[:20])
            await self._prevenir(
                "💰 <b>%s</b> a atteint <b>x%.2f</b> (cible x%.2f)\n"
                "%d %% vendus · %.4f SOL encaisses\n<code>%s</code>\n"
                "<i>Lu sur la chaine : /manuel dans une minute.</i>"
                % (ligne.get("nom") or jeton[:10], atteint, mult,
                   int(100 * (1 if derniere else part)), q.out_amount / 1e9, h[:32]))
        return {"status": "ok", "suivis": suivis, "vendus": vendus}
