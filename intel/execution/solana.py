"""Execution on Solana: quote, check, sign, send. Dry run unless the operator says otherwise.

The hard half of an execution layer is not the chain, it is everything around the order -- the
absolute ceilings, the journal, the receipt reconciliation, the exit rule, the book. All of that
already exists and does not care which chain it is on. What is chain-specific is small:

  Robinhood Chain                      Solana
  secp256k1, EIP-1559                  ed25519, versioned transactions
  UniversalRouter calldata built here  Jupiter returns the transaction already built
  Permit2 grants before a sale         nothing to grant
  eth_getLogs to read the pool         an indexed endpoint, one account at a time

Jupiter is what collapses the work: it quotes across pump.fun, Raydium, Meteora and PumpSwap, and
answers with a serialised transaction that only needs a signature. That also makes it a dependency
in the hot path -- an outage there is an outage here -- and the reason a sale never relies on a
quote alone: what the chain returns is read back from the wallet balance afterwards.

Two deliberate acts are still required before anything leaves a wallet, exactly as on the other
chain: a key in SOLANA_PRIVATE_KEY, and execution.solana.mode set to live.
"""
from __future__ import annotations

import base64
import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx

log = logging.getLogger(__name__)

JUPITER = "https://lite-api.jup.ag/swap/v1"
SOL_MINT = "So11111111111111111111111111111111111111112"
LAMPORTS = 1_000_000_000
KEY_ENV = "SOLANA_PRIVATE_KEY"
RPC_ENV = "SOLANA_RPC_URL"


class SolanaRefused(Exception):
    """Raised instead of signing. Never carries the key or any part of it."""


@dataclass(frozen=True)
class SolanaQuote:
    in_lamports: int
    out_amount: int
    price_impact_pct: float
    route: str
    raw: dict[str, Any]

    @property
    def usable(self) -> bool:
        return self.out_amount > 0


def rpc_url() -> str:
    """The indexed endpoint, from the environment or from a file beside the data.

    A container reads its environment once, at creation. Changing .env therefore needs the
    container recreated, which is not always possible while a live book is running, so a path is
    accepted as well -- the same convention as the *_FILE variables of most daemons. The file
    lives under data/, which is outside the repository.
    """
    direct = (os.environ.get(RPC_ENV) or "").strip()
    if direct.startswith("http"):
        return direct
    for path in (os.environ.get(RPC_ENV + "_FILE") or "", "/app/data/.solana_rpc"):
        if path and os.path.exists(path):
            try:
                with open(path) as fh:
                    val = fh.read().strip()
                if val.startswith("http"):
                    return val
            except OSError:
                continue
    return ""


_SOL_EUR: tuple[float, float] = (0.0, 0.0)      # (price, fetched_at)


async def sol_eur(client: httpx.AsyncClient, fallback: float = 96.0, max_age_s: int = 600) -> float:
    """What one SOL is worth in euros, read from the market and cached for a few minutes.

    A hard-coded rate is a silent accounting error. On 2026-09-08 the book assumed 180 EUR while
    SOL traded at 96: a ticket announced at 5 EUR committed 2.67, and every gain was reported 88 %
    too high. Only the multiples happened to be right, the two errors cancelling each other.
    """
    global _SOL_EUR
    import time as _t
    px, at = _SOL_EUR
    if px > 0 and _t.time() - at < max_age_s:
        return px
    try:
        r = await client.get("https://api.dexscreener.com/latest/dex/tokens/" + SOL_MINT, timeout=15)
        pairs = [x for x in ((r.json() or {}).get("pairs") or []) if x.get("priceUsd")]
        best = max(pairs, key=lambda x: float((x.get("liquidity") or {}).get("usd") or 0))
        usd = float(best["priceUsd"])
        if usd > 0:
            _SOL_EUR = (usd / 1.08, _t.time())
            return _SOL_EUR[0]
    except Exception:  # noqa: BLE001
        pass
    return px or fallback


def signer_address(fichier: str | None = None) -> str | None:
    """The address that would sign, or None when no key is configured. Public information."""
    try:
        return str(_keypair(fichier).pubkey())
    except SolanaRefused:
        return None


