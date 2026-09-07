import copy

from intel.alerts.dedup import AlertDeduper
from intel.alerts.rules import AlertCandidate, evaluate_alerts
from intel.db.connection import Database
from intel.scoring.hard_filters import apply_hard_filters
from intel.scoring.scores import compute_scores
from intel.scoring.states import decide_state
from intel.settings import DEFAULT_CONFIG

HF = DEFAULT_CONFIG["hard_filters"]
SC = DEFAULT_CONFIG["scoring"]
ST = DEFAULT_CONFIG["states"]
AL = DEFAULT_CONFIG["alerts"]


def base_metrics(**over):
    m = {
        "token": "0x" + "ab" * 20, "as_of_ts": 2_000_000, "token_age_seconds": 3 * 86400,
        "price_usd": 0.003, "market_cap": 3_000_000.0, "liquidity_usd": 300_000.0, "volume_24h": 800_000.0,
        "returns": {"return_1h": 0.02, "return_6h": 0.05, "return_24h": 0.10},
        "launch": {"fmm_reached": True, "fmm_price_usd": 0.001},
        "asymmetry": {"x_from_first_meaningful_market": 3.0, "drawdown_from_ath": 0.2},
        "holders": {"holder_count": 5000, "holder_growth_rate_1h": 0.01, "holder_growth_rate_6h": 0.03, "holder_growth_rate_24h": 0.08, "holder_growth_acceleration": 0.2, "divergences": []},
        "concentration": {"top10_pct": 0.20, "top20_pct": 0.28, "hhi": 0.02, "n_holders_economic": 4800, "top20_pct_change_24h": 0.0, "top20_pct_change_1h": 0.0},
        "clusters": {"effective_top10_pct": 0.21, "largest_cluster_pct": 0.03},
        "whales": {"whale_netflow_1h": 1000.0, "whale_netflow_6h": 5000.0, "whale_netflow_24h": 20000.0, "number_accumulating": 4, "number_distributing": 1},
        "top_wallet_distribution": [],
        "trading_quality": {"1h": {"unique_buyers": 40, "organic_volume_score": 80}, "24h": {"unique_buyers": 900, "new_buyers": 500, "organic_volume_score": 80, "organic_explain": []}},
        "organic_volume_score": 80,
        "liquidity": {"liquidity_to_mc": 0.10, "liquidity_change_1h": 0.0, "liquidity_change_24h": 0.05, "large_lp_removal": False, "single_pool_dependency": False},
        "price_impact": {"buy_1000": 0.01},
        "security": {"overall": "WARN", "fails": [], "warns": ["owner_admin"], "unknowns": [], "checks": {"source_verified": {"status": "PASS"}, "lp_control": {"status": "PASS"}, "honeypot_indicators": {"status": "PASS"}, "transfer_simulation": {"status": "PASS"}, "mint_capability": {"status": "PASS"}, "blacklist": {"status": "PASS"}}},
        "narrative": {"score": 60}, "smart_money": {"smart_money_score": None, "smart_money_status": "UNKNOWN"},
        "quality_flags": [],
    }
    for k, v in over.items():
        cur = m
        parts = k.split(".")
        for p in parts[:-1]:
            cur = cur[p]
        cur[parts[-1]] = v
    return m


def test_hard_filters_pass_and_reject_rules():
    ok = apply_hard_filters(base_metrics(), HF)
    assert ok.passed and not ok.reasons
    low = apply_hard_filters(base_metrics(liquidity_usd=10_000.0), HF)
    assert not low.passed and any("liquidité" in r for r in low.reasons)
    conc = apply_hard_filters(base_metrics(**{"clusters.effective_top10_pct": 0.55}), HF)
    assert not conc.passed and "wallets liés" in conc.reasons[0]
    hp = apply_hard_filters(base_metrics(**{"security.checks.honeypot_indicators": {"status": "FAIL"}, "security.fails": ["honeypot_indicators"]}), HF)
    assert not hp.passed and hp.security_reject
    unknown = apply_hard_filters(base_metrics(security=None), HF)
    assert not unknown.passed and "security_unknown" in unknown.unknowns and not unknown.reasons
    young = apply_hard_filters(base_metrics(**{"liquidity.liquidity_to_mc": 0.01}, token_age_seconds=3600), HF)
    assert young.passed and young.warnings  # young token: warning, not reject
    old = apply_hard_filters(base_metrics(**{"liquidity.liquidity_to_mc": 0.01}), HF)
    assert not old.passed
    warn_x = apply_hard_filters(base_metrics(**{"asymmetry.x_from_first_meaningful_market": 80.0}), HF)
    assert warn_x.passed and any("pénalisé" in w for w in warn_x.warnings)


