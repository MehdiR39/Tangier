"""T+1 watcher: buy the launches that are already busy sixty seconds after their first trade.

The only entry rule that survived every check in the research package is a trade COUNTER: a pool
with at least N swaps in the minute after its first trade reaches x2 about twice as often as the
rest, in every period measured. The rule is worthless after two minutes, and the scanner's
discovery-then-analysis path takes several. So this engine does one thing, fast, and nothing else:

  poll the last few blocks · remember each pool's first swap · count swaps · at T+60 s, if the
  count clears the bar, write a BUY decision.

It never signs. Decisions are consumed by the existing execution loop, which stays in dry-run
unless the operator has deliberately switched it live -- the two-act safety model is untouched.
It is opt-in (`t1.enabled`, default off), sized small (`t1.size_eur`, default 5), and rate-limited
(`t1.max_per_hour`). A missed poll is a missed launch, never a corrupt state: the watcher keeps no
cursor that has to be exact.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from intel.chain.constants import TOPIC_V4_INITIALIZE, TOPIC_V4_SWAP
from intel.chain.uniswap_v4 import PoolInitialize, decode_initialize, decode_swap
from intel.context import IntelContext
from intel.ingest.pools import store_pool_init
from intel.utils.timeutil import now_ts

log = logging.getLogger(__name__)
MODEL_VERSION = "t1-watcher-v0.1"
MODEL_VERSION_SHADOW = "t1-shadow-v0.1"     # decisions the executor builds but never sends (paper book while paused)
BLOCKS_PER_MIN = 600


@dataclass
class Watched:
    init: PoolInitialize
    token: str
    quote: str
    first_swap_block: int | None = None
    swaps: list[dict[str, Any]] = field(default_factory=list)
    decided: bool = False
    decimals: int = 18


class T1Watcher:
    def __init__(self, ctx: IntelContext) -> None:
        self.ctx = ctx
        self.pools: dict[str, Watched] = {}
        self.last_block: int | None = None
        self.sent_ts: list[int] = []
        self._follow: dict[str, int] = {}          # bought pool -> block until which its swaps are kept
        self._restored = False
        self._last_recover = 0

    def _restore_follow(self, head: int) -> None:
        """Pick the follow list back up from the journal after a restart.

        The list lived only in memory, so every restart dropped the pools bought before it and the
        paper book could not be marked for them. Any T+1 buy decided less than six hours ago is
        still worth following.
        """
        self._restored = True
        try:
            rows = self.ctx.db.query(
                "SELECT metrics_json FROM decisions WHERE chain_id=? AND model_version LIKE 't1-%' AND kind='BUY' AND ts>?",
                (self.ctx.chain_id, now_ts() - 6 * 3600))
        except Exception as exc:  # noqa: BLE001
            log.info("t1: liste de suivi non restauree (%s)", str(exc)[:80])
            return
        n = 0
        for r in rows:
            try:
                mj = json.loads(r["metrics_json"] or "{}")
            except Exception:  # noqa: BLE001
                continue
            pid, decided = mj.get("pool_id"), mj.get("decided_block")
            if pid and decided and decided + 6 * 60 * BLOCKS_PER_MIN > head:
                self._follow[pid] = decided + 6 * 60 * BLOCKS_PER_MIN
                n += 1
        if n:
            log.info("t1: suivi restaure pour %d pools achetes avant le redemarrage", n)

    # ------------------------------------------------------------------ config
    def _cfg(self, key: str, default: Any) -> Any:
        return self.ctx.config.get(f"t1.{key}", default)

    def _classify(self, init: PoolInitialize) -> tuple[str, str] | None:
        """(token, quote) or None when neither side is a known quote asset"""
        quotes = {a.lower() for a in (self.ctx.config.quote_assets or {})}
        c0, c1 = init.currency0.lower(), init.currency1.lower()
        if c1 in quotes and c0 not in quotes:
            return c0, c1
        if c0 in quotes and c1 not in quotes:
            return c1, c0
        return None

    # ------------------------------------------------------------------- cycle
    async def run_cycle(self) -> dict[str, Any]:
        if not self._cfg("enabled", False):
            return {"status": "disabled"}
        head = await self.ctx.rpc.block_number()
        span = int(self._cfg("max_blocks_per_poll", 300))
        start = head - span if self.last_block is None else max(self.last_block + 1, head - span)
        if start > head:
            return {"status": "idle"}
        try:
            logs = await self.ctx.rpc.get_logs(address=self.ctx.pool_manager,
                                               topics=[[TOPIC_V4_INITIALIZE, TOPIC_V4_SWAP]],
                                               from_block=start, to_block=head)
            # Keep following the pools this book bought, for six hours, in the same poll: their
            # later swaps are what the paper book is marked against, and reading them back from
            # the public node afterwards (141 pools, one-off) got throttled. Same window, same
            # query shape, zero extra requests -- only the swaps of followed pools are kept.
            if not self._restored:
                self._restore_follow(head)
            self._follow = {pid: until for pid, until in self._follow.items() if until > head}
            followed: list[dict[str, Any]] = []
            if self._follow:
                try:
                    # The follow list is sent as an OR filter on the pool id topic. On the night of
                    # 2026-09-06 it grew to a hundred pools and the node answered such filters with
                    # partial results, silently: 172 of 281 bought pools ended with no followed swap
                    # while a direct read found them still trading. Twenty ids per request is what
                    # the node has been seen to honour.
                    flogs = []
                    ids = list(self._follow)
                    for i in range(0, len(ids), 20):
                        flogs.extend(await self.ctx.rpc.get_logs(address=self.ctx.pool_manager,
                                                                 topics=[TOPIC_V4_SWAP, ids[i:i + 20]],
                                                                 from_block=start, to_block=head))
                    ts_map: dict[int, int] = {}
                    for lg in flogs:
                        try:
                            ev = decode_swap(lg)
                        except Exception:
                            continue
                        followed.append({
                            "chain_id": self.ctx.chain_id, "tx_hash": ev.tx_hash, "log_index": ev.log_index,
                            "block_number": ev.block_number, "ts": None, "pair_id": ev.pool_id,
                            "sender": ev.sender, "amount0": str(ev.amount0), "amount1": str(ev.amount1),
                            "sqrt_price_x96": str(ev.sqrt_price_x96), "liquidity": str(ev.liquidity),
                            "tick": ev.tick, "fee": ev.fee, "source": "t1_follow",
                        })
                    if followed:
                        blocks = sorted({r["block_number"] for r in followed})
                        try:
                            ts_map = await self.ctx.rpc.block_timestamps(blocks)
                        except Exception:  # noqa: BLE001
                            ts_map = {}
                        for r in followed:
                            r["ts"] = ts_map.get(r["block_number"])
                        with self.ctx.db.transaction():
                            self.ctx.db.insert_many("swap_events", followed, ignore=True)
                except Exception as exc:  # noqa: BLE001
                    log.info("t1 suivi des pools achetes refuse (%s) — cette fenetre est sautee", str(exc)[:80])
        except Exception as exc:  # noqa: BLE001
            log.info("t1 poll refused (%s) — this window is skipped, nothing is corrupted", str(exc)[:80])
            return {"status": "skipped", "error": str(exc)[:120]}
        self.last_block = head

        n_init = n_swap = 0
        for lg in logs:
            t0 = str(lg["topics"][0]).lower()
            if t0 == TOPIC_V4_INITIALIZE:
                try:
                    init = decode_initialize(lg)
                except Exception:
                    continue
                cls = self._classify(init)
                if cls and init.pool_id not in self.pools:
                    self.pools[init.pool_id] = Watched(init, *cls)
                    n_init += 1
            elif t0 == TOPIC_V4_SWAP:
                try:
                    ev = decode_swap(lg)
                except Exception:
                    continue
                w = self.pools.get(ev.pool_id)
                if w is None or w.decided:
                    continue
                if w.first_swap_block is None:
                    w.first_swap_block = ev.block_number
                w.swaps.append({
                    "chain_id": self.ctx.chain_id, "tx_hash": ev.tx_hash, "log_index": ev.log_index,
                    "block_number": ev.block_number, "ts": None, "pair_id": ev.pool_id,
                    "sender": ev.sender, "amount0": str(ev.amount0), "amount1": str(ev.amount1),
                    "sqrt_price_x96": str(ev.sqrt_price_x96), "liquidity": str(ev.liquidity),
                    "tick": ev.tick, "fee": ev.fee, "source": "t1_watcher",
                })
                n_swap += 1

        decided = await self._decide(head)
        self._forget(head)
        try:
            sold = await self._book()
        except Exception as exc:  # noqa: BLE001
            log.warning("t1 livre: %s", str(exc)[:160])
            sold = 0
        return {"status": "ok", "head": head, "new_pools": n_init, "swaps_seen": n_swap,
                "watched": len(self.pools), "decisions": decided, "sells": sold, "seen": bool(logs)}

    async def _decide(self, head: int) -> int:
        """At T+60 s after the first swap: buy if the pool cleared the bar, then stop watching it."""
        min_trades = int(self._cfg("min_trades", 27))
        window = int(self._cfg("decide_after_blocks", BLOCKS_PER_MIN))
        size = float(self._cfg("size_eur", 5.0))
        per_hour = int(self._cfg("max_per_hour", 20))
        allowed = {a.lower() for a in (self.ctx.config.get("execution.allowed_quotes") or [])}
        now = now_ts()
        self.sent_ts = [t for t in self.sent_ts if now - t < 3600]
        try:
            from intel.alerts.commands import t1_paused
            paused = t1_paused(self.ctx)
        except Exception:  # noqa: BLE001
            paused = False
        n = 0
        for pid, w in self.pools.items():
            if w.decided or w.first_swap_block is None or head - w.first_swap_block < window:
                continue
            w.decided = True                          # one verdict per pool, whichever way it goes
            count = len(w.swaps)
            # Every verdict is recorded, not only the buys. This is the continuous series the
            # regime question needs -- how busy the chain's launches are, minute by minute --
            # and it costs nothing: the watcher already saw every one of these pools.
            self._observe(pid, w, count, head, count >= min_trades)
            if count < min_trades:
                continue
            # /pause from Telegram: no real order. With t1.shadow (default on) the decision is
            # still written under a shadow model version, which the executor never sends and
            # the book marks like the paper book: the honeypot probe and the exit rule keep
            # being measured while no money moves.
            shadow = bool(paused and self._cfg("shadow", True))
            if paused and not shadow:
                log.info("t1: %s passe la barre (%d swaps) mais les achats sont en pause", pid[:10], count)
                continue
            hooks = (w.init.hooks or "").lower()
            if hooks and int(hooks, 16) != 0 and not self._cfg("allow_hooks", False):
                # Hooked pools (the launchpad's 0xe5e7...) taxed the first real buys 12.6 %, blocked
                # or taxed the sells up to 46 %, and lost money in the paper book (-2.4 EUR on 14
                # vs +93 EUR on 21 hookless). Off by default; t1.allow_hooks turns them back on.
                log.info("t1: %s passe la barre (%d swaps) mais le pool a un hook (%s)", pid[:10], count, hooks[:10])
                continue
            if allowed and w.quote not in allowed:
                # Not for the real book -- but the paper book measures it (USDG/WETH pools, to
                # know whether they deserve real money one day) under the shadow model version.
                if self._cfg("shadow", True):
                    shadow = True
                else:
                    log.info("t1: %s passe la barre (%d swaps) mais cotation non autorisee (%s)", pid[:10], count, w.quote[:8])
                    continue
            if not shadow and self._burned(w.token):
                # The same token relaunched in a new pool (0x319c5b3f, 2026-09-07: 46 % sell tax at
                # noon, bought again at 14:47). A token that could not be sold, or that taxed a
                # trade past the ceiling, is never bought again by the real book.
                log.info("t1: %s passe la barre (%d swaps) mais le token %s a deja ete pris en defaut", pid[:10], count, w.token[:10])
                continue
            if len(self.sent_ts) >= per_hour:
                log.info("t1: %s cleared the bar (%d swaps) but the hourly cap is reached", pid[:10], count)
                continue
            await self._persist(w)
            last_px = self._price(w)
            self.ctx.db.insert("decisions", {
                "ts": now, "chain_id": self.ctx.chain_id, "token_address": w.token, "label": None,
                "kind": "BUY", "reason": f"T+1 · {count} swaps dans la premiere minute (seuil {min_trades})",
                "price": last_px, "size_eur": size, "position_id": None, "sent": 0,
                "metrics_json": json.dumps({"swaps_first_minute": count, "pool_id": pid, "quote": w.quote,
                                            "first_swap_block": w.first_swap_block, "decided_block": head, "shadow": shadow}),
                "model_version": MODEL_VERSION_SHADOW if shadow else MODEL_VERSION,
            })
            self.sent_ts.append(now)
            n += 1
            # follow this pool's swaps for six hours so the book can be marked from the database
            self._follow[pid] = head + 6 * 60 * BLOCKS_PER_MIN
            log.info("t1 BUY%s %s · %d swaps en 60 s · %.0f EUR · pool %s", " (ombre)" if shadow else "", w.token[:10], count, size, pid[:10])
        return n

    def _burned(self, token: str) -> bool:
        """Has the real book already been unable to sell this token, or refused it for its tax?"""
        try:
            n = self.ctx.db.scalar(
                "SELECT COUNT(*) FROM positions WHERE chain_id=? AND token_address=? AND kind='PORTFOLIO' "
                "AND (close_reason LIKE 'invendable%' OR close_reason LIKE 'achat reverte%')", (self.ctx.chain_id, token), 0)
            m = self.ctx.db.scalar(
                "SELECT COUNT(*) FROM executions WHERE chain_id=? AND token_address=? AND mode='live' "
                "AND (refused_reason LIKE '%taxe du hook%' OR refused_reason LIKE '%invendable%')", (self.ctx.chain_id, token), 0)
            return bool(n or m)
        except Exception:  # noqa: BLE001
            return False

    def _observe(self, pid: str, w: Watched, count: int, head: int, passed: bool) -> None:
        """one row per judged pool, bought or not -- the chain's launch activity as a time series"""
        try:
            self.ctx.db.execute(
                "CREATE TABLE IF NOT EXISTS t1_observations("
                "  ts INTEGER NOT NULL, chain_id INTEGER NOT NULL, pool_id TEXT NOT NULL, token_address TEXT,"
                "  quote_address TEXT, created_block INTEGER, first_swap_block INTEGER, decided_block INTEGER,"
                "  swaps_first_minute INTEGER NOT NULL, passed INTEGER NOT NULL, PRIMARY KEY(chain_id, pool_id))")
            try:
                self.ctx.db.execute("ALTER TABLE t1_observations ADD COLUMN hooks TEXT")
            except Exception:  # noqa: BLE001
                pass                                       # column already there
            self.ctx.db.execute(
                "INSERT OR IGNORE INTO t1_observations(ts, chain_id, pool_id, token_address, quote_address, created_block, "
                "first_swap_block, decided_block, swaps_first_minute, passed, hooks) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (now_ts(), self.ctx.chain_id, pid, w.token, w.quote, w.init.block_number,
                 w.first_swap_block, head, count, int(passed), (w.init.hooks or "").lower()))
        except Exception as exc:  # noqa: BLE001
            log.info("t1 observation non enregistree (%s)", str(exc)[:80])

    async def _persist(self, w: Watched) -> None:
        """Make the pool and its swaps visible to the executor, which reads pairs and swap_events."""
        try:
            blocks = sorted({r["block_number"] for r in w.swaps})
            ts_map = await self.ctx.rpc.block_timestamps(blocks) if blocks else {}
        except Exception:  # noqa: BLE001
            ts_map = {}
        created_ts = ts_map.get(w.init.block_number) or (min(ts_map.values()) if ts_map else None)
        store_pool_init(self.ctx, w.token, w.init, created_ts, "t1_watcher")
        # The executor sizes a sell from the token's decimals and refuses when they are unknown;
        # a pool sixty seconds old has no token row yet, so it is written here, at the buy.
        try:
            from intel.chain.erc20 import fetch_metadata
            meta = await fetch_metadata(self.ctx.rpc, w.token)
            if meta.get("decimals") is not None:
                w.decimals = int(meta["decimals"])
            self.ctx.db.execute(
                "INSERT INTO tokens(chain_id, address, name, symbol, decimals, total_supply, first_seen_ts, updated_ts) VALUES(?,?,?,?,?,?,?,?) "
                "ON CONFLICT(chain_id, address) DO UPDATE SET decimals=COALESCE(tokens.decimals, excluded.decimals), updated_ts=excluded.updated_ts",
                (self.ctx.chain_id, w.token, meta.get("name"), meta.get("symbol"), w.decimals,
                 str(meta["total_supply"]) if meta.get("total_supply") is not None else None, now_ts(), now_ts()))
        except Exception as exc:  # noqa: BLE001
            log.info("t1: metadonnees du token %s illisibles (%s) — 18 decimales supposees", w.token[:10], str(exc)[:80])
        for r in w.swaps:
            r["ts"] = ts_map.get(r["block_number"])
        with self.ctx.db.transaction():
            self.ctx.db.insert_many("swap_events", w.swaps, ignore=True)

    def _price(self, w: Watched) -> float | None:
        if not w.swaps:
            return None
        from intel.chain.uniswap_v4 import token_price_in_quote
        last = w.swaps[-1]
        try:
            dec_q = int((self.ctx.config.quote_assets.get(w.quote) or {}).get("decimals", 18))
            return token_price_in_quote(int(last["sqrt_price_x96"]), w.init.currency0.lower() == w.token, w.decimals, dec_q)
        except Exception:  # noqa: BLE001
            return None

    def _forget(self, head: int) -> None:
        """Drop pools that were decided, or never traded within ten minutes of creation."""
        stale = [pid for pid, w in self.pools.items()
                 if w.decided or (w.first_swap_block is None and head - w.init.block_number > 10 * BLOCKS_PER_MIN)]
        for pid in stale:
            del self.pools[pid]

    # -------------------------------------------------------------------- book
    async def _book(self) -> int:
        """Open the positions the executor accepted, then close them by the exit rule.

        The rule was measured on 2026-09-07 over 350 launches (intel/research/book_sim2.py): sell
        everything at x2, or at T+5 min, whichever comes first. Later is worth nothing -- 81 % of
        these pools have their liquidity pulled within a second of their last swap, about eight
        minutes after our entry -- so the clock, not the chart, is the exit. A sell the executor
        refuses is asked again a bounded number of times, then the line is written off.
        """
        from intel.execution.executor import quote_price_usd

        # Positions opened before the token row was written at the buy cannot be sold ("décimales
        # inconnues"): fill the gap a few tokens per cycle rather than write them off.
        missing = self.ctx.db.query(
            "SELECT DISTINCT p.token_address FROM positions p LEFT JOIN tokens t ON t.chain_id=p.chain_id AND t.address=p.token_address "
            "WHERE p.chain_id=? AND p.model_version LIKE 't1-%' AND p.status='OPEN' AND (t.address IS NULL OR t.decimals IS NULL) LIMIT 3",
            (self.ctx.chain_id,))
        for r in missing:
            try:
                from intel.chain.erc20 import fetch_metadata
                meta = await fetch_metadata(self.ctx.rpc, r["token_address"])
                dec = int(meta["decimals"]) if meta.get("decimals") is not None else 18
                self.ctx.db.execute(
                    "INSERT INTO tokens(chain_id, address, name, symbol, decimals, total_supply, first_seen_ts, updated_ts) VALUES(?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(chain_id, address) DO UPDATE SET decimals=COALESCE(tokens.decimals, excluded.decimals), updated_ts=excluded.updated_ts",
                    (self.ctx.chain_id, r["token_address"], meta.get("name"), meta.get("symbol"), dec,
                     str(meta["total_supply"]) if meta.get("total_supply") is not None else None, now_ts(), now_ts()))
            except Exception as exc:  # noqa: BLE001
                log.info("t1: decimales de %s non lues (%s)", r["token_address"][:10], str(exc)[:80])

        mode = str(self.ctx.config.get("execution.mode", "dry_run"))
        # Live, a position exists only once the chain says so. The first real buy (2026-09-07) was
        # SUBMITTED, reverted on chain, and still opened a phantom position: the receipt decides.
        accepted = ("BUILT",) if mode != "live" else ("CONFIRMED",)
        if mode == "live":
            await self._reconcile_receipts()
            await self._recover()
        tp = float(self._cfg("take_profit_multiple", 2.0))
        max_hold = int(self._cfg("max_hold_seconds", 300))
        retry_max = int(self._cfg("sell_retry_max", 5))
        now = now_ts()
        db = self.ctx.db
        ph = ",".join("?" * len(accepted))

        # 1. buys the executor accepted and the book does not hold yet
        rows = db.query(
            "SELECT d.id, d.token_address, d.price, d.size_eur, d.metrics_json, d.model_version, e.ts ets FROM decisions d "
            "JOIN executions e ON e.chain_id=d.chain_id AND e.decision_id=d.id "
            f"WHERE d.chain_id=? AND d.model_version LIKE 't1-%' AND d.kind='BUY' AND d.ts>? "
            f"AND ((d.model_version LIKE 't1-shadow%' AND e.status='BUILT') OR (d.model_version NOT LIKE 't1-shadow%' AND e.status IN ({ph}))) "
            "AND NOT EXISTS (SELECT 1 FROM positions p WHERE p.chain_id=d.chain_id AND p.notes LIKE ('decision:' || d.id || ' %'))",
            (self.ctx.chain_id, now - 6 * 3600, *accepted))
        for r in rows:
            mj = json.loads(r["metrics_json"] or "{}")
            quote = (mj.get("quote") or "").lower()
            qusd = quote_price_usd(self.ctx, quote) if quote else None
            entry = float(r["price"]) * float(qusd) if (r["price"] and qusd) else None
            is_shadow = str(r["model_version"] or "").startswith("t1-shadow")
            db.insert("positions", {
                "chain_id": self.ctx.chain_id, "token_address": r["token_address"], "label": r["token_address"][:10],
                "kind": "VIRTUAL" if (mode != "live" or is_shadow) else "PORTFOLIO", "opened_ts": int(r["ets"] or now),
                "entry_price": entry, "size_eur": r["size_eur"], "status": "OPEN", "peak_price": entry,
                "model_version": MODEL_VERSION, "notes": f"decision:{r['id']} pool:{mj.get('pool_id')} quote:{quote}",
            })
            log.info("t1 position ouverte %s · %.0f EUR · entree %s", r["token_address"][:10],
                     float(r["size_eur"] or 0), f"{entry:.3g} $" if entry else "inconnue")

        # 2. open positions: mark them, then sell by the rule
        sold = 0
        for p in db.query("SELECT * FROM positions WHERE chain_id=? AND model_version LIKE 't1-%' AND status='OPEN'", (self.ctx.chain_id,)):
            notes = dict(kv.split(":", 1) for kv in (p["notes"] or "").split() if ":" in kv)
            pool_id, quote = notes.get("pool"), notes.get("quote")
            token = p["token_address"]
            price = self._mark(pool_id, token, quote)
            mult = (price / float(p["entry_price"])) if (price and p["entry_price"]) else None
            if price and (p["peak_price"] is None or price > float(p["peak_price"])):
                db.execute("UPDATE positions SET peak_price=? WHERE id=?", (price, p["id"]))
            n_tries = 0
            last = db.query_one(
                "SELECT d.id, d.ts, e.status FROM decisions d LEFT JOIN executions e ON e.chain_id=d.chain_id AND e.decision_id=d.id "
                "WHERE d.chain_id=? AND d.position_id=? AND d.kind='SELL_ALL' ORDER BY d.id DESC LIMIT 1",
                (self.ctx.chain_id, p["id"]))
            done_states = ("BUILT",) if p["kind"] == "VIRTUAL" else accepted
            # Any sell of this line that went through closes it -- not only the latest attempt.
            # On 2026-09-07 14:52 a sell was SUBMITTED, the next cycle read that as a failed try,
            # asked again (refused: nothing left), and the confirmed sale was then hidden behind
            # the refusals. A sell in flight (SUBMITTED) is waited for, never retried over.
            ph2 = ",".join("?" * len(done_states))
            done = db.query_one(
                f"SELECT e.status FROM decisions d JOIN executions e ON e.chain_id=d.chain_id AND e.decision_id=d.id "
                f"WHERE d.chain_id=? AND d.position_id=? AND d.kind='SELL_ALL' AND e.status IN ({ph2}) LIMIT 1",
                (self.ctx.chain_id, p["id"], *done_states))
            if done is not None and last is not None:
                last = dict(last)
                last["status"] = done["status"]
            if last is not None:
                if last["status"] is None or last["status"] == "SUBMITTED":
                    continue                                       # not looked at yet, or in flight
                if last["status"] in done_states:
                    realized = float(p["size_eur"]) * (mult - 1.0) if (mult is not None and p["size_eur"]) else None
                    db.execute("UPDATE positions SET status='CLOSED', closed_ts=?, close_price=?, close_reason=?, realized_eur=? WHERE id=?",
                               (now, price, "vendu" + (f" x{mult:.2f}" if mult is not None else ""), realized, p["id"]))
                    log.info("t1 position fermee %s · %s", token[:10], f"x{mult:.2f}" if mult is not None else "multiple inconnu")
                    continue
                n_tries = int(db.scalar("SELECT COUNT(*) FROM decisions WHERE chain_id=? AND position_id=? AND kind='SELL_ALL'",
                                        (self.ctx.chain_id, p["id"]), 0))
                if n_tries >= retry_max:
                    db.execute("UPDATE positions SET status='CLOSED', closed_ts=?, close_price=?, close_reason=?, realized_eur=? WHERE id=?",
                               (now, price, f"invendable après {n_tries} essais ({last['status']})", -float(p["size_eur"] or 0), p["id"]))
                    log.warning("t1 position abandonnee %s : vente refusee %d fois", token[:10], n_tries)
                    continue
                if now - int(last["ts"]) < 15:
                    continue                                       # let the next try see a fresh state
            age = now - int(p["opened_ts"])
            reason = None
            if mult is not None and mult >= tp:
                reason = f"objectif x{tp:g} atteint (x{mult:.2f}) : on vend tout pendant qu'il y a un pool"
            elif age >= max_hold:
                reason = f"T+{age // 60} min : la fenêtre est finie, on vend tout" + (f" (x{mult:.2f})" if mult is not None else "")
            if not reason:
                continue
            db.insert("decisions", {
                "ts": now, "chain_id": self.ctx.chain_id, "token_address": token, "label": p["label"], "kind": "SELL_ALL",
                "reason": reason, "price": price, "size_eur": p["size_eur"], "position_id": p["id"], "sent": 0,
                "metrics_json": json.dumps({"pool_id": pool_id, "quote": quote, "multiple": mult, "age_s": age, "try": n_tries + 1}),
                "model_version": MODEL_VERSION_SHADOW if p["kind"] == "VIRTUAL" else MODEL_VERSION,
            })
            sold += 1
            log.info("t1 SELL %s · %s", token[:10], reason)
        return sold

    async def _recover(self) -> None:
        """Retry the bags written off as unsellable: the wallet still holds them, and pools change.

        Measured on 2026-09-07: of three bags written off at noon, one was worth 4.93 EUR the same
        afternoon through a pool that did not exist at the time, and a fourth (pos 240) came back
        as 85 EUR when its token was relaunched. A write-off is a bookkeeping state, not a verdict
        on the tokens: as long as the wallet holds them, the question is asked again, at intervals,
        a few at a time, and each attempt costs nothing until the chain agrees to pay.
        """
        from intel.chain.erc20 import balance_of
        from intel.execution.signer import signer_address

        every = int(self._cfg("recover_interval_seconds", 900))
        if now_ts() - self._last_recover < every:
            return
        self._last_recover = now_ts()
        owner = signer_address()
        if owner is None:
            return
        db = self.ctx.db
        rows = db.query(
            "SELECT id, token_address, notes FROM positions WHERE chain_id=? AND kind='PORTFOLIO' AND model_version LIKE 't1-%' "
            "AND status='CLOSED' AND (close_reason LIKE 'invendable%' OR close_reason LIKE 'achat reverte%') "
            "AND closed_ts>? ORDER BY closed_ts DESC LIMIT 12", (self.ctx.chain_id, now_ts() - 7 * 86400))
        tried = 0
        for p in rows:
            if tried >= int(self._cfg("recover_per_cycle", 3)):
                break
            notes = p["notes"] or ""
            done = sum(1 for kv in notes.split() if kv.startswith("recover:"))
            if done >= int(self._cfg("recover_max", 8)):
                continue
            try:
                bal = await balance_of(self.ctx.rpc, p["token_address"], owner)
            except Exception:  # noqa: BLE001
                continue
            if not bal:
                continue
            tried += 1
            # detach the old attempts so the retry counter starts from zero, then reopen the line:
            # the ordinary exit path (age past the window -> sell) takes it from here.
            db.execute("UPDATE decisions SET position_id=NULL WHERE chain_id=? AND position_id=? AND kind='SELL_ALL'", (self.ctx.chain_id, p["id"]))
            # The recorded loss stays on the row. Clearing it made 15 EUR of real losses vanish
            # from /pnl for as long as the bags were being retried (2026-09-07), so the reported
            # result swung by that much depending on the minute the question was asked.
            db.execute("UPDATE positions SET status='OPEN', closed_ts=NULL, close_price=NULL, close_reason=NULL, "
                       "notes=notes || ' recover:' || ? WHERE id=?", (done + 1, p["id"]))
            log.info("t1 reprise %s : le portefeuille detient encore ce token, nouvelle tentative de vente (%d/%s)",
                     p["token_address"][:10], done + 1, self._cfg("recover_max", 8))

    async def _reconcile_receipts(self) -> None:
        """Turn SUBMITTED live orders into CONFIRMED or FAILED from their receipts; void phantom buys."""
        db = self.ctx.db
        rows = db.query(
            "SELECT id, tx_hash, kind, decision_id, token_address FROM executions WHERE chain_id=? AND mode='live' "
            "AND status='SUBMITTED' AND tx_hash IS NOT NULL AND ts>?", (self.ctx.chain_id, now_ts() - 6 * 3600))
        for e in rows:
            try:
                rc = await self.ctx.rpc.get_transaction_receipt(e["tx_hash"])
            except Exception as exc:  # noqa: BLE001
                log.info("recu %s illisible (%s)", e["tx_hash"][:12], str(exc)[:80])
                continue
            if not rc or rc.get("blockNumber") is None:
                continue                                       # still pending
            ok = int(str(rc.get("status", "0x0")), 16) == 1
            gas = int(str(rc.get("gasUsed", "0x0")), 16)
            db.execute("UPDATE executions SET status=?, error=? WHERE id=?",
                       ("CONFIRMED" if ok else "FAILED", None if ok else f"revert en chaine (gaz {gas})", e["id"]))
            log.info("ordre %s %s en chaine · tx %s", e["kind"], "confirme" if ok else "REVERTE", e["tx_hash"][:14])
            if not ok and e["kind"] == "BUY" and e["decision_id"]:
                db.execute("UPDATE positions SET status='CLOSED', closed_ts=?, close_reason=?, realized_eur=0 "
                           "WHERE chain_id=? AND status='OPEN' AND notes LIKE ?",
                           (now_ts(), "achat reverté en chaîne : aucune position (gaz perdu)", self.ctx.chain_id, f"decision:{e['decision_id']} %"))

    def _mark(self, pool_id: str | None, token: str, quote: str | None) -> float | None:
        """The token's price in dollars from the pool's latest swap; None when it cannot be known."""
        if not pool_id or not quote:
            return None
        from intel.chain.uniswap_v4 import token_price_in_quote
        from intel.execution.executor import quote_price_usd

        last = self.ctx.db.query_one("SELECT sqrt_price_x96 FROM swap_events WHERE chain_id=? AND pair_id=? ORDER BY block_number DESC, log_index DESC LIMIT 1",
                                     (self.ctx.chain_id, pool_id))
        pair = self.ctx.db.query_one("SELECT token_is_currency0 FROM pairs WHERE chain_id=? AND pair_id=?", (self.ctx.chain_id, pool_id))
        qusd = quote_price_usd(self.ctx, quote)
        if last is None or pair is None or not qusd:
            return None
        dec_t = self.ctx.db.scalar("SELECT decimals FROM tokens WHERE chain_id=? AND address=?", (self.ctx.chain_id, token)) or 18
        dec_q = int((self.ctx.config.quote_assets.get(quote) or {}).get("decimals", 18))
        try:
            return float(token_price_in_quote(int(last["sqrt_price_x96"]), bool(pair["token_is_currency0"]), int(dec_t), dec_q)) * float(qusd)
        except Exception:  # noqa: BLE001
            return None
