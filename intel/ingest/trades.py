"""Trade reconstruction from raw Transfer + Uniswap v4 Swap events.

Why not ``tx.from``: on Robinhood Chain app trades are routed through the RobinHoodSettler
and the ERC-4337 EntryPoint, so the transaction sender is a bundler/settler, not the
trader. The economic trader is the address whose *net* token balance changed inside the
transaction, after removing system addresses (pool manager, hooks, routers, settlers).
Doppler launch pools also emit extra hook-internal ``Swap`` events (fee re-hypothecation),
which are excluded via the ``hook:`` label on the swap ``sender``.
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from intel.chain.uniswap_v4 import SwapEvent, swap_token_and_quote_deltas
from intel.context import IntelContext
from intel.ingest.pools import PoolInfo
from intel.metrics.pricing import QuotePricer
from intel.utils.abi import ZERO_ADDRESS
from intel.utils.timeutil import now_ts

log = logging.getLogger(__name__)
SOURCE = "rpc_reconstruction"
MISMATCH_TOLERANCE = 0.05


@dataclass
class TransferRow:
    tx_hash: str
    log_index: int
    block_number: int
    ts: int | None
    from_address: str
    to_address: str
    value: int


@dataclass
class Trade:
    tx_hash: str
    token_address: str
    trader: str
    block_number: int
    ts: int | None
    log_index: int
    pair_id: str | None
    side: str  # BUY / SELL / ROUNDTRIP
    token_amount: int
    token_amount_float: float
    quote_address: str | None
    quote_amount_float: float | None
    price_native: float | None
    price_usd: float | None
    usd_value: float | None
    swap_log_count: int
    quality_flags: list[str] = field(default_factory=list)

    def as_row(self, chain_id: int) -> dict[str, Any]:
        return {
            "chain_id": chain_id, "tx_hash": self.tx_hash, "token_address": self.token_address, "trader": self.trader,
            "block_number": self.block_number, "ts": self.ts, "log_index": self.log_index, "pair_id": self.pair_id, "side": self.side,
            "token_amount": str(self.token_amount), "token_amount_float": self.token_amount_float,
            "quote_address": self.quote_address, "quote_amount_float": self.quote_amount_float,
            "price_native": self.price_native, "price_usd": self.price_usd, "usd_value": self.usd_value,
            "swap_log_count": self.swap_log_count, "source": SOURCE, "quality_flags": json.dumps(self.quality_flags),
        }


def reconstruct_tx_trades(
    token: str,
    token_decimals: int,
    transfers: list[TransferRow],
    swaps: list[SwapEvent],
    pools: dict[str, PoolInfo],
    system_label: Callable[[str], str | None],
    quote_decimals: Callable[[str], int | None],
    quote_usd: Callable[[str, int | None], tuple[float | None, list[str]]],
) -> list[Trade]:
    token = token.lower()
    if not transfers and not swaps:
        return []
    tx_hash = (transfers[0].tx_hash if transfers else swaps[0].tx_hash)
    block = transfers[0].block_number if transfers else swaps[0].block_number
    ts = transfers[0].ts if transfers else None
    min_li = min([t.log_index for t in transfers] + [s.log_index for s in swaps])

    # 1. net token deltas per address, excluding system addresses (routers/settlers net to 0 anyway)
    net: dict[str, int] = defaultdict(int)
    gross_in: dict[str, int] = defaultdict(int)
    gross_out: dict[str, int] = defaultdict(int)
    in_from: dict[str, set[str]] = defaultdict(set)
    out_to: dict[str, set[str]] = defaultdict(set)
    for t in transfers:
        if t.from_address != ZERO_ADDRESS:
            net[t.from_address] -= t.value
            gross_out[t.from_address] += t.value
            out_to[t.from_address].add(t.to_address)
        if t.to_address != ZERO_ADDRESS:
            net[t.to_address] += t.value
            gross_in[t.to_address] += t.value
            in_from[t.to_address].add(t.from_address)
    buyers = {a: d for a, d in net.items() if d > 0 and system_label(a) is None}
    sellers = {a: -d for a, d in net.items() if d < 0 and system_label(a) is None}
    # A same-tx round trip is a wallet that received from AND returned to the pool/system side.
    # Unlabeled pass-through contracts in a transfer chain (PM -> router -> user) also net to
    # zero but have a non-system counterparty on one leg, so they are ignored, not flagged.
    roundtrips = {
        a: min(gross_in[a], gross_out[a])
        for a in net
        if net[a] == 0 and gross_in[a] > 0 and gross_out[a] > 0 and system_label(a) is None
        and all(system_label(x) is not None for x in in_from[a]) and all(system_label(x) is not None for x in out_to[a])
    }

    # 2. user-level swaps by side (hook-internal swaps excluded)
    buys: list[tuple[PoolInfo, int, int]] = []
    sells: list[tuple[PoolInfo, int, int]] = []
    internal = 0
    for s in swaps:
        pi = pools.get(s.pool_id)
        if pi is None:
            continue
        lbl = system_label(s.sender)
        if lbl and lbl.startswith("hook:"):
            internal += 1
            continue
        td, qd = swap_token_and_quote_deltas(s, pi.token_is_currency0)
        if td > 0:
            buys.append((pi, td, qd))
        elif td < 0:
            sells.append((pi, td, qd))

    out: list[Trade] = []
    scale = 10 ** token_decimals

    def _emit(side: str, parties: dict[str, int], side_swaps: list[tuple[PoolInfo, int, int]]) -> None:
        if not parties:
            return
        flags: list[str] = []
        tot_parties = sum(parties.values())
        pair_id = None
        quote_addr = None
        quote_total_raw = 0
        tot_tok_swaps = 0
        if side_swaps:
            # dominant quote by token volume
            by_quote: dict[str, int] = defaultdict(int)
            for pi, td, _qd in side_swaps:
                by_quote[pi.quote_address] += abs(td)
            quote_addr = max(by_quote, key=by_quote.get)
            if len(by_quote) > 1:
                flags.append("multi_quote_tx")
            primary = max((x for x in side_swaps if x[0].quote_address == quote_addr), key=lambda x: abs(x[1]))
            pair_id = primary[0].pair_id
            quote_total_raw = sum(abs(qd) for pi, _td, qd in side_swaps if pi.quote_address == quote_addr)
            tot_tok_swaps = sum(abs(td) for pi, td, _ in side_swaps if pi.quote_address == quote_addr)
            if tot_tok_swaps and abs(tot_parties - tot_tok_swaps) / max(tot_parties, tot_tok_swaps) > MISMATCH_TOLERANCE:
                flags.append("transfer_swap_mismatch")
        else:
            flags.append("no_user_swap")  # plain wallet-to-wallet transfer, not a trade
            return
        qdec = quote_decimals(quote_addr) if quote_addr else None
        if qdec is None:
            flags.append("quote_decimals_unknown")
        qusd, qflags = quote_usd(quote_addr, ts) if quote_addr else (None, ["quote_unknown"])
        flags.extend(qflags)
        # Price comes from the swaps themselves (exact); each party's quote leg is implied from
        # its token amount at that price. Attributing the raw quote total proportionally would
        # explode prices whenever transfers and swaps disagree (routers keeping part of the flow).
        swap_price_native = None
        if qdec is not None and quote_total_raw and tot_tok_swaps:
            swap_price_native = (quote_total_raw / (10 ** qdec)) / (tot_tok_swaps / scale)
        for addr, amt in parties.items():
            token_float = amt / scale
            price_native = swap_price_native
            quote_float = (token_float * price_native) if price_native is not None else None
            price_usd = (price_native * qusd) if (price_native is not None and qusd is not None) else None
            usd_value = (quote_float * qusd) if (quote_float is not None and qusd is not None) else None
            out.append(Trade(
                tx_hash=tx_hash, token_address=token, trader=addr, block_number=block, ts=ts, log_index=min_li, pair_id=pair_id, side=side,
                token_amount=amt, token_amount_float=token_float, quote_address=quote_addr, quote_amount_float=quote_float,
                price_native=price_native, price_usd=price_usd, usd_value=usd_value, swap_log_count=len(side_swaps) + internal, quality_flags=list(flags),
            ))

    _emit("BUY", buyers, buys)
    _emit("SELL", sellers, sells)
    for addr, amt in roundtrips.items():
        if not (buys or sells):
            continue
        out.append(Trade(
            tx_hash=tx_hash, token_address=token, trader=addr, block_number=block, ts=ts, log_index=min_li,
            pair_id=(buys or sells)[0][0].pair_id, side="ROUNDTRIP", token_amount=amt, token_amount_float=amt / scale,
            quote_address=(buys or sells)[0][0].quote_address, quote_amount_float=None, price_native=None, price_usd=None, usd_value=None,
            swap_log_count=len(buys) + len(sells) + internal, quality_flags=["same_tx_roundtrip"],
        ))
    return out


# --------------------------------------------------------------------------- #
# DB-driven ingestion
# --------------------------------------------------------------------------- #
def _load_transfers(ctx: IntelContext, token: str, a: int, b: int) -> dict[str, list[TransferRow]]:
    rows = ctx.db.query(
        "SELECT tx_hash, log_index, block_number, ts, from_address, to_address, value FROM transfers WHERE chain_id=? AND token_address=? AND block_number BETWEEN ? AND ? ORDER BY block_number, log_index",
        (ctx.chain_id, token, a, b),
    )
    out: dict[str, list[TransferRow]] = defaultdict(list)
    for r in rows:
        out[r["tx_hash"]].append(TransferRow(r["tx_hash"], r["log_index"], r["block_number"], r["ts"], r["from_address"], r["to_address"], int(r["value"])))
    return out


def _load_swaps(ctx: IntelContext, pool_ids: Iterable[str], a: int, b: int) -> dict[str, list[SwapEvent]]:
    ids = list(pool_ids)
    if not ids:
        return {}
    rows = ctx.db.query(
        f"SELECT * FROM swap_events WHERE chain_id=? AND pair_id IN ({','.join('?' for _ in ids)}) AND block_number BETWEEN ? AND ? ORDER BY block_number, log_index",
        (ctx.chain_id, *ids, a, b),
    )
    out: dict[str, list[SwapEvent]] = defaultdict(list)
    for r in rows:
        out[r["tx_hash"]].append(SwapEvent(
            pool_id=r["pair_id"], sender=r["sender"], amount0=int(r["amount0"]), amount1=int(r["amount1"]), sqrt_price_x96=int(r["sqrt_price_x96"]),
            liquidity=int(r["liquidity"]), tick=r["tick"] or 0, fee=r["fee"] or 0, block_number=r["block_number"], tx_hash=r["tx_hash"], log_index=r["log_index"],
        ))
    return out


def ingest_trades(ctx: IntelContext, token: str, pools: dict[str, PoolInfo], token_decimals: int, pricer: QuotePricer, *, to_block: int, from_block: int | None = None, batch_blocks: int = 50000, update_cursor: bool = True) -> dict[str, Any]:
    """Reconstruct trades for blocks not yet processed (cursor ``trades:<token>``).

    With ``update_cursor=False`` an explicit ``[from_block, to_block]`` range is processed
    (backward backfill) without touching the forward cursor.
    """
    token = token.lower()
    cursor_name = f"trades:{token}"
    if not update_cursor:
        if from_block is None:
            raise ValueError("from_block required when update_cursor=False")
        start, limit = int(from_block), int(to_block)
    else:
        cur = ctx.db.cursor_get(cursor_name)
        if from_block is not None and cur is None:
            start = from_block
        elif cur is not None:
            start = int(cur) + 1
        else:
            first = ctx.db.scalar("SELECT MIN(block_number) FROM transfers WHERE chain_id=? AND token_address=?", (ctx.chain_id, token))
            start = int(first) if first is not None else to_block + 1
        # never run ahead of what transfers/pool events have ingested
        t_cur = ctx.db.cursor_get(f"transfers:{token}")
        p_cur = ctx.db.cursor_get(f"pools:{token}")
        limit = min([x for x in (t_cur, p_cur, to_block) if x is not None])
    if start > limit:
        return {"trades": 0, "from_block": start, "to_block": limit}
    n = 0
    a = start
    quote_dec = lambda q: pricer.decimals(q)  # noqa: E731
    while a <= limit:
        b = min(limit, a + batch_blocks - 1)
        tx_transfers = _load_transfers(ctx, token, a, b)
        tx_swaps = _load_swaps(ctx, pools.keys(), a, b)
        rows: list[dict[str, Any]] = []
        for tx_hash in set(tx_transfers) | set(tx_swaps):
            trades = reconstruct_tx_trades(token, token_decimals, tx_transfers.get(tx_hash, []), tx_swaps.get(tx_hash, []), pools, ctx.system_label, quote_dec, pricer.usd_price)
            rows.extend(t.as_row(ctx.chain_id) for t in trades)
        with ctx.db.transaction():
            n += ctx.db.insert_many("trades", rows)
            if update_cursor:
                ctx.db.cursor_set(cursor_name, b, now_ts())
        a = b + 1
    log.info("trades reconstructed token=%s new=%d range=%d-%d", token[:10], n, start, limit)
    return {"trades": n, "from_block": start, "to_block": limit}
