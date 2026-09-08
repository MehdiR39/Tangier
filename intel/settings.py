"""Environment + YAML configuration for the intel engines.

Secrets and endpoints come from environment variables (``.env`` in the project root is
read the same way ``scripts/daily_report.py`` does it: OS environment wins, then the
file). Tunables (thresholds, weights, portfolio positions, system addresses) live in
``config/intel.yaml`` and are deep-merged over ``DEFAULT_CONFIG``.
"""
from __future__ import annotations

import copy
import dataclasses
import os
from typing import Any

try:  # PyYAML is optional: without it, only DEFAULT_CONFIG is used.
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None  # type: ignore

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CONFIG_PATH = os.path.join(PROJECT_DIR, "config", "intel.yaml")
DEFAULT_DB_PATH = os.path.join(PROJECT_DIR, "data", "intel.sqlite")
DEFAULT_LOGS_DIR = os.path.join(PROJECT_DIR, "logs")


# --------------------------------------------------------------------------- #
# environment
# --------------------------------------------------------------------------- #
def read_env_file(path: str) -> dict[str, str]:
    """Minimal .env parser (stdlib only), ported from scripts/daily_report.py."""
    out: dict[str, str] = {}
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


_ENV_FILE_CACHE: dict[str, dict[str, str]] = {}


def env(key: str, default: str | None = None, *aliases: str, env_file: str | None = None) -> str | None:
    """OS environment first, then ``.env`` file, then aliases (same order), then default."""
    path = env_file or os.path.join(PROJECT_DIR, ".env")
    if path not in _ENV_FILE_CACHE:
        _ENV_FILE_CACHE[path] = read_env_file(path)
    filed = _ENV_FILE_CACHE[path]
    for k in (key, *aliases):
        v = os.environ.get(k)
        if v not in (None, ""):
            return v
        v = filed.get(k)
        if v not in (None, ""):
            return v
    return default


def env_int(key: str, default: int, *aliases: str) -> int:
    v = env(key, None, *aliases)
    try:
        return int(v) if v is not None else default
    except ValueError:
        return default


def env_float(key: str, default: float, *aliases: str) -> float:
    v = env(key, None, *aliases)
    try:
        return float(v) if v is not None else default
    except ValueError:
        return default


def env_bool(key: str, default: bool, *aliases: str) -> bool:
    v = env(key, None, *aliases)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


@dataclasses.dataclass(frozen=True)
class ProviderLimits:
    rpc_rps: float = 15.0        # node measured at 55 req/s with zero errors (2026-09-04); kept well under
    rpc_concurrency: int = 6
    blockscout_rpm: float = 20.0
    blockscout_reserve_calls: int = 25
    blockscout_concurrency: int = 2
    dexscreener_rpm: float = 250.0
    dexscreener_profiles_rpm: float = 50.0
    dexscreener_concurrency: int = 4
    telegram_rps: float = 0.5


