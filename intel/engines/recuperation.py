"""Recuperation des cautions de compte-jeton : l argent qu on paie a chaque achat et qu on ne
reprend jamais.

CE QUE C EST. Solana exige qu un compte soit « rent-exempt » : ouvrir un compte-jeton immobilise
**0,002039 SOL**. Notre moteur en cree un a chaque achat et n en ferme aucun -- il n y a aucun
`closeAccount` dans le projet. Cette caution n est pas perdue, elle est BLOQUEE : il suffit de
fermer le compte, une fois vide, pour la recuperer.

CE QUE CA VAUT. Sur un ticket de 30 EUR (0,31 SOL), 0,002039 SOL font **0,66 point**. Sur 50 EUR,
0,39 point. Le cout d execution total, mesure de bout en bout sur 236 tickets reels, est de
2,62 pts : le ramener a ~1,96 fait passer `RISQUE seul` (brut +2,15 %) de perdante a gagnante.
C est le seul poste de frais reductible SANS contrepartie -- baisser la priorite fait echouer des
ordres (§3.40 : quatre sur six), et reduire l impact demande de changer la strategie.

POURQUOI UN MODULE A PART, ET PAS DANS LA VENTE. Trois raisons, dans cet ordre :
  - le chemin d achat/vente signe des transactions qui deplacent de l argent ; y ajouter une etape,
    c est transformer un bug de fermeture en bug de trading ;
  - une vente doit atterrir en secondes, une fermeture peut attendre une heure sans rien changer au
    montant recupere -- melanger du lent et du critique ne rapporte rien et coute du risque ;
  - fermer par PAQUETS demande d accumuler des comptes, ce qui n a pas de sens dans une vente unique.

CE QU IL NE PEUT PAS FAIRE. Il n a qu une instruction a sa disposition : `CloseAccount`. Il ne peut
ni acheter, ni vendre, ni transferer, ni bruler. Un compte dont le solde n est pas EXACTEMENT zero
est ignore, donc aucun jeton ne peut disparaitre.

RAPIDITE. Une seule lecture RPC par passage (`getTokenAccountsByOwner` liste tout d un coup), pas de
frais de priorite -- ce n est pas urgent, et surtout ca evite de disputer la place dans le bloc a nos
propres ordres d achat --, un intervalle long, et un plafond de transactions par passage.
"""
from __future__ import annotations

import base64
import logging
from typing import Any

from intel.execution import solana as sol

log = logging.getLogger(__name__)

PROGRAMMES = {
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",          # SPL Token
    "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",          # Token-2022
}
CAUTION_SOL = 0.00203928          # rent-exempt d un compte-jeton, ce qu on recupere
PAR_PAQUET = 20                   # instructions par transaction
FERMER_APRES_S = 900.0            # ne pas toucher un compte vide depuis moins de 15 min


