"""Turn a decision into an order: pick the pool, price it, check it, journal it.

Everything here runs identically in dry run and live; the only difference is the last step. That
is deliberate — a dry run that skips the hard parts proves nothing. In dry run the order is
built in full, priced against real pool state, put through the safety envelope and written to the
journal with status ``BUILT``; only the broadcast is skipped.

A decision is acted on once. The journal carries a unique index on ``decision_id``, so a restart
or an overlapping cycle cannot submit the same order twice.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from intel import MODEL_VERSION
from intel.context import IntelContext
from intel.execution import orders as ord_mod
import dataclasses

from intel.chain.uniswap_v4 import virtual_reserves
from intel.execution import safety
from intel.execution.quote import latest_pool_state, quote_from_pool
from intel.utils.timeutil import now_ts

log = logging.getLogger(__name__)


def pending_decisions(ctx: IntelContext, *, limit: int = 20) -> list[dict[str, Any]]:
    """Decisions with no journal entry yet, oldest first so the book stays in order.

    Les decisions Solana sont exclues : elles portent le meme `chain_id` faute de mieux, mais elles
    ne se traitent pas ici -- il n existe aucun pool Uniswap pour un jeton Solana. Le 08/09/2026 a
    17h02 cet executeur a ramasse une decision Solana, l a refusee (« aucun pool utilisable ») et a
    ecrit sa ligne de journal ; le carnet Solana avait deja envoye l ordre en chaine, et son
    ecriture a heurte l unicite (chain_id, decision_id). Resultat : BIPOLAR achete pour 20,20 EUR,
    aucune position pour le gerer, personne pour le revendre.
    """
    return [dict(r) for r in ctx.db.query(
        "SELECT d.* FROM decisions d LEFT JOIN executions e ON e.chain_id=d.chain_id AND e.decision_id=d.id "
        "WHERE d.chain_id=? AND e.id IS NULL AND (d.model_version IS NULL OR d.model_version NOT LIKE 'sol-%') "
        "ORDER BY d.id ASC LIMIT ?",
        (ctx.chain_id, limit),
    )]


def choose_pool(ctx: IntelContext, token: str, allowed_quotes: tuple[str, ...]) -> dict[str, Any] | None:
    """The pool to trade through: an allowed quote, and the most recent activity.

    Recency beats headline depth here. A pool that has not traded in an hour cannot be priced
    from its last state, and a stale quote is worse than a shallower live one.
    """
    rows = ctx.db.query(
        "SELECT p.pair_id, p.token_address, p.quote_address, p.currency0, p.currency1, p.fee, p.tick_spacing, p.hooks, "
        "       (SELECT MAX(block_number) FROM swap_events s WHERE s.chain_id=p.chain_id AND s.pair_id=p.pair_id) last_block "
        "FROM pairs p WHERE p.chain_id=? AND p.token_address=? AND p.currency0 IS NOT NULL AND p.quote_address IS NOT NULL",
        (ctx.chain_id, token),
    )
    usable = [dict(r) for r in rows if (r["quote_address"] or "").lower() in allowed_quotes and r["last_block"]]
    if not usable:
        return None
    return max(usable, key=lambda r: r["last_block"])


def quote_price_usd(ctx: IntelContext, quote_address: str) -> float | None:
    """What one unit of the quote asset is worth in dollars.

    Native ETH has no contract and therefore no market snapshot of its own; it is priced through
    its wrapped twin, which trades and is observed like any other token.
    """
    addr = quote_address.lower()
    meta = ctx.config.quote_assets.get(addr) or {}
    if meta.get("kind") == "stable":
        return float(meta.get("usd", 1.0))
    if meta.get("kind") == "native":
        wrapped = next((a for a, m in ctx.config.quote_assets.items() if m.get("kind") == "native_wrapped"), None)
        addr = wrapped or addr
    row = ctx.db.query_one(
        "SELECT price_usd FROM token_snapshots WHERE chain_id=? AND token_address=? AND price_usd IS NOT NULL ORDER BY ts DESC LIMIT 1",
        (ctx.chain_id, addr),
    )
    price = float(row["price_usd"]) if row and row["price_usd"] else 0.0
    return price if price > 0 else None


def _amount_in_raw(ctx: IntelContext, quote_address: str, size_eur: float, eur_usd: float) -> int | None:
    """Convert an order size in euros into raw units of the quote asset."""
    decimals = (ctx.config.quote_assets.get(quote_address.lower()) or {}).get("decimals")
    price_usd = quote_price_usd(ctx, quote_address)
    if decimals is None or not price_usd:
        return None
    return int(size_eur * eur_usd / price_usd * (10 ** int(decimals)))


def held_units(ctx: IntelContext, token: str, d: dict[str, Any], *, eur_usd: float) -> float | None:
    """How many tokens the book believes we hold, in human units.

    Derived from the position that the decision refers to: the euros committed at the entry price,
    halved once part of it has already been sold. When execution goes live this is replaced by the
    signer wallet's on-chain balance, which is the only figure that can be trusted to settle.
    """
    # Le carnet de la decision, et lui seul : une vente se dimensionne sur NOTRE ligne. Une ligne
    # sans version est du scanner (voir carnet.sql) -- sans ce cas, une vente du scanner sur une
    # vieille ligne partait « quantite inconnue » et etait refusee a l aveugle.
    from intel.engines.carnet import SCANNER, prefixe_de
    prefixe = prefixe_de(d.get("model_version"))
    ou = ("(model_version IS NULL OR model_version LIKE ?)" if prefixe == SCANNER
          else "model_version LIKE ?")
    pos = ctx.db.query_one(
        "SELECT size_eur, entry_price, status FROM positions WHERE chain_id=? AND token_address=? "
        "AND status IN ('OPEN','HALF') AND " + ou + " ORDER BY id DESC LIMIT 1",
        (ctx.chain_id, token, prefixe + "%"))
    if pos is None or not pos["entry_price"] or not pos["size_eur"]:
        return None
    units = float(pos["size_eur"]) * eur_usd / float(pos["entry_price"])
    return units * 0.5 if pos["status"] == "HALF" else units


def _journal(ctx: IntelContext, d: dict[str, Any], *, status: str, mode: str, **kw: Any) -> int | None:
    row = {
        "ts": now_ts(), "chain_id": ctx.chain_id, "decision_id": d.get("id"), "token_address": d["token_address"],
        "label": d.get("label"), "kind": d["kind"], "size_eur": d.get("size_eur"), "mode": mode, "status": status,
        "model_version": MODEL_VERSION,
    }
    row.update(kw)
    return ctx.db.insert("executions", row)


def prepare(ctx: IntelContext, d: dict[str, Any], *, limits: safety.Limits, eur_usd: float = 1.08,
            held_raw: int | None = None) -> dict[str, Any]:
    """Build and check one order without sending it. Returns what the journal will record.

    ``held_raw`` is the signer wallet's own token balance in raw units, read on chain by the
    caller when execution is live. A sell sized from the book's estimate instead is off by the
    fee and the impact of the entry, and selling more than the wallet holds reverts after gas.
    """
    token = str(d["token_address"]).lower()
    # A decision is a statement about a moment. Acting on a backlog after a restart would buy a
    # price that no longer exists, so an old decision is dropped rather than executed late.
    is_buy = d["kind"] == safety.BUY
    max_age = int(ctx.config.get("execution.max_decision_age_s", 600))
    age = now_ts() - int(d.get("ts") or 0)
    if is_buy and age > max_age:
        # Only a purchase expires. A sale is an order to get out of a position we already hold, and
        # throwing it away because the engine was busy for ten minutes leaves the book holding the
        # bag with nothing scheduled to sell it -- the same entry rule applied to an exit, for the
        # fourth time today.
        return {"status": "REFUSED", "refused_reason": f"décision vieille de {age // 60} min (> {max_age // 60} min) : elle ne vaut plus"}
    # Selling looks for the pool that pays, whatever it is quoted in -- the whitelist governs what
    # we are willing to SPEND, not how we get out. Same for a shadow decision (paper book on
    # USDG/WETH pools): it is priced through any configured quote, and nothing is ever sent.
    quotes = (tuple(ctx.config.quote_assets.keys())
              if (not is_buy or str(d.get("model_version") or "").startswith("t1-shadow"))
              else limits.allowed_quotes)
    pool = choose_pool(ctx, token, quotes)
    if pool is None:
        return {"status": "REFUSED", "refused_reason": "aucun pool utilisable avec un actif de cotation autorisé"}
    quote_addr = str(pool["quote_address"]).lower()

    if is_buy:
        amount_in = _amount_in_raw(ctx, quote_addr, float(d.get("size_eur") or 0), eur_usd)
        if not amount_in:
            return {"status": "REFUSED", "refused_reason": "taille d'ordre non convertible en unités de cotation"}
    else:
        # What WE hold, never what the chain holds. Reading an observed holder's balance here
        # sized a sell from a whale's bag and produced a 103 352 % price impact (2026-09-04):
        # the book's own position is the only honest source.
        half = d["kind"] == safety.SELL_HALF
        share = 0.5 if half else 1.0
        if held_raw is not None:
            # Integer arithmetic, never a float. A token balance runs past 10^21 raw units, well
            # beyond the 2^53 a float can hold exactly, so `held_raw * 1.0` rounds UP: on
            # 2026-09-07 the book asked to sell 3562110037979391066112 of a balance of
            # 3562110037979390964595 -- a hundred thousandth of a percent too much -- and the chain
            # answered TRANSFER_FROM_FAILED. Four bags worth 18 EUR were written off as
            # "unsellable" for that, and the day was reported 18 EUR worse than it was.
            amount_in = (held_raw // 2) if half else held_raw
        else:
            if str(ctx.config.get("execution.mode", "dry_run")) == "live":
                # The wallet is the only honest source live. Falling back to the book's estimate
                # asks the chain for tokens that may not be there and reverts with
                # TRANSFER_FROM_FAILED, which the book then records as "unsellable".
                return {"status": "REFUSED", "refused_reason": "solde du portefeuille illisible : vente reportée"}
            decimals = ctx.db.scalar("SELECT decimals FROM tokens WHERE chain_id=? AND address=?", (ctx.chain_id, token))
            if decimals is None:
                return {"status": "REFUSED", "refused_reason": "décimales du token inconnues"}
            units = held_units(ctx, token, d, eur_usd=eur_usd)
            if units is None:
                return {"status": "REFUSED", "refused_reason": "quantité détenue inconnue : une vente à l'aveugle est refusée"}
            amount_in = int(units * share * (10 ** int(decimals)))
        if amount_in <= 0:
            return {"status": "REFUSED", "refused_reason": "quantité à vendre nulle"}

    # Direction: we spend the quote to buy the token, and the token to sell it.
    spending = quote_addr if is_buy else token
    zero_for_one = (str(pool["currency0"]).lower() == spending)
    # The pool key is what the chain hashes to find the pool: every field must be the stored one.
    # "fee or 3000" turned the launchpad's dynamic-fee pools (fee = 0) into fee-3000 keys and every
    # such buy died on PoolNotInitialized (2026-09-07). A fee of 0 is a real value; only an absent
    # field is unknown, and an unknown key is refused rather than guessed.
    if pool.get("fee") is None or pool.get("tick_spacing") is None:
        return {"status": "REFUSED", "refused_reason": "clé de pool incomplète (fee ou tick_spacing inconnu)"}
    pool_fee = int(pool["fee"])
    # A dynamic-fee pool reports 0 here while its hook charges what it likes: quote with 1 % so the
    # minimum output is not set from a fee-free price.
    is_t1 = str(d.get("model_version") or "").startswith("t1-")
    check_limits = limits
    if str(d.get("model_version") or "").startswith("t1-shadow"):
        # A shadow decision is measured, never sent. Judging it against the real book's quote
        # whitelist refused every USDG launch (2026-09-07) -- which is precisely the question the
        # paper book exists to answer. Every other ceiling still applies, so the simulation stays
        # comparable to the real book.
        check_limits = dataclasses.replace(limits, allowed_quotes=tuple(ctx.config.quote_assets.keys()))
    if is_t1:
        # The scanner's 20 000 $ floor describes tokens hours old. For a 5 EUR entry at T+1 the
        # relevant question is whether the ticket moves the pool, and 500 $ of quote-side depth
        # keeps that near 1 %; the slippage cap and every daily ceiling still apply unchanged.
        check_limits = dataclasses.replace(
            check_limits, min_quote_liquidity_usd=float(ctx.config.get("t1.min_quote_liquidity_usd", 500.0)),
            max_slippage_pct=float(ctx.config.get("t1.max_slippage_pct", 8.0)))
    # Entry guards must not become exit walls. The staleness, single-tick and impact ceilings all
    # exist to stop us OVERPAYING on the way in; applied to a sell they refuse to let go of a bag
    # (2026-09-07: "dernier échange il y a 82 min", "impact 7.5 % > 3 %") and the only alternative
    # to a costly exit is a worthless one. On the way out the chain's own quote decides, and the
    # minimum output computed from it is what actually protects the trade.
    if is_buy:
        # The quoter's own 3 % ceiling describes a scanner order on an established pool. A T+1 pool
        # is minutes old and a 5 EUR ticket routinely moves it more than that: four of the twenty
        # test tickets died on "impact 3.0 % > 3.0 %" while the book's own ceiling was 8 %.
        # Un achat MANUEL ne subit pas le controle de fraicheur de l etat du pool. Cet etat n est
        # rafraichi que pour les jetons que le scanner ingere ; sur DOGSHIT, hors scanner, il datait
        # de 551 min et l ordre de l operateur du 09/09 23h09 a ete refuse pour un pool qui echangeait
        # toutes les dix secondes (§5.22). L operateur a le graphique sous les yeux et a decide ; et
        # la sortie minimale calculee depuis la cotation protege l echange : un etat perime fait
        # au pire echouer la transaction, jamais surpayer. Meme tolerance que pour les sorties.
        manuel = str(d.get("model_version") or "").startswith("manuel-")
        q = quote_from_pool(ctx, pool_id=pool["pair_id"], zero_for_one=zero_for_one, amount_in=amount_in,
                            fee_pips=pool_fee if pool_fee > 0 else 10_000,
                            max_impact_pct=float(check_limits.max_slippage_pct),
                            **({"max_state_age_s": 7 * 86400} if manuel else {}))
    else:
        q = quote_from_pool(ctx, pool_id=pool["pair_id"], zero_for_one=zero_for_one, amount_in=amount_in,
                            fee_pips=pool_fee if pool_fee > 0 else 10_000,
                            max_state_age_s=7 * 86400, max_order_fraction=1.0,
                            max_impact_pct=float(ctx.config.get("execution.max_sell_impact_pct", 60.0)))
    if not q.usable:
        return {"status": "REFUSED", "refused_reason": "cotation impossible : " + "; ".join(q.reasons),
                "amount_in": str(amount_in), "quote_address": quote_addr}

    liq_usd = ctx.db.scalar(
        "SELECT liquidity_usd FROM token_snapshots WHERE chain_id=? AND token_address=? AND liquidity_usd IS NOT NULL ORDER BY ts DESC LIMIT 1",
        (ctx.chain_id, token))
    liq_source = "snapshot"
    if liq_usd is None:
        # A pool sixty seconds old has no market snapshot yet, so the first three T+1 decisions
        # (2026-09-06, all quoted at 0.1-0.2 % impact) were refused as "liquidité inconnue". The
        # depth IS known: the same pool state the quote was just computed from. Quote-side virtual
        # reserve, priced in dollars -- an upper bound on depth, so the floor below stays strict.
        state = latest_pool_state(ctx, pool["pair_id"])
        px = quote_price_usd(ctx, quote_addr)
        qdec = (ctx.config.quote_assets.get(quote_addr) or {}).get("decimals")
        if state and px and qdec is not None:
            try:
                r0, r1 = virtual_reserves(int(state["liquidity"]), int(state["sqrt_price_x96"]))
                quote_is_c0 = str(pool["currency0"]).lower() == quote_addr
                liq_usd = (r0 if quote_is_c0 else r1) / (10 ** int(qdec)) * float(px)
                liq_source = "pool_state"
            except (TypeError, ValueError, KeyError):
                liq_usd = None
    verdict = safety.check(ctx, {"kind": d["kind"], "token": token, "quote": quote_addr,
                                "size_eur": d.get("size_eur"), "slippage_pct": q.price_impact_pct,
                                "quote_liquidity_usd": liq_usd,
                                "model_version": d.get("model_version"),
                                # L enveloppe quotidienne appartient au CARNET qui passe l ordre.
                                # Elle etait comptee sous la version de l executeur, donc le carnet
                                # du scanner et les ordres manuels partageaient la meme : le
                                # scanner pouvait epuiser le budget de l operateur sans qu il
                                # comprenne pourquoi son achat Telegram est refuse (§5.25).
                                "journal_version": d.get("model_version") or MODEL_VERSION},
                               check_limits)
    if is_t1:
        log.info("t1 ordre %s · profondeur %s %s · impact %.2f %% · %s", token[:10],
                 f"{liq_usd:,.0f} $" if liq_usd is not None else "inconnue", liq_source,
                 q.price_impact_pct, "ok" if verdict.allowed else verdict.why)
    if not verdict.allowed:
        return {"status": "REFUSED", "refused_reason": verdict.why, "amount_in": str(amount_in),
                "quote_address": quote_addr, "slippage_pct": q.price_impact_pct}

    key = ord_mod.PoolKey(currency0=pool["currency0"], currency1=pool["currency1"],
                          fee=pool_fee, tick_spacing=int(pool["tick_spacing"]),
                          hooks=pool.get("hooks") or "0x" + "00" * 20)
    # A T+1 pool moves several percent between the quote and the block that includes us; a 0.5 %
    # tolerance would only ever buy the pumps that have already stalled. The tolerance is the
    # book's own ceiling for these orders (t1.max_slippage_pct), never the scanner's.
    # Leaving is not entering. A sale refused for a minimum set too high (ROBIN, 2026-09-07,
    # V4TooLittleReceived on a pool that was still trading) is a position abandoned for nothing,
    # and the chain quote below already sets that minimum from what the pool really returns.
    if is_t1 and not is_buy:
        slippage = float(ctx.config.get("t1.sell_slippage_pct", 25.0))
    elif is_t1:
        slippage = float(check_limits.max_slippage_pct)
    else:
        slippage = min(limits.max_slippage_pct, max(0.5, q.price_impact_pct * 2))
    order = ord_mod.build_swap(
        key=key, token=token, quote=quote_addr, kind=d["kind"], zero_for_one=zero_for_one, amount_in=amount_in,
        quoted_amount_out=q.amount_out, slippage_pct=slippage,
        router=str(ctx.config.get("execution.router")), deadline_s=int(ctx.config.get("execution.deadline_seconds", 120)),
        native_quote=(quote_addr == "0x" + "00" * 20),
    )
    return {"status": "BUILT", "order": order, "key": key, "amount_in": str(order.amount_in),
            "min_amount_out": str(order.min_amount_out), "quoted_amount_out": str(order.quoted_amount_out),
            # The measured impact, not the tolerance we allow. Recording the tolerance made every
            # confirmed buy read "8.0 %" (2026-09-07) and left no way to answer whether a bigger
            # ticket would cost more -- the one question the journal existed to settle.
            "slippage_pct": q.price_impact_pct, "quote_address": quote_addr, "calldata": order.calldata}


SEL_TOO_LITTLE = "0x8b063d73"     # V4TooLittleReceived(uint256 minimum, uint256 actual)


async def chain_actual_out(ctx: IntelContext, order: Any, key: Any) -> int | None:
    """What the pool would really return for this order, asked to the chain itself.

    The single-tick math quote knows nothing of what a hook takes: on 2026-09-07 the first real
    buy reverted with the price unmoved because the launchpad's hook kept 12.6 % of the output.
    The router's own error carries the true figure, so the probe asks for an impossible minimum
    and reads the actual amount out of the revert. One read-only call, exact by construction.
    """
    from intel.execution import orders as ord_mod
    from intel.execution.signer import signer_address

    owner = signer_address()
    if owner is None:
        return None
    probe = ord_mod.build_swap(key=key, token=order.token, quote=order.quote, kind=order.kind, zero_for_one=order.zero_for_one,
                               amount_in=order.amount_in, quoted_amount_out=2 ** 100, slippage_pct=0.0, router=order.router,
                               deadline_s=120, native_quote=order.value_wei > 0)
    call = {"from": owner, "to": probe.router, "data": probe.calldata, "value": hex(probe.value_wei)}
    try:
        await ctx.rpc.request("eth_call", [call, "latest"])
        return None                                      # cannot happen with a 2**100 minimum
    except Exception as exc:  # noqa: BLE001
        data = getattr(exc, "data", None) or (exc.args[2] if len(exc.args) > 2 else None)
        data = str(data or "")
        if not data.startswith(SEL_TOO_LITTLE) or len(data) < 138:
            log.info("cotation en chaîne impossible pour %s : %s", order.token[:10], (data[:10] or str(exc)[:80]))
            return None
        return int(data[74:138], 16)


async def run_once(ctx: IntelContext, *, limit: int = 20) -> dict[str, Any]:
    """Process every decision that has not been journalled yet."""
    mode = str(ctx.config.get("execution.mode", "dry_run"))
    limits = safety.Limits.from_config(ctx)
    out = {"mode": mode, "seen": 0, "built": 0, "refused": 0, "submitted": 0, "failed": 0}
    for d in pending_decisions(ctx, limit=limit):
        out["seen"] += 1
        held_raw: int | None = None
        if mode == "live" and d["kind"] != safety.BUY and not str(d.get("model_version") or "").startswith("t1-shadow"):
            # Live sells are sized from what the wallet actually holds. The book's estimate is
            # the fallback, and prepare() refuses when neither is known.
            try:
                from intel.chain.erc20 import balance_of
                from intel.execution.signer import signer_address

                owner = signer_address()
                if owner:
                    held_raw = await balance_of(ctx.rpc, str(d["token_address"]).lower(), owner)
            except Exception as exc:  # noqa: BLE001
                log.warning("solde du portefeuille illisible pour %s : %s", d.get("label"), str(exc)[:120])
        # Shadow decisions (t1-shadow-…) exist to be measured, never sent: they take the dry path
        # whatever the mode, and the honeypot probe's verdict is written next to them so the paper
        # book can say, tomorrow, how many traps the probe would have caught.
        shadow = str(d.get("model_version") or "").startswith("t1-shadow")
        probe_note: str | None = None
        if (mode == "live" or shadow) and d["kind"] == safety.BUY and str(d.get("model_version") or "").startswith("t1-"):
            # Before paying for a token: can a holder move it at all? (honeypot filter)
            try:
                import json as _json
                from intel.execution.honeypot import transfer_probe

                pool_id = (_json.loads(d.get("metrics_json") or "{}") or {}).get("pool_id")
                ok, why = await transfer_probe(ctx, str(d["token_address"]), pool_id)
            except Exception as exc:  # noqa: BLE001
                ok, why = True, f"sonde en erreur ({str(exc)[:60]})"
            probe_note = ("sonde OK : " if ok else "sonde BLOQUE : ") + why
            if not ok and not shadow:
                _journal(ctx, d, status="REFUSED", mode=mode, refused_reason="token invendable : " + why)
                out["refused"] += 1
                log.info("ordre refusé BUY %s : token invendable : %s", str(d["token_address"])[:10], why)
                continue
        try:
            res = prepare(ctx, d, limits=limits, held_raw=held_raw)
        except Exception as exc:  # noqa: BLE001
            log.exception("préparation de l'ordre %s: %s", d.get("label"), exc)
            _journal(ctx, d, status="FAILED", mode=mode, error=str(exc)[:400])
            out["failed"] += 1
            continue
        order = res.pop("order", None)
        key = res.pop("key", None)
        status = res.pop("status")
        # The paper book asks the chain the same question and records the answer, but never lets it
        # refuse: the tax ceiling was set by judgement on four tickets, and a ceiling can only be
        # placed where the outcomes of the buys it refuses have been measured.
        if status == "BUILT" and shadow and order is not None and key is not None:
            try:
                actual = await chain_actual_out(ctx, order, key)
            except Exception:  # noqa: BLE001
                actual = None
            if actual is not None and order.quoted_amount_out > 0:
                gap = 1.0 - actual / order.quoted_amount_out
                res["refused_reason"] = f"taxe mesurée {gap * 100:.1f} %"
                res["quoted_amount_out"] = str(actual)
        if status == "BUILT" and mode == "live" and not shadow and order is not None and key is not None:
            # Replace the math quote by the chain's own answer before anything is signed.
            actual = await chain_actual_out(ctx, order, key)
            if actual is not None and order.quoted_amount_out > 0:
                gap = 1.0 - actual / order.quoted_amount_out
                max_tax = float(ctx.config.get("execution.max_hook_tax_pct", 25.0)) / 100.0
                if actual <= 0:
                    status = "REFUSED"
                    res["refused_reason"] = "la chaîne ne rend rien pour cet ordre (token invendable)"
                elif d["kind"] == safety.BUY and gap > max_tax:
                    # a buy is optional: too expensive a hook, we pass. A sell is not: a token
                    # that pays 46 % less than quoted still pays more than the zero it becomes.
                    status = "REFUSED"
                    res["refused_reason"] = f"le pool rend {gap * 100:.1f} % de moins que la cotation (taxe du hook) > {max_tax * 100:.0f} %"
                else:
                    from intel.execution import orders as ord_mod
                    order = ord_mod.build_swap(key=key, token=order.token, quote=order.quote, kind=order.kind,
                                               zero_for_one=order.zero_for_one, amount_in=order.amount_in,
                                               quoted_amount_out=actual, slippage_pct=order.slippage_pct, router=order.router,
                                               deadline_s=int(ctx.config.get("execution.deadline_seconds", 120)),
                                               native_quote=order.value_wei > 0)
                    res.update({"min_amount_out": str(order.min_amount_out), "quoted_amount_out": str(order.quoted_amount_out),
                                "calldata": order.calldata})
                    log.info("cotation en chaîne %s : %.1f %% sous la cotation calculée, minimum recalculé", order.token[:10], gap * 100)
        if status == "REFUSED":
            _journal(ctx, d, status="REFUSED", mode="dry_run" if shadow else mode, **res)
            out["refused"] += 1
            log.info("ordre refusé %s %s : %s", d["kind"], d.get("label"), res.get("refused_reason"))
            continue
        if mode != "live" or shadow:
            _journal(ctx, d, status="BUILT", mode="dry_run" if shadow else mode, error=probe_note, **res)
            out["built"] += 1
            log.info("ordre construit à blanc %s %s : %s -> min %s", d["kind"], d.get("label"), res["amount_in"], res["min_amount_out"])
            continue
        exec_id = _journal(ctx, d, status="BUILT", mode=mode, **res)
        try:
            from intel.execution.approvals import missing_approvals
            from intel.execution.signer import broadcast, build_and_sign, signer_address

            # A swap without the spending grants does not fail politely: it reverts after the gas
            # has been paid. Each grant is given once per token and then reused.
            owner = signer_address()
            if owner is None:
                raise RuntimeError("aucune clé configurée")
            spending = order.quote if d["kind"] == safety.BUY else order.token
            for need in await missing_approvals(ctx, token=spending, owner=owner, amount=order.amount_in, now_ts=now_ts()):
                log.info("autorisation manquante (%s) : %s", need.what, need.reason)
                a_signed = await build_and_sign(ctx, to=need.to, data=need.data, value_wei=0,
                                                sortie=d["kind"] != safety.BUY)
                a_hash = await broadcast(ctx, a_signed)
                # The node's pending nonce lags a fresh broadcast by a second or two: the first
                # real sell (2026-09-07) signed with the approval's nonce and died "nonce too low".
                # Each grant is one-off per token, so waiting for its receipt costs nothing that matters.
                from intel.execution.signer import wait_receipt
                await wait_receipt(ctx, a_hash, attempts=40, delay_s=1.0)
                # Journalled with no decision_id: an approval is not the decision itself, and the
                # unique index must stay free for the swap that follows.
                _journal(ctx, d, status="SUBMITTED", mode=mode, decision_id=None, size_eur=None,
                         kind="APPROVE", tx_hash=a_hash, refused_reason=need.what)
                log.info("autorisation envoyée %s tx=%s", need.what, a_hash)

            signed = await build_and_sign(ctx, to=order.router, data=order.calldata, value_wei=order.value_wei,
                                          sortie=d["kind"] != safety.BUY)
            tx_hash = await broadcast(ctx, signed)
            ctx.db.execute("UPDATE executions SET status='SUBMITTED', tx_hash=? WHERE id=?", (tx_hash, exec_id))
            out["submitted"] += 1
            log.info("ordre envoyé %s %s tx=%s", d["kind"], d.get("label"), tx_hash)
        except Exception as exc:  # noqa: BLE001
            ctx.db.execute("UPDATE executions SET status='FAILED', error=? WHERE id=?", (str(exc)[:400], exec_id))
            out["failed"] += 1
            log.warning("ordre non envoyé %s %s : %s", d["kind"], d.get("label"), str(exc)[:200])
    return out
