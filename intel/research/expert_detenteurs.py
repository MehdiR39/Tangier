"""EXPERT DETENTEURS, PRE-ENREGISTRE le 18/09 a 01h00 UTC (03h00 Paris).

POURQUOI UN DEUXIEME EXPERT. L agregation de modeles ne vaut que si les modeles se trompent
DIFFEREMMENT. Notre ensemble et notre foret sont correles a 0,939 et se recouvrent a 91 % sur leurs
selections : il n y a rien a echanger entre eux. Un expert entraine UNIQUEMENT sur la concentration
des detenteurs -- sans voir un seul prix -- atteint AUC 0,682 hors echantillon avec une correlation
de seulement 0,682 au modele de prix. C est cette decorrelation qui a de la valeur, pas son AUC.

CE QU IL VOIT. Deux variables, et deux seulement : la part du plus gros detenteur (`sac1`) et celle
des cinq premiers (`n_sacs5`), lues en chaine a 45 s. Mesure faite AVANT d ecrire le collecteur :
les onze variables non-prix donnent 0,678, les cinq « utiles » 0,699, ces deux-la 0,682. Le
createur et le financeur, tous deux couteux, n apportent rien de plus.

Sur les jetons vivants, la concentration est extreme : le plus gros detenteur tient 58 % en mediane,
les cinq premiers 92 %.

LA REGLE FIGEE : acheter seulement si le modele en service ET l expert detenteurs acceptent. Sur
l historique hors echantillon, exiger les deux donnait -6,43 % par ticket contre -8,66 % pour le
prix seul et -7,56 % pour les detenteurs seuls -- chaque filtre ameliore, et leur conjonction
ameliore plus que chacun. (La periode etait negative pour tout : c est le classement qui compte.)

CRITERE, FIGE : au premier atteint de 1 000 tickets posterieurs au gel ou de 21 jours, la
conjonction doit faire MIEUX que le modele en service seul, sur EXACTEMENT les memes tickets.
Comparaison appariee : meme marche, memes jetons, seule la regle change.

CE QUI NE CHANGE PAS. Le modele en service continue de decider seul. Cet expert est note en
parallele, en joignant `papier_combo` (les decisions et leurs resultats) et `papier_social` (la
detention). Aucun collecteur en marche n est modifie.
"""
from __future__ import annotations

import os
import sqlite3

from intel.research.ensemble import Ensemble

GEL_DETENTEURS = 1789693200.0      # 18/09/2026 01h00 UTC = 03h00 Paris
CHEMIN = os.environ.get("DETENTEURS_VIDAGE", "/app/data/recherche/balayage/detenteurs_vidage.json")
BASE_SOCIAL = os.environ.get("SOCIAL_DB", "/app/db/papier_social.sqlite")
N_CRITERE, JOURS_CRITERE = 1000, 21


def rapport(ici: sqlite3.Connection, mise: float = 25.0, cout: float = 0.0262) -> None:
    """La conjonction prix + detenteurs contre le modele en service, sur les memes tickets."""
    try:
        expert = Ensemble(CHEMIN)
    except FileNotFoundError:
        print("\nEXPERT DETENTEURS : fichier absent (%s)" % CHEMIN)
        return
    ici.execute("ATTACH DATABASE 'file:%s?mode=ro' AS S" % BASE_SOCIAL)
    rows = ici.execute("""SELECT d.risque, i.brut_240, s.sac1, s.n_sacs5 FROM decision d
                          JOIN issue i ON i.pair = d.pair JOIN S.jeton s ON s.pair = d.pair
                          WHERE d.eligible = 1 AND i.brut_240 IS NOT NULL AND d.risque IS NOT NULL
                          AND s.sac1 IS NOT NULL AND d.t_dec >= ? ORDER BY d.t_dec""",
                       (GEL_DETENTEURS,)).fetchall()
    print("\nEXPERT DETENTEURS · PRE-ENREGISTRE le 18/09 a 03h00 Paris")
    print("   %d ticket(s) depuis le gel, sur les %d du critere" % (len(rows), N_CRITERE))
    if rows:
        serv, deux = [], []
        for risque, brut, sac1, n5 in rows:
            net = min(brut - cout, 3.0)
            ok_prix = risque <= 0.2694
            ok_det = expert.probabilite({"sac1": sac1, "n_sacs5": n5}) <= expert.seuil_p80
            if ok_prix:
                serv.append(net)
            if ok_prix and ok_det:
                deux.append(net)
        for nom, v in (("modele en service", serv), ("prix ET detenteurs", deux)):
            if v:
                print("   %-22s n=%4d · %+7.2f %% · %+7.0f EUR"
                      % (nom, len(v), 100 * sum(v) / len(v), mise * sum(v)))
        if serv and deux:
            ecart = mise * (sum(deux) - sum(serv))
            print("   -> la conjonction apporte %+.0f EUR · %s"
                  % (ecart, "MIEUX" if ecart > 0 else "moins bien"))
    print("   CRITERE : faire mieux que le modele en service seul, a %d tickets ou %d jours."
          % (N_CRITERE, JOURS_CRITERE))


if __name__ == "__main__":
    rapport(sqlite3.connect("file:/app/db/papier_combo.sqlite?mode=ro", uri=True, timeout=30))