class Recuperation:
    """Ferme les comptes-jetons vides et rend leur caution au portefeuille."""

    def __init__(self, ctx, client) -> None:
        self.ctx, self.client = ctx, client
        self._vus: dict[str, float] = {}      # compte -> premier instant ou on l a vu vide

    def _cfg(self, cle: str, defaut: Any) -> Any:
        return self.ctx.config.get("recuperation.%s" % cle, defaut)

    async def _comptes_vides(self, client, rpc: str, proprio: str) -> list[tuple[str, str, str]]:
        """(compte, programme, mint) pour chaque compte-jeton a solde nul. UNE lecture par programme."""
        out = []
        for prog in PROGRAMMES:
            r = await client.post(rpc, json={
                "jsonrpc": "2.0", "id": 1, "method": "getTokenAccountsByOwner",
                "params": [proprio, {"programId": prog}, {"encoding": "jsonParsed"}]}, timeout=30)
            for acc in ((r.json() or {}).get("result") or {}).get("value") or []:
                info = acc["account"]["data"]["parsed"]["info"]
                if int(info["tokenAmount"].get("amount") or 0) == 0:
                    out.append((str(acc["pubkey"]), prog, str(info.get("mint") or "")))
        return out

    def _mints_ouverts(self) -> set[str]:
        """Les jetons d une position encore ouverte. On n y touche pas.

        Un compte fraichement cree par un achat en vol a un solde de zero pendant quelques
        secondes : le fermer ferait echouer l achat. D ou cette garde, plus le delai
        FERMER_APRES_S qui exige qu un compte soit vu vide deux fois a un quart d heure d ecart.
        """
        try:
            return {str(r["token_address"]) for r in self.ctx.db.query(
                "SELECT token_address FROM positions WHERE status='OPEN' AND chain='solana'")}
        except Exception:  # noqa: BLE001
            return set()          # dans le doute on ne ferme rien de plus, la garde de temps reste

    def _instruction_fermer(self, compte: str, prog: str, proprio: str):
        from solders.instruction import AccountMeta, Instruction
        from solders.pubkey import Pubkey

        p = Pubkey.from_string(proprio)
        return Instruction(
            program_id=Pubkey.from_string(prog),
            accounts=[AccountMeta(Pubkey.from_string(compte), False, True),   # le compte a fermer
                      AccountMeta(p, False, True),                            # ou va la caution
                      AccountMeta(p, True, False)],                           # le proprietaire signe
            data=bytes([9]),                                                  # CloseAccount
        )

    async def cycle(self) -> None:
        if not bool(self._cfg("enabled", False)):
            return
        client = self.client
        rpc = str(self.ctx.config.get("solana.rpc_url", ""))
        proprio = sol.signer_address()
        if not rpc or not proprio:
            return
        vides = await self._comptes_vides(client, rpc, proprio)
        if not vides:
            return

        from intel.utils.timeutil import now_ts
        maintenant = now_ts()
        ouverts = self._mints_ouverts()
        prets = []
        for compte, prog, mint in vides:
            self._vus.setdefault(compte, maintenant)
            if mint in ouverts:
                continue
            if maintenant - self._vus[compte] >= FERMER_APRES_S:
                prets.append((compte, prog))
        for c in list(self._vus):                     # oublier ceux qui ne sont plus vides
            if c not in {v[0] for v in vides}:
                self._vus.pop(c, None)

        if not prets:
            log.info("recuperation: %d compte(s) vide(s), aucun encore mur", len(vides))
            return
        plafond = int(self._cfg("max_transactions_par_passage", 3))
        paquets = [prets[i:i + PAR_PAQUET] for i in range(0, len(prets), PAR_PAQUET)][:plafond]
        gain = CAUTION_SOL * sum(len(p) for p in paquets)

        if str(self.ctx.config.get("execution.mode", "paper")).lower() != "live":
            log.info("recuperation (PAPIER) : %d compte(s) fermables en %d transaction(s), "
                     "%.4f SOL a recuperer -- rien n a ete signe", sum(len(p) for p in paquets),
                     len(paquets), gain)
            return

        for paquet in paquets:
            try:
                await self._fermer(client, rpc, proprio, paquet)
            except Exception as exc:  # noqa: BLE001
                log.warning("recuperation: paquet refuse (%s)", str(exc)[:160])
                break                                  # on reessaiera au prochain passage

    async def _fermer(self, client, rpc: str, proprio: str, paquet: list[tuple[str, str]]) -> None:
        from solders.hash import Hash
        from solders.message import MessageV0
        from solders.pubkey import Pubkey
        from solders.transaction import VersionedTransaction

        r = await client.post(rpc, json={"jsonrpc": "2.0", "id": 1,
                                         "method": "getLatestBlockhash", "params": [{"commitment": "finalized"}]},
                              timeout=20)
        bh = (((r.json() or {}).get("result") or {}).get("value") or {}).get("blockhash")
        if not bh:
            raise RuntimeError("pas de blockhash")
        instrs = [self._instruction_fermer(c, p, proprio) for c, p in paquet]
        msg = MessageV0.try_compile(Pubkey.from_string(proprio), instrs, [], Hash.from_string(bh))
        nonsigne = base64.b64encode(bytes(VersionedTransaction.populate(msg, []))).decode()
        signe = sol.sign(nonsigne)
        h = await sol.send(client, rpc, signe)
        log.info("recuperation: %d compte(s) fermes, %.4f SOL rendus -- %s",
                 len(paquet), CAUTION_SOL * len(paquet), h)