def _keypair(fichier: str | None = None) -> Any:
    """Derive the keypair. The key never leaves this function.

     designe un portefeuille SEPARE -- celui du trading manuel. Le carnet automatique et
    les ordres passes a la main n ont aucune raison de partager une cle : ce qui est mis dans le
    portefeuille manuel est ce que l operateur accepte de risquer a la main, et une erreur du robot
    ne peut pas y toucher. C est la meme raison qui fait que le bot a son propre portefeuille plutot
    que celui de l operateur.
    """
    if fichier:
        try:
            with open(fichier) as fh:
                raw = fh.read().strip()
        except OSError as exc:
            raise SolanaRefused(f"portefeuille manuel illisible : {exc.__class__.__name__}") from exc
        if not raw:
            raise SolanaRefused("portefeuille manuel vide")
        return _depuis_texte(raw)
    raw = (os.environ.get(KEY_ENV) or "").strip()
    if not raw:
        # A container reads its environment once, at creation, so a key added to .env while a live
        # book is running would need the container recreated. The same file convention as the
        # endpoint is accepted, under data/, which never enters the repository.
        for path in (os.environ.get(KEY_ENV + "_FILE") or "", "/app/data/.solana_key"):
            if path and os.path.exists(path):
                try:
                    with open(path) as fh:
                        raw = fh.read().strip()
                except OSError:
                    raw = ""
                if raw:
                    break
    if not raw:
        raise SolanaRefused(f"aucune clé dans {KEY_ENV} : rien n'est signé")
    return _depuis_texte(raw)


def _depuis_texte(raw: str) -> Any:
    try:
        import base58
        from solders.keypair import Keypair
    except ImportError as exc:  # pragma: no cover - declared in requirements-intel.txt
        raise SolanaRefused(f"bibliothèque de signature absente: {exc}") from exc
    try:
        data = base58.b58decode(raw)          # Phantom and the CLI both export base58
        return Keypair.from_bytes(data) if len(data) == 64 else Keypair.from_seed(data)
    except Exception as exc:  # noqa: BLE001
        raise SolanaRefused("clé privée illisible") from exc  # never echo the value


async def quote(client: httpx.AsyncClient, *, input_mint: str, output_mint: str, amount: int,
                slippage_bps: int, max_comptes: int | None = None) -> SolanaQuote:
    """`max_comptes` borne le nombre de comptes de la route, donc la TAILLE de la transaction.

    Solana refuse toute transaction depassant 1 232 octets. Jupiter assemble parfois une route a
    plusieurs sauts qui franchit ce seuil : le 09/09, deux achats sur 747 ont ete rejetes a
    1 233 octets, un octet de trop. On ne bride pas les routes par defaut -- ce serait degrader
    99,7 % des ordres pour en sauver 0,3 -- mais `prepare_buy` recote avec cette borne quand la
    transaction construite frole la limite.
    """
    params = {"inputMint": input_mint, "outputMint": output_mint,
              "amount": amount, "slippageBps": slippage_bps}
    if max_comptes:
        params["maxAccounts"] = int(max_comptes)
    r = await client.get(f"{JUPITER}/quote", params=params, timeout=20)
    if r.status_code != 200:
        raise SolanaRefused(f"cotation refusée ({r.status_code}): {r.text[:120]}")
    q = r.json()
    routes = [x.get("swapInfo", {}).get("label") for x in q.get("routePlan") or []]
    return SolanaQuote(in_lamports=int(q.get("inAmount") or 0), out_amount=int(q.get("outAmount") or 0),
                       price_impact_pct=float(q.get("priceImpactPct") or 0) * 100,
                       route=" > ".join(str(x) for x in routes if x), raw=q)


async def build_swap(client: httpx.AsyncClient, q: SolanaQuote, owner: str,
                     priorite_lamports: int = 0) -> str:
    """The serialised transaction Jupiter has already assembled; only the signature is missing.

    `priorite_lamports` achete une place dans les prochains blocs. Sans frais de priorite une
    transaction Solana attend son tour, et pendant cette attente le prix bouge : Jupiter compare
    alors le montant recu au seuil calcule lors de la cotation, ne le trouve plus, et annule en
    erreur 0x1771. C est ce qui a fait echouer quatre ordres sur six le 09/09 -- Jacob, wcat,
    PHOUSE deux fois -- avec des cotations pourtant bonnes, entre 1,7 et 2 % d impact (§3.36).
    Payer pour atterrir vite est donc moins cher que ne pas atterrir : 0,001 SOL, soit environ
    0,10 EUR, contre un ticket de 20 EUR qui ne se place pas.
    """
    corps: dict[str, Any] = {"quoteResponse": q.raw, "userPublicKey": owner,
                             "wrapAndUnwrapSol": True, "dynamicComputeUnitLimit": True}
    # MONTANT FIXE, pas un niveau. Verifie contre l API le 09/09 : sans parametre Jupiter applique
    # deja 99 999 lamports ; demander le niveau « high » plafonne a 1 000 000 en fait appliquer
    # 59 431, soit MOINS que son propre defaut -- ma premiere version reduisait donc la priorite en
    # croyant l augmenter. « veryHigh » ne monte qu a 128 218. Un entier passe tel quel est applique
    # tel quel : 300 000 donne 299 999, 1 000 000 donne 999 999.
    if priorite_lamports > 0:
        corps["prioritizationFeeLamports"] = int(priorite_lamports)
    r = await client.post(f"{JUPITER}/swap", json=corps, timeout=25)
    if r.status_code != 200:
        raise SolanaRefused(f"construction refusée ({r.status_code}): {r.text[:120]}")
    tx = (r.json() or {}).get("swapTransaction")
    if not tx:
        raise SolanaRefused("Jupiter n'a renvoyé aucune transaction")
    return tx


