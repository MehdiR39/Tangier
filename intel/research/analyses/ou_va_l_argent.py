"""OU VA L ARGENT ? Le seul acteur qu on n avait pas compte : celui qui RETIRE la liquidite.

CE QUI EST DEJA ETABLI. Dans les 60 premieres secondes, AUCUNE classe d acheteurs n a repris son
argent : les robots tres actifs sont a -6 422 SOL encaisses, les recurrents a -130 153, les
occasionnels a -291 095. Leur « benefice » est a 100 % du papier -- des jetons encore detenus, dont
on a mesure par ailleurs qu ils tombent a -80,5 % en 4 minutes et -97,1 % en 20 heures.

Donc l argent sort des poches des acheteurs. Il va bien QUELQUE PART.

COMMENT ON RECONNAIT CHAQUE MOUVEMENT, sans deviner. Chaque transaction laisse l etat des deux
reserves du pool. Le sens des deux variations suffit a classer, sans ambiguite :

    jetons BAISSE, SOL MONTE      un ACHAT      (il prend des jetons, il verse du SOL)
    jetons MONTE,  SOL BAISSE     une VENTE     (il rend des jetons, il emporte du SOL)
    les DEUX MONTENT              on AJOUTE de la liquidite
    les DEUX BAISSENT             on RETIRE de la liquidite   <- l acteur qu on cherche

Un retrait est la seule operation qui vide le pool des deux cotes a la fois. C est la signature
qu on ne peut pas confondre avec une vente, et c est pour ca qu on classe sur le COUPLE de signes
et jamais sur une seule reserve.

A QUI ON L ATTRIBUE. Au `payeur` de la transaction -- le signataire qui paie les frais. C est le
champ le plus proche de « qui a decide », et il est present sur chaque ligne.

CE QUE CETTE MESURE NE PROUVE PAS. Qu un retrait soit une escroquerie. Retirer sa liquidite est une
operation legitime, et certains pools la retirent pour migrer ailleurs. On compte des flux, on ne
qualifie pas des intentions. Ce qui est mesure : combien de SOL sort par cette porte, sur combien de
lancements, et si les memes signataires reviennent.
"""
from __future__ import annotations

import glob
import json
import os
import statistics as st
from collections import defaultdict

DOSSIER = os.environ.get("V1_DIR", "/app/data/recherche/v1_avant")
BRUIT = 1e-9                   # en dessous, c est du bruit d arrondi, pas un mouvement


def main() -> None:
    n_pools = 0
    retraits_par_pool: dict[str, float] = {}
    sol_par_payeur: defaultdict[str, float] = defaultdict(float)
    pools_par_payeur: defaultdict[str, set] = defaultdict(set)
    ages_retrait = []
    achats_sol = 0.0
    ventes_sol = 0.0
    ajouts_sol = 0.0
    retraits_sol = 0.0

    for f in sorted(glob.glob(os.path.join(DOSSIER, "*.jsonl"))):
        with open(f, encoding="utf-8") as fh:
            for ligne in fh:
                try:
                    d = json.loads(ligne)
                except Exception:  # noqa: BLE001
                    continue
                pair = d.get("pair")
                n_pools += 1
                prec = None
                for tx in d.get("tx") or []:
                    try:
                        age, cs, cj, payeur = tx[0], tx[3], tx[4], tx[6]
                    except Exception:  # noqa: BLE001
                        continue
                    if cs is None or cj is None:
                        continue
                    cs, cj = float(cs), float(cj)
                    if prec is not None:
                        dsol, djet = cs - prec[0], cj - prec[1]
                        if abs(dsol) > BRUIT and abs(djet) > BRUIT:
                            if djet < 0 and dsol > 0:
                                achats_sol += dsol
                            elif djet > 0 and dsol < 0:
                                ventes_sol += -dsol
                            elif djet > 0 and dsol > 0:
                                ajouts_sol += dsol
                            else:                       # les DEUX baissent : un RETRAIT
                                retraits_sol += -dsol
                                retraits_par_pool[pair] = retraits_par_pool.get(pair, 0.0) - dsol
                                if payeur:
                                    sol_par_payeur[str(payeur)] += -dsol
                                    pools_par_payeur[str(payeur)].add(pair)
                                ages_retrait.append(int(age))
                    prec = (cs, cj)

    print("%d lancements · les 60 premieres secondes" % n_pools)
    print()
    print("LES QUATRE PORTES DU POOL, en SOL")
    print("   entre : achats              %+10.0f SOL" % achats_sol)
    print("   entre : ajouts de liquidite %+10.0f SOL" % ajouts_sol)
    print("   sort  : ventes              %+10.0f SOL" % -ventes_sol)
    print("   sort  : RETRAITS            %+10.0f SOL" % -retraits_sol)
    print("   ------------------------------------------")
    print("   solde du pool               %+10.0f SOL" % (achats_sol + ajouts_sol - ventes_sol - retraits_sol))

    print()
    print("LES RETRAITS DE LIQUIDITE")
    if not retraits_par_pool:
        print("   aucun retrait detecte dans la fenetre de 60 s")
        return
    v = sorted(retraits_par_pool.values())
    print("   %d lancements sur %d en subissent un dans les 60 s  (%.1f %%)"
          % (len(v), n_pools, 100 * len(v) / n_pools))
    print("   SOL retire : total %.0f · median %.2f · moyenne %.2f par lancement touche"
          % (sum(v), st.median(v), st.mean(v)))
    if ages_retrait:
        ages_retrait.sort()
        print("   age du retrait : median %d s · quartiles %d / %d s"
              % (ages_retrait[len(ages_retrait) // 2], ages_retrait[len(ages_retrait) // 4],
                 ages_retrait[3 * len(ages_retrait) // 4]))

    print()
    print("LES SIGNATAIRES QUI RETIRENT -- reviennent-ils d un lancement a l autre ?")
    top = sorted(sol_par_payeur.items(), key=lambda kv: -kv[1])[:12]
    for a, s in top:
        print("   %-46s %9.2f SOL sur %4d lancement(s)" % (a[:44], s, len(pools_par_payeur[a])))
    multi = [a for a, p in pools_par_payeur.items() if len(p) >= 5]
    print()
    print("   signataires ayant retire sur >= 5 lancements : %d" % len(multi))
    if multi:
        print("   ils totalisent %.0f SOL, soit %.1f %% de tout ce qui est retire"
              % (sum(sol_par_payeur[a] for a in multi),
                 100 * sum(sol_par_payeur[a] for a in multi) / max(sum(v), 1e-9)))


if __name__ == "__main__":
    main()
