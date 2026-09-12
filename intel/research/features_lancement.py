"""La table de variables d un lancement, batie sur la litterature et non sur l intuition.

Deux papiers lus le 09/09 au soir disent ce qui predit un rug pull et une graduation :

  Yaremus et al. 2025, TON (arXiv 2509.01168), AUC 0,885-0,891 dans les 5 premieres minutes.
    Variables de tete, approche TVL  : max_tvl_5min, jetton_creation_trade_delta, first_buy_time.
    Variables de tete, approche Idle : total_usd_volume_5min, buys_5min, is_pool_creator.
    Definition du rug (TVL) : chute de plus de p % depuis le pic de TVL dans la premiere heure.

  Kamat 2026, pump.fun (arXiv 2607.02823), 832 941 lancements, concordance 0,858.
    Telegram HR 5,40 · log capitalisation initiale HR 4,51 · Twitter 1,30 · site 1,19.

Ce module construit, pour chaque lancement dont on a la courbe en chaine (`solana_prix_chaine`),
les variables que ces travaux designent, plus celles mesurees ici (§3.66), avec une etiquette
definie EXACTEMENT comme dans le papier TON : rug = reserve SOL tombee sous (1-p) de son pic.

TOUT est connu a T+90 s ou avant. Aucune variable ne regarde apres la decision.

VARIABLES
  chaine, lisibles en un ou deux appels RPC par lancement :
    delta_creation_s     secondes entre la creation du mint et la migration (papier TON : en tete)
    createur             adresse qui a signe la creation du mint
    lancements_createur  combien de mints ce createur a deja migres avant celui-ci (lanceur en serie)
    is_pool_creator      le createur du mint est-il le createur du pool PumpSwap (offset 11)
  deja collectees :
    liq_initiale_sol     reserve SOL au premier releve (TON : initial_tvl / max_tvl_5min)
    liq_max_90s          reserve SOL maximale avant T+90 s
    trades, payers       echanges et acheteurs distincts au jugement (TON : buys, unique_buyers)
    trades_30s, payers_30s
    market_cap, chg_m5
  mesurees ici (§3.66) :
    var_90s, pic_90s, creux_90s, liq_var_90s, signes_trop_propre
  optionnelles (None si illisibles) :
    a_telegram, a_twitter, a_site, longueur_description

ETIQUETTES
    rug_tvl      reserve SOL < (1-p) x pic, p = 0,80, dans les 15 min suivant T+90 s
    suite_mult   prix a T+15 min / prix a T+90 s   (la seule qui vaille de l argent)

Usage :
    python -m intel.research.features_lancement            # construit et resume
    python -m intel.research.features_lancement --csv x    # exporte
"""
from __future__ import annotations

import argparse
import base64
import sqlite3
import statistics as st
import sys
import time
from typing import Any

import base58
import httpx

sys.path.insert(0, "/app")

PAMM = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
T_DECISION = 90
T_FIN = 900
P_RUG = 0.80            # chute de plus de 80 % de la reserve depuis son pic = rug (TON, approche TVL)


def _rpc(cl: httpx.Client, url: str, methode: str, params: list) -> Any:
    try:
        return (cl.post(url, json={"jsonrpc": "2.0", "id": 1, "method": methode,
                                   "params": params}, timeout=40).json() or {}).get("result")
    except Exception:  # noqa: BLE001
        return None


def creation_du_mint(cl: httpx.Client, url: str, mint: str) -> tuple[int | None, str | None]:
    """(horodatage de creation, signataire). On pagine jusqu au bout : un jeton tres echange a plus
    de mille signatures, et sans pagination on lirait la plus ancienne des mille DERNIERES, c est-a-
    dire une date proche de la migration -- ce qui est exactement l erreur commise a la premiere sonde
    (delta de 1 s sur deux jetons)."""
    before = None
    plus_vieille = None
    for _ in range(20):                       # 20 000 signatures au plus
        p = [mint, {"limit": 1000}]
        if before:
            p[1]["before"] = before
        sigs = _rpc(cl, url, "getSignaturesForAddress", p) or []
        if not sigs:
            break
        plus_vieille = sigs[-1]
        before = sigs[-1]["signature"]
        if len(sigs) < 1000:
            break
        time.sleep(0.05)
    if not plus_vieille:
        return None, None
    tx = _rpc(cl, url, "getTransaction", [plus_vieille["signature"],
                                          {"maxSupportedTransactionVersion": 0, "encoding": "jsonParsed"}])
    signer = None
    if tx:
        for k in tx["transaction"]["message"]["accountKeys"]:
            if isinstance(k, dict) and k.get("signer"):
                signer = k["pubkey"]
                break
    return plus_vieille.get("blockTime"), signer


def createur_du_pool(cl: httpx.Client, url: str, mint: str) -> str | None:
    res = _rpc(cl, url, "getProgramAccounts", [PAMM, {
        "encoding": "base64",
        "filters": [{"dataSize": 301}, {"memcmp": {"offset": 43, "bytes": mint}}]}]) or []
    if not res:
        return None
    d = base64.b64decode(res[0]["account"]["data"][0])
    return base58.b58encode(d[11:43]).decode()


