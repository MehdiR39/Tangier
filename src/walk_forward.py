"""
Walk-Forward evaluator for the stock scanner.

Splits the pooled training frame chronologically into expanding windows,
retrains the model at each fold, and records out-of-sample predictions.
From these predictions we compute:

- accuracy per class
- probability calibration (reliability curve)
- realised forward returns per signal (what would we have gained?)

This is the honest answer to "is the signal_quality_pct meaningful?".
"""

import logging
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


EXCLUDE_COLS = {"Open", "High", "Low", "Close", "Volume",
                "Returns", "Log_Returns", "Target",
                "ticker", "fwd_return"}  # internal bookkeeping, not features


def _feature_cols(df: pd.DataFrame) -> List[str]:
    return [c for c in df.columns if c not in EXCLUDE_COLS]


def walk_forward_eval(
    featured_per_ticker: Dict[str, pd.DataFrame],
    trainer_factory,
    target_creator,
    n_splits: int = 5,
    min_train_frac: float = 0.4,
    return_horizon: int = 5,
) -> pd.DataFrame:
    """
    Runs walk-forward training on the pooled dataset.

    Each ticker in `featured_per_ticker` contains engineered features +
    OHLCV (Target is NOT yet assigned; we re-create it inside each fold
    from the future returns, to respect the train/test boundary).

    Args:
        featured_per_ticker: {symbol: DataFrame with features and OHLCV}
        trainer_factory: callable() -> fresh ModelTrainer (one per fold).
        target_creator: TargetCreator instance (for labels).
        n_splits: number of expanding-window folds.
        min_train_frac: first fold's training share of the timeline.
        return_horizon: forward-return horizon (bars) to compute realised P&L.

    Returns:
        DataFrame with one row per OOS prediction:
            timestamp, ticker, p_sell, p_hold, p_buy,
            pred_class, true_class, fwd_return, signal_quality,
            direction
    """
    # Pooled timeline: union of all timestamps across tickers
    all_timestamps = pd.DatetimeIndex(
        sorted({ts for df in featured_per_ticker.values() for ts in df.index})
    )
    if len(all_timestamps) < 100:
        raise ValueError("Not enough timestamps to run walk-forward")

    # Build fold boundaries: expanding training window, fixed-size OOS chunks
    start_idx = int(len(all_timestamps) * min_train_frac)
    remaining = len(all_timestamps) - start_idx
    fold_size = max(20, remaining // n_splits)

    all_oos_rows: List[dict] = []

    for fold in range(n_splits):
        train_end = start_idx + fold * fold_size
        test_end = min(train_end + fold_size, len(all_timestamps))
        if train_end >= len(all_timestamps) or test_end <= train_end:
            break

        train_cut = all_timestamps[train_end - 1]
        test_cut = all_timestamps[test_end - 1]
        logger.info(
            f"Fold {fold+1}/{n_splits}: train until {train_cut.date()}, "
            f"test until {test_cut.date()}"
        )

        # Build training frame from each ticker's [ : train_cut ] slice
        train_pieces = []
        test_pieces = []
        for sym, feats in featured_per_ticker.items():
            tr = feats.loc[:train_cut]
            te = feats.loc[train_cut:test_cut].iloc[1:]  # avoid overlap
            if len(tr) < 100 or len(te) == 0:
                continue
            labelled = target_creator.create_targets(tr.copy(), sym)
            if labelled.empty:
                continue
            labelled["ticker"] = sym
            train_pieces.append(labelled)

            te = te.copy()
            te["ticker"] = sym
            # For OOS we also compute realised forward return (using future Close)
            te["fwd_return"] = te["Close"].pct_change(return_horizon).shift(-return_horizon)
            test_pieces.append(te)

        if not train_pieces or not test_pieces:
            logger.warning(f"Fold {fold+1}: insufficient data, skipping")
            continue

        train_df = pd.concat(train_pieces, axis=0).reset_index(drop=True)
        cols = _feature_cols(train_df)
        clean = train_df[cols + ["Target"]].replace([np.inf, -np.inf], np.nan).dropna()
        X_tr, y_tr = clean[cols], clean["Target"].astype(int)

        trainer = trainer_factory()
        selected = trainer.feature_selector.select_features(X_tr, y_tr) or cols
        trainer.feature_selector.selected_features = selected
        trainer.train(X_tr[selected], y_tr, symbol=f"WF_fold{fold+1}")

        # OOS predictions — keep row-level info
        for te in test_pieces:
            missing = [c for c in selected if c not in te.columns]
            if missing:
                continue
            Xte = te[selected].replace([np.inf, -np.inf], np.nan).dropna()
            if Xte.empty:
                continue
            aligned = te.loc[Xte.index]
            probas = trainer.predict(Xte)
            pred = np.argmax(probas, axis=1)
            # Compute true class the same way as training targets would
            # on this test slice — needed for accuracy
            labelled_te = target_creator.create_targets(
                te.drop(columns=["ticker", "fwd_return"]).copy(),
                aligned["ticker"].iloc[0] if "ticker" in aligned else "?"
            )
            true_by_idx = labelled_te["Target"].to_dict() if "Target" in labelled_te else {}

            for i, ts in enumerate(Xte.index):
                p_sell, p_hold, p_buy = float(probas[i, 0]), float(probas[i, 1]), float(probas[i, 2])
                quality = max(p_buy, p_sell)
                all_oos_rows.append({
                    "timestamp": ts,
                    "ticker": aligned.loc[ts, "ticker"],
                    "fold": fold + 1,
                    "p_sell": p_sell,
                    "p_hold": p_hold,
                    "p_buy": p_buy,
                    "signal_quality": quality,
                    "direction": "LONG" if p_buy >= p_sell else "SHORT",
                    "pred_class": int(pred[i]),
                    "true_class": int(true_by_idx.get(ts, -1)),
                    "fwd_return": float(aligned.loc[ts, "fwd_return"])
                                  if pd.notna(aligned.loc[ts, "fwd_return"]) else np.nan,
                })

    return pd.DataFrame(all_oos_rows)


# ---------------------------------------------------------------------------
# Analysis helpers
# ---------------------------------------------------------------------------
def calibration_bins(oos: pd.DataFrame, n_bins: int = 10) -> pd.DataFrame:
    """
    Compare predicted signal_quality to realised 'was the signal correct'.
    Returns a table: bin, avg_predicted_quality, realised_hit_rate, count.
    """
    df = oos.copy()
    # Hit: did the predicted direction produce the expected forward move?
    df["hit"] = np.where(
        df["direction"] == "LONG", df["fwd_return"] > 0, df["fwd_return"] < 0
    ).astype(int)
    df = df.dropna(subset=["fwd_return"])

    df["bin"] = pd.cut(df["signal_quality"], bins=n_bins, include_lowest=True)
    out = df.groupby("bin", observed=True).agg(
        avg_predicted_quality=("signal_quality", "mean"),
        realised_hit_rate=("hit", "mean"),
        count=("hit", "size"),
        avg_fwd_return=("fwd_return", "mean"),
    ).reset_index()
    return out


def accuracy_by_class(oos: pd.DataFrame) -> pd.DataFrame:
    df = oos[oos["true_class"].isin([0, 1, 2])]
    if df.empty:
        return pd.DataFrame()
    return (
        df.groupby("true_class")
        .apply(lambda g: (g["pred_class"] == g["true_class"]).mean())
        .rename("accuracy")
        .reset_index()
        .assign(true_class=lambda d: d["true_class"].map({0: "Sell", 1: "Hold", 2: "Buy"}))
    )