def test_scores_respond_to_inputs_and_weights():
    m = base_metrics()
    hf = apply_hard_filters(m, HF)
    s = compute_scores(m, SC, hf)
    assert 0 <= s.moonshot <= 100 and s.smart_money is None and s.organic_volume == 80
    worse = compute_scores(base_metrics(**{"concentration.top10_pct": 0.45}), SC, hf)
    assert worse.distribution < s.distribution
    extended = compute_scores(base_metrics(**{"asymmetry.x_from_first_meaningful_market": 60.0}), SC, hf)
    assert extended.asymmetry < s.asymmetry - 30
    sec_fail = base_metrics(**{"security.fails": ["mint_capability"], "security.checks.mint_capability": {"status": "FAIL"}})
    hf2 = apply_hard_filters(sec_fail, HF)
    s2 = compute_scores(sec_fail, SC, hf2)
    assert s2.survival <= 10 and s2.narrative == 0 and s2.rug_risk >= 90  # narrative can't override security
    # weights configurable: all weight on asymmetry -> moonshot == asymmetry
    cfg = copy.deepcopy(SC)
    cfg["weights"] = {"asymmetry": 1.0, "traction": 0, "survival": 0, "distribution": 0, "narrative": 0}
    s3 = compute_scores(m, cfg, hf)
    assert abs(s3.moonshot - s3.asymmetry) < 1e-9


def test_distribution_uses_explorer_holder_count_when_only_top_page_known():
    m = base_metrics(**{"concentration.n_holders_economic": 48, "concentration.quality_flags": ["topn_only"], "holders.holder_count": 6004})
    hf = apply_hard_filters(m, HF)
    s = compute_scores(m, SC, hf)
    assert not any("holders (-" in w for w in s.explain["distribution"])
    m2 = base_metrics(**{"concentration.n_holders_economic": 48, "concentration.quality_flags": []})
    s2 = compute_scores(m2, SC, apply_hard_filters(m2, HF))
    assert any("48 holders (-20)" in w for w in s2.explain["distribution"])


def _decide(m, prev=None, since=None, portfolio=True):
    hf = apply_hard_filters(m, HF)
    s = compute_scores(m, SC, hf)
    return decide_state(m, s, hf, ST, prev_state=prev, prev_since_ts=since, is_portfolio=portfolio, moonshot_threshold=70), s, hf


def test_state_engine_transitions():
    d, _, _ = _decide(base_metrics())
    assert d.state == "ACCUMULATION" and d.action == "HOLD"
    d, _, _ = _decide(base_metrics(**{"whales.whale_netflow_24h": -50000.0, "concentration.top20_pct_change_24h": 0.05}))
    assert d.state == "DISTRIBUTION" and d.action == "DO_NOT_ADD"
    d, _, _ = _decide(base_metrics(**{"liquidity.liquidity_change_24h": -0.6}))
    assert d.state == "THESIS_BREAK" and d.action == "REVIEW_EXIT"
    d, _, _ = _decide(base_metrics(**{"security.fails": ["honeypot_indicators"], "security.checks.honeypot_indicators": {"status": "FAIL"}}))
    assert d.state == "SECURITY_RISK" and d.action == "REVIEW_EXIT"
    d, _, _ = _decide(base_metrics(**{"asymmetry.x_from_first_meaningful_market": 25.0}))
    assert d.state == "EXTENDED"
    d, _, _ = _decide(base_metrics(**{"returns.return_1h": 0.25, "holders.holder_growth_rate_24h": 0.0}))
    assert d.state == "BREAKOUT"
    d2, _, _ = _decide(base_metrics(**{"returns.return_1h": 0.0, "holders.holder_growth_rate_24h": 0.0}), prev="BREAKOUT", since=2_000_000 - 7 * 3600)
    assert d2.state == "BREAKOUT_CONFIRMED"
    d3, _, _ = _decide(base_metrics(liquidity_usd=1000.0), portfolio=False)
    assert d3.state == "REJECTED" and d3.action == "REJECT"
    d4, _, _ = _decide(base_metrics(security=None), portfolio=False)
    assert d4.state == "DISCOVER"


