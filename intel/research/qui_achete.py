"""QUI SE FAIT PIEGER ? La question de Mido, posee le 18/09 au soir.

    « Ces escrocs creent des jetons et retirent en quelques secondes. Ils piegent qui ? L humain qui
    execute a la main n aura pas le temps de rentrer. Est-ce que les gens comme nous ne sont pas
    leur cible ? »

C est une question de FAIT, et on a exactement les donnees pour y repondre : `v1_enregistreur`
enregistre depuis le 15/09 les 60 premieres secondes de chaque lancement, transaction par
transaction, avec le proprietaire, les jetons recus et le SOL depense. Quatre jours, ~180 Mo.

CE QU ON MESURE, et pourquoi chaque mesure repond a une moitie de la question :

 1. QUAND les achats tombent. Si la masse est dans les toutes premieres secondes, aucun humain
    n a le temps : la reponse est deja la.
 2. QUI achete : un portefeuille vu dans UN seul lancement, ou dans des dizaines ? Un portefeuille
    present sur 50 lancements en quatre jours n est pas une personne qui clique.
 3. COMBIEN ils engagent, par classe. Un robot qui mise 0,3 SOL cinquante fois n est pas la meme
    proie qu un portefeuille qui mise 5 SOL une fois.
 4. Et NOUS, dans tout ca : a 47 s, combien d acheteurs sont deja passes, et sommes-nous dans la
    queue ou dans la tete ?

LE CONTROLE A FAIRE AVANT TOUT LE RESTE, sinon la mesure ne veut rien dire. Le champ
`proprietaire` peut etre un ROUTEUR et non un acheteur : 98 % des sorties de pool passent par un
routeur (§3.42), et c est ce piege qui a rendu `sac_wallet` inutilisable (654 jetons, 654
portefeuilles distincts : c etait le coffre). On affiche donc d abord les dix adresses vues dans le
plus de lancements. Si l une domine massivement, c est une infrastructure, pas un acheteur, et elle
doit etre ecartee avant de conclure quoi que ce soit.

CE QUE CETTE MESURE NE DIT PAS. Elle ne dit pas qui GAGNE ou qui PERD -- seulement qui est present
et quand. Le resultat par acheteur demande de croiser avec le prix a 240 s, c est une seconde
etape. Ne pas conclure sur l argent a partir d un comptage de presences.
"""
from __future__ import annotations

import glob
import json
import os
import statistics as st
import sys
from collections import Counter, defaultdict

DOSSIER = os.environ.get("V1_DIR", "/app/data/recherche/v1_avant")
NOTRE_AGE = 47           # l instant ou notre moteur achete
RECURRENT = 5            # vu dans au moins 5 lancements = ce n est plus une personne qui clique


def lire(dossier: str):
    """Rend (pair, naissance, [(age, proprietaire, d_jetons, d_sol)]) pour chaque lancement."""
    for f in sorted(glob.glob(os.path.join(dossier, "*.jsonl"))):
        with open(f, encoding="utf-8") as fh:
            for ligne in fh:
                try:
                    d = json.loads(ligne)
                except Exception:  # noqa: BLE001
                    continue
                mouvements = []
                for tx in d.get("tx") or []:
                    try:
                        age, _v, parts = tx[0], tx[1], tx[2]
                    except Exception:  # noqa: BLE001
                        continue
                    for p in parts or []:
                        try:
                            mouvements.append((int(age), str(p[0]), float(p[1]), float(p[2])))
                        except Exception:  # noqa: BLE001
                            continue
                yield d.get("pair"), d.get("naissance"), mouvements


