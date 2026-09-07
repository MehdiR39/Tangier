import asyncio
import json

from intel.alerts.telegram import strip_html
from intel.context import IntelContext
from intel.db.connection import Database
from intel.engines.digest import build_digest, send_digest
from intel.providers.base import ProviderStatusRegistry
from intel.settings import IntelConfig, Settings
from intel.utils.timeutil import now_ts

TOKEN = "0xd18528b39da6464b3662c331a52181ecb15b1e18"


class FakeSender:
    def __init__(self):
        self.sent = []

    async def send(self, text):
        self.sent.append(text)
        return True, "42", None


def _ctx() -> IntelContext:
    ctx = IntelContext.__new__(IntelContext)
    ctx.settings = Settings.load(db_path=":memory:", telegram_dry_run=True)
    ctx.config = IntelConfig()
    ctx.db = Database(":memory:")
    ctx.status = ProviderStatusRegistry(ctx.db)
    ctx.rpc = ctx.blockscout = ctx.dex = None  # type: ignore[assignment]
    return ctx


def test_digest_is_plain_french_and_sent_once_per_day():
    ctx = _ctx()
    ts = now_ts()
    ctx.db.insert("portfolio_positions", {"chain_id": ctx.chain_id, "token_address": TOKEN, "label": "SAYLORMOON", "active": 1, "updated_ts": ts})
    ctx.db.insert("portfolio_positions", {"chain_id": ctx.chain_id, "token_address": "0x" + "bb" * 20, "label": "TAIWAN", "active": 1, "updated_ts": ts})
    ctx.db.insert("tokens", {"chain_id": ctx.chain_id, "address": TOKEN, "symbol": "SAYLORMOON", "first_seen_ts": ts, "updated_ts": ts})
    ctx.db.insert("token_states", {"chain_id": ctx.chain_id, "token_address": TOKEN, "state": "WATCH", "since_ts": ts, "last_eval_ts": ts, "moonshot": 67.0, "action": "HOLD", "reason": "score 67, pas de tendance nette"})
    metrics = {"market_cap": 3_500_000.0, "liquidity_usd": 746_000.0, "returns": {"return_24h": -0.086}, "holders": {"holder_count": 6004}, "security": {"overall": "WARN"}}
    ctx.db.insert("token_scores", {"ts": ts, "chain_id": ctx.chain_id, "token_address": TOKEN, "model_version": "t", "as_of_ts": ts, "moonshot": 67.0, "metrics_json": json.dumps(metrics)})
    ctx.db.insert("token_snapshots", {"ts": ts, "chain_id": ctx.chain_id, "token_address": TOKEN, "source": "dexscreener", "price_usd": 0.0035})
    ctx.db.insert("decisions", {"ts": ts - 3600, "chain_id": ctx.chain_id, "token_address": TOKEN, "label": "SAYLORMOON", "kind": "SELL_HALF", "reason": "x", "price": 0.0030, "sent": 1})
    text = build_digest(ctx)
    plain = strip_html(text)
    assert "Résumé du matin" in plain
    assert "SAYLORMOON — GARDER" in plain and "À surveiller" in plain
    assert "-9 % sur 24 h · capitalisation 3,50 M$ · liquidité 746 k$ · 6 004 holders · contrat avec avertissements" in plain
    assert "TAIWAN — première analyse en cours" in plain
    assert "VENDS LA MOITIÉ SAYLORMOON · depuis : +17 %" in plain
    assert "aucun achat conseillé pour l'instant" in plain
    assert "rien de convaincant pour l'instant" in plain
    assert "Pas de message dans la journée = rien à faire." in plain
    for jargon in ("WATCH →", "moonshot", "MC $", "LP $", "WARN", "0xd185"):
        assert jargon not in plain, jargon
    assert len(text) < 4096
    sender = FakeSender()
    ok, err = asyncio.run(send_digest(ctx, sender))
    assert ok and len(sender.sent) == 1
    ok2, err2 = asyncio.run(send_digest(ctx, sender))
    assert not ok2 and err2 == "already sent today" and len(sender.sent) == 1
    ok3, _ = asyncio.run(send_digest(ctx, sender, force=True))
    assert ok3 and len(sender.sent) == 2
    assert ctx.db.scalar("SELECT COUNT(*) FROM alerts WHERE kind='daily_digest' AND sent=1") == 2
