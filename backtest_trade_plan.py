"""
Trade plan ablation — runs multiple variants and reports which wins.

Pipeline:
  1. Load 30-ticker universe + attach macro + engineer features
  2. Load saved global model (or retrain if missing)
  3. On the last 30% of the timeline, for every ticker-date where the model
     predicts LONG or SHORT with proba >= threshold → add a signal to the list
  4. For each trade plan variant, simulate the outcome on each signal
  5. Compare summary metrics and print ranking
"""

import os
import sys
import logging
from functools import partial

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import config
from src.data_manager_stocks import StockDataManager
from src.feature_engineer import FeatureEngineer
from src.model_trainer import ModelTrainer, TargetCreator
from src.macro_features import (
    fetch_macro_series, build_macro_features,
    compute_breadth, attach_macro_to_tickers,
)
from src.trade_plan_backtest import (
    simulate_trade, backtest_variant, summarize,
    trigger_immediate, trigger_sma20_cross, trigger_breakout_n,
    stop_atr, stop_swing, target_swing, target_atr,
)
from scanner import build_training_frame, train_global_model, SCANNER_MODEL_NAME

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Wrapper functions matching simulate_trade signatures
# ---------------------------------------------------------------------------
def make_trigger(kind, n=3):
    if kind == "immediate":
        return lambda fwd, sc, d, **ctx: trigger_immediate(fwd, sc, d)
    if kind == "sma20":
        return lambda fwd, sc, d, sma_20, **ctx: trigger_sma20_cross(fwd, sc, d, sma_20)
    if kind.startswith("breakout"):
        nb = int(kind.split("_")[-1])
        return lambda fwd, sc, d, history, **ctx: trigger_breakout_n(fwd, sc, d, nb, history)
    raise ValueError(kind)


def make_stop(kind, mult=2.0):
    if kind.startswith("atr"):
        m = float(kind.split("_")[-1]) if "_" in kind else mult
        return lambda entry, atr, d, **ctx: stop_atr(entry, atr, d, m)
    if kind == "swing":
        return lambda entry, atr, d, swing_low, swing_high, **ctx: \
            stop_swing(entry, swing_low, swing_high, d, fallback_atr=atr)
    raise ValueError(kind)


def make_target(kind):
    if kind == "none":
        return None
    if kind == "swing":
        return lambda entry, atr, d, swing_low, swing_high, **ctx: \
            target_swing(entry, swing_low, swing_high, d)
    if kind.startswith("atr"):
        m = float(kind.split("_")[-1])
        return lambda entry, atr, d, **ctx: target_atr(entry, atr, d, m)
    raise ValueError(kind)


# ---------------------------------------------------------------------------
# Build signals
# ---------------------------------------------------------------------------
def generate_historical_signals(
    trainer, featured_per_ticker, test_fraction=0.30, min_quality=0.40,
) -> list:
    """
    For each ticker, predict on the TEST portion (last `test_fraction` of
    each ticker's history) using a model that has ONLY seen the train
    portion. Returns list of (ticker, bar_idx, direction) for LONG/SHORT
    signals above the quality threshold.

    Caller is responsible for training the model on the train portion only
    before passing it here.
    """
    signals = []
    selected = trainer.feature_selector.selected_features
    if not selected:
        raise RuntimeError("Model has no selected_features — load/train first")

    for ticker, feats in featured_per_ticker.items():
        missing = [c for c in selected if c not in feats.columns]
        if missing:
            continue
        X = feats[selected].replace([np.inf, -np.inf], np.nan).dropna()
        if len(X) < 100:
            continue
        test_start = int(len(X) * (1 - test_fraction))
        X_test = X.iloc[test_start:]
        probas = trainer.predict(X_test)

        ohlcv_idx = feats.index
        for i, ts in enumerate(X_test.index):
            p_sell, p_hold, p_buy = probas[i]
            max_p = max(p_buy, p_sell)
            if max_p < min_quality:
                continue
            direction = "LONG" if p_buy >= p_sell else "SHORT"
            pos = ohlcv_idx.get_indexer([ts])[0]
            if pos < 0:
                continue
            signals.append((ticker, pos, direction))
    return signals


