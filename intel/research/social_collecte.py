"""Collecte de la CONCENTRATION DES DETENTEURS, a l age ou la decision se prendrait (45 s).

POURQUOI. Le modele en service n a que des variables de prix. Un expert entraine UNIQUEMENT sur des
variables non-prix se trompe DIFFEREMMENT : sa correlation de rang avec le modele de prix est de
0,68, la ou notre ensemble et notre foret sont a 0,939. C est la condition qui manquait pour que
deux experts s apportent quelque chose -- deux modeles qui designent les memes jetons ne peuvent
rien s echanger, quelle que soit la ponderation.

CE QUI PORTE LE SIGNAL, MESURE AVANT D ECRIRE CE FICHIER. Les variables gratuites -- Telegram,
Twitter, site, description, regime de marche -- ne valent rien : AUC 0,563 a elles seules, et les
RETIRER ameliore le reste. Tout est dans QUI DETIENT le jeton, et deux variables suffisent :

    les 11 variables non-prix              AUC 0,678 · correlation au prix 0,649
    les 5 « utiles »                       AUC 0,699 · 0,680
    sac1 + n_sacs5 SEULES                  AUC 0,682 · 0,682   <- un seul appel, 82 ms

Le createur n est PAS recuperable a bas cout : ces jetons sont en Token-2022 avec metadonnees
integrees et `updateAuthority` a null, il faudrait paginer jusqu a la premiere transaction du mint.
Le financeur demande la meme pagination sur le portefeuille. Ni l un ni l autre ne justifie ce cout
quand deux parts de detention donnent deja 0,682.

CE QUE CA COUTE. UN `getTokenLargestAccounts` et un `getTokenSupply` : 82 ms en mediane, 186 au
pire, sur une fenetre de 45 s ou les pools sont vus des 19 s. Piege evite de justesse : j avais
chronometre `getSignaturesForAddress` avec `limit: 1` (57 ms) puis ecrit `limit: 1000` -- ce n est
pas le meme appel, il bloque des minutes sur un jeton actif ET ne remonte meme pas jusqu a la
creation. Toujours chronometrer l appel EXACT qu on va ecrire.

CE QU IL ENREGISTRE. Des FAITS BRUTS seulement : quel portefeuille detient le plus, quelle part il
tient, quelle part tiennent les cinq premiers. Les variables derivees -- « ce portefeuille a deja
ete dans un vidage » -- se calculent a l ANALYSE, en ne regardant que les resultats connus a
l instant de la decision. Cette separation est ce qui les empeche de fuir.

IL N ECRIT QUE DANS SA PROPRE BASE et lit tout le reste en lecture seule. Aucun collecteur en
marche n est modifie : s il tombe, il tombe seul.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import copie_collecte as cc  # noqa: E402

BASE_MOTEUR = os.environ.get("INTEL_DB", "/app/db/intel.sqlite")
BASE_ICI = os.environ.get("SOCIAL_DB", "/app/db/papier_social.sqlite")
A = 45                     # l age auquel la decision se prend
PAUSE = 20.0               # entre deux tours : rien ne presse, un pool reste lisible longtemps
MAX_PAR_TOUR = 40          # plafond : un tour ne doit jamais monopoliser le RPC


def schema(c: sqlite3.Connection) -> None:
    c.executescript("""
        CREATE TABLE IF NOT EXISTS jeton(
            pair TEXT PRIMARY KEY, mint TEXT, naissance REAL, t_vu REAL,
            sac_wallet TEXT, sac1 REAL, n_sacs5 REAL, erreur TEXT);
        CREATE INDEX IF NOT EXISTS i_jeton_mint ON jeton(mint);
        CREATE TABLE IF NOT EXISTS meta(cle TEXT PRIMARY KEY, valeur TEXT);
    """)
    c.commit()


def detenteurs(mint: str) -> tuple[str | None, float | None, float | None]:
    """(portefeuille du plus gros detenteur, sa part, la part des cinq premiers).

    Les parts sont rapportees a l offre que la chaine donne AU MOMENT DE LA LECTURE, pas a une
    offre theorique : sur un jeton qui vient de naitre, les deux n ont rien a voir.
    """
    r = cc.rpc({"jsonrpc": "2.0", "id": 1, "method": "getTokenLargestAccounts", "params": [mint]})
    vals = (r or {}).get("value") or []
    if not vals:
        return None, None, None
    montants = [float(v["uiAmount"] or 0) for v in vals]
    sup = cc.rpc({"jsonrpc": "2.0", "id": 1, "method": "getTokenSupply", "params": [mint]})
    total = float(((sup or {}).get("value") or {}).get("uiAmount") or 0)
    if total <= 0:
        return str(vals[0]["address"]), None, None
    return str(vals[0]["address"]), montants[0] / total, sum(montants[:5]) / total


def tour(ici: sqlite3.Connection, moteur: sqlite3.Connection) -> int:
    """Documente les pools vus recemment qui ont depasse 45 s et qu on n a pas encore traites."""
    now = time.time()
    rows = moteur.execute(
        "SELECT pair_id, mint, MIN(ts - age_s) AS naissance, MAX(age_s) AS age"
        " FROM solana_prix_chaine WHERE ts > ? GROUP BY pair_id", (now - 1800,)).fetchall()
    deja = {r[0] for r in ici.execute("SELECT pair FROM jeton")}
    faits = 0
    for pair, mint, naissance, age in rows:
        if pair in deja or not mint or (age or 0) < A:
            continue
        if faits >= MAX_PAR_TOUR:
            break
        sac = s1 = s5 = None
        erreur = None
        try:
            sac, s1, s5 = detenteurs(mint)
        except Exception as exc:  # noqa: BLE001
            erreur = str(exc)[:120]          # un pool rate ne doit JAMAIS arreter la boucle
        ici.execute("INSERT OR IGNORE INTO jeton(pair, mint, naissance, t_vu, sac_wallet,"
                    " sac1, n_sacs5, erreur) VALUES(?,?,?,?,?,?,?,?)",
                    (pair, mint, naissance, now, sac, s1, s5, erreur))
        faits += 1
    ici.commit()
    return faits


def main() -> None:
    ici = sqlite3.connect(BASE_ICI, timeout=30)
    schema(ici)
    moteur = sqlite3.connect("file:%s?mode=ro" % BASE_MOTEUR, uri=True, timeout=30)
    print("social_collecte: demarre · base %s" % BASE_ICI, flush=True)
    while True:
        try:
            n = tour(ici, moteur)
            if n:
                total, rates = ici.execute(
                    "SELECT COUNT(*), SUM(erreur IS NOT NULL) FROM jeton").fetchone()
                print("social_collecte: +%d · total %d · %d en erreur"
                      % (n, total, rates or 0), flush=True)
        except Exception as exc:  # noqa: BLE001
            print("social_collecte: tour rate (%s)" % str(exc)[:160], flush=True)
        time.sleep(PAUSE)


if __name__ == "__main__":
    main()
