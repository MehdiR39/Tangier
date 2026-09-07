"""Heuristic wallet clustering with explicit evidence and confidence.

We never assert common ownership. Each edge carries an evidence type and weight; a
cluster's confidence is ``1 - Π(1 - w)`` over its distinct evidence types (capped). Hub
addresses (system contracts, routers, or wallets touching > ``hub_degree_threshold``
peers) are excluded as evidence because they connect everyone.
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable

from intel import MODEL_VERSION
from intel.context import IntelContext
from intel.metrics.trading_quality import size_bucket
from intel.utils.timeutil import now_ts

log = logging.getLogger(__name__)


@dataclass
class Edge:
    a: str
    b: str
    kind: str
    weight: float
    detail: str


@dataclass
class Cluster:
    members: list[str]
    confidence: float
    evidence: dict[str, Any] = field(default_factory=dict)
    member_confidence: dict[str, float] = field(default_factory=dict)


class _UF:
    def __init__(self) -> None:
        self.p: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[ra] = rb


def build_clusters(edges: list[Edge], *, max_size: int = 200) -> list[Cluster]:
    uf = _UF()
    for e in edges:
        uf.union(e.a, e.b)
    groups: dict[str, list[Edge]] = defaultdict(list)
    members: dict[str, set[str]] = defaultdict(set)
    for e in edges:
        r = uf.find(e.a)
        groups[r].append(e)
        members[r].update((e.a, e.b))
    out: list[Cluster] = []
    for r, es in groups.items():
        ms = sorted(members[r])
        if len(ms) < 2 or len(ms) > max_size:
            continue
        best_by_kind: dict[str, float] = {}
        for e in es:
            best_by_kind[e.kind] = max(best_by_kind.get(e.kind, 0.0), e.weight)
        conf = 1.0
        for w in best_by_kind.values():
            conf *= 1.0 - w
        conf = min(0.98, 1.0 - conf)
        mconf: dict[str, float] = defaultdict(float)
        for e in es:
            mconf[e.a] = max(mconf[e.a], e.weight)
            mconf[e.b] = max(mconf[e.b], e.weight)
        evidence = {"edge_kinds": {k: round(v, 3) for k, v in best_by_kind.items()}, "n_edges": len(es), "samples": [f"{e.kind}:{e.a[:8]}~{e.b[:8]}:{e.detail}" for e in es[:6]]}
        out.append(Cluster(ms, conf, evidence, dict(mconf)))
    out.sort(key=lambda c: (-c.confidence, -len(c.members)))
    return out


def edges_from_transfers(transfers: list[tuple[str, str, int]], candidates: set[str], is_hub: Callable[[str], bool], weight: float) -> list[Edge]:
    """Direct token transfers between two candidate wallets (neither a hub)."""
    seen: dict[tuple[str, str], int] = defaultdict(int)
    for frm, to, _v in transfers:
        if frm == to or frm not in candidates or to not in candidates or is_hub(frm) or is_hub(to):
            continue
        seen[(min(frm, to), max(frm, to))] += 1
    return [Edge(a, b, "direct_transfer", min(0.95, weight + 0.05 * (n - 1)), f"{n} transfers") for (a, b), n in seen.items()]


def edges_from_funding(funding: dict[str, str], candidates: set[str], is_hub: Callable[[str], bool], weight: float) -> list[Edge]:
    by_src: dict[str, list[str]] = defaultdict(list)
    for a in candidates:
        src = funding.get(a)
        if src and not is_hub(src):
            by_src[src].append(a)
    out: list[Edge] = []
    for src, addrs in by_src.items():
        if 2 <= len(addrs) <= 25:  # a funder of 100 wallets is an exchange / hub, not evidence
            w = weight if len(addrs) <= 5 else weight * 0.6
            for i in range(1, len(addrs)):
                out.append(Edge(addrs[0], addrs[i], "same_funding_source", w, f"funded by {src[:10]}"))
    return out


def edges_from_synchrony(trades: list[dict[str, Any]], candidates: set[str], window_seconds: int, min_events: int, weight: float) -> list[Edge]:
    """Wallets repeatedly trading the same side within ``window_seconds`` of each other."""
    rows = sorted((t for t in trades if t["trader"] in candidates and t["side"] in ("BUY", "SELL")), key=lambda t: t["ts"])
    pair_counts: dict[tuple[str, str], int] = defaultdict(int)
    for i, t in enumerate(rows):
        j = i + 1
        while j < len(rows) and rows[j]["ts"] - t["ts"] <= window_seconds:
            u = rows[j]
            if u["trader"] != t["trader"] and u["side"] == t["side"] and u.get("tx_hash") != t.get("tx_hash"):
                pair_counts[(min(t["trader"], u["trader"]), max(t["trader"], u["trader"]))] += 1
            j += 1
    return [Edge(a, b, "synchronized_trades", min(0.9, weight + 0.03 * (n - min_events)), f"{n} synchronized trades") for (a, b), n in pair_counts.items() if n >= min_events]


def edges_from_size_patterns(trades: list[dict[str, Any]], candidates: set[str], weight: float, tolerance: float = 0.002, min_repeats: int = 3) -> list[Edge]:
    sizes: dict[int, set[str]] = defaultdict(set)
    counts: dict[tuple[int, str], int] = defaultdict(int)
    for t in trades:
        if t["trader"] not in candidates or not t.get("usd_value"):
            continue
        v = float(t["usd_value"])
        if v < 20:
            continue
        key = size_bucket(v, tolerance)
        sizes[key].add(t["trader"])
        counts[(key, t["trader"])] += 1
    out: list[Edge] = []
    for key, wallets in sizes.items():
        ws = [w for w in wallets if counts[(key, w)] >= min_repeats]
        if 2 <= len(ws) <= 10:
            for i in range(1, len(ws)):
                out.append(Edge(ws[0], ws[i], "identical_trade_sizes", weight, f"size key {key} x{min_repeats}+"))
    return out


def effective_concentration(holders: list[tuple[str, int, bool]], econ_supply: int, clusters: list[Cluster], min_confidence: float) -> dict[str, Any]:
    """Merge balances of high-confidence clusters into single actors and recompute top-N."""
    owner_of: dict[str, str] = {}
    for c in clusters:
        if c.confidence >= min_confidence:
            root = c.members[0]
            for m in c.members:
                owner_of[m] = root
    merged: dict[str, int] = defaultdict(int)
    for a, b, ex in holders:
        if ex or b <= 0:
            continue
        merged[owner_of.get(a, a)] += b
    vals = sorted(merged.values(), reverse=True)
    if not vals or econ_supply <= 0:
        return {"effective_top10_pct": None, "effective_top20_pct": None, "n_effective_actors": 0, "largest_cluster_pct": None}
    largest_cluster = 0
    for c in clusters:
        if c.confidence >= min_confidence:
            largest_cluster = max(largest_cluster, sum(b for a, b, ex in holders if not ex and a in set(c.members)))
    return {
        "effective_top10_pct": sum(vals[:10]) / econ_supply,
        "effective_top20_pct": sum(vals[:20]) / econ_supply,
        "n_effective_actors": len(vals),
        "largest_cluster_pct": largest_cluster / econ_supply,
        "n_high_confidence_clusters": sum(1 for c in clusters if c.confidence >= min_confidence),
    }


def cluster_token(ctx: IntelContext, token: str, as_of_ts: int, candidates: set[str], *, persist: bool = True) -> list[Cluster]:
    token = token.lower()
    p = ctx.config.section("clustering")
    lst = list(candidates)[:400]
    if len(lst) < 2:
        return []
    cand = set(lst)
    # hubs: system addresses or wallets with very many distinct counterparties for this token
    transfers: list[tuple[str, str, int]] = []
    tx_in: dict[tuple[str, str], int] = defaultdict(int)
    tx_out: dict[tuple[str, str], int] = defaultdict(int)
    for i in range(0, len(lst), 300):
        chunk = lst[i: i + 300]
        ph = ",".join("?" for _ in chunk)
        rows = ctx.db.query(
            f"SELECT tx_hash, from_address, to_address, value FROM transfers WHERE chain_id=? AND token_address=? AND ts<=? AND (from_address IN ({ph}) OR to_address IN ({ph}))",
            (ctx.chain_id, token, as_of_ts, *chunk, *chunk),
        )
        for r in rows:
            v = int(r["value"])
            transfers.append((r["from_address"], r["to_address"], v))
            tx_out[(r["tx_hash"], r["from_address"])] += v
            tx_in[(r["tx_hash"], r["to_address"])] += v
    peers: dict[str, set[str]] = defaultdict(set)
    for frm, to, _ in transfers:
        peers[frm].add(to)
        peers[to].add(frm)
    # pass-through intermediaries (received and forwarded the same amount inside a tx) are
    # routers/settlers/aggregators: they connect unrelated users and are never evidence
    passthrough_hits: dict[str, int] = defaultdict(int)
    for (tx, a), v in tx_in.items():
        if v > 0 and tx_out.get((tx, a), 0) == v:
            passthrough_hits[a] += 1
    contracts = {r["address"] for r in ctx.db.query(f"SELECT address FROM wallets WHERE chain_id=? AND is_contract=1 AND address IN ({','.join('?' for _ in lst)})", (ctx.chain_id, *lst))}
    hub_thr = int(p.get("hub_degree_threshold", 50))

    def is_hub(a: str) -> bool:
        return ctx.is_system(a) or a in contracts or passthrough_hits.get(a, 0) >= 2 or len(peers.get(a, ())) > hub_thr

    trades = [dict(r) for r in ctx.db.query(
        "SELECT trader, side, ts, usd_value, tx_hash FROM trades WHERE chain_id=? AND token_address=? AND ts<=? ORDER BY ts", (ctx.chain_id, token, as_of_ts)
    ) if r["trader"] in cand]
    funding: dict[str, str] = {}
    for r in ctx.db.query(f"SELECT address, funding_source FROM wallets WHERE chain_id=? AND funding_source IS NOT NULL AND address IN ({','.join('?' for _ in lst)})", (ctx.chain_id, *lst)):
        funding[r["address"]] = r["funding_source"]
    # drop hubs from the candidate set entirely so synchrony/pattern evidence ignores them too
    cand = {a for a in cand if not is_hub(a)}
    edges: list[Edge] = []
    edges += edges_from_transfers(transfers, cand, is_hub, float(p.get("direct_transfer_weight", 0.35)))
    edges += edges_from_funding(funding, cand, is_hub, float(p.get("same_funding_weight", 0.45)))
    edges += edges_from_synchrony(trades, cand, int(p.get("sync_window_seconds", 60)), int(p.get("min_sync_events", 3)), float(p.get("sync_weight", 0.25)))
    edges += edges_from_size_patterns(trades, cand, float(p.get("pattern_weight", 0.20)))
    clusters = build_clusters(edges, max_size=int(p.get("max_cluster_size", 200)))
    if persist and clusters:
        ts = now_ts()
        with ctx.db.transaction():
            for c in clusters:
                cid = ctx.db.insert("wallet_clusters", {"ts": ts, "chain_id": ctx.chain_id, "token_address": token, "confidence": c.confidence, "size": len(c.members), "evidence_json": json.dumps(c.evidence), "model_version": MODEL_VERSION})
                ctx.db.insert_many("wallet_cluster_members", [{"cluster_id": cid, "address": m, "confidence": c.member_confidence.get(m, c.confidence), "evidence_json": None} for m in c.members], ignore=True)
    return clusters


async def resolve_funding_sources(ctx: IntelContext, addresses: list[str], max_lookups: int = 25) -> int:
    """Populate wallets.funding_source with the sender of the wallet's earliest incoming token transfer
    or transaction (Blockscout, cached). Used as clustering evidence; hubs are filtered later."""
    n = 0
    todo = [a for a in addresses if ctx.db.query_one("SELECT 1 FROM wallets WHERE chain_id=? AND address=? AND funding_source IS NOT NULL", (ctx.chain_id, a)) is None]
    for a in todo[:max_lookups]:
        src = None
        tx = None
        ts = None
        try:
            txs = await ctx.blockscout.address_transactions(a, max_pages=1)
            incoming = [t for t in txs if (t.get("to") or {}).get("hash", "").lower() == a]
            if incoming:
                first = min(incoming, key=lambda t: int(t.get("block_number") or t.get("block") or 0))
                src = (first.get("from") or {}).get("hash", "").lower() or None
                tx = first.get("hash")
            if src is None:
                tts = await ctx.blockscout.address_token_transfers(a, max_pages=1)
                inc = [t for t in tts if (t.get("to") or {}).get("hash", "").lower() == a]
                if inc:
                    first = min(inc, key=lambda t: int(t.get("block_number") or 0))
                    src = (first.get("from") or {}).get("hash", "").lower() or None
                    tx = first.get("transaction_hash")
        except Exception as exc:
            log.debug("funding lookup failed %s: %s", a[:10], exc)
            continue
        if src:
            ctx.db.execute(
                "INSERT INTO wallets(chain_id, address, funding_source, funding_tx, funding_ts, updated_ts) VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(chain_id, address) DO UPDATE SET funding_source=excluded.funding_source, funding_tx=excluded.funding_tx, updated_ts=excluded.updated_ts",
                (ctx.chain_id, a, src, tx, ts, now_ts()),
            )
            n += 1
    return n
