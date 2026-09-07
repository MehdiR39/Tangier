from intel.backtest.scorecard import alert_outcomes, format_scorecard, summarize_by_kind
from intel.context import IntelContext
from intel.db.connection import Database
from intel.providers.base import ProviderStatusRegistry
from intel.settings import IntelConfig, Settings
from intel.utils.timeutil import now_ts

TOK = "0x" + "ab" * 20


def _ctx() -> IntelContext:
    ctx = IntelContext.__new__(IntelContext)
    ctx.settings = Settings.load(db_path=":memory:", telegram_dry_run=True)
    ctx.config = IntelConfig()
    ctx.db = Database(":memory:")
    ctx.status = ProviderStatusRegistry(ctx.db)
    ctx.rpc = ctx.blockscout = ctx.dex = None  # type: ignore[assignment]
    return ctx


def _snap(ctx, ts, price):
    ctx.db.insert("token_snapshots", {"ts": ts, "chain_id": ctx.chain_id, "token_address": TOK, "source": "dexscreener", "price_usd": price})


def test_alert_outcomes_and_scorecard():
    ctx = _ctx()
    now = now_ts()
    t0 = now - 30 * 3600
    ctx.db.insert("tokens", {"chain_id": ctx.chain_id, "address": TOK, "symbol": "XYZ", "first_seen_ts": t0, "updated_ts": t0})
    _snap(ctx, t0 - 60, 1.0)          # price at alert
    _snap(ctx, t0 + 3600, 1.2)        # +20% at 1h
    _snap(ctx, t0 + 6 * 3600, 0.9)    # -10% at 6h
    _snap(ctx, t0 + 24 * 3600, 0.5)   # -50% at 24h
    _snap(ctx, now - 600, 0.4)        # now
    ctx.db.insert("alerts", {"ts": t0, "chain_id": ctx.chain_id, "token_address": TOK, "severity": "WATCH", "kind": "state_change", "dedup_key": "k", "title": "XYZ — EXTENDED", "body": "", "action": "DO_NOT_ADD", "sent": 1})
    ctx.db.insert("alerts", {"ts": now - 600, "chain_id": ctx.chain_id, "token_address": TOK, "severity": "WATCH", "kind": "whale_accumulation", "dedup_key": "k2", "title": "x", "body": "", "action": "WATCH", "sent": 1})
    out = alert_outcomes(ctx, since_ts=now - 3 * 86400)
    assert len(out) == 2
    old, recent = out[0], out[1]
    assert abs(old["ret_1h"] - 0.2) < 1e-9 and abs(old["ret_6h"] + 0.1) < 1e-9 and abs(old["ret_24h"] + 0.5) < 1e-9 and abs(old["ret_now"] + 0.6) < 1e-9
    assert recent["ret_1h"] is None and recent["ret_24h"] is None  # horizon not reached yet
    s = summarize_by_kind(out, "24h")
    assert s["state_change/DO_NOT_ADD"]["n"] == 1 and s["state_change/DO_NOT_ADD"]["hit_up"] == 0.0
    lines = format_scorecard(out, "24h")
    assert any("state_change/DO_NOT_ADD" in l and "-50%" in l for l in lines)
    assert any("XYZ" in l for l in lines)
    assert format_scorecard([recent], "24h")[0].startswith("• 1 alerte")
