"""Relire TOUTE la phase courbe pump.fun sur deux jours (15/09 soir, accord de l operateur : « vas-y »).

POURQUOI (journal §3.88). En argent reel, frais compris, les 325 bons portefeuilles gagnent sur la COURBE pump.fun
(+3,9 % sur 16 101 SOL apres leur periode de selection) et perdent dans les pools (-3,3 %). Notre moteur n a jamais
trade la courbe, et les releves du 13-14/09 (`pump_prix`, un point toutes les 25 s, SOL douteux) ne suffisent pas.

COMMENT. Helius `getTransactionsForAddress` sur le PROGRAMME pump.fun, transactions reussies, 13/09 00h -> 15/09 00h
UTC, par tranches d une heure lues en parallele. Mesure avant lancement : 1 727 transactions par minute, soit
~250 000 credits par jour (10 par 100 transactions). Pour chaque jeton touche par une transaction :
  - compte de courbe = adresse derivee ["bonding-curve", mint] du programme ;
  - SOL de la courbe (lamports) et jetons de la courbe APRES la transaction, et leurs variations ;
  - chaque proprietaire (hors courbe) dont le solde du jeton bouge, avec sa part du SOL entre ou sorti, au prorata
    de ses jetons de meme sens (meme regle que les pools) ;
  - drapeau : PumpSwap appele dans la transaction (migration).
Sortie : data/recherche/courbe/AAAAMMJJ_HH.jsonl, une ligne par (transaction, jeton) :
  [heure bloc, slot, mint, lamports courbe apres, jetons courbe apres, d lamports, d jetons, [[proprio, d jetons,
   d SOL]], migration]
  (pour une creation ou une migration, les parts ont un SOL de 0 : seuls les jetons sont connus)
`--sonde` lit 60 s et affiche des controles sans rien ecrire.

REGLAGES DES COURBES (mesure sur les 3 premieres heures, 15/09) : 1 099 jetons sur 1 722 suivent exactement
(30 SOL + SOL de la courbe) / (jetons + 73 M), et finissent a 85,01 SOL ; 621 ont d autres reglages mais ne
depassent quasi jamais 10 SOL (15 jetons) ni 30 SOL (1).
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

PROG = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
PSWAP = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
WSOL = "So11111111111111111111111111111111111111112"
D = os.environ.get("COURBE_DIR", "/app/data/recherche/courbe")
DEBUT = int(dt.datetime(2026, 9, 13, tzinfo=dt.timezone.utc).timestamp())
FIN = int(dt.datetime(2026, 9, 15, tzinfo=dt.timezone.utc).timestamp())
PAGES_MAX = 400
_PDA: dict[str, str] = {}


def courbe_de(mint):
    c = _PDA.get(mint)
    if c is None:
        from solders.pubkey import Pubkey
        c = _PDA[mint] = str(Pubkey.find_program_address([b"bonding-curve", bytes(Pubkey.from_string(mint))],
                                                         Pubkey.from_string(PROG))[0])
    return c


def _ui(b):
    return float(b["uiTokenAmount"].get("uiAmountString") or 0)


def analyser(tx):
    meta = tx.get("meta") or {}
    msg = (tx.get("transaction") or {}).get("message") or {}
    cles = [k.get("pubkey") if isinstance(k, dict) else k for k in msg.get("accountKeys") or []]
    pre_l, post_l = meta.get("preBalances") or [], meta.get("postBalances") or []
    pre, post = meta.get("preTokenBalances") or [], meta.get("postTokenBalances") or []
    progs = {ins.get("programId") for ins in msg.get("instructions") or []}
    for g in meta.get("innerInstructions") or []:
        progs |= {ins.get("programId") for ins in g.get("instructions") or []}
    migration = PSWAP in progs
    mints = {b.get("mint") for b in pre + post if b.get("mint") and b.get("mint") != WSOL}
    out = []
    for m in mints:
        c = courbe_de(m)
        if c not in cles:
            continue
        i = cles.index(c)
        lam_av, lam_ap = (pre_l[i] if i < len(pre_l) else 0), (post_l[i] if i < len(post_l) else 0)
        tok_av = sum(_ui(b) for b in pre if b.get("mint") == m and b.get("owner") == c)
        tok_ap = sum(_ui(b) for b in post if b.get("mint") == m and b.get("owner") == c)
        d_lam, d_tok = lam_ap - lam_av, tok_ap - tok_av
        if d_lam == 0 and d_tok == 0:
            continue
        avant = {}
        for b in pre:
            if b.get("mint") == m and b.get("owner") != c:
                avant[b.get("owner")] = avant.get(b.get("owner"), 0.0) + _ui(b)
        apres = {}
        for b in post:
            if b.get("mint") == m and b.get("owner") != c:
                apres[b.get("owner")] = apres.get(b.get("owner"), 0.0) + _ui(b)
        deltas = {o: apres.get(o, 0.0) - avant.get(o, 0.0) for o in set(avant) | set(apres)}
        parts = []
        if d_lam * d_tok < 0:                                  # un echange : SOL et jetons en sens opposes
            sens = 1.0 if d_tok < 0 else -1.0                   # la courbe perd des jetons = achat
            memes = {o: d for o, d in deltas.items() if o and d * sens > 0}
            tot = sum(abs(d) for d in memes.values())
            if tot > 0:
                parts = [[o, d, round(-(d_lam / 1e9) * abs(d) / tot, 9)] for o, d in memes.items()]
        else:
            # creation (la courbe recoit SOL et jetons ensemble) ou migration : on garde qui recoit ou rend des
            # jetons, SOL inconnu (0). Sans ca, le createur est invisible (vu le 15/09 au premier essai).
            parts = [[o, d, 0.0] for o, d in deltas.items() if o and d]
        out.append([tx.get("blockTime"), tx.get("slot"), m, lam_ap, tok_ap, d_lam, d_tok, parts, migration])
    return out


def lire_tranche(t0, t1, ecrire=True):
    jeton, pages, n_tx, lignes = None, 0, 0, []
    while pages < PAGES_MAX:
        opts = {"transactionDetails": "full", "sortOrder": "asc", "limit": 1000, "encoding": "jsonParsed",
                "maxSupportedTransactionVersion": 0,
                "filters": {"blockTime": {"gte": t0, "lt": t1}, "status": "succeeded"}}
        if jeton:
            opts["paginationToken"] = jeton
        res = rpc({"jsonrpc": "2.0", "id": 1, "method": "getTransactionsForAddress", "params": [PROG, opts]}) or {}
        pages += 1
        for tx in res.get("data") or []:
            n_tx += 1
            lignes.extend(analyser(tx))
        jeton = res.get("paginationToken")
        if not jeton:
            break
    if ecrire:
        nom = dt.datetime.fromtimestamp(t0, dt.timezone.utc).strftime("%Y%m%d_%H")
        chemin = os.path.join(D, nom + ".jsonl")
        with open(chemin + ".part", "w", encoding="utf-8") as f:
            for l in lignes:
                f.write(json.dumps(l) + "\n")
        os.replace(chemin + ".part", chemin)
    return n_tx, len(lignes), bool(jeton), lignes


def main():
    if "--sonde" in sys.argv:
        t0 = DEBUT + 11 * 3600
        n_tx, n_l, tronque, lignes = lire_tranche(t0, t0 + 60, ecrire=False)
        print("sonde 60 s : %d transactions, %d lignes (transaction, jeton), tronque %s" % (n_tx, n_l, tronque))
        ech = [l for l in lignes if l[7]]
        ok = sum(1 for l in ech if abs(sum(p[1] for p in l[7]) + l[6]) <= 1e-6 * max(1.0, abs(l[6])))
        print("echanges avec acheteur/vendeur visible : %d ; jetons des traders = -jetons de la courbe : %d" % (len(ech), ok))
        for l in ech[:5]:
            px = abs(l[5] / 1e9) / abs(l[6]) if l[6] else None
            print("  %s SOL courbe apres %.3f · jetons courbe %.4g · d SOL %+.4f · prix paye %.3e SOL/jeton · migration %s" % (
                l[2][:8], l[3] / 1e9, l[4], l[5] / 1e9, px or 0, l[8]))
        print("jetons distincts : %d · migrations vues : %d" % (len({l[2] for l in lignes}), sum(1 for l in lignes if l[8])))
        return
    os.makedirs(D, exist_ok=True)
    faits = {f[:-6] for f in os.listdir(D) if f.endswith(".jsonl")}
    tranches = [t for t in range(DEBUT, FIN, 3600)
                if dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y%m%d_%H") not in faits]
    print("courbe_collecte: %d heures a lire" % len(tranches), flush=True)
    verrou, etat = threading.Lock(), {"h": 0, "tx": 0, "err": 0}
    t_debut = time.time()

    def une(t0):
        if etat["err"] >= 3:
            return
        try:
            n_tx, n_l, tronque, _ = lire_tranche(t0, t0 + 3600)
        except Exception as exc:  # noqa: BLE001
            with verrou:
                etat["err"] += 1
                print("courbe_collecte: ERREUR heure %d : %s" % (t0, str(exc)[:160]), flush=True)
            return
        with verrou:
            etat["h"] += 1
            etat["tx"] += n_tx
            print("courbe_collecte: %s %d tx, %d lignes%s · total %d h, %d tx, ~%d credits, %.0f s" % (
                dt.datetime.fromtimestamp(t0, dt.timezone.utc).strftime("%d/%m %Hh"), n_tx, n_l,
                " TRONQUE" if tronque else "", etat["h"], etat["tx"], etat["tx"] // 10, time.time() - t_debut), flush=True)

    with ThreadPoolExecutor(3) as ex:
        list(ex.map(une, tranches))
    print("courbe_collecte: FINI (%d heures, %d transactions, ~%d credits)" % (etat["h"], etat["tx"], etat["tx"] // 10), flush=True)


if __name__ == "__main__":
    main()
