"""
Macro event calendar — FOMC, CPI, NFP, PCE (US).

Hard-coded with official schedules (published by Fed and BLS at the start
of the year). Known far enough in advance that the hard-coded list is
sufficient.

Sources used at build time:
  - FOMC    : federalreserve.gov/monetarypolicy/fomccalendars.htm
  - CPI     : bls.gov/schedule/news_release/cpi.htm
  - NFP     : bls.gov/schedule/news_release/empsit.htm
  - PCE     : bea.gov/news/schedule
"""

import logging
from datetime import date
from typing import List, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)


# Calendrier macro US 2026 — dates officielles (mises à jour annuellement)
# Format: (date ISO, event_type, label)
MACRO_EVENTS: List[Tuple[str, str, str]] = [
    # --- 2026 FOMC (8 meetings/year) ---
    ("2026-01-28", "FOMC", "FOMC Meeting (Jan)"),
    ("2026-03-18", "FOMC", "FOMC Meeting (Mar)"),
    ("2026-04-29", "FOMC", "FOMC Meeting (Apr/May)"),
    ("2026-06-17", "FOMC", "FOMC Meeting (Jun)"),
    ("2026-07-29", "FOMC", "FOMC Meeting (Jul)"),
    ("2026-09-16", "FOMC", "FOMC Meeting (Sep)"),
    ("2026-10-28", "FOMC", "FOMC Meeting (Oct/Nov)"),
    ("2026-12-16", "FOMC", "FOMC Meeting (Dec)"),

    # --- 2026 CPI releases (monthly, ~mid-month) ---
    ("2026-01-13", "CPI", "CPI Dec-2025"),
    ("2026-02-11", "CPI", "CPI Jan-2026"),
    ("2026-03-12", "CPI", "CPI Feb-2026"),
    ("2026-04-10", "CPI", "CPI Mar-2026"),
    ("2026-05-13", "CPI", "CPI Apr-2026"),
    ("2026-06-11", "CPI", "CPI May-2026"),
    ("2026-07-15", "CPI", "CPI Jun-2026"),
    ("2026-08-12", "CPI", "CPI Jul-2026"),
    ("2026-09-11", "CPI", "CPI Aug-2026"),
    ("2026-10-15", "CPI", "CPI Sep-2026"),
    ("2026-11-13", "CPI", "CPI Oct-2026"),
    ("2026-12-10", "CPI", "CPI Nov-2026"),

    # --- 2026 NFP / Employment Situation (first Friday monthly) ---
    ("2026-01-09", "NFP", "NFP Dec-2025"),
    ("2026-02-06", "NFP", "NFP Jan-2026"),
    ("2026-03-06", "NFP", "NFP Feb-2026"),
    ("2026-04-03", "NFP", "NFP Mar-2026"),
    ("2026-05-01", "NFP", "NFP Apr-2026"),
    ("2026-06-05", "NFP", "NFP May-2026"),
    ("2026-07-02", "NFP", "NFP Jun-2026"),
    ("2026-08-07", "NFP", "NFP Jul-2026"),
    ("2026-09-04", "NFP", "NFP Aug-2026"),
    ("2026-10-02", "NFP", "NFP Sep-2026"),
    ("2026-11-06", "NFP", "NFP Oct-2026"),
    ("2026-12-04", "NFP", "NFP Nov-2026"),

    # --- 2026 PCE releases ---
    ("2026-01-30", "PCE", "PCE Dec-2025"),
    ("2026-02-27", "PCE", "PCE Jan-2026"),
    ("2026-03-27", "PCE", "PCE Feb-2026"),
    ("2026-04-30", "PCE", "PCE Mar-2026"),
    ("2026-05-29", "PCE", "PCE Apr-2026"),
    ("2026-06-26", "PCE", "PCE May-2026"),
    ("2026-07-31", "PCE", "PCE Jun-2026"),
    ("2026-08-28", "PCE", "PCE Jul-2026"),
    ("2026-09-25", "PCE", "PCE Aug-2026"),
    ("2026-10-30", "PCE", "PCE Sep-2026"),
    ("2026-11-25", "PCE", "PCE Oct-2026"),
    ("2026-12-23", "PCE", "PCE Nov-2026"),
]


def _as_df() -> pd.DataFrame:
    return pd.DataFrame(MACRO_EVENTS, columns=["date", "event_type", "label"]) \
        .assign(date=lambda d: pd.to_datetime(d["date"])) \
        .sort_values("date").reset_index(drop=True)


def upcoming_macro_events(
    reference_date: Optional[pd.Timestamp] = None,
    days_ahead: int = 14,
) -> pd.DataFrame:
    """
    Returns all macro events between reference_date and reference_date+days_ahead.
    """
    ref = pd.Timestamp(reference_date or pd.Timestamp.today()).normalize()
    cutoff = ref + pd.Timedelta(days=days_ahead)
    df = _as_df()
    return df[(df["date"] >= ref) & (df["date"] <= cutoff)].reset_index(drop=True)


def next_macro_event(
    reference_date: Optional[pd.Timestamp] = None,
) -> Optional[dict]:
    """
    Returns the next macro event as a dict {date, event_type, label, days_ahead}.
    None if no event in the hard-coded calendar after reference_date.
    """
    ref = pd.Timestamp(reference_date or pd.Timestamp.today()).normalize()
    df = _as_df()
    future = df[df["date"] >= ref]
    if future.empty:
        return None
    row = future.iloc[0]
    return {
        "date": row["date"],
        "event_type": row["event_type"],
        "label": row["label"],
        "days_ahead": int((row["date"] - ref).days),
    }
