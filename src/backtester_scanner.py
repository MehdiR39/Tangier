"""
Simple Top-K Backtester for the stock scanner.

Strategy simulated:
    - At each rebalance date:
        * Train the global model on all data STRICTLY BEFORE that date.
        * Run the scanner.
        * Go long equal-weight on top K 'LONG' signals (optionally short
          top K 'SHORT' signals).
        * Hold until the next rebalance.
    - Tracks daily equity, trades, and P&L.

No leverage. No stops. No transaction cost by default (pass `fee_bps`).
This is the honest baseline the scanner creates value against.
"""

import logging
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


EXCLUDE_COLS = {"Open", "High", "Low", "Close", "Volume",
                "Returns", "Log_Returns", "Target"}


def _feature_cols(df: pd.DataFrame) -> List[str]:
    return [c for c in df.columns if c not in EXCLUDE_COLS]


def _rebalance_dates(timeline: pd.DatetimeIndex, every_n_bars: int,
                     start_offset: int) -> List[pd.Timestamp]:
    dates = []
    i = start_offset
    while i < len(timeline):
        dates.append(timeline[i])
        i += every_n_bars
    return dates


def backtest_topk(
    featured_per_ticker: Dict[str, pd.DataFrame],
    trainer_factory,
    target_creator,
    top_k: int = 10,
    rebalance_bars: int = 5,
    hold_bars: int = 5,
    min_train_bars: int = 300,
    allow_short: bool = True,
    fee_bps: float = 5.0,
    initial_capital: float = 1.0,
    stop_atr_mult: Optional[float] = None,
    take_profit_atr_mult: Optional[float] = None,
) -> Dict[str, pd.DataFrame]:
    """
    Backtest the scanner as a long/(short) top-K rebalancing strategy.

    Returns dict with:
        'equity'   — DataFrame indexed by date, col 'equity'
        'trades'   — log of every position taken
        'summary'  — scalar metrics (CAGR, Sharpe, max DD, hit rate)
    """
    # Union timeline
    timeline = pd.DatetimeIndex(
        sorted({ts for df in featured_per_ticker.values() for ts in df.index})
    )
    if len(timeline) < min_train_bars + hold_bars:
        raise ValueError("Not enough history for backtest")

    rebalance_dates = _rebalance_dates(timeline, rebalance_bars, min_train_bars)
    logger.info(
        f"Backtest: {len(rebalance_dates)} rebalances on {len(timeline)} bars, "
        f"top_k={top_k}, hold_bars={hold_bars}, allow_short={allow_short}"
    )

    equity = initial_capital
    equity_curve: List[Tuple[pd.Timestamp, float]] = [(timeline[min_train_bars - 1], equity)]
    trades: List[dict] = []
    fee = fee_bps / 10_000.0

    for i, rebal_ts in enumerate(rebalance_dates):
        # 1. Train on [start, rebal_ts]
        train_pieces = []
        for sym, feats in featured_per_ticker.items():
            sl = feats.loc[:rebal_ts]
            if len(sl) < 100:
                continue
            lbl = target_creator.create_targets(sl.copy(), sym)
            if not lbl.empty:
                train_pieces.append(lbl)
        if not train_pieces:
            continue
        train_df = pd.concat(train_pieces, axis=0).reset_index(drop=True)
        cols = _feature_cols(train_df)
        clean = train_df[cols + ["Target"]].replace([np.inf, -np.inf], np.nan).dropna()
        X_tr, y_tr = clean[cols], clean["Target"].astype(int)

        trainer = trainer_factory()
        selected = trainer.feature_selector.select_features(X_tr, y_tr) or cols
        trainer.feature_selector.selected_features = selected
        trainer.train(X_tr[selected], y_tr, symbol=f"BT_{i}")

        # 2. Scan at rebal_ts: predict on the bar AT rebal_ts for each ticker
        scan_rows = []
        for sym, feats in featured_per_ticker.items():
            if rebal_ts not in feats.index:
                continue
            row = feats.loc[[rebal_ts], selected].replace([np.inf, -np.inf], np.nan).dropna()
            if row.empty:
                continue
            proba = trainer.predict(row)[0]
            p_sell, p_hold, p_buy = float(proba[0]), float(proba[1]), float(proba[2])
            scan_rows.append({
                "ticker": sym, "p_sell": p_sell, "p_hold": p_hold, "p_buy": p_buy,
                "quality": max(p_buy, p_sell),
                "direction": "LONG" if p_buy >= p_sell else "SHORT",
            })
        if not scan_rows:
            continue
        scan_df = pd.DataFrame(scan_rows).sort_values("quality", ascending=False)

        longs = scan_df[scan_df["direction"] == "LONG"].head(top_k)
        shorts = scan_df[scan_df["direction"] == "SHORT"].head(top_k) if allow_short else \
                 pd.DataFrame(columns=scan_df.columns)

        # 3. Realise P&L: open at rebal_ts close, exit at hold_bars later OR
        #    earlier if stop/take-profit is hit (ATR-based).
        leg_returns = []
        for _, r in pd.concat([longs.assign(side=1), shorts.assign(side=-1)]).iterrows():
            sym = r["ticker"]
            feats = featured_per_ticker[sym]
            idx = feats.index
            pos = idx.get_indexer([rebal_ts])[0]
            if pos == -1 or pos + hold_bars >= len(idx):
                continue

            entry = float(feats["Close"].iloc[pos])
            side = int(r["side"])
            # ATR at entry — fall back to HV × Close if ATR missing
            atr_val = float(feats.get("ATR", pd.Series()).iloc[pos]) \
                      if "ATR" in feats.columns else np.nan
            if not np.isfinite(atr_val) or atr_val <= 0:
                atr_val = entry * 0.02  # default: 2% as ATR proxy

            stop_level = (entry - side * stop_atr_mult * atr_val) \
                         if stop_atr_mult else None
            tp_level = (entry + side * take_profit_atr_mult * atr_val) \
                       if take_profit_atr_mult else None

            # Walk bars forward until stop, TP, or hold_bars
            exit_pos = pos + hold_bars
            exit_reason = "time"
            for k in range(1, hold_bars + 1):
                bar_idx = pos + k
                bar = feats.iloc[bar_idx]
                hi, lo = float(bar["High"]), float(bar["Low"])
                if side == 1:
                    # Long: stop if low <= stop, TP if high >= tp
                    if stop_level is not None and lo <= stop_level:
                        exit_pos = bar_idx
                        exit_reason = "stop"
                        break
                    if tp_level is not None and hi >= tp_level:
                        exit_pos = bar_idx
                        exit_reason = "take_profit"
                        break
                else:
                    # Short: stop if high >= stop, TP if low <= tp
                    if stop_level is not None and hi >= stop_level:
                        exit_pos = bar_idx
                        exit_reason = "stop"
                        break
                    if tp_level is not None and lo <= tp_level:
                        exit_pos = bar_idx
                        exit_reason = "take_profit"
                        break

            if exit_reason == "stop":
                exit_price = stop_level
            elif exit_reason == "take_profit":
                exit_price = tp_level
            else:
                exit_price = float(feats["Close"].iloc[exit_pos])

            raw_ret = (exit_price / entry - 1.0) * side
            net_ret = raw_ret - 2 * fee
            leg_returns.append(net_ret)
            trades.append({
                "rebal_ts": rebal_ts,
                "ticker": sym,
                "side": "LONG" if side == 1 else "SHORT",
                "entry_price": entry,
                "exit_price": float(exit_price),
                "entry_ts": idx[pos],
                "exit_ts": idx[exit_pos],
                "quality": float(r["quality"]),
                "gross_return": float(raw_ret),
                "net_return": float(net_ret),
                "exit_reason": exit_reason,
            })

        if not leg_returns:
            continue
        # Equal-weight across legs (long side + short side)
        portfolio_ret = float(np.mean(leg_returns))
        equity *= (1.0 + portfolio_ret)

        exit_ts = timeline[min(
            timeline.get_indexer([rebal_ts])[0] + hold_bars,
            len(timeline) - 1
        )]
        equity_curve.append((exit_ts, equity))

    eq_df = pd.DataFrame(equity_curve, columns=["date", "equity"]).set_index("date")
    eq_df = eq_df[~eq_df.index.duplicated(keep="last")]
    trades_df = pd.DataFrame(trades)
    summary = _summarize(eq_df, trades_df)
    return {"equity": eq_df, "trades": trades_df, "summary": summary}


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
def _summarize(equity: pd.DataFrame, trades: pd.DataFrame,
               periods_per_year: int = 252) -> pd.DataFrame:
    if equity.empty:
        return pd.DataFrame([{"metric": "empty", "value": np.nan}])

    eq = equity["equity"]
    returns = eq.pct_change().dropna()
    n_years = max((eq.index[-1] - eq.index[0]).days / 365.25, 1e-6)
    cagr = eq.iloc[-1] ** (1 / n_years) - 1
    sharpe = (returns.mean() / (returns.std() + 1e-10)) * np.sqrt(periods_per_year) \
             if len(returns) > 1 else np.nan
    running_max = eq.cummax()
    drawdown = (eq / running_max - 1).min()
    hit_rate = (trades["net_return"] > 0).mean() if not trades.empty else np.nan
    avg_win = trades.loc[trades["net_return"] > 0, "net_return"].mean() if not trades.empty else np.nan
    avg_loss = trades.loc[trades["net_return"] <= 0, "net_return"].mean() if not trades.empty else np.nan

    return pd.DataFrame([
        {"metric": "final_equity", "value": float(eq.iloc[-1])},
        {"metric": "CAGR", "value": float(cagr)},
        {"metric": "Sharpe", "value": float(sharpe) if sharpe == sharpe else np.nan},
        {"metric": "max_drawdown", "value": float(drawdown)},
        {"metric": "n_trades", "value": int(len(trades))},
        {"metric": "hit_rate", "value": float(hit_rate) if hit_rate == hit_rate else np.nan},
        {"metric": "avg_win", "value": float(avg_win) if avg_win == avg_win else np.nan},
        {"metric": "avg_loss", "value": float(avg_loss) if avg_loss == avg_loss else np.nan},
    ])
