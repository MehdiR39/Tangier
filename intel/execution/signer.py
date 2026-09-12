"""Sign and submit one transaction.

The private key is read from the environment at the moment of signing and never stored, cached,
returned or logged. Nothing else in this package touches it: everything upstream works with an
unsigned order, so the whole pipeline can be exercised without a key existing at all.

Refusals are deliberate and loud. A missing key, a mode that is not ``live``, a chain id that
does not match the configured chain, an estimate that reverts — each aborts before anything is
broadcast, because a transaction cannot be recalled once it is.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

from intel.context import IntelContext

log = logging.getLogger(__name__)

KEY_ENV = "INTEL_EXECUTION_PRIVATE_KEY"
GAS_HEADROOM = 1.25          # estimates are tight; a revert for out-of-gas still costs the gas
FEE_HEADROOM = 2.0           # base fee can double between estimate and inclusion


class SigningRefused(RuntimeError):
    """Raised instead of broadcasting whenever a precondition is not met."""


@dataclass(frozen=True)
class SignedTx:
    raw: str
    tx_hash: str
    from_address: str
    nonce: int
    gas: int
    max_fee_per_gas: int
    value_wei: int


def _load_account() -> Any:
    """Derive the account from the environment. The key never leaves this function."""
    key = os.environ.get(KEY_ENV, "").strip()
    if not key:
        raise SigningRefused(f"aucune clé dans {KEY_ENV} : rien n'est signé")
    try:
        from eth_account import Account
    except ImportError as exc:  # pragma: no cover - dependency is declared in requirements
        raise SigningRefused(f"bibliothèque de signature absente: {exc}") from exc
    try:
        return Account.from_key(key if key.startswith("0x") else "0x" + key)
    except Exception as exc:
        raise SigningRefused("clé privée illisible") from exc  # never echo the value


def signer_address() -> str | None:
    """The address that would sign, or None when no key is configured. Public information."""
    try:
        return _load_account().address.lower()
    except SigningRefused:
        return None


def verifier_arret(ctx: IntelContext, *, sortie: bool) -> None:
    """L arret d urgence bloque ce qui DEPENSE, jamais ce qui SORT.

    Ce second controle doublait celui de safety.check, mais sans connaitre le sens de l ordre. Le
    10/09 a 03h05 la vente de moitie de DOGSHIT, declenchee a x2,98 comme l operateur l avait
    demande, a passe la porte de securite (corrigee la veille) et a ete refusee ICI. Un arret pose
    pour empecher le scanner d acheter a empeche l operateur d encaisser (§5.24). Une sortie n est
    jamais un risque de depense : elle passe.
    """
    if bool(ctx.config.get("execution.kill_switch", False)) and not sortie:
        raise SigningRefused("arrêt d'urgence actif")


async def build_and_sign(ctx: IntelContext, *, to: str, data: str, value_wei: int, gas_limit: int | None = None,
                         sortie: bool = False) -> SignedTx:
    """Assemble an EIP-1559 transaction, estimate it, and sign it. Nothing is broadcast here.

    `sortie` dit que l ordre fait SORTIR un jeton (vente, ou autorisation prealable a une vente) ;
    l arret d urgence ne le bloque pas. Un appelant qui ne le precise pas est traite comme un achat.
    """
    if str(ctx.config.get("execution.mode", "dry_run")) != "live":
        raise SigningRefused("mode d'exécution = dry_run : rien n'est signé")
    verifier_arret(ctx, sortie=sortie)
    account = _load_account()
    sender = account.address

    chain_id_hex = await ctx.rpc.request("eth_chainId", [])
    chain_id = int(chain_id_hex, 16)
    if chain_id != ctx.chain_id:
        raise SigningRefused(f"le nœud répond chain_id {chain_id}, attendu {ctx.chain_id}")

    nonce = int(await ctx.rpc.request("eth_getTransactionCount", [sender, "pending"]), 16)
    # eth-account refuses a lowercase "to" ("Transaction had invalid fields"): the first order
    # through the corrected router (2026-09-07) died on that alone. Checksum it here, always.
    from eth_utils import to_checksum_address
    to = to_checksum_address(to)
    tx: dict[str, Any] = {"from": sender, "to": to, "data": data, "value": hex(int(value_wei))}
    if gas_limit is None:
        # An estimate that reverts is the cheapest possible refusal: it costs nothing and it means
        # the swap would have failed on-chain after paying gas.
        try:
            gas_limit = int(await ctx.rpc.request("eth_estimateGas", [tx]), 16)
        except Exception as exc:
            # The revert data carries the custom error selector (four bytes): the one thing that
            # says WHY the chain refuses. Without it the first live day (2026-09-07) logged five
            # "execution reverted" with nothing to diagnose.
            data = getattr(exc, "data", None) or (exc.args[2] if len(exc.args) > 2 else None)
            why = f" · revert {str(data)[:10]}" if data else ""
            raise SigningRefused(f"l'estimation échoue, la transaction échouerait aussi: {str(exc)[:160]}{why}") from exc
    gas = int(gas_limit * GAS_HEADROOM)

    base_hex = await ctx.rpc.request("eth_gasPrice", [])
    base = int(base_hex, 16)
    try:
        tip = int(await ctx.rpc.request("eth_maxPriorityFeePerGas", []), 16)
    except Exception:
        tip = base // 10
    max_fee = int(base * FEE_HEADROOM) + tip

    unsigned = {
        "type": 2, "chainId": chain_id, "nonce": nonce, "to": to, "data": data,
        "value": int(value_wei), "gas": gas, "maxFeePerGas": max_fee, "maxPriorityFeePerGas": tip,
    }
    signed = account.sign_transaction(unsigned)
    raw = signed.raw_transaction.hex() if hasattr(signed, "raw_transaction") else signed.rawTransaction.hex()
    raw = raw if raw.startswith("0x") else "0x" + raw
    tx_hash = signed.hash.hex() if hasattr(signed, "hash") else signed.hash
    tx_hash = tx_hash if str(tx_hash).startswith("0x") else "0x" + str(tx_hash)
    log.info("transaction signée par %s nonce=%d gas=%d maxFee=%d", sender, nonce, gas, max_fee)
    return SignedTx(raw=raw, tx_hash=tx_hash, from_address=sender.lower(), nonce=nonce, gas=gas,
                    max_fee_per_gas=max_fee, value_wei=int(value_wei))


async def broadcast(ctx: IntelContext, signed: SignedTx) -> str:
    """Send a signed transaction. Irreversible: called only after the safety envelope has passed."""
    return await ctx.rpc.request("eth_sendRawTransaction", [signed.raw])


async def wait_receipt(ctx: IntelContext, tx_hash: str, *, attempts: int = 30, delay_s: float = 2.0) -> dict[str, Any] | None:
    """Poll for the receipt. Returns None when it never appears, which is not the same as failure."""
    import asyncio

    for _ in range(attempts):
        try:
            r = await ctx.rpc.request("eth_getTransactionReceipt", [tx_hash])
            if r:
                return r
        except Exception as exc:  # noqa: BLE001
            log.warning("lecture du reçu %s: %s", tx_hash[:12], exc)
        await asyncio.sleep(delay_s)
    return None
