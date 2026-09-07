from intel.context import IntelContext
from intel.db.connection import Database
from intel.engines.decisions import book_summary, evaluate_decisions, format_decision, open_position
from intel.providers.base import ProviderStatusRegistry
from intel.scoring.scores import Scores
from intel.scoring.states import StateDecision
from intel.settings import IntelConfig, Settings

TOK = "0x" + "ab" * 20


def _ctx() -> IntelContext:
    ctx = IntelContext.__new__(IntelContext)
    ctx.settings = Settings.load(db_path=":memory:", telegram_dry_run=True)
    ctx.config = IntelConfig()
    ctx.db = Database(":memory:")
    ctx.status = ProviderStatusRegistry(ctx.db)
    ctx.rpc = ctx.blockscout = ctx.dex = None  # type: ignore[assignment]
    return ctx


def _m(price, **over):
    m = {"price_usd": price, "market_cap": 1_000_000.0, "liquidity_usd": 250_000.0, "liquidity": {"liquidity_change_24h": 0.0}, "holders": {"holder_count": 800}, "returns": {"return_24h": 0.1}, "security": {"overall": "WARN", "fails": []}}
    m.update(over)
    return m


def _scores(moon):
    return Scores(70, 70, 70, 70, 80, None, 20, 50, moon, {})


def test_buy_then_moonbag_then_wide_trailing_stop():
    ctx = _ctx()
    d = StateDecision("ACCUMULATION", "CANDIDATE", "holders +12 % sur 24 h")
    out = evaluate_decisions(ctx, token=TOK, label="GEM", m=_m(1.0), scores=_scores(75), decision=d, is_portfolio=False)
    assert [x["kind"] for x in out] == ["BUY"] and out[0]["size_eur"] == 20.0
    txt = format_decision(out[0])
    assert "ACHÈTE GEM — 20 €" in txt and "Plan de sortie" in txt
    # no double buy while open
    assert evaluate_decisions(ctx, token=TOK, label="GEM", m=_m(1.1), scores=_scores(75), decision=d, is_portfolio=False) == []
    # reaching the target sells EVERYTHING, not half. Measured 2026-09-04 on 381 tokens: keeping
    # half turns a mean of +4.2 % into -39.5 %, because 91 % stop trading right after the move.
    out2 = evaluate_decisions(ctx, token=TOK, label="GEM", m=_m(1.6), scores=_scores(75), decision=StateDecision("WATCH", "WATCH", "rien"), is_portfolio=False)
    assert [x["kind"] for x in out2] == ["SELL_ALL"]
    assert open_position(ctx, TOK) is None, "nothing is left running"
    pos = ctx.db.query_one("SELECT * FROM positions WHERE token_address=?", (TOK,))
    # 20 EUR entered at 1.0 and exited at 1.6 books a 12 EUR gain, the whole line realised
    assert pos["status"] == "CLOSED" and abs(pos["realized_eur"] - 12.0) < 0.01
    txt2 = format_decision(out2[0])
    assert "VENDS TOUT GEM" in txt2
    # cooldown: no immediate re-buy
    assert evaluate_decisions(ctx, token=TOK, label="GEM", m=_m(2.0), scores=_scores(80), decision=d, is_portfolio=False) == []


def test_no_buy_when_not_candidate_or_low_score_or_security_fail():
    ctx = _ctx()
    d_watch = StateDecision("ACCUMULATION", "WATCH", "x")
    assert evaluate_decisions(ctx, token=TOK, label="A", m=_m(1.0), scores=_scores(80), decision=d_watch, is_portfolio=False) == []
    d_cand = StateDecision("ACCUMULATION", "CANDIDATE", "x")
    assert evaluate_decisions(ctx, token=TOK, label="A", m=_m(1.0), scores=_scores(60), decision=d_cand, is_portfolio=False) == []
    assert evaluate_decisions(ctx, token=TOK, label="A", m=_m(1.0, security={"overall": "FAIL", "fails": ["mint"]}), scores=_scores(80), decision=d_cand, is_portfolio=False) == []
    assert evaluate_decisions(ctx, token=TOK, label="A", m=_m(1.0), scores=_scores(80), decision=StateDecision("EXTENDED", "CANDIDATE", "x"), is_portfolio=False) == []


def test_sell_all_is_never_repeated_every_cycle_for_a_portfolio_token():
    """Regression: 2026-09-03 night, 'VENDS TOUT TAIWAN' was sent ~150 times."""
    ctx = _ctx()
    tb = StateDecision("THESIS_BREAK", "REVIEW_EXIT", "75 % sous le sommet et les holders diminuent")
    first = evaluate_decisions(ctx, token=TOK, label="TAIWAN", m=_m(0.0004), scores=_scores(40), decision=tb, is_portfolio=True)
    assert [x["kind"] for x in first] == ["SELL_ALL"]
    for _ in range(50):  # subsequent cycles with the same state: silence
        assert evaluate_decisions(ctx, token=TOK, label="TAIWAN", m=_m(0.00041), scores=_scores(40), decision=tb, is_portfolio=True) == []
    assert ctx.db.scalar("SELECT COUNT(*) FROM decisions WHERE kind='SELL_ALL'") == 1
    assert ctx.db.scalar("SELECT COUNT(*) FROM positions") == 1  # no re-opened position while the state is negative
    # back to a healthy state but inside the cooldown: still no new position
    assert evaluate_decisions(ctx, token=TOK, label="TAIWAN", m=_m(0.0005), scores=_scores(60), decision=StateDecision("WATCH", "HOLD", "ok"), is_portfolio=True) == []
    assert ctx.db.scalar("SELECT COUNT(*) FROM positions") == 1


