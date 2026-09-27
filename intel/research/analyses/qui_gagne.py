"""QUI PIEGE QUI ? Le SOLDE de chaque acteur, pas sa presence.

`qui_achete.py` a montre QUI est present : sur 1 668 lancements en quatre jours, un portefeuille
achete dans 1 615 d entre eux -- et les dix plus actifs sont tous des PORTEFEUILLES NORMAUX verifies
sur la chaine (ni programmes, ni comptes de programme, donc pas des routeurs). Personne ne clique
400 fois par jour : les premieres secondes sont peuplees de robots.

MAIS LA PRESENCE NE DIT PAS QUI PERD. Un robot present partout peut aussi bien etre celui qui
ramasse que celui qui se fait ramasser. La question de Mido -- « ils piegent qui ? » -- demande le
SOLDE, et c est ce que ce script mesure.

COMMENT ON LIT UN SOLDE, ET POURQUOI IL FAUT DEUX CHIFFRES ET PAS UN. Pour chaque (portefeuille,
lancement) on somme sur les 60 s enregistrees :
    d_SOL     ce qu il a encaisse moins ce qu il a depense ;
    d_jetons  ce qu il detient encore a la fin de la fenetre.
Un d_SOL negatif ne veut PAS dire qu il perd : il peut tenir des jetons qui valent quelque chose.
**On ne peut donc conclure que sur les positions BOUCLEES** -- celles ou il ne reste presque plus de
jetons (< 1 % de ce qui a ete achete). Pour celles-la, le d_SOL est le resultat, definitivement.

C est volontairement restrictif. Les positions encore ouvertes a 60 s sont comptees a part, et leur
sort est inconnu ici : ne rien conclure sur elles, c est exactement ce qui distingue cette mesure
d une estimation.

LE PIEGE DEJA EVITE UNE FOIS, a re-verifier ici. Une adresse vue partout peut etre une
infrastructure. Le controle sur la chaine (`executable`, proprietaire du compte) a montre que les
dix plus actives sont des portefeuilles ordinaires, mais le script le re-affiche pour que la
verification ne soit jamais implicite.
"""
from __future__ import annotations

import os
import statistics as st
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from qui_achete import lire  # noqa: E402

DOSSIER = os.environ.get("V1_DIR", "/app/data/recherche/v1_avant")
RESTE = 0.01               # moins de 1 % des jetons achetes encore detenus = position BOUCLEE
RECURRENT = 5


def main() -> None:
    # (portefeuille, lancement) -> [sol net, jetons achetes, jetons nets]
    cpt: defaultdict[tuple, list] = defaultdict(lambda: [0.0, 0.0, 0.0])
    pools: defaultdict[str, set] = defaultdict(set)
    n_pools = 0

    for pair, _naissance, mouvements in lire(DOSSIER):
        n_pools += 1
        for _age, qui, dj, ds in mouvements:
            c = cpt[(qui, pair)]
            c[0] += ds
            c[2] += dj
            if dj > 0 and ds < 0:
                c[1] += dj
                pools[qui].add(pair)

    print("%d lancements · %d couples (portefeuille, lancement)" % (n_pools, len(cpt)))

    boucle_rec, boucle_uni, ouvert_rec, ouvert_uni = [], [], [], []
    for (qui, _pair), (sol, achetes, nets) in cpt.items():
        if achetes <= 0:
            continue                               # n a jamais achete : createur, liquidite
        fini = nets <= RESTE * achetes             # il ne tient presque plus rien : c est solde
        rec = len(pools.get(qui, ())) >= RECURRENT
        (boucle_rec if rec else boucle_uni).append(sol) if fini else \
            (ouvert_rec if rec else ouvert_uni).append(sol)

    def montre(nom, v):
        if not v:
            print("   %-34s aucun" % nom)
            return
        gagnants = sum(1 for x in v if x > 0)
        print("   %-34s n=%6d   total %+9.1f SOL   median %+7.4f   gagnants %5.1f %%"
              % (nom, len(v), sum(v), st.median(v), 100 * gagnants / len(v)))

    print()
    print("POSITIONS BOUCLEES DANS LES 60 s -- le d_SOL EST le resultat, definitivement")
    montre("robots (>= %d lancements)" % RECURRENT, boucle_rec)
    montre("portefeuilles occasionnels", boucle_uni)

    print()
    print("POSITIONS ENCORE OUVERTES A 60 s -- resultat INCONNU, ne rien en conclure")
    montre("robots (>= %d lancements)" % RECURRENT, ouvert_rec)
    montre("portefeuilles occasionnels", ouvert_uni)

    # ------------------------------------------------------------------ les plus actifs, un par un
    print()
    print("LES DIX PORTEFEUILLES LES PLUS ACTIFS, chacun sur ses positions BOUCLEES")
    print("   (verifies sur la chaine : tous des portefeuilles ordinaires, ni programmes ni PDA)")
    top = sorted(pools.items(), key=lambda kv: -len(kv[1]))[:10]
    for a, s in top:
        v = [sol for (q, _p), (sol, ach, nets) in cpt.items()
             if q == a and ach > 0 and nets <= RESTE * ach]
        if not v:
            print("   %-44s %4d lancements · aucune position bouclee" % (a[:42], len(s)))
            continue
        print("   %-44s %4d lancements · %4d bouclees · total %+8.1f SOL · %5.1f %% gagnantes"
              % (a[:42], len(s), len(v), sum(v), 100 * sum(1 for x in v if x > 0) / len(v)))


if __name__ == "__main__":
    main()
