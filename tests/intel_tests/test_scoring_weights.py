"""The composite score: renormalisation over measured components, and no silent zeros.

The weighting itself was derived from measurement (see the note in settings.DEFAULT_CONFIG).
What is asserted here is the arithmetic that carries it, and the two properties that make the
weighting safe: a component we failed to measure must not count as a bad one, and a component
that no longer carries weight must not influence the result.
"""
from intel.scoring.scores import compute_scores


class _HF:
    passed, reasons, unknowns, warnings = True, [], [], []
    security_reject = False


def _cfg(weights):
    return {"weights": weights, "asymmetry": {}, "narrative_cap_on_security_fail": 0}


def _metrics(**over):
    """A neutral token: every input that feeds a component is absent unless given."""
    m = {"token": "0x" + "aa" * 20, "security": {"checks": {}, "fails": [], "warns": [], "unknowns": []}}
    m.update(over)
    return m


def test_a_missing_component_is_not_counted_as_zero():
    """Two tokens identical except that one has no organic-volume measurement at all."""
    measured = compute_scores(_metrics(organic_volume_score=80.0), _cfg({"organic_volume": 0.5, "survival": 0.5}), _HF())
    missing = compute_scores(_metrics(), _cfg({"organic_volume": 0.5, "survival": 0.5}), _HF())
    # the one without the measurement falls back to its other components, not to a penalty
    assert missing.moonshot == missing.survival
    assert measured.moonshot > missing.moonshot or measured.organic_volume == 80.0


def test_the_composite_is_a_weighted_mean_of_what_is_available():
    s = compute_scores(_metrics(organic_volume_score=100.0), _cfg({"organic_volume": 1.0}), _HF())
    assert abs(s.moonshot - 100.0) < 1e-6


def test_a_component_with_no_weight_does_not_influence_the_score():
    high = compute_scores(_metrics(organic_volume_score=100.0), _cfg({"survival": 1.0}), _HF())
    low = compute_scores(_metrics(organic_volume_score=0.0), _cfg({"survival": 1.0}), _HF())
    assert high.moonshot == low.moonshot
    # it is still reported, so it stays auditable even when unweighted
    assert high.organic_volume == 100.0 and low.organic_volume == 0.0


def test_no_weighted_component_at_all_yields_zero_not_a_crash():
    s = compute_scores(_metrics(), _cfg({"organic_volume": 1.0}), _HF())
    assert s.moonshot == 0.0


def test_the_production_weighting_excludes_the_two_harmful_components():
    """Regression guard: asymmetry and narrative were measured as consistently harmful."""
    from intel.settings import DEFAULT_CONFIG

    w = DEFAULT_CONFIG["scoring"]["weights"]
    assert "asymmetry" not in w and "narrative" not in w
    assert w["organic_volume"] > 0 and w["distribution"] > 0
    assert abs(sum(w.values()) - 1.0) < 1e-9


def test_the_explanation_names_the_components_actually_used():
    s = compute_scores(_metrics(organic_volume_score=70.0), _cfg({"organic_volume": 0.5, "survival": 0.5}), _HF())
    joined = " ".join(s.explain["moonshot"])
    assert "organic_volume=70" in joined and "survival=" in joined