def test_thesis_break_on_pre_tracking_ath_does_not_sell():
    """Regression (TAIWAN): the ATH was the launch spike, days before the position existed."""
    ctx = _ctx()
    ok = StateDecision("WATCH", "HOLD", "rien")
    evaluate_decisions(ctx, token=TOK, label="TAIWAN", m=_m(0.0004, ath={"ath_price": 0.0014, "ath_ts": 100}), scores=_scores(60), decision=ok, is_portfolio=True)
    tb = StateDecision("THESIS_BREAK", "REVIEW_EXIT", "75 % sous le sommet et les holders diminuent", ["drawdown_ath"])
    assert evaluate_decisions(ctx, token=TOK, label="TAIWAN", m=_m(0.0004, ath={"ath_price": 0.0014, "ath_ts": 100}), scores=_scores(40), decision=tb, is_portfolio=True) == []
    # but a genuine liquidity/holder break still sells
    tb2 = StateDecision("THESIS_BREAK", "REVIEW_EXIT", "liquidité -60 % sur 24 h", ["liquidity_24h"])
    assert [x["kind"] for x in evaluate_decisions(ctx, token=TOK, label="TAIWAN", m=_m(0.0004), scores=_scores(40), decision=tb2, is_portfolio=True)] == ["SELL_ALL"]
    # and a -70% fall from the peak reached since we follow it sells too
    tok2 = "0x" + "ee" * 20
    evaluate_decisions(ctx, token=tok2, label="Y", m=_m(1.0), scores=_scores(60), decision=ok, is_portfolio=True)
    # stays under the take-profit multiple, so the position is still open when it collapses
    evaluate_decisions(ctx, token=tok2, label="Y", m=_m(1.4), scores=_scores(60), decision=ok, is_portfolio=True)
    out = evaluate_decisions(ctx, token=tok2, label="Y", m=_m(0.4), scores=_scores(60), decision=ok, is_portfolio=True)
    assert [x["kind"] for x in out] == ["SELL_ALL"] and "depuis son plus haut sous suivi" in out[0]["reason"]


def test_portfolio_position_sell_rules_and_book():
    ctx = _ctx()
    # user-held token: first observed price becomes the reference entry
    out = evaluate_decisions(ctx, token=TOK, label="PAIR", m=_m(0.004), scores=_scores(65), decision=StateDecision("WATCH", "HOLD", "rien"), is_portfolio=True)
    assert out == [] and open_position(ctx, TOK)["kind"] == "PORTFOLIO"
    # distribution -> sell half
    out = evaluate_decisions(ctx, token=TOK, label="PAIR", m=_m(0.0041), scores=_scores(60), decision=StateDecision("DISTRIBUTION", "DO_NOT_ADD", "9 gros porteurs vendent contre 2"), is_portfolio=True)
    assert [x["kind"] for x in out] == ["SELL_HALF"] and "VENDS LA MOITIÉ de PAIR" in format_decision(out[0])
    # thesis break -> sell all
    out = evaluate_decisions(ctx, token=TOK, label="PAIR", m=_m(0.003), scores=_scores(40), decision=StateDecision("THESIS_BREAK", "REVIEW_EXIT", "liquidité -60 % sur 24 h"), is_portfolio=True)
    assert [x["kind"] for x in out] == ["SELL_ALL"]
    book = book_summary(ctx)
    assert book["n_open"] == 0 and book["positions"][0]["status"] == "CLOSED"
    # after an exit the token is not re-opened during the cooldown, even in a healthy state
    out = evaluate_decisions(ctx, token=TOK, label="PAIR", m=_m(0.003), scores=_scores(60), decision=StateDecision("WATCH", "HOLD", "rien"), is_portfolio=True)
    assert out == [] and ctx.db.scalar("SELECT COUNT(*) FROM positions") == 1
    # liquidity-drop sell on a fresh token
    tok2 = "0x" + "cd" * 20
    evaluate_decisions(ctx, token=tok2, label="Z", m=_m(0.003), scores=_scores(60), decision=StateDecision("WATCH", "HOLD", "rien"), is_portfolio=True)
    out = evaluate_decisions(ctx, token=tok2, label="Z", m=_m(0.003, liquidity={"liquidity_change_24h": -0.55}), scores=_scores(60), decision=StateDecision("WATCH", "HOLD", "rien"), is_portfolio=True)
    assert [x["kind"] for x in out] == ["SELL_ALL"] and "liquidité a perdu 55 %" in out[0]["reason"]


def test_the_buy_message_states_the_rules_actually_in_force():
    """A message must never promise an exit the engine no longer makes."""
    from intel.engines.decisions import format_decision

    d = {"kind": "BUY", "label": "TOK", "size_eur": 20.0, "price": 0.001, "reason": "test",
         "metrics": {}, "plan": {"take_profit": 1.5, "timeout_h": 3.0, "sells_all": True}}
    body = format_decision(d)
    assert "x1.5" in body and "3 h" in body and "TOUT" in body
    assert "x3" not in body and "18 h" not in body


def test_the_message_falls_back_to_the_current_defaults():
    from intel.engines.decisions import format_decision

    body = format_decision({"kind": "BUY", "label": "TOK", "size_eur": 20.0, "price": 0.001,
                            "reason": "test", "metrics": {}})
    assert "x1.5" in body and "3 h" in body
