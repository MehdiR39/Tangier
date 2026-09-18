"""Qui detient le stock a l instant ou le moteur achete ? Enregistrement VERS L AVANT.

POURQUOI (§3.81). Les vidages font l essentiel de la perte, et rien de ce qu on mesurait a l entree
ne les separe. Mais leur mecanisme est connu : la premiere vente d un vidage fait souvent 5 a 37 %
de l offre du jeton en UNE transaction. Ce stock etait donc dans un portefeuille AVANT qu on achete.
C est la seule variable jamais mesuree qui ait une raison mecanique de separer.

POURQUOI VERS L AVANT. Sur l historique c est impossible : les vendeurs ont vendu, et les soldes
actuels d un jeton vide ne disent plus rien de ce qu ils etaient a T+60 s.

CE QUE FAIT CE SCRIPT, pour chaque lancement vu par le flux (`solana_stream_launches`) :
  a T+~60 s  les 20 plus gros comptes du jeton, leur proprietaire, l offre, les reserves du pool ;
  a +240 s   les reserves du pool a nouveau (l issue, a la duree de detention du moteur) ;
  a +480 s   idem.
Il ne lit la base du moteur qu en lecture seule et ecrit dans SA base, `detenteurs.sqlite`. Il
n achete rien, ne signe rien, et ne depend ni de `pool_quote` ni du collecteur pour l issue.

Lancement : python -m intel.research.detenteurs   (tourne jusqu a ce qu on l arrete)
"""
from __future__ import annotations

import base64
import json
import os
import sqlite3
import time
import urllib.request

import base58

PAMM = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
WSOL = "So11111111111111111111111111111111111111112"
OFF_QUOTE_MINT = 43 + 32
OFF_BASE_TA = 43 + 32 * 3
BASE_MOTEUR = os.environ.get("INTEL_DB", "/app/db/intel.sqlite")
BASE_ICI = os.environ.get("DETENTEURS_DB", "/app/db/detenteurs.sqlite")
RELEVES = (240, 480)


def rpc(methode, params):
    url = os.environ["SOLANA_RPC_URL"]
    corps = json.dumps({"jsonrpc": "2.0", "id": 1, "method": methode, "params": params}).encode()
    for essai in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(
                    url, data=corps, headers={"Content-Type": "application/json"}), timeout=20) as r:
                j = json.load(r)
            # une erreur n est pas un resultat vide (§6)
            if "error" in j:
                raise RuntimeError(str(j["error"])[:120])
            return j.get("result")
        except Exception as exc:  # noqa: BLE001
            dernier = exc
            time.sleep(1.5 * (essai + 1))
    raise RuntimeError(str(dernier)[:120])


def schema(c):
    c.execute("CREATE TABLE IF NOT EXISTS releve(mint TEXT PRIMARY KEY, ts_lancement INTEGER,"
              " ts INTEGER, age_s INTEGER, pool TEXT, quote_mint TEXT, offre REAL, pool_base REAL,"
              " pool_quote REAL, prix REAL, top1 REAL, top5 REAL, top10 REAL, n_1pct INTEGER,"
              " n_5pct INTEGER, identiques INTEGER, comptes TEXT, erreur TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS issue(mint TEXT, delai_s INTEGER, ts INTEGER,"
              " pool_base REAL, pool_quote REAL, prix REAL, PRIMARY KEY(mint, delai_s))")
    c.commit()


def lire_pool(pool):
    v = (rpc("getAccountInfo", [pool, {"encoding": "base64"}]) or {}).get("value")
    if not v or v.get("owner") != PAMM:
        return None
    d = base64.b64decode(v["data"][0])
    from intel.engines.prix_chaine import reserve_virtuelle
    return {"virtuelle": reserve_virtuelle(d),
            "quote_mint": base58.b58encode(d[OFF_QUOTE_MINT:OFF_QUOTE_MINT + 32]).decode(),
            "base_ta": base58.b58encode(d[OFF_BASE_TA:OFF_BASE_TA + 32]).decode(),
            "quote_ta": base58.b58encode(d[OFF_BASE_TA + 32:OFF_BASE_TA + 64]).decode()}


def reserves(base_ta, quote_ta):
    vals = (rpc("getMultipleAccounts", [[base_ta, quote_ta], {"encoding": "jsonParsed", "commitment": "processed"}])
            or {}).get("value") or []
    b = float(vals[0]["data"]["parsed"]["info"]["tokenAmount"]["uiAmountString"])
    q = float(vals[1]["data"]["parsed"]["info"]["tokenAmount"]["uiAmountString"])
    return b, q


def est_portefeuille(proprio) -> bool:
    """Un portefeuille est une cle SUR la courbe ; un pool, un coffre ou une courbe de lancement est
    une adresse de programme, HORS de la courbe. Sans ce tri, le coffre d un autre pool passerait
    pour un gros detenteur (vu le 15/09 au premier essai)."""
    if not proprio:
        return False
    from solders.pubkey import Pubkey
    try:
        return Pubkey.from_string(proprio).is_on_curve()
    except Exception:  # noqa: BLE001
        return False


