"""
Stock Scanner — scans a universe of tickers and returns the top-N
highest-conviction Buy/Sell signals.

Pipeline:
  1. Fetch OHLCV for the universe (StockDataManager).
  2. Engineer features (reuses FeatureEngineer from the crypto bot).
  3. Build training set by concatenating all tickers with a `ticker_id`
     feature and fit ONE global LightGBM model (ModelTrainer).
  4. At the latest bar for each ticker, run predict_proba and rank by
     max(p_buy, p_sell).

Usage:
    python scanner.py                 # uses STOCK_UNIVERSE from config
    python scanner.py --top 10 --universe sp500
    python scanner.py --retrain       # force retrain
"""

import os
import sys
import argparse
import logging
from datetime import datetime, timezone
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import config
from src.data_manager_stocks import StockDataManager
from src.feature_engineer import FeatureEngineer
from src.model_trainer import ModelTrainer, TargetCreator

logger = logging.getLogger(__name__)

SCANNER_MODEL_NAME = "SCANNER_GLOBAL"
EXCLUDE_COLS = {"Open", "High", "Low", "Close", "Volume",
                "Returns", "Log_Returns", "Target"}


# ---------------------------------------------------------------------------
# Training set construction
# ---------------------------------------------------------------------------
def build_training_frame(
    data_dict: Dict[str, pd.DataFrame],
    fe: FeatureEngineer,
    tc: TargetCreator,
) -> Tuple[pd.DataFrame, Dict[str, pd.DataFrame]]:
    """
    Engineer features + targets per ticker, then concat into one frame
    with a `ticker_id` column so a single model can learn cross-sectional.

    Returns (training_frame, per_ticker_featured_dict). The second dict is
    kept so the scanner can re-use features at inference without recomputing.
    """
    featured: Dict[str, pd.DataFrame] = {}
    pieces: List[pd.DataFrame] = []

    ticker_to_id = {sym: i for i, sym in enumerate(sorted(data_dict.keys()))}

    for sym, ohlcv in data_dict.items():
        try:
            feats = fe.engineer_features(ohlcv, sym)
        except Exception as e:
            logger.warning(f"{sym}: feature engineering failed ({e})")
            continue
        if feats.empty:
            continue

        feats["ticker_id"] = ticker_to_id[sym]
        featured[sym] = feats  # keep full frame for inference (no Target drop)

        try:
            labelled = tc.create_targets(feats, sym)
        except Exception as e:
            logger.warning(f"{sym}: target creation failed ({e})")
            continue
        if not labelled.empty:
            pieces.append(labelled)

    if not pieces:
        raise RuntimeError("No tickers produced a usable training frame")

    # Reset the DatetimeIndex → duplicate dates across tickers would otherwise
    # break any label-based alignment on this pooled frame.
    training = pd.concat(pieces, axis=0).sort_index().reset_index(drop=True)
    logger.info(
        f"Training frame: {len(training)} rows across "
        f"{len(pieces)} tickers, {training.shape[1]} columns"
    )
    return training, featured


def feature_cols_from(df: pd.DataFrame) -> List[str]:
    return [c for c in df.columns if c not in EXCLUDE_COLS]


# ---------------------------------------------------------------------------
# Train / load global model
# ---------------------------------------------------------------------------
def train_global_model(training: pd.DataFrame, trainer: ModelTrainer) -> List[str]:
    cols = feature_cols_from(training)
    clean = training[cols + ["Target"]].replace([np.inf, -np.inf], np.nan).dropna()
    X = clean[cols]
    y = clean["Target"].astype(int)

    # Feature selection on the pooled dataset
    selected = trainer.feature_selector.select_features(X, y)
    if not selected:
        selected = cols
    X = X[selected]

    trainer.train(X, y, symbol=SCANNER_MODEL_NAME)
    trainer.feature_selector.selected_features = selected
    trainer.save_model(SCANNER_MODEL_NAME)
    return selected


# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------
def scan(
    featured: Dict[str, pd.DataFrame],
    trainer: ModelTrainer,
    top_n: int = 10,
) -> pd.DataFrame:
    """
    For each ticker, take the latest row, run predict_proba, and rank by
    signal_quality = max(p_buy, p_sell).
    """
    selected = trainer.feature_selector.selected_features
    if not selected:
        raise RuntimeError("Trainer has no selected_features — model not loaded?")

    rows = []
    for sym, feats in featured.items():
        missing = [c for c in selected if c not in feats.columns]
        if missing:
            logger.debug(f"{sym}: missing features {missing[:5]}..., skipping")
            continue

        latest = feats[selected].replace([np.inf, -np.inf], np.nan).dropna()
        if latest.empty:
            continue
        last_row = latest.iloc[[-1]]
        last_ts = last_row.index[0]

        proba = trainer.predict(last_row)[0]  # [p_sell, p_hold, p_buy]
        p_sell, p_hold, p_buy = float(proba[0]), float(proba[1]), float(proba[2])

        if p_buy >= p_sell:
            direction, quality = "LONG", p_buy
        else:
            direction, quality = "SHORT", p_sell

        rows.append({
            "ticker": sym,
            "timestamp": last_ts,
            "direction": direction,
            "signal_quality_pct": round(quality * 100, 2),
            "p_sell": round(p_sell, 4),
            "p_hold": round(p_hold, 4),
            "p_buy": round(p_buy, 4),
            "close": float(feats["Close"].iloc[-1]),
        })

    if not rows:
        return pd.DataFrame()

    ranked = pd.DataFrame(rows).sort_values("signal_quality_pct", ascending=False)
    return ranked.head(top_n).reset_index(drop=True)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def resolve_universe(name: str, dm: StockDataManager) -> List[str]:
    name = (name or "config").lower()
    if name == "sp500":
        return dm.sp500_tickers()
    if name == "config":
        return getattr(config, "STOCK_UNIVERSE", [])
    raise ValueError(f"Unknown universe: {name}")


