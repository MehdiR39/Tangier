"""Le collecteur de stock ne doit RIEN pouvoir casser, et ne rien mesurer de contamine.

Chaque test ici vient d une erreur reelle du projet, pas d une precaution theorique.
"""
from __future__ import annotations

import pathlib
import re

SRC = pathlib.Path(__file__).resolve().parents[2] / "intel" / "research" / "stock_collecte.py"
CODE = SRC.read_text(encoding="utf-8")
# DEUX niveaux de nettoyage, et la difference compte. `SQL` garde les chaines (donc le schema) et
# ne retire que les commentaires. `NU` retire aussi les docstrings : c est le seul texte ou chercher
# un mot INTERDIT, parce que greper la prose a deja fait passer des tests entierement faux.
SQL = re.sub(r"#.*", "", CODE)
NU = re.sub(r"#.*", "", re.sub(r'""".*?"""', "", CODE, flags=re.S))


def test_il_ecrit_uniquement_dans_sa_propre_base():
    """Il lit le moteur, il n y ecrit jamais. Une base de recherche ne touche pas la production."""
    assert 'mode=ro' in NU and 'BASE_MOTEUR' in NU
    for verbe in ("INSERT INTO mr_", "UPDATE mr_", "DELETE", "DROP", "ALTER"):
        assert verbe not in NU.upper().replace("INSERT OR IGNORE INTO PHOTO", "")


def test_il_ne_tue_rien():
    """Le gardien et les collecteurs ne doivent jamais arreter un processus."""
    for mot in ("kill", "terminate", "SIGTERM", "SIGKILL", "docker"):
        assert mot not in NU


def test_le_coffre_du_pool_est_exclu():
    """LE piege central : le plus gros detenteur est tantot le coffre, tantot un portefeuille.

    Ce sont les deux etats les plus OPPOSES -- offre enfermee dans le pool contre un acteur qui
    peut le vider -- et les confondre leur donnerait le meme chiffre. Mesure du 18/09 : sur six
    pools, 4 fois le coffre, 2 fois un vrai portefeuille. C est ce qui avait rendu `sac_wallet`
    inutilisable (654 jetons, 654 portefeuilles distincts : c etait le coffre).
    """
    assert "!= pool" in NU, "le coffre doit etre retire du classement"
    assert "hors_pool" in SQL and "s1_hp" in SQL, "les parts hors pool doivent etre stockees"
    assert "w1_est_coffre" in SQL, "il faut POUVOIR verifier apres coup que l exclusion a marche"


def test_les_detenteurs_sont_des_portefeuilles_pas_des_comptes_jetons():
    """`getTokenLargestAccounts` rend des comptes-jetons : un par (portefeuille, jeton).

    Les garder tels quels interdit de reconnaitre un meme acteur d un lancement au suivant, qui
    est precisement ce que l hypothese demande. Le proprietaire est aux octets 32-64.
    """
    assert "getMultipleAccounts" in NU
    assert "[32:64]" in NU


def test_aucune_variable_derivee_n_est_stockee():
    """On stocke des FAITS BRUTS ; « a-t-il vendu ? » se calcule a l analyse.

    Calculer la variable de decision dans le collecteur, c est figer une formulation avant d avoir
    vu les resultats -- et s interdire de la refaire autrement quand elle montre un motif monotone
    (regle 3 de la discipline : le cout « additif » montait, en multiplicatif il s inverse).
    """
    for interdit in ("a_vendu", "distribue", "signal", "achat", "decision", "seuil"):
        assert interdit not in NU.lower(), "le collecteur ne doit pas decider, seulement mesurer"


def test_l_age_reel_est_conserve():
    """Le moteur ecrit toutes les 10 s : l age vise n est pas l age reel (20 s pour 15 s vises).

    Sans `naissance` dans la ligne, l analyse comparerait des photos prises a des ages differents
    en les croyant identiques.
    """
    assert "naissance REAL" in SQL


def test_un_tour_est_borne_en_temps_et_en_nombre():
    """Une photo lente (2,8 s au pire) ne doit pas faire rater les fenetres des autres."""
    assert "MAX_PAR_TOUR" in NU and "BUDGET" in NU
    assert "time.time() - t0 > BUDGET" in NU


def test_il_est_surveille_par_le_gardien():
    """Un collecteur absent de la liste du gardien reste mort toute la nuit, en silence."""
    g = (SRC.parent / "gardien.py").read_text(encoding="utf-8")
    assert '"stock_collecte"' in g
