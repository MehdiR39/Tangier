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

# (nom lisible, fichier, table, colonne de temps, retard tolere en minutes, lignes de la table)
SOURCES = [
    ("papier_combo", f"{DB}/papier_combo.sqlite", "decision", "t_dec", 20,
     "temoin, regime, RISQUE seul, BANDE, ENSEMBLE, FORET ALEATOIRE, AU PLUS BAS, RISQUE+FREIN, RISQUE+IPFS..."),
    ("papier_gd45", f"{DB}/papier_gd.sqlite", "decision", "t_dec", 20, "G+D a 45 s"),
    ("papier_gd30", f"{DB}/papier_gd30.sqlite", "decision", "t_dec", 20, "G+D a 30 s"),
    ("papier_large", f"{DB}/papier_large.sqlite", "decision", "t_dec", 20,
     "coffre seul, G foule, D tendance, D+F, G+D les trois"),
    ("foret_gel45", f"{DB}/papier_foret.sqlite", "decision", "t_dec", 450, "FORET 45s top 5 % et 10 %"),
    ("foret_gel75", f"{DB}/papier_foret75.sqlite", "decision", "t_dec", 450, "FORET 75s top 5 % et 10 %"),
    ("social", f"{DB}/papier_social.sqlite", "jeton", "t_vu", 30, "variable detenteurs"),
    ("stock", f"{DB}/papier_stock.sqlite", "photo", "t", 30, "gel du stock (collecte)"),
    ("prix_rapide", f"{DB}/prix_rapide.sqlite", "prix", "ts", 20, "prix a 1 s"),
    ("moteur_prix", f"{DB}/intel.sqlite", "solana_prix_chaine", "ts", 20, "LA SOURCE DE TOUT"),
    ("telegram", f"{DB}/intel.sqlite", "tg_lignes", "ts_entree", 180, "ENTREE T+75"),
]


def retard(f: str, table: str, col: str) -> float | None:
    """Minutes depuis la derniere ecriture, None si la base est illisible ou vide."""
    if not os.path.exists(f):
        return None
    try:
        c = sqlite3.connect("file:%s?mode=ro" % f, uri=True, timeout=20)
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
                alerter("VEILLE TABLE · %s ne repond plus (%s) - lignes touchees : %s"
                        % (nom, ("base illisible" if r is None else "%.0f min de silence, tolere %d" % (r, tol)),
                           lignes))
            elif not muette and nom in muettes:
                mn = (t0 - muettes.pop(nom)) / 60.0
                alerter("VEILLE TABLE · %s est repartie apres %.0f min" % (nom, mn))
        time.sleep(max(60.0, PAS - (time.time() - t0)))


if __name__ == "__main__":
    main()