@dataclasses.dataclass(frozen=True)
class Settings:
    chain_id: int = 4663
    dexscreener_chain: str = "robinhood"
    rpc_url: str = "https://rpc.mainnet.chain.robinhood.com"
    rpc_fallback_url: str = "https://rpc.mainnet.chain.robinhood.com"
    blockscout_url: str = "https://robinhoodchain.blockscout.com"
    blockscout_api_key: str | None = None
    dexscreener_url: str = "https://api.dexscreener.com"
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    db_path: str = DEFAULT_DB_PATH
    backup_dir: str = os.path.join(PROJECT_DIR, "data", "backups")
    logs_dir: str = DEFAULT_LOGS_DIR
    config_path: str = DEFAULT_CONFIG_PATH
    user_agent: str = "Mozilla/5.0 (compatible; tangier-intel/0.1; read-only research bot)"
    log_level: str = "INFO"
    health_port: int = 8787
    http_timeout: float = 30.0
    limits: ProviderLimits = dataclasses.field(default_factory=ProviderLimits)
    telegram_dry_run: bool = False

    @classmethod
    def load(cls, **overrides: Any) -> "Settings":
        limits = ProviderLimits(
            rpc_rps=env_float("INTEL_RPC_RPS", 15.0),
            rpc_concurrency=env_int("INTEL_RPC_CONCURRENCY", 6),
            blockscout_rpm=env_float("INTEL_BLOCKSCOUT_RPM", 20.0),
            blockscout_reserve_calls=env_int("INTEL_BLOCKSCOUT_RESERVE_CALLS", 25),
            blockscout_concurrency=env_int("INTEL_BLOCKSCOUT_CONCURRENCY", 2),
            dexscreener_rpm=env_float("INTEL_DEXSCREENER_RPM", 250.0),
            dexscreener_profiles_rpm=env_float("INTEL_DEXSCREENER_PROFILES_RPM", 50.0),
            dexscreener_concurrency=env_int("INTEL_DEXSCREENER_CONCURRENCY", 4),
            telegram_rps=env_float("INTEL_TELEGRAM_RPS", 0.5),
        )
        fallback = env("INTEL_RPC_FALLBACK_URL", "https://rpc.mainnet.chain.robinhood.com") or ""
        values: dict[str, Any] = dict(
            chain_id=env_int("INTEL_CHAIN_ID", 4663),
            dexscreener_chain=env("INTEL_DEXSCREENER_CHAIN", "robinhood") or "robinhood",
            rpc_url=env("INTEL_RPC_URL", fallback, "ROBINHOOD_RPC_URL") or fallback,
            rpc_fallback_url=fallback,
            blockscout_url=(env("INTEL_BLOCKSCOUT_URL", "https://robinhoodchain.blockscout.com", "BLOCKSCOUT_URL") or "").rstrip("/"),
            blockscout_api_key=env("INTEL_BLOCKSCOUT_API_KEY", None, "BLOCKSCOUT_API_KEY"),
            dexscreener_url=(env("INTEL_DEXSCREENER_URL", "https://api.dexscreener.com") or "").rstrip("/"),
            telegram_bot_token=env("INTEL_TELEGRAM_BOT_TOKEN", None, "TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=env("INTEL_TELEGRAM_CHAT_ID", None, "TELEGRAM_CHAT_ID"),
            db_path=env("INTEL_DB_PATH", DEFAULT_DB_PATH) or DEFAULT_DB_PATH,
            backup_dir=env("INTEL_BACKUP_DIR", os.path.join(PROJECT_DIR, "data", "backups")) or os.path.join(PROJECT_DIR, "data", "backups"),
            logs_dir=env("INTEL_LOGS_DIR", DEFAULT_LOGS_DIR) or DEFAULT_LOGS_DIR,
            config_path=env("INTEL_CONFIG", DEFAULT_CONFIG_PATH) or DEFAULT_CONFIG_PATH,
            user_agent=env("INTEL_HTTP_USER_AGENT", cls.user_agent) or cls.user_agent,
            log_level=env("INTEL_LOG_LEVEL", "INFO") or "INFO",
            health_port=env_int("INTEL_HEALTH_PORT", 8787),
            http_timeout=env_float("INTEL_HTTP_TIMEOUT", 30.0),
            limits=limits,
            telegram_dry_run=env_bool("INTEL_TELEGRAM_DRY_RUN", False),
        )
        values.update(overrides)
        return cls(**values)


# --------------------------------------------------------------------------- #
# tunables
# --------------------------------------------------------------------------- #
DEFAULT_CONFIG: dict[str, Any] = {
    "engine": {
        "portfolio_cycle_seconds": 60,
        # Latency, not capacity, is what a six-minute trading window punishes: an evaluation costs
        # 2.9 s since migration 6, so the cycles are what decide how late a decision arrives.
        "scanner_cycle_seconds": 60,
        "scanner_deep_cycle_seconds": 120,
        "rpc_log_chunk_blocks": 150_000,   # the node returns 400k blocks in 0.5 s; iter_logs adapts down on density
        "rpc_max_logs_per_query": 10000,
        "backfill_max_blocks": 4_500_000,  # ~5.2 days at ~0.1s blocks
        "trade_lookback_blocks": 900_000,  # ~1 day
        "top_holders_pages": 2,
        "max_pools_per_token": 10,
        "max_blocks_per_cycle": 300_000,
        "initial_lookback_blocks": 900_000,   # first pass: ~1 day, so evaluation starts fast
        "history_cycle_seconds": 30,          # background launch-to-date completion
        "history_blocks_per_cycle": 40_000,   # small slices so live cycles are never starved
        "backup_interval_seconds": 12 * 3600,  # online backup to INTEL_BACKUP_DIR (static files, host-readable)
        "backup_keep": 2,
        "holders_blockscout_interval_seconds": 900,
        "security_interval_seconds": 6 * 3600,
        "holder_snapshot_top_n": 100,
        "block_time_seconds_hint": 0.1,
    },
    "portfolio": {
        "positions": [
            {"address": "0xd18528b39da6464b3662c331a52181ecb15b1e18", "label": "SAYLORMOON", "quantity": None, "cost_basis_usd": None, "entry_ts": None},
            {"address": "0xaa0b48defde440b8445ba45db88cb076cf261e18", "label": "TAIWAN", "quantity": None, "cost_basis_usd": None, "entry_ts": None},
            {"address": "0x6b1d42927b1a84ec28fa88d4fc6fa7af404966be", "label": "PAIR", "quantity": None, "cost_basis_usd": None, "entry_ts": None},
        ]
    },
    "quote_assets": {
        # kind: stable -> usd fixed; native_wrapped -> priced via DexScreener; other -> DexScreener
        "0x5fc5360d0400a0fd4f2af552add042d716f1d168": {"symbol": "USDG", "kind": "stable", "usd": 1.0, "decimals": 6},
        "0x0bd7d308f8e1639fab988df18a8011f41eacad73": {"symbol": "WETH", "kind": "native_wrapped", "decimals": 18},
        "0x0000000000000000000000000000000000000000": {"symbol": "ETH", "kind": "native", "decimals": 18},
    },
    # Addresses that are never economic holders/traders. Labels drive concentration exclusion.
    "system_addresses": {
        "0x0000000000000000000000000000000000000000": "burn",
        "0x000000000000000000000000000000000000dead": "burn",
        "0x8366a39cc670b4001a1121b8f6a443a643e40951": "lp:uniswap_v4_pool_manager",
        "0xeb7c034704ef8dcd2d32324c1545f62fb4ad0862": "launchpad:doppler_airlock",
        "0x1b37d3a72082029c44b35b604ea473617580b69a": "launchpad:doppler_erc20_factory",
        "0x4e3468951d49f2eea976ed0d6e75ffcb44a9a544": "hook:doppler_hook_initializer",
        "0x6f02324d20cc679d0e585290caa6b16bacbc0f77": "hook:rehype_doppler_hook_initializer",
        "0x5f9eb5f6726fe88d5e39867967f5b833d2fa3215": "hook:rehype_doppler_hook_initializer",
        "0x6cce158b6d1747617fc218592b4d60b239b957ea": "hook:uniswap_v4_initializer",
        "0xde8886a0019ea060b8378ee37b8a23b8117f29a3": "hook:lockable_uniswap_v3_initializer",
        "0x7bf319d8e969f7596b1bc171da9ce322f67ae0c4": "launchpad:doppler_hook_migrator",
        "0x660740d7d6fb2c8998fa3fff459cceb9ac12c84b": "launchpad:rehype_doppler_hook_migrator",
        "0xa4052ee0f7904754222be15e2eba276314cc6a40": "launchpad:uniswap_v4_migrator",
        "0x3449085914bd77626502d85f588e0ba6f0d677be": "launchpad:uniswap_v4_migrator",
        "0xc16c826f75338a5ea626f94f8992191b4ce5aba2": "hook:swap_restrictor_doppler_hook",
        "0x7b6147ac3f615bdb764e7ebd5f517dac1ad163b8": "treasury:streamable_fees_locker",
        "0xf45588e8e0b1df9db9ae7e20ece5726ae931357c": "router:doppler_bundler",
        "0x39b38686a19836ac10162c490e4558e120cbbe5f": "router:robinhood_settler",
        "0x4337084d9e255ff0702461cf8895ce9e3b5ff108": "system:erc4337_entrypoint",
        "0x6131b5fae19ea4f9d964eac0408e4408b66337b5": "router:kyber_meta_aggregation_router_v2",
        "0xccc88a9d1b4ed6b0eaba998850414b24f1c315be": "bridge:relay_approval_proxy",
        "0x4cd00e387622c35bddb9b4c962c136462338bc31": "bridge:relay_depository",
        "0xf8b30c1b77e38f2df9d058c43a3af8d47161a0c7": "router:universal_router",
        "0x40d6bdac60c0810fc3ed30a988a4c3ac890fdd43": "router:universal_router",
        "0x74c7cffa2c1669808747de8be9164bb61726f7ae": "router:universal_router",
        "0x37e076a3fe61d6ef3459c1d4f583bd3e1b988334": "router:universal_router",
        "0xf04cd61f73aa11609f73155c940dc920a41a84df": "lp:uniswap_v4_position_manager",
        "0x7cfa3a5b8d143df7737478a8c93d05eac45171fc": "lp:uniswap_v4_position_manager",
        "0xe38a007e42d7aab09b7ad5fe083293c2cc3de45b": "lp:uniswap_v4_position_manager",
        "0x588c683ecc450f8b2aadb13d7f63792b840425dc": "lp:uniswap_v4_position_manager",
        "0x58daec3116aae6d93017baaea7749052e8a04fa7": "lp:uniswap_v4_position_manager",
    },
    "contracts": {
        "pool_manager": "0x8366a39cc670b4001a1121b8f6a443a643e40951",
        "airlock": "0xeb7c034704ef8dcd2d32324c1545f62fb4ad0862",
        "v4_quoter": "0x1234e25025fa902da29520bec7b6497b6e29a90a",
        "v4_quoter_fallbacks": ["0xa173e2eab577ebddaa9c5d75d181596911c5a9fb", "0x454a28d1ec3a2358b5e533574183e19d7330828b", "0x987e643e0d2b5a2b56ab52a0c0036c508d3451fa"],
        "state_view": "0x09c0e2e13ebb3ec5f29671272daba968528d9cda",
        "state_view_fallbacks": ["0x59bc1b60f7f5ff21cb8eaddc5f779524c30ba441", "0xfaf9a7656e9adfcc40bc660ab7fc97a2a40941ba", "0x5f131256599f5b597a939c165f7bf16e05b23d8b"],
        "weth": "0x0bd7d308f8e1639fab988df18a8011f41eacad73",
        "usdg": "0x5fc5360d0400a0fd4f2af552add042d716f1d168",
        "doppler_erc20_impl": "0x3be8b97fd0e713b5abe0649fa830223b6b4bc599",
    },
    "first_meaningful_market": {
        "bucket_seconds": 300,
        "min_unique_traders": 25,
        "min_trades": 50,
        "min_cum_quote_inflow_usd": 10000.0,
        "min_liquidity_usd": 20000.0,
        "persistence_buckets": 3,
    },
    "holders": {
        "min_balance_fraction_of_supply": 1e-9,
        "growth_windows": ["5m", "1h", "6h", "24h"],
        "acceleration_window": "1h",
        "divergence_price_move": 0.05,
        "divergence_holder_move": 0.03,
    },
    "concentration": {
        "top_n": [1, 5, 10, 20, 50],
        "exclude_kinds": ["lp", "burn", "contract", "treasury", "bridge", "system", "launchpad", "hook", "router"],
        "change_windows": ["1h", "6h", "24h"],
    },
    "whales": {
        "min_position_usd": 5000.0,
        "min_supply_pct": 0.0025,
        "ownership_percentile": 0.99,
        "max_tracked": 50,
        "flow_windows": ["5m", "1h", "6h", "24h"],
    },
    "clustering": {
        "sync_window_seconds": 60,
        "min_sync_events": 3,
        "same_funding_weight": 0.45,
        "direct_transfer_weight": 0.35,
        "sync_weight": 0.25,
        "pattern_weight": 0.20,
        "high_confidence": 0.75,
        "max_cluster_size": 200,
        "hub_degree_threshold": 50,
    },
    "smart_money": {
        "min_tokens_observed": 5,
        "min_closed_positions": 3,
        "early_entry_hours": 6,
        "success_multiple": 2.0,
    },
    "liquidity": {
        "price_impact_trade_sizes_usd": [100, 1000, 5000, 20000],
        "meaningful_pool_min_liquidity_usd": 5000.0,
        "lp_removal_alert_pct": 0.15,
        "lp_addition_alert_pct": 0.30,
        "single_pool_dependency_pct": 0.90,
    },
    "trading_quality": {
        "same_block_roundtrip_penalty": 15,
        "repetitive_size_penalty": 15,
        "wallet_volume_concentration_penalty": 25,
        "churn_penalty": 20,
        "low_unique_trader_penalty": 25,
        "repetitive_size_tolerance": 0.002,
        "top_wallet_volume_share_threshold": 0.35,
        "round_trip_ratio_threshold": 0.4,
        "volume_per_trader_usd_threshold": 25000.0,
    },
    "hard_filters": {
        "min_liquidity_usd": 20000.0,
        "min_liquidity_to_mc": 0.03,
        "liquidity_to_mc_reject_min_age_hours": 24,
        "max_top10_excluded_system_pct": 0.50,
        "max_insider_cluster_pct": 0.40,
        "insider_cluster_min_confidence": 0.75,
        "asymmetry_penalty_x_from_fmm": 50.0,
        "reject_on_security_fail": True,
    },
    "scoring": {
        # v0.2 (2026-09-02 review): survival/liquidity was the only component with a positive
        # relation to realised returns on day one; asymmetry and traction favoured small caps in
        # buying frenzies that then collapsed.
        # Measured, not assumed (2026-09-04, 3 942 evaluations paired with the price 24 h later;
        # weights chosen on the first half of the period and confirmed on the second, which was
        # never inspected while choosing). Rank correlation with the forward return, per half:
        #   organic_volume  +0.09 / +0.41   real distributed trading — the strongest signal
        #   distribution    +0.15 / +0.25   concentration, insiders, linked wallets
        #   smart_money     +0.13 / +0.11   buyers with a profitable observed history
        #   traction        -0.04 / +0.19   unstable, kept small
        #   survival        -0.04 / -0.10   kept small; it guards the downside rather than predicts
        #   asymmetry       -0.23 / -0.27   REMOVED — consistently harmful, and it carried the
        #                                   largest weight: it rewards tokens that already fell
        #   narrative       -0.09 / -0.22   REMOVED — consistently harmful
        # Result on the untouched half: the top quartile doubled 11.7 % of the time against a
        # 3.8 % base rate, with a +50.8 % median. The previous weighting scored 1.0 %, i.e. worse
        # than choosing at random.
        "weights": {"organic_volume": 0.35, "distribution": 0.30, "smart_money": 0.15, "traction": 0.10, "survival": 0.10},
        "asymmetry": {"target_mc_usd": 250000.0, "penalty_x_from_fmm": 50.0, "max_mc_usd": 50_000_000.0},
        "narrative_cap_on_security_fail": 0,
    },
    "states": {
        "breakout_return_1h": 0.15,
        "breakout_confirm_hours": 6,
        "extended_x_from_fmm": 20.0,
        "extended_return_24h": 2.0,
        "distribution_whale_netflow_usd": -20000.0,
        "distribution_top20_increase": 0.03,
        "thesis_break_drawdown": 0.70,
        "thesis_break_lp_drop": 0.50,
        "thesis_break_holder_drop_24h": -0.10,
        "accumulation_holder_growth_24h": 0.05,
        "early_accumulation_max_age_hours": 48,
        "watch_moonshot_min": 50,
        # CANDIDATE gating (anti-chasing, tradeable size).
        # 2026-09-03: floor lowered from 100k to 30k. A 20 € line moves a $37k pool by ~0.06 %,
        # so "fees eat everything" did not justify 100k — and that floor would have excluded a
        # token seen at $37k liquidity that then did ×7. Deliberate experiment: the paper book
        # measures whether the looser floor pays for the extra losers.
        "candidate_min_liquidity_usd": 30_000.0,
        "candidate_min_age_hours": 24,
        "candidate_max_buy_sell_ratio": 2.0,
        "candidate_max_return_1h": 0.50,
    },
    "scanner": {
        "discovery_sources": ["poolmanager_initialize", "airlock_create", "dexscreener_profiles", "dexscreener_boosts", "dexscreener_search"],
        "exclude_name_patterns": ["robinhood token"],  # tokenised stocks/ETFs are quote assets, not candidates
        "search_queries": ["USDG", "MSTR", "SPY", "TSM", "NVDA", "RH", "WETH"],
        "discovery_lookback_blocks": 100_000,
        "hot_sweep_blocks": 5_000,   # one chain-wide Swap sweep per triage cycle (~8 min of chain)
        "fastlane_per_cycle": 5,     # busiest tokens handed to the fast lane each triage cycle
        "analyse_now_per_cycle": 3,  # busiest tokens fully evaluated inside the triage cycle itself
        "hot_rescore_seconds": 900,  # below this, a token already has a recent enough score
        "stage1": {"max_age_hours": 24 * 14, "min_age_minutes": 10, "min_liquidity_usd": 20000.0, "max_market_cap_usd": 5_000_000.0, "min_market_cap_usd": 20000.0, "min_volume_24h_usd": 5000.0, "max_candidates": 300, "fresh_share": 0.5, "hot_share": 0.4},
        "stage2": {"min_holders": 50, "max_top10_pct": 0.60, "max_candidates": 25},
        # 8 per cycle was sized for an evaluation that took 355 s. After the per-pass block bound
        # and the covering indexes of migration 6, one evaluation costs 2.9 s (measured
        # 2026-09-05), so the cycle budget rather than the count is now the real limit.
        "stage3": {"max_candidates_per_cycle": 60, "refresh_per_cycle": 5, "backfill_blocks": 900_000,
                   "cycle_budget_seconds": 240, "max_blocks_per_pass": 20_000},
        "moonshot_alert_threshold": 70,
        "rescan_interval_seconds": 600,
    },
    "alerts": {
        "enabled": True,
        "min_severity": "WATCH",
        "cooldown_seconds": {"INFO": 21600, "WATCH": 10800, "IMPORTANT": 3600, "CRITICAL": 900},
        "material_score_delta": 10,
        "lp_drop_pct": 0.15,
        "top_wallet_distribution_pct": 0.20,
        "whale_accumulation_usd": 25000.0,
        "whale_distribution_usd": -25000.0,
        "holder_acceleration_threshold": 1.0,
        "holder_acceleration_min_new": 25,
        "max_per_cycle": 12,
        "scanner_alert_min_moonshot": 60,
        "scanner_min_liquidity_usd": 30_000.0,    # matches the candidate floor (20 € line: impact ~0.06 %)
        "hard_filters_pass_min_moonshot": 70,
        "daily_digest_enabled": True,
        "daily_digest_hour_utc": 7,   # 09:00 Paris in summer, 08:00 in winter
    },
    "execution": {
        # Dry run builds and checks the complete order but sends nothing. Going live is a
        # deliberate act: mode must be "live" AND the key supplied through the environment.
        "enabled": True,                    # the loop runs; "mode" decides whether anything is sent
        "mode": "dry_run",                  # dry_run | live
        "cycle_seconds": 30,                # a decision is worth minutes, not hours
        "max_decision_age_s": 600,          # past this, the price the decision was made on is gone
        "kill_switch": False,               # True refuses every order, whatever the mode
        "router": "0xf8b30c1b77e38f2df9d058c43a3af8d47161a0c7",   # UniversalRouter, deployment verified
        "permit2": "0x000000000022d473030f116ddee9f6b43ac78ba3",
        # USDG carries the most activity (554 live pools over 24 h on 2026-09-04), native ETH adds
        # 326 more and needs no spending grant at all: it travels as the transaction's value.
        "allowed_quotes": ["0x5fc5360d0400a0fd4f2af552add042d716f1d168",
                           "0x0000000000000000000000000000000000000000"],
        "max_eur_per_order": 25.0,
        "max_open_positions": 15,
        "max_orders_per_day": 40,
        "max_eur_per_day": 200.0,
        "max_slippage_pct": 5.0,
        "min_quote_liquidity_usd": 20000.0,
        "deadline_seconds": 120,
    },
    "solana": {"enabled": False, "mode": "dry_run", "poll_seconds": 30, "size_eur": 5.0, "min_buyers": 0,
               "max_trades_per_buyer": 0, "min_liquidity_usd": 5000.0, "max_per_hour": 10, "slippage_pct": 5.0,
               "max_impact_pct": 10.0, "sol_eur": 180.0, "max_open_positions": 4, "max_age_seconds": 600, "take_profit_multiple": 2.0, "max_hold_seconds": 900, "sell_slippage_pct": 25.0, "buy_budget": 0, "budget_since_ts": 0},
    "t1": {
        # T+1 watcher (intel/engines/t1_watcher.py). Measured 2026-09-06 on 5 491 launches drawn
        # at random: pools with >= ~27 swaps in the minute after their first trade reach x2 about
        # twice as often as the rest, in every period, and the rule is worthless two minutes later.
        # Off by default: switching it on only makes the watcher WRITE decisions; the execution
        # section above still has to be deliberately switched live for any order to leave.
        "enabled": False,
        "min_trades": 27, "max_trades": 60,               # swaps in the first 60 s, the only threshold that held
        "decide_after_blocks": 600,     # ~60 s at 0.1 s a block
        "size_eur": 5.0,                # the one ticket size that never lost in any period
        "max_per_hour": 20,
        "poll_seconds": 5,              # the scheduler floors every loop at 5 s anyway
        "max_blocks_per_poll": 300,     # ~30 s of chain; a bigger gap is skipped, not chased
        # Depth floor for a T+1 entry, in place of the scanner's 20 000 $ (which describes tokens
        # hours old). 500 $ of quote-side depth keeps a 5 EUR ticket's impact near 1 %; the 5 %
        # slippage cap and the daily ceilings in `execution` still apply unchanged.
        "min_quote_liquidity_usd": 500.0, "take_profit_multiple": 2.0, "max_hold_seconds": 300, "sell_retry_max": 8, "retry_gap_seconds": 20, "recover_interval_seconds": 600, "recover_max": 40, "recover_per_cycle": 6, "sell_slippage_pct": 25.0, "max_slippage_pct": 8.0,
    },
    "decisions": {
        # The user only hears ACHÈTE / VENDS. The book stays virtual unless the execution
        # section above is explicitly switched to live.
        "enabled": True,
        "size_eur": 20.0,
        "max_open": 15,
        "min_moonshot_buy": 70,
        "buy_states": ["ACCUMULATION", "EARLY_ACCUMULATION", "BREAKOUT_CONFIRMED"],
        # Take profit, and take all of it. Measured 2026-09-04 on 381 tokens, costs deducted, with
        # the level chosen on the first half of the period and the ranking confirmed on the second:
        #   x1.5 sell all   +27.0 % / -8.0 %      x2 sell all   +21.1 % / -15.5 %
        #   x3   sell all   -17.6 % / -37.1 %
        # Keeping half is the costly part: it turns +4.2 % into -39.5 %, because 91 % of these
        # tokens stop trading after the move and the kept half can no longer be sold at all.
        # The ranking holds in both halves; the profitability does not — the second half loses at
        # every level. These numbers make the strategy less bad, they do not make it proven.
        "take_profit_multiple": 1.5,
        "take_profit_sells_all": True,
        # Fast lane. The deep pass scores ~96 tokens an hour against a queue of 14 000, so a token
        # that becomes tradeable waits hours while its window — a median of six minutes — closes.
        # Measured 2026-09-04: 100 % of tradeable tokens spotted, 0 % scored in time. This buys on
        # the two things that were actually shown to matter, real traded volume and a clean
        # contract, and leaves the score to refine everything else.
        "fastlane_enabled": True,
        "fastlane_min_volume_usd": 2000.0,   # USD genuinely traded in the preceding hour
        "fastlane_min_age_minutes": 10,
        "fastlane_max_age_hours": 48,
        "fastlane_max_unknown_checks": 2,    # an unanswered security check is not a passing one
        "moonbag_multiple": 1.5,    # kept for older records that reference it
        # 2026-09-03 simulation on 559 real price paths: a -35 % trailing stop after the x3 was
        # the WORST rule in every run (win rate 24-25 % vs 42-43 % without it) — these tokens
        # swing ±50 % routinely, so it converts noise into a realised loss. Removed.
        # The hard stop is left WIDE: the two runs contradicted each other on -50 %, so only a
        # real collapse triggers it. Risk control is the line size (20 € = 5 % of 400 €), not stops.
        "stop_loss": 0.75,
        "trailing_stop": 0.70,
        # 18 h was not merely unoptimised, it was unreachable: measured 2026-09-04, 94 % of these
        # tokens have stopped trading entirely 6 h after becoming buyable, so there is nobody left
        # to sell to. Sellability collapses after roughly an hour; an out-of-sample sweep
        # independently picked 4 h. 3 h is the middle of that bracket, not a proven optimum.
        "timeout_hours": 3,         # frees a virtual line for a fresh candidate (never applies to held tokens)
        "liquidity_drop_sell": 0.5,
        "rebuy_cooldown_seconds": 3 * 86400,
        "portfolio_reopen_cooldown_seconds": 12 * 3600,  # after a SELL on a held token, re-follow after 12h if healthy
        "peak_drawdown_sell": 0.7,      # sell all when -70% from the peak reached since the position exists
        "repeat_guard_seconds": 86400,  # never the same decision kind twice in 24h for a token
        # Market-weather switch: OFF. It was added by analogy with the user's July 2026 study
        # (large alts, multi-week horizons) but there is no evidence yet that BTC drives these
        # 24h memecoin moves. The regime is still recorded with every score so the question can
        # be answered with data later; it changes no behaviour today.
        "regime_gate_enabled": False,
        "regime_block": ["bear"],
        "telegram_mode": "decisions",   # decisions | alerts | both
    },
    "retention": {
        "prune_interval_seconds": 6 * 3600,
        "dead_token_days": 2,           # raw events of REJECTED/DORMANT scanner tokens older than this are dropped
        "holder_snapshot_days": 7,
        "pair_snapshot_days": 14,
    },
    "backtest": {"horizons": ["1h", "6h", "24h", "3d", "7d"], "survival_liquidity_retention": 0.5},
    "health": {"stale_after_seconds": 300},
}


def deep_merge(base: dict[str, Any], override: dict[str, Any] | None) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


class IntelConfig:
    """Dotted-path access over the merged configuration dictionary."""

    def __init__(self, data: dict[str, Any] | None = None) -> None:
        self.data = deep_merge(DEFAULT_CONFIG, data or {})
        # normalise addresses
        self.data["system_addresses"] = {k.lower(): v for k, v in self.data.get("system_addresses", {}).items()}
        self.data["quote_assets"] = {k.lower(): v for k, v in self.data.get("quote_assets", {}).items()}
        for p in self.data.get("portfolio", {}).get("positions", []):
            p["address"] = str(p["address"]).lower()

    @classmethod
    def load(cls, path: str | None = None) -> "IntelConfig":
        path = path or DEFAULT_CONFIG_PATH
        data: dict[str, Any] = {}
        if path and os.path.exists(path) and yaml is not None:
            with open(path, encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
        return cls(data)

    def get(self, path: str, default: Any = None) -> Any:
        cur: Any = self.data
        for part in path.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    def section(self, name: str) -> dict[str, Any]:
        v = self.get(name, {})
        return v if isinstance(v, dict) else {}

    @property
    def portfolio_positions(self) -> list[dict[str, Any]]:
        return list(self.get("portfolio.positions", []) or [])

    @property
    def system_addresses(self) -> dict[str, str]:
        return dict(self.data.get("system_addresses", {}))

    @property
    def quote_assets(self) -> dict[str, dict[str, Any]]:
        return dict(self.data.get("quote_assets", {}))

    def system_kind(self, address: str) -> str | None:
        label = self.data["system_addresses"].get(address.lower())
        if not label:
            return None
        return label.split(":", 1)[0]
