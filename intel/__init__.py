"""Tangier Intel: read-only crypto intelligence engines (portfolio watcher + moonshot scanner).

Chain: Robinhood Chain (chain_id 4663). The package never signs or submits transactions.
"""

__version__ = "0.1.0"

# Bump whenever a scoring formula, weight default, hard filter or state rule changes.
# Stored with every token_scores row so historical scores are reproducible.
# v0.3: weights derived from measurement instead of judgement. The composite is now built from
# trading authenticity, holder distribution and smart money; asymmetry and narrative were removed
# after both were shown to correlate negatively with the forward return in two independent halves
# of the period. Validated out of sample: top quartile 11.7 % of doublings against a 3.8 % base
# rate, where the previous weighting scored 1.0 %.
MODEL_VERSION = "intel-scoring-v0.3.0"
