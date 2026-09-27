"""UN SITE WEB REND-IL UN JETON PLUS SERIEUX ? La question de Mido, 18/09 au soir.

LA CONFUSION A LEVER D ABORD. « On a teste Telegram » designait dans ce projet les SIGNAUX DE
CHAINES Telegram -- quelqu un poste un jeton, on l achete. Ce n est pas du tout la question posee
ici, qui porte sur la METADONNEE du jeton : son createur a-t-il pris la peine de mettre un lien
vers un site, un Twitter, un Telegram ? **Ca n a jamais ete teste.** `features_lancement.py` liste
`a_site`, `a_twitter`, `a_telegram` dans sa documentation depuis le 09/09, mais aucun des trois n a
jamais ete implemente.

CE QUE DIT LA LITTERATURE, et qui sert de cadrage et non de conclusion. Kamat 2026 (pump.fun,
832 941 lancements, concordance 0,858) : Telegram HR 5,40 · capitalisation initiale 4,51 ·
Twitter 1,30 · **site 1,19**. Le site est donc l indice le plus FAIBLE des trois, et l effet mesure
porte sur la survie du jeton, pas sur le rendement d un acheteur apres couts. Les deux peuvent tres
bien diverger -- c est meme le fait central du projet : « le modele mesure la VIE, pas le danger ».

POURQUOI CETTE MESURE-CI N EST PAS PIEGEE, contrairement a celle de cet apres-midi. Les metadonnees
pump.fun sont des fichiers IPFS **immuables**, fixes a la creation du jeton. Les relire aujourd hui
rend donc exactement ce qui existait a l instant de la decision. C est l oppose du piege des comptes
fermes (§3.124), ou la LISIBILITE d aujourd hui dependait du resultat. Ici, rien de ce qu on lit ne
peut avoir change a cause de ce qui est arrive ensuite.

IL N ECRIT QUE DANS SA PROPRE BASE et lit le moteur en lecture seule.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE = os.environ.get("LIENS_DB", "/app/db/liens.sqlite")
COMBO = os.environ.get("COMBO_DB", "/app/db/papier_combo.sqlite")
PASSERELLES = ("https://ipfs.io/ipfs/%s", "https://cloudflare-ipfs.com/ipfs/%s",
               "https://gateway.pinata.cloud/ipfs/%s", "https://dweb.link/ipfs/%s",
               "https://nftstorage.link/ipfs/%s", "https://4everland.io/ipfs/%s",
               "https://ipfs.filebase.io/ipfs/%s", "https://flk-ipfs.xyz/ipfs/%s")
FILS = 4           # PREMIER ESSAI A 12 FILS : 1 505 erreurs 403 sur 1 511 echecs -- les passerelles
                   # bloquent pour debit excessif, pas pour un probleme de contenu (6 vrais 404).
                   # A 4 fils et avec l ordre des passerelles TIRE AU HASARD a chaque appel, on ne
                   # martele plus la premiere de la liste.


def schema(c: sqlite3.Connection) -> None:
    c.execute("CREATE TABLE IF NOT EXISTS lien("
              "  mint TEXT PRIMARY KEY, a_site INTEGER, a_twitter INTEGER, a_telegram INTEGER,"
              "  domaine TEXT, n_description INTEGER, n_champs INTEGER, erreur TEXT, t REAL)")
    c.commit()


def _chercher(cid: str, timeout: int = 15):
    """Essayer TOUTES les passerelles : un 429 sur l une ne dit rien du contenu."""
    import random as _r
    import requests
    derniere = None
    # ordre TIRE AU HASARD : en le gardant fixe, tout le trafic tombait sur ipfs.io, qui repondait
    # alors 403 -- et les sept autres passerelles ne servaient a rien.
    for p in _r.sample(PASSERELLES, len(PASSERELLES)):
        try:
            r = requests.get(p % cid, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            return r
        except Exception as exc:  # noqa: BLE001
            derniere = exc
    raise RuntimeError(str(derniere)[:80])


def lire(uri: str) -> dict:
    """Les liens declares dans la metadonnee. On ne VISITE pas le site : on note qu il est declare.

    Verifier qu un site repond changerait la question -- et surtout ce serait une lecture
    d AUJOURD HUI, donc une information posterieure a la decision. On s en tient a ce qui etait
    ecrit dans le fichier immuable.
    """
    import requests
    if uri.startswith("ipfs://") or "/ipfs/" in uri:
        meta = _chercher(uri.rstrip("/").split("/")[-1]).json()
    else:
        r = requests.get(uri, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        meta = r.json()
    if not isinstance(meta, dict):
        raise ValueError("metadonnee illisible")

    def champ(*noms) -> str:
        for n in noms:
            v = meta.get(n) or meta.get(n.capitalize())
            if isinstance(v, str) and v.strip():
                return v.strip()
        return ""

    site = champ("website", "site", "web", "url")
    tw = champ("twitter", "x")
    tg = champ("telegram", "tg")
    desc = champ("description")
    dom = ""
    if site:
        d = site.split("//")[-1].split("/")[0].lower()
        dom = d[4:] if d.startswith("www.") else d
    return {"a_site": int(bool(site)), "a_twitter": int(bool(tw)), "a_telegram": int(bool(tg)),
            "domaine": dom, "n_description": len(desc),
            "n_champs": sum(1 for x in (site, tw, tg) if x)}


def main() -> None:
    c = sqlite3.connect(BASE, timeout=30)
    schema(c)
    d = sqlite3.connect("file:%s?mode=ro" % COMBO, uri=True, timeout=30)
    d.execute("ATTACH DATABASE 'file:/app/db/intel.sqlite?mode=ro' AS M")
    # uniquement les jetons qui ont un ticket ANALYSABLE : mesurer sur des jetons sans resultat
    # gonflerait le n sans rien apporter
    rows = d.execute(
        "SELECT DISTINCT d.mint, o.uri FROM decision d"
        " JOIN issue i ON i.pair = d.pair JOIN M.solana_social o ON o.mint = d.mint"
        " WHERE i.brut_240 IS NOT NULL AND o.uri IS NOT NULL AND o.uri != ''").fetchall()
    # on ne garde comme « fait » que ce qui a REUSSI : un 403 est un echec de passerelle, pas un
    # fait sur le jeton, et il doit etre retente.
    faits = {m for (m,) in c.execute("SELECT mint FROM lien WHERE erreur IS NULL")}
    reste = [(m, u) for m, u in rows if m not in faits]
    print("%d jetons avec un resultat · %d deja faits · %d a lire"
          % (len(rows), len(faits), len(reste)), flush=True)

    def un(t):
        mint, uri = t
        try:
            return mint, lire(uri), None
        except Exception as exc:  # noqa: BLE001
            return mint, None, str(exc)[:120]

    ok = ko = 0
    # L ECRITURE RESTE DANS LE FIL PRINCIPAL : une connexion sqlite ne se partage pas entre fils,
    # et un collecteur qui corrompt sa propre base ne vaut rien.
    with ThreadPoolExecutor(max_workers=FILS) as pool:
        for i, (mint, v, err) in enumerate(pool.map(un, reste), 1):
            if v is not None:
                c.execute("INSERT OR REPLACE INTO lien(mint, a_site, a_twitter, a_telegram,"
                          " domaine, n_description, n_champs, t) VALUES(?,?,?,?,?,?,?,?)",
                          (mint, v["a_site"], v["a_twitter"], v["a_telegram"], v["domaine"],
                           v["n_description"], v["n_champs"], time.time()))
                ok += 1
            else:
                c.execute("INSERT OR REPLACE INTO lien(mint, erreur, t) VALUES(?,?,?)",
                          (mint, err, time.time()))
                ko += 1
            if i % 100 == 0:
                c.commit()
                print("  %d/%d · %d lus, %d en echec" % (i, len(reste), ok, ko), flush=True)
    c.commit()
    n_ok, n_ko = c.execute("SELECT SUM(erreur IS NULL), SUM(erreur IS NOT NULL) FROM lien").fetchone()
    print("termine · %s lus · %s en echec" % (n_ok, n_ko), flush=True)


if __name__ == "__main__":
    main()
