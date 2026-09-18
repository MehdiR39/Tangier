"""Qui a achete gros dans les premieres secondes du pool ? Reconstruction sur l historique.

POURQUOI (§3.81). Dans 15 vidages sur 22, le premier gros vendeur detenait deja son stock a notre
achat, et son compte de jetons est ne entre T-1 s et T+25 s apres la migration : ces portefeuilles
achetent dans les toutes premieres secondes du pool. Ces achats sont inscrits dans les transactions
du pool, donc on peut les relire pour chaque jeton passe -- et savoir aujourd hui, sur cinq jours
d historique, si « un gros acheteur des premieres secondes » annonce le vidage.

CE QUE LE PREMIER ESSAI A APPRIS (15/09). Lire les transactions du POOL ne montre rien : les stocks
des vidages n y sont pas achetes. Relu transaction par transaction sur six vidages, ils arrivent de
deux facons, toutes deux au moment de la migration :
  - achat du dernier morceau de la courbe pump.fun a T-1 s (HIKKO 52 %, GOLDGOOSE 51 % en deux
    portefeuilles) ;
  - TRANSFERT vers un portefeuille neuf entre T+0 et T+12 s (cashcaton 20 %, BBRAIN 11 %, CHILLGPT
    11 %, TROLLGPT 48 %).
Les deux passent par l adresse du JETON. Lue sur la fenetre [T-5 s, T+30 s], elle montre le vendeur
avec le bon montant dans les quatre cas testes.

LIMITE CONNUE. Un stock achete sur la courbe bien avant la migration et garde tel quel n apparait
pas dans la fenetre ; c est ce que couvre l enregistreur vers l avant (`detenteurs.py`), qui lit les
soldes. Ce qui est mesure ici est donc un minorant.

COMMENT. Helius `getTransactionsForAddress` sur l adresse du jeton, ordre chronologique, fenetre
[naissance - 5 s, naissance + 30 s], 100 transactions par appel, au plus 8 pages. Pour chaque
transaction : variation du solde de chaque proprietaire. On ne garde que les PORTEFEUILLES (cle sur
la courbe), jamais le pool ni un compte de programme. Instantanes des positions nettes a +10 et +30 s.

Sortie : data/recherche/premieres_secondes.jsonl, une ligne par jeton, relancable (reprend ou il en
etait).
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
import urllib.request

COFFRE = os.environ.get("COFFRE", "/app/data/recherche/archive_solana.sqlite")
SORTIE = os.environ.get("PREMIERES_SORTIE", "/app/data/recherche/sacs_migration.jsonl")
INSTANTS = (10, 30)
PAGES_MAX = 8


def rpc(corps):
    url = os.environ["SOLANA_RPC_URL"]
    for essai in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(
                    url, data=json.dumps(corps).encode(), headers={"Content-Type": "application/json"}),
                    timeout=60) as r:
                j = json.load(r)
            if "error" in j:
                raise RuntimeError(str(j["error"])[:160])
            return j.get("result")
        except Exception as exc:  # noqa: BLE001
            dernier = exc
            time.sleep(2 * (essai + 1))
    raise RuntimeError(str(dernier)[:160])


def candidats(c):
    """Les jetons a reconstruire : tickets reels + tous les jetons du coffre dont on connait la
    naissance du pool (premiere lecture a moins de 20 s) et qui ont un verdict Telegram."""
    out = {}
    for mint, pair in c.execute("SELECT mint, pair_id FROM tg_lignes WHERE pair_id IS NOT NULL"):
        out[mint] = pair
    for mint, pair in c.execute(
            "SELECT p.mint, p.pair_id FROM solana_prix_chaine p JOIN tg_juges j ON j.mint=p.mint"
            " JOIN pool_quote q ON q.pool=p.pair_id AND q.est_sol=1"
            " GROUP BY p.pair_id HAVING MIN(p.age_s) <= 20"):
        out.setdefault(mint, pair)
    return out


def naissance(c, pair):
    r = c.execute("SELECT MIN(ts - age_s) FROM solana_prix_chaine WHERE pair_id=? AND age_s <= 60", (pair,)).fetchone()
    return r[0] if r and r[0] else None


def reconstruire(mint, pair, t0):
    positions: dict[str, float] = {}
    instants = {}
    n_tx = 0
    fin_lue = None
    jeton = None
    page = 0
    prochains = list(INSTANTS)
    while page < PAGES_MAX:
        opts = {"transactionDetails": "full", "sortOrder": "asc", "limit": 100,
                "filters": {"blockTime": {"gte": t0 - 5, "lte": t0 + INSTANTS[-1]}},
                "encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}
        if jeton:
            opts["paginationToken"] = jeton
        res = rpc({"jsonrpc": "2.0", "id": 1, "method": "getTransactionsForAddress", "params": [mint, opts]}) or {}
        page += 1
        for tx in res.get("data") or []:
            bt = tx.get("blockTime") or t0
            while prochains and bt > t0 + prochains[0]:
                instants[prochains[0]] = sorted(positions.items(), key=lambda kv: -kv[1])[:25]
                prochains.pop(0)
            meta = tx.get("meta") or {}
            if meta.get("err"):
                continue
            n_tx += 1
            fin_lue = bt - t0
            avant = {b.get("owner"): float(b["uiTokenAmount"]["uiAmountString"] or 0)
                     for b in meta.get("preTokenBalances", []) if b.get("mint") == mint}
            apres = {b.get("owner"): float(b["uiTokenAmount"]["uiAmountString"] or 0)
                     for b in meta.get("postTokenBalances", []) if b.get("mint") == mint}
            for proprio in set(avant) | set(apres):
                if not proprio or proprio == pair:
                    continue
                d = apres.get(proprio, 0.0) - avant.get(proprio, 0.0)
                if d:
                    positions[proprio] = positions.get(proprio, 0.0) + d
        jeton = res.get("paginationToken")
        if not jeton:
            break
    for s in prochains:                         # instants atteints sans nouvelle transaction apres
        instants[s] = sorted(positions.items(), key=lambda kv: -kv[1])[:25]
    from intel.research.detenteurs import est_portefeuille
    instants = {k: [(w, q) for w, q in v if w != pair and est_portefeuille(w)] for k, v in instants.items()}
    tronque = bool(jeton)                       # 8 pages lues sans atteindre la fin de la fenetre
    return {"mint": mint, "pair": pair, "naissance": t0, "n_tx": n_tx, "fin_lue_s": fin_lue,
            "tronque": tronque, "instants": {str(k): v for k, v in instants.items()}}


def main():
    c = sqlite3.connect("file:%s?mode=ro" % COFFRE, uri=True, timeout=60)
    faits = set()
    if os.path.exists(SORTIE):
        for ligne in open(SORTIE, encoding="utf-8"):
            try:
                faits.add(json.loads(ligne)["mint"])
            except Exception:  # noqa: BLE001
                pass
    reels = {r[0] for r in c.execute("SELECT mint FROM tg_lignes")}
    todo = sorted(((m, p) for m, p in candidats(c).items() if m not in faits), key=lambda mp: mp[0] not in reels)
    print("premieres_secondes: %d jetons a reconstruire (%d deja faits)" % (len(todo), len(faits)), flush=True)
    t_debut = time.time()
    for i, (mint, pair) in enumerate(todo):
        t0 = naissance(c, pair)
        if not t0:
            continue
        try:
            ligne = reconstruire(mint, pair, t0)
        except Exception as exc:  # noqa: BLE001
            ligne = {"mint": mint, "pair": pair, "naissance": t0, "erreur": str(exc)[:160]}
        with open(SORTIE, "a", encoding="utf-8") as f:
            f.write(json.dumps(ligne) + "\n")
        if i % 25 == 24:
            print("premieres_secondes: %d/%d en %.0f s" % (i + 1, len(todo), time.time() - t_debut), flush=True)
        time.sleep(0.3)
    print("premieres_secondes: FINI", flush=True)


if __name__ == "__main__":
    main()
