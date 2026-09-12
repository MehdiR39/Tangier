"""Les metadonnees sociales d un lancement : le predicteur le plus fort de la litterature.

Kamat 2026 (arXiv 2607.02823), 832 941 lancements pump.fun : la presence d un canal Telegram
multiplie par **8,94** le taux de graduation (1,485 % contre 0,166 %), les trois reseaux reunis par
17,4. Rapport de risque 5,40 pour Telegram, 1,30 pour Twitter, 1,19 pour un site. C est de tres loin
le plus fort effet publie sur cette classe d actifs -- devant tout ce que ce projet a teste.

C est aussi la seule variable que la collecte n avait pas, et pour une raison bete : le 09/09 j ai
cherche les metadonnees au mauvais endroit. Ces jetons sont en **Token-2022** et portent leur
metadonnee DANS le compte du mint (extension `tokenMetadata`), pas dans un compte Metaplex separe --
d ou un PDA vide et la conclusion erronee que la donnee n existait pas. Et la passerelle IPFS par
defaut (`ipfs.io`) repond 429 : tous les champs revenaient vides sans que rien ne le signale.

    getAccountInfo(mint)  ->  extensions.tokenMetadata.uri  ->  JSON {name, symbol, description,
                                                                     twitter, telegram, website}

Ce fichier remplit `solana_social` pour les lancements dont on a deja la courbe, afin de tester
l effet sur NOS donnees au lieu de le supposer.

Usage :
    python -m intel.research.social --limite 600
"""
from __future__ import annotations

import argparse
import asyncio
import sqlite3
import sys

import httpx

sys.path.insert(0, "/app")

# `ipfs.io` repond 429 des qu on enchaine : on tourne sur plusieurs passerelles.
# `pump.mypinata.cloud` d abord : mesure le 12/09 sur 2 900 jetons, c est la plus fiable au premier
# essai (81 %) ; `ipfs.io` rend 429 sans le dire des qu on enchaine, ce qui avait fait croire le
# 09/09 que la donnee n existait pas.
#
# La liste est longue EXPRES. Le 12/09 a 15 h, apres le remplissage de 2 900 jetons, les cinq
# premieres renvoyaient toutes 429 en meme temps et le moteur en direct declarait « illisible » un
# lancement sur trois -- donc renoncait a un achat sur trois. Neuf passerelles repondent, testees
# une par une le meme jour ; une saturation simultanee des neuf est bien moins probable.
# `_fiche` les essaie a tour de role en decalant le point de depart, pour ne pas taper toujours la
# meme en tete de liste.
PASSERELLES = ("https://pump.mypinata.cloud/ipfs/",
               "https://ipfs.io/ipfs/",
               "https://dweb.link/ipfs/",
               "https://w3s.link/ipfs/",
               "https://nftstorage.link/ipfs/",
               "https://4everland.io/ipfs/",
               "https://ipfs.filebase.io/ipfs/",
               "https://gateway.ipfs.io/ipfs/",
               "https://ipfs.raribleuserdata.com/ipfs/",
               "https://gateway.pinata.cloud/ipfs/")


def _cid(uri: str) -> str | None:
    for marque in ("/ipfs/", "ipfs://"):
        if marque in uri:
            return uri.split(marque, 1)[1].strip("/")
    return None


async def _meta(cl: httpx.AsyncClient, rpc: str, mint: str) -> dict | None:
    """(nom, symbole, uri) depuis le compte du mint. Token-2022 les porte dedans."""
    try:
        r = await cl.post(rpc, json={"jsonrpc": "2.0", "id": 1, "method": "getAccountInfo",
                                     "params": [mint, {"encoding": "jsonParsed"}]}, timeout=25)
        info = ((((r.json() or {}).get("result") or {}).get("value") or {})
                .get("data") or {}).get("parsed", {}).get("info", {})
        for e in (info.get("extensions") or []):
            if e.get("extension") == "tokenMetadata":
                return e.get("state") or {}
    except Exception:  # noqa: BLE001
        pass
    return None


async def _fiche(cl: httpx.AsyncClient, uri: str, depart: int = 0) -> dict | None:
    """Le JSON de la metadonnee, en essayant les passerelles a tour de role."""
    cid = _cid(uri or "")
    urls = [p + cid for p in PASSERELLES] if cid else ([uri] if uri.startswith("http") else [])
    if cid:
        urls = urls[depart % len(urls):] + urls[:depart % len(urls)]
    for u in urls:
        try:
            r = await cl.get(u, timeout=15, follow_redirects=True)
            if r.status_code == 200:
                return r.json()
        except Exception:  # noqa: BLE001
            continue
    return None


async def remplir(db: str, rpc: str, limite: int) -> None:
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE IF NOT EXISTS solana_social("
              " mint TEXT PRIMARY KEY, nom TEXT, symbole TEXT, uri TEXT,"
              " twitter INTEGER, telegram INTEGER, site INTEGER, n_descr INTEGER, lu INTEGER)")
    deja = {r[0] for r in c.execute("SELECT mint FROM solana_social")}
    cibles = [r[0] for r in c.execute(
        "SELECT DISTINCT mint FROM solana_prix_chaine WHERE mint IS NOT NULL ORDER BY ts DESC")
        if r[0] not in deja][:limite]
    if not cibles:
        print("  rien a remplir")
        return
    print("  %d lancements a lire (%d deja connus)" % (len(cibles), len(deja)))
    ok = vides = 0
    async with httpx.AsyncClient(headers={"accept": "application/json"}) as cl:
        for i, mint in enumerate(cibles):
            meta = await _meta(cl, rpc, mint)
            if not meta:
                c.execute("INSERT OR REPLACE INTO solana_social VALUES(?,?,?,?,?,?,?,?,?)",
                          (mint, None, None, None, None, None, None, None, 0))
                vides += 1
            else:
                j = await _fiche(cl, meta.get("uri") or "", depart=i) or {}
                c.execute("INSERT OR REPLACE INTO solana_social VALUES(?,?,?,?,?,?,?,?,?)",
                          (mint, meta.get("name"), meta.get("symbol"), meta.get("uri"),
                           int(bool(j.get("twitter"))), int(bool(j.get("telegram"))),
                           int(bool(j.get("website"))), len(j.get("description") or ""),
                           1 if j else 0))
                ok += 1 if j else 0
            if i % 50 == 49:
                c.commit()
                print("    %d/%d · %d fiches lues · %d sans metadonnee" % (i + 1, len(cibles), ok, vides))
            await asyncio.sleep(0.15)
    c.commit()
    print("  fini : %d fiches lues, %d sans metadonnee" % (ok, vides))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="/app/db/intel.sqlite")
    ap.add_argument("--limite", type=int, default=600)
    a = ap.parse_args()
    from intel.execution import solana as sol
    rpc = sol.rpc_url()
    if not rpc:
        print("  pas de RPC")
        return
    asyncio.run(remplir(a.db, rpc, a.limite))


if __name__ == "__main__":
    main()
