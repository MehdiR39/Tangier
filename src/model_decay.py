"""
Model decay analysis — how fast does a trained model lose its edge
as time passes without retraining ?

Protocol :
  1. Pick N anchor dates evenly spread in the timeline
  2. For each anchor : train a fresh model on data BEFORE the anchor
  3. Predict on bars AFTER the anchor at several horizons
     (e.g. 3, 7, 14, 30, 60 days after training)
  4. Measure OOS hit rate at each horizon
  5. Aggregate across anchors → decay curve

The curve answers : "if I last retrained D days ago, what hit rate should
I expect today ?" → tells us when it's worth retraining.
"""

import logging
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


EXCLUDE_COLS = {"Open", "High", "Low", "Close", "Volume",
                "Returns", "Log_Returns", "Target"}


def _feature_cols(df: pd.DataFrame) -> List[str]:
    return [c for c in df.columns if c not in EXCLUDE_COLS]


def _build_train_frame(
    featured_per_ticker: Dict[str, pd.DataFrame],
    target_creator,
    train_until: pd.Timestamp,
) -> pd.DataFrame:
    pieces = []
    for sym, feats in featured_per_ticker.items():
        sl = feats.loc[:train_until]
        if len(sl) < 100:
            continue
        labelled = target_creator.create_targets(sl.copy(), sym)
        if not labelled.empty:
            pieces.append(labelled)
    if not pieces:
        return pd.DataFrame()
    return pd.concat(pieces, axis=0).reset_index(drop=True)


def model_decay_analysis(
    featured_per_ticker: Dict[str, pd.DataFrame],
    target_creator,
    trainer_factory,
    horizon_days: Optional[List[int]] = None,
    n_anchors: int = 6,
    min_anchor_frac: float = 0.35,
    max_anchor_frac: float = 0.75,
    return_horizon_bars: int = 5,
    min_quality: float = 0.50,
) -> pd.DataFrame:
    """
    Returns DataFrame with columns :
      anchor_date | horizon_days | n_predictions | hit_rate | avg_fwd_return

    hit_rate is measured on signals LONG/SHORT (excludes Hold).
    `return_horizon_bars` is the number of bars we look FORWARD from each
    prediction to realise the outcome (should match the target horizon).
    """
    if horizon_days is None:
        horizon_days = [3, 7, 14, 30, 60]
    max_h = max(horizon_days)

    # Build union timeline
    all_ts = sorted({ts for df in featured_per_ticker.values() for ts in df.index})
    timeline = pd.DatetimeIndex(all_ts)

    if len(timeline) < 200:
        raise ValueError("Not enough timeline bars for decay analysis")

    # Anchor positions evenly spaced between min and max fraction
    start_i = int(len(timeline) * min_anchor_frac)
    end_i = int(len(timeline) * max_anchor_frac)
    anchor_positions = np.linspace(start_i, end_i, n_anchors).astype(int)
    anchor_dates = timeline[anchor_positions]

    rows = []
    for i_anchor, anchor in enumerate(anchor_dates):
        logger.info(f"[anchor {i_anchor+1}/{n_anchors}] train until {anchor.date()}")

        # 1. Build training frame
        train_df = _build_train_frame(featured_per_ticker, target_creator, anchor)
        if train_df.empty:
            continue
        cols = _feature_cols(train_df)
        clean = train_df[cols + ["Target"]].replace([np.inf, -np.inf], np.nan).dropna()
        X_tr, y_tr = clean[cols], clean["Target"].astype(int)

        trainer = trainer_factory()
        selected = trainer.feature_selector.select_features(X_tr, y_tr) or cols
        trainer.feature_selector.selected_features = selected
        trainer.train(X_tr[selected], y_tr, symbol=f"DECAY_{i_anchor}")

        # 2. For each horizon, gather predictions on bars in [anchor + h_start, anchor + h_end]
        anchor_pos = int(timeline.get_indexer([anchor])[0])

        for h in horizon_days:
            target_pos = anchor_pos + h
            if target_pos + return_horizon_bars >= len(timeline):
                continue
            target_ts = timeline[target_pos]

            hits_total = 0
            n_pred = 0
            aligned_rets = []

            for sym, feats in featured_per_ticker.items():
                if target_ts not in feats.index:
                    continue
                # Skip if ticker doesn't have return_horizon_bars more data
                ts_pos = feats.index.get_indexer([target_ts])[0]
                if ts_pos < 0 or ts_pos + return_horizon_bars >= len(feats):
                    continue

                row = feats.loc[[target_ts], selected].replace([np.inf, -np.inf], np.nan).dropna()
                if row.empty:
                    continue

                proba = trainer.predict(row)[0]  # [sell, hold, buy]
                p_sell, p_hold, p_buy = float(proba[0]), float(proba[1]), float(proba[2])

                if max(p_buy, p_sell) < min_quality:
                    continue

                direction = "LONG" if p_buy >= p_sell else "SHORT"
                # Realised fwd return
                entry = float(feats["Close"].iloc[ts_pos])
                exit_ = float(feats["Close"].iloc[ts_pos + return_horizon_bars])
                fwd_ret = (exit_ - entry) / entry

                aligned = fwd_ret if direction == "LONG" else -fwd_ret
                aligned_rets.append(aligned)
                if aligned > 0:
                    hits_total += 1
                n_pred += 1

            if n_pred > 0:
                rows.append({
                    "anchor_date": anchor,
                    "horizon_days": h,
                    "n_predictions": n_pred,
                    "hit_rate": hits_total / n_pred,
                    "avg_aligned_return": float(np.mean(aligned_rets)),
                })

    return pd.DataFrame(rows)


def aggregate_decay(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate per-anchor measurements into a decay curve by horizon."""
    if df.empty:
        return df
    agg = df.groupby("horizon_days").agg(
        n_predictions=("n_predictions", "sum"),
        hit_rate_mean=("hit_rate", "mean"),
        hit_rate_std=("hit_rate", "std"),
        avg_return_mean=("avg_aligned_return", "mean"),
        n_anchors=("hit_rate", "size"),
    ).reset_index()
    return agg
