"""Le DEUXIEME marche de pump.fun : les courbes libellees en jeton PUMP, pas en SOL (16/09).

DECOUVERTE (journal §3.94). 36 % des jetons actifs ont une courbe dont le compte ne recoit jamais de SOL : ils se
tradent contre le jeton de la plateforme (mint `pumpCmXq...`). Notre lecture, qui cherchait des lamports, ne voyait
rien. Or les trois portefeuilles les plus rentables y font 487 de leurs 826 jetons : c est le seul marche ou on a la
preuve mesuree que quelqu un gagne, et le seul qu on n a jamais regarde.

COMMENT. Meme methode que `courbe_collecte.py`, mais on lit les DEUX cotes : pour chaque transaction du programme
pump.fun, la variation du compte de jetons de la courbe ET celle de son compte en PUMP. Prix = PUMP par jeton.
Fenetre : 13/09 12h -> 14/09 12h UTC (24 h), une tranche d une heure a la fois, transactions reussies, version 1
acceptee. Sortie : data/recherche/courbe_pump/AAAAMMJJ_HH.jsonl, une ligne par (transaction, jeton).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from copie_collecte import rpc  # noqa: E402
from courbe_collecte import PROG, courbe_de  # noqa: E402

PUMP = "pumpCmXqMfrsAkQ5r49WcJnRayYRqmXz6ae8H7H9Dfn"
D = os.environ.get("COURBE_PUMP_DIR", "/app/data/recherche/courbe_pump")
DEBUT = int(dt.datetime(2026, 9, 13, 12, tzinfo=dt.timezone.utc).timestamp())
FIN = int(dt.datetime(2026, 9, 14, 12, tzinfo=dt.timezone.utc).timestamp())
PAGES_MAX = 400


def _ui(b):
    return float(b["uiTokenAmount"].get("uiAmountString") or 0)


def analyser(tx, t0):
    meta = tx.get("meta") or {}
    pre, post = meta.get("preTokenBalances") or [], meta.get("postTokenBalances") or []
    mints = {b.get("mint") for b in pre + post if b.get("mint") and b.get("mint") != PUMP}
    out = []
    for m in mints:
        c = courbe_de(m)

        def solde(liste, mint, proprio):
            return sum(_ui(b) for b in liste if b.get("mint") == mint and b.get("owner") == proprio)

        tok0, tok1 = solde(pre, m, c), solde(post, m, c)
        pmp0, pmp1 = solde(pre, PUMP, c), solde(post, PUMP, c)
        if tok0 == tok1 and pmp0 == pmp1:
            continue
        if pmp1 == 0 and pmp0 == 0:
            continue                                   # courbe en SOL : deja couverte par courbe_collecte
        dtok, dpmp = tok1 - tok0, pmp1 - pmp0
        avant = {b.get("owner"): _ui(b) for b in pre if b.get("mint") == m and b.get("owner") != c}
        apres = {b.get("owner"): _ui(b) for b in post if b.get("mint") == m and b.get("owner") != c}
        deltas = {o: apres.get(o, 0.0) - avant.get(o, 0.0) for o in set(avant) | set(apres)}
        parts = []
        if dtok * dpmp < 0:
            sens = 1.0 if dtok < 0 else -1.0
            memes = {o: d for o, d in deltas.items() if o and d * sens > 0}
            tot = sum(abs(d) for d in memes.values())
            if tot > 0:
                parts = [[o, d, round(-dpmp * abs(d) / tot, 9)] for o, d in memes.items()]
        out.append([tx.get("blockTime", t0), tx.get("slot"), m, round(pmp1, 6), round(tok1, 3),
                    round(dpmp, 6), round(dtok, 3), parts, tx.get("version")])
    return out


def lire_tranche(t0, t1):
    jeton, pages, n_tx, lignes = None, 0, 0, []
    while pages < PAGES_MAX:
        opts = {"transactionDetails": "full", "sortOrder": "asc", "limit": 1000, "encoding": "jsonParsed",
                "maxSupportedTransactionVersion": 1,
                "filters": {"blockTime": {"gte": t0, "lt": t1}, "status": "succeeded"}}
        if jeton:
            opts["paginationToken"] = jeton
        res = rpc({"jsonrpc": "2.0", "id": 1, "method": "getTransactionsForAddress", "params": [PROG, opts]}) or {}
        pages += 1
        for tx in res.get("data") or []:
            n_tx += 1
            lignes.extend(analyser(tx, t0))
        jeton = res.get("paginationToken")
        if not jeton:
            break
    nom = dt.datetime.fromtimestamp(t0, dt.timezone.utc).strftime("%Y%m%d_%H")
    with open(os.path.join(D, nom + ".jsonl"), "w", encoding="utf-8") as f:
        for l in lignes:
            f.write(json.dumps(l) + "\n")
    return n_tx, len(lignes), bool(jeton)


def main():
    os.makedirs(D, exist_ok=True)
    faits = {f[:-6] for f in os.listdir(D) if f.endswith(".jsonl")}
    tranches = [t for t in range(DEBUT, FIN, 3600)
                if dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y%m%d_%H") not in faits]
    print("courbe_pump: %d heures a lire" % len(tranches), flush=True)
    verrou, etat, t_debut = threading.Lock(), {"h": 0, "tx": 0, "l": 0, "err": 0}, time.time()

    def une(t0):
        if etat["err"] >= 3:
            return
        try:
            n_tx, n_l, tronque = lire_tranche(t0, t0 + 3600)
        except Exception as exc:  # noqa: BLE001
            with verrou:
                etat["err"] += 1
                print("courbe_pump: ERREUR %d : %s" % (t0, str(exc)[:140]), flush=True)
            return
        with verrou:
            etat["h"] += 1
            etat["tx"] += n_tx
            etat["l"] += n_l
            print("courbe_pump: %s %d tx, %d lignes PUMP%s · total %d h, %d tx, ~%d credits, %.0f s" % (
                dt.datetime.fromtimestamp(t0, dt.timezone.utc).strftime("%d/%m %Hh"), n_tx, n_l,
                " TRONQUE" if tronque else "", etat["h"], etat["tx"], etat["tx"] // 10, time.time() - t_debut), flush=True)

    with ThreadPoolExecutor(3) as ex:
        list(ex.map(une, tranches))
    print("courbe_pump: FINI (%d heures, %d transactions, %d lignes, ~%d credits)" % (
        etat["h"], etat["tx"], etat["l"], etat["tx"] // 10), flush=True)


if __name__ == "__main__":
    main()
