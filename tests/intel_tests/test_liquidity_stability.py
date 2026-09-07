"""A sell trigger must not fire on measurement noise.

Regression 2026-09-04: PAIR's aggregated liquidity oscillated between 258k and 645k every few
minutes, because the provider returns a varying subset of its 16 pools. Comparing two point
readings turned one of those dips into "liquidity -51 %" and sold a position that then doubled.
"""
from intel.metrics.market import median_at, pct_change, robust_pct_change

T0 = 1_800_000_000
HOUR = 3600


def _oscillating(start_ts: int, n: int, high: float, low: float, every: int = 5) -> list[tuple[int, float]]:
    """A series mostly at ``high`` that drops to ``low`` once every ``every`` readings."""
    return [(start_ts + i * 120, low if i % every == 0 else high) for i in range(n)]


def test_a_point_to_point_comparison_is_fooled_by_the_oscillation():
    # a steady book, and one bad reading at the exact moment the decision is taken
    series = [(T0 + i * 120, 645_000.0) for i in range(800)]
    dip_ts = series[-1][0] + 120
    series.append((dip_ts, 258_000.0))
    naive = pct_change(series, dip_ts, "24h")
    assert naive is not None and naive < -0.5, "this is the bug: a flat series reads as a collapse"
    # the robust version, on the very same series and instant, reads it as flat
    assert abs(robust_pct_change(series, dip_ts, "24h")) < 0.05


def test_the_median_ignores_the_oscillation():
    series = _oscillating(T0, 800, 645_000, 258_000)      # ~27 h of readings
    end = series[-1][0]
    change = robust_pct_change(series, end, "24h")
    assert change is not None and abs(change) < 0.05, "a flat but noisy series must read as flat"


def test_a_real_collapse_is_still_caught():
    before = [(T0 + i * 120, 600_000.0) for i in range(400)]
    after_start = before[-1][0] + 120
    after = [(after_start + i * 120, 100_000.0) for i in range(400)]
    series = before + after
    change = robust_pct_change(series, series[-1][0], "24h")
    assert change is not None and change < -0.7, "a genuine drop must still trigger"


def test_the_median_needs_readings_nearby():
    series = [(T0, 500_000.0)]
    assert median_at(series, T0 + 10 * HOUR) is None
    assert median_at(series, T0) == 500_000.0
    assert robust_pct_change(series, T0, "24h") is None   # unknown, never a fabricated zero


def test_a_single_outlier_does_not_move_the_median():
    series = [(T0 + i * 60, 500_000.0) for i in range(30)]
    series[15] = (series[15][0], 1.0)
    assert median_at(series, T0 + 15 * 60, half_window=900) == 500_000.0
