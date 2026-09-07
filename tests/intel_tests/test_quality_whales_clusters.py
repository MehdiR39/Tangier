from intel.metrics.clustering import Edge, build_clusters, edges_from_funding, edges_from_synchrony, edges_from_transfers, effective_concentration
from intel.metrics.trading_quality import organic_volume_score, trading_quality
from intel.metrics.whales import define_whales


def _t(trader, side, usd, block, ts, tx="0x1"):
    return {"trader": trader, "side": side, "usd_value": usd, "block_number": block, "ts": ts, "tx_hash": tx}


def test_trading_quality_organic_looks_organic():
    trades = [_t(f"w{i}", "BUY", 50 + i * 7.3, 100 + i, 1000 + i * 30, f"0x{i}") for i in range(40)]
    trades += [_t(f"w{i}", "SELL", 30 + i * 5.1, 300 + i, 3000 + i * 30, f"0xs{i}") for i in range(5)]
    q = trading_quality(trades, first_trade_ts={f"w{i}": 1000 + i * 30 for i in range(40)}, window_start=0)
    assert q["unique_buyers"] == 40 and q["buy_count"] == 40 and q["sell_count"] == 5
    assert q["new_buyers"] == 40 and q["repeat_buyers"] == 0
    assert q["organic_volume_score"] >= 85, q["organic_explain"]


def test_trading_quality_flags_churn_and_roundtrips():
    trades = []
    for i in range(30):
        trades.append(_t("bot", "BUY", 100.0, 100 + i, 1000 + i, f"0xb{i}"))
        trades.append(_t("bot", "SELL", 100.0, 100 + i, 1000 + i, f"0xs{i}"))
    q = trading_quality(trades)
    assert q["unique_traders"] == 1
    assert q["round_trip_ratio"] is not None and q["round_trip_ratio"] > 0.9
    assert q["repetitive_size_share"] == 1.0
    assert q["top1_wallet_volume_share"] == 1.0
    assert q["organic_volume_score"] < 25, q["organic_explain"]
    assert any("round_trip" in w for w in q["organic_explain"])


def test_organic_score_none_without_trades():
    s, why = organic_volume_score({"unique_traders": 0}, {})
    assert s is None and why == ["no_trades"]


def test_define_whales_percentile_and_usd():
    holders = [(f"h{i}", (100 - i) * 10 ** 18, False) for i in range(100)] + [("lp", 10 ** 24, True)]
    supply = sum(b for _a, b, ex in holders if not ex)
    whales = define_whales(holders, supply, price_usd=100.0, decimals=18, params={"min_position_usd": 5000, "min_supply_pct": 0.5, "ownership_percentile": 0.95, "max_tracked": 50})
    # top 5% by rank = 5 wallets, all worth >= $5000
    assert [a for a, _ in whales] == ["h0", "h1", "h2", "h3", "h4"]
    none = define_whales(holders, supply, price_usd=0.01, decimals=18, params={"min_position_usd": 5000, "min_supply_pct": 0.5, "ownership_percentile": 0.95})
    assert none == []


def test_clusters_confidence_and_effective_concentration():
    cand = {"a", "b", "c", "d"}
    edges = edges_from_transfers([("a", "b", 1), ("a", "b", 2), ("c", "hub", 1)], cand, lambda x: x == "hub", 0.35)
    edges += edges_from_funding({"a": "f1", "b": "f1", "c": "f2", "d": "exchange"}, cand, lambda x: x == "exchange", 0.45)
    trades = [_t("c", "BUY", 10, 1, 100, "0x1"), _t("d", "BUY", 10, 1, 110, "0x2"), _t("c", "BUY", 10, 2, 200, "0x3"), _t("d", "BUY", 10, 2, 220, "0x4"), _t("c", "BUY", 10, 3, 300, "0x5"), _t("d", "BUY", 10, 3, 330, "0x6")]
    edges += edges_from_synchrony(trades, cand, 60, 3, 0.25)
    clusters = build_clusters(edges)
    by = {tuple(c.members): c for c in clusters}
    ab = by[("a", "b")]
    assert 0.6 < ab.confidence < 0.8  # direct transfer + same funding
    assert "direct_transfer" in ab.evidence["edge_kinds"] and "same_funding_source" in ab.evidence["edge_kinds"]
    cd = by[("c", "d")]
    assert cd.confidence < 0.4  # synchrony alone is weak
    holders = [("a", 300, False), ("b", 300, False), ("c", 100, False), ("d", 100, False), ("e", 200, False)]
    eff = effective_concentration(holders, 1000, clusters, min_confidence=0.6)
    assert eff["n_effective_actors"] == 4  # a+b merged
    assert abs(eff["largest_cluster_pct"] - 0.6) < 1e-9
    assert eff["n_high_confidence_clusters"] == 1


def test_funding_hub_ignored():
    cand = {f"w{i}" for i in range(40)}
    edges = edges_from_funding({w: "cex" for w in cand}, cand, lambda x: False, 0.45)
    assert edges == []  # 40 wallets from one funder is a hub pattern, not evidence