def sign(tx_b64: str, fichier: str | None = None) -> str:
    """Sign the transaction Jupiter built. Returns it serialised, ready to broadcast."""
    from solders.transaction import VersionedTransaction

    kp = _keypair(fichier)
    unsigned = VersionedTransaction.from_bytes(base64.b64decode(tx_b64))
    signed = VersionedTransaction(unsigned.message, [kp])
    return base64.b64encode(bytes(signed)).decode()


async def send(client: httpx.AsyncClient, rpc_url: str, signed_b64: str) -> str:
    """Broadcast a signed transaction, surviving a sending node that lags the one that built it.

    The router builds the transaction against the blockhash of whatever node it queried. Our own
    node may be a slot or two behind, and its preflight simulation then rejects a perfectly valid
    transaction with BlockhashNotFound -- two Solana entries were lost that way on 2026-09-08,
    RWA and CATECOIN, both refused before ever reaching the network. The blockhash is not stale,
    the simulator simply has not seen it, so the transaction is resent once with preflight off and
    left to the network to judge. A blockhash that really has expired costs nothing: the
    transaction is dropped rather than executed, and the reconciler writes the order off.
    """
    async def _post(skip: bool) -> dict[str, Any]:
        r = await client.post(rpc_url, json={
            "jsonrpc": "2.0", "id": 1, "method": "sendTransaction",
            "params": [signed_b64, {"encoding": "base64", "maxRetries": 3, "skipPreflight": skip}]}, timeout=30)
        return r.json() or {}

    body = await _post(False)
    err = str(body.get("error") or "")
    if "Blockhash not found" in err or "BlockhashNotFound" in err:
        body = await _post(True)
    if body.get("error"):
        raise SolanaRefused(f"envoi refusé: {str(body['error'])[:160]}")
    return str(body.get("result"))


async def token_balance(client: httpx.AsyncClient, rpc_url: str, owner: str, mint: str) -> int:
    """Raw units of ``mint`` held by ``owner`` -- what a sale is sized from, never an estimate."""
    r = await client.post(rpc_url, json={"jsonrpc": "2.0", "id": 1, "method": "getTokenAccountsByOwner",
                                         "params": [owner, {"mint": mint}, {"encoding": "jsonParsed"}]}, timeout=20)
    total = 0
    for acc in ((r.json() or {}).get("result") or {}).get("value") or []:
        info = acc["account"]["data"]["parsed"]["info"]["tokenAmount"]
        total += int(info.get("amount") or 0)
    return total


async def sol_delta(client: httpx.AsyncClient, rpc_url: str, tx_hash: str, owner: str) -> float | None:
    """SOL the wallet actually gained or lost in one confirmed transaction, fees included.

    The book used to price a sale from the quote taken just before it: on 2026-09-08 that reported
    +5.05 EUR on a line the chain paid +2.54 for, because the quote was right about the multiple
    and wrong about the stake. What a position earned is not what a router promised, it is the
    difference the wallet shows before and after -- the one number nothing can drift from.
    """
    try:
        r = await client.post(rpc_url, json={
            "jsonrpc": "2.0", "id": 1, "method": "getTransaction",
            "params": [tx_hash, {"maxSupportedTransactionVersion": 0, "encoding": "jsonParsed"}]}, timeout=25)
        res = (r.json() or {}).get("result")
        if not res or (res.get("meta") or {}).get("err"):
            return None
        keys = [k["pubkey"] if isinstance(k, dict) else k
                for k in res["transaction"]["message"]["accountKeys"]]
        if owner not in keys:
            return None
        i = keys.index(owner)
        meta = res["meta"]
        return (meta["postBalances"][i] - meta["preBalances"][i]) / LAMPORTS
    except Exception:  # noqa: BLE001
        return None


