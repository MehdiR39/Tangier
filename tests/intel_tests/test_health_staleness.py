"""Each engine is judged against its own cadence, not one global threshold.

Regression 2026-09-04: the container reported unhealthy for hours because the 6-hourly backup
had not run in the last 15 minutes. A permanent false alarm hides real failures.
"""
from intel.context import IntelContext
from intel.db.connection import Database
from intel.health import HealthState
from intel.providers.base import ProviderStatusRegistry
from intel.settings import IntelConfig, Settings
from intel.utils.timeutil import now_ts


def _ctx() -> IntelContext:
    ctx = IntelContext.__new__(IntelContext)
    ctx.settings = Settings.load(db_path=":memory:", telegram_dry_run=True)
    ctx.config = IntelConfig()
    ctx.db = Database(":memory:")
    ctx.status = ProviderStatusRegistry(ctx.db)
    ctx.rpc = ctx.blockscout = ctx.dex = None  # type: ignore[assignment]
    return ctx


def test_a_slow_engine_is_not_stale_within_its_own_cadence():
    h = HealthState(_ctx())
    now = now_ts()
    h.runs["backup"] = {"ts": now - 3 * 3600, "ok": True, "seconds": 1.0, "error": None}      # every 6 h
    h.runs["retention"] = {"ts": now - 3 * 3600, "ok": True, "seconds": 1.0, "error": None}   # every 6 h
    h.runs["portfolio"] = {"ts": now - 30, "ok": True, "seconds": 1.0, "error": None}
    s = h.snapshot()
    assert s["stale_engines"] == [] and s["ok"] is True


def test_a_fast_engine_that_stops_is_still_caught():
    h = HealthState(_ctx())
    now = now_ts()
    h.runs["portfolio"] = {"ts": now - 3600, "ok": True, "seconds": 1.0, "error": None}  # 60 s cadence
    s = h.snapshot()
    assert "portfolio" in s["stale_engines"] and s["ok"] is False


def test_a_slow_engine_that_really_stops_is_caught_too():
    ctx = _ctx()
    h = HealthState(ctx)
    silent_for = h._expected_interval("backup") * 3 + 3600
    h.runs["backup"] = {"ts": now_ts() - silent_for, "ok": True, "seconds": 1.0, "error": None}
    assert "backup" in h.snapshot()["stale_engines"]
