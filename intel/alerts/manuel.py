"""Acheter et vendre a la main depuis Telegram, sur les deux chaines.

Demande de l operateur le 09/09 : ecrire l adresse d un jeton et un montant, laisser le code
reconnaitre s il s agit de Solana ou d une chaine EVM, executer, et disposer de commandes pour
suivre ce qui est achete, ce qui est vendu, et le resultat.

Ce module ne touche PAS aux carnets automatiques. Les lignes manuelles portent leur propre
`model_version` (`manuel-sol-v1`, `manuel-evm-v1`), donc :
  - elles n entrent dans aucune mesure de strategie, aucun rejeu, aucun plafond de pertes du bot ;
  - le bot ne les vend jamais : une ligne manuelle se ferme a la main, c est le principe ;
  - le resultat manuel se lit separement de celui des robots, ce qui evite de melanger deux
    performances qui n ont rien a voir.

Reconnaissance de la chaine, sans configuration :
  - une adresse `0x` suivie de 40 caracteres hexadecimaux est une adresse EVM ;
  - une adresse base58 de 32 a 44 caracteres est un mint Solana.
Aucune autre forme n est acceptee -- il vaut mieux refuser que se tromper de chaine avec de
l argent reel.

Garde-fous, parce qu un message Telegram declenche ici une depense reelle :
  - un plafond par ordre (`manuel.max_ordre_eur`, 100 EUR par defaut) ;
  - le montant, le jeton et la chaine sont repetes dans la reponse avant tout le reste, pour qu une
    erreur de frappe se voie immediatement ;
  - la vente se fait sur le solde REEL lu en chaine, jamais sur ce que le livre croit detenir --
    c est la lecon de §5.1 et elle vaut autant a la main qu automatiquement.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from intel.context import IntelContext
from intel.utils.timeutil import now_ts

log = logging.getLogger(__name__)

EVM = re.compile(r"^0x[0-9a-fA-F]{40}$")
SOL = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
MV_SOL = "manuel-sol-v1"
MV_EVM = "manuel-evm-v1"


def chaine(adresse: str) -> str | None:
    """'evm', 'sol', ou None quand la forme n est reconnue ni par l une ni par l autre."""
    a = adresse.strip()
    if EVM.match(a):
        return "evm"
    if SOL.match(a) and not a.startswith("0x"):
        return "sol"
    return None


class Manuel:
    def __init__(self, ctx: IntelContext, client: Any) -> None:
        self.ctx = ctx
        self.client = client

    def _cfg(self, cle: str, defaut: Any) -> Any:
        return self.ctx.config.get(f"manuel.{cle}", defaut)

    # ------------------------------------------------------------------ achat
    async def acheter(self, arg: str) -> str:
        parts = arg.split()
        if len(parts) < 2:
            return ("Usage : <code>/achat &lt;adresse&gt; &lt;montant en euros&gt;</code>\n"
                    "La chaine est reconnue seule d apres la forme de l adresse.")
        adresse, montant_txt = parts[0], parts[1].replace(",", ".").replace("€", "").replace("$", "")
        try:
            montant = float(montant_txt)
        except ValueError:
            return f"Montant illisible : <code>{montant_txt}</code>"
        ch = chaine(adresse)
        if ch is None:
            return (f"Adresse non reconnue : <code>{adresse[:24]}</code>\n"
                    "Attendu : <code>0x…</code> (40 caracteres) pour EVM, ou une adresse base58 "
                    "de 32 a 44 caracteres pour Solana. Rien n a ete envoye.")
        plafond = float(self._cfg("max_ordre_eur", 100.0))
        if montant <= 0 or montant > plafond:
            return (f"Montant refuse : {montant:.2f} EUR. Le plafond par ordre est de "
                    f"{plafond:.0f} EUR (<code>manuel.max_ordre_eur</code>). Rien n a ete envoye.")
        if ch == "sol":
            return await self._acheter_sol(adresse, montant)
        return self._acheter_evm(adresse, montant)

    async def _acheter_sol(self, mint: str, eur: float) -> str:
        from intel.execution import solana as sol

        rpc = sol.rpc_url()
        if not rpc:
            return "Solana indisponible : aucun point d acces configure."
        if str(self.ctx.config.get("solana.mode", "dry_run")) != "live":
            return "Solana est en mode a blanc (<code>solana.mode</code>) : rien n est envoye."
        try:
            taux = await sol.sol_eur(self.client)
            res = await sol.prepare_buy(
                self.client, mint=mint, size_eur=eur, sol_eur=taux,
                slippage_pct=float(self.ctx.config.get("solana.slippage_pct", 15.0)),
                max_impact_pct=float(self.ctx.config.get("solana.max_impact_pct", 6.0)),
                priorite_lamports=int(self.ctx.config.get("solana.priority_fee_lamports", 0) or 0),
                max_aller_retour_pct=float(self._cfg("max_aller_retour_pct", 0) or 0))
        except Exception as exc:  # noqa: BLE001
            return f"Cotation refusee : {str(exc)[:140]}"
        if res.get("status") == "REFUSED":
            return f"Achat refuse : {res.get('refused_reason')}"
        tx_b64 = res.pop("tx", None)
        if not tx_b64:
            return f"Transaction non assemblee : {res.get('refused_reason') or 'aucune cle'}"
        try:
            signee = sol.sign(tx_b64)
            h = await sol.send(self.client, rpc, signee)
        except Exception as exc:  # noqa: BLE001
            return f"Envoi refuse : {str(exc)[:140]}"
        did = self.ctx.db.insert("decisions", {
            "ts": now_ts(), "chain_id": self.ctx.chain_id, "token_address": mint, "label": mint[:10],
            "kind": "BUY", "reason": "achat manuel Telegram", "price": None, "size_eur": eur,
            "position_id": None, "sent": 1, "model_version": MV_SOL})
        self.ctx.db.insert("executions", {
            "ts": now_ts(), "chain_id": self.ctx.chain_id, "decision_id": did, "token_address": mint,
            "label": mint[:10], "kind": "BUY", "size_eur": eur, "amount_in": res.get("amount_in"),
            "quoted_amount_out": res.get("quoted_amount_out"), "slippage_pct": res.get("slippage_pct"),
            "mode": "live", "status": "SUBMITTED", "tx_hash": h, "model_version": MV_SOL})
        self.ctx.db.insert("positions", {
            "chain_id": self.ctx.chain_id, "token_address": mint, "label": mint[:10],
            "kind": "PORTFOLIO", "opened_ts": now_ts(), "entry_price": None, "size_eur": eur,
            "status": "OPEN", "peak_price": None, "model_version": MV_SOL,
            "notes": f"manuel:{did} mint:{mint}"})
        return (f"<b>Achat Solana envoye</b>\n"
                f"jeton   <code>{mint}</code>\n"
                f"montant {eur:.2f} EUR ({eur / taux:.4f} SOL)\n"
                f"impact  {float(res.get('slippage_pct') or 0):.2f} %\n"
                f"tx      <code>{h[:32]}</code>\n\n"
                f"<i>Le bot ne vendra pas cette ligne. /vente pour sortir, /manuel pour suivre.</i>")

    def _acheter_evm(self, token: str, eur: float) -> str:
        """Sur EVM on ECRIT la decision : l executeur existant la prend au cycle suivant.

        Il porte deja la cotation, les plafonds absolus, la signature, le recu et la reconciliation ;
        les refaire ici serait dupliquer la partie du code ou une erreur coute le plus cher.
        """
        if str(self.ctx.config.get("execution.mode", "dry_run")) != "live":
            return "L execution EVM est en mode a blanc (<code>execution.mode</code>) : rien n est envoye."
        did = self.ctx.db.insert("decisions", {
            "ts": now_ts(), "chain_id": self.ctx.chain_id, "token_address": token.lower(),
            "label": token[:10], "kind": "BUY", "reason": "achat manuel Telegram", "price": None,
            "size_eur": eur, "position_id": None, "sent": 0, "model_version": MV_EVM})
        return (f"<b>Achat EVM en file</b>\n"
                f"jeton   <code>{token}</code>\n"
                f"montant {eur:.2f} EUR\n"
                f"decision <code>{did}</code>\n\n"
                f"<i>L executeur le prend au prochain cycle (quelques secondes) : il cote, verifie "
                f"la profondeur et signe. /orders pour voir le resultat.</i>")

    # ------------------------------------------------------------------ vente
    async def vendre(self, arg: str) -> str:
        parts = arg.split()
        if not parts:
            return "Usage : <code>/vente &lt;adresse&gt; [pourcentage]</code> — 100 % par defaut."
        adresse = parts[0]
        pct = 100.0
        if len(parts) > 1:
            try:
                pct = float(parts[1].replace("%", "").replace(",", "."))
            except ValueError:
                return f"Pourcentage illisible : <code>{parts[1]}</code>"
        if not 0 < pct <= 100:
            return "Le pourcentage doit etre entre 0 et 100."
        ch = chaine(adresse)
        if ch is None:
            return f"Adresse non reconnue : <code>{adresse[:24]}</code>. Rien n a ete envoye."
        if ch != "sol":
            return ("La vente EVM passe par le carnet automatique et n est pas encore exposee ici. "
                    "Utiliser /positions pour voir la ligne.")
        from intel.execution import solana as sol

        rpc = sol.rpc_url()
        proprio = sol.signer_address()
        if not rpc or not proprio:
            return "Solana indisponible : point d acces ou cle absent."
        # Le solde REEL, jamais ce que le livre croit detenir (§5.1).
        try:
            solde = await sol.token_balance(self.client, rpc, proprio, adresse)
        except Exception as exc:  # noqa: BLE001
            return f"Solde illisible : {str(exc)[:120]}. Rien n a ete vendu."
        if solde <= 0:
            return "Le portefeuille ne detient pas ce jeton. Rien n a ete vendu."
        montant = int(solde * pct / 100)
        try:
            res = await sol.prepare_sell(
                self.client, mint=adresse, amount=montant,
                slippage_pct=float(self.ctx.config.get("solana.sell_slippage_pct", 25.0)),
                priorite_lamports=int(self.ctx.config.get("solana.priority_fee_lamports", 0) or 0))
        except Exception as exc:  # noqa: BLE001
            return f"Cotation refusee : {str(exc)[:140]}"
        if res.get("status") == "REFUSED":
            return f"Vente refusee : {res.get('refused_reason')}"
        tx_b64 = res.pop("tx", None)
        if not tx_b64:
            return "Transaction non assemblee (aucune cle ?)."
        try:
            h = await sol.send(self.client, rpc, sol.sign(tx_b64))
        except Exception as exc:  # noqa: BLE001
            return f"Envoi refuse : {str(exc)[:140]}"
        self.ctx.db.insert("executions", {
            "ts": now_ts(), "chain_id": self.ctx.chain_id, "decision_id": None,
            "token_address": adresse, "label": adresse[:10], "kind": "SELL_ALL", "size_eur": None,
            "amount_in": str(montant), "quoted_amount_out": res.get("quoted_amount_out"),
            "slippage_pct": res.get("slippage_pct"), "mode": "live", "status": "SUBMITTED",
            "tx_hash": h, "model_version": MV_SOL})
        if pct >= 100:
            self.ctx.db.execute(
                "UPDATE positions SET status='CLOSED', closed_ts=?, close_reason='vendu a la main' "
                "WHERE chain_id=? AND model_version=? AND status='OPEN' AND lower(token_address)=lower(?)",
                (now_ts(), self.ctx.chain_id, MV_SOL, adresse))
        return (f"<b>Vente Solana envoyee</b>\n"
                f"jeton  <code>{adresse}</code>\n"
                f"part   {pct:.0f} % ({montant} unites)\n"
                f"tx     <code>{h[:32]}</code>\n\n"
                f"<i>Le montant reellement recu se lit en chaine : /manuel dans une minute.</i>")

    # ------------------------------------------------------------------ suivi
    def suivi(self) -> str:
        """Ce qui est ouvert, ce qui est ferme, et le resultat -- lignes manuelles seulement."""
        ouvertes = self.ctx.db.query(
            "SELECT * FROM positions WHERE chain_id=? AND model_version LIKE 'manuel-%' "
            "AND status='OPEN' ORDER BY opened_ts DESC", (self.ctx.chain_id,))
        fermees = self.ctx.db.query(
            "SELECT * FROM positions WHERE chain_id=? AND model_version LIKE 'manuel-%' "
            "AND status='CLOSED' ORDER BY closed_ts DESC LIMIT 10", (self.ctx.chain_id,))
        lignes = ["<b>Positions manuelles</b>", ""]
        if ouvertes:
            lignes.append("<b>Ouvertes</b>")
            for p in ouvertes:
                ch = "SOL" if str(p["model_version"]).startswith("manuel-sol") else "EVM"
                age = (now_ts() - int(p["opened_ts"])) // 60
                lignes.append(f"<code>{(p['label'] or '')[:12]:<13}</code>{ch} · {float(p['size_eur'] or 0):.0f} EUR "
                              f"· {age} min\n  <code>{p['token_address']}</code>")
        else:
            lignes.append("<i>aucune position ouverte</i>")
        if fermees:
            lignes += ["", "<b>Dernieres fermees</b>"]
            for p in fermees:
                r = p["realized_eur"]
                lignes.append(f"<code>{(p['label'] or '')[:12]:<13}</code>"
                              f"{(p['close_reason'] or '')[:22]:<24}"
                              f"{('%+.2f EUR' % r) if r is not None else 'reglement en cours'}")
        tot = self.ctx.db.scalar(
            "SELECT COALESCE(SUM(realized_eur), 0) FROM positions WHERE chain_id=? "
            "AND model_version LIKE 'manuel-%' AND realized_eur IS NOT NULL", (self.ctx.chain_id,), 0.0)
        mise = self.ctx.db.scalar(
            "SELECT COALESCE(SUM(size_eur), 0) FROM positions WHERE chain_id=? "
            "AND model_version LIKE 'manuel-%' AND status='CLOSED'", (self.ctx.chain_id,), 0.0)
        lignes += ["", f"<b>Resultat manuel</b> {float(tot):+.2f} EUR"
                       + (f" sur {float(mise):.0f} EUR engages ({float(tot) / float(mise):+.1%})" if mise else "")]
        lignes.append("<i>Lu sur la chaine, jamais sur une cotation.</i>")
        return "\n".join(lignes)
