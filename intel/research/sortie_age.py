"""A QUEL AGE FAUT-IL VENDRE ? Le meme ticket, mesure a six sorties.

MIDO, 20/09 : « attaque ». Suite de §3.164 : nos meilleures lignes tiennent MOINS longtemps que le
moteur (les 75s sortent a 240 s, le moteur a 287 s), et l historique dit +0,22 point pour ces 47 s
de moins. Sortie et modele sont donc confondus dans leur avantage. Ici on isole la sortie : memes
tickets, meme cout, meme entree -- seul l age de vente change.

POURQUOI C EST UNE COMPARAISON APPARIEE, et pourquoi ca change tout. Chaque ticket donne SIX
rendements, un par age de sortie. Comparer deux ages, c est comparer deux colonnes sur les memes
lignes : la variance du marche s annule, et le bruit est celui de la DIFFERENCE, pas celui du
niveau. C est l erreur de la regle 22 prise a l endroit -- ici elle joue pour nous, et une
difference de 0,2 point peut devenir mesurable la ou un niveau demanderait 3 000 tickets.

CE QUE CE SCRIPT NE DIT PAS. Il ne dit pas qu on peut vendre a cet age-la : le moteur cote, signe et
attend une confirmation, et §3.36 a montre que ne pas atterrir coute plus cher que le gain vise.
Sortir plus tot veut aussi dire plus de tickets par jour, donc plus de frais fixes. Ce script mesure
UNE chose : ce que le prix fait. L executabilite est une autre question, et elle vient apres.

Papier, zero euro, lecture seule.
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd

TABLE = "/app/data/recherche/tout/table.pkl"
COUT = float(os.environ.get("COUT_MESURE", "0.0371"))
MISE = 20.0
AGES = (60, 90, 120, 180, 240, 287)


def net(r):
    return MISE * ((1.0 + r) * (1.0 - COUT) - 1.0)


def main() -> None:
    df = pd.read_pickle(TABLE)
    cols = ["ret_%d" % h for h in AGES]
    df = df[(df["eligible"] == 1)].sort_values("t_dec")
    df = df.dropna(subset=cols).reset_index(drop=True)
    if len(df) < 200:
        print("sortie_age: %d tickets complets, trop peu" % len(df))
        return
    n = len(df)
    V = {h: net(df["ret_%d" % h].to_numpy(dtype=float)) for h in AGES}
    mi = n // 2
    print("%d tickets ayant les six sorties · cout %.2f pt · mise %.0f EUR" % (n, 100 * COUT, MISE))
    print()
    print("   %5s %11s %10s %9s %19s" % ("age", "EUR/ticket", "mediane", "gagnants", "deux moities"))
    for h in AGES:
        v = V[h]
        print("   %4ds %+11.3f %+10.3f %8.0f %% %+9.3f / %+7.3f"
              % (h, v.mean(), np.median(v), 100 * (v > 0).mean(), v[:mi].mean(), v[mi:].mean()))

    print()
    print("CHAQUE SORTIE CONTRE CELLE DU MOTEUR (287 s), COMPARAISON APPARIEE")
    print("   le bruit est celui de la DIFFERENCE sur les memes tickets, pas celui du niveau")
    print("   %5s %12s %10s %8s %19s" % ("age", "ecart", "bruit", "sigma", "deux moities"))
    ref = V[287]
    for h in AGES:
        if h == 287:
            continue
        d = V[h] - ref
        bruit = d.std(ddof=1) / np.sqrt(n)
        print("   %4ds %+12.3f %10.3f %+8.2f %+9.3f / %+7.3f"
              % (h, d.mean(), bruit, d.mean() / bruit if bruit else 0.0,
                 d[:mi].mean(), d[mi:].mean()))

    # LE VOLUME : sortir plus tot libere le capital plus vite. Mais le cout est PAR TICKET, donc
    # doubler la cadence double les frais fixes -- on le dit au lieu de le supposer.
    print()
    print("   Rappel : le cout de %.2f pt est PAR ALLER-RETOUR. Sortir deux fois plus vite ne le"
          % (100 * COUT))
    print("   divise pas, il se paie a chaque ticket. Un gain d age ne vaut que s il depasse ce")
    print("   qu on paierait a faire tourner l argent plus vite.")


if __name__ == "__main__":
    main()
