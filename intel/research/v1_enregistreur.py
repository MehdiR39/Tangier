"""Enregistreur vers l avant : les 60 premieres secondes de chaque nouveau pool, transaction par transaction (15/09 soir).

POURQUOI (journal §3.90). Le 15/09 a 01h04 UTC, Solana a active les transactions « version 1 ». Les pools ou elles
apparaissent ont porte tout le gain de l apres-midi, mais une journee ne prouve rien et le signal n existe que
depuis le 15/09 : il faut des jours neufs. L operateur : « rassure-toi que tu recuperes les bonnes data et toute la
data, pour qu on fasse une analyse solide et profonde apres ». Les regles A / B / C sont pre-enregistrees au journal.

CE QUI EST ENREGISTRE, pour chaque pool suivi par le collecteur du moteur (`solana_prix_chaine`), des qu il a 70 s :
Helius `getTransactionsForAddress` sur le pool, transactions REUSSIES, fenetre [naissance - 5 s, naissance + 60 s],
`maxSupportedTransactionVersion: 1`. Par transaction :
  [age, version, [[proprietaire, d jetons, d SOL]], coffre SOL apres, coffre jetons apres, nb signataires, payeur]
(parts vides = creation, liquidite ou echange sans acheteur visible ; meme analyse que copie_collecte.py).
Les prix au-dela de 60 s viennent du collecteur (correlation 0,987 avec les transactions, verifie le 15/09).

GARDE-FOU : le forfait Helius est partage avec le moteur ; au-dela de PLAFOND_JOUR credits sur 24 h glissantes,
l enregistreur attend. Sortie : data/recherche/v1_avant/AAAAMMJJ.jsonl (heure UTC de naissance), une ligne par pool.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
import sys
import time
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import copie_collecte as cc  # noqa: E402

BASE = os.environ.get("INTEL_DB", "/app/db/intel.sqlite")
D = os.environ.get("V1_DIR", "/app/data/recherche/v1_avant")
FENETRE = 60
ATTENTE = 70
PLAFOND_JOUR = 150_000
DEBUT = int(dt.datetime(2026, 9, 15, 22, 0, tzinfo=dt.timezone.utc).timestamp())   # 16/09 00h Paris


def nouveaux(faits, maintenant):
    c = sqlite3.connect("file:%s?mode=ro" % BASE, uri=True, timeout=60)
    try:
        rows = c.execute(
            "SELECT pair_id, MAX(mint), MIN(ts - age_s), MAX(reserve_virtuelle) FROM solana_prix_chaine"
            " WHERE ts >= ? GROUP BY pair_id HAVING MIN(age_s) <= 20", (DEBUT,)).fetchall()
    finally:
        c.close()
    return sorted((r for r in rows if r[0] not in faits and r[1] and r[2] >= DEBUT and r[2] <= maintenant - ATTENTE),
                  key=lambda r: r[2])


def lire(pair, mint, t0, V):
    jeton, pages, ev, n = None, 0, [], 0
    while pages < 10:
        opts = {"transactionDetails": "full", "sortOrder": "asc", "limit": 1000, "encoding": "jsonParsed",
                "maxSupportedTransactionVersion": 1,
                "filters": {"blockTime": {"gte": int(t0) - 5, "lte": int(t0) + FENETRE}, "status": "succeeded"}}
        if jeton:
            opts["paginationToken"] = jeton
        res = cc.rpc({"jsonrpc": "2.0", "id": 1, "method": "getTransactionsForAddress", "params": [pair, opts]}) or {}
        pages += 1
        for tx in res.get("data") or []:
            n += 1
            msg = (tx.get("transaction") or {}).get("message") or {}
            cles = msg.get("accountKeys") or []
            signataires = sum(1 for k in cles if isinstance(k, dict) and k.get("signer"))
            payeur = (cles[0].get("pubkey") if cles and isinstance(cles[0], dict) else None)
            a = cc.analyser(tx, pair, mint, V or 0.0, t0)
            age = (tx.get("blockTime") or t0) - t0
            if a:
                ev.append([age, tx.get("version"), [[o, d, x] for o, d, x in a[4]], a[3], a[5], signataires, payeur])
            else:
                ev.append([age, tx.get("version"), [], None, None, signataires, payeur])
        jeton = res.get("paginationToken")
        if not jeton:
            break
    return ev, n, bool(jeton)


def main():
    os.makedirs(D, exist_ok=True)
    faits = set()
    for f in os.listdir(D):
        if f.endswith(".jsonl"):
            for ligne in open(os.path.join(D, f), encoding="utf-8"):
                try:
                    faits.add(json.loads(ligne)["pair"])
                except Exception:  # noqa: BLE001
                    pass
    depenses: deque = deque()                       # (heure, credits)
    print("v1_enregistreur: demarre, %d pools deja enregistres" % len(faits), flush=True)
    while True:
        maintenant = time.time()
        while depenses and depenses[0][0] < maintenant - 86400:
            depenses.popleft()
        if sum(x for _, x in depenses) >= PLAFOND_JOUR:
            time.sleep(300)
            continue
        try:
            todo = nouveaux(faits, maintenant)
        except Exception as exc:  # noqa: BLE001
            print("v1_enregistreur: lecture base impossible : %s" % str(exc)[:120], flush=True)
            time.sleep(60)
            continue
        for pair, mint, t0, V in todo:
            try:
                ev, n, tronque = lire(pair, mint, t0, V)
                ligne = {"pair": pair, "mint": mint, "naissance": t0, "V": V, "n_tx": n, "tronque": tronque, "tx": ev}
            except Exception as exc:  # noqa: BLE001
                ligne = {"pair": pair, "mint": mint, "naissance": t0, "erreur": str(exc)[:160]}
                n = 0
            nom = dt.datetime.fromtimestamp(t0, dt.timezone.utc).strftime("%Y%m%d")
            with open(os.path.join(D, nom + ".jsonl"), "a", encoding="utf-8") as f:
                f.write(json.dumps(ligne) + "\n")
            faits.add(pair)
            depenses.append((time.time(), max(10, n // 10)))
            if sum(x for _, x in depenses) >= PLAFOND_JOUR:
                print("v1_enregistreur: plafond de %d credits sur 24 h atteint, pause" % PLAFOND_JOUR, flush=True)
                break
        time.sleep(30)


if __name__ == "__main__":
    main()