def main():
    parser = argparse.ArgumentParser(description="Stock signal scanner")
    parser.add_argument("--universe", default="config",
                        help="'config' (use STOCK_UNIVERSE) or 'sp500'")
    parser.add_argument("--top", type=int, default=10,
                        help="Number of top signals to return")
    parser.add_argument("--retrain", action="store_true",
                        help="Force retraining even if a saved model exists")
    parser.add_argument("--min-quality", type=float, default=0.0,
                        help="Filter out signals below this quality pct (0-100)")
    parser.add_argument("--interval", default=None,
                        help="Bar interval (1d, 1h, 30m...). "
                             "Overrides STOCK_INTERVAL in config. "
                             "Note: yfinance limits 1h history to ~730d.")
    parser.add_argument("--min-dollar-volume", type=float, default=None,
                        help="Filter tickers with 20d avg $-volume below this threshold")
    parser.add_argument("--include-sectors", nargs="+", default=None,
                        help="Keep only these sectors (e.g. Technology Healthcare)")
    parser.add_argument("--exclude-sectors", nargs="+", default=None,
                        help="Drop these sectors")
    parser.add_argument("--min-market-cap", type=float, default=None,
                        help="Min market cap in USD (e.g. 2e9 for >$2B)")
    parser.add_argument("--earnings-days-ahead", type=int, default=7,
                        help="Drop tickers with earnings in next N days "
                             "(0 or negative to disable)")
    parser.add_argument("--gap-threshold", type=float, default=0.05,
                        help="Drop tickers with abs(gap) > this in last 3 bars "
                             "(0 or negative to disable)")
    args = parser.parse_args()

    # Apply CLI interval override
    if args.interval:
        config.STOCK_INTERVAL = args.interval

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )

    dm = StockDataManager(config)
    fe = FeatureEngineer(config)
    tc = TargetCreator(config)
    trainer = ModelTrainer(config)

    tickers = resolve_universe(args.universe, dm)
    if not tickers:
        logger.error("Empty universe. Set STOCK_UNIVERSE in config.py "
                     "or pass --universe sp500")
        sys.exit(1)
    logger.info(f"Universe: {len(tickers)} tickers")

    data_dict = dm.fetch_universe(tickers)
    if not data_dict:
        logger.error("No tickers loaded. Aborting.")
        sys.exit(1)

    # Apply universe filters
    needs_meta = args.min_market_cap is not None or args.include_sectors \
                 or args.exclude_sectors
    metadata = None
    if needs_meta:
        from src.scanner_utils import fetch_metadata
        cache_path = os.path.join(config.DATA_DIR, "stocks", "metadata.parquet")
        metadata = fetch_metadata(list(data_dict.keys()), cache_path=cache_path)

    if any([args.min_dollar_volume, args.min_market_cap,
            args.include_sectors, args.exclude_sectors]):
        from src.scanner_utils import filter_universe
        data_dict = filter_universe(
            data_dict,
            metadata=metadata,
            min_dollar_volume=args.min_dollar_volume,
            min_market_cap=args.min_market_cap,
            include_sectors=args.include_sectors,
            exclude_sectors=args.exclude_sectors,
        )
        if not data_dict:
            logger.error("All tickers filtered out. Aborting.")
            sys.exit(1)

    _, featured = build_training_frame(data_dict, fe, tc)

    loaded = (not args.retrain) and trainer.load_model(SCANNER_MODEL_NAME)
    if not loaded:
        logger.info("Training new global model...")
        training, featured = build_training_frame(data_dict, fe, tc)
        train_global_model(training, trainer)
    else:
        logger.info("Loaded existing global model")

    top = scan(featured, trainer, top_n=args.top)
    if top.empty:
        print("No signals generated.")
        return

    if args.min_quality > 0:
        top = top[top["signal_quality_pct"] >= args.min_quality].reset_index(drop=True)

    # --- Enrichment : events context + tiered risk ---
    enriched = top
    dropped = top.iloc[0:0]
    if not top.empty and (args.earnings_days_ahead > 0 or args.gap_threshold > 0):
        from src.signal_filters import enrich_signals, drop_critical
        from src.ticker_events import fetch_ticker_events

        print(f"\nFetching event context for {len(top)} tickers...")
        ticker_events = fetch_ticker_events(top["ticker"].tolist(), max_workers=8)

        enriched = enrich_signals(
            top, data_dict,
            ticker_events=ticker_events,
            critical_days=max(1, args.earnings_days_ahead // 3) if args.earnings_days_ahead > 0 else 2,
            high_days=args.earnings_days_ahead if args.earnings_days_ahead > 0 else 7,
            medium_days=(args.earnings_days_ahead * 2) if args.earnings_days_ahead > 0 else 14,
            gap_threshold=args.gap_threshold if args.gap_threshold > 0 else 999,
        )
        enriched, dropped = drop_critical(enriched)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(config.RESULTS_DIR, f"scanner_top{args.top}_{ts}.csv")
    # Flatten risk_tags list → comma-separated string for CSV
    enriched_csv = enriched.copy()
    if not enriched_csv.empty and "risk_tags" in enriched_csv.columns:
        enriched_csv["risk_tags"] = enriched_csv["risk_tags"].apply(
            lambda x: ",".join(x) if isinstance(x, list) else ""
        )
    enriched_csv.to_csv(out_path, index=False)

    print("\n" + "=" * 80)
    print(f"TOP {len(enriched)} SIGNALS  —  universe={args.universe}  "
          f"generated={datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}")
    print("=" * 80)

    if not enriched.empty:
        display_cols = ["risk_icon", "ticker", "direction", "signal_quality_pct",
                        "close", "events_summary"]
        display_cols = [c for c in display_cols if c in enriched.columns]
        print(enriched[display_cols].to_string(index=False))

    if not dropped.empty:
        print(f"\n🔴 DROPPED (CRITICAL risk — event imminent) :")
        for _, r in dropped.iterrows():
            print(f"    {r['ticker']:6s}  {r.get('direction', ''):5s}  "
                  f"{r.get('signal_quality_pct', 0):5.1f}%  | {r.get('events_summary', '')}")

    # Summary par tier
    if not enriched.empty and "risk_level" in enriched.columns:
        counts = enriched["risk_level"].value_counts().to_dict()
        summary = " | ".join(
            f"{k}: {counts.get(k, 0)}"
            for k in ["CLEAN", "MEDIUM", "HIGH", "CRITICAL"]
            if counts.get(k, 0) > 0
        )
        print(f"\nTiers: {summary}")

    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
