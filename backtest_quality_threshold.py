"""
Quality threshold ablation — does filtering by signal_quality improve
expectancy per trade ?

Uses the winning trade plan from backtest_trade_plan.py :
  trigger = immediate, stop = 2×ATR, target = 2×ATR, hold = 10 bars.

Varies only the minimum signal_quality (proba of predicted class).
"""

import os
import sys
import logging

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import config
from src.data_manager_stocks import StockDataManager
from src.feature_engineer import FeatureEngineer
from src.model_trainer import TargetCreator
from src.macro_features import (
    fetch_macro_series, build_macro_features,
    compute_breadth, attach_macro_to_tickers,
)
from src.trade_plan_backtest import (
    backtest_variant, summarize,
    trigger_immediate, stop_atr, target_atr,
)
from scanner import build_training_frame
from backtest_trade_plan import (
    generate_historical_signals, train_on_train_portion,
)

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")


def main():
    print("Loading data + training on first 70%...")
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
    trainer = train_on_train_portion(featured, tc, config, train_fraction=0.70)

    print("\nQuality-threshold ablation with winning plan (immediate/2xATR/2xATR)\n")
    print("=" * 100)

    trigger_fn = lambda fwd, sc, d, **ctx: trigger_immediate(fwd, sc, d)
    stop_fn = lambda entry, atr, d, **ctx: stop_atr(entry, atr, d, 2.0)
    target_fn = lambda entry, atr, d, **ctx: target_atr(entry, atr, d, 2.0)

    thresholds = [0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75]
    rows = []
    for thr in thresholds:
        signals = generate_historical_signals(
            trainer, featured,
            test_fraction=0.30,
            min_quality=thr,
        )
        if len(signals) < 20:
            rows.append({
                "min_quality": thr,
                "n_signals": len(signals),
                "n_entered": 0,
                "hit_rate": np.nan,
                "expectancy": np.nan,
                "sum_returns": np.nan,
                "profit_factor": np.nan,
            })
            continue
        res = backtest_variant(
            signals, featured,
            trigger_fn=trigger_fn,
            stop_fn=stop_fn,
            target_fn=target_fn,
            max_hold_bars=10, trigger_window=3, fee_bps=5.0,
        )
        s = summarize(res, f"q≥{thr:.2f}")
        rows.append({
            "min_quality": thr,
            "n_signals": s["n_signals"],
            "n_entered": s["n_entered"],
            "hit_rate": s["hit_rate"],
            "expectancy": s["expectancy"],
            "sum_returns": s["sum_returns"],
            "profit_factor": s["profit_factor"],
        })

    df = pd.DataFrame(rows)
    print(df.to_string(index=False))
    print("\n" + "=" * 100)
    print("Reading : higher quality threshold = fewer signals, but expectancy should go UP")
    print("if the calibration is good. If flat/declining -> calibration bad, quality is noise.")


if __name__ == "__main__":
    main()
