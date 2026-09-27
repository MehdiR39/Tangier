# Automatic Strategy Optimization Guide

This guide explains how to use the new `optimize_strategy.py` script to automatically find the best parameters for your trading strategy.

## Overview

The optimization script performs two key functions:

1.  **Hyperparameter Optimization**: Automatically tests different combinations of trading parameters (stop-loss, take-profit, buy/sell thresholds) to find the most profitable setup.
2.  **Walk-Forward Validation**: Prevents overfitting by training the model on historical data and testing it on future data, then rolling forward in time.

## How to Run Optimization

To run the optimization, use the `optimize_strategy.py` script from your terminal:

```bash
python optimize_strategy.py
```

This will run both hyperparameter optimization and walk-forward validation for all symbols defined in your `config.py` file.

### Command-Line Options

You can customize the optimization with these flags:

-   `--symbol <SYMBOL>`: Optimize only a single symbol (e.g., `BTCUSDT`).
-   `--symbols <S1,S2>`: Optimize a specific list of symbols.
-   `--no-hyperopt`: Skip hyperparameter optimization.
-   `--no-wf`: Skip walk-forward validation.
-   `--trials <N>`: Set the number of optimization trials (default: 50).

**Example:**

Run hyperparameter optimization for BTCUSDT and ETHUSDT with 100 trials:

```bash
python optimize_strategy.py --symbols BTCUSDT,ETHUSDT --trials 100
```

## What to Expect

-   **Time**: Optimization can take a long time, especially with many trials.
-   **Output**: The script will log its progress and save the best parameters and validation results to the `results/` directory.
-   **Log Files**: Detailed logs are saved in the `logs/` directory.

## Interpreting the Results

After optimization, you will find these files in your `results/` directory:

-   **`<SYMBOL>_best_params.json`**: The best trading parameters found for each symbol.
-   **`<SYMBOL>_walk_forward_results.csv`**: The performance of the strategy in each walk-forward window.

Use these results to update your `config.py` with the optimized parameters for live trading.

## Next Steps

1.  Run the optimization script.
2.  Review the results.
3.  Update your `config.py` with the best parameters.
4.  Run the `live_trading.py` script with your optimized strategy.