def test_scanner_noise_control_keeps_low_score_tokens_silent():
    m = base_metrics(**{"whales.whale_netflow_1h": 40000.0})
    d, s, hf = _decide(m, portfolio=False)
    # simulate a low-score scanner token: everything except candidate/security alerts must be INFO
    s.moonshot = 35.0
    cands = evaluate_alerts(token=m["token"], label="X", m=m, scores=s, decision=d, prev_state="DISCOVER", prev_moonshot=20.0, prev_hard_pass=False, hard_pass=hf.passed, is_portfolio=False, cfg=AL, moonshot_threshold=70)
    assert cands and all(c.severity == "INFO" for c in cands)
    # same token with a meaningful score (and liquidity above the scanner floor): the state
    # change becomes WATCH; "passed hard filters" only reaches WATCH from moonshot 70 (v0.2)
    s.moonshot = 62.0
    cands2 = evaluate_alerts(token=m["token"], label="X", m=m, scores=s, decision=d, prev_state="DISCOVER", prev_moonshot=None, prev_hard_pass=False, hard_pass=hf.passed, is_portfolio=False, cfg=AL, moonshot_threshold=70)
    kinds = {c.kind: c.severity for c in cands2}
    assert kinds["hard_filters_pass"] == "INFO" and kinds["state_change"] == "WATCH" and "whale_accumulation" in kinds
    s.moonshot = 72.0
    cands3 = evaluate_alerts(token=m["token"], label="X", m=m, scores=s, decision=d, prev_state="DISCOVER", prev_moonshot=None, prev_hard_pass=False, hard_pass=hf.passed, is_portfolio=False, cfg=AL, moonshot_threshold=70)
    assert {c.kind: c.severity for c in cands3}["hard_filters_pass"] == "WATCH"
    # below the liquidity floor (30k) nothing but security/thesis alerts may leave INFO
    thin = base_metrics(liquidity_usd=25_000.0, **{"whales.whale_netflow_1h": 40000.0})
    d2, s2, hf2 = _decide(thin, portfolio=False)
    s2.moonshot = 80.0
    cands4 = evaluate_alerts(token=thin["token"], label="X", m=thin, scores=s2, decision=d2, prev_state="DISCOVER", prev_moonshot=None, prev_hard_pass=False, hard_pass=hf2.passed, is_portfolio=False, cfg=AL, moonshot_threshold=70)
    assert cands4 and all(c.severity == "INFO" for c in cands4)


def test_candidate_gate_rejects_thin_young_chased_tokens():
    from intel.scoring.states import candidate_eligible

    ok, why = candidate_eligible(base_metrics(), ST)
    assert ok, why
    assert not candidate_eligible(base_metrics(liquidity_usd=25_000.0), ST)[0]  # below the 30k floor
    assert candidate_eligible(base_metrics(liquidity_usd=40_000.0), ST)[0]      # 2026-09-03: 40k is tradeable for a 20 € line
    assert not candidate_eligible(base_metrics(token_age_seconds=3 * 3600), ST)[0]
    assert not candidate_eligible(base_metrics(**{"returns.return_1h": 0.8}), ST)[0]
    assert not candidate_eligible(base_metrics(**{"trading_quality.24h.buy_sell_ratio": 3.5}), ST)[0]
    assert not candidate_eligible(base_metrics(**{"holders.holder_growth_rate_24h": None}), ST)[0]
    # a BREAKOUT on a thin, brand-new token is WATCH, never CANDIDATE
    # 25k: above the hard-filter floor (20k) but below the candidate floor (30k)
    d, _, _ = _decide(base_metrics(liquidity_usd=25_000.0, token_age_seconds=2 * 3600, **{"returns.return_1h": 0.64, "holders.holder_growth_rate_24h": 0.0}), portfolio=False)
    assert d.state == "BREAKOUT" and d.action == "WATCH" and "pas candidat" in d.reason


def test_alert_rules_and_dedup(tmp_path):
    m = base_metrics(**{"liquidity.liquidity_change_1h": -0.2, "whales.whale_netflow_1h": 40000.0})
    d, s, hf = _decide(m, prev="ACCUMULATION")
    cands = evaluate_alerts(token=m["token"], label="TEST", m=m, scores=s, decision=d, prev_state="WATCH", prev_moonshot=s.moonshot - 15, prev_hard_pass=True, hard_pass=hf.passed, is_portfolio=True, cfg=AL, moonshot_threshold=70)
    kinds = {c.kind for c in cands}
    assert {"state_change", "lp_drop", "whale_accumulation", "score_change"} <= kinds
    lp = next(c for c in cands if c.kind == "lp_drop")
    assert lp.severity == "IMPORTANT" and lp.action == "REVIEW_EXIT" and "1 h" in lp.why
    db = Database(":memory:")
    dd = AlertDeduper(db, AL, 4663)
    send, supp = dd.select(cands, ts=1000)
    assert len(send) == len(cands)
    for c in send:
        dd.record(c, sent=True, suppressed_reason=None, ts=1000)
    send2, supp2 = dd.select(cands, ts=1000 + 60)
    assert send2 == [] and all("cooldown" in r for _, r in supp2)
    # escalation bypasses the cooldown
    esc = AlertCandidate("lp_drop", "CRITICAL", "t", "why", "REVIEW_EXIT", lp.dedup_key, m["token"], "TEST")
    send3, _ = dd.select([esc], ts=1000 + 60)
    assert send3 == [esc]
    # after cooldown expiry it can be sent again
    send4, _ = dd.select([lp], ts=1000 + AL["cooldown_seconds"]["IMPORTANT"] + 1)
    assert send4 == [lp]
    # INFO below min severity is suppressed
    info = AlertCandidate("state_change", "INFO", "t", "why", "WATCH", "state:x:WATCH", m["token"], "TEST")
    send5, supp5 = dd.select([info], ts=5000)
    assert send5 == [] and "min severity" in supp5[0][1]
