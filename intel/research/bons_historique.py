"""Historique complet des bons portefeuilles (15/09, demande de l operateur : « analyser quand ils rentrent,
quand ils sortent, sur quels jetons »).

Les 325 portefeuilles vus dans >= 10 pools de RECHERCHE avec un rendement propre moyen > +10 % (journal §3.87,
`data/recherche/copie/bons_R.json`) gardent leur avance hors echantillon (+8,8 % par pool sur TRI contre
-13,5 %). La collecte par pool ne voit que les 15 premieres minutes des pools PumpSwap du balayage. Ici on lit
l ADRESSE du portefeuille : tout ce qu il a signe ou recu sur la periode, sur toutes les plateformes.

Mesure du cout avant lancement : 8 551 transactions pour le plus actif (166 pools), 747 pour le median, 243
pour le moins actif ; 10 credits par 100 transactions.

Sortie : data/recherche/copie/bons_historique.jsonl, une ligne par portefeuille. Chaque transaction :
[heure bloc, slot, variation SOL du portefeuille (lamports / 1e9, frais compris), payeur des frais == lui,
 [[mint, variation jetons]], [programmes appeles]]
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from copie_collecte import rpc, D  # noqa: E402

SORTIE = os.path.join(D, "bons_historique.jsonl")
PAGES_MAX = 50


def resume(tx, w):
    meta = tx.get("meta") or {}
    msg = (tx.get("transaction") or {}).get("message") or {}
    cles = [k.get("pubkey") if isinstance(k, dict) else k for k in msg.get("accountKeys") or []]
    try:
        i = cles.index(w)
        d_sol = ((meta.get("postBalances") or [0])[i] - (meta.get("preBalances") or [0])[i]) / 1e9
    except (ValueError, IndexError):
        d_sol = 0.0
    avant = {b.get("mint"): float(b["uiTokenAmount"].get("uiAmountString") or 0)
             for b in meta.get("preTokenBalances") or [] if b.get("owner") == w}
    apres = {b.get("mint"): float(b["uiTokenAmount"].get("uiAmountString") or 0)
             for b in meta.get("postTokenBalances") or [] if b.get("owner") == w}
    jetons = [[m, apres.get(m, 0.0) - avant.get(m, 0.0)] for m in set(avant) | set(apres)
              if apres.get(m, 0.0) != avant.get(m, 0.0)]
    progs = {ins.get("programId") for ins in msg.get("instructions") or []}
    for groupe in meta.get("innerInstructions") or []:
        progs |= {ins.get("programId") for ins in groupe.get("instructions") or []}
    return [tx.get("blockTime"), tx.get("slot"), round(d_sol, 9), bool(cles and cles[0] == w), jetons,
            sorted(p for p in progs if p)]


def lire(w, t0, t1):
    out, jeton, pages = [], None, 0
    while pages < PAGES_MAX:
        opts = {"transactionDetails": "full", "sortOrder": "asc", "limit": 1000, "encoding": "jsonParsed",
                "maxSupportedTransactionVersion": 0,
                "filters": {"blockTime": {"gte": t0, "lte": t1}, "status": "succeeded"}}
        if jeton:
            opts["paginationToken"] = jeton
        res = rpc({"jsonrpc": "2.0", "id": 1, "method": "getTransactionsForAddress", "params": [w, opts]}) or {}
        pages += 1
        out.extend(resume(tx, w) for tx in res.get("data") or [])
        jeton = res.get("paginationToken")
        if not jeton:
            break
    return out, bool(jeton)


def main():
    pools = json.load(open(os.path.join(D, "pools.json")))
    t0 = int(min(p["naissance"] for p in pools))
    t1 = int(max(p["naissance"] for p in pools)) + 900
    bons = json.load(open(os.path.join(D, "bons_R.json")))
    faits = set()
    if os.path.exists(SORTIE):
        for ligne in open(SORTIE, encoding="utf-8"):
            try:
                faits.add(json.loads(ligne)["wallet"])
            except Exception:  # noqa: BLE001
                pass
    todo = [b for b in bons if b["wallet"] not in faits]
    print("bons_historique: %d portefeuilles a lire" % len(todo), flush=True)
    verrou, etat = threading.Lock(), {"n": 0, "tx": 0}

    def un(b):
        try:
            txs, tronque = lire(b["wallet"], t0, t1)
            ligne = dict(b, tronque=tronque, tx=txs)
        except Exception as exc:  # noqa: BLE001
            ligne = dict(b, erreur=str(exc)[:160])
        with verrou:
            etat["n"] += 1
            etat["tx"] += len(ligne.get("tx", []))
            with open(SORTIE, "a", encoding="utf-8") as f:
                f.write(json.dumps(ligne) + "\n")
            if etat["n"] % 25 == 0:
                print("bons_historique: %d/%d, %d transactions, ~%d credits" % (
                    etat["n"], len(todo), etat["tx"], etat["tx"] // 10 + 10 * etat["n"]), flush=True)

    with ThreadPoolExecutor(3) as ex:
        list(ex.map(un, todo))
    print("bons_historique: FINI (%d transactions, ~%d credits)" % (etat["tx"], etat["tx"] // 10 + 10 * etat["n"]), flush=True)


if __name__ == "__main__":
    main()
