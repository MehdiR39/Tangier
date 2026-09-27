"""A QUEL AGE `v1_enregistreur` A-T-IL ECRIT CHAQUE POOL ? Le moteur pourra-t-il le LIRE a 75 s ?

Suite de `latence_75`. L appel Helius tient dans les 5 s (mediane 0,70 s, 96 % des pools) -- mais en
le mesurant j ai vu mieux : **`v1_enregistreur` fait deja cet appel pour chaque pool**, a 70 s, et
ecrit le resultat dans `v1_avant/AAAAMMJJ.jsonl`. Si le moteur LIT ce fichier au lieu de rappeler
Helius, le quota ne bouge pas d un credit et la latence tombe a une lecture de fichier.

MAIS CA NE MARCHE QUE SI L ENREGISTREUR TIENT LA CADENCE. Il traite les pools en file, avec un
garde-fou de budget Helius ; s il prend du retard, la ligne d un pool n est ecrite qu a 200 s et le
moteur ne trouvera rien a 75 s. Ce script mesure ce retard REEL, pool par pool : l age du pool au
moment ou sa ligne a ete ecrite.

MESURE : pour chaque ligne du jour, `ecrit_a` (horodatage pose par l enregistreur) moins
`naissance`. Si ce nombre est <= 75 s pour l essentiel des pools, le moteur peut lire. Sinon il
faudra qu il appelle lui-meme -- ce qui marche aussi (96 %), mais coute du quota.

Lecture seule.
"""
from __future__ import annotations

import datetime as dt
import glob
import json
import os
import time

V1 = "/app/data/recherche/v1_avant"
DECISION = 75.0


def main() -> None:
    fichiers = sorted(glob.glob(os.path.join(V1, "*.jsonl")))[-2:]
    if not fichiers:
        print("v1_retard: aucun fichier")
        return
    ages, sans_horodatage, total = [], 0, 0
    cles = set()
    for f in fichiers:
        with open(f, encoding="utf-8") as fh:
            for ligne in fh:
                try:
                    d = json.loads(ligne)
                except Exception:  # noqa: BLE001
                    continue
                total += 1
                cles |= set(d)
                naiss = float(d.get("naissance") or 0)
                ecrit = d.get("ecrit_a") or d.get("ts") or d.get("t_ecrit")
                if not naiss or not ecrit:
                    sans_horodatage += 1
                    continue
                ages.append(float(ecrit) - naiss)
    print("%d pools lus dans %s" % (total, ", ".join(os.path.basename(x) for x in fichiers)))
    print("champs disponibles par ligne : %s" % " ".join(sorted(cles)))
    if not ages:
        print()
        print("   AUCUN horodatage d ecriture dans le fichier : on ne peut pas mesurer le retard")
        print("   directement. Il faudra l ajouter a l enregistreur, ou faire appeler le moteur.")
        # repli : l age du fichier le plus recent contre la naissance du dernier pool ecrit
        f = fichiers[-1]
        dernier = None
        with open(f, encoding="utf-8") as fh:
            for ligne in fh:
                try:
                    dernier = json.loads(ligne)
                except Exception:  # noqa: BLE001
                    pass
        if dernier and dernier.get("naissance"):
            r = os.path.getmtime(f) - float(dernier["naissance"])
            print()
            print("   REPLI : la derniere ligne ecrite porte une naissance a %s ;"
                  % dt.datetime.fromtimestamp(float(dernier["naissance"])).strftime("%H:%M:%S"))
            print("   le fichier a ete touche %.0f s apres cette naissance." % r)
            print("   (borne haute : le fichier a pu etre touche par une ligne ulterieure)")
        return
    ages.sort()
    q = lambda f_: ages[min(int(f_ * len(ages)), len(ages) - 1)]  # noqa: E731
    print()
    print("   retard d ecriture : mediane %.0f s · q3 %.0f · d9 %.0f · max %.0f"
          % (q(.5), q(.75), q(.9), ages[-1]))
    ok = sum(1 for a in ages if a <= DECISION)
    print("   ecrits avant %.0f s : %d sur %d (%.0f %%)" % (DECISION, ok, len(ages), 100 * ok / len(ages)))
    print()
    if 100 * ok / len(ages) >= 90:
        print("   -> LE MOTEUR PEUT LIRE le fichier : zero appel, zero quota, zero latence.")
    else:
        print("   -> l enregistreur est trop lent pour etre lu a 75 s ; le moteur devra appeler")
        print("      lui-meme (mediane 0,70 s, 96 % des pools) et cela consommera du quota.")


if __name__ == "__main__":
    main()
