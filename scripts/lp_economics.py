#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Fournir la liquidite plutot que la consommer : est-ce le bon siege ?

Le carnet paie 2 % par aller-retour. Ce peage n'est pas perdu pour tout le monde : il va aux
fournisseurs de liquidite. Dans un jeu ou le mouvement median est plus petit que le peage, le siege
rentable pourrait etre celui qui l'encaisse.

Deux cas radicalement differents, testes separement :

  1. LP sur un pool de memecoin. Fournir de la liquidite, c'est detenir le jeton. Sur une tranche
     dont l'issue mediane est x0,17 et dont un lancement sur cinq finit sous x0,10, c'est un pari
     directionnel deguise -- et SANS stop, puisqu'on ne peut pas sortir d'un pool vide.

  2. LP sur une paire majeure (SOL/USDC). Le jeton ne va pas a zero ; le resultat est le revenu de
     frais moins la perte divergente. C'est un metier de rendement, pas de prediction.

La perte divergente d'un AMM a produit constant se calcule exactement :
    IL(r) = 2*sqrt(r)/(1+r) - 1,   r = prix_fin / prix_debut

Aucune position, aucun ordre : calcul sur des prix deja sur le disque.
"""
import os
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data_raw")


def il(r):
    return 2 * np.sqrt(r) / (1 + r) - 1


print("=" * 74)
print("CAS 1 — LP SUR UN POOL DE MEMECOIN")
print("=" * 74)
print("""
  Fournir la liquidite d'un pool, c'est detenir le jeton a hauteur de la moitie du depot.
  Distribution mesuree sur 464 lancements suivis (§3.62) :
      issue mediane            x0,17
      finissent sous x0,10     20,5 %
      finissent au-dessus du peage  38 %
""")
for nom, mult in (("mediane", 0.17), ("mauvais cas (1 sur 5)", 0.05), ("bon cas (1 sur 4)", 1.50)):
    perte = il(mult)
    print("  issue %-22s x%-5.2f  perte divergente %+6.1f %%   valeur du depot %+6.1f %%" % (
        nom, mult, 100 * perte, 100 * (np.sqrt(mult) * 2 / (1 + mult) * (1 + mult) / 2 - 1)))
print("""
  Sur l'issue mediane a x0,17, le LP detient a la sortie un panier dont la moitie a perdu 83 %.
  Il encaisse des frais pendant ce temps -- mais il faudrait ~40 % de frais sur le depot pour
  compenser, soit un volume de quarante fois la liquidite en trente minutes. Non atteignable.
  Et sur un pool vide on ne retire rien : le stop n'existe pas pour un LP.

  VERDICT : c'est un pari directionnel long, sans stop, sur une distribution a issue mediane x0,17.
  Strictement pire que ce que fait le carnet aujourd'hui.
""")

print("=" * 74)
print("CAS 2 — LP SUR UNE PAIRE MAJEURE (SOL/USDC)")
print("=" * 74)
px = pd.read_csv(os.path.join(RAW, "broad_daily_close_current.csv"), index_col=0, parse_dates=True)
sol = px["SOLUSDT"].dropna()
print("\n  SOL de %s a %s\n" % (sol.index.min().date(), sol.index.max().date()))
print("  %-14s %10s %12s %12s %12s" % ("fenetre", "variation", "perte div.", "frais 10%APR", "net"))
print("  " + "-" * 64)
for jours in (30, 90, 180, 365):
    rs, ils = [], []
    for i in range(0, len(sol) - jours, 7):
        a, b = sol.iloc[i], sol.iloc[i + jours]
        rs.append(b / a); ils.append(il(b / a))
    if not rs:
        continue
    m_il = np.median(ils)
    for apr in (0.10,):
        frais = apr * jours / 365
        print("  %-14s %9.0f%% %11.2f%% %11.2f%% %11.2f%%" % (
            "%d jours" % jours, 100 * (np.median(rs) - 1), 100 * m_il, 100 * frais, 100 * (m_il + frais)))
print("""
  La perte divergente est mediane : la moitie des fenetres font pire.
  Un LP SOL/USDC a 10 %/an de frais couvre la perte divergente mediane, mais le resultat depend
  entierement du rendement reel du pool, qui varie de 5 a 30 % selon le lieu et la periode.

  VERDICT : ce n'est pas une strategie de prediction, c'est un metier de rendement -- de l'ordre de
  quelques pour cent nets par an, contre le risque de contrat et de depeg. Cela ne repond pas a la
  question posee (battre le marche), mais c'est le seul des trois sieges qui ne perd pas par
  construction.
""")
