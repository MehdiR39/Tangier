"""PAYONS-NOUS PLUS CHER QUE LES AUTRES ? La commission des tiers contre la notre.

CE QUI AMENE ICI (19/09 au soir). Le cout d execution est de 3,71 points par aller-retour ; resolu
sur nos propres echanges, cela correspond a une commission de **1,81 % par jambe** (la reserve
virtuelle, resolue en meme temps, ressort a 17,99 -- la constante du projet, 17,5845, est donc
confirmee). Mais 1,81 % n est le parametre d aucun pool : sur 12 pools aux commissions mesurees de
0,9 a 3,5 %, AUCUN octet des 301 du compte ne les separe. La commission ne vient donc pas du pool.

L HYPOTHESE. Nos ordres passent par **Jupiter**, un agregateur qui construit la route et signe pour
nous (`intel/execution/solana.py`). Ce que je prenais pour la commission du pool contient donc la
marge du routeur. Si c est vrai, une grande partie du cout n est pas un peage mais un choix
d implementation -- et un choix se change.

COMMENT ON TRANCHE. `v1_enregistreur` enregistre TOUTES les transactions de chaque pool pendant ses
60 premieres secondes, avec l etat du coffre apres chacune. L etat AVANT une transaction est donc
l etat APRES la precedente. On peut ainsi calculer la commission effective de CHAQUE echange du
pool -- ceux des autres, qui tapent le pool en direct -- exactement comme on l a fait pour les
notres.

    achat   jetons = R_j . d_sol(1-f) / (R_s + V + d_sol(1-f))
    vente   sol    = (R_s + V) . d_jet(1-f) / (R_j + d_jet(1-f))

Si les tiers paient ~0,3 % et nous 1,8 %, l ecart est notre routage, et il se supprime.
Si les tiers paient 1,8 % aussi, c est le prix du marche et il n y a rien a faire.
"""
from __future__ import annotations

import glob
import json
import os

import numpy as np

V1 = "/app/data/recherche/v1_avant"
V_RESERVE = 17.5845
SORTIE = "/app/data/cout_routeur.json"


def f_achat(Rs, Rj, dsol, jetons):
    den = Rj - jetons
    if den <= 0 or dsol <= 0 or jetons <= 0:
        return None
    return 1.0 - (jetons * (Rs + V_RESERVE) / den) / dsol


def f_vente(Rs, Rj, djet, sol):
    den = (Rs + V_RESERVE) - sol
    if den <= 0 or djet <= 0 or sol <= 0:
        return None
    return 1.0 - (sol * Rj / den) / djet


def main() -> None:
    achats, ventes, tailles = [], [], []
    pools = 0
    for fichier in sorted(glob.glob(os.path.join(V1, "*.jsonl"))):
        with open(fichier, encoding="utf-8") as fh:
            for ligne in fh:
                try:
                    d = json.loads(ligne)
                except Exception:  # noqa: BLE001
                    continue
                tx = d.get("tx") or []
                if len(tx) < 3:
                    continue
                pools += 1
                # tx = [age, version, [[proprio, d_jetons, d_SOL]], coffre SOL apres,
                #       coffre jetons apres, nb signataires, payeur]
                # L etat AVANT une transaction est l etat APRES la precedente.
                for i in range(1, len(tx)):
                    try:
                        Rs, Rj = float(tx[i - 1][3]), float(tx[i - 1][4])
                        parts = tx[i][2] or []
                    except Exception:  # noqa: BLE001
                        continue
                    if Rs <= 0 or Rj <= 0 or len(parts) != 1:
                        continue            # on ne garde que les echanges SIMPLES, un seul portefeuille
                    try:
                        _, dj, ds = parts[0][0], float(parts[0][1]), float(parts[0][2])
                    except Exception:  # noqa: BLE001
                        continue
                    if dj > 0 and ds < 0:                      # un ACHAT du tiers
                        f = f_achat(Rs, Rj, -ds, dj)
                        if f is not None and 0 < f < 0.20:
                            achats.append(f)
                            tailles.append(-ds / (Rs + V_RESERVE))
                    elif dj < 0 and ds > 0:                    # une VENTE du tiers
                        f = f_vente(Rs, Rj, -dj, ds)
                        if f is not None and 0 < f < 0.20:
                            ventes.append(f)

    a, v = np.array(achats), np.array(ventes)
    if len(a) < 50 or len(v) < 50:
        print("cout_routeur: pas assez d echanges exploitables (%d achats, %d ventes)" % (len(a), len(v)))
        return
    json.dump({"n_achats": len(a), "n_ventes": len(v),
               "achat_median": float(np.median(a)), "vente_median": float(np.median(v))},
              open(SORTIE, "w"))
    print("LES ECHANGES DES AUTRES, dans les memes pools (%d pools lus)" % pools)
    print()
    for nom, x in (("ACHAT", a), ("VENTE", v)):
        q = np.percentile(x, [10, 25, 50, 75, 90])
        print("   %-6s n=%6d · mediane %5.3f %% · quartiles %5.3f / %5.3f · deciles %5.3f / %5.3f"
              % (nom, len(x), 100 * q[2], 100 * q[1], 100 * q[3], 100 * q[0], 100 * q[4]))
    print()
    print("   aller-retour des tiers : %.3f %%" % (100 * (np.median(a) + np.median(v))))
    print("   NOTRE aller-retour     : 3.620 %% (1,81 %% par jambe, resolu sur nos 91 tickets)")
    print()
    ecart = 3.620 - 100 * (np.median(a) + np.median(v))
    print("   -> ECART : %+.3f point" % ecart)
    if ecart > 0.5:
        print("      Nous payons nettement plus que les autres dans les MEMES pools.")
        print("      Ce n est donc pas un peage : c est notre chemin d execution.")
    elif ecart < -0.5:
        print("      Nous payons MOINS que les autres -- resultat inattendu, a re-verifier.")
    else:
        print("      Nous payons comme tout le monde : c est le prix du marche, pas notre routage.")
    print()
    t = np.array(tailles)
    print("   pour comparaison, la taille des ordres des tiers : mediane %.3f %% du pool"
          % (100 * np.median(t)))
    print("   la notre : environ 0,3 %% du pool (0,2 SOL sur ~70)")


if __name__ == "__main__":
    main()
