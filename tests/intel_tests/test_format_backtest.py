from intel.alerts.format import format_alert, strip_tags_for_test
from intel.alerts.rules import AlertCandidate
from intel.backtest.forward import spearman, summarize
from intel.scoring.scores import Scores
from intel.scoring.states import StateDecision


def test_format_alert_is_plain_french_with_why_action_and_meaning():
    m = {
        "token": "0x" + "ab" * 20, "price_usd": 0.0047, "market_cap": 842_000.0, "liquidity_usd": 261_000.0,
        "returns": {"return_1h": -0.062, "return_24h": -0.11},
        "liquidity": {"liquidity_change_1h": -0.021, "liquidity_to_mc": 0.31},
        "holders": {"holder_count": 1411, "holder_growth_rate_6h": 0.048, "holder_growth_rate_24h": 0.091},
        "concentration": {"top20_pct": 0.258, "top20_pct_change_24h": 0.044},
        "clusters": {"effective_top20_pct": 0.271},
        "whales": {"n_whales": 5, "whale_netflow_1h": -41200.0, "whale_netflow_24h": -120400.0, "number_accumulating": 1, "number_distributing": 4},
        "asymmetry": {"x_from_first_meaningful_market": 3.2, "drawdown_from_ath": 0.35},
        "organic_volume_score": 72.0, "smart_money": {"smart_money_score": None},
        "security": {"overall": "WARN", "fails": [], "warns": ["owner_admin"]},
        "quality_flags": [],
    }
    scores = Scores(62, 55, 70, 48, 72, None, 30, 60, 61, {"moonshot": ["asymmetry=0.30"]})
    dec = StateDecision("DISTRIBUTION", "DO_NOT_ADD", "3 gros porteurs vendent contre 1 qui achète")
    c = AlertCandidate("state_change", "IMPORTANT", "TAIWAN — DISTRIBUTION", dec.reason, dec.action, "state:x:DISTRIBUTION", m["token"], "TAIWAN")
    text = format_alert(c, m, scores, dec, prev_state="ACCUMULATION", prev_moonshot=74.0, token_url="https://dexscreener.com/robinhood/x", is_portfolio=True)
    plain = strip_tags_for_test(text)
    assert "⚠️ Important · TAIWAN — Les gros porteurs vendent" in plain
    assert "Ton token · Action : NE PAS RENFORCER" in plain
    assert "Pourquoi : 3 gros porteurs vendent contre 1 qui achète" in plain
    assert "Capitalisation : 842 k$ · Liquidité : 261 k$ (stable)" in plain
    assert "Holders : 1 411 (+9 % sur 24 h)" in plain
    assert "Gros porteurs (24 h) : -120 k$ net, 1 achètent / 4 vendent" in plain
    assert "Sécurité du contrat : avertissements" in plain
    assert "Ce que ça veut dire : Signal de prudence" in plain
    assert "score 74 → 61" in plain and "Accumulation en cours → Les gros porteurs vendent" in plain
    assert "x3.2 depuis le premier vrai marché" in plain and "35 % sous le sommet" in plain
    assert "MC:" not in plain and "WHY" not in plain  # no developer jargon left
    assert len(text) < 4096


def test_format_alert_scanner_token_and_missing_data():
    m = {"token": "0x" + "cd" * 20, "price_usd": None, "market_cap": None, "liquidity_usd": None, "returns": {}, "liquidity": {}, "holders": {}, "whales": {}, "asymmetry": {}, "security": None, "quality_flags": ["partial_transfer_history"]}
    scores = Scores(50, 50, 50, 50, None, None, 40, 50, 50, {})
    dec = StateDecision("WATCH", "WATCH", "score 50, pas de tendance nette")
    c = AlertCandidate("whale_accumulation", "WATCH", "X — WHALE", "les gros porteurs ont acheté net 30 000 $ en 1 h", "WATCH", "k", m["token"], "X")
    plain = strip_tags_for_test(format_alert(c, m, scores, dec, prev_state=None, prev_moonshot=None, is_portfolio=False))
    assert "Nouveau token (scanner) · Action : SURVEILLER" in plain
    assert "X — Les baleines achètent" in plain
    assert "Prix : ? (? sur 1 h, ? sur 24 h)" in plain and "Holders : ?" in plain
    assert "Sécurité du contrat : non vérifiée" in plain
    assert "historique encore incomplet" in plain


def test_spearman_and_summary():
    assert abs(spearman([(1, 1), (2, 2), (3, 3), (4, 4)]) - 1.0) < 1e-9
    assert abs(spearman([(1, 4), (2, 3), (3, 2), (4, 1)]) + 1.0) < 1e-9
    rows = []
    for i in range(20):
        rows.append({"moonshot": 30 + i * 3, "state": "WATCH" if i % 2 else "ACCUMULATION", "fwd_1h": 0.01 * i, "fwd_24h": 0.05 * i - 0.2, "mfe_24h": 0.1 * i, "mae_24h": -0.05,
                     "survived_7d": i > 5, "rugged_7d": i <= 5, "survival": 50, "traction": i, "asymmetry": 50, "distribution": 50, "organic_volume": 50, "rug_risk": 50, "narrative": 50})
    s = summarize(rows, ["1h", "24h"])
    assert s["n"] == 20 and set(s["by_state"]) == {"WATCH", "ACCUMULATION"}
    assert s["components_ic"]["moonshot"] == 1.0 and s["components_ic"]["traction"] == 1.0
    deciles = s["by_moonshot_decile"]
    assert any("survival_rate_7d" in v for v in deciles.values())
