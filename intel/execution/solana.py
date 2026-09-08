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


def signer_address() -> str | None:
    """The address that would sign, or None when no key is configured. Public information."""
    try:
        return str(_keypair().pubkey())
    except SolanaRefused:
        return None


def _keypair() -> Any:
    """Derive the keypair from the environment. The key never leaves this function."""
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
                slippage_bps: int) -> SolanaQuote:
    r = await client.get(f"{JUPITER}/quote", params={"inputMint": input_mint, "outputMint": output_mint,
                                                     "amount": amount, "slippageBps": slippage_bps}, timeout=20)
    if r.status_code != 200:
        raise SolanaRefused(f"cotation refusée ({r.status_code}): {r.text[:120]}")
    q = r.json()
    routes = [x.get("swapInfo", {}).get("label") for x in q.get("routePlan") or []]
    return SolanaQuote(in_lamports=int(q.get("inAmount") or 0), out_amount=int(q.get("outAmount") or 0),
                       price_impact_pct=float(q.get("priceImpactPct") or 0) * 100,
                       route=" > ".join(str(x) for x in routes if x), raw=q)


async def build_swap(client: httpx.AsyncClient, q: SolanaQuote, owner: str) -> str:
    """The serialised transaction Jupiter has already assembled; only the signature is missing."""
    r = await client.post(f"{JUPITER}/swap", json={"quoteResponse": q.raw, "userPublicKey": owner,
                                                   "wrapAndUnwrapSol": True,
                                                   "dynamicComputeUnitLimit": True}, timeout=25)
    if r.status_code != 200:
        raise SolanaRefused(f"construction refusée ({r.status_code}): {r.text[:120]}")
    tx = (r.json() or {}).get("swapTransaction")
    if not tx:
        raise SolanaRefused("Jupiter n'a renvoyé aucune transaction")
    return tx


def sign(tx_b64: str) -> str:
    """Sign the transaction Jupiter built. Returns it serialised, ready to broadcast."""
    from solders.transaction import VersionedTransaction

    kp = _keypair()
    unsigned = VersionedTransaction.from_bytes(base64.b64decode(tx_b64))
    signed = VersionedTransaction(unsigned.message, [kp])
    return base64.b64encode(bytes(signed)).decode()


async def send(client: httpx.AsyncClient, rpc_url: str, signed_b64: str) -> str:
    r = await client.post(rpc_url, json={"jsonrpc": "2.0", "id": 1, "method": "sendTransaction",
                                         "params": [signed_b64, {"encoding": "base64", "maxRetries": 3}]}, timeout=30)
    body = r.json()
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


async def sol_balance(client: httpx.AsyncClient, rpc_url: str, owner: str) -> int:
    r = await client.post(rpc_url, json={"jsonrpc": "2.0", "id": 1, "method": "getBalance",
                                         "params": [owner]}, timeout=20)
    return int(((r.json() or {}).get("result") or {}).get("value") or 0)


async def prepare_sell(client: httpx.AsyncClient, *, mint: str, amount: int, slippage_pct: float,
                       max_impact_pct: float = 100.0) -> dict[str, Any]:
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
    owner = signer_address()
    if owner is None:
        return {"status": "BUILT", "amount_in": str(amount), "quoted_amount_out": str(q.out_amount),
                "slippage_pct": q.price_impact_pct, "route": q.route,
                "refused_reason": "aucune cle : transaction non assemblee (a blanc)"}
    try:
        tx = await build_swap(client, q, owner)
    except SolanaRefused as exc:
        return {"status": "REFUSED", "refused_reason": str(exc)}
    return {"status": "BUILT", "amount_in": str(amount), "quoted_amount_out": str(q.out_amount),
            "slippage_pct": q.price_impact_pct, "route": q.route, "tx": tx}


async def prepare_buy(client: httpx.AsyncClient, *, mint: str, size_eur: float, sol_eur: float,
                      slippage_pct: float, max_impact_pct: float) -> dict[str, Any]:
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
    owner = signer_address()
    if owner is None:
        return {"status": "BUILT", "amount_in": str(lamports), "quoted_amount_out": str(q.out_amount),
                "slippage_pct": q.price_impact_pct, "route": q.route,
                "refused_reason": "aucune clé : transaction non assemblée (à blanc)"}
    try:
        tx = await build_swap(client, q, owner)
    except SolanaRefused as exc:
        return {"status": "REFUSED", "refused_reason": str(exc)}
    return {"status": "BUILT", "amount_in": str(lamports), "quoted_amount_out": str(q.out_amount),
            "slippage_pct": q.price_impact_pct, "route": q.route, "tx": tx}
