"""Le coffre : TOUTES les donnees de recherche, en un seul fichier, sur le disque de l operateur.

POURQUOI (demande de l operateur, 15/09 : « il faut qu on garde toutes les donnees qu on recupere
depuis des jours, il faut qu on puisse faire une grosse analyse a la fin »). Aujourd hui elles sont
eparpillees :
  - l ancienne base (45 Go, jusqu au 14/09 20h25), gardee dans le volume Docker ;
  - la base du moteur depuis le 14/09 21h08, qui grossit et devra un jour etre allegee ;
  - la base de l enregistreur de detenteurs ;
et un volume Docker disparait avec une reinitialisation de Docker Desktop.

CE QUE FAIT CE SCRIPT. Il recopie les tables de recherche de chaque source dans
`data/recherche/archive_solana.sqlite` (dossier du PC, monte dans le conteneur sur /app/data).
  - meme schema que la source, cles primaires comprises : une ligne deja archivee n est jamais
    dupliquee, et si elle a CHANGE a la source (une ligne du carnet passe d OUVERTE a FERMEE avec
    son gain) c est la version la plus recente qui reste (INSERT OR REPLACE, sources lues de la plus
    ancienne a la plus recente) ;
  - une table SANS cle recoit une cle sur toutes ses colonnes, pour la meme garantie ;
  - il ne SUPPRIME rien, nulle part, et n ecrit jamais dans les bases sources (ouvertes en lecture
    seule) ;
  - relancable a volonte : chaque passage ajoute ce qui est arrive depuis.

Les grosses tables EVM (transfers 41,8 M de lignes, trades 15 M...) restent dans l ancienne base :
elles ne servent pas a la recherche Solana et doubleraient le coffre.

Lancement : python -m intel.research.coffre            (un passage)
            python -m intel.research.coffre --boucle   (un passage par heure)
"""
from __future__ import annotations

import os
import sqlite3
import sys
import time

SOURCES = [
    os.environ.get("COFFRE_ANCIENNE", "/app/db/intel-ancienne-45go.sqlite"),
    os.environ.get("INTEL_DB", "/app/db/intel.sqlite"),
    os.environ.get("DETENTEURS_DB", "/app/db/detenteurs.sqlite"),
]
CIBLE = os.environ.get("COFFRE", "/app/data/recherche/archive_solana.sqlite")

TABLES = [
    # carnets, decisions, refus
    "tg_lignes", "tg_juges", "tg_echecs", "tg_cascade", "positions", "decisions", "executions",
    "solana_judgements", "solana_observations", "sol_strat_resultat", "alerts",
    # prix et suivi des lancements Solana
    "solana_stream_launches", "solana_prix_chaine", "solana_suivi", "solana_suivi_long",
    "solana_social", "sol_createur", "mint_offre", "pool_quote",
    # courbes pump.fun, BNB, NFT, recherches annexes
    "pump_creations", "pump_prix", "bnb_lancements", "bnb_releves", "bnb_social",
    "nft_traits", "nft_ventes", "ath_sommets", "paliers_faits", "t1_observations",
    "history_meta", "history_series",
    # enregistreur de detenteurs (15/09)
    "releve", "issue",
]
LOT = 20_000


def schema_cible(src: sqlite3.Connection, dst: sqlite3.Connection, table: str):
    """Cree la table dans le coffre. Rend (colonnes, numerotee) ou None si la source ne l a pas.

    CLE NUMEROTEE. `positions`, `decisions`, `executions`, `solana_judgements`, `alerts` ont une cle
    `id` auto-incrementee. La base neuve du 14/09 a recommence a 1 : copier les deux bases sur la
    meme cle ferait ecraser un jugement du 09/09 par un jugement du 15/09 portant le meme numero
    (constate au premier passage, 387 lignes). Pour ces tables la cle du coffre est donc
    (base d origine, id), et la colonne `coffre_source` dit d ou vient chaque ligne.
    """
    ligne = src.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    if not ligne:
        return None
    info = list(src.execute('PRAGMA table_info("%s")' % table))
    cols = [r[1] for r in info]
    pk = [r for r in info if r[5]]
    numerotee = len(pk) == 1 and "INT" in (pk[0][2] or "").upper()
    existe = dst.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    if not existe:
        if numerotee:
            dst.execute('CREATE TABLE "%s"(coffre_source TEXT, %s)'
                        % (table, ", ".join('"%s" %s' % (r[1], r[2] or "") for r in info)))
            dst.execute('CREATE UNIQUE INDEX "coffre_%s" ON "%s"(coffre_source, "%s")' % (table, table, pk[0][1]))
        else:
            a_une_cle = bool(pk) or any(r[2] for r in src.execute('PRAGMA index_list("%s")' % table))
            dst.execute(ligne[0])
            if not a_une_cle:
                dst.execute('CREATE UNIQUE INDEX "coffre_%s" ON "%s"(%s)'
                            % (table, table, ",".join('"%s"' % c for c in cols)))
        dst.commit()
    cols_dst = {r[1] for r in dst.execute('PRAGMA table_info("%s")' % table)}
    for c in cols:                                  # une colonne ajoutee apres coup a la source
        if c not in cols_dst:
            dst.execute('ALTER TABLE "%s" ADD COLUMN "%s"' % (table, c))
    dst.commit()
    return cols, numerotee


