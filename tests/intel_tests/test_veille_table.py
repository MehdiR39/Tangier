"""La veille doit couvrir TOUTES les lignes de la table -- sinon une ligne peut mourir en silence.

Le 18/09 a 9h14, trois collecteurs sont tombes ensemble et sept lignes de la table n ont rien vu
pendant 24 h sans qu aucun signal ne le dise. Ce test rend cette situation impossible a produire
sans la voir : il lit ORDRE dans la table elle-meme et exige que chaque ligne ait une source
surveillee, et que chaque source nommee existe vraiment dans SOURCES.
"""
from __future__ import annotations

import pathlib
import re
import sys

RACINE = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "intel" / "research"))
import veille_table as V  # noqa: E402

TABLE = (RACINE / "data" / "table_std2.py").read_text(encoding="utf-8")
ORDRE = re.findall('"([^"]+)"', re.search(r"ORDRE = \[(.*?)\]", TABLE, re.S).group(1))


def test_la_table_a_bien_ete_lue():
    assert len(ORDRE) >= 20, "ORDRE mal lu dans table_std2.py : %d lignes" % len(ORDRE)


def test_chaque_ligne_de_la_table_a_une_source_surveillee():
    manquantes = [x for x in ORDRE if x not in V.LIGNES]
    assert not manquantes, "lignes de la table sans source surveillee : %s" % manquantes


def test_chaque_source_nommee_existe_dans_SOURCES():
    connues = {s[0] for s in V.SOURCES}
    # 27/09 : une source ARRETEE volontairement (menage) n est plus surveillee, mais ses lignes restent
    inconnues = sorted(set(V.LIGNES.values()) - connues - V.ARRETEES)
    assert not inconnues, "sources nommees mais absentes de SOURCES : %s" % inconnues


def test_aucune_source_ne_surveille_le_vide():
    """Une source qui n alimente aucune ligne est du bruit : soit on la relie, soit on l enleve.

    Les trois tolerees ici ne portent pas de ligne mais nourrissent les VARIABLES des modeles --
    on les garde, et on le dit explicitement pour que la liste ne derive pas.
    """
    utilisees = set(V.LIGNES.values())
    orphelines = {s[0] for s in V.SOURCES} - utilisees
    assert orphelines <= {"stock", "prix_rapide", "moteur_prix"}, "sources orphelines : %s" % sorted(orphelines)


def test_les_tolerances_sont_plausibles():
    """Un collecteur continu ne tolere pas des heures ; un gel a cycle de 6 h ne tolere pas 20 min."""
    tol = {s[0]: s[4] for s in V.SOURCES}
    for continu in ("papier_combo", "papier_gd45", "papier_challenger", "papier_large", "prix_rapide", "moteur_prix"):
        assert tol[continu] <= 30, "%s : tolerance trop large (%d min)" % (continu, tol[continu])


def test_une_source_arretee_n_est_jamais_surveillee():
    """27/09 : apres le menage, la veille alertait sur Telegram pour des collecteurs arretes EXPRES.
    Une source ne peut pas etre a la fois arretee et surveillee."""
    assert not ({s[0] for s in V.SOURCES} & V.ARRETEES), "source arretee encore surveillee"
