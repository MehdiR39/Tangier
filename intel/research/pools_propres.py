"""Assainir les donnees de pool AVANT toute mesure : quel jeton en face, et quelle offre.

RAISON D ETRE. Le 13/09 au soir, un balayage de 1 866 combinaisons a designe une seule survivante :
« petite capitalisation ET gros pool ». Elle n a jamais tire un seul ticket en neuf heures. La
cause n etait pas le marche, c etait une colonne : `solana_prix_chaine.reserve_sol` comptait les
unites du second compte du pool SANS verifier que ce second jeton etait du WSOL. 9,9 % des pools
n en sont pas, et la pollution se concentre exactement dans la queue haute -- la ou une regle
« gros pool » va chercher. Un pool annonce a 2 060 964 SOL, soit 200 M EUR pour un jeton a 43 000 $.

Ce module etablit deux tables de reference que toute mesure ulterieure doit joindre :

  pool_quote(pool, quote_mint, est_sol)   le VRAI second jeton de chaque pool PumpSwap
  mint_offre(mint, offre, decimales)      l offre totale reelle de chaque jeton

POURQUOI L OFFRE AUSSI. Elle n est pas constante chez pump.fun : mediane 9,99e8 mais etendue de
7,55e8 a 2,00e9, et 38 % seulement a 1 % d un milliard. La supposer egale a un milliard fausse la
capitalisation jusqu a un facteur 2. Le moteur live la lit a chaque decision et avait donc raison ;
c est la recherche hors-ligne qui se serait trompee.

DEUX LECTURES EN LOT, pas une par jeton :
  - le compte de pool porte `quote_mint` en clair a l offset 43+32 ;
  - le compte de mint porte l offre en u64 petit-boutiste a l offset 36..44, les decimales en 44.
    Token-2022 garde cette base et ajoute ses extensions apres, donc l offset tient pour les deux.
Soit 40 appels au lieu de 4 000. Controle contre `getTokenSupply` sur un echantillon : ecart nul.

CE MODULE N ACHETE RIEN, NE VEND RIEN, NE SIGNE RIEN.

Usage :
    python -m intel.research.pools_propres
"""
from __future__ import annotations

import argparse
import base64
import json
import random
import sqlite3
import struct
import sys
import time
import urllib.request

sys.path.insert(0, "/app")

import base58

OFF_QUOTE = 43 + 32          # 8 discriminant + 1 bump + 2 index + 32 createur + 32 base_mint
OFF_OFFRE = 36               # disposition SPL Token : supply en u64 petit-boutiste


def rpc(url: str, methode: str, params: list):
    """Un appel JSON-RPC, avec quelques reprises. Renvoie None plutot que de lever.

    On distingue volontairement « pas de reponse » de « reponse vide » : confondre les deux a deja
    fait conclure qu un contrat n emettait aucun evenement alors que le noeud repondait
    `limit exceeded` (S6).
    """
    corps = json.dumps({"jsonrpc": "2.0", "id": 1, "method": methode, "params": params}).encode()
    req = urllib.request.Request(url, data=corps, headers={"content-type": "application/json"})
    for essai in range(4):
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                j = json.loads(r.read()) or {}
                if j.get("error"):
                    return None
                return j.get("result")
        except Exception:  # noqa: BLE001
            time.sleep(1.5 * (essai + 1))
    return None


