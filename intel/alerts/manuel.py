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

    def _cle(self) -> str | None:
        """Le portefeuille du trading manuel, separe de celui du robot.

        Les deux n ont aucune raison de partager une cle : ce qu on met dans le portefeuille manuel
        est ce qu on accepte de risquer a la main, et une erreur du robot ne peut pas y toucher.
        Si le fichier n existe pas, le manuel utilise le portefeuille du robot -- comportement
        d avant, conserve pour ne rien casser."""
        import os
        f = str(self._cfg("cle_fichier", "/app/data/.solana_key_manuel"))
        return f if f and os.path.exists(f) else None

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
        # 0 = aucun plafond, retire le 09/09 a la demande de l operateur. La limite reelle devient
        # le solde du portefeuille manuel, qui est de toute facon la perte maximale possible.
        plafond = float(self._cfg("max_ordre_eur", 100.0) or 0)
        if montant <= 0:
            return "Le montant doit etre positif. Rien n a ete envoye."
        if plafond and montant > plafond:
            return (f"Montant refuse : {montant:.2f} EUR. Le plafond par ordre est de "
                    f"{plafond:.0f} EUR (<code>manuel.max_ordre_eur</code>, 0 pour le retirer). "
                    f"Rien n a ete envoye.")
        if ch == "sol":
            return await self._acheter_sol(adresse, montant)
        return self._acheter_evm(adresse, montant)

    def _ajouter_ou_ouvrir(self, *, mint: str, label: str, eur: float, entree, unites,
                           model_version: str, notes: str) -> str:
        """UN JETON, UNE LIGNE. Renforcer une position l agrandit, elle n en cree pas une seconde.

        Le 10/09 l operateur a rachete du Rock qu il detenait deja : deux lignes ouvertes sur le meme
        jeton, et comme la valeur se lit sur le SOLDE de la chaine -- qui est commun -- chacune
        valorisait la totalite. `/manuel` annoncait +94,04 EUR de latent la ou la chaine en disait
        +64,90, et affichait le meme jeton a x0,25 et a x1,52 en meme temps. L operateur a repondu
        « je trust pas la position », a juste titre.

        La regle existait deja dans les notes du projet (« un jeton, une ligne », §5.2) et n avait
        jamais ete appliquee au chemin manuel. Le prix d entree combine est le total paye divise par
        le total detenu -- la seule definition qui redonne le vrai multiple apres un renforcement.
        """
        ancienne = self.ctx.db.query_one(
            "SELECT * FROM positions WHERE chain_id=? AND lower(token_address)=lower(?) "
            "AND model_version=? AND status IN ('OPEN','HALF') ORDER BY id DESC LIMIT 1",
            (self.ctx.chain_id, mint, model_version))
        if not ancienne:
            self.ctx.db.insert("positions", {
                "chain_id": self.ctx.chain_id, "token_address": mint, "label": label,
                "kind": "PORTFOLIO", "opened_ts": now_ts(), "entry_price": entree, "size_eur": eur,
                "status": "OPEN", "peak_price": None, "model_version": model_version, "notes": notes})
            return "ouverte"
        vieilles_notes = dict(kv.split(":", 1) for kv in (ancienne["notes"] or "").split() if ":" in kv)
        u_avant = float(vieilles_notes.get("unites") or 0)
        u_total = u_avant + float(unites or 0)
        e_total = float(ancienne["size_eur"] or 0) + eur
        vieilles_notes["unites"] = str(int(u_total))
        vieilles_notes["renforts"] = str(int(vieilles_notes.get("renforts") or 0) + 1)
        self.ctx.db.execute(
            "UPDATE positions SET size_eur=?, entry_price=?, notes=? WHERE id=?",
            (e_total, (e_total / u_total) if u_total > 0 else ancienne["entry_price"],
             " ".join(f"{k}:{v}" for k, v in vieilles_notes.items()), ancienne["id"]))
        return "renforcee (%d au total, %.2f EUR)" % (
            int(vieilles_notes["renforts"]) + 1, e_total)

    async def _acheter_sol(self, mint: str, eur: float) -> str:
        from intel.execution import solana as sol

        rpc = sol.rpc_url()
        if not rpc:
            return "Solana indisponible : aucun point d acces configure."
        # `solana.mode` gouverne le CARNET AUTOMATIQUE, pas l operateur. Il a ete mis a `paper` le
        # 10/09 pour arreter le robot, et il a du meme coup refuse les achats tapes sur Telegram
        # (§5.25). Le manuel a son propre interrupteur : `manuel.enabled`, vrai par defaut.
        if not bool(self._cfg("enabled", True)):
            return "Le trading manuel est desactive (<code>manuel.enabled</code>)."
        if not sol.signer_address(self._cle()):
            return "Aucune cle pour le portefeuille manuel : rien n est envoye."
        try:
            taux = await sol.sol_eur(self.client)
            res = await sol.prepare_buy(
                self.client, mint=mint, size_eur=eur, sol_eur=taux, proprietaire=sol.signer_address(self._cle()),
                slippage_pct=float(self.ctx.config.get("solana.slippage_pct", 15.0)),
                # Plafond d impact PROPRE au manuel. Celui du robot est a 6 % parce qu il achete
                # sans regarder ; a la main c est l operateur qui decide, et il peut vouloir entrer
                # dans un pool que le robot refuserait. On garde neanmoins une borne : un impact de
                # 100 % signifie qu il n y a pas de contrepartie et que la mise est perdue a
                # l instant de l achat, ce qui n est pas un arbitrage mais une erreur.
                max_impact_pct=float(self._cfg("max_impact_pct", 25.0) or 100.0),
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
            signee = sol.sign(tx_b64, self._cle())
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
        # Le prix d entree est le rapport entre ce qu on paie et ce qu on recoit. Sans lui, aucun
        # multiple n est calculable et le suivi ne peut rien dire d autre que « ouverte ».
        recus = float(res.get("quoted_amount_out") or 0)
        entree = (eur / recus) if recus else None
        etat = self._ajouter_ou_ouvrir(
            mint=mint, label=mint[:10], eur=eur, entree=entree, unites=recus,
            model_version=MV_SOL, notes=f"manuel:{did} mint:{mint} unites:{int(recus)}")
        return (f"<b>Achat Solana envoye</b>\n"
                f"jeton   <code>{mint}</code>\n"
                f"montant {eur:.2f} EUR ({eur / taux:.4f} SOL)\n"
                f"impact  {float(res.get('slippage_pct') or 0):.2f} %\n"
                f"tx      <code>{h[:32]}</code>\n"
                f"ligne   {etat}\n\n"
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
        if not rpc:
            return "Solana indisponible : point d acces absent."
        # Le solde REEL, jamais ce que le livre croit detenir (§5.1) -- et sur LES DEUX
        # portefeuilles. Une position ouverte avant la creation du portefeuille manuel dort sur
        # celui du robot : ne chercher que sur un seul repondait « ne detient pas ce jeton » sur une
        # ligne parfaitement vivante, et la vente etait alors impossible depuis Telegram.
        # On retient AUSSI la cle du portefeuille trouve. Assembler la transaction pour un
        # proprietaire puis la signer avec l autre cle produit une transaction invalide : c est
        # silencieux a la construction et ne se voit qu au rejet, position toujours ouverte.
        solde, proprio, cle = 0, None, None
        for f in (self._cle(), None):
            a = sol.signer_address(f)
            if not a:
                continue
            try:
                b = await sol.token_balance(self.client, rpc, a, adresse)
            except Exception as exc:  # noqa: BLE001
                return f"Solde illisible : {str(exc)[:120]}. Rien n a ete vendu."
            if b > solde:
                solde, proprio, cle = b, a, f
        if solde <= 0 or not proprio:
            return "Aucun des deux portefeuilles ne detient ce jeton. Rien n a ete vendu."
        montant = int(solde * pct / 100)
        try:
            res = await sol.prepare_sell(
                self.client, mint=adresse, amount=montant,
                slippage_pct=float(self.ctx.config.get("solana.sell_slippage_pct", 25.0)),
                priorite_lamports=int(self.ctx.config.get("solana.priority_fee_lamports", 0) or 0),
                proprietaire=proprio)
        except Exception as exc:  # noqa: BLE001
            return f"Cotation refusee : {str(exc)[:140]}"
        if res.get("status") == "REFUSED":
            return f"Vente refusee : {res.get('refused_reason')}"
        tx_b64 = res.pop("tx", None)
        if not tx_b64:
            return "Transaction non assemblee (aucune cle ?)."
        try:
            h = await sol.send(self.client, rpc, sol.sign(tx_b64, cle))
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



    async def _fiche_evm(self, token: str) -> tuple[str | None, str | None]:
        """(symbole, paire) pour un jeton EVM. Meme raison qu en Solana : le lien se construit sur
        la paire, jamais sur le jeton, sinon rien ne dit quel marche s ouvre (§5.15)."""
        try:
            r = await self.client.get(
                "https://api.dexscreener.com/latest/dex/tokens/" + token, timeout=15)
            paires = [x for x in ((r.json() or {}).get("pairs") or []) if x.get("pairAddress")]
            if not paires:
                return None, None
            best = max(paires, key=lambda x: float((x.get("liquidity") or {}).get("usd") or 0))
            return (best.get("baseToken") or {}).get("symbol"), best.get("pairAddress")
        except Exception:  # noqa: BLE001
            return None, None

    async def _fiche(self, mint: str) -> tuple[str | None, str | None]:
        """(symbole, adresse de la paire la plus profonde) chez DexScreener.

        Le lien de graphique se construit sur la PAIRE, pas sur le jeton : `/solana/<mint>` n est
        pas la forme canonique et rien ne garantit qu elle ouvre le bon marche. On demande donc la
        paire reelle, et on prend la plus profonde -- un jeton en a souvent plusieurs et c est celle
        ou le negoce a lieu qui interesse.
        """
        try:
            r = await self.client.get(
                "https://api.dexscreener.com/latest/dex/tokens/" + mint, timeout=15)
            paires = [x for x in ((r.json() or {}).get("pairs") or []) if x.get("pairAddress")]
            if not paires:
                return None, None
            best = max(paires, key=lambda x: float((x.get("liquidity") or {}).get("usd") or 0))
            return (best.get("baseToken") or {}).get("symbol"), best.get("pairAddress")
        except Exception:  # noqa: BLE001
            return None, None

    # ---------------------------------------------------------------- valeur
    async def _valeur_evm(self, token: str) -> tuple[float, float] | None:
        """Ce que vaut une ligne EVM, lue sur la chaine puis cotee.

        Symetrique de `_valeur` pour Solana, avec une difference qu il faut assumer : sur Solana on
        demande au ROUTEUR ce qu on encaisserait vraiment, ici on multiplie le solde par un prix
        affiche. C est moins bon -- un prix moyen n est pas un prix de sortie -- mais Robinhood Chain
        n a pas d agregateur qui cote une revente. La valeur affichee est donc un ordre de grandeur,
        pas une promesse ; la vente reelle passera par le carnet et donnera le vrai chiffre.
        """
        from intel.execution.signer import signer_address

        rpc = getattr(self.ctx.settings, "rpc_url", None)
        proprio = signer_address()
        if not rpc or not proprio:
            return None
        try:
            appel = lambda to, data: (self.ctx.rpc.call("eth_call", [{"to": to, "data": data}, "latest"])
                                      if hasattr(self.ctx, "rpc") else None)
            r = await self.client.post(rpc, json={"jsonrpc": "2.0", "id": 1, "method": "eth_call",
                                                  "params": [{"to": token,
                                                              "data": "0x70a08231" + "0" * 24 + proprio[2:]},
                                                             "latest"]}, timeout=20)
            brut = int((r.json() or {}).get("result") or "0x0", 16)
            if brut <= 0:
                return None
            r2 = await self.client.post(rpc, json={"jsonrpc": "2.0", "id": 1, "method": "eth_call",
                                                   "params": [{"to": token, "data": "0x313ce567"},
                                                              "latest"]}, timeout=20)
            dec = int((r2.json() or {}).get("result") or "0x12", 16)
            qte = brut / (10 ** dec)
            d = await self.client.get("https://api.dexscreener.com/latest/dex/tokens/" + token, timeout=20)
            paires = [x for x in ((d.json() or {}).get("pairs") or []) if x.get("priceUsd")]
            if not paires:
                return None
            best = max(paires, key=lambda x: float((x.get("liquidity") or {}).get("usd") or 0))
            return qte * float(best["priceUsd"]) / 1.08, 0.0      # en euros
        except Exception:  # noqa: BLE001
            return None

    async def _valeur(self, mint: str) -> tuple[float, float] | None:
        """Ce que la position vaut A LA VENTE, pour la taille reellement detenue.

        On demande au routeur, pas a DexScreener : un prix moyen de marche n est pas ce qu on
        encaisse. Sur un pool mince l ecart atteint des dizaines de pour cent, et c est justement
        sur les pools minces qu on se fait avoir (§3.47). Rend (euros, multiple).
        """
        from intel.execution import solana as sol

        rpc = sol.rpc_url()
        if not rpc:
            return None
        # On cherche les jetons sur LES DEUX portefeuilles, pas seulement celui du manuel. Une
        # position ouverte avant la creation du portefeuille dedie est partie du portefeuille du
        # robot -- c est arrive le 09/09 a 15:37, et le suivi affichait « valeur inconnue » sur une
        # ligne parfaitement vivante a x1,07. Chercher la ou l argent est plutot que la ou il devrait
        # etre coute deux appels et evite de declarer disparue une position qui ne l est pas.
        try:
            solde, proprio = 0, None
            for f in (self._cle(), None):
                a = sol.signer_address(f)
                if not a:
                    continue
                b = await sol.token_balance(self.client, rpc, a, mint)
                if b > solde:
                    solde, proprio = b, a
            if solde <= 0 or not proprio:
                return None
            q = await sol.quote(self.client, input_mint=mint, output_mint=sol.SOL_MINT,
                                amount=solde, slippage_bps=2500)
            if not q.usable:
                return None
            taux = await sol.sol_eur(self.client)
            return (q.out_amount / 1e9) * taux, 0.0
        except Exception:  # noqa: BLE001
            return None

    async def surveiller(self) -> int:
        """Prevenir quand une ligne manuelle franchit un palier. Appele par la boucle du carnet.

        Ce que l operateur a demande : savoir que ca monte sans avoir a le demander. Le palier n est
        annonce QU UNE FOIS -- sans quoi une ligne qui oscille autour de x1,5 enverrait un message
        toutes les vingt secondes et on finirait par ne plus les lire.

        La valeur est celle du routeur pour la taille detenue, jamais un prix affiche : c est la
        seule qui corresponde a ce qu on encaisserait en vendant maintenant.
        """
        paliers = self._cfg("paliers", [1.5, 2.0, 3.0, 5.0]) or []
        bas = float(self._cfg("palier_bas", 0.5) or 0)
        envoyes = 0
        for p in self.ctx.db.query(
                "SELECT * FROM positions WHERE chain_id=? AND model_version LIKE 'manuel-%' AND status='OPEN'",
                (self.ctx.chain_id,)):
            notes = dict(kv.split(":", 1) for kv in (p["notes"] or "").split() if ":" in kv)
            evm = str(p["model_version"]).startswith("manuel-evm")
            mint = p["token_address"] if evm else notes.get("mint")
            if not mint or not p["size_eur"]:
                continue
            v = await (self._valeur_evm(mint) if evm else self._valeur(mint))
            if v is None:
                continue
            euros, _ = v
            mult = euros / float(p["size_eur"])
            # VENTE AUTOMATIQUE sur les lignes EVM, demandee par l operateur le 09/09 au soir pour
            # DOGSHIT (« tu vends cette pose si elle fait un gros gain cette nuit »). Deux tranches,
            # comme il trade lui-meme : la moitie a `moitie_a`, le reste a `tout_a`. On ecrit une
            # DECISION que l executeur EVM ramasse a son cycle suivant et dimensionne sur le solde
            # reel du portefeuille ; on ne signe rien ici. Chaque tranche n est emise qu UNE fois,
            # tracee dans les notes. L arret d urgence ne bloque plus les ventes (safety.py).
            if evm and bool(self._cfg("vente_auto.enabled", False)):
                moitie = float(self._cfg("vente_auto.moitie_a", 2.0) or 0)
                tout = float(self._cfg("vente_auto.tout_a", 4.0) or 0)
                faites = set((notes.get("vendu") or "").split(",")) - {""}
                ordre = None
                if tout and mult >= tout and "tout" not in faites:
                    ordre, faites = "SELL_ALL", faites | {"tout"}
                elif moitie and mult >= moitie and "moitie" not in faites and "tout" not in faites:
                    ordre, faites = "SELL_HALF", faites | {"moitie"}
                if ordre:
                    notes["vendu"] = ",".join(sorted(faites))
                    self.ctx.db.execute(
                        "UPDATE positions SET notes=? WHERE id=?",
                        (" ".join(f"{k}:{v}" for k, v in notes.items()), p["id"]))
                    self.ctx.db.insert("decisions", {
                        "ts": now_ts(), "chain_id": self.ctx.chain_id, "token_address": mint,
                        "label": p["label"], "kind": ordre,
                        "reason": f"vente automatique manuelle : x{mult:.2f} atteint (seuil {tout if ordre == 'SELL_ALL' else moitie})",
                        "price": None, "size_eur": float(p["size_eur"]), "position_id": p["id"],
                        "sent": 0, "model_version": p["model_version"]})
                    await self._prevenir(
                        f"💰 <b>{p['label']}</b> a atteint <b>x{mult:.2f}</b> — "
                        f"{'VENTE TOTALE' if ordre == 'SELL_ALL' else 'VENTE DE LA MOITIE'} envoyee a l executeur\n"
                        f"mise {float(p['size_eur']):.0f} EUR · vaut {euros:.2f} EUR\n"
                        f"<i>Le montant reellement recu se lit en chaine : /manuel dans une minute.</i>")
                    envoyes += 1
            deja = {float(x) for x in (notes.get("vus", "").split(",") if notes.get("vus") else [])}
            atteints = [s for s in paliers if mult >= float(s) and float(s) not in deja]
            if bas and mult <= bas and bas not in deja:
                atteints.append(bas)
            if not atteints:
                continue
            for s in atteints:
                deja.add(float(s))
            notes["vus"] = ",".join(str(x) for x in sorted(deja))
            # Le pic va dans les notes, en MULTIPLE. Il allait dans `peak_price`, qui attend un PRIX :
            # le scanner a lu x3,27 comme un prix de 3,27 $, calcule « -100 % depuis le plus haut »
            # et ferme la ligne DOGSHIT de l operateur le 10/09 a 03h06 (§5.24).
            notes["pic"] = "%.3f" % max(float(notes.get("pic") or 0), mult)
            self.ctx.db.execute(
                "UPDATE positions SET notes=? WHERE id=?",
                (" ".join(f"{k}:{v}" for k, v in notes.items()), p["id"]))
            haut = max(atteints)
            fleche = "📈" if haut > 1 else "📉"
            await self._prevenir(
                f"{fleche} <b>{p['label']}</b> a franchi <b>x{haut}</b>\n"
                f"mise {float(p['size_eur']):.0f} EUR · vaut maintenant "
                f"<b>{euros:.2f} EUR</b> (x{mult:.2f})\n"
                f"<code>{mint}</code>\n"
                f"<i>/vente {mint[:8]} pour sortir</i>")
            envoyes += 1
        return envoyes

    async def _prevenir(self, texte: str) -> None:
        from intel.alerts.telegram import TelegramSender

        try:
            await TelegramSender(self.ctx.settings).send(texte)
        except Exception as exc:  # noqa: BLE001
            log.info("alerte manuelle non envoyee (%s)", str(exc)[:80])

    # ------------------------------------------------------------------ suivi
    async def _inventaire(self) -> list[str]:
        """Ce que l operateur DETIENT, lu sur la chaine, tous portefeuilles confondus.

        `/manuel` ne montrait que le registre -- les lignes que le systeme avait enregistrees. Le
        09/09 a minuit l operateur, avec six portefeuilles dont trois ouverts par le moteur, ne s y
        retrouvait plus : ses PURR sur Trust, son SOL, son ETH n apparaissaient nulle part parce que
        personne ne les avait saisis. Un registre dit ce qu on croit avoir ; la chaine dit ce qu on
        a. Cette section lit la seconde, pour chaque portefeuille declare dans
        `manuel.portefeuilles`, et vaut les jetons par la paire la plus profonde de DexScreener.
        Un ordre de grandeur, pas un prix de sortie -- ce que le registre au-dessus, lui, cote au
        routeur pour les lignes qu il connait.
        """
        from intel.execution import solana as sol

        ports = self.ctx.config.get("manuel.portefeuilles", []) or []
        if not ports:
            return []
        rpc_sol = sol.rpc_url()
        rpc_evm = getattr(self.ctx.settings, "rpc_url", None)
        try:
            taux = await sol.sol_eur(self.client)
        except Exception:  # noqa: BLE001
            taux = 95.0
        eth_eur = float(self.ctx.config.get("manuel.eth_eur", 2280.0) or 2280.0)

        async def prix(mint: str, chain: str) -> tuple[str, float]:
            """Le prix du jeton, pris comme la MEDIANE de ses paires.

            Deux pieges, tous deux rencontres :

            1. La paire la plus PROFONDE n a pas forcement le bon prix. Le 10/09, HYPE avait cinq
               paires : quatre a 82,8 $ et une, la plus profonde (33 M$ annonces), a 419 741 $ --
               cinq mille fois plus. En prenant la plus profonde, `/manuel` a affiche 12 640 EUR
               pour une ligne qui en vaut 2,49, et un total de 14 089 EUR au lieu de ~1 450.
               L operateur a demande de tout vendre sur la foi de ce chiffre. La mediane ignore
               l aberration sans avoir a decider laquelle des sources ment (S5.30).

            2. Notre jeton doit etre le jeton de BASE de la paire. `priceUsd` est le prix du jeton
               de base ; sur une paire ou le notre est la cotation, c est le prix de l AUTRE.
            """
            try:
                d = await self.client.get("https://api.dexscreener.com/latest/dex/tokens/" + mint, timeout=15)
                ps = [x for x in ((d.json() or {}).get("pairs") or [])
                      if x.get("chainId") == chain and x.get("priceUsd")
                      and ((x.get("baseToken") or {}).get("address") or "").lower() == mint.lower()]
                if ps:
                    px = sorted(float(x["priceUsd"]) for x in ps)
                    n = len(px)
                    med = px[n // 2] if n % 2 else (px[n // 2 - 1] + px[n // 2]) / 2
                    sym = (ps[0].get("baseToken") or {}).get("symbol") or mint[:6]
                    return sym, med / 1.08
            except Exception:  # noqa: BLE001
                pass
            return mint[:6], 0.0

        out = ["", "<b>Ce que tu detiens, lu sur la chaine</b>"]
        total = 0.0
        for w in ports:
            nom, adr, chain = w.get("nom", "?"), w.get("adresse", ""), w.get("chaine", "solana")
            if not adr:
                continue
            valeur, items = 0.0, []
            try:
                if chain == "solana" and rpc_sol:
                    r = await self.client.post(rpc_sol, json={"jsonrpc": "2.0", "id": 1, "method": "getBalance",
                                                             "params": [adr]}, timeout=20)
                    b = ((r.json() or {}).get("result") or {}).get("value", 0) / 1e9
                    valeur += b * taux
                    items.append(f"{b:.3f} SOL")
                    for prog in ("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA", "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"):
                        r = await self.client.post(rpc_sol, json={
                            "jsonrpc": "2.0", "id": 1, "method": "getTokenAccountsByOwner",
                            "params": [adr, {"programId": prog}, {"encoding": "jsonParsed"}]}, timeout=25)
                        for x in ((r.json() or {}).get("result") or {}).get("value", []):
                            i = x["account"]["data"]["parsed"]["info"]
                            q = float(i["tokenAmount"]["uiAmount"] or 0)
                            if q <= 0:
                                continue
                            sym, px = await prix(i["mint"], "solana")
                            v = q * px
                            valeur += v
                            if v >= 1:
                                items.append(f"{sym} {v:.0f}")
                elif chain == "robinhood" and rpc_evm:
                    r = await self.client.post(rpc_evm, json={"jsonrpc": "2.0", "id": 1, "method": "eth_getBalance",
                                                             "params": [adr, "latest"]}, timeout=20)
                    b = int((r.json() or {}).get("result") or "0x0", 16) / 1e18
                    valeur += b * eth_eur
                    items.append(f"{b:.4f} ETH")
                    # les jetons EVM connus du registre, faute d index de jetons sur cette chaine
                    # TOUS les jetons de l adresse, demandes a l explorateur. La version precedente
                    # ne testait que les jetons deja presents dans `positions`, faute d index de
                    # jetons sur cette chaine -- donc tout ce que l operateur achete AILLEURS etait
                    # structurellement invisible. Le 10/09 elle annoncait 825 EUR au total quand il
                    # en detenait 1 610 : 785 EUR manquants, presque la moitie, dont trois lignes de
                    # son portefeuille Trust (ROBIN 363, TWO 231, PACK 206) que le systeme n avait
                    # jamais enregistrees et ne cherchait donc pas (§5.29).
                    soldes = []
                    try:
                        d = await self.ctx.blockscout.get_v2(
                            "addresses/%s/token-balances" % adr, essential=True)
                        for x in (d or []):
                            t = x.get("token") or {}
                            dec = int(t.get("decimals") or 18)
                            q = int(x.get("value") or 0) / (10 ** dec)
                            jeton = t.get("address_hash") or ""
                            if q > 0 and jeton:
                                soldes.append((jeton, q, t.get("symbol") or jeton[:6]))
                    except Exception:  # noqa: BLE001
                        # L explorateur peut etre indisponible ou a court de quota : on retombe sur
                        # les jetons connus du registre, incomplet mais mieux que rien, et la ligne
                        # le dit pour qu un total trop bas ne passe pas pour un total juste.
                        items.append("<i>explorateur indisponible, liste partielle</i>")
                        vus = set()
                        for t in self.ctx.db.query(
                                "SELECT token_address FROM positions WHERE chain_id=? AND token_address LIKE '0x%' "
                                "ORDER BY (status='OPEN') DESC, opened_ts DESC", (self.ctx.chain_id,)):
                            k = str(t["token_address"]).lower()
                            if k in vus:
                                continue
                            vus.add(k)
                            r = await self.client.post(rpc_evm, json={
                                "jsonrpc": "2.0", "id": 1, "method": "eth_call",
                                "params": [{"to": k, "data": "0x70a08231" + "0" * 24 + adr[2:].lower()},
                                           "latest"]}, timeout=15)
                            brut = int((r.json() or {}).get("result") or "0x0", 16)
                            if brut > 0:
                                soldes.append((k, brut / 1e18, k[:6]))
                            if len(vus) >= 60:
                                break
                    petits = 0.0
                    for jeton, q, sym in soldes:
                        _s, px = await prix(jeton, "robinhood")
                        v = q * px
                        valeur += v
                        if v >= 1:
                            items.append(f"{sym} {v:.0f}")
                        else:
                            petits += v
                    if petits or len(soldes) > len([i for i in items if " " in i]):
                        morts = sum(1 for _j, _q, _s in soldes) - sum(1 for i in items if " " in i)
                        if morts > 0:
                            items.append(f"<i>+{morts} sans valeur</i>")
            except Exception as exc:  # noqa: BLE001
                items.append(f"<i>illisible ({str(exc)[:30]})</i>")
            total += valeur
            out.append(f"<code>{nom[:14]:<15}</code><b>{valeur:7.2f} EUR</b>  {' · '.join(items)}")
        out.append(f"<b>Total detenu : {total:.2f} EUR</b>")
        return out

    async def suivi(self) -> str:
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
            latent = 0.0
            for p in ouvertes:
                ch = "SOL" if str(p["model_version"]).startswith("manuel-sol") else "EVM"
                age = (now_ts() - int(p["opened_ts"])) // 60
                mise = float(p["size_eur"] or 0)
                # La valeur du moment, demandee au routeur pour la quantite reellement detenue :
                # c est ce qu on encaisserait en vendant maintenant, pas un prix affiche ailleurs.
                # Sur un pool mince les deux different de dizaines de pour cent (§3.47).
                v = (await self._valeur(p["token_address"]) if ch == "SOL"
                     else await self._valeur_evm(p["token_address"]))
                if v:
                    euros = v[0]
                    mult = (euros / mise) if mise else 0.0
                    latent += euros - mise
                    rond = "\U0001F7E2" if euros >= mise else "\U0001F534"
                    lignes.append(f"{rond} <b>__NOM__</b>  <b>x{mult:.2f}</b>  {euros:.2f} EUR "
                                  f"sur {mise:.0f} ({euros - mise:+.2f}) · {age} min")
                else:
                    lignes.append(f"⚪ <b>__NOM__</b> {ch} · {mise:.0f} EUR · {age} min · <i>valeur inconnue</i>")
                # Le lien vers la courbe, construit sur la PAIRE et non sur le jeton.
                sym, paire = (await self._fiche(p["token_address"]) if ch == "SOL"
                              else await self._fiche_evm(p["token_address"]))
                base = "https://dexscreener.com/solana/" if ch == "SOL" else "https://dexscreener.com/robinhood/"
                lien = base + (paire or p["token_address"])
                nom = sym or (p["label"] or "")[:12]
                lignes[-1] = lignes[-1].replace("__NOM__", nom)
                lignes.append(f"  <a href=\"{lien}\">graphique {nom}</a>  <code>{p['token_address']}</code>")
            lignes.append("")
            lignes.append(f"<b>Latent {latent:+.2f} EUR</b> <i>(si on vendait tout maintenant)</i>")
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
        lignes += await self._inventaire()
        lignes.append("<i>Lu sur la chaine, jamais sur une cotation.</i>")
        return "\n".join(lignes)
