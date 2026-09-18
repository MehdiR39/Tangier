"""Grand balayage, etape 1 : la table (pool x moment de decision), prix CORRIGES, couts reels.

Chaque ligne = un pool a un age de decision A (secondes depuis la migration). Tout ce qui est dans
une ligne etait VISIBLE a l instant A (lectures d age <= A, historique des autres jetons dont l issue
etait connue avant). Les rendements futurs partent du prix d EXECUTION (lecture la plus proche de
A + 2 s) et sortent a A + 2 + H.

Prix echangeable = (reserve_sol + reserve virtuelle) / reserve_base (§3.83). Horodatage decale de
12 s (lectures « finalized » de l historique). Cout d un aller-retour :
    1,7 %  (frais de pool ~1,2 + priorite 0,3 + marge ; depot du compte de jetons suppose recupere)
  + 2 x 0,31 SOL / (reserve_sol + reserve virtuelle)   (impact d un ordre de 30 EUR, a l aller et au retour)
Calibrage (calibration_corrigee.py) : ecart reel - simule = -2,4 points en mediane, depot compris.

Sortie : data/recherche/balayage/table.pkl
"""
from __future__ import annotations

import json
import os
import sqlite3
from bisect import bisect_right
from collections import defaultdict

import numpy as np
import pandas as pd

ICI = os.path.dirname(os.path.abspath(__file__))
RACINE = os.path.abspath(os.path.join(ICI, "..", ".."))
D = os.path.join(RACINE, "data", "recherche")
SORTIE = os.path.join(D, "balayage")
RETARD_S = 12
EXEC_S = 2
V_PUMP = 17.5845
AGES = (20, 30, 45, 60, 90, 120, 180, 300, 450, 600)
HORIZONS = (30, 60, 120, 240, 480, 900)
MISE_SOL = 0.31
COUT_FIXE = 0.017


def charger():
    c = sqlite3.connect("file:%s?mode=ro" % os.path.join(D, "archive_solana.sqlite"), uri=True, timeout=120)
    V = json.load(open(os.path.join(D, "reserve_virtuelle.json")))
    rows = c.execute("""SELECT p.pair_id, p.mint, p.ts, p.age_s, p.reserve_base, p.reserve_sol
                        FROM solana_prix_chaine p JOIN pool_quote q ON q.pool=p.pair_id AND q.est_sol=1
                        WHERE p.prix_sol > 0 AND p.reserve_base > 0 ORDER BY p.pair_id, p.ts""").fetchall()
    pools = defaultdict(list)
    for pair, mint, ts, age, xb, xs in rows:
        v = V.get(pair)
        if v is None or (v != 0 and abs(v - V_PUMP) > 0.001):
            continue
        pools[pair].append((age - RETARD_S, ts - RETARD_S, (xs + v) / xb, xs, xb, v, mint))
    tg = {m: t for m, t in c.execute("SELECT mint, telegram FROM tg_juges")}
    soc = {m: (tw, si, nd) for m, tw, si, nd in c.execute("SELECT mint, twitter, site, n_descr FROM solana_social")}
    cre = {m: (cr, ts) for m, cr, ts in c.execute("SELECT mint, createur, ts FROM sol_createur")}
    lanc = sorted(ts for (ts,) in c.execute("SELECT MIN(ts) FROM solana_stream_launches GROUP BY mint"))
    sacs = {}
    for l in open(os.path.join(D, "sacs_migration.jsonl"), encoding="utf-8"):
        d = json.loads(l)
        if d.get("erreur") or not d.get("instants"):
            continue
        top = d["instants"].get("30", [])
        parts = [q / 1e9 for _, q in top]
        sacs[d["mint"]] = (parts[0] if parts else 0.0, sum(1 for x in parts if x >= 0.05), top[0][0] if top else None)
    fin = {}
    if os.path.exists(os.path.join(D, "financeurs.jsonl")):
        for l in open(os.path.join(D, "financeurs.jsonl"), encoding="utf-8"):
            d = json.loads(l)
            if d.get("financeur"):
                fin[d["wallet"]] = d["financeur"]
    return pools, tg, soc, cre, lanc, sacs, fin


def a_age(ages, prix, cible, tol):
    i = bisect_right(ages, cible)
    best = None
    for j in (i - 1, i):
        if 0 <= j < len(ages) and abs(ages[j] - cible) <= tol:
            if best is None or abs(ages[j] - cible) < abs(ages[best] - cible):
                best = j
    return best


