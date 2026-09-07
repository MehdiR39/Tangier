"""Command line entry point: ``python -m intel <command>``."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from typing import Any

from intel import MODEL_VERSION, __version__
from intel.context import IntelContext
from intel.logging_setup import setup_logging
from intel.settings import PROJECT_DIR, Settings
from intel.utils.timeutil import now_ts, to_iso

log = logging.getLogger("intel.cli")


def _ctx(args: argparse.Namespace) -> IntelContext:
    overrides: dict[str, Any] = {}
    if getattr(args, "db", None):
        overrides["db_path"] = args.db
    if getattr(args, "dry_run", False):
        overrides["telegram_dry_run"] = True
    settings = Settings.load(**overrides)
    setup_logging(settings.logs_dir, settings.log_level)
    return IntelContext.build(settings)


def _json(obj: Any) -> None:
    print(json.dumps(obj, indent=1, default=lambda o: getattr(o, "as_dict", lambda: str(o))()))


async def cmd_run(args: argparse.Namespace) -> int:
    from intel.engines.scheduler import Runtime

    ctx = _ctx(args)
    rt = Runtime(ctx)
    try:
        await rt.run(portfolio=not args.scanner_only, scanner=not args.portfolio_only, once=args.once)
    finally:
        await rt.close()
    return 0


async def cmd_backfill(args: argparse.Namespace) -> int:
    from intel.engines.pipeline import TokenPipeline
    from intel.alerts.dedup import AlertDeduper
    from intel.ingest.pools import load_pools
    from intel.metrics.pricing import QuotePricer

    ctx = _ctx(args)
    pipeline = TokenPipeline(ctx, QuotePricer(ctx), AlertDeduper(ctx.db, ctx.config.section("alerts"), ctx.chain_id), None)
    tokens = [args.token.lower()] if args.token else [p["address"] for p in ctx.config.portfolio_positions]
    try:
        for t in tokens:
            await pipeline.ensure_token(t, label=None, is_portfolio=not args.token)
            agg = await pipeline.refresh_market(t)
            total = 0
            while True:
                stats = await pipeline.ingest_onchain(t, agg, deep=True, max_blocks=args.blocks)
                total += stats.get("transfers", 0)
                log.info("backfill %s: +%d transfers, backlog %d blocks", t[:10], stats.get("transfers", 0), stats.get("backlog_blocks", 0))
                if stats.get("backlog_blocks", 0) <= 0 or args.once:
                    break
            back = await pipeline.backfill_history(t)
            log.info("backward backfill %s: %s", t[:10], back)
            await pipeline.maybe_refresh_security(t, load_pools(ctx, t), force=True)
            print(f"{t}: {total} new transfers forward; backward={back.get('status')} (+{back.get('transfers', 0)} transfers, {back.get('trades', 0)} trades); holders={back.get('holder_count', stats.get('holders'))}")
    finally:
        await ctx.close()
    return 0


async def cmd_evaluate(args: argparse.Namespace) -> int:
    from intel.engines.pipeline import TokenPipeline
    from intel.alerts.dedup import AlertDeduper
    from intel.alerts.telegram import TelegramSender
    from intel.metrics.pricing import QuotePricer

    ctx = _ctx(args)
    sender = TelegramSender(ctx.settings)
    pipeline = TokenPipeline(ctx, QuotePricer(ctx), AlertDeduper(ctx.db, ctx.config.section("alerts"), ctx.chain_id), sender)
    try:
        label = args.label or ctx.db.scalar("SELECT symbol FROM tokens WHERE chain_id=? AND address=?", (ctx.chain_id, args.token.lower())) or args.token[:10]
        r = await pipeline.process(args.token, label, is_portfolio=args.portfolio, deep=not args.shallow, force_security=args.refresh_security)
        m = r["metrics"]
        out = {
            "token": r["token"], "label": label, "state": r["decision"].state, "action": r["decision"].action, "reason": r["decision"].reason,
            "prev_state": r["prev_state"], "scores": r["scores"].as_dict(), "hard_filters": r["hard_filters"].as_dict(), "alerts": r.get("alerts"), "ingest": r.get("ingest"),
            "market": {k: m.get(k) for k in ("price_usd", "market_cap", "fdv", "liquidity_usd", "volume_24h", "token_age_seconds", "launchpad")},
            "returns": m.get("returns"), "asymmetry": m.get("asymmetry"), "launch": {k: v for k, v in (m.get("launch") or {}).items() if k != "params"},
            "holders": m.get("holders"), "concentration": m.get("concentration"), "clusters": m.get("clusters"), "whales": m.get("whales"),
            "trading_quality_24h": m.get("trading_quality", {}).get("24h"), "liquidity": m.get("liquidity"), "price_impact": m.get("price_impact"),
            "security": m.get("security"), "narrative": m.get("narrative"), "smart_money": m.get("smart_money"), "quality_flags": m.get("quality_flags"),
        }
        _json(out)
    finally:
        await sender.close()
        await ctx.close()
    return 0


async def cmd_status(args: argparse.Namespace) -> int:
    from intel.health import HealthState

    ctx = _ctx(args)
    try:
        _json(HealthState(ctx).status_detail())
    finally:
        await ctx.close()
    return 0


async def cmd_alerts(args: argparse.Namespace) -> int:
    ctx = _ctx(args)
    try:
        rows = ctx.db.query("SELECT ts, severity, kind, title, action, sent, suppress_reason FROM alerts ORDER BY id DESC LIMIT ?", (args.last,))
        for r in rows:
            print(f"{to_iso(r['ts'])} {r['severity']:<9} {r['kind']:<24} sent={r['sent']} {r['title']}  {r['action']}  {r['suppress_reason'] or ''}")
    finally:
        await ctx.close()
    return 0


async def cmd_telegram_test(args: argparse.Namespace) -> int:
    from intel.alerts.telegram import TelegramSender

    ctx = _ctx(args)
    sender = TelegramSender(ctx.settings)
    try:
        ok, mid, err = await sender.send(f"✅ <b>Tangier Intel</b> {__version__} online\nmodel {MODEL_VERSION}\n{to_iso(now_ts())}")
        print("sent" if ok else f"failed: {err}", mid or "")
    finally:
        await sender.close()
        await ctx.close()
    return 0 if ok else 1


async def cmd_digest(args: argparse.Namespace) -> int:
    from intel.alerts.telegram import TelegramSender
    from intel.engines.digest import build_digest, send_digest

    ctx = _ctx(args)
    sender = TelegramSender(ctx.settings)
    try:
        if args.print_only:
            print(build_digest(ctx))
            return 0
        ok, err = await send_digest(ctx, sender, force=True)
        print("digest sent" if ok else f"digest failed: {err}")
        return 0 if ok else 1
    finally:
        await sender.close()
        await ctx.close()


async def cmd_backtest(args: argparse.Namespace) -> int:
    from intel.backtest.forward import replay_scores, run_backtest

    ctx = _ctx(args)
    try:
        if args.replay:
            n = await replay_scores(ctx, args.replay, step_seconds=args.step)
            print(f"replayed {n} historical evaluations for {args.replay}")
        summary = run_backtest(ctx, token=args.token, since_ts=args.since, out_dir=args.out or os.path.join(PROJECT_DIR, "results"))
        _json(summary)
    finally:
        await ctx.close()
    return 0


async def cmd_preview_alert(args: argparse.Namespace) -> int:
    """Render (and optionally send) the current state of a token as an alert, bypassing dedup.
    Used to show the message format; ingestion is skipped (evaluation only)."""
    from intel.alerts.dedup import AlertDeduper
    from intel.alerts.format import format_alert
    from intel.alerts.rules import AlertCandidate
    from intel.alerts.telegram import TelegramSender
    from intel.engines.pipeline import TokenPipeline
    from intel.ingest.pools import load_pools
    from intel.metrics.pricing import QuotePricer

    ctx = _ctx(args)
    sender = TelegramSender(ctx.settings)
    try:
        token = args.token.lower()
        is_portfolio = ctx.db.query_one("SELECT 1 FROM portfolio_positions WHERE chain_id=? AND token_address=? AND active=1", (ctx.chain_id, token)) is not None
        pipeline = TokenPipeline(ctx, QuotePricer(ctx), AlertDeduper(ctx.db, ctx.config.section("alerts"), ctx.chain_id), None)
        label = ctx.db.scalar("SELECT COALESCE(label, symbol) FROM portfolio_positions p LEFT JOIN tokens t ON t.address=p.token_address WHERE p.token_address=?", (token,)) or ctx.db.scalar("SELECT symbol FROM tokens WHERE address=?", (token,)) or token[:10]
        r = await pipeline.evaluate(token, label, is_portfolio=is_portfolio, deep=False, pools=load_pools(ctx, token), as_of_ts=now_ts())
        m = r["metrics"]
        m["_is_portfolio"] = is_portfolio
        d = r["decision"]
        c = AlertCandidate("state_change", "IMPORTANT" if d.state in ("DISTRIBUTION", "BREAKOUT") else "WATCH", f"{label} — {d.state}", d.reason, d.action, f"preview:{token}", token, label)
        text = format_alert(c, m, r["scores"], d, prev_state=r["prev_state"], prev_moonshot=r["prev_moonshot"], token_url=f"https://dexscreener.com/{ctx.settings.dexscreener_chain}/{token}", is_portfolio=is_portfolio)
        print(text)
        if args.send:
            ok, mid, err = await sender.send("🧪 Exemple du nouveau format\n\n" + text)
            print("sent" if ok else f"failed: {err}")
    finally:
        await sender.close()
        await ctx.close()
    return 0


async def cmd_orders(args: argparse.Namespace) -> int:
    """What the executor did, or would have done. Reads the journal; sends nothing."""
    ctx = _ctx(args)
    try:
        from intel.execution.safety import Limits
        from intel.execution.signer import signer_address

        mode = str(ctx.config.get("execution.mode", "dry_run"))
        lim = Limits.from_config(ctx)
        addr = signer_address()
        print(f"mode : {mode}" + ("  ← AUCUN ORDRE N'EST ENVOYÉ" if mode != "live" else "  ← LES ORDRES PARTENT RÉELLEMENT"))
        print(f"portefeuille signataire : {addr or 'aucune clé configurée'}")
        print(f"plafonds : {lim.max_eur_per_order:.0f} € par ordre · {lim.max_eur_per_day:.0f} € et {lim.max_orders_per_day} ordres par jour · "
              f"{lim.max_open_positions} positions · slippage {lim.max_slippage_pct:.1f} %"
              + ("  · ARRÊT D'URGENCE ACTIF" if lim.kill_switch else ""))
        n, eur = __import__("intel.execution.safety", fromlist=["spent_today"]).spent_today(ctx)
        print(f"engagé aujourd'hui : {eur:.0f} € sur {n} ordres\n")
        rows = ctx.db.query("SELECT * FROM executions WHERE chain_id=? ORDER BY id DESC LIMIT ?", (ctx.chain_id, args.last))
        if not rows:
            print("aucun ordre au journal pour l'instant")
            return 0
        for r in rows:
            d = dict(r)
            head = f"{to_iso(d['ts'])} {d['kind']:<10} {(d['label'] or d['token_address'][:10]):<14} {d['status']:<10}"
            if d["status"] == "REFUSED":
                print(f"{head} refusé : {d['refused_reason']}")
            else:
                print(f"{head} {d['size_eur'] or 0:.0f} € · min reçu {d['min_amount_out']} · slippage {d['slippage_pct'] or 0:.2f} %"
                      + (f" · tx {d['tx_hash']}" if d.get("tx_hash") else ""))
        agg = ctx.db.query("SELECT status, COUNT(*) c FROM executions WHERE chain_id=? GROUP BY status ORDER BY c DESC", (ctx.chain_id,))
        print("\n" + " · ".join(f"{r['status']} {r['c']}" for r in agg))
    finally:
        await ctx.close()
    return 0


async def cmd_scorecard(args: argparse.Namespace) -> int:
    """Price outcome after each sent alert (1h/6h/24h) and per-kind summary."""
    from intel.backtest.scorecard import alert_outcomes, format_scorecard

    ctx = _ctx(args)
    try:
        outcomes = alert_outcomes(ctx, since_ts=now_ts() - int(args.days) * 86400)
        for o in outcomes:
            print(f"{to_iso(o['ts'])} {o['symbol']:<12} {o['kind']:<24} {o['action']:<12} " + " ".join(f"{h}={('%+.0f%%' % (o['ret_' + h] * 100)) if o.get('ret_' + h) is not None else '   ?  '}" for h in ("1h", "6h", "24h")) + (f" now={o['ret_now']:+.0%}" if o.get("ret_now") is not None else ""))
        print()
        for l in format_scorecard(outcomes, args.horizon):
            print(l)
    finally:
        await ctx.close()
    return 0


async def cmd_backtest_history(args: argparse.Namespace) -> int:
    """Rebuild past prices from on-chain swaps, then replay the rules on that history."""
    from intel.backtest.history import (Rules, build_history_batch, candidate_pools, enumerate_launches,
                                        load_series, monte_carlo)
    from intel.providers.dexscreener import normalize_pair

    ctx = _ctx(args)
    try:
        if args.cohorts:
            per_day = max(1, args.sample // max(1, int(args.days)))
            pools = await enumerate_launches(ctx, days=int(args.days), per_day=per_day)
            print(f"{len(pools)} tokens échantillonnés directement sur la chaîne ({per_day} par jour sur {int(args.days)} jours)")
        else:
            pools = candidate_pools(ctx, min_age_hours=args.min_age_hours, max_age_hours=args.days * 24, limit=args.sample)
            print(f"{len(pools)} tokens sélectionnés dans les pools connus (créés entre {args.days * 24:.0f} h et {args.min_age_hours:.0f} h avant maintenant)")
        # One log query carries many pools: measured 0.004 s per pool grouped against 2.5 s one at
        # a time. Progress is reported per slice, since a slice is now the unit of work.
        step = max(1, int(args.batch))
        done = 0
        for i in range(0, len(pools), step * 4):
            part = pools[i: i + step * 4]
            r = await build_history_batch(ctx, part, batch=step)
            done += len(part)
            print(f"  reconstruit {done}/{len(pools)} · {r['swaps']:,} swaps en {r['requests']} requêtes, {r['seconds']}s"
                  + (f" · {r['skipped']} ignorés" if r.get("skipped") else "")
                  + (f" · {r['failed_groups']} lots en échec" if r.get("failed_groups") else ""))
        quotes = {r["quote_address"] for r in ctx.db.query("SELECT DISTINCT quote_address FROM history_meta WHERE chain_id=?", (ctx.chain_id,)) if r["quote_address"]}
        quote_usd: dict[str, float] = {}
        for q in quotes:
            meta = ctx.config.quote_assets.get(q)
            if meta and meta.get("kind") == "stable":
                quote_usd[q] = float(meta.get("usd", 1.0))
        # Native ETH has no contract and no DexScreener entry: price it through its wrapped twin.
        wrapped = next((a for a, m in ctx.config.quote_assets.items() if m.get("kind") == "native_wrapped"), None)
        natives = [q for q in quotes if (ctx.config.quote_assets.get(q) or {}).get("kind") == "native"]
        missing = [q for q in quotes if q not in quote_usd and q not in natives]
        if natives and wrapped and wrapped not in missing and wrapped not in quote_usd:
            missing.append(wrapped)
        for i in range(0, len(missing), 30):
            for pr in await ctx.dex.tokens(missing[i: i + 30]):
                np = normalize_pair(pr)
                if np.get("price_usd"):
                    quote_usd[np["base_address"]] = float(np["price_usd"])
        for q in natives:
            if wrapped and quote_usd.get(wrapped):
                quote_usd[q] = quote_usd[wrapped]
        tokens = [r["token_address"] for r in ctx.db.query("SELECT DISTINCT token_address FROM history_meta WHERE chain_id=?", (ctx.chain_id,))]
        series = load_series(ctx, tokens, quote_usd)
        span_h = 0.0
        if series:
            lo = min(s[0][0] for s in series.values())
            hi = max(s[-1][0] for s in series.values())
            span_h = (hi - lo) / 3600
        print(f"\nhistorique exploitable : {len(series)} tokens · {sum(len(s) for s in series.values()):,} points · fenêtre {span_h:.0f} h")
        if not series:
            return 1
        variants = [
            Rules("moitié x3 · sortie 18 h · stop large -75 % (règle actuelle)", moonbag=3.0, stop=0.75, trail=0.70, timeout_h=18),
            Rules("moitié x3 · garder le reste, aucune sortie", moonbag=3.0, stop=None, trail=None, timeout_h=None),
            Rules("garder jusqu'au bout, aucune règle", moonbag=None, stop=None, trail=None, timeout_h=None),
            Rules("stop -50 % (classique)", moonbag=None, stop=0.5, trail=None, timeout_h=None),
            Rules("moitié x3 · stop suiveur -35 % (ancienne règle)", moonbag=3.0, stop=0.5, trail=0.35, timeout_h=None),
            Rules("sortie 6 h", moonbag=None, timeout_h=6),
            Rules("sortie 18 h", moonbag=None, timeout_h=18),
        ]
        print(f"\n=== RÈGLES DE SORTIE · {args.capital:.0f} € · lignes de {args.line:.0f} € · {args.draws} tirages · frais 2 % A/R · achat au hasard ===")
        for rules in variants:
            r = monte_carlo(series, rules, capital=args.capital, line=args.line, draws=args.draws)
            print(f"  {r['rule']:56s} médiane {r['median']:>6.0f} € · moyenne {r['mean']:>7.0f} € · gagnant {r['win_rate']:>4.0%} · pire {r['worst']:>5.0f} € · meilleur {r['best']:>8.0f} € · {r['lines']:.0f} lignes")

        base = Rules("selection", moonbag=3.0, stop=0.75, trail=0.70, timeout_h=18)
        pickers = [("random", "au hasard (référence)"), ("deep", "la plus liquide"), ("thin", "la moins liquide"),
                   ("momentum", "la plus en hausse"), ("flat", "celle qui n'a pas encore bougé"),
                   ("young", "la plus récente"), ("active", "la plus échangée"), ("liq_growth", "liquidité qui monte le plus vite")]
        # A selection rule can only show up when candidates outnumber free slots. With a full-size
        # book every eligible token is bought and all criteria give the identical result, so the
        # comparison runs on a deliberately narrow book and is reported per line.
        sel_slots = max(1, int(args.sel_lines))
        sel_capital = args.line * sel_slots
        print(f"\n=== CHOIX DU TOKEN · carnet étroit de {sel_slots} ligne(s) pour forcer un vrai choix · mêmes tirages ({args.draws}) ===")
        rows = []
        for kind, label in pickers:
            r = monte_carlo(series, base, capital=sel_capital, line=args.line, draws=args.draws, picker=kind)
            rows.append((label, r))
        ref = next(r for lbl, r in rows if r["picker"] == "random")
        for label, r in sorted(rows, key=lambda x: -x[1]["mean"]):
            delta = (r["mean"] - ref["mean"]) / sel_capital
            print(f"  {label:34s} par ligne : médiane x{r['median'] / sel_capital:>5.2f} · moyenne x{r['mean'] / sel_capital:>6.2f} ({delta:+.2f} vs hasard) · gagnant {r['win_rate']:>4.0%} · meilleur x{r['best'] / sel_capital:>7.2f}")
        comp = ref["choices"]
        print(f"\n  candidats disponibles à chaque achat : {comp:.1f}")
        if comp < 1.5:
            print("  -> pas de choix à faire : tout ce qui passe le filtre est acheté, aucun critère ne peut se distinguer.")
    finally:
        await ctx.close()
    return 0


async def cmd_snapshot(args: argparse.Namespace) -> int:
    """Consistent copy of the live database for analysis from another process/OS."""
    ctx = _ctx(args)
    try:
        dest = args.out or os.path.join(os.path.dirname(ctx.settings.backup_dir.rstrip("/\\")), "intel_snapshot.sqlite")
        path = ctx.db.backup_to(dest)
        ok, msg = ctx.db.quick_check()
        print(f"snapshot written: {path} (live db check: {msg})")
        return 0 if ok else 1
    finally:
        await ctx.close()


async def cmd_import_tables(args: argparse.Namespace) -> int:
    """Copy rows from another intel database (e.g. a recovery file) into the live one.

    Rows are inserted with INSERT OR IGNORE on the intersection of column names, so partial
    or older schemas import cleanly; nothing is overwritten.
    """
    import sqlite3

    ctx = _ctx(args)
    try:
        src = sqlite3.connect(f"file:{args.src}?mode=ro", uri=True)
        src.row_factory = sqlite3.Row
        wanted = [t.strip() for t in (args.tables or "").split(",") if t.strip()] or [r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name!='schema_migrations'")]
        total = 0
        for t in wanted:
            try:
                live_cols = [r["name"] for r in ctx.db.query(f"PRAGMA table_info({t})")]
                src_cols = [r[1] for r in src.execute(f"PRAGMA table_info({t})")]
            except Exception as exc:  # noqa: BLE001
                print(f"{t}: skipped ({exc})")
                continue
            cols = [c for c in src_cols if c in live_cols]
            if not cols:
                print(f"{t}: no matching columns, skipped")
                continue
            rows = [tuple(r[c] for c in cols) for r in src.execute(f"SELECT {', '.join(cols)} FROM {t}")]
            with ctx.db.transaction():
                before = ctx.db._conn.total_changes
                ctx.db.executemany(f"INSERT OR IGNORE INTO {t} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})", rows)
                n = ctx.db._conn.total_changes - before
            total += n
            print(f"{t}: {n}/{len(rows)} rows imported")
        src.close()
        print(f"total imported: {total}")
    finally:
        await ctx.close()
    return 0


async def cmd_migrate(args: argparse.Namespace) -> int:
    ctx = _ctx(args)
    try:
        applied = ctx.db.migrate()
        print("applied:", applied or "nothing (up to date)")
    finally:
        await ctx.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="intel", description="Tangier Intel — read-only crypto intelligence (Robinhood Chain)")
    p.add_argument("--db", help="sqlite path (default: INTEL_DB_PATH or data/intel.sqlite)")
    p.add_argument("--dry-run", action="store_true", help="never send Telegram messages (log only)")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run engines continuously (portfolio watcher + scanner)")
    r.add_argument("--once", action="store_true")
    r.add_argument("--portfolio-only", action="store_true")
    r.add_argument("--scanner-only", action="store_true")
    r.set_defaults(fn=cmd_run)

    b = sub.add_parser("backfill", help="ingest historical transfers/swaps for portfolio tokens (or --token)")
    b.add_argument("--token")
    b.add_argument("--blocks", type=int, default=300_000, help="blocks per batch")
    b.add_argument("--once", action="store_true", help="one batch only")
    b.set_defaults(fn=cmd_backfill)

    e = sub.add_parser("evaluate", help="run the full pipeline once for a token and print metrics/scores")
    e.add_argument("--token", required=True)
    e.add_argument("--label")
    e.add_argument("--portfolio", action="store_true")
    e.add_argument("--shallow", action="store_true")
    e.add_argument("--refresh-security", action="store_true", help="re-run contract security checks now")
    e.set_defaults(fn=cmd_evaluate)

    s = sub.add_parser("status", help="health + engine + provider status")
    s.set_defaults(fn=cmd_status)

    a = sub.add_parser("alerts", help="list recent alerts")
    a.add_argument("--last", type=int, default=30)
    a.set_defaults(fn=cmd_alerts)

    t = sub.add_parser("telegram-test", help="send a test message")
    t.set_defaults(fn=cmd_telegram_test)

    dg = sub.add_parser("digest", help="send (or print) the daily summary now")
    dg.add_argument("--print-only", action="store_true")
    dg.set_defaults(fn=cmd_digest)

    bt = sub.add_parser("backtest", help="forward-return / survival evaluation of stored scores")
    bt.add_argument("--token")
    bt.add_argument("--since", type=int, help="unix ts")
    bt.add_argument("--out")
    bt.add_argument("--replay", help="token: recompute historical scores point-in-time before evaluating")
    bt.add_argument("--step", type=int, default=3600)
    bt.set_defaults(fn=cmd_backtest)

    pv = sub.add_parser("preview-alert", help="render the current state of a token as an alert (optionally send it)")
    pv.add_argument("--token", required=True)
    pv.add_argument("--send", action="store_true")
    pv.set_defaults(fn=cmd_preview_alert)

    od = sub.add_parser("orders", help="the execution journal: orders built, refused or sent")
    od.add_argument("--last", type=int, default=25)
    od.set_defaults(fn=cmd_orders)

    sc = sub.add_parser("scorecard", help="what prices did after each sent alert")
    sc.add_argument("--days", type=int, default=3)
    sc.add_argument("--horizon", default="24h")
    sc.set_defaults(fn=cmd_scorecard)

    bh = sub.add_parser("backtest-history", help="rebuild past prices from on-chain swaps and replay the rules (real backtest, no waiting)")
    bh.add_argument("--days", type=float, default=5.0, help="look back this many days for token launches")
    bh.add_argument("--min-age-hours", type=float, default=12.0, help="each token must have at least this much forward history")
    bh.add_argument("--sample", type=int, default=40)
    bh.add_argument("--capital", type=float, default=400.0)
    bh.add_argument("--line", type=float, default=20.0)
    bh.add_argument("--draws", type=int, default=100)
    bh.add_argument("--sel-lines", type=int, default=2, help="book size used only for the selection comparison; small on purpose so criteria compete")
    bh.add_argument("--batch", type=int, default=50, help="pools per log query; the node accepts a list of pool ids")
    bh.add_argument("--cohorts", action="store_true", help="sample launches directly from the chain, one cohort per past day (recommended)")
    bh.set_defaults(fn=cmd_backtest_history)

    sn = sub.add_parser("snapshot", help="write a consistent copy of the live DB (read it from the host, never the live file)")
    sn.add_argument("--out")
    sn.set_defaults(fn=cmd_snapshot)

    im = sub.add_parser("import-tables", help="import rows from another intel database (recovery / migration between hosts)")
    im.add_argument("--src", required=True)
    im.add_argument("--tables", help="comma-separated list (default: all)")
    im.set_defaults(fn=cmd_import_tables)

    m = sub.add_parser("migrate", help="apply pending DB migrations")
    m.set_defaults(fn=cmd_migrate)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(args.fn(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
