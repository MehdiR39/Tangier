"""
Daily Stock Signals — orchestrator for the scanner-as-a-service.

Pipeline:
  1. Load model (retrain if stale or --retrain passed)
  2. Fetch/refresh OHLCV for universe
  3. Scan + filter by quality + liquidity
  4. Enrich with event context (earnings, ex-dividend, macro, gap)
  5. Drop CRITICAL, keep CLEAN/MEDIUM/HIGH
  6. Format Telegram message
  7. Send via TelegramNotifier
  8. Append to history CSV for later performance tracking

Usage:
    python daily_signals.py                         # default: sp500, top 20
    python daily_signals.py --retrain               # force retrain
    python daily_signals.py --dry-run               # print instead of send
    python daily_signals.py --universe config       # 30-ticker dev universe
"""

import os
import sys
import argparse
import logging
from datetime import datetime, timezone
from typing import List

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from config import config
from src.data_manager_stocks import StockDataManager
from src.feature_engineer import FeatureEngineer
from src.model_trainer import ModelTrainer, TargetCreator
from src.scanner_utils import fetch_metadata, filter_universe
from src.macro_features import (
    fetch_macro_series, build_macro_features,
    compute_breadth, attach_macro_to_tickers,
)
from src.ticker_events import fetch_ticker_events
from src.signal_filters import enrich_signals, drop_critical
from src.trade_plan import attach_trade_plans, MIN_ACCEPTABLE_RR
from src.live_utils import TelegramNotifier
from scanner import build_training_frame, train_global_model, scan, SCANNER_MODEL_NAME

logger = logging.getLogger(__name__)

HISTORY_CSV = os.path.join(config.RESULTS_DIR, "signal_history.csv")


# ---------------------------------------------------------------------------
# Telegram formatting
# ---------------------------------------------------------------------------
TIER_ICONS = {"CLEAN": "🟢", "MEDIUM": "🟡", "HIGH": "🟠", "CRITICAL": "🔴"}


def _short_event(events_summary: str) -> str:
    """Collapse verbose events_summary into short tags for table cell."""
    if not events_summary or events_summary == "—":
        return "clean"
    import re
    parts = [p.strip() for p in events_summary.split("|")]
    tags = []
    for p in parts:
        # "📊 earnings in 3d (2026-04-22)" -> "earn 3d"
        m = re.search(r"earnings in (\d+)d", p)
        if m:
            tags.append(f"earn {m.group(1)}d")
            continue
        # "💰 ex-div in 5d" -> "div 5d"
        m = re.search(r"ex-div in (\d+)d", p)
        if m:
            tags.append(f"div {m.group(1)}d")
            continue
        # "🏛️ FOMC Meeting (Apr/May) in 10d" -> "FOMC 10d"
        m = re.search(r"(FOMC|CPI|NFP|PCE).*?in (\d+)d", p)
        if m:
            tags.append(f"{m.group(1)} {m.group(2)}d")
            continue
        # "↕️ gap +5.2% 1d ago" -> "gap 5.2%"
        m = re.search(r"gap ([+-]?[\d.]+)%", p)
        if m:
            tags.append(f"gap {m.group(1)}%")
            continue
    return ", ".join(tags) if tags else "clean"


def _tier_rank(tier: str) -> int:
    return {"CLEAN": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}.get(tier, 4)