def main() -> None:
    pools_par_adresse: defaultdict[str, set] = defaultdict(set)
    achats = []                        # (age, adresse, sol engage)
    n_pools = 0

    for pair, _naissance, mouvements in lire(DOSSIER):
        n_pools += 1
        for age, qui, dj, ds in mouvements:
            # ACHAT = recoit des jetons ET depense du SOL. Le signe a deja ete une source de bug
            # dans ce projet (`features.py`), donc on exige les DEUX conditions, jamais une seule.
            if dj > 0 and ds < 0:
                achats.append((age, qui, -ds))
                pools_par_adresse[qui].add(pair)

    print("%d lancements · %d achats" % (n_pools, len(achats)))
    if not achats:
        return

    # ------------------------------------------------------------------ le controle, d abord
    print()
    print("CONTROLE : les dix adresses vues dans le plus de lancements")
    print("  (si l une domine, c est un ROUTEUR ou une infrastructure, pas un acheteur)")
    top = sorted(pools_par_adresse.items(), key=lambda kv: -len(kv[1]))[:10]
    for a, s in top:
        print("   %-46s %5d lancements (%.1f %%)" % (a, len(s), 100 * len(s) / n_pools))

    # ------------------------------------------------------------------ 1. quand
    print()
    print("1. QUAND LES ACHATS TOMBENT")
    tranches = [(0, 1), (1, 3), (3, 5), (5, 10), (10, 20), (20, 30), (30, 45), (45, 61)]
    tot = len(achats)
    cum = 0
    for a, b in tranches:
        n = sum(1 for age, _q, _s in achats if a <= age < b)
        cum += n
        print("   %2d-%2d s  %6d achats  %5.1f %%   cumule %5.1f %%"
              % (a, b, n, 100 * n / tot, 100 * cum / tot))
    avant_nous = sum(1 for age, _q, _s in achats if age < NOTRE_AGE)
    print("   -> %.1f %% des achats des 60 premieres secondes sont deja passes quand NOUS achetons"
          " a %d s" % (100 * avant_nous / tot, NOTRE_AGE))

    # ------------------------------------------------------------------ 2. qui
    print()
    print("2. QUI ACHETE : une personne qui clique, ou une adresse qui revient ?")
    vus = Counter({a: len(s) for a, s in pools_par_adresse.items()})
    uniques = sum(1 for _a, n in vus.items() if n == 1)
    recur = sum(1 for _a, n in vus.items() if n >= RECURRENT)
    print("   %d adresses acheteuses distinctes" % len(vus))
    print("   vues dans UN seul lancement      : %6d  (%.1f %%)"
          % (uniques, 100 * uniques / len(vus)))
    print("   vues dans >= %d lancements        : %6d  (%.1f %%)"
          % (RECURRENT, recur, 100 * recur / len(vus)))
    print("   la plus active                   : %d lancements sur %d" % (vus.most_common(1)[0][1], n_pools))

    # la part des ACHATS (et non des adresses) faite par les recurrentes : c est elle qui dit qui
    # tient le marche. Beaucoup d adresses uniques peut cacher peu de volume.
    rec = {a for a, n in vus.items() if n >= RECURRENT}
    n_rec = sum(1 for _age, q, _s in achats if q in rec)
    sol_rec = sum(s for _age, q, s in achats if q in rec)
    sol_tot = sum(s for _age, _q, s in achats)
    print("   part des ACHATS faits par les recurrentes : %.1f %%" % (100 * n_rec / tot))
    print("   part du SOL  engage par les recurrentes   : %.1f %%" % (100 * sol_rec / max(sol_tot, 1e-9)))

    # ------------------------------------------------------------------ 3. combien
    print()
    print("3. COMBIEN ILS ENGAGENT (SOL par achat)")
    for nom, sel in (("recurrentes (>= %d pools)" % RECURRENT, [s for _a, q, s in achats if q in rec]),
                     ("uniques (1 seul pool)", [s for _a, q, s in achats
                                                if vus.get(q, 0) == 1])):
        if sel:
            print("   %-28s n=%6d  median %.3f SOL  moyenne %.3f  total %.0f SOL"
                  % (nom, len(sel), st.median(sel), st.mean(sel), sum(sel)))

    # ------------------------------------------------------------------ 4. et nous
    print()
    print("4. LA TETE ET LA QUEUE")
    par_pool_avant = []
    for pair, _n, mouv in lire(DOSSIER):
        a = {q for age, q, dj, ds in mouv if dj > 0 and ds < 0 and age < NOTRE_AGE}
        par_pool_avant.append(len(a))
    if par_pool_avant:
        par_pool_avant.sort()
        m = par_pool_avant[len(par_pool_avant) // 2]
        print("   acheteurs distincts deja entres avant %d s : median %d par lancement"
              % (NOTRE_AGE, m))
        print("   (quartiles %d / %d)"
              % (par_pool_avant[len(par_pool_avant) // 4],
                 par_pool_avant[3 * len(par_pool_avant) // 4]))


if __name__ == "__main__":
    main()