async def echange_reel(client: httpx.AsyncClient, rpc_url: str, tx_hash: str, owner: str,
                       mint: str) -> tuple[float, float] | None:
    """Ce qui a REELLEMENT change de mains dans une transaction : (SOL, jetons).

    `sol_delta` donne deja le SOL. Il manquait les JETONS, et leur rapport est le seul prix qu on
    ait vraiment paye ou encaisse.

    POURQUOI C EST INDISPENSABLE. Le livre enregistre `prix_entree`, une lecture du POOL prise
    quelques secondes avant l ordre. Sur ces jetons le prix bouge de 50 % en neuf secondes : cette
    lecture ne dit donc pas a quel prix on a achete. Le 14/09, TWINEGPT affichait un prix d entree
    de 4,05e-07 alors qu on a paye 8,56e-07 -- 63 % au-dessus. Sans le prix effectif, on ne peut pas
    distinguer « le jeton a baisse apres l achat » de « on a paye trop cher des l entree », et ces
    deux causes appellent des corrections opposees.

    Le SOL est signe (negatif a l achat), les jetons aussi. On rend les deux bruts : l appelant sait
    ce qu il lit.
    """
    try:
        r = await client.post(rpc_url, json={
            "jsonrpc": "2.0", "id": 1, "method": "getTransaction",
            "params": [tx_hash, {"maxSupportedTransactionVersion": 0,
                                 "encoding": "jsonParsed"}]}, timeout=25)
        res = (r.json() or {}).get("result")
        if not res or (res.get("meta") or {}).get("err"):
            return None
        keys = [k["pubkey"] if isinstance(k, dict) else k
                for k in res["transaction"]["message"]["accountKeys"]]
        if owner not in keys:
            return None
        meta = res["meta"]
        i = keys.index(owner)
        dsol = (meta["postBalances"][i] - meta["preBalances"][i]) / LAMPORTS

        def solde(cle: str) -> float:
            for b in (meta.get(cle) or []):
                if b.get("mint") == mint and b.get("owner") == owner:
                    return float((b.get("uiTokenAmount") or {}).get("uiAmountString") or 0)
            return 0.0

        return dsol, solde("postTokenBalances") - solde("preTokenBalances")
    except Exception:  # noqa: BLE001
        return None


async def sol_balance(client: httpx.AsyncClient, rpc_url: str, owner: str) -> int:
    r = await client.post(rpc_url, json={"jsonrpc": "2.0", "id": 1, "method": "getBalance",
                                         "params": [owner]}, timeout=20)
    return int(((r.json() or {}).get("result") or {}).get("value") or 0)


async def prepare_sell(client: httpx.AsyncClient, *, mint: str, amount: int, slippage_pct: float,
                       max_impact_pct: float = 100.0, priorite_lamports: int = 0,
                       proprietaire: str | None = None) -> dict[str, Any]:
    """Sell what the wallet holds, sized from the chain and never from the book.

    Leaving is not entering: the impact ceiling that protects a purchase from overpaying would,
    applied here, refuse to let go of a bag whose only alternative is zero. It stays wide open by
    default and exists only to catch a pool with nothing left in it.
    """
    if amount <= 0:
        return {"status": "REFUSED", "refused_reason": "rien a vendre"}
    try:
        q = await quote(client, input_mint=mint, output_mint=SOL_MINT, amount=amount,
                        slippage_bps=int(slippage_pct * 100))
    except SolanaRefused as exc:
        return {"status": "REFUSED", "refused_reason": str(exc)}
    if not q.usable:
        return {"status": "REFUSED", "refused_reason": "la chaine ne rend rien pour cette vente"}
    if q.price_impact_pct > max_impact_pct:
        return {"status": "REFUSED", "refused_reason": f"impact de sortie {q.price_impact_pct:.1f} % > {max_impact_pct:.0f} %"}
    owner = proprietaire or signer_address()
    if owner is None:
        return {"status": "BUILT", "amount_in": str(amount), "quoted_amount_out": str(q.out_amount),
                "slippage_pct": q.price_impact_pct, "route": q.route,
                "refused_reason": "aucune cle : transaction non assemblee (a blanc)"}
    try:
        tx, q = await _construire_sous_limite(
            client, q, owner, priorite_lamports, input_mint=mint, output_mint=SOL_MINT,
            amount=amount, slippage_bps=int(slippage_pct * 100))
    except SolanaRefused as exc:
        return {"status": "REFUSED", "refused_reason": str(exc)}
    return {"status": "BUILT", "amount_in": str(amount), "quoted_amount_out": str(q.out_amount),
            "slippage_pct": q.price_impact_pct, "route": q.route, "tx": tx}


