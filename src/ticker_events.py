"""
Per-ticker events lookup — earnings date + ex-dividend date.

Wrapper around yfinance for fetching a single-function view of the next
corporate events for a ticker. Used by the tiered signal filter.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)


def _fetch_one(symbol: str) -> dict:
    """
    Returns dict with optional keys:
      - next_earnings_date  (pd.Timestamp)
      - eps_estimate        (float, if available)
      - ex_dividend_date    (pd.Timestamp)
      - dividend_amount     (float, if available)
    """
    result = {}
    try:
        import yfinance as yf
        t = yf.Ticker(symbol)
        today = pd.Timestamp.today().normalize()

        # --- Earnings: check calendar first, then earnings_dates ---
        next_earn = None
        try:
            cal = t.calendar
            if cal:
                ed = cal.get("Earnings Date")
                if isinstance(ed, list) and ed:
                    ed_ts = pd.Timestamp(ed[0]).normalize()
                    if ed_ts >= today:
                        next_earn = ed_ts
                elif ed is not None:
                    ed_ts = pd.Timestamp(ed).normalize()
                    if ed_ts >= today:
                        next_earn = ed_ts
                if "Earnings Average" in (cal or {}):
                    result["eps_estimate"] = cal.get("Earnings Average")
        except Exception:
            pass

        if next_earn is None:
            try:
                ed = t.earnings_dates
                if ed is not None and not ed.empty:
                    future = [pd.Timestamp(x).normalize().tz_localize(None)
                              for x in ed.index if pd.notna(x)
                              and pd.Timestamp(x).normalize().tz_localize(None) >= today]
                    if future:
                        next_earn = min(future)
            except Exception:
                pass

        if next_earn is not None:
            result["next_earnings_date"] = next_earn

        # --- Ex-dividend date ---
        try:
            info = t.info or {}
            exdiv = info.get("exDividendDate")
            if exdiv:
                # Unix epoch seconds -> Timestamp
                try:
                    exdiv_ts = pd.to_datetime(exdiv, unit="s").normalize()
                except Exception:
                    exdiv_ts = pd.Timestamp(exdiv).normalize()
                if exdiv_ts >= today:
                    result["ex_dividend_date"] = exdiv_ts
            div_rate = info.get("dividendRate")
            if div_rate:
                result["dividend_amount"] = float(div_rate)
        except Exception:
            pass

    except Exception as e:
        logger.debug(f"{symbol}: events fetch failed — {e}")
    return result


def fetch_ticker_events(
    symbols: List[str],
    max_workers: int = 8,
) -> Dict[str, dict]:
    """
    Parallel fetch of per-ticker events. Returns {symbol: {next_earnings_date, ex_dividend_date, ...}}.
    """
    out: Dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futs = {pool.submit(_fetch_one, s): s for s in symbols}
        for fut in as_completed(futs):
            sym = futs[fut]
            try:
                out[sym] = fut.result()
            except Exception as e:
                logger.debug(f"{sym}: events worker failed — {e}")
                out[sym] = {}
    return out