def _html_escape(s: str) -> str:
    return (s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;"))


def _format_trade_plan(r: pd.Series) -> str:
    """Format one signal as a compact trade plan block."""
    tier = r.get("risk_level", "CLEAN")
    icon = TIER_ICONS.get(tier, "⚪")
    ticker = r["ticker"]
    direction = r.get("direction", "?")
    dir_emoji = "📈" if direction == "LONG" else "📉"
    q = float(r.get("signal_quality_pct", 0))
    close = float(r.get("close", 0))

    # Trade plan fields
    entry_low = r.get("entry_low")
    entry_high = r.get("entry_high")
    stop = r.get("stop")
    t1 = r.get("target_1")
    t2 = r.get("target_2")
    rr = r.get("rr")
    risk_pct = r.get("risk_pct")
    reward_pct = r.get("reward_pct")
    trigger = r.get("trigger", "")
    plan_q = r.get("plan_quality", "")
    events = r.get("events_summary", "")

    # Header line
    lines = [
        f"{icon} <b>{ticker}</b>  {dir_emoji} {direction}  <b>{q:.0f}%</b>  @ ${close:,.2f}"
    ]

    # If plan not computable, just show events
    if entry_low is None or pd.isna(entry_low):
        lines.append(f"   <i>no plan (data missing)</i>")
        if events and events != "—":
            lines.append(f"   ⚠️ {_short_event(str(events))}")
        return "\n".join(lines)

    # Entry zone
    lines.append(f"   Entry  ${entry_low:.2f} — ${entry_high:.2f}")

    # Stop
    if stop and pd.notna(stop) and risk_pct and pd.notna(risk_pct):
        lines.append(f"   Stop   ${stop:.2f}  (-{abs(risk_pct):.1f}%)")

    # Targets
    if t1 and pd.notna(t1) and reward_pct and pd.notna(reward_pct):
        lines.append(f"   T1     ${t1:.2f}  (+{abs(reward_pct):.1f}%)")
    if t2 and pd.notna(t2):
        ext_pct = abs(t2 / close - 1) * 100
        lines.append(f"   T2     ${t2:.2f}  (+{ext_pct:.1f}%)")

    # R/R + plan quality indicator
    if rr and pd.notna(rr):
        rr_mark = "✅" if plan_q == "accept" else ("⚠️ weak" if plan_q == "poor_rr" else "")
        lines.append(f"   R/R    {rr:.2f}  {rr_mark}")

    # Trigger
    if trigger:
        lines.append(f"   Wait   {trigger}")

    # Events
    if events and events != "—":
        lines.append(f"   Event  {_short_event(str(events))}")

    return "\n".join(lines)


def format_telegram_message(
    enriched: pd.DataFrame,
    dropped: pd.DataFrame,
    universe_name: str,
    n_total_universe: int,
    max_signals: int = 8,
) -> str:
    """
    Build an HTML message for Telegram with full trade plans per signal.
    Shows only the top `max_signals` (ranked by plan quality then quality%).
    """
    now = datetime.now(timezone.utc)

    header = (
        f"📊 <b>STOCK SIGNALS — {now:%Y-%m-%d}</b>\n"
        f"<i>universe: {universe_name} ({n_total_universe} tickers) · "
        f"generated: {now:%H:%M UTC}</i>\n"
    )

    if enriched.empty and dropped.empty:
        return header + "\n<i>No signals today.</i>"

    # Sort: plan_quality=accept first, then by signal_quality desc
    df = enriched.copy()
    plan_rank = {"accept": 0, "poor_rr": 1, "no_target": 2, "": 3}
    if "plan_quality" in df.columns:
        df["_plan_rank"] = df["plan_quality"].map(lambda x: plan_rank.get(x, 3))
    else:
        df["_plan_rank"] = 3
    df = df.sort_values(
        by=["_plan_rank", "signal_quality_pct"],
        ascending=[True, False],
    ).head(max_signals)

    # Accept block
    accept_block = df[df.get("plan_quality", "") == "accept"]
    weak_block = df[df.get("plan_quality", "") == "poor_rr"]
    other_block = df[~df.get("plan_quality", "").isin(["accept", "poor_rr"])]

    parts = [header]

    if not accept_block.empty:
        parts.append(f"\n<b>✅ ACTIONABLE (R/R ≥ {MIN_ACCEPTABLE_RR})</b>\n")
        for _, r in accept_block.iterrows():
            parts.append(_format_trade_plan(r))
            parts.append("")

    if not weak_block.empty:
        parts.append(f"\n<b>⚠️ WEAK R/R (skip unless strong conviction)</b>\n")
        for _, r in weak_block.iterrows():
            parts.append(_format_trade_plan(r))
            parts.append("")

    if not other_block.empty and accept_block.empty and weak_block.empty:
        parts.append("\n<b>No target detected (no clear swing level)</b>\n")
        for _, r in other_block.head(3).iterrows():
            parts.append(_format_trade_plan(r))
            parts.append("")

    # Dropped
    if not dropped.empty:
        parts.append("\n<b>🔴 DROPPED — event ≤2d</b>")
        for _, r in dropped.iterrows():
            parts.append(
                f"  • {r['ticker']} — {_short_event(str(r.get('events_summary', '')))}"
            )
        parts.append("")

    # Footer stats
    n_kept = len(enriched)
    n_drop = len(dropped)
    n_actionable = int((enriched.get("plan_quality", pd.Series()) == "accept").sum()) \
                   if "plan_quality" in enriched.columns else 0
    parts.append(
        f"\n<i>{n_total_universe} tickers → {n_kept + n_drop} ranked → "
        f"{n_actionable} actionable · {n_drop} dropped</i>"
    )

    msg = "\n".join(parts)
    if len(msg) > 4000:
        msg = msg[:3950] + "\n<i>...truncated</i>"
    return msg


# ---------------------------------------------------------------------------
# History logging
# ---------------------------------------------------------------------------
def append_to_history(enriched: pd.DataFrame) -> None:
    if enriched.empty:
        return
    out = enriched.copy()
    out["scan_ts"] = datetime.now(timezone.utc).isoformat()
    if "risk_tags" in out.columns:
        out["risk_tags"] = out["risk_tags"].apply(
            lambda x: ",".join(x) if isinstance(x, list) else ""
        )
    header = not os.path.exists(HISTORY_CSV)
    out.to_csv(HISTORY_CSV, mode="a", header=header, index=False)
    logger.info(f"Appended {len(out)} rows to {HISTORY_CSV}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Daily stock signals scanner")
    parser.add_argument("--universe", default="sp500",
                        help="'sp500' (default) or 'config'")
    parser.add_argument("--top", type=int, default=20,
                        help="Number of top signals to scan (before filtering)")
    parser.add_argument("--retrain", action="store_true",
                        help="Force model retrain")
    parser.add_argument("--min-quality", type=float, default=60.0,
                        help="Minimum signal_quality_pct")
    parser.add_argument("--min-dollar-volume", type=float, default=50e6,
                        help="Minimum 20d avg $-volume")
    parser.add_argument("--earnings-days-ahead", type=int, default=7)
    parser.add_argument("--gap-threshold", type=float, default=0.05)
    parser.add_argument("--dry-run", action="store_true",
                        help="Print message instead of sending to Telegram")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )

    dm = StockDataManager(config)
    fe = FeatureEngineer(config)
    tc = TargetCreator(config)
    trainer = ModelTrainer(config)

    # --- Universe resolution ---
    if args.universe == "sp500":
        tickers = dm.sp500_tickers()
    elif args.universe == "config":
        tickers = getattr(config, "STOCK_UNIVERSE", [])
    else:
        raise ValueError(f"Unknown universe: {args.universe}")
    n_universe = len(tickers)
    logger.info(f"Universe: {n_universe} tickers ({args.universe})")

    # --- Fetch OHLCV ---
    data_dict = dm.fetch_universe(tickers)
    if not data_dict:
        logger.error("No data fetched. Aborting.")
        return

    # --- Liquidity filter ---
    if args.min_dollar_volume > 0:
        data_dict = filter_universe(
            data_dict, min_dollar_volume=args.min_dollar_volume,
        )

    # --- Macro features attach ---
    try:
        macro_raw = fetch_macro_series(
            start=config.DATA_START_DATE, end=config.DATA_END_DATE,
        )
        macro_feats = build_macro_features(macro_raw)
        breadth = compute_breadth(data_dict, sma_period=50)
        data_enriched = attach_macro_to_tickers(data_dict, macro_feats, breadth)
    except Exception as e:
        logger.warning(f"Macro enrichment failed ({e}), continuing without macros")
        data_enriched = data_dict

    # --- Training frame + model load/retrain ---
    training, featured = build_training_frame(data_enriched, fe, tc)

    model_loaded = (not args.retrain) and trainer.load_model(SCANNER_MODEL_NAME)
    if not model_loaded:
        logger.info("Training global model...")
        train_global_model(training, trainer)

    # --- Scan ---
    top = scan(featured, trainer, top_n=args.top)
    if top.empty:
        logger.warning("No signals generated")
        msg = format_telegram_message(top, top, args.universe, n_universe)
    else:
        if args.min_quality > 0:
            top = top[top["signal_quality_pct"] >= args.min_quality].reset_index(drop=True)

        # --- Enrichment with events ---
        if top.empty:
            enriched, dropped = top, top
        else:
            logger.info(f"Fetching event context for {len(top)} tickers...")
            ticker_events = fetch_ticker_events(top["ticker"].tolist(), max_workers=8)
            enriched_all = enrich_signals(
                top, data_dict,
                ticker_events=ticker_events,
                critical_days=max(1, args.earnings_days_ahead // 3),
                high_days=args.earnings_days_ahead,
                medium_days=args.earnings_days_ahead * 2,
                gap_threshold=args.gap_threshold,
            )
            enriched, dropped = drop_critical(enriched_all)

            # --- Attach trade plans (entry/stop/target/RR/trigger) ---
            if not enriched.empty:
                enriched = attach_trade_plans(enriched, data_dict)

        # --- Log history ---
        append_to_history(enriched)

        # --- Format ---
        msg = format_telegram_message(enriched, dropped, args.universe, n_universe)

    # --- Deliver ---
    if args.dry_run:
        print("\n" + "=" * 60)
        print("DRY RUN — Message that would be sent:")
        print("=" * 60)
        print(msg)
        print("=" * 60)
    else:
        notifier = TelegramNotifier()
        success = notifier.send_message(msg, parse_mode="HTML")
        if success:
            logger.info("Daily signals sent to Telegram ✓")
        else:
            logger.error("Failed to send Telegram notification")
            print("\nMessage (not sent):\n", msg)


if __name__ == "__main__":
    main()