def etiqueter_pools(c: sqlite3.Connection, url: str) -> None:
    """Le vrai `quote_mint` de chaque pool vu dans `solana_prix_chaine`."""
    from intel.execution.solana import SOL_MINT

    c.execute("CREATE TABLE IF NOT EXISTS pool_quote("
              "  pool TEXT PRIMARY KEY, quote_mint TEXT, est_sol INTEGER, ts INTEGER)")
    c.commit()
    deja = {r[0] for r in c.execute("SELECT pool FROM pool_quote")}
    pools = [r[0] for r in c.execute("SELECT DISTINCT pair_id FROM solana_prix_chaine")
             if r[0] and r[0] not in deja]
    print("  pools a etiqueter : %d (%d deja connus)" % (len(pools), len(deja)), flush=True)
    now = int(time.time())
    for i in range(0, len(pools), 100):
        lot = pools[i:i + 100]
        vals = ((rpc(url, "getMultipleAccounts", [lot, {"encoding": "base64"}]) or {})
                .get("value") or [])
        for j, p in enumerate(lot):
            q = None
            try:
                d = base64.b64decode(vals[j]["data"][0])
                q = base58.b58encode(d[OFF_QUOTE:OFF_QUOTE + 32]).decode()
            except Exception:  # noqa: BLE001
                pass
            c.execute("INSERT OR REPLACE INTO pool_quote VALUES(?,?,?,?)",
                      (p, q, 1 if q == SOL_MINT else 0, now))
        c.commit()
    n = c.execute("SELECT COUNT(*) FROM pool_quote").fetchone()[0]
    k = c.execute("SELECT COUNT(*) FROM pool_quote WHERE est_sol=1").fetchone()[0]
    print("  %d pools · %d adosses au SOL (%.1f %%) · %d NON"
          % (n, k, 100 * k / n if n else 0, n - k))


def lire_offres(c: sqlite3.Connection, url: str) -> None:
    """L offre totale de chaque jeton dont on a une courbe sur un pool adosse au SOL."""
    c.execute("CREATE TABLE IF NOT EXISTS mint_offre("
              "  mint TEXT PRIMARY KEY, offre REAL, decimales INTEGER)")
    c.commit()
    deja = {r[0] for r in c.execute("SELECT mint FROM mint_offre")}
    mints = [r[0] for r in c.execute(
        "SELECT DISTINCT p.mint FROM solana_prix_chaine p"
        " JOIN pool_quote q ON q.pool = p.pair_id AND q.est_sol = 1"
        " WHERE p.mint IS NOT NULL") if r[0] not in deja]
    print("  offres a lire : %d (%d deja connues)" % (len(mints), len(deja)), flush=True)
    for i in range(0, len(mints), 100):
        lot = mints[i:i + 100]
        vals = ((rpc(url, "getMultipleAccounts", [lot, {"encoding": "base64"}]) or {})
                .get("value") or [])
        for j, m in enumerate(lot):
            try:
                d = base64.b64decode(vals[j]["data"][0])
                brut = struct.unpack("<Q", d[OFF_OFFRE:OFF_OFFRE + 8])[0]
                dec = d[OFF_OFFRE + 8]
                c.execute("INSERT OR REPLACE INTO mint_offre VALUES(?,?,?)",
                          (m, brut / (10 ** dec), dec))
            except Exception:  # noqa: BLE001
                pass
        c.commit()


def controler(c: sqlite3.Connection, url: str, n: int = 15) -> None:
    """La lecture en lot dit-elle la meme chose que `getTokenSupply` ? Sinon tout le reste est faux."""
    lus = [(r[0], r[1]) for r in c.execute("SELECT mint, offre FROM mint_offre")]
    if not lus:
        return
    random.seed(5)
    ecarts = []
    for m, offre in random.sample(lus, min(n, len(lus))):
        r = rpc(url, "getTokenSupply", [m])
        try:
            vrai = float(r["value"]["uiAmountString"])
            if vrai:
                ecarts.append(abs(vrai - offre) / vrai)
        except Exception:  # noqa: BLE001
            pass
    v = sorted(x[1] for x in lus)
    k = len(v)
    print("  CONTROLE sur %d jetons contre getTokenSupply : ecart max %.2e"
          % (len(ecarts), max(ecarts) if ecarts else -1))
    print("  %d offres · mediane %.4e · p10 %.4e · p90 %.4e"
          % (k, v[k // 2], v[k // 10], v[9 * k // 10]))


def main() -> None:
    from intel.execution.solana import rpc_url

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="/app/db/intel.sqlite")
    a = ap.parse_args()
    url = rpc_url()
    if not url:
        print("  pas de noeud RPC configure")
        return
    c = sqlite3.connect(a.db)
    etiqueter_pools(c, url)
    print()
    lire_offres(c, url)
    print()
    controler(c, url)


if __name__ == "__main__":
    main()
