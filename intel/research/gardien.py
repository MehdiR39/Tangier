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

COLLECTEURS = ("papier_combo", "social_collecte", "prix_rapide", "stock_collecte", "foret_gel", "foret_gel75", "v1_enregistreur",
               "papier_gd45", "papier_gd30", "papier_large", "veille_table",
               # alimente la page de suivi locale (Streamlit) : table toutes les 5 min, carnet reel
               # toutes les 20 s, et le registre des couts ticket par ticket. Sans lui la page se
               # fige en silence -- elle affiche l age de ses donnees, mais autant qu elle vive.
               "carnet_json",
               # la foret de vidage au FLUX D ORDRES, gelee le 19/09 16h00 : elle n apprend que sur
               # les transactions <= 30 s, la seule vue que l index montre surement a l instant de
               # decider. Papier, zero euro, critere a 600 tickets.
               "foret_flux",
               # la METHODE reentrainee, gelee le 19/09 21h23 : la recette est figee (15 variables,
               # aucune de cout, reentrainement toutes les 6 h, on garde 80 %), les poids se
               # refont. Papier, zero euro, critere a 1 200 tickets.
               "foret_marche",
               # la recette 75 s REENTRAINEE, gelee le 19/09 23h35 : decision a 75 s, 25 variables
               # rechoisies a chaque coupe, SEUIL ABSOLU a 20 %. Ce qui se refait toutes les 6 h,
               # c est aussi le seuil -- c est la l essentiel de l effet mesure (§3.158). Papier,
               # zero euro, critere a 400 retenus, dont une condition sur le NIVEAU.
               "foret75_carnet",
               # la BONNE QUESTION, gelee le 20/09 : cible « gagnant net » au lieu de « pas de
               # vidage », seuil absolu a 20 %, reentrainee toutes les 6 h. §3.159 : demander
               # « ne t effondre pas » selectionne l immobilite, et l immobilite paie le peage.
               # Papier, zero euro, deux echeances : 400 retenus puis 2 000.
               "foret_gagnant",
               # LE REENTRAINEMENT DU MODELE EN PRODUCTION, branche le 20/09 au soir. S il meurt,
               # le moteur continue de tourner sur le dernier fichier ecrit -- il ne s arrete pas,
               # il vieillit. C est precisement le genre de panne silencieuse que ce gardien existe
               # pour empecher : ici elle coute de l argent reel, pas des tickets de recherche.
               "prod_reentraine")
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