def concentration(comptes, offre, pool, base_ta, portefeuille=est_portefeuille):
    """Parts de l offre detenues par des PORTEFEUILLES, hors du pool.

    `comptes` : [(adresse, proprietaire, montant)]. Rend (top1, top5, top10, n >= 1 %, n >= 5 %,
    identiques) ; `identiques` compte les portefeuilles >= 1 % dont le solde en egale un autre a
    0,1 % pres -- la signature d un bundle reparti sur plusieurs adresses (7yyngnwg, 15/09 : quatre
    portefeuilles a exactement 18,7 % chacun).
    """
    hors = sorted((m for a, o, m in comptes if a != base_ta and o != pool and portefeuille(o)), reverse=True)
    part = [m / offre for m in hors] if offre else []
    gros = [p for p in part if p >= 0.01]
    identiques = sum(1 for i, p in enumerate(gros)
                     if any(j != i and abs(p - q) <= 0.001 * p for j, q in enumerate(gros)))
    return (sum(part[:1]), sum(part[:5]), sum(part[:10]),
            len(gros), sum(1 for p in part if p >= 0.05), identiques)


def relever(ici, moteur, mint, ts_lancement, now):
    pool = moteur.execute("SELECT pair_id FROM solana_prix_chaine WHERE mint=? ORDER BY ts DESC LIMIT 1",
                          (mint,)).fetchone()
    if not pool:
        return False                       # le collecteur n a pas encore resolu le pool : on reessaiera
    pool = pool[0]
    ligne = {"mint": mint, "ts_lancement": ts_lancement, "ts": now, "age_s": now - ts_lancement, "pool": pool}
    try:
        p = lire_pool(pool)
        if not p:
            raise RuntimeError("pas un pool PumpSwap")
        offre = float((rpc("getTokenSupply", [mint]) or {}).get("value", {}).get("uiAmountString") or 0)
        gros = (rpc("getTokenLargestAccounts", [mint]) or {}).get("value") or []
        adresses = [g["address"] for g in gros]
        proprios = (rpc("getMultipleAccounts", [adresses, {"encoding": "jsonParsed"}]) or {}).get("value") or []
        comptes = []
        for g, v in zip(gros, proprios):
            try:
                o = v["data"]["parsed"]["info"]["owner"]
            except Exception:  # noqa: BLE001
                o = None
            comptes.append((g["address"], o, float(g.get("uiAmountString") or 0)))
        b, q = reserves(p["base_ta"], p["quote_ta"])
        t1, t5, t10, n1, n5, ident = concentration(comptes, offre, pool, p["base_ta"])
        ligne.update(quote_mint=p["quote_mint"], offre=offre, pool_base=b, pool_quote=q,
                     prix=((q + p["virtuelle"]) / b if b else None), top1=t1, top5=t5, top10=t10, n_1pct=n1, n_5pct=n5,
                     identiques=ident, comptes=json.dumps(comptes), erreur=None)
    except Exception as exc:  # noqa: BLE001
        ligne["erreur"] = str(exc)[:200]
    cols = ",".join(ligne)
    ici.execute("INSERT OR REPLACE INTO releve(%s) VALUES(%s)" % (cols, ",".join("?" * len(ligne))),
                list(ligne.values()))
    ici.commit()
    return True


def issues(ici, now):
    for delai in RELEVES:
        dus = ici.execute(
            "SELECT r.mint, r.pool, r.ts FROM releve r LEFT JOIN issue i ON i.mint=r.mint AND i.delai_s=?"
            " WHERE r.erreur IS NULL AND i.mint IS NULL AND r.ts + ? <= ? AND r.ts + ? + 120 >= ?",
            (delai, delai, now, delai, now)).fetchall()
        for mint, pool, ts in dus:
            try:
                p = lire_pool(pool)
                b, q = reserves(p["base_ta"], p["quote_ta"])
                ici.execute("INSERT OR REPLACE INTO issue VALUES(?,?,?,?,?,?)",
                            (mint, delai, now, b, q, ((q + p["virtuelle"]) / b if b else None)))
            except Exception:  # noqa: BLE001
                # un pool vide ou illisible est une issue en soi : on la note, prix nul
                ici.execute("INSERT OR REPLACE INTO issue VALUES(?,?,?,?,?,?)", (mint, delai, now, None, None, 0.0))
        ici.commit()


def main():
    ici = sqlite3.connect(BASE_ICI, timeout=30)
    schema(ici)
    moteur = sqlite3.connect("file:%s?mode=ro" % BASE_MOTEUR, uri=True, timeout=30)
    print("detenteurs: demarre", flush=True)
    while True:
        now = int(time.time())
        try:
            faits = {r[0] for r in ici.execute("SELECT mint FROM releve WHERE ts > ?", (now - 3600,))}
            for mint, ts in moteur.execute(
                    "SELECT mint, MIN(ts) FROM solana_stream_launches WHERE ts BETWEEN ? AND ? GROUP BY mint",
                    (now - 120, now - 55)).fetchall():
                if mint not in faits:
                    relever(ici, moteur, mint, int(ts), now)
            issues(ici, now)
        except Exception as exc:  # noqa: BLE001
            print("detenteurs: tour rate (%s)" % str(exc)[:120], flush=True)
        time.sleep(5)


if __name__ == "__main__":
    main()