def construire():
    pools, tg, soc, cre, lanc, sacs, fin = charger()
    lignes = []
    for pair, pts in pools.items():
        if pts[0][0] > 20 or len(pts) < 6:
            continue
        ages = [x[0] for x in pts]
        prix = np.array([x[2] for x in pts])
        qs = np.array([x[3] for x in pts])
        mint, v = pts[0][6], pts[0][5]
        naissance = pts[0][1] - pts[0][0]
        for A in AGES:
            k = bisect_right(ages, A)                      # lectures visibles : age <= A
            if k < 3:
                continue
            e = a_age(ages, prix, A + EXEC_S, 6)
            if e is None:
                continue
            p_vis, q_vis = prix[:k], qs[:k]
            pe = prix[e]
            # le moteur n achete pas quand l ordre pese plus de 15 % du pool (`max_impact_pct`)
            if q_vis[-1] + v <= 0 or MISE_SOL / (q_vis[-1] + v) > 0.15:
                continue
            f = {"pair": pair, "mint": mint, "naissance": naissance, "A": A, "V": int(v > 0),
                 "n_lect": k, "ret_naiss": p_vis[-1] / p_vis[0] - 1,
                 "dd_max": p_vis[-1] / p_vis.max() - 1, "depuis_min": p_vis[-1] / p_vis.min() - 1,
                 "t_depuis_max": A - ages[int(np.argmax(p_vis))],
                 "vol": float(np.std(np.diff(np.log(p_vis)))) if k >= 3 else np.nan,
                 "q": q_vis[-1], "q_croiss": q_vis[-1] / q_vis[0] - 1 if q_vis[0] > 0 else np.nan,
                 "heure": int(((naissance + A) % 86400) // 3600)}
            for w in (10, 30, 60, 120):
                j = a_age(ages, prix, A - w, 6)
                f["ret_%d" % w] = (p_vis[-1] / prix[j] - 1) if (j is not None and j < k) else np.nan
            for w in (30, 60):
                j = a_age(ages, prix, A - w, 6)
                f["q_croiss_%d" % w] = (q_vis[-1] / qs[j] - 1) if (j is not None and j < k and qs[j] > 0) else np.nan
            f["telegram"] = tg.get(mint)
            tw, si, nd = soc.get(mint, (None, None, None))
            f.update(twitter=tw, site=si, n_descr=nd)
            s = sacs.get(mint)
            f["sac1"] = s[0] if (s and A >= 30) else np.nan
            f["n_sacs5"] = s[1] if (s and A >= 30) else np.nan
            f["sac_wallet"] = s[2] if (s and A >= 30 and s[0] >= 0.05) else None
            f["createur"] = cre.get(mint, (None, None))[0]
            t_dec = naissance + A
            f["lancements_10min"] = bisect_right(lanc, t_dec) - bisect_right(lanc, t_dec - 600)
            cout = COUT_FIXE + 2 * MISE_SOL / (q_vis[-1] + v if (q_vis[-1] + v) > 0 else 1)
            f["cout"] = cout
            for H in HORIZONS:
                s_ = a_age(ages, prix, A + EXEC_S + H, 8)
                f["brut_%d" % H] = (prix[s_] / pe - 1) if s_ is not None and s_ > e else np.nan
                f["net_%d" % H] = f["brut_%d" % H] - cout if s_ is not None and s_ > e else np.nan
            lignes.append(f)
    df = pd.DataFrame(lignes).sort_values(["naissance", "A"]).reset_index(drop=True)

    # --- historique connu AVANT la decision : createur, detenteur, financeur, marche ---
    issue = (df[df.A == 60][["mint", "naissance", "brut_240", "sac_wallet"]].dropna(subset=["brut_240"])
             .assign(connu=lambda x: x.naissance + 60 + 2 + 240, vide=lambda x: x.brut_240 <= -0.5)
             .sort_values("connu"))
    connus_t = issue.connu.to_numpy()
    fin_de = {w: fin.get(w) for w in issue.sac_wallet.dropna().unique()}
    cre_de = {m: c_ for m, (c_, _) in cre.items()}
    prec_cre, prec_w_vide, prec_f_vide, mkt_ret, mkt_vide = [], [], [], [], []
    iss = issue.to_dict("records")
    for r in df[["mint", "naissance", "A", "sac_wallet", "createur"]].itertuples(index=False):
        t = r.naissance + r.A
        n = bisect_right(connus_t, t)
        passes = iss[:n]
        recents = [x for x in passes if x["connu"] >= t - 1800]
        mkt_ret.append(np.mean([x["brut_240"] for x in recents]) if len(recents) >= 5 else np.nan)
        mkt_vide.append(np.mean([x["vide"] for x in recents]) if len(recents) >= 5 else np.nan)
        prec_cre.append(sum(1 for x in passes if r.createur and cre_de.get(x["mint"]) == r.createur and x["mint"] != r.mint))
        w = r.sac_wallet
        f_ = fin.get(w) if w else None
        prec_w_vide.append(int(any(x["vide"] and x["sac_wallet"] == w for x in passes)) if w else np.nan)
        prec_f_vide.append(int(any(x["vide"] and x["sac_wallet"] and fin_de.get(x["sac_wallet"]) == f_ for x in passes)) if f_ else np.nan)
    df["createur_prec"], df["det_a_vide"], df["fin_a_vide"] = prec_cre, prec_w_vide, prec_f_vide
    df["marche_ret_30min"], df["marche_vides_30min"] = mkt_ret, mkt_vide
    os.makedirs(SORTIE, exist_ok=True)
    df.to_pickle(os.path.join(SORTIE, "table.pkl"))
    print("table : %d lignes, %d pools, %d colonnes -> %s" % (len(df), df.pair.nunique(), df.shape[1], SORTIE))
    print(df.groupby("A")[["net_240"]].agg(["count", "mean"]).round(4).to_string())


if __name__ == "__main__":
    construire()
