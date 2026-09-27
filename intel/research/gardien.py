"""GARDIEN DES COLLECTEURS DE RECHERCHE : les relancer s ils meurent, sans intervention humaine.

POURQUOI. Les collecteurs de recherche (`papier_combo`, `social_collecte`, `prix_rapide`) tournent
en processus DETACHES, lances a la main dans le conteneur. Le conteneur, lui, a une politique
`restart: unless-stopped` : il revient tout seul apres un plantage ou un redemarrage de la machine
-- mais sa commande ne lance que l ordonnanceur. **Les collecteurs, eux, resteraient morts**, et
personne ne s en apercevrait avant des heures.

Ce qui serait perdu : les sept tests GELES ne collectent plus, donc leurs criteres -- ecrits
d avance, et c est tout leur interet -- se jugeraient sur une periode trouee. Mido, la nuit du
17/09 : « un truc important, il faut rien casser pour que nos gels continuent de tourner la nuit ».
Un collecteur mort casse exactement ca, en silence.

CE QU IL FAIT, ET RIEN D AUTRE. Toutes les 60 s, il regarde dans `/proc` si chaque collecteur a
encore un processus. S il manque, il le relance. Il ne tue jamais rien, ne touche a aucune base, ne
decide rien. S il meurt lui-meme, les collecteurs continuent : il n est pas leur parent.

POURQUOI PAS DANS L ORDONNANCEUR. Les collecteurs sont des boucles `while True` avec leur propre
`main()`, pas des moteurs a `cycle()`. Les convertir demanderait de les recrire -- donc de risquer
de casser ce qui tourne, pour un gain nul. Un gardien separe est plus sur : il ne peut rien casser
puisqu il ne fait que demarrer des processus.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

# LE MENAGE DU 27/09 (Mido : « ok »). Neuf collecteurs retires : les sept forets (`foret_gel`,
# `foret_gel75`, `foret_flux`, `foret_marche`, `foret75_carnet`, `foret_gagnant`, `foret75_iso`),
# `prod_reentraine` (il reentrainait `foret_vidage_reentraine.json`, que plus rien ne lit depuis
# le passage a `modele_vidage.json`) et `papier_gd30` (G+D a 30 s ; celle a 45 s a gagne et tourne
# en reel). Toutes en perte, de −0,21 a −1,84 EUR/ticket sur 168 a 3 705 tickets. Les sept forets
# occupaient ~5 Go des 6,5 Go du conteneur -- la memoire qui a fait tomber Docker deux fois.
# RIEN N EST EFFACE : leurs bases restent sur le disque (consigne : tout garder pour l analyse
# finale). Les relancer = les remettre dans cette liste.
COLLECTEURS = ("papier_combo", "social_collecte", "prix_rapide", "stock_collecte", "v1_enregistreur",
               # la base de `papier_gd45` est celle que le suiveur G+D EXECUTE en reel
               # (`suiveur_gd.gd_db`). S il meurt, G+D cesse d acheter en silence.
               "papier_gd45", "papier_large", "veille_table",
               # alimente la page de suivi locale (Streamlit) : table toutes les 5 min, carnet reel
               # toutes les 20 s, et le registre des couts ticket par ticket. Sans lui la page se
               # fige en silence -- elle affiche l age de ses donnees, mais autant qu elle vive.
               "carnet_json",
               # LE FLUX SCORE DU CHALLENGER, sans lequel aucun modele reentraine ne peut etre
               # adopte : sa PAUSE doit voir le flux entier de SA bande, et ce flux n existe nulle
               # part ailleurs (`papier_combo` ne stocke que les scores du modele en service).
               # Adopter un challenger sans ce carnet ferait tourner sa bande SANS pause, soit
               # -106 EUR/jour (mesure du 26/09 sur 3 032 tickets). Papier, zero euro.
               "papier_challenger")
PAS = 60.0
JOURNAL = "/app/logs"


def vivants() -> set[str]:
    """Quels collecteurs ont un processus en vie, lu dans /proc -- `ps` n existe pas dans l image."""
    out: set[str] = set()
    moi = str(os.getpid())
    for pid in os.listdir("/proc"):
        if not pid.isdigit() or pid == moi:
            continue
        try:
            with open("/proc/%s/cmdline" % pid) as fh:
                cmd = fh.read().replace("\0", " ")
        except OSError:
            continue                          # le processus vient de disparaitre : rien a dire
        if "gardien" in cmd:
            continue                          # ne jamais se compter soi-meme
        for nom in COLLECTEURS:
            if "intel.research.%s" % nom in cmd:
                out.add(nom)
    return out


def relancer(nom: str) -> None:
    """Redemarre un collecteur, detache, en ajoutant a son journal plutot qu en l ecrasant."""
    chemin = os.path.join(JOURNAL, "%s.log" % nom)
    with open(chemin, "a") as fh:
        fh.write("\n--- relance par le gardien a %s ---\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
        fh.flush()
        subprocess.Popen([sys.executable, "-u", "-m", "intel.research.%s" % nom],
                         cwd="/app", stdout=fh, stderr=subprocess.STDOUT,
                         start_new_session=True)
    print("gardien: %s RELANCE" % nom, flush=True)


def main() -> None:
    print("gardien: demarre · surveille %s toutes les %.0f s"
          % (", ".join(COLLECTEURS), PAS), flush=True)
    # Au demarrage on laisse passer un tour : apres un redemarrage du conteneur, les collecteurs
    # peuvent etre en train de se lancer par ailleurs. Relancer trop vite en ferait deux.
    time.sleep(PAS)
    while True:
        try:
            v = vivants()
            for nom in COLLECTEURS:
                if nom not in v:
                    relancer(nom)
        except Exception as exc:  # noqa: BLE001
            print("gardien: tour rate (%s)" % str(exc)[:160], flush=True)
        time.sleep(PAS)


if __name__ == "__main__":
    main()
