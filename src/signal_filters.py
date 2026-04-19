"""
Pre-notification enrichment + tiered filter for scanner signals.

New contract (v2):
    Every signal is enriched with event context instead of being simply
    dropped. A risk tier is assigned based on the shortest event delay.

    Tiers:
      🔴 CRITICAL — event in <= critical_days (default 2)   → filtered OUT
      🟠 HIGH     — event in <= high_days     (default 7)   → kept w/ flag
      🟡 MEDIUM   — event in <= medium_days   (default 14)  → kept w/ flag
      🟢 CLEAN    — no event within medium_days             → kept

    Events considered:
      - earnings       (ticker-specific, via yfinance)
      - ex-dividend    (ticker-specific, via yfinance)
      - gap > threshold in last 3 bars (ticker-specific, from OHLCV)
      - FOMC / CPI / NFP / PCE (market-wide, hard-coded calendar)
"""

import logging
from typing import Dict, List, Optional, Tuple

import pandas as pd

from src.event_calendar import next_macro_event

logger = logging.getLogger(__name__)


RISK_ICONS = {
    "CLEAN":    "🟢",
    "MEDIUM":   "🟡",
    "HIGH":     "🟠",
    "CRITICAL": "🔴",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _days_to(date: pd.Timestamp, ref: pd.Timestamp) -> int:
    return int((pd.Timestamp(date).normalize() - ref.normalize()).days)


def _classify(days: Optional[int], critical: int, high: int, medium: int) -> str:
    """
    Map days-until-event to a tier. Pass critical/high/medium = -1 to
    disable that tier for the given event type.
    """
    if days is None or days < 0:
        return "CLEAN"
    if critical >= 0 and days <= critical:
        return "CRITICAL"
    if high >= 0 and days <= high:
        return "HIGH"
    if medium >= 0 and days <= medium:
        return "MEDIUM"
    return "CLEAN"


def _merge_tier(a: str, b: str) -> str:
    """Return the worst (most restrictive) of two tiers."""
    order = {"CLEAN": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
    return a if order[a] >= order[b] else b


# ---------------------------------------------------------------------------
# Gap check (standalone — doesn't need API)
# ---------------------------------------------------------------------------
def recent_gap_info(
    df: pd.DataFrame,
    lookback_bars: int = 3,
    threshold: float = 0.05,
) -> Optional[dict]:
    """Returns {'gap_pct': .., 'bars_ago': ..} if a gap > threshold found, else None."""
    if len(df) < lookback_bars + 1:
        return None
    gaps = (df["Open"] / df["Close"].shift(1) - 1)
    recent = gaps.tail(lookback_bars)
    abs_max = recent.abs().max()
    if pd.notna(abs_max) and abs_max > threshold:
        idx_max = recent.abs().idxmax()
        return {
            "gap_pct": float(recent.loc[idx_max]),
            "bars_ago": int(lookback_bars - recent.index.get_loc(idx_max) - 1),
        }
    return None


# ---------------------------------------------------------------------------
# Main enrichment
# ---------------------------------------------------------------------------
def enrich_signals(
    ranked_scan: pd.DataFrame,
    data_dict: Dict[str, pd.DataFrame],
    ticker_events: Optional[Dict[str, dict]] = None,
    reference_date: Optional[pd.Timestamp] = None,
    critical_days: int = 2,
    high_days: int = 7,
    medium_days: int = 14,
    gap_threshold: float = 0.05,
    gap_lookback: int = 3,
) -> pd.DataFrame:
    """
    Add event-context columns + risk tier to each signal.

    New columns added:
      - risk_level      (str)   CLEAN / MEDIUM / HIGH / CRITICAL
      - risk_icon       (str)   🟢 🟡 🟠 🔴
      - events_summary  (str)   human-readable event list
      - risk_tags       (list)  ['EARNINGS_3D', 'FOMC_5D', 'GAP_4pct', ...]
      - next_earnings_date  (Timestamp or NaT)
      - days_to_earnings    (int or NaN)
      - ex_dividend_date    (Timestamp or NaT)
      - days_to_exdiv       (int or NaN)
      - next_macro_label    (str)
      - days_to_macro       (int or NaN)
      - recent_gap_pct      (float or NaN)
    """
    if ranked_scan.empty:
        return ranked_scan

    ref = pd.Timestamp(reference_date or pd.Timestamp.today()).normalize()
    ticker_events = ticker_events or {}

    # Next macro event (shared across tickers)
    macro = next_macro_event(ref)

    rows = []
    for _, sig in ranked_scan.iterrows():
        sym = sig["ticker"]
        events = ticker_events.get(sym, {})

        tier = "CLEAN"
        tags: List[str] = []
        summary: List[str] = []

        # --- Earnings ---
        earn_date = events.get("next_earnings_date")
        days_earn = None
        if pd.notna(earn_date) and earn_date is not None:
            days_earn = _days_to(earn_date, ref)
            if days_earn >= 0:
                t = _classify(days_earn, critical_days, high_days, medium_days)
                tier = _merge_tier(tier, t)
                if t != "CLEAN":
                    tags.append(f"EARNINGS_{days_earn}D")
                    summary.append(
                        f"📊 earnings in {days_earn}d ({pd.Timestamp(earn_date):%Y-%m-%d})"
                    )

        # --- Ex-dividend ---
        exdiv_date = events.get("ex_dividend_date")
        days_exdiv = None
        if pd.notna(exdiv_date) and exdiv_date is not None:
            days_exdiv = _days_to(exdiv_date, ref)
            if days_exdiv >= 0 and days_exdiv <= medium_days:
                # Ex-div is less critical than earnings → cap at HIGH
                t = _classify(days_exdiv, -1, high_days, medium_days)  # no CRITICAL for dividends
                tier = _merge_tier(tier, t)
                if t != "CLEAN":
                    tags.append(f"EXDIV_{days_exdiv}D")
                    summary.append(
                        f"💰 ex-div in {days_exdiv}d"
                    )

        # --- Macro event (same for all tickers) ---
        days_macro = None
        macro_label = None
        if macro:
            days_macro = int(macro["days_ahead"])
            macro_label = macro["label"]
            if 0 <= days_macro <= medium_days:
                # Macro events = market-wide binary risk, cap at HIGH
                t = _classify(days_macro, -1, high_days, medium_days)
                tier = _merge_tier(tier, t)
                if t != "CLEAN":
                    tags.append(f"{macro['event_type']}_{days_macro}D")
                    summary.append(f"🏛️ {macro_label} in {days_macro}d")

        # --- Recent gap (from OHLCV) ---
        gap_pct = None
        gap_info = recent_gap_info(
            data_dict.get(sym, pd.DataFrame()),
            lookback_bars=gap_lookback, threshold=gap_threshold,
        )
        if gap_info:
            gap_pct = gap_info["gap_pct"]
            # Large recent gap → HIGH risk (indicators polluted)
            tier = _merge_tier(tier, "HIGH")
            tags.append(f"GAP_{abs(gap_pct)*100:.1f}pct")
            summary.append(
                f"↕️ gap {gap_pct*100:+.1f}% {gap_info['bars_ago']}d ago"
            )

        rows.append({
            "ticker": sym,
            "direction": sig.get("direction"),
            "signal_quality_pct": sig.get("signal_quality_pct"),
            "close": sig.get("close"),
            "p_sell": sig.get("p_sell"),
            "p_hold": sig.get("p_hold"),
            "p_buy": sig.get("p_buy"),
            "risk_level": tier,
            "risk_icon": RISK_ICONS[tier],
            "events_summary": " | ".join(summary) if summary else "—",
            "risk_tags": tags,
            "next_earnings_date": earn_date,
            "days_to_earnings": days_earn,
            "ex_dividend_date": exdiv_date,
            "days_to_exdiv": days_exdiv,
            "next_macro_label": macro_label,
            "days_to_macro": days_macro,
            "recent_gap_pct": gap_pct,
        })

    return pd.DataFrame(rows)


def drop_critical(ranked_scan: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Split an enriched DataFrame into (kept, dropped_critical).
    Only rows tagged CRITICAL are dropped; HIGH/MEDIUM/CLEAN are kept.
    """
    if "risk_level" not in ranked_scan.columns:
        return ranked_scan, ranked_scan.iloc[0:0]
    mask_critical = ranked_scan["risk_level"] == "CRITICAL"
    return (ranked_scan[~mask_critical].reset_index(drop=True),
            ranked_scan[mask_critical].reset_index(drop=True))


# ---------------------------------------------------------------------------
# Legacy API (kept for back-compat with earlier CLI integration)
# ---------------------------------------------------------------------------
def apply_post_scan_filters(
    ranked_scan: pd.DataFrame,
    data_dict: Dict[str, pd.DataFrame],
    earnings_days_ahead: Optional[int] = 7,
    gap_threshold: Optional[float] = 0.05,
    gap_lookback: int = 3,
    fundamentals_cache: Optional[Dict] = None,
) -> Tuple[pd.DataFrame, Dict[str, List[str]]]:
    """
    Legacy binary-drop API. Prefer `enrich_signals` + `drop_critical`.
    Kept so existing CLI callers don't break.
    """
    from src.ticker_events import fetch_ticker_events
    tickers = ranked_scan["ticker"].tolist() if not ranked_scan.empty else []
    ev = fetch_ticker_events(tickers) if tickers else {}

    enriched = enrich_signals(
        ranked_scan, data_dict, ticker_events=ev,
        critical_days=max(1, (earnings_days_ahead or 7) // 3),
        high_days=earnings_days_ahead or 7,
        medium_days=(earnings_days_ahead or 7) * 2,
        gap_threshold=gap_threshold or 0.05,
        gap_lookback=gap_lookback,
    )
    kept, dropped = drop_critical(enriched)
    dropped_by_reason = {
        "earnings": [r["ticker"] for _, r in dropped.iterrows()
                     if r["days_to_earnings"] is not None and r["days_to_earnings"] >= 0],
        "gap": [],
    }
    return kept, dropped_by_reason