def construire(db: str, url: str, limite: int = 400) -> list[dict]:
    c = sqlite3.connect("file:" + db + "?mode=ro", uri=True)
    c.row_factory = sqlite3.Row

    # les courbes en chaine
    courbes: dict[str, list[tuple[int, float, float]]] = {}
    mint_de: dict[str, str] = {}
    for r in c.execute("SELECT pair_id, mint, age_s, prix_sol, reserve_sol FROM solana_prix_chaine"
                       " WHERE prix_sol > 0 ORDER BY pair_id, age_s"):
        courbes.setdefault(r["pair_id"], []).append((int(r["age_s"]), float(r["prix_sol"]), float(r["reserve_sol"] or 0)))
        mint_de[r["pair_id"]] = r["mint"]

    # ce que le jugement et l observation savent deja
    jug = {}
    for r in c.execute("SELECT mint, trades, payers, market_cap, liquidity_usd, chg_m5, age_s, ts FROM solana_judgements"):
        jug.setdefault(r["mint"], dict(r))
    obs = {}
    for r in c.execute("SELECT mint, trades_30s, uniq_payers_30s, trades_first_minute, uniq_payers FROM solana_observations"):
        obs.setdefault(r["mint"], dict(r))
    migr = {r["mint"]: int(r["ts"]) for r in c.execute("SELECT mint, ts FROM solana_stream_launches")}

    cl = httpx.Client(timeout=40)
    cache_createur: dict[str, tuple[int | None, str | None]] = {}
    lancements_par_createur: dict[str, list[int]] = {}
    out = []
    n = 0
    for pid, pts in courbes.items():
        if n >= limite:
            break
        avant = [p for p in pts if p[0] <= T_DECISION]
        apres = [p for p in pts if T_DECISION < p[0] <= T_FIN]
        if len(avant) < 4 or avant[0][0] > 45 or len(apres) < 6:
            continue
        mint = mint_de[pid]
        p0 = avant[0][1]
        pv = [p[1] / p0 for p in avant]
        rv = [p[2] for p in avant]
        ra = [p[2] for p in apres]
        pa = [p[1] / p0 for p in apres]

        # --- variables chaine (couteuses : mises en cache par mint)
        if mint not in cache_createur:
            cache_createur[mint] = creation_du_mint(cl, url, mint)
        t_cre, createur = cache_createur[mint]
        t_mig = migr.get(mint)
        pool_cre = createur_du_pool(cl, url, mint)
        if createur:
            lancements_par_createur.setdefault(createur, []).append(t_mig or 0)

        d = dict(
            pair_id=pid, mint=mint, migration_ts=t_mig,
            delta_creation_s=(t_mig - t_cre) if (t_mig and t_cre) else None,
            createur=createur, pool_createur=pool_cre,
            is_pool_creator=int(bool(createur and pool_cre and createur == pool_cre)),
            liq_initiale_sol=rv[0], liq_max_90s=max(rv),
            var_90s=pv[-1] - 1, pic_90s=max(pv) - 1, creux_90s=min(pv) - 1,
            liq_var_90s=(rv[-1] / rv[0] - 1) if rv[0] > 0 else None,
            rug_tvl=int(min(ra) < (1 - P_RUG) * max(rv + ra[:1])) if rv else 0,
            suite_mult=pa[-1] / pv[-1],
            suite_pic=max(pa) / pv[-1],
        )
        d["signes_trop_propre"] = int(d["var_90s"] >= 0.007) + int(d["creux_90s"] >= 0) + int((d["liq_var_90s"] or 0) >= 0.0035)
        j = jug.get(mint) or {}
        o = obs.get(mint) or {}
        d.update(trades=j.get("trades"), payers=j.get("payers"), market_cap=j.get("market_cap"),
                 chg_m5=j.get("chg_m5"), trades_30s=o.get("trades_30s"),
                 payers_30s=(o.get("uniq_payers_30s") if not (o.get("uniq_payers_30s") == 0 and (o.get("trades_30s") or 0) > 0) else None))
        out.append(d)
        n += 1

    # le compte des lancements ANTERIEURS du meme createur -- calcule apres coup, sans regarder l avenir
    for d in out:
        cr = d["createur"]
        if cr and d["migration_ts"]:
            d["lancements_createur"] = sum(1 for t in lancements_par_createur.get(cr, []) if t < d["migration_ts"])
        else:
            d["lancements_createur"] = None
    out.sort(key=lambda x: x["migration_ts"] or 0)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="/app/db/intel.sqlite")
    ap.add_argument("--limite", type=int, default=400)
    ap.add_argument("--csv")
    a = ap.parse_args()
    from intel.execution import solana as sol
    url = sol.rpc_url()
    if not url:
        print("  pas de RPC"); return
    d = construire(a.db, url, a.limite)
    print("  %d lancements avec variables completes" % len(d))
    if not d:
        return
    rug = sum(x["rug_tvl"] for x in d)
    print("  rugs (TVL, p=%.0f %%) : %d (%.0f %%)" % (100 * P_RUG, rug, 100 * rug / len(d)))
    print()
    for v in ("delta_creation_s", "lancements_createur", "liq_initiale_sol", "trades", "payers", "signes_trop_propre"):
        vals = [x[v] for x in d if x.get(v) is not None]
        if not vals:
            print("  %-22s aucune valeur" % v); continue
        print("  %-22s mediane %10.2f · min %8.2f · max %10.2f · connu %d/%d" % (
            v, st.median(vals), min(vals), max(vals), len(vals), len(d)))
    print()
    print("  is_pool_creator : %d/%d" % (sum(x["is_pool_creator"] for x in d), len(d)))
    if a.csv:
        import csv
        cols = list(d[0].keys())
        with open(a.csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cols); w.writeheader(); w.writerows(d)
        print("  exporte vers", a.csv)


if __name__ == "__main__":
    main()
