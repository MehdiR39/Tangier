"""Quantitative research on ultra-early launches.

Separate from the live pipeline on purpose: it writes to its own SQLite file and never touches
the engine's tables. What it adds is the one thing the engine never collected -- launches sampled
WITHOUT reference to what became of them.

Everything the engine stores (trades, transfers, launch_profiles, swap_events) covers only tokens
the scanner selected for already having liquidity and volume: 280 tokens out of 75 017 pools. Any
statistic computed there is conditioned on success, which is why buying at random inside it
returned +73% median. This package fixes the sampling, not the analysis.
"""
RESEARCH_DB = "/app/data/research.sqlite"
