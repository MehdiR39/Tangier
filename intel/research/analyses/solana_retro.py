"""Answer tonight instead of tomorrow: take Solana launches already hours old and read both ends.

Waiting for new launches to age is unnecessary. A pool that opened three hours ago has both halves
of the question already written on the chain: what its first minute looked like, and what became of
it since. This reads them together, so the study that would take a night takes twenty minutes.

The question is the one Robinhood Chain could not answer. There, 73 % of what this book bought was
rugged within a minute of the purchase and no pre-buy signal separated the victims: the swap
`sender` is a router for 98 % of trades, so "how many distinct people are buying" was unknowable.
On Solana the payer of each transaction is in plain sight, and the first measurements show the gap
the Robinhood data could not: 2 834 trades between 40 wallets on one launchpad, 343 trades between
139 wallets on another. If that ratio predicts which pools still let people sell hours later, it is
the filter Robinhood never had.

Read-only. Nothing here trades, and no Solana wallet exists.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import statistics
import time
from typing import Any

import httpx

DEX_SEARCH = "https://api.dexscreener.com/latest/dex/search?q="
PAIRS_URL = "https://api.dexscreener.com/latest/dex/tokens/"


async def recent_pairs(client: httpx.AsyncClient, queries: tuple[str, ...], min_age_h: float,
                       max_age_h: float) -> list[dict[str, Any]]:
    """Solana pairs whose age is inside the window, from DexScreener's search."""
    now = time.time() * 1000
    seen: dict[str, dict[str, Any]] = {}
    for q in queries:
        try:
            r = await client.get(DEX_SEARCH + q, timeout=30)
            pairs = (r.json() or {}).get("pairs") or []
        except Exception:  # noqa: BLE001
            continue
        for p in pairs:
            if p.get("chainId") != "solana" or not p.get("pairCreatedAt"):
                continue
            age_h = (now - p["pairCreatedAt"]) / 3_600_000
            if min_age_h <= age_h <= max_age_h:
                seen[p["pairAddress"]] = p
        await asyncio.sleep(0.4)
    return list(seen.values())


async def first_minute(client: httpx.AsyncClient, rpc: str, key: str, pair_id: str, created_ms: int) -> dict[str, Any]:
    start = created_ms // 1000
    sigs: list[dict[str, Any]] = []
    before = None
    for _ in range(8):
        params: dict[str, Any] = {"limit": 1000}
        if before:
            params["before"] = before
        try:
            r = await client.post(rpc, json={"jsonrpc": "2.0", "id": 1, "method": "getSignaturesForAddress",
                                             "params": [pair_id, params]}, timeout=45)
            got = (r.json() or {}).get("result") or []
        except Exception:  # noqa: BLE001
            return {}
        if not got:
            break
        sigs.extend(got)
        before = got[-1]["signature"]
        if (got[-1].get("blockTime") or 0) <= start:
            break
    window = [g for g in sigs if g.get("blockTime") and start <= g["blockTime"] <= start + 60]
    if not window:
        return {"trades": 0, "payers": 0}
    payers: set[str] = set()
    if key:
        for i in range(0, min(len(window), 500), 100):
            try:
                r = await client.post(f"https://api.helius.xyz/v0/transactions/?api-key={key}",
                                      json={"transactions": [w["signature"] for w in window[i:i + 100]]}, timeout=60)
                for tx in r.json() or []:
                    if tx.get("feePayer"):
                        payers.add(tx["feePayer"])
            except Exception:  # noqa: BLE001
                break
    return {"trades": len(window), "payers": len(payers)}


def alive(p: dict[str, Any]) -> bool:
    """Is anyone still able to trade this pool? Sales in the last hour, and liquidity left to pay them."""
    txns = (p.get("txns") or {}).get("h1") or {}
    liq = float((p.get("liquidity") or {}).get("usd") or 0)
    return (txns.get("sells") or 0) > 0 and liq > 500


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--min-age-h", type=float, default=2.0)
    ap.add_argument("--max-age-h", type=float, default=12.0)
    ap.add_argument("--limit", type=int, default=40)
    args = ap.parse_args()
    rpc = (os.environ.get("SOLANA_RPC_URL") or "").strip()
    if not rpc:
        print("SOLANA_RPC_URL absent : mesure impossible")
        return
    key = rpc.split("api-key=")[-1] if "api-key=" in rpc else ""
    queries = ("SOL", "USDC", "pump", "bonk", "cat", "dog", "ai", "moon", "trump", "meme")
    async with httpx.AsyncClient(headers={"User-Agent": "tangier-intel/solana-retro"}) as client:
        pairs = await recent_pairs(client, queries, args.min_age_h, args.max_age_h)
        pairs = pairs[: args.limit]
        print(f"{len(pairs)} lancements Solana ages de {args.min_age_h:g} a {args.max_age_h:g} h\n")
        rows = []
        for p in pairs:
            fm = await first_minute(client, rpc, key, p["pairAddress"], p["pairCreatedAt"])
            if not fm or not fm.get("trades"):
                continue
            rows.append({
                "symbol": (p.get("baseToken") or {}).get("symbol") or "?",
                "dex": p.get("dexId"), "trades": fm["trades"], "payers": fm["payers"],
                "ratio": fm["trades"] / max(fm["payers"], 1),
                "alive": alive(p),
                "liq": float((p.get("liquidity") or {}).get("usd") or 0),
                "age_h": (time.time() * 1000 - p["pairCreatedAt"]) / 3_600_000,
            })
            await asyncio.sleep(0.3)
        if not rows:
            print("aucune mesure exploitable")
            return
        n_alive = sum(1 for r in rows if r["alive"])
        print(f"{n_alive}/{len(rows)} laissent encore vendre apres {args.min_age_h:g}-{args.max_age_h:g} h "
              f"({n_alive / len(rows):.0%})\n")
        print(f"  {'acheteurs distincts':>22}{'n':>5}{'encore vendable':>18}{'liquidite mediane':>19}")
        for lo, hi, lab in ((0, 20, "moins de 20"), (20, 50, "20 a 50"), (50, 100, "50 a 100"), (100, 10 ** 9, "plus de 100")):
            g = [r for r in rows if lo <= r["payers"] < hi]
            if len(g) < 3:
                continue
            liq = statistics.median(r["liq"] for r in g)
            print(f"  {lab:>22}{len(g):>5}{sum(1 for r in g if r['alive']) / len(g):>17.0%}{liq:>18,.0f}$")
        print(f"\n  {'echanges par acheteur':>22}{'n':>5}{'encore vendable':>18}")
        for lo, hi, lab in ((0, 3, "moins de 3"), (3, 10, "3 a 10"), (10, 30, "10 a 30"), (30, 10 ** 9, "plus de 30")):
            g = [r for r in rows if lo <= r["ratio"] < hi]
            if len(g) < 3:
                continue
            print(f"  {lab:>22}{len(g):>5}{sum(1 for r in g if r['alive']) / len(g):>17.0%}")
        print(f"\n  {'launchpad':>22}{'n':>5}{'encore vendable':>18}")
        for dex in sorted({r["dex"] for r in rows}):
            g = [r for r in rows if r["dex"] == dex]
            if len(g) < 3:
                continue
            print(f"  {str(dex):>22}{len(g):>5}{sum(1 for r in g if r['alive']) / len(g):>17.0%}")


if __name__ == "__main__":
    asyncio.run(main())
