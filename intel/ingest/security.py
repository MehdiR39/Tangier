"""Contract / security checks. Every check yields PASS / WARN / FAIL / UNKNOWN.

UNKNOWN is never upgraded to PASS. Verified ABIs (Blockscout) are inspected for
privileged functions; unverified bytecode is scanned for ``PUSH4 selector`` patterns
(heuristic → at best UNKNOWN when nothing is found). Sell-ability is probed with
``eth_call`` simulations (transfer from a real holder, V4 quoter sell quote); these are
indicators, not proof.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from intel import MODEL_VERSION
from intel.chain import doppler, erc20
from intel.chain.constants import PRIVILEGED_SIGNATURES, V4_QUOTE_EXACT_INPUT_SINGLE
from intel.context import IntelContext
from intel.ingest.pools import PoolInfo
from intel.utils.abi import ZERO_ADDRESS, bytecode_has_selector, decode, encode_call, selector
from intel.utils.timeutil import now_ts

log = logging.getLogger(__name__)

STATUS_ORDER = {"PASS": 0, "UNKNOWN": 1, "WARN": 2, "FAIL": 3}
DEAD = "0x000000000000000000000000000000000000dead"


@dataclass
class Check:
    name: str
    status: str
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class SecurityReport:
    checks: list[Check]
    launchpad: str | None
    implementation: str | None
    proxy_type: str | None
    is_verified: bool | None
    owner: str | None
    creator: str | None
    team_addresses: dict[str, str]

    @property
    def overall(self) -> str:
        worst = "PASS"
        for c in self.checks:
            if STATUS_ORDER[c.status] > STATUS_ORDER[worst]:
                worst = c.status
        return worst

    @property
    def fails(self) -> list[Check]:
        return [c for c in self.checks if c.status == "FAIL"]

    @property
    def warns(self) -> list[Check]:
        return [c for c in self.checks if c.status == "WARN"]

    @property
    def unknowns(self) -> list[Check]:
        return [c for c in self.checks if c.status == "UNKNOWN"]

    def get(self, name: str) -> Check | None:
        return next((c for c in self.checks if c.name == name), None)

    def as_dict(self) -> dict[str, Any]:
        return {
            "overall": self.overall,
            "fails": [c.name for c in self.fails],
            "warns": [c.name for c in self.warns],
            "unknowns": [c.name for c in self.unknowns],
            "checks": {c.name: {"status": c.status, "detail": c.detail} for c in self.checks},
            "launchpad": self.launchpad,
            "implementation": self.implementation,
            "proxy_type": self.proxy_type,
            "is_verified": self.is_verified,
            "owner": self.owner,
            "creator": self.creator,
            "team_addresses": self.team_addresses,
        }


def _abi_function_sigs(abi: list[dict[str, Any]] | None) -> set[str]:
    out: set[str] = set()
    for item in abi or []:
        if item.get("type") != "function":
            continue
        types = ",".join(_abi_type(i) for i in item.get("inputs", []))
        out.add(f"{item['name']}({types})")
    return out


def _abi_type(inp: dict[str, Any]) -> str:
    t = inp.get("type", "")
    if t.startswith("tuple"):
        inner = ",".join(_abi_type(c) for c in inp.get("components", []))
        return f"({inner}){t[5:]}"
    return t


def _names(sigs: set[str]) -> set[str]:
    return {s.split("(", 1)[0].lower() for s in sigs}


async def run_security_checks(ctx: IntelContext, token: str, pools: dict[str, PoolInfo], *, top_holder: str | None = None, total_supply: int | None = None, persist: bool = True) -> SecurityReport:
    token = token.lower()
    checks: list[Check] = []
    team: dict[str, str] = {}

    # ---- proxy / implementation / verification ---------------------------- #
    code = await ctx.rpc.get_code(token)
    pinfo = await erc20.proxy_info(ctx.rpc, token, code)
    impl = pinfo["implementation"]
    proxy_type = pinfo["proxy_type"]
    bs_addr = None
    bs_contract = None
    bs_impl_contract = None
    try:
        bs_addr = await ctx.blockscout.address(token)
        bs_contract = await ctx.blockscout.smart_contract(token)
        if impl:
            bs_impl_contract = await ctx.blockscout.smart_contract(impl)
    except Exception as exc:
        log.info("blockscout security lookups failed for %s: %s", token[:10], exc)
    if bs_addr and not proxy_type and bs_addr.get("proxy_type"):
        proxy_type = bs_addr.get("proxy_type")
        impls = bs_addr.get("implementations") or []
        if impls and not impl:
            impl = str(impls[0].get("address_hash") or impls[0].get("address") or "").lower() or None
    creator = (bs_addr or {}).get("creator_address_hash")
    creator = creator.lower() if creator else None
    verified_token = bool((bs_addr or {}).get("is_verified")) if bs_addr else None
    verified_impl = bool((bs_impl_contract or {}).get("is_verified")) if bs_impl_contract else None
    is_verified = verified_impl if impl else verified_token
    if bs_addr is None:
        checks.append(Check("source_verified", "UNKNOWN", "explorer unavailable"))
    elif is_verified:
        checks.append(Check("source_verified", "PASS", "verified" + (" (implementation)" if impl else ""), {"implementation": impl}))
    else:
        checks.append(Check("source_verified", "WARN", "source not verified", {"implementation": impl}))

    doppler_impl = str(ctx.config.get("contracts.doppler_erc20_impl", "")).lower()
    launchpad = None
    asset_data = None
    if impl and impl == doppler_impl:
        launchpad = "doppler"
    asset_data = await doppler.airlock_asset_data(ctx.rpc, ctx.airlock, token)
    if asset_data:
        launchpad = launchpad or "doppler"
        for k in ("timelock", "governance", "integrator"):
            a = asset_data.get(k)
            if a and a != ZERO_ADDRESS:
                team[a.lower()] = f"doppler_{k}"
    if proxy_type == "eip1167":
        checks.append(Check("proxy", "PASS" if launchpad == "doppler" else "WARN", f"EIP-1167 clone of {impl}" + (" (DopplerERC20V1, immutable clone)" if launchpad == "doppler" else " (unknown implementation)"), {"implementation": impl}))
    elif proxy_type in ("eip1967", "beacon"):
        checks.append(Check("proxy", "WARN", f"upgradeable proxy ({proxy_type}); implementation {impl}, admin {pinfo.get('admin')}", {"implementation": impl, "admin": pinfo.get("admin"), "beacon": pinfo.get("beacon")}))
        checks.append(Check("upgradeability", "WARN", "logic can be replaced by the proxy admin"))
    elif proxy_type:
        checks.append(Check("proxy", "WARN", f"proxy type {proxy_type}", {"implementation": impl}))
    else:
        checks.append(Check("proxy", "PASS", "not a proxy"))
        checks.append(Check("upgradeability", "PASS", "no proxy pattern detected"))
    if proxy_type == "eip1167":
        checks.append(Check("upgradeability", "PASS", "minimal proxy clones are immutable"))

    # ---- ownership --------------------------------------------------------- #
    owner = await erc20.owner_of(ctx.rpc, token)
    if owner is None:
        checks.append(Check("owner_admin", "UNKNOWN", "no owner() / getOwner()"))
    elif owner in (ZERO_ADDRESS, DEAD):
        checks.append(Check("owner_admin", "PASS", "ownership renounced", {"owner": owner}))
    else:
        lbl = ctx.system_label(owner)
        if lbl:
            checks.append(Check("owner_admin", "WARN", f"owner is protocol contract {lbl}", {"owner": owner}))
        else:
            team[owner.lower()] = "owner"
            owner_code = await ctx.rpc.get_code(owner)
            kind = "contract" if owner_code and owner_code != "0x" else "EOA"
            checks.append(Check("owner_admin", "WARN", f"owner is {kind} {owner} (not renounced)", {"owner": owner, "owner_kind": kind}))

    # ---- privileged functions --------------------------------------------- #
    abi = (bs_impl_contract or bs_contract or {}).get("abi") if (bs_impl_contract or bs_contract) else None
    sigs = _abi_function_sigs(abi) if abi else set()
    names = _names(sigs)
    found: dict[str, list[str]] = {}
    scan_code = None
    if not sigs:
        scan_code = (bs_impl_contract or {}).get("deployed_bytecode") if impl else code
        if impl and not scan_code:
            try:
                scan_code = await ctx.rpc.get_code(impl)
            except Exception:
                scan_code = None
    for sig, (category, _sev) in PRIVILEGED_SIGNATURES.items():
        hit = False
        if sigs:
            hit = sig in sigs
        elif scan_code:
            hit = bytecode_has_selector(scan_code, selector(sig))
        if hit:
            found.setdefault(category, []).append(sig)
    if sigs:
        for n in names:
            if n.startswith("mint") and "mint" not in found:
                found.setdefault("mint", []).append(n + "(...)")
            if ("blacklist" in n or n in ("setbots", "addbots")) and "blacklist" not in found:
                found.setdefault("blacklist", []).append(n + "(...)")
            if ("tax" in n or "fee" in n) and n.startswith(("set", "update")) and "tax" not in found:
                found.setdefault("tax", []).append(n + "(...)")
    evidence_mode = "abi" if sigs else ("bytecode_scan" if scan_code else "none")
    renounced = owner in (ZERO_ADDRESS, DEAD)

    def priv_check(name: str, categories: list[str], fail_if_found: bool, unknown_detail: str) -> None:
        hits = [s for c in categories for s in found.get(c, [])]
        if hits:
            sev = "FAIL" if (fail_if_found and not renounced) else "WARN"
            checks.append(Check(name, sev, f"{'/'.join(categories)} functions present ({evidence_mode}): {', '.join(hits[:4])}" + (" — owner renounced" if renounced else ""), {"functions": hits, "mode": evidence_mode}))
        elif evidence_mode == "abi":
            checks.append(Check(name, "PASS", f"no {'/'.join(categories)} function in verified ABI", {"mode": evidence_mode}))
        elif evidence_mode == "bytecode_scan":
            checks.append(Check(name, "UNKNOWN", f"unverified; bytecode scan found no {'/'.join(categories)} selector (heuristic)", {"mode": evidence_mode}))
        else:
            checks.append(Check(name, "UNKNOWN", unknown_detail))

    priv_check("mint_capability", ["mint"], True, "no ABI or bytecode available")
    priv_check("supply_modification", ["burn_from", "rescue"], False, "no ABI or bytecode available")
    priv_check("blacklist", ["blacklist"], True, "no ABI or bytecode available")
    priv_check("whitelist", ["whitelist"], False, "no ABI or bytecode available")
    priv_check("pause", ["pause", "trading_switch", "sell_switch"], False, "no ABI or bytecode available")
    priv_check("taxes", ["tax"], False, "no ABI or bytecode available")
    priv_check("transfer_restrictions", ["transfer_limit", "pool_lock"], False, "no ABI or bytecode available")

    paused = await erc20.is_paused(ctx.rpc, token)
    if paused is True:
        checks.append(Check("paused_state", "FAIL", "contract reports paused()=true"))
    elif paused is False:
        checks.append(Check("paused_state", "PASS", "paused()=false"))

    # ---- Doppler-specific views -------------------------------------------- #
    if launchpad == "doppler":
        views = await doppler.doppler_erc20_views(ctx.rpc, token)
        bl_active = views.get("isBalanceLimitActive")
        bl_end = views.get("balanceLimitEnd")
        max_bl = views.get("maxBalanceLimit")
        if bl_active is None:
            checks.append(Check("doppler_balance_limit", "UNKNOWN", "balance limit state unreadable"))
        elif bl_active:
            pct = (max_bl / total_supply) if (max_bl and total_supply) else None
            checks.append(Check("doppler_balance_limit", "WARN", f"anti-whale balance limit active until {bl_end}" + (f" (max {pct:.2%} of supply)" if pct else ""), {"balance_limit_end": bl_end, "max_balance_limit": str(max_bl) if max_bl is not None else None}))
        else:
            checks.append(Check("doppler_balance_limit", "PASS", "balance limit inactive"))
        locked = views.get("isPoolLocked")
        locked_pool = views.get("pool")
        if locked is None:
            checks.append(Check("doppler_pool_lock", "UNKNOWN", "pool lock state unreadable"))
        elif locked:
            # Verified on SAYLORMOON: isPoolLocked()=true while swaps, sells and quotes all work.
            # The DERC20 lock targets the address returned by pool() (pre-migration venue), not
            # the Uniswap v4 PoolId the token trades on, so on its own it is a WARN. It becomes
            # a FAIL only if empirical sell evidence also fails (see honeypot_indicators).
            checks.append(Check("doppler_pool_lock", "WARN", f"isPoolLocked()=true for pool() {locked_pool}; trading venue is a v4 PoolId — verified empirically below", {"locked_pool": locked_pool, "controller": views.get("controller")}))
        else:
            checks.append(Check("doppler_pool_lock", "WARN", "owner/controller can call lockPool() (Doppler standard)", {"controller": views.get("controller")}))
        vested = views.get("vestedTotalAmount")
        nsched = views.get("vestingScheduleCount")
        if vested is not None and total_supply:
            share = vested / total_supply
            checks.append(Check("vesting", "WARN" if share > 0.10 else "PASS", f"{share:.1%} of supply under vesting ({nsched} schedules)", {"vested_total": str(vested), "schedules": nsched}))
        elif vested is None:
            checks.append(Check("vesting", "UNKNOWN", "vesting not readable"))

    # ---- deployer / team holdings ------------------------------------------ #
    if creator and not ctx.system_label(creator):
        team.setdefault(creator, "creator")
    holdings: dict[str, float] = {}
    if team and total_supply:
        for a in list(team)[:6]:
            bal = await erc20.balance_of(ctx.rpc, token, a)
            if bal is not None:
                holdings[a] = bal / total_supply
        if holdings:
            worst = max(holdings.values())
            status = "FAIL" if worst > 0.30 else "WARN" if worst > 0.05 else "PASS"
            checks.append(Check("deployer_holdings", status, "team/deployer wallets hold " + ", ".join(f"{team[a]} {v:.1%}" for a, v in holdings.items()), {"holdings": {a: v for a, v in holdings.items()}}))
        else:
            checks.append(Check("deployer_holdings", "UNKNOWN", "team balances unreadable"))
    elif not team:
        checks.append(Check("deployer_holdings", "UNKNOWN", "deployer/team addresses unknown"))
    else:
        checks.append(Check("deployer_holdings", "UNKNOWN", "total supply unknown"))

    # ---- LP control ---------------------------------------------------------- #
    if pools:
        ids = list(pools.keys())
        rows = ctx.db.query(
            f"SELECT sender, SUM(CAST(liquidity_delta AS REAL)) AS d, COUNT(*) AS n FROM liquidity_events WHERE chain_id=? AND pair_id IN ({','.join('?' for _ in ids)}) GROUP BY sender",
            (ctx.chain_id, *ids),
        )
        if rows:
            senders = {r["sender"]: (r["d"], r["n"]) for r in rows}
            labels = {s: (ctx.system_label(s) or "unlabeled") for s in senders}
            hook_managed = all(l.startswith(("hook:", "launchpad:", "lp:")) for l in labels.values())
            if hook_managed:
                checks.append(Check("lp_control", "PASS", "all liquidity managed by launchpad hooks / position manager contracts", {"senders": labels}))
            else:
                unl = [s for s, l in labels.items() if l == "unlabeled"]
                checks.append(Check("lp_control", "WARN", f"liquidity added by non-protocol addresses ({len(unl)}); LP can be withdrawn", {"senders": labels}))
        else:
            hooks = {p.hooks for p in pools.values() if p.hooks}
            if hooks and all(ctx.system_label(h) for h in hooks):
                checks.append(Check("lp_control", "WARN", "no liquidity events ingested yet; pool has launchpad hook", {"hooks": list(hooks)}))
            else:
                checks.append(Check("lp_control", "UNKNOWN", "no liquidity events ingested yet"))
    else:
        checks.append(Check("lp_control", "UNKNOWN", "no pools known"))

    # ---- sell-ability probes ------------------------------------------------- #
    # Simulate from a holder whose *real* on-chain balance is known to be positive: replayed
    # balances can be partial, and simulating from an empty wallet reverts for the wrong reason.
    transfer_ok: bool | None = None
    detail = "no holder available for simulation"
    holder_used: str | None = None
    candidates = [top_holder] if top_holder else []
    candidates += [r["address"] for r in ctx.db.query(
        "SELECT address FROM holders WHERE chain_id=? AND token_address=? AND is_system=0 AND COALESCE(is_contract,0)=0 ORDER BY CAST(balance AS REAL) DESC LIMIT 6", (ctx.chain_id, token)
    ) if r["address"] != top_holder]
    for h in candidates[:6]:
        bal = await erc20.balance_of(ctx.rpc, token, h)
        if not bal or bal < 1:
            continue
        holder_used = h
        transfer_ok, detail = await erc20.simulate_transfer(ctx.rpc, token, h, "0x000000000000000000000000000000000000beef", 1)
        if transfer_ok is not None:
            break
    if transfer_ok is True:
        checks.append(Check("transfer_simulation", "PASS", f"eth_call transfer from {holder_used[:10]} (real balance > 0) succeeded"))
    elif transfer_ok is False:
        checks.append(Check("transfer_simulation", "FAIL", f"transfer from {holder_used[:10]} (real balance > 0) reverted: {detail}"))
    else:
        checks.append(Check("transfer_simulation", "UNKNOWN", f"transfer simulation inconclusive: {detail}"))
    quote_ok: bool | None = None
    if pools:
        quote_ok, qdetail = await quote_sell(ctx, token, pools)
        if quote_ok is True:
            checks.append(Check("sell_quote", "PASS", qdetail))
        elif quote_ok is False:
            checks.append(Check("sell_quote", "WARN", f"sell quote reverted on all quoters: {qdetail}"))
        else:
            checks.append(Check("sell_quote", "UNKNOWN", qdetail))
    else:
        checks.append(Check("sell_quote", "UNKNOWN", "no pools known"))
    # empirical evidence: reconstructed successful sells by distinct wallets in the last 24h
    recent_sells = ctx.db.query_one(
        "SELECT COUNT(*) AS n, COUNT(DISTINCT trader) AS w FROM trades WHERE chain_id=? AND token_address=? AND side='SELL' AND ts>=?",
        (ctx.chain_id, token, now_ts() - 86400),
    )
    n_sells = int(recent_sells["n"] or 0) if recent_sells else 0
    n_sellers = int(recent_sells["w"] or 0) if recent_sells else 0
    sells_observed = n_sellers >= 5
    lock_flag = launchpad == "doppler" and any(c.name == "doppler_pool_lock" and c.status in ("WARN", "FAIL") and "isPoolLocked()=true" in c.detail for c in checks)
    if paused is True or (transfer_ok is False and not sells_observed and quote_ok is not True):
        checks.append(Check("honeypot_indicators", "FAIL", "transfers blocked / paused — selling likely impossible", {"recent_sells": n_sells, "recent_sellers": n_sellers}))
    elif transfer_ok is False:
        # simulation reverted but the chain shows real sells / a working quote: contradictory evidence
        checks.append(Check("honeypot_indicators", "WARN", f"transfer simulation reverted but {n_sells} sells by {n_sellers} wallets in 24h (quote={'ok' if quote_ok else 'n/a'}) — possible transfer restriction (limits, whitelist), verify before buying", {"recent_sells": n_sells}))
    elif lock_flag and not (quote_ok is True or sells_observed):
        checks.append(Check("honeypot_indicators", "FAIL", "isPoolLocked()=true and no successful sell quote / observed sells", {"recent_sells": n_sells}))
    elif transfer_ok is True and (quote_ok is True or sells_observed):
        detail = f"transfer simulation ok; sell quote {'ok' if quote_ok else 'n/a'}; {n_sells} sells by {n_sellers} wallets in 24h (evidence, not a guarantee)"
        checks.append(Check("honeypot_indicators", "PASS", detail, {"recent_sells": n_sells, "recent_sellers": n_sellers}))
    elif transfer_ok is True or quote_ok is True or sells_observed:
        checks.append(Check("honeypot_indicators", "WARN", f"partial evidence only (transfer={transfer_ok}, quote={quote_ok}, sellers24h={n_sellers})", {"recent_sells": n_sells}))
    else:
        checks.append(Check("honeypot_indicators", "UNKNOWN", "simulations inconclusive and no observed sells"))

    report = SecurityReport(checks, launchpad, impl, proxy_type, is_verified, owner, creator, team)
    if persist:
        ts = now_ts()
        with ctx.db.transaction():
            for c in checks:
                ctx.db.insert("contract_security", {
                    "ts": ts, "chain_id": ctx.chain_id, "token_address": token, "source": "rpc+blockscout", "block_number": None,
                    "check_name": c.name, "status": c.status, "detail": c.detail, "evidence_json": json.dumps(c.evidence, default=str), "model_version": MODEL_VERSION,
                })
            ctx.db.execute(
                "UPDATE tokens SET launchpad=COALESCE(?, launchpad), proxy_type=?, implementation=?, is_verified=?, creator_address=COALESCE(creator_address, ?), updated_ts=? WHERE chain_id=? AND address=?",
                (launchpad, proxy_type, impl, None if is_verified is None else int(is_verified), creator, ts, ctx.chain_id, token),
            )
    return report


async def quote_sell(ctx: IntelContext, token: str, pools: dict[str, PoolInfo], token_amount: int = 10 ** 18) -> tuple[bool | None, str]:
    """Try V4Quoter.quoteExactInputSingle selling ``token_amount`` on the deepest known pool."""
    quoters = [ctx.config.get("contracts.v4_quoter")] + list(ctx.config.get("contracts.v4_quoter_fallbacks", []))
    quoters = [q for q in quoters if q]
    if not quoters:
        return None, "no quoter configured"
    last_err = ""
    for pool in pools.values():
        key = (pool.currency0, pool.currency1, pool.fee or 0, pool.tick_spacing or 0, pool.hooks or ZERO_ADDRESS)
        zero_for_one = pool.token_is_currency0  # selling token: token->quote
        data = encode_call(V4_QUOTE_EXACT_INPUT_SINGLE, [(key, zero_for_one, token_amount, b"")])
        for q in quoters:
            try:
                out = await ctx.rpc.call(q, data)
                amount_out, _gas = decode(["uint256", "uint256"], out)
                if amount_out > 0:
                    return True, f"sell quote ok via {q[:10]} on pool {pool.pair_id[:10]} (out={amount_out})"
                last_err = "zero output"
            except Exception as exc:
                last_err = str(exc)[:80]
                continue
    return (False if "revert" in last_err.lower() else None), last_err or "no result"


def latest_security(ctx: IntelContext, token: str, as_of_ts: int) -> dict[str, Any] | None:
    """Latest persisted check set not after ``as_of_ts`` (point-in-time)."""
    row = ctx.db.query_one("SELECT MAX(ts) AS t FROM contract_security WHERE chain_id=? AND token_address=? AND ts<=?", (ctx.chain_id, token.lower(), as_of_ts))
    if row is None or row["t"] is None:
        return None
    rows = ctx.db.query("SELECT check_name, status, detail FROM contract_security WHERE chain_id=? AND token_address=? AND ts=?", (ctx.chain_id, token.lower(), row["t"]))
    checks = {r["check_name"]: {"status": r["status"], "detail": r["detail"]} for r in rows}
    worst = "PASS"
    for c in checks.values():
        if STATUS_ORDER[c["status"]] > STATUS_ORDER[worst]:
            worst = c["status"]
    return {"ts": int(row["t"]), "overall": worst, "checks": checks, "fails": [k for k, v in checks.items() if v["status"] == "FAIL"], "warns": [k for k, v in checks.items() if v["status"] == "WARN"], "unknowns": [k for k, v in checks.items() if v["status"] == "UNKNOWN"]}
