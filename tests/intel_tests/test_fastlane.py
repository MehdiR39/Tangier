"""The fast lane: buy on the measured signal, but never with fewer safeguards.

It exists because the deep pass scores about 96 tokens an hour against a queue of 14 000, so a
token that becomes tradeable waits hours while its window closes. Speed is the point; laxity is
not, so every guard from the ordinary path is asserted here individually.
"""
import asyncio

import pytest

from intel.context import IntelContext
from intel.db.connection import Database
from intel.engines import fastlane
from intel.providers.base import ProviderStatusRegistry
from intel.settings import IntelConfig, Settings
from intel.utils.timeutil import now_ts

TOKEN = "0x" + "aa" * 20
USDG = "0x5fc5360d0400a0fd4f2af552add042d716f1d168"


class _Report:
    def __init__(self, fails=(), unknowns=(), checks=("source_verified",)):
        self.fails = [type("C", (), {"name": n})() for n in fails]
        self.unknowns = [type("C", (), {"name": n})() for n in unknowns]
        self.checks = [type("C", (), {"name": n})() for n in checks]


def _ctx(**over) -> IntelContext:
    ctx = IntelContext.__new__(IntelContext)
    ctx.settings = Settings.load(db_path=":memory:", telegram_dry_run=True)
    cfg = {"fastlane_enabled": True, "fastlane_min_volume_usd": 2000.0, "size_eur": 20.0,
           "max_open": 15, "fastlane_max_age_hours": 48, "fastlane_min_age_minutes": 10,
           "fastlane_max_unknown_checks": 2, "take_profit_multiple": 1.5, "timeout_hours": 3}
    cfg.update(over)
    ctx.config = IntelConfig({"decisions": cfg})
    ctx.db = Database(":memory:")
    ctx.status = ProviderStatusRegistry(ctx.db)
    ctx.rpc = ctx.blockscout = ctx.dex = None  # type: ignore[assignment]
    return ctx


def _pool(ctx, age_h=2.0):
    ctx.db.insert("pairs", {"chain_id": ctx.chain_id, "pair_id": "0x" + "cd" * 32, "token_address": TOKEN,
                            "quote_address": USDG, "currency0": TOKEN, "currency1": USDG, "fee": 3000,
                            "tick_spacing": 60, "hooks": "0x" + "00" * 20, "token_is_currency0": 1,
                            "created_block": 1, "created_ts": now_ts() - int(age_h * 3600),
                            "first_seen_ts": now_ts() - 7200, "updated_ts": now_ts(), "source": "test"})


def _patch(monkeypatch, report=None, pools=True):
    monkeypatch.setattr("intel.ingest.pools.load_pools", lambda ctx, t: ({"p": object()} if pools else {}))

    async def _sec(ctx, token, pools, **kw):
        return report if report is not None else _Report()

    monkeypatch.setattr("intel.ingest.security.run_security_checks", _sec)


def _consider(ctx, vol=5000.0, price=0.01):
    return asyncio.run(fastlane.consider(ctx, TOKEN, vol, price))


def test_a_clean_token_with_real_volume_is_bought(monkeypatch):
    ctx = _ctx()
    _pool(ctx)
    _patch(monkeypatch)
    rec = _consider(ctx)
    assert rec is not None and rec["kind"] == "BUY" and rec["size_eur"] == 20.0
    assert ctx.db.query_one("SELECT status, notes FROM positions WHERE token_address=?", (TOKEN,))["status"] == "OPEN"
    assert "voie rapide" in ctx.db.query_one("SELECT notes FROM positions WHERE token_address=?", (TOKEN,))["notes"]
    # the reason states the evidence it acted on, not a score it never computed
    assert "$ échangés dans l'heure" in rec["reason"]


def test_thin_volume_is_refused(monkeypatch):
    ctx = _ctx()
    _pool(ctx)
    _patch(monkeypatch)
    assert _consider(ctx, vol=1999.0) is None


def test_a_failing_contract_is_refused(monkeypatch):
    ctx = _ctx()
    _pool(ctx)
    _patch(monkeypatch, report=_Report(fails=("sell_simulation",)))
    assert _consider(ctx) is None


def test_a_contract_that_cannot_be_checked_is_refused(monkeypatch):
    """Unknown is never safe — that rule does not get relaxed because the lane is fast."""
    ctx = _ctx()
    _pool(ctx)
    _patch(monkeypatch, report=_Report(checks=()))
    assert _consider(ctx) is None


def test_too_many_unanswered_checks_is_refused(monkeypatch):
    ctx = _ctx()
    _pool(ctx)
    _patch(monkeypatch, report=_Report(unknowns=("a", "b", "c")))
    assert _consider(ctx) is None


def test_an_unknown_age_is_refused(monkeypatch):
    ctx = _ctx()          # no pool row at all
    _patch(monkeypatch)
    assert _consider(ctx) is None


def test_a_token_too_old_or_too_new_is_refused(monkeypatch):
    _patch(monkeypatch)
    old = _ctx(); _pool(old, age_h=72)
    assert _consider(old) is None
    fresh = _ctx(); _pool(fresh, age_h=0.05)      # 3 minutes
    assert _consider(fresh) is None


def test_no_second_position_on_the_same_token(monkeypatch):
    ctx = _ctx()
    _pool(ctx)
    _patch(monkeypatch)
    assert _consider(ctx) is not None
    assert _consider(ctx) is None


def test_the_open_position_ceiling_is_respected(monkeypatch):
    ctx = _ctx(max_open=2)
    _pool(ctx)
    _patch(monkeypatch)
    for i in range(2):
        ctx.db.insert("positions", {"chain_id": ctx.chain_id, "token_address": f"0x{i:040x}", "label": "x",
                                    "kind": "VIRTUAL", "opened_ts": now_ts(), "status": "OPEN", "size_eur": 20.0})
    assert _consider(ctx) is None


def test_a_token_played_recently_is_not_replayed(monkeypatch):
    ctx = _ctx(rebuy_cooldown_seconds=3600)
    _pool(ctx)
    _patch(monkeypatch)
    ctx.db.insert("positions", {"chain_id": ctx.chain_id, "token_address": TOKEN, "label": "x", "kind": "VIRTUAL",
                                "opened_ts": now_ts() - 1800, "closed_ts": now_ts() - 600, "status": "CLOSED",
                                "size_eur": 20.0, "entry_price": 1.0})
    assert _consider(ctx) is None


def test_the_lane_can_be_switched_off(monkeypatch):
    ctx = _ctx(fastlane_enabled=False)
    _pool(ctx)
    _patch(monkeypatch)
    assert _consider(ctx) is None


def test_a_missing_price_is_refused(monkeypatch):
    ctx = _ctx()
    _pool(ctx)
    _patch(monkeypatch)
    assert _consider(ctx, price=None) is None
    assert _consider(ctx, price=0.0) is None


def test_run_takes_the_busiest_first_and_stops_at_the_limit(monkeypatch):
    ctx = _ctx()
    _pool(ctx)
    _patch(monkeypatch)
    seen = []

    async def _fake(ctx_, token, vol, price):
        seen.append((token, vol))
        return None

    monkeypatch.setattr(fastlane, "consider", _fake)
    hot = {f"0x{i:040x}": float(i * 100) for i in range(1, 11)}
    out = asyncio.run(fastlane.run(ctx, hot, {}, limit=3))
    assert out["bought"] == 0 and len(seen) == 3
    assert [v for _t, v in seen] == [1000.0, 900.0, 800.0], "busiest first"