LIMITE_TX = 1232          # octets : le maximum absolu d une transaction Solana
MARGE_TX = 1180           # au-dela, on recote une route plus courte avant de tenter l envoi


async def _construire_sous_limite(client: httpx.AsyncClient, q: SolanaQuote, owner: str,
                                  priorite_lamports: int, *, input_mint: str, output_mint: str,
                                  amount: int, slippage_bps: int) -> tuple[str, SolanaQuote]:
    """Assembler la transaction, et si elle frole la limite de taille, recoter plus court.

    Solana refuse toute transaction depassant 1 232 octets. Jupiter compose parfois une route a
    plusieurs sauts qui la franchit : le 09/09, deux ordres sur 747 ont ete rejetes a 1 233 octets,
    UN octet de trop. L argent n etait pas perdu -- le refus arrive avant l envoi -- mais l occasion
    l etait, pour une raison purement technique.

    On ne bride pas les routes par defaut : ce serait degrader 99,7 % des ordres pour en sauver 0,3.
    On mesure la transaction reellement construite, et on ne recote que si elle est au-dessus de la
    marge, en resserrant le nombre de comptes autorises jusqu a passer.
    """
    tx = await build_swap(client, q, owner, priorite_lamports)
    taille = len(base64.b64decode(tx))
    if taille <= MARGE_TX:
        return tx, q
    for comptes in (40, 32, 24):
        try:
            q2 = await quote(client, input_mint=input_mint, output_mint=output_mint,
                             amount=amount, slippage_bps=slippage_bps, max_comptes=comptes)
            if not q2.usable:
                continue
            tx2 = await build_swap(client, q2, owner, priorite_lamports)
            if len(base64.b64decode(tx2)) <= MARGE_TX:
                log.info("solana: route raccourcie a %d comptes (%d -> %d octets)",
                         comptes, taille, len(base64.b64decode(tx2)))
                return tx2, q2
        except SolanaRefused:
            continue
    if taille > LIMITE_TX:
        raise SolanaRefused(f"transaction de {taille} octets, la chaine refuse au-dela de {LIMITE_TX}")
    return tx, q                          # sous la limite absolue : on tente