def train_on_train_portion(
    featured_per_ticker, tc, config_obj, train_fraction=0.70,
) -> ModelTrainer:
    """
    Slice each ticker's featured frame to its first `train_fraction`, build
    a pooled training DataFrame, then train a fresh model. Guarantees the
    test period is genuinely unseen.
    """
    train_pieces = []
    for sym, feats in featured_per_ticker.items():
        cut = int(len(feats) * train_fraction)
        piece = feats.iloc[:cut]
        labelled = tc.create_targets(piece.copy(), sym)
        if not labelled.empty:
            train_pieces.append(labelled)
    if not train_pieces:
        raise RuntimeError("Empty training pool")
    train_df = pd.concat(train_pieces, axis=0).reset_index(drop=True)

    EXCLUDE = {"Open", "High", "Low", "Close", "Volume",
               "Returns", "Log_Returns", "Target"}
    cols = [c for c in train_df.columns if c not in EXCLUDE]
    clean = train_df[cols + ["Target"]].replace([np.inf, -np.inf], np.nan).dropna()
    X, y = clean[cols], clean["Target"].astype(int)

    trainer = ModelTrainer(config_obj)
    selected = trainer.feature_selector.select_features(X, y) or cols
    trainer.feature_selector.selected_features = selected
    trainer.train(X[selected], y, symbol="TRAIN_ONLY")
    return trainer


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    # Build data pipeline
    print("1/4 Loading data + features...")
    dm = StockDataManager(config)
    data_dict = dm.fetch_universe(config.STOCK_UNIVERSE)
    macro_raw = fetch_macro_series(
        start=config.DATA_START_DATE, end=config.DATA_END_DATE,
    )
    macro_feats = build_macro_features(macro_raw)
    breadth = compute_breadth(data_dict, sma_period=50)
    data_enriched = attach_macro_to_tickers(data_dict, macro_feats, breadth)

    fe = FeatureEngineer(config)
    tc = TargetCreator(config)
    training, featured = build_training_frame(data_enriched, fe, tc)

    # Train model on FIRST 70% only so the test period is genuinely unseen
    print("2/4 Training model on first 70% (test 30% is OOS)...")
    trainer = train_on_train_portion(featured, tc, config, train_fraction=0.70)

    # Generate historical signals on the last 30%
    print("3/4 Generating historical signals on held-out test set...")
    signals = generate_historical_signals(
        trainer, featured,
        test_fraction=0.30,
        min_quality=0.40,
    )
    print(f"   → {len(signals)} signals over {len(featured)} tickers")

    # IMPORTANT : the simulate_trade function needs OHLCV with ATR.
    # Our featured DataFrames do have ATR (engineered), so we pass them.
    # But `data_dict` (raw OHLCV) does NOT. We use `featured` for simulation.
    data_for_sim = featured

    # ------------------------------------------------------------------
    # Ablation 1 : triggers  (stop = ATR×2, target = swing-high)
    # ------------------------------------------------------------------
    print("\n4/4 Running ablations...\n")
    print("=" * 78)
    print("ABLATION 1 : TRIGGER  (stop=2×ATR, target=swing-high, hold=10, fee=5bps)")
    print("=" * 78)
    trigger_variants = [
        ("immediate",   "immediate"),
        ("sma20_cross", "sma20"),
        ("breakout_3",  "breakout_3"),
        ("breakout_5",  "breakout_5"),
    ]
    trig_results = []
    for name, kind in trigger_variants:
        res = backtest_variant(
            signals, data_for_sim,
            trigger_fn=make_trigger(kind),
            stop_fn=make_stop("atr_2.0"),
            target_fn=make_target("swing"),
            max_hold_bars=10, trigger_window=3, fee_bps=5.0,
        )
        trig_results.append(summarize(res, name))
    trig_df = pd.DataFrame(trig_results)
    print(trig_df.to_string(index=False))
    best_trigger_kind = trigger_variants[
        int(trig_df["expectancy"].fillna(-999).argmax())
    ][1]
    print(f"\n>> BEST TRIGGER (by expectancy): {best_trigger_kind}")

    # ------------------------------------------------------------------
    # Ablation 2 : stops  (best trigger, target = swing)
    # ------------------------------------------------------------------
    print("\n" + "=" * 78)
    print(f"ABLATION 2 : STOP  (trigger={best_trigger_kind}, target=swing-high)")
    print("=" * 78)
    stop_variants = [
        ("atr_1.5",   "atr_1.5"),
        ("atr_2.0",   "atr_2.0"),
        ("atr_3.0",   "atr_3.0"),
        ("swing",     "swing"),
    ]
    stop_results = []
    for name, kind in stop_variants:
        res = backtest_variant(
            signals, data_for_sim,
            trigger_fn=make_trigger(best_trigger_kind),
            stop_fn=make_stop(kind),
            target_fn=make_target("swing"),
            max_hold_bars=10, trigger_window=3, fee_bps=5.0,
        )
        stop_results.append(summarize(res, name))
    stop_df = pd.DataFrame(stop_results)
    print(stop_df.to_string(index=False))
    best_stop_kind = stop_variants[
        int(stop_df["expectancy"].fillna(-999).argmax())
    ][1]
    print(f"\n>> BEST STOP: {best_stop_kind}")

    # ------------------------------------------------------------------
    # Ablation 3 : targets  (best trigger + stop)
    # ------------------------------------------------------------------
    print("\n" + "=" * 78)
    print(f"ABLATION 3 : TARGET  (trigger={best_trigger_kind}, stop={best_stop_kind})")
    print("=" * 78)
    target_variants = [
        ("swing",    "swing"),
        ("atr_2.0",  "atr_2.0"),
        ("atr_3.0",  "atr_3.0"),
        ("none",     "none"),
    ]
    tgt_results = []
    for name, kind in target_variants:
        res = backtest_variant(
            signals, data_for_sim,
            trigger_fn=make_trigger(best_trigger_kind),
            stop_fn=make_stop(best_stop_kind),
            target_fn=make_target(kind),
            max_hold_bars=10, trigger_window=3, fee_bps=5.0,
        )
        tgt_results.append(summarize(res, name))
    tgt_df = pd.DataFrame(tgt_results)
    print(tgt_df.to_string(index=False))
    best_target_kind = target_variants[
        int(tgt_df["expectancy"].fillna(-999).argmax())
    ][1]
    print(f"\n>> BEST TARGET: {best_target_kind}")

    # ------------------------------------------------------------------
    # Final verdict
    # ------------------------------------------------------------------
    print("\n" + "=" * 78)
    print("FINAL VERDICT")
    print("=" * 78)
    print(f"Winning trade plan :")
    print(f"   Trigger : {best_trigger_kind}")
    print(f"   Stop    : {best_stop_kind}")
    print(f"   Target  : {best_target_kind}")
    print(f"   Hold    : max 10 bars")
    print(f"   Fees    : 5 bps per side\n")
    # Also report this final combo's metrics
    final = backtest_variant(
        signals, data_for_sim,
        trigger_fn=make_trigger(best_trigger_kind),
        stop_fn=make_stop(best_stop_kind),
        target_fn=make_target(best_target_kind),
        max_hold_bars=10, trigger_window=3, fee_bps=5.0,
    )
    final_summary = summarize(final, "FINAL")
    for k, v in final_summary.items():
        print(f"  {k:>15} = {v}")


if __name__ == "__main__":
    main()
