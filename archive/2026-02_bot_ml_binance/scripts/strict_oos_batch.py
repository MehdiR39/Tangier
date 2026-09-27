#!/usr/bin/env python3
"""
Batch strict OOS runner.
Launches multiple (symbol, model) strict OOS evaluations with worker auto-dispatch.
"""

import argparse
import concurrent.futures
import json
import os
import subprocess
import sys
import time
from datetime import datetime

import pandas as pd


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS_DIR = os.path.join(ROOT_DIR, "results")


def _run_one(task: dict) -> dict:
    symbol = task["symbol"]
    model = task["model"]
    cmd = [
        sys.executable,
        os.path.join("scripts", "strict_oos_eval.py"),
        "--symbol",
        symbol,
        "--model",
        model,
        "--valid-start",
        task["valid_start"],
        "--holdout-start",
        task["holdout_start"],
        "--trials",
        str(task["trials"]),
        "--workers",
        str(task["trial_workers"]),
        "--objective-mode",
        task["objective_mode"],
        "--gate-min-return-delta",
        str(task["gate_min_return_delta"]),
        "--gate-min-sharpe-delta",
        str(task["gate_min_sharpe_delta"]),
        "--gate-max-dd-delta",
        str(task["gate_max_dd_delta"]),
        "--gate-min-trades",
        str(task["gate_min_trades"]),
    ]
    if task["no_plots"]:
        cmd.append("--no-plots")

    t0 = time.time()
    proc = subprocess.run(
        cmd,
        cwd=ROOT_DIR,
        text=True,
        capture_output=True,
    )
    elapsed = time.time() - t0

    report_path = os.path.join(RESULTS_DIR, f"{symbol}_{model}_strict_oos_report.json")
    if proc.returncode != 0:
        return {
            "symbol": symbol,
            "model": model,
            "status": "failed",
            "elapsed_sec": round(elapsed, 2),
            "error": (proc.stderr or proc.stdout)[-1200:],
        }
    if not os.path.exists(report_path):
        return {
            "symbol": symbol,
            "model": model,
            "status": "failed",
            "elapsed_sec": round(elapsed, 2),
            "error": f"missing report: {report_path}",
        }

    with open(report_path, "r", encoding="utf-8") as f:
        report = json.load(f)

    baseline = report["holdout_baseline"]
    tuned = report["holdout_tuned"]
    selected = report.get("selected_metrics", baseline)
    gate = report.get("deployment_gate", {})

    return {
        "symbol": symbol,
        "model": model,
        "status": "ok",
        "elapsed_sec": round(elapsed, 2),
        "selected_strategy": report.get("selected_strategy", "baseline"),
        "gate_deploy_tuned": bool(gate.get("deploy_tuned", False)),
        "baseline_return_pct": float(baseline["return_pct"]),
        "tuned_return_pct": float(tuned["return_pct"]),
        "selected_return_pct": float(selected["return_pct"]),
        "baseline_sharpe": float(baseline["sharpe"]),
        "tuned_sharpe": float(tuned["sharpe"]),
        "selected_sharpe": float(selected["sharpe"]),
        "baseline_max_dd_pct": float(baseline["max_drawdown_pct"]),
        "tuned_max_dd_pct": float(tuned["max_drawdown_pct"]),
        "selected_max_dd_pct": float(selected["max_drawdown_pct"]),
        "baseline_trades": int(baseline["num_trades"]),
        "tuned_trades": int(tuned["num_trades"]),
        "selected_trades": int(selected["num_trades"]),
        "return_delta_tuned_minus_baseline": float(tuned["return_pct"]) - float(baseline["return_pct"]),
        "report_path": report_path,
    }


