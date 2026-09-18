"""QUI GAGNE VRAIMENT ? Le solde COMPLET, ce qui reste sur les bras inclus.

LA QUESTION, DE MIDO : « alors tu veux dire quoi, ni eux ni nous ne font de l argent ? »

CE QUI MANQUAIT AUX DEUX MESURES PRECEDENTES. `qui_gagne.py` ne comptait que les positions BOUCLEES
dans les 60 s -- 18 % du total -- parce que pour les autres le SOL depense ne dit rien tant qu on ne
sait pas ce que valent les jetons gardes. Resultat : +4 623 SOL, mais sur un cinquieme des positions,
et precisement celui ou l acteur a REUSSI a sortir. Ca ne repond pas a « qui gagne ».

CE QU ON FAIT ICI. Pour chaque (portefeuille, lancement) on ajoute au SOL net ce que ses jetons
restants rapporteraient s il les vendait DANS LE POOL, a la fin de la fenetre :

    SOL rendu = (coffre SOL + V) x jetons / (coffre jetons + jetons)      -- produit constant

PREMIERE VERSION, FAUSSE, ET POURQUOI. J avais d abord valorise au PRIX affiche,
(coffre SOL + V) / coffre jetons. Resultat : **+11 407 308 SOL au total**, soit plus d un milliard
d euros -- absurde. La cause est mecanique : quand la liquidite est retiree, le coffre en jetons
tend vers zero, donc ce prix EXPLOSE, et on valorise a l infini precisement les jetons qui ne valent
plus rien. Une valorisation « genereuse » doit rester BORNEE, sinon elle ne dit plus rien. La
formule du produit constant l est par construction : on ne peut jamais extraire plus que ce que le
pool contient.

LE CADEAU EST DELIBERE, et il faut le dire avant de lire le resultat. Cette valorisation est
GENEREUSE pour celui qui detient encore :
  - elle ignore l IMPACT : vendre 40 % du coffre ne se fait pas au prix affiche ;
  - elle ignore la SUITE, alors qu on a mesure que garder un jeton effondre aggrave TOUJOURS
    (-80,5 % a 4 min, -97,1 % a 20 h, monotone, et 20 % disparaissent) ;
  - elle ignore le cout de la vente qui reste a payer.
Donc **si un groupe est deja negatif dans cette comptabilite, il l est reellement**, et davantage.
C est le seul sens dans lequel on peut conclure, et c est pour ca qu on choisit ce biais-la.

CE QU ON CHERCHE : la part des portefeuilles qui finissent positifs, par classe d activite. Si
presque personne n est positif, la reponse a Mido est oui -- le jeu n a pas de gagnant visible dans
les 60 premieres secondes, et l argent part ailleurs (createur, retrait de liquidite, frais).
"""
from __future__ import annotations

import os
import statistics as st
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import glob  # noqa: E402
import json  # noqa: E402

DOSSIER = os.environ.get("V1_DIR", "/app/data/recherche/v1_avant")
RECURRENT = 5


def main() -> None:
    # (portefeuille, pool) -> [sol net, jetons nets, a achete]
    cpt: defaultdict[tuple, list] = defaultdict(lambda: [0.0, 0.0, False])
    coffres: dict[str, tuple] = {}            # (SOL + V, jetons) a la fin de la fenetre
    pools: defaultdict[str, set] = defaultdict(set)
    n_pools = 0
    sans_prix = 0

    for f in sorted(glob.glob(os.path.join(DOSSIER, "*.jsonl"))):
        with open(f, encoding="utf-8") as fh:
            for ligne in fh:
                try:
                    d = json.loads(ligne)
                except Exception:  # noqa: BLE001
                    continue
                pair, V = d.get("pair"), float(d.get("V") or 0)
                n_pools += 1
                prix = None
                mouv = []
                for tx in d.get("tx") or []:
                    try:
                        parts, cs, cj = tx[2], tx[3], tx[4]
                    except Exception:  # noqa: BLE001
                        continue
                    # le DERNIER etat lisible du coffre : on en garde les DEUX reserves, pas un
                    # prix -- c est la paire qui permet de borner la valeur de sortie
                    if cs is not None and cj:
                        prix = (float(cs) + V, float(cj))
                    for p in parts or []:
                        try:
                            mouv.append((str(p[0]), float(p[1]), float(p[2])))
                        except Exception:  # noqa: BLE001
                            continue
                if prix is None:
                    sans_prix += 1
                    continue
                coffres[pair] = prix
                for qui, dj, ds in mouv:
                    c = cpt[(qui, pair)]
                    c[0] += ds
                    c[1] += dj
                    if dj > 0 and ds < 0:
                        c[2] = True
                        pools[qui].add(pair)

    print("%d lancements (%d sans prix lisible, ecartes)" % (n_pools, sans_prix))

    # solde par PORTEFEUILLE, tous ses lancements confondus
    solde: defaultdict[str, float] = defaultdict(float)
    for (qui, pair), c in cpt.items():
        if not c[2]:
            continue                              # n a jamais achete : createur, liquidite
        reste = max(0.0, c[1])
        cs, cj = coffres.get(pair, (0.0, 0.0))
        # ce que le pool rendrait REELLEMENT pour ces jetons : borne par le contenu du pool
        rendu = (cs * reste / (cj + reste)) if (cj + reste) > 0 else 0.0
        solde[qui] += c[0] + rendu

    def montre(nom: str, v: list[float]) -> None:
        if not v:
            print("   %-32s aucun" % nom)
            return
        s = sorted(v)
        print("   %-32s n=%6d  total %+10.1f SOL  median %+8.4f  positifs %5.1f %%"
              % (nom, len(v), sum(v), st.median(v), 100 * sum(1 for x in v if x > 0) / len(v)))
        print("   %-32s sans les 10 meilleurs : %+.1f SOL" % ("", sum(s[:-10])))

    tres = [s for q, s in solde.items() if len(pools[q]) >= 50]
    rec = [s for q, s in solde.items() if RECURRENT <= len(pools[q]) < 50]
    occ = [s for q, s in solde.items() if len(pools[q]) < RECURRENT]

    print()
    print("SOLDE COMPLET PAR PORTEFEUILLE -- jetons gardes valorises au prix de fin de fenetre")
    print("(valorisation GENEREUSE : sans impact, sans la suite, sans le cout de la vente)")
    montre("robots tres actifs (>= 50 pools)", tres)
    montre("recurrents (%d a 49 pools)" % RECURRENT, rec)
    montre("occasionnels (< %d pools)" % RECURRENT, occ)
    tout = list(solde.values())
    montre("TOUS", tout)

    print()
    print("LES DIX PLUS ACTIFS, SOLDE COMPLET")
    for q, s in sorted(pools.items(), key=lambda kv: -len(kv[1]))[:10]:
        print("   %-44s %4d pools · %+9.2f SOL" % (q[:42], len(s), solde.get(q, 0.0)))


if __name__ == "__main__":
    main()
