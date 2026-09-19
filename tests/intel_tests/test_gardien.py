"""Garde-fous du gardien des collecteurs.

Ce module DEMARRE des processus. Ce qu on protege :
  1. il ne TUE jamais rien et ne touche a aucune base -- il ne sait que demarrer ;
  2. il ne se compte jamais lui-meme, sinon il ne relancerait jamais rien ;
  3. il surveille bien les trois collecteurs dont dependent les tests geles.
"""
from __future__ import annotations

import inspect

from intel.research import gardien


def test_il_surveille_tous_les_collecteurs():
    assert set(gardien.COLLECTEURS) == {"papier_combo", "social_collecte", "prix_rapide",
                                       "stock_collecte", "foret_gel", "foret_gel75", "v1_enregistreur",
                                       "papier_gd45", "papier_gd30", "papier_large", "veille_table"}


def test_il_ne_tue_rien_et_n_ecrit_dans_aucune_base():
    """Un gardien qui peut tuer ou ecrire peut casser ce qu il est cense proteger."""
    src = inspect.getsource(gardien)
    for interdit in ("kill", "terminate", "SIGTERM", "sqlite3", "DELETE", "DROP", "UPDATE "):
        assert interdit not in src, "le gardien ne doit jamais %s" % interdit


def test_il_ne_se_compte_pas_lui_meme():
    """Sans cette garde il se verrait dans /proc et ne relancerait jamais personne."""
    src = inspect.getsource(gardien.vivants)
    assert "gardien" in src and "continue" in src
    assert "os.getpid()" in src


def test_il_attend_avant_le_premier_tour():
    """Apres un redemarrage les collecteurs peuvent etre en train de demarrer : relancer trop vite
    en ferait deux."""
    src = inspect.getsource(gardien.main)
    i_boucle = src.index("while True")
    assert "time.sleep(PAS)" in src[:i_boucle], "il doit laisser passer un tour au demarrage"


def test_il_ajoute_au_journal_au_lieu_de_l_ecraser():
    src = inspect.getsource(gardien.relancer)
    assert '"a"' in src, "ouvrir en 'w' effacerait l historique du collecteur a chaque relance"


def test_l_ordonnanceur_le_lance():
    """Le gardien doit etre accroche a l ordonnanceur : c est le seul dont le redemarrage est sur."""
    from intel.engines import scheduler
    src = inspect.getsource(scheduler)
    assert "intel.research.gardien" in src
    assert "gardien_enabled" in src
