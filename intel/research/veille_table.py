"""VEILLE DE LA TABLE : chaque ligne a une source, chaque source est surveillee, ou on le sait.

MIDO, 19/09 10h05 : « toutes les strats de la table doivent etre suivies. » Apres que trois
collecteurs (`papier_gd`, `papier_gd30`, `papier_large`) et l enregistreur de transactions sont
morts ensemble le 18/09 a 9h14 et que SEPT lignes de la table n ont rien vu pendant 24 h sans
qu aucun signal ne le dise (§3.146, §3.149).

CE QU IL FAIT. Toutes les PAS minutes, pour CHAQUE source de la table : lire la derniere ecriture,
la comparer au retard TOLERE de cette source, et alerter sur Telegram quand elle depasse. Une seule
alerte par source tant qu elle reste muette, et un message de retour quand elle repart -- sinon une
panne de nuit produit cent messages et on n en lit aucun.

LE RETARD TOLERE N EST PAS LE MEME PARTOUT, et c est tout l interet de le declarer ici :
  - les collecteurs continus (papier_combo, papier_gd*, prix_rapide, social, stock, moteur) ecrivent
    plusieurs fois par minute : 20 minutes de silence est deja une panne ;
  - les deux gels de la foret notent par cycles de 6 h : 7 h 30 de silence, pas 20 minutes ;
  - `tg_lignes` depend d un canal exterieur : 3 h.
Une tolerance trop serree fabrique des fausses alertes, qu on apprend a ignorer -- c est la meme
faute qu un garde-fou qui bloque quand il ne sait pas.

IL NE REPARE RIEN. Le gardien relance, la veille previent. Les deux sont separes pour qu une panne
de l un ne masque pas l autre : c est precisement ce qui s est passe le 18/09, ou le gardien ne
connaissait pas ces processus et personne ne regardait.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PAS = float(os.environ.get("VEILLE_PAS_MIN", "10")) * 60.0
DB = "/app/db"

# LES 26 LIGNES DE LA TABLE, chacune rattachee a la source qui la nourrit -- verifie le 19/09 en
# lisant ORDRE dans table_std2.py et en remontant le code qui appelle ranger() pour chaque ligne.
# Aucune ligne ne doit manquer ici : c est ce controle, pas la liste des processus, qui garantit
# qu une ligne de la table ne meurt pas en silence.
#
# (nom lisible, fichier, table, colonne de temps, retard tolere en minutes, lignes de la table)
SOURCES = [
    ("papier_combo", f"{DB}/papier_combo.sqlite", "decision", "t_dec", 20,
     "13 lignes : temoin, regime seul, RISQUE seul, regime+risque, BANDE, BANDE+PAUSE, ENSEMBLE de 12,"
     " FORET ALEATOIRE, PRIX+DETENTEURS, AU PLUS BAS, BAS+BANDE, RISQUE+FREIN, RISQUE+IPFS"),
    ("papier_gd45", f"{DB}/papier_gd.sqlite", "decision", "t_dec", 20, "G+D a 45 s"),
    ("papier_gd30", f"{DB}/papier_gd30.sqlite", "decision", "t_dec", 20, "G+D a 30 s"),
    ("papier_large", f"{DB}/papier_large.sqlite", "decision", "t_dec", 20,
     "6 lignes : coffre seul, G foule <= 74, D tendance > 0, D+F tendance+pause, G+D les trois, PISTE FOULE"),
    ("foret_gel45", f"{DB}/papier_foret.sqlite", "decision", "t_dec", 450, "FORET 45s top 5 % et 10 %"),
    ("foret_gel75", f"{DB}/papier_foret75.sqlite", "decision", "t_dec", 450, "FORET 75s top 5 % et 10 %"),
    ("social", f"{DB}/papier_social.sqlite", "jeton", "t_vu", 30,
     "PRIX + DETENTEURS (sac1, n_sacs5) -- et la variable detenteurs des deux forets"),
    # RISQUE + IPFS lit `solana_social.uri`, remplie par telegram_rapide/social au fil des lancements :
    # une source a part, qui peut se taire sans que papier_combo se taise.
    ("metadonnee_uri", f"{DB}/intel.sqlite", "solana_social", "rowid", 45, "RISQUE + IPFS (usine a jetons)"),
    ("stock", f"{DB}/papier_stock.sqlite", "photo", "t", 30, "gel du stock (collecte)"),
    ("prix_rapide", f"{DB}/prix_rapide.sqlite", "prix", "ts", 20, "prix a 1 s"),
    ("moteur_prix", f"{DB}/intel.sqlite", "solana_prix_chaine", "ts", 20, "LA SOURCE DE TOUT"),
    ("telegram", f"{DB}/intel.sqlite", "tg_lignes", "ts_entree", 180, "ENTREE T+75"),
]


_compteurs: dict[str, tuple[int, float]] = {}       # table sans horodatage -> (lignes, instant)


# CORRESPONDANCE EXPLICITE ligne de la table -> source. Ecrite a la main, verifiee par
# tests/intel_tests/test_veille_table.py, qui lit ORDRE dans table_std2.py et echoue si UNE ligne
# n est pas ici. Ajouter une ligne a la table sans la surveiller devient donc impossible en silence.
LIGNES = {
    "temoin sans filtre": "papier_combo",
    "regime seul": "papier_combo",
    "RISQUE seul (modele)": "papier_combo",
    "regime + risque": "papier_combo",
    "G+D a 45 s (gele)": "papier_gd45",
    "G+D a 30 s (gele)": "papier_gd30",
    "coffre seul": "papier_large",
    "G  foule <= 74": "papier_large",
    "D  tendance > 0": "papier_large",
    "D+F  tendance + pause": "papier_large",
    "G+D  les trois": "papier_large",
    "BANDE 0,20-0,35 (gelee)": "papier_combo",
    "BANDE + PAUSE (gelee)": "papier_combo",
    "PISTE FOULE (gelee)": "papier_large",
    "ENSEMBLE de 12 (gele)": "papier_combo",
    "FORET ALEATOIRE (gelee)": "papier_combo",
    "PRIX + DETENTEURS (gele)": "social",
    "AU PLUS BAS (gele)": "papier_combo",
    "BAS + BANDE (gele)": "papier_combo",
    "RISQUE + FREIN (gele)": "papier_combo",
    "RISQUE + IPFS (gele)": "metadonnee_uri",
    "FORET 45s top 5 % (gelee)": "foret_gel45",
    "FORET 45s top 10 % (lecture)": "foret_gel45",
    "FORET 75s top 5 % (gelee)": "foret_gel75",
    "FORET 75s top 10 % (lecture)": "foret_gel75",
    "ENTREE T+75 (gelee)*": "telegram",
}


def retard(f: str, table: str, col: str) -> float | None:
    """Minutes depuis la derniere ecriture, None si la base est illisible ou vide.

    `solana_social` n a AUCUNE colonne de temps : on y suit le nombre de lignes, et le « retard »
    est le temps ecoule depuis la derniere fois qu il a augmente. Sans ca, cette source -- celle de
    RISQUE + IPFS -- serait la seule a ne pas pouvoir etre surveillee.
    """
    if not os.path.exists(f):
        return None
    try:
        c = sqlite3.connect("file:%s?mode=ro" % f, uri=True, timeout=20)
        if col == "rowid":
            n = int(c.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0])
            vus, quand = _compteurs.get(table, (None, time.time()))
            if vus is None or n > vus:
                _compteurs[table] = (n, time.time())
                return 0.0
            return (time.time() - quand) / 60.0
        v = c.execute("SELECT MAX(%s) FROM %s" % (col, table)).fetchone()[0]
        return (time.time() - float(v)) / 60.0 if v else None
    except Exception:  # noqa: BLE001
        return None


def alerter(texte: str) -> None:
    """Telegram si configure, sinon le journal seul. Une alerte qui plante ne doit pas tuer la veille."""
    print(texte, flush=True)
    try:
        import asyncio

        from intel.alerts.telegram import TelegramNotifier
        from intel.settings import Settings

        async def _envoi():
            n = TelegramNotifier(Settings.load())
            try:
                await n.send(texte)
            finally:
                await n.close()

        asyncio.run(_envoi())
    except Exception as exc:  # noqa: BLE001
        print("veille_table: telegram indisponible (%s)" % str(exc)[:80], flush=True)


def main() -> None:
    muettes: dict[str, float] = {}              # source -> instant de la premiere alerte
    print("veille_table: demarre · %d sources · pas %.0f min" % (len(SOURCES), PAS / 60), flush=True)
    while True:
        t0 = time.time()
        for nom, f, table, col, tol, lignes in SOURCES:
            r = retard(f, table, col)
            muette = r is None or r > tol
            if muette and nom not in muettes:
                muettes[nom] = t0
                touchees = sorted(k for k, v in LIGNES.items() if v == nom) or [lignes]
                alerter("VEILLE TABLE · %s ne repond plus (%s)\nlignes touchees (%d) : %s"
                        % (nom, ("base illisible" if r is None else "%.0f min de silence, tolere %d" % (r, tol)),
                           len(touchees), " · ".join(touchees)))
            elif not muette and nom in muettes:
                mn = (t0 - muettes.pop(nom)) / 60.0
                alerter("VEILLE TABLE · %s est repartie apres %.0f min" % (nom, mn))
        time.sleep(max(60.0, PAS - (time.time() - t0)))


if __name__ == "__main__":
    main()