def _auto_dispatch(total_workers: int, n_tasks: int, trial_workers_override: int = None):
    total_workers = max(1, int(total_workers))
    n_tasks = max(1, int(n_tasks))
    if trial_workers_override is not None:
        trial_workers = max(1, int(trial_workers_override))
        parallel_jobs = max(1, min(n_tasks, total_workers // trial_workers))
        if parallel_jobs == 0:
            parallel_jobs = 1
        return parallel_jobs, trial_workers

    # Target around 4 trial workers per task by default.
    parallel_jobs = max(1, min(n_tasks, total_workers // 4))
    trial_workers = max(1, total_workers // parallel_jobs)
    return parallel_jobs, trial_workers


def main():
    parser = argparse.ArgumentParser(description="Batch strict OOS runner")
    parser.add_argument("--symbols", type=str, required=True, help="Comma-separated symbols")
    parser.add_argument("--models", type=str, default="random_forest,xgboost,extra_trees", help="Comma-separated models")
    parser.add_argument("--trials", type=int, default=20, help="Optuna trials per task")
    parser.add_argument("--workers", type=int, default=16, help="Total CPU workers budget")
    parser.add_argument("--trial-workers", type=int, default=None, help="Optional fixed Optuna workers per task")
    parser.add_argument("--parallel-jobs", type=int, default=None, help="Optional fixed number of concurrent tasks")
    parser.add_argument("--valid-start", type=str, default="2024-01-01")
    parser.add_argument("--holdout-start", type=str, default="2025-01-01")
    parser.add_argument("--objective-mode", type=str, default="robust_windows")
    parser.add_argument("--gate-min-return-delta", type=float, default=0.0)
    parser.add_argument("--gate-min-sharpe-delta", type=float, default=-0.10)
    parser.add_argument("--gate-max-dd-delta", type=float, default=5.0)
    parser.add_argument("--gate-min-trades", type=int, default=5)
    parser.add_argument("--no-plots", action="store_true")
    args = parser.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    models = [m.strip().lower() for m in args.models.split(",") if m.strip()]
    tasks = [{"symbol": s, "model": m} for s in symbols for m in models]
    if not tasks:
        raise ValueError("No tasks to run")

    auto_parallel, auto_trial_workers = _auto_dispatch(
        total_workers=args.workers,
        n_tasks=len(tasks),
        trial_workers_override=args.trial_workers,
    )
    parallel_jobs = max(1, int(args.parallel_jobs)) if args.parallel_jobs is not None else auto_parallel
    trial_workers = auto_trial_workers

    print("=" * 80)
    print("STRICT OOS BATCH")
    print("=" * 80)
    print(f"Symbols: {', '.join(symbols)}")
    print(f"Models: {', '.join(models)}")
    print(
        f"Workers: total={int(args.workers)}, parallel_jobs={parallel_jobs}, "
        f"trial_workers_per_task={trial_workers}"
    )
    print(
        f"Split: train<{args.valid_start} | valid[{args.valid_start},{args.holdout_start}) | "
        f"holdout>={args.holdout_start}"
    )
    print(f"Trials per task: {int(args.trials)} | Objective: {args.objective_mode}")
    print("=" * 80)

    enriched_tasks = []
    for t in tasks:
        task = dict(t)
        task.update({
            "valid_start": args.valid_start,
            "holdout_start": args.holdout_start,
            "trials": int(args.trials),
            "trial_workers": int(trial_workers),
            "objective_mode": str(args.objective_mode).strip().lower(),
            "gate_min_return_delta": float(args.gate_min_return_delta),
            "gate_min_sharpe_delta": float(args.gate_min_sharpe_delta),
            "gate_max_dd_delta": float(args.gate_max_dd_delta),
            "gate_min_trades": int(args.gate_min_trades),
            "no_plots": bool(args.no_plots),
        })
        enriched_tasks.append(task)

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=parallel_jobs) as ex:
        future_map = {ex.submit(_run_one, t): t for t in enriched_tasks}
        done = 0
        total = len(enriched_tasks)
        for fut in concurrent.futures.as_completed(future_map):
            done += 1
            t = future_map[fut]
            try:
                out = fut.result()
            except Exception as e:
                out = {
                    "symbol": t["symbol"],
                    "model": t["model"],
                    "status": "failed",
                    "elapsed_sec": 0.0,
                    "error": str(e),
                }
            results.append(out)
            if out["status"] == "ok":
                print(
                    f"[{done}/{total}] {out['symbol']} {out['model']} | "
                    f"selected={out['selected_strategy']} | "
                    f"ret={out['selected_return_pct']:.2f}% | sharpe={out['selected_sharpe']:.2f}"
                )
            else:
                print(f"[{done}/{total}] {out['symbol']} {out['model']} | FAILED")

    df = pd.DataFrame(results)
    os.makedirs(RESULTS_DIR, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    csv_stamp = os.path.join(RESULTS_DIR, f"strict_oos_batch_summary_{stamp}.csv")
    csv_latest = os.path.join(RESULTS_DIR, "strict_oos_batch_summary.csv")
    json_stamp = os.path.join(RESULTS_DIR, f"strict_oos_batch_summary_{stamp}.json")

    df.to_csv(csv_stamp, index=False)
    df.to_csv(csv_latest, index=False)
    with open(json_stamp, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    ok_df = df[df["status"] == "ok"].copy() if "status" in df.columns else pd.DataFrame()
    if len(ok_df) > 0:
        # Best deployed model per symbol.
        best_rows = []
        for symbol, grp in ok_df.groupby("symbol"):
            best = grp.sort_values(
                by=["selected_return_pct", "selected_sharpe"],
                ascending=[False, False],
            ).iloc[0]
            best_rows.append(best)
        best_df = pd.DataFrame(best_rows).sort_values(by="selected_return_pct", ascending=False)
        best_path = os.path.join(RESULTS_DIR, "strict_oos_best_by_symbol.csv")
        best_df.to_csv(best_path, index=False)

        print("\nBEST DEPLOYED BY SYMBOL")
        print("-" * 80)
        for _, r in best_df.iterrows():
            print(
                f"{r['symbol']}: {r['model']} | selected={r['selected_strategy']} | "
                f"ret={r['selected_return_pct']:.2f}% | sharpe={r['selected_sharpe']:.2f} | "
                f"maxDD={r['selected_max_dd_pct']:.2f}%"
            )
        print("-" * 80)
        print(f"Best-by-symbol CSV: {best_path}")

    print(f"Batch CSV: {csv_stamp}")
    print(f"Latest CSV: {csv_latest}")
    print(f"Batch JSON: {json_stamp}")


if __name__ == "__main__":
    main()