async def prepare_buy(client: httpx.AsyncClient, *, mint: str, size_eur: float, sol_eur: float,
                      slippage_pct: float, max_impact_pct: float, priorite_lamports: int = 0,
                      max_aller_retour_pct: float = 0.0, prix_pool_sol: float = 0.0,
                      decimales: int = 6, max_ecart_pool_pct: float = 0.0,
                      proprietaire: str | None = None) -> dict[str, Any]:
    """Everything but the signature: what the journal records, in dry run and live alike."""
    lamports = int(size_eur / max(sol_eur, 1e-9) * LAMPORTS)
    if lamports <= 0:
        return {"status": "REFUSED", "refused_reason": "taille d'ordre non convertible en lamports"}
    try:
        q = await quote(client, input_mint=SOL_MINT, output_mint=mint, amount=lamports,
                        slippage_bps=int(slippage_pct * 100))
    except SolanaRefused as exc:
        return {"status": "REFUSED", "refused_reason": str(exc)}
    if not q.usable:
        return {"status": "REFUSED", "refused_reason": "la cotation ne rend rien"}
    if q.price_impact_pct > max_impact_pct:
        return {"status": "REFUSED", "amount_in": str(lamports),
                "refused_reason": f"impact {q.price_impact_pct:.1f} % > plafond {max_impact_pct:.1f} %"}
    # LA COTATION EST-ELLE AU PRIX DU MARCHE ? On la compare a NOTRE propre lecture du pool.
    #
    # `slippage_pct` ne protege pas de ca : il borne la derive entre la cotation et l atterrissage
    # de la transaction, pas l ecart entre cette cotation et le vrai prix. Si le routeur cote 60 %
    # trop cher, on signe sans broncher. Mesure du 14/09 sur 60 tickets reels, prix effectif lu
    # dans la transaction confirmee contre prix du pool au meme instant :
    #
    #     ecart median +5,8 %  ·  p90 +32,8 %  ·  max +74,0 %
    #
    # Et les trois plus grosses pertes de la journee sont trois achats payes 28 a 59 % trop cher --
    # gptstonks -90 EUR (+59 %), BEMJAK -87 EUR (+47 %), IRONMIKE -43 EUR (+28 %). Ce n etait pas le
    # signal qui etait mauvais, c etait le prix d entree.
    #
    #     seuil de refus   refuses   total des 60 tickets
    #     aucun (avant)       0 %          -52,58 EUR
    #     plus de 30 %       10 %         +110,83 EUR
    #     plus de 20 %       18 %         +130,02 EUR   <- retenu
    #     plus de 10 %       40 %          -54,25 EUR   (jette trop)
    #
    # Ce controle ne coute AUCUN appel : le prix du pool est deja lu toutes les dix secondes par le
    # collecteur, et il ne depend d aucune promesse du routeur -- c est sa valeur.
    if max_ecart_pool_pct > 0 and prix_pool_sol > 0 and q.out_amount > 0:
        jetons = q.out_amount / (10 ** decimales)
        implique = (lamports / LAMPORTS) / jetons if jetons > 0 else 0.0
        if implique > 0:
            ecart = (implique / prix_pool_sol - 1) * 100
            if ecart > max_ecart_pool_pct:
                return {"status": "REFUSED", "amount_in": str(lamports),
                        "refused_reason": f"cotation {ecart:.1f} % au-dessus du pool "
                                          f"> plafond {max_ecart_pool_pct:.1f} %"}
    # PEUT-ON RESSORTIR ? On cote la revente immediate de ce qu on recevrait, avant d acheter.
    #
    # Mesure du 09/09 sur 25 pools suivis : un aller-retour de 20 EUR coute 2,9 % en mediane -- mais
    # SIX pools sur vingt-cinq coutent plus de 10 %, CINQ plus de 25 %, et le pire ne rend que 1,3 %
    # de la mise. Sur ces pools-la on peut acheter et pas ressortir, a notre taille.
    #
    # Ce chiffre colle a ce qui detruit le carnet : sept tickets sur vingt-huit anaeantis (25 %),
    # contre cinq pools sur vingt-cinq (20 %) invendables. Ce n est donc pas le prix qui s effondre,
    # c est qu on n aurait jamais du entrer. Aucune regle de SORTIE ne repare ca -- le stop, la
    # boucle rapide et les frais de priorite ne servent a rien quand la contrepartie n existe pas.
    # La seule reponse est de ne pas entrer, et ca se sait avant, pour une cotation de plus.
    #
    # L impact affiche a l achat ne suffit pas : il est de 1,11 % en mediane a l achat contre 1,15 %
    # a la vente, donc symetrique EN MOYENNE -- et c est precisement sur les pools asymetriques,
    # ceux qui coutent 25 % ou 98 %, qu il ne dit rien. Il faut coter le retour.
    if max_aller_retour_pct > 0:
        try:
            retour = await quote(client, input_mint=mint, output_mint=SOL_MINT,
                                 amount=q.out_amount, slippage_bps=int(slippage_pct * 100))
            perte = (1 - retour.out_amount / lamports) * 100 if retour.usable else 100.0
        except SolanaRefused as exc:
            return {"status": "REFUSED", "amount_in": str(lamports),
                    "refused_reason": f"revente non cotable ({str(exc)[:50]})"}
        if perte > max_aller_retour_pct:
            return {"status": "REFUSED", "amount_in": str(lamports),
                    "refused_reason": f"aller-retour {perte:.1f} % > plafond {max_aller_retour_pct:.1f} % "
                                      f"(on entrerait sans pouvoir ressortir)"}
    owner = proprietaire or signer_address()
    if owner is None:
        return {"status": "BUILT", "amount_in": str(lamports), "quoted_amount_out": str(q.out_amount),
                "slippage_pct": q.price_impact_pct, "route": q.route,
                "refused_reason": "aucune clé : transaction non assemblée (à blanc)"}
    try:
        tx, q = await _construire_sous_limite(
            client, q, owner, priorite_lamports, input_mint=SOL_MINT, output_mint=mint,
            amount=lamports, slippage_bps=int(slippage_pct * 100))
    except SolanaRefused as exc:
        return {"status": "REFUSED", "refused_reason": str(exc)}
    return {"status": "BUILT", "amount_in": str(lamports), "quoted_amount_out": str(q.out_amount),
            "slippage_pct": q.price_impact_pct, "route": q.route, "tx": tx}
