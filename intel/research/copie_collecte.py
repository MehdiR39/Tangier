"""Copier les portefeuilles gagnants : etape 1, relire chaque echange des 15 premieres minutes du pool.

POURQUOI (15/09, demande de l operateur apres la recherche internet). La copie de portefeuilles est la
seule idee du marche memecoin jamais testee ici. Nos prix sont lus toutes les 10 s sans les acheteurs :
pour savoir qui achete, qui gagne, et ce qu aurait donne le fait de le suivre, il faut chaque echange.

COMMENT. Helius `getTransactionsForAddress` sur l adresse du POOL, ordre chronologique, fenetre
[naissance - 5 s, naissance + 900 s], transactions REUSSIES seulement (a la sonde, sans ce filtre,
60 pages de 100 ne depassaient pas 101 a 432 s sur 5 pools sur 12), 1 000 par appel, au plus PAGES_MAX pages. Pour chaque
transaction reussie qui change les coffres du pool :
  - prix apres = (coffre SOL + reserve virtuelle) / coffre jetons (§3.83), a la resolution de la
    transaction ;
  - chaque proprietaire (hors pool) dont le solde du jeton bouge recoit sa part du SOL entre ou sorti
    du coffre, au prorata de sa variation de jetons de meme sens.
Les pools sont ceux de la table du grand balayage (3 157), dans l ordre de naissance.

Sortie : data/recherche/copie/echanges.jsonl, une ligne par pool, relancable. `--sonde N` lit N pools
et affiche le volume, sans rien ecrire.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

D = os.environ.get("COPIE_DIR", "/app/data/recherche/copie")
SORTIE = os.path.join(D, "echanges.jsonl")
WSOL = "So11111111111111111111111111111111111111112"
FENETRE_S = 900
PAR_PAGE = 1000          # maximum documente ; les transactions echouees sont filtrees a la source
PAGES_MAX = 20
# Solana a active les transactions « version 1 » le 15/09 a 01h04 UTC (§3.90). Un client qui demande
# 0 se voit refuser TOUT le pool des qu une seule transactionversionnee s y trouve (-32015), il ne
# perd pas juste cette transaction. La valeur par defaut reste 0 pour ne rien changer aux collectes
# deja faites ; les appelants recents (v1_enregistreur, flux_latence) montent a 1.
VERSION_MAX = 0


def rpc(corps):
    url = os.environ["SOLANA_RPC_URL"]
    dernier = None
    for essai in range(6):
        try:
            with urllib.request.urlopen(urllib.request.Request(
                    url, data=json.dumps(corps).encode(), headers={"Content-Type": "application/json"}),
                    timeout=90) as r:
                j = json.load(r)
            if "error" in j:
                raise RuntimeError(str(j["error"])[:160])
            return j.get("result")
        except Exception as exc:  # noqa: BLE001
            dernier = exc
            time.sleep(2 * (essai + 1))
    raise RuntimeError(str(dernier)[:160])


def _ui(b):
    return float(b["uiTokenAmount"].get("uiAmountString") or 0)


def analyser(tx, pair, mint, V, t0):
    """Une transaction -> (age, slot, prix_apres, q_apres, [(proprio, d_jetons, d_sol)], b_apres) ou None."""
    meta = tx.get("meta") or {}
    if meta.get("err"):
        return None
    pre, post = meta.get("preTokenBalances") or [], meta.get("postTokenBalances") or []

    def coffre(liste, m):
        for b in liste:
            if b.get("owner") == pair and b.get("mint") == m:
                return _ui(b)
        return None

    b0, b1 = coffre(pre, mint), coffre(post, mint)
    q0, q1 = coffre(pre, WSOL), coffre(post, WSOL)
    if b1 is None or q1 is None or b0 is None or q0 is None:
        return None
    db, dq = b1 - b0, q1 - q0
    if db == 0 and dq == 0:
        return None
    prix = (q1 + V) / b1 if b1 > 0 else None
    if db * dq >= 0:
        # creation du pool, ajout ou retrait de liquidite : les deux coffres bougent dans le meme sens.
        # Ce n est pas un echange (vu le 15/09 : la creation comptee comme une vente de 4 948 SOL).
        return (tx.get("blockTime", t0) - t0, tx.get("slot"), prix, q1, [], b1)
    avant = {b.get("owner"): _ui(b) for b in pre if b.get("mint") == mint and b.get("owner") != pair}
    apres = {b.get("owner"): _ui(b) for b in post if b.get("mint") == mint and b.get("owner") != pair}
    deltas = {o: apres.get(o, 0.0) - avant.get(o, 0.0) for o in set(avant) | set(apres)}
    # achat : le coffre perd des jetons, les proprietaires en gagnent ; vente : l inverse
    sens = 1.0 if db < 0 else -1.0
    memes = {o: d for o, d in deltas.items() if o and d * sens > 0}
    tot = sum(abs(d) for d in memes.values())
    parts = []
    if tot > 0 and dq != 0:
        for o, d in memes.items():
            parts.append((o, d, -dq * abs(d) / tot))       # SOL vu du portefeuille : achat < 0
    return (tx.get("blockTime", t0) - t0, tx.get("slot"), prix, q1, parts, b1)


def lire_pool(p):
    pair, mint, t0, V = p["pair"], p["mint"], p["naissance"], p["V"]
    jeton, pages, n_tx, lignes, fin_lue = None, 0, 0, [], None
    while pages < PAGES_MAX:
        opts = {"transactionDetails": "full", "sortOrder": "asc", "limit": PAR_PAGE,
                "filters": {"blockTime": {"gte": int(t0) - 5, "lte": int(t0) + FENETRE_S}, "status": "succeeded"},
                "encoding": "jsonParsed", "maxSupportedTransactionVersion": VERSION_MAX}
        if jeton:
            opts["paginationToken"] = jeton
        res = rpc({"jsonrpc": "2.0", "id": 1, "method": "getTransactionsForAddress", "params": [pair, opts]}) or {}
        pages += 1
        for tx in res.get("data") or []:
            n_tx += 1
            fin_lue = (tx.get("blockTime") or t0) - t0
            a = analyser(tx, pair, mint, V, t0)
            if a:
                lignes.append(a)
        jeton = res.get("paginationToken")
        if not jeton:
            break
    return {"pair": pair, "mint": mint, "naissance": t0, "V": V, "n_tx": n_tx, "pages": pages,
            "tronque": bool(jeton), "fin_lue_s": fin_lue,
            # [age, slot, prix apres, coffre SOL apres, [[proprietaire, d_jetons, d_SOL]], coffre jetons apres]
            # parts vide = creation ou mouvement de liquidite (le prix reste utilisable)
            "echanges": [[round(a, 3) if isinstance(a, float) else a, s, pr, q,
                          [[o, d, round(x, 9)] for o, d, x in parts], b] for a, s, pr, q, parts, b in lignes]}


def main():
    pools = json.load(open(os.path.join(D, "pools.json")))
    if "--sonde" in sys.argv:
        n = int(sys.argv[sys.argv.index("--sonde") + 1])
        pas = max(1, len(pools) // n)
        for p in pools[::pas][:n]:
            t = time.time()
            r = lire_pool(p)
            nb = len(r["echanges"])
            nw = len({o for e in r["echanges"] for o, _, _ in e[4]})
            print("%s tx=%-5d pages=%-3d echanges=%-5d portefeuilles=%-4d tronque=%s fin=%s %.1f s" % (
                p["pair"][:8], r["n_tx"], r["pages"], nb, nw, r["tronque"], r["fin_lue_s"], time.time() - t), flush=True)
        return
    faits = set()
    if os.path.exists(SORTIE):
        for ligne in open(SORTIE, encoding="utf-8"):
            try:
                faits.add(json.loads(ligne)["pair"])
            except Exception:  # noqa: BLE001
                pass
    todo = [p for p in pools if p["pair"] not in faits]
    if "--premiers" in sys.argv:
        todo = todo[:int(sys.argv[sys.argv.index("--premiers") + 1])]
    print("copie_collecte: %d pools a lire (%d deja faits)" % (len(todo), len(faits)), flush=True)
    import threading
    from concurrent.futures import ThreadPoolExecutor
    verrou = threading.Lock()
    etat = {"n": 0, "erreurs_suite": 0, "credits": 0}
    t_debut = time.time()

    def un(p):
        # le moteur partage le forfait Helius : plusieurs pools en erreur d affilee = on s arrete
        if etat["erreurs_suite"] >= 5:
            return
        try:
            ligne = lire_pool(p)
            err = False
        except Exception as exc:  # noqa: BLE001
            ligne = {"pair": p["pair"], "mint": p["mint"], "naissance": p["naissance"], "erreur": str(exc)[:160]}
            err = True
        with verrou:
            etat["erreurs_suite"] = etat["erreurs_suite"] + 1 if err else 0
            if err and etat["erreurs_suite"] >= 5:
                print("copie_collecte: 5 pools en erreur d affilee, ARRET : %s" % ligne["erreur"], flush=True)
                return
            etat["n"] += 1
            etat["credits"] += 10 * max(1, -(-ligne.get("n_tx", 0) // 100))
            with open(SORTIE, "a", encoding="utf-8") as f:
                f.write(json.dumps(ligne) + "\n")
            if etat["n"] % 50 == 0:
                print("copie_collecte: %d/%d en %.0f s, ~%d credits" % (
                    etat["n"], len(todo), time.time() - t_debut, etat["credits"]), flush=True)

    with ThreadPoolExecutor(3) as ex:
        list(ex.map(un, todo))
    print("copie_collecte: FINI (%d pools, ~%d credits)" % (etat["n"], etat["credits"]), flush=True)


if __name__ == "__main__":
    main()
