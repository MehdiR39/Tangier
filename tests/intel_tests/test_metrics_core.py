from intel.metrics.concentration import concentration, gini, hhi
from intel.metrics.holders import divergences, holder_growth
from intel.metrics.launch import FMMParams, first_meaningful_market
from intel.metrics.market import asymmetry_multiples


def test_asymmetry_multiples_and_mc_required():
    m = asymmetry_multiples(price=0.004, market_cap=4_000_000, raw_first_price=0.00001, fmm_price=0.001, fmm_market_cap=1_000_000, ath_price=0.008)
    assert abs(m["x_from_raw_launch"] - 400) < 1e-9
    assert abs(m["x_from_first_meaningful_market"] - 4) < 1e-9
    assert abs(m["x_from_100k_mc"] - 40) < 1e-9 and abs(m["x_from_1m_mc"] - 4) < 1e-9
    assert abs(m["launch_to_ath_x"] - 800) < 1e-9 and abs(m["first_market_to_ath_x"] - 8) < 1e-9
    assert abs(m["drawdown_from_ath"] - 0.5) < 1e-9
    assert m["mc_required_x10"] == 40_000_000 and m["mc_required_x1000"] == 4_000_000_000
    m2 = asymmetry_multiples(None, None, None, None, None, None)
    assert all(v is None for v in m2.values())


def test_gini_hhi_and_concentration_exclusion():
    assert gini([1, 1, 1, 1]) == 0.0
    g = gini([0, 0, 0, 100])
    assert g is not None and g > 0.7
    assert abs(hhi([0.5, 0.5]) - 0.5) < 1e-12
    holders = [("lp", 500, True), ("a", 200, False), ("b", 100, False), ("c", 100, False), ("d", 100, False)]
    c = concentration(holders, total_supply=1000)
    # economic supply = 500 ; top1 = 200/500
    assert abs(c["top1_pct"] - 0.4) < 1e-9 and abs(c["top1_pct_total"] - 0.2) < 1e-9
    assert abs(c["top5_pct"] - 1.0) < 1e-9
    assert abs(c["excluded_supply_pct"] - 0.5) < 1e-9
    assert c["n_holders_economic"] == 4
    empty = concentration([("lp", 500, True)], total_supply=1000)
    assert empty["top10_pct"] is None and "no_economic_holders" in empty["quality_flags"]


def test_holder_growth_and_acceleration():
    base = 1_000_000
    series = [(base - 7200, 100, 90, "rpc_replay"), (base - 3600, 110, 100, "rpc_replay"), (base, 140, 130, "rpc_replay")]
    g = holder_growth(series, base, windows=["1h"], acceleration_window="1h")
    assert g["holder_count"] == 140
    assert g["net_holder_growth_1h"] == 30
    assert abs(g["holder_growth_rate_1h"] - 30 / 110) < 1e-9
    assert g["holder_growth_acceleration"] == (30 - 10) / 10
    stale = holder_growth(series, base + 10 * 3600, windows=["1h"])
    assert stale["holder_count"] is None and "holder_count_stale_or_missing" in stale["quality_flags"]


def test_divergences():
    assert "price_down_holders_up_6h" in divergences({"return_6h": -0.10}, {"holder_growth_rate_6h": 0.05})
    assert "price_up_holders_down_24h" in divergences({"return_24h": 0.30}, {"holder_growth_rate_24h": -0.05})
    assert divergences({"return_6h": None}, {"holder_growth_rate_6h": 0.5}) == []


def _trade(ts, trader, side, usd, price):
    return {"ts": ts, "trader": trader, "side": side, "usd_value": usd, "price_usd": price, "token_amount_float": usd / price, "price_native": None, "log_index": 0}


def test_first_meaningful_market_reached_after_persistence():
    params = FMMParams(bucket_seconds=60, min_unique_traders=5, min_trades=5, min_cum_quote_inflow_usd=500, min_liquidity_usd=1000, persistence_buckets=2)
    trades = [_trade(0, "seed", "BUY", 10, 0.0001)]  # raw seed print at 0.0001
    t = 60
    for i in range(10):  # bucket 1: 10 distinct buyers, 100 usd each at 0.001
        trades.append(_trade(t + i, f"u{i}", "BUY", 100, 0.001))
    trades.append(_trade(130, "u1", "SELL", 20, 0.0011))  # bucket 2 still ok
    trades.append(_trade(200, "u2", "BUY", 30, 0.0012))   # bucket 3
    liq = [(0, 100.0), (60, 5000.0)]
    res = first_meaningful_market(trades, params, liq)
    assert res.reached and res.bucket_index == 1 and res.ts == 60
    assert abs(res.price_usd - 0.001) < 1e-12  # VWAP of bucket 1
    assert res.raw_first_trade_price_usd == 0.0001


def test_first_meaningful_market_not_reached_without_traders():
    params = FMMParams(bucket_seconds=60, min_unique_traders=50, min_trades=5, min_cum_quote_inflow_usd=1, min_liquidity_usd=1, persistence_buckets=1)
    trades = [_trade(i, f"u{i % 3}", "BUY", 100, 0.001) for i in range(30)]
    res = first_meaningful_market(trades, params, None)
    assert not res.reached and "fmm_liquidity_proxy_inflow" in res.quality_flags
    assert res.evidence["unique_traders"] == 3
