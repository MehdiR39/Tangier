"""Event-time features, computed strictly from what was visible at each instant.

Observations are anchored on the pool's FIRST TRADE, not on its creation block: a pool that sits
idle for two hours before anyone touches it has not been alive for two hours, and anchoring on
creation would put its "T+5 min" reading in a period with no market at all.

Decimals are deliberately avoided. A token's decimals were unreadable for a large share of pools on
this node, and dropping those pools silently is what biased the previous collection. Every feature
here is either a ratio (volume/mcap, liquidity/mcap, an acceleration, a share of supply) in which
the decimals cancel exactly, or a count. Absolute USD market cap is the one thing that needs them,
so it is filled only where the quote's decimals are known from config and left NULL otherwise --
never guessed.

Buys and sells are read from ERC20 transfers against the v4 PoolManager, because the Swap event's
`sender` is the router, not the person: a transfer PoolManager -> wallet is somebody buying, and
wallet -> PoolManager is somebody selling. That is also what makes unique-buyer counts possible.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from typing import Any

BLOCKS_PER_MIN = 600          # ~0.1 s a block
GRID_MIN = [1, 2, 5, 10, 15, 30, 60, 120, 180, 360, 1440]
Q96 = 1 << 96


def price_from_sqrt(sqrt_price: int, is_c0: bool) -> float:
    """token price in quote units, decimals NOT applied (a constant factor, cancels in ratios)"""
    x = sqrt_price / Q96
    p = x * x
    if p <= 0:
        return 0.0
    return p if is_c0 else 1.0 / p


def virtual_quote(liquidity: int, sqrt_price: int, is_c0: bool) -> float:
    """quote-side virtual reserve; an upper bound on depth, used only inside ratios"""
    if liquidity <= 0 or sqrt_price <= 0:
        return 0.0
    x = sqrt_price / Q96
    # reserve0 = L / sqrtP, reserve1 = L * sqrtP
    return (liquidity * x) if is_c0 else (liquidity / x)


def _safe(a: float, b: float, default: float | None = None) -> float | None:
    return default if not b else a / b


class PoolTape:
    """the swaps and transfers of one pool, in order, with point-in-time readers"""

    def __init__(self, pool: dict[str, Any], swaps: list[Any], transfers: list[Any],
                 pool_manager: str) -> None:
        self.pool = pool
        self.is_c0 = bool(pool["is_c0"])
        self.pm = pool_manager.lower()
        self.swaps = [(int(s["block"]), int(s["sqrt_price"]), int(s["liquidity"]),
                       int(s["amount0"]), int(s["amount1"])) for s in swaps]
        self.swaps.sort(key=lambda r: r[0])
        self.transfers = [(int(t["block"]), str(t["from_address"]).lower(),
                           str(t["to_address"]).lower(), int(t["value"])) for t in transfers]
        self.transfers.sort(key=lambda r: r[0])
        self._resolve_hops()
        self.t0 = self.swaps[0][0] if self.swaps else None
        # The deployer is unknown for almost every sampled pool (the tokens table only describes
        # the 308 the scanner selected), so the "deployer share" bound filtered nothing. The
        # transfers say who it is: the first mint from the zero address goes to the deployer or
        # its launchpad -- either way the wallet whose selling is the warning sign.
        if not (pool.get("deployer") or ""):
            for _blk, frm, to, _val in self.transfers:
                if frm == "0x0000000000000000000000000000000000000000":
                    self.pool = {**pool, "deployer": to}
                    break
        supply = pool.get("total_supply")
        try:
            self.supply = float(supply) if supply not in (None, "") else None
        except (TypeError, ValueError):
            self.supply = None

    def _resolve_hops(self) -> None:
        """Replace router hops by the people behind them.

        Measured on 59 tokens: 80 % of the PoolManager's outflows land on a handful of router or
        hook contracts (one of them on 27 tokens), and the router forwards the tokens to the real
        buyer within the same block. Counting the router as "the buyer" collapsed every unique-
        buyer figure to one address and made the organic-flow features measure nothing.

        Within each block, a PoolManager -> X transfer followed by X -> Y of (about) the same
        amount is one buy by Y: the first leg is rewritten to Y and the forwarding leg dropped, so
        balances are not credited twice. Sells are resolved the mirror way. Chains of up to three
        hops are followed. Anything that cannot be resolved is left exactly as it was.
        """
        by_block: dict[int, list[int]] = defaultdict(list)
        for i, (blk, _f, _t, _v) in enumerate(self.transfers):
            by_block[blk].append(i)
        rows = [list(t) for t in self.transfers]
        drop: set[int] = set()
        zero = "0x0000000000000000000000000000000000000000"
        for blk, idxs in by_block.items():
            # index the block once: a naive scan per transfer is quadratic, and airdrop blocks
            # carry thousands of transfers of the same token
            by_from: dict[str, list[int]] = defaultdict(list)
            by_to: dict[str, list[int]] = defaultdict(list)
            for j in idxs:
                by_from[rows[j][1]].append(j)
                by_to[rows[j][2]].append(j)
            for i in idxs:
                b, frm, to, val = rows[i]
                if i in drop or val <= 0:
                    continue
                if frm == self.pm and to != self.pm:                       # a buy: follow X forward
                    cur, hops = to, 0
                    while hops < 3:
                        nxt = next((j for j in by_from.get(cur, ()) if j not in drop and j != i
                                    and rows[j][2] not in (self.pm, zero)
                                    and rows[j][3] >= 0.9 * val), None)
                        if nxt is None:
                            break
                        drop.add(nxt)
                        cur = rows[nxt][2]
                        hops += 1
                    rows[i][2] = cur
                elif to == self.pm and frm != self.pm:                     # a sell: follow X back
                    cur, hops = frm, 0
                    while hops < 3:
                        prv = next((j for j in by_to.get(cur, ()) if j not in drop and j != i
                                    and rows[j][1] not in (self.pm, zero)
                                    and rows[j][3] >= 0.9 * val), None)
                        if prv is None:
                            break
                        drop.add(prv)
                        cur = rows[prv][1]
                        hops += 1
                    rows[i][1] = cur
        self.transfers = [tuple(r) for i, r in enumerate(rows) if i not in drop]

    # ---------------------------------------------------------------- swaps
    def _swaps_upto(self, block: int) -> list[tuple]:
        out = []
        for s in self.swaps:
            if s[0] > block:
                break
            out.append(s)
        return out

    def price_at(self, block: int) -> float:
        last = None
        for s in self.swaps:
            if s[0] > block:
                break
            last = s
        return price_from_sqrt(last[1], self.is_c0) if last else 0.0

    def window(self, b_from: int, b_to: int) -> dict[str, float]:
        """trade counts and quote volume inside a block window"""
        n = vol = 0.0
        buy = sell = 0.0
        nb = ns = 0
        for blk, _sq, _lq, a0, a1 in self.swaps:
            if blk <= b_from:
                continue
            if blk > b_to:
                break
            n += 1
            q = abs(a1 if self.is_c0 else a0)      # quote leg, raw units
            vol += q
            # the token leg's sign says which way it went: token leaving the pool is a buy
            tok = a0 if self.is_c0 else a1
            if tok < 0:
                buy += q
                nb += 1
            else:
                sell += q
                ns += 1
        return {"n": n, "vol": vol, "buy": buy, "sell": sell, "n_buys": nb, "n_sells": ns}

    # ------------------------------------------------------------ transfers
    def wallet_state(self, block: int) -> dict[str, Any]:
        """holders, concentration and traders as of ``block``, from transfers only"""
        bal: dict[str, int] = defaultdict(int)
        buyers: set[str] = set()
        sellers: set[str] = set()
        for blk, frm, to, val in self.transfers:
            if blk > block:
                break
            if frm != "0x0000000000000000000000000000000000000000":
                bal[frm] -= val
            if to != "0x0000000000000000000000000000000000000000":
                bal[to] += val
            if frm == self.pm and to != self.pm:
                buyers.add(to)
            elif to == self.pm and frm != self.pm:
                sellers.add(frm)
        skip = {self.pm, "0x0000000000000000000000000000000000000000",
                "0x000000000000000000000000000000000000dead"}
        held = {a: v for a, v in bal.items() if v > 0 and a not in skip}
        tot = sum(held.values())
        top = sorted(held.values(), reverse=True)
        dep = (self.pool.get("deployer") or "").lower()
        return {
            "holders": len(held),
            "top1": _safe(sum(top[:1]), tot),
            "top5": _safe(sum(top[:5]), tot),
            "top10": _safe(sum(top[:10]), tot),
            "top20": _safe(sum(top[:20]), tot),
            "deployer_pct": _safe(held.get(dep, 0), tot) if dep else None,
            "buyers": buyers, "sellers": sellers,
        }


    def flow(self, block: int) -> dict[str, Any]:
        """quality of the buy flow up to ``block``: is the demand new wallets, or the same ones?

        Read from transfers against the PoolManager. A buy from a wallet seen buying before is
        churn; a buy whose amount repeats another buy's amount exactly is a bot pattern; the
        deployer sending tokens to the pool is the deployer selling. Ratios only, so decimals
        cancel. None of these needs a threshold to be computed -- the thresholds come later,
        from the training half, or not at all.
        """
        first_buy: set[str] = set()
        buy_new = buy_all = 0
        amounts: dict[int, int] = defaultdict(int)
        n_buys = 0
        dep = (self.pool.get("deployer") or "").lower()
        dep_sold = 0
        for blk, frm, to, val in self.transfers:
            if blk > block:
                break
            if frm == self.pm and to != self.pm:              # a buy
                n_buys += 1
                buy_all += val
                amounts[val] += 1
                if to not in first_buy:
                    first_buy.add(to)
                    buy_new += val
            elif to == self.pm and frm != self.pm:            # a sell
                if dep and frm == dep:
                    dep_sold = 1
        repeated = sum(c for c in amounts.values() if c >= 2)
        return {
            "organic_buy_ratio": _safe(buy_new, buy_all),
            "returning_share": _safe(n_buys - len(first_buy), n_buys),
            "repeat_amount_share": _safe(repeated, n_buys),
            "deployer_sold": dep_sold,
        }


def snapshot(tape: PoolTape, t_min: float, *, have_transfers: bool) -> dict[str, Any] | None:
    """one observation at ``t_min`` minutes after the first trade, using nothing later"""
    if tape.t0 is None:
        return None
    b = tape.t0 + int(t_min * BLOCKS_PER_MIN)
    seen = tape._swaps_upto(b)
    if not seen:
        return None
    price = tape.price_at(b)
    if price <= 0:
        return None
    last = seen[-1]
    liq_q = virtual_quote(last[2], last[1], tape.is_c0)
    mcap_q = price * tape.supply if tape.supply else None

    w5 = tape.window(b - 5 * BLOCKS_PER_MIN, b)
    w5p = tape.window(b - 10 * BLOCKS_PER_MIN, b - 5 * BLOCKS_PER_MIN)
    w1 = tape.window(b - BLOCKS_PER_MIN, b)
    w15 = tape.window(b - 15 * BLOCKS_PER_MIN, b)
    w30 = tape.window(b - 30 * BLOCKS_PER_MIN, b)
    w60 = tape.window(b - 60 * BLOCKS_PER_MIN, b)
    allw = tape.window(tape.t0 - 1, b)

    p1 = tape.price_at(b - BLOCKS_PER_MIN)
    p5 = tape.price_at(b - 5 * BLOCKS_PER_MIN)
    p15 = tape.price_at(b - 15 * BLOCKS_PER_MIN)
    p0 = price_from_sqrt(tape.swaps[0][1], tape.is_c0)

    ws = tape.wallet_state(b) if have_transfers else {}
    ws_prev = tape.wallet_state(b - 5 * BLOCKS_PER_MIN) if have_transfers else {}
    ws_prev2 = tape.wallet_state(b - 10 * BLOCKS_PER_MIN) if have_transfers else {}

    h, hp, hp2 = ws.get("holders"), ws_prev.get("holders"), ws_prev2.get("holders")
    hv = _safe((h - hp), hp) if h is not None and hp else None
    hv_prev = _safe((hp - hp2), hp2) if hp is not None and hp2 else None
    nb5 = len(ws.get("buyers", set()) - ws_prev.get("buyers", set())) if have_transfers else None
    nb5_prev = (len(ws_prev.get("buyers", set()) - ws_prev2.get("buyers", set()))
                if have_transfers else None)

    feat = {
        "age_min": t_min,
        "price_chg_1m": _safe(price - p1, p1),
        "price_chg_5m": _safe(price - p5, p5),
        "price_chg_15m": _safe(price - p15, p15),
        "ret_since_first": _safe(price, p0),
        "vol_1m": w1["vol"], "vol_5m": w5["vol"], "vol_15m": w15["vol"],
        "vol_30m": w30["vol"], "vol_60m": w60["vol"],
        "trades_5m": w5["n"], "trades_total": allw["n"],
        "vol_accel": _safe(w5["vol"], w5p["vol"]),
        "trade_accel": _safe(w5["n"], w5p["n"]),
        "net_buy_pressure": _safe(w5["buy"] - w5["sell"], w5["buy"] + w5["sell"]),
        "buy_share_trades": _safe(w5["n_buys"], w5["n_buys"] + w5["n_sells"]),
        "liq_to_mc": _safe(liq_q, mcap_q) if mcap_q else None,
        "vol5_to_mc": _safe(w5["vol"], mcap_q) if mcap_q else None,
        "vol5_to_liq": _safe(w5["vol"], liq_q),
        "holder_velocity_5m": hv,
        "holder_accel": _safe(hv, hv_prev) if hv is not None and hv_prev else None,
        "new_buyers_5m": nb5,
        "buyer_accel": _safe(nb5, nb5_prev) if nb5 is not None and nb5_prev else None,
        "uniq_buyers": len(ws.get("buyers", set())) if have_transfers else None,
        "uniq_sellers": len(ws.get("sellers", set())) if have_transfers else None,
        "price_holder_ratio": (_safe(_safe(price - p5, p5) or 0.0, hv)
                               if hv not in (None, 0) else None),
        "log_mcap": math.log10(mcap_q) if mcap_q and mcap_q > 0 else None,
    }
    # adoption running ahead of price -- the divergence the layered strategy is built on.
    # Positive and large: holders / new buyers growing faster than the price has moved.
    pc5 = _safe(price - p5, p5)
    feat["holders_vs_price"] = _safe(hv, abs(pc5)) if hv is not None and pc5 not in (None, 0) else None
    nb_growth = _safe(nb5, len(ws_prev.get("buyers", set()))) if nb5 is not None else None
    feat["buyers_vs_price"] = (_safe(nb_growth, abs(pc5))
                               if nb_growth is not None and pc5 not in (None, 0) else None)
    if have_transfers:
        feat.update(tape.flow(b))
    return {
        "pair_id": tape.pool["pair_id"], "t_min": t_min, "block": b,
        "price": price, "liquidity_q": liq_q, "mcap_q": mcap_q,
        "n_trades": allw["n"], "n_buys": allw["n_buys"], "n_sells": allw["n_sells"],
        "vol_q": allw["vol"], "buy_vol_q": allw["buy"], "sell_vol_q": allw["sell"],
        "uniq_traders": (len(ws.get("buyers", set()) | ws.get("sellers", set()))
                         if have_transfers else None),
        "uniq_buyers": len(ws.get("buyers", set())) if have_transfers else None,
        "uniq_sellers": len(ws.get("sellers", set())) if have_transfers else None,
        "new_buyers": nb5,
        "holders": ws.get("holders"), "top1": ws.get("top1"), "top5": ws.get("top5"),
        "top10": ws.get("top10"), "top20": ws.get("top20"),
        "deployer_pct": ws.get("deployer_pct"),
        "feat_json": json.dumps(feat),
    }