def recopier(src_chemin: str, dst: sqlite3.Connection) -> dict[str, int]:
    if not os.path.exists(src_chemin):
        return {}
    src = sqlite3.connect("file:%s?mode=ro" % src_chemin, uri=True, timeout=60)
    ajouts = {}
    for table in TABLES:
        sc = schema_cible(src, dst, table)
        if not sc:
            continue
        cols, numerotee = sc
        avant = dst.execute('SELECT COUNT(*) FROM "%s"' % table).fetchone()[0]
        liste = ",".join('"%s"' % c for c in cols)
        origine = os.path.basename(src_chemin)
        dernier = 0
        while True:
            lot = src.execute('SELECT rowid, %s FROM "%s" WHERE rowid > ? ORDER BY rowid LIMIT ?'
                              % (liste, table), (dernier, LOT)).fetchall()
            if not lot:
                break
            dernier = lot[-1][0]
            if numerotee:
                dst.executemany('INSERT OR REPLACE INTO "%s"(coffre_source,%s) VALUES(?,%s)'
                                % (table, liste, ",".join("?" * len(cols))), [(origine,) + tuple(r[1:]) for r in lot])
            else:
                dst.executemany('INSERT OR REPLACE INTO "%s"(%s) VALUES(%s)' % (table, liste, ",".join("?" * len(cols))),
                                [r[1:] for r in lot])
            dst.commit()
            time.sleep(0.05)                        # ne pas affamer le moteur qui partage le disque
        ajouts[table] = dst.execute('SELECT COUNT(*) FROM "%s"' % table).fetchone()[0] - avant
    src.close()
    return ajouts


def passage() -> None:
    os.makedirs(os.path.dirname(CIBLE), exist_ok=True)
    dst = sqlite3.connect(CIBLE, timeout=60)
    dst.execute("CREATE TABLE IF NOT EXISTS coffre_passages(ts INTEGER, source TEXT, table_nom TEXT, ajoutees INTEGER)")
    t0 = time.time()
    for s in SOURCES:
        # une source qui n a pas bouge depuis son dernier passage complet n est pas relue : l ancienne
        # base (45 Go) ne change plus, la relire toutes les heures userait le disque du moteur pour rien
        der = dst.execute("SELECT MAX(ts) FROM coffre_passages WHERE source=?", (os.path.basename(s),)).fetchone()[0]
        # la base du moteur est en WAL : ses ecritures recentes sont dans le -wal, pas dans le fichier
        # principal, dont la date ne bouge qu au checkpoint -- regarder les deux
        bouge = max([os.path.getmtime(f) for f in (s, s + "-wal") if os.path.exists(f)] or [0])
        if der and os.path.exists(s) and bouge < der:
            print("coffre: %-32s inchangee depuis le dernier passage" % os.path.basename(s), flush=True)
            continue
        ajouts = recopier(s, dst)
        for t, n in ajouts.items():
            dst.execute("INSERT INTO coffre_passages VALUES(?,?,?,?)", (int(time.time()), os.path.basename(s), t, n))
        dst.commit()
        print("coffre: %-32s %s" % (os.path.basename(s), ", ".join("%s +%d" % kv for kv in ajouts.items() if kv[1])), flush=True)
    dst.close()
    print("coffre: passage fini en %.0f s -> %s (%.0f Mo)" % (time.time() - t0, CIBLE, os.path.getsize(CIBLE) / 1e6), flush=True)


if __name__ == "__main__":
    if "--boucle" in sys.argv:
        while True:
            try:
                passage()
            except Exception as exc:  # noqa: BLE001
                print("coffre: passage rate (%s)" % str(exc)[:160], flush=True)
            time.sleep(3600)
    else:
        passage()
