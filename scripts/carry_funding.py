#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Le portage de funding : encaisser au lieu de parier.

Les trois familles testees jusqu ici -- lancements memecoin, selection on-chain, fourniture de
liquidite sur pool toxique -- consistent toutes a DEVINER. Elles echouent toutes, ce qui est
coherent : deviner mieux que le marche est le metier le plus dur qui existe.

Le portage de funding ne devine rien. Sur un perpetuel, quand le taux est positif, les acheteurs a
effet de levier PAIENT les vendeurs, mecaniquement, toutes les huit heures. Etre long au comptant et
short le perpetuel annule le risque de prix et encaisse ce taux. On ne parie pas sur une direction :
on facture un service a des gens presses.

C est la categorie ou l argent se gagne reellement en crypto -- les teneurs de marche, ceux qui
encaissent au lieu de parier.

CE QUE CE FICHIER MESURE, et ce qu il ne mesure pas :
  - il mesure le taux encaisse, sa stabilite, ses pires periodes, et ce qu il reste apres des couts
    realistes ;
  - il NE mesure PAS le risque d execution (liquidation du short si la base diverge, defaillance de
    plateforme, retrait de cotation). Ce sont des risques reels que des chiffres historiques ne
    montrent pas, et il faut le dire avant de conclure quoi que ce soit.

Aucune position, aucun ordre : lecture d un fichier deja sur le disque.
"""
import os
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data_onchain")


def main() -> None:
    d = pd.read_csv(os.path.join(OUT, "funding_rates.csv"), parse_dates=["date"])
    d = d.dropna(subset=["funding_rate"])
    print("  %d lignes · %d actifs · %s -> %s\n" % (
        len(d), d.coin.nunique(), d.date.min().date(), d.date.max().date()))

    # Le pas : une ligne par jour et par actif. Un taux de 0,0001 par periode de 8 h donne
    # 3 x 0,01 % par jour ; si la ligne est deja journaliere, c est 0,01 %. On teste les deux
    # lectures et on retient celle qui colle aux ordres de grandeur connus du marche.
    med = d.funding_rate.abs().median()
    print("  taux median absolu par ligne : %.6f  (%.4f %%)" % (med, 100 * med))
    print("  si la ligne est journaliere  : %.1f %% par an" % (100 * med * 365))
    print("  si la ligne est par 8 h      : %.1f %% par an" % (100 * med * 3 * 365))
    print()

    par_jour = d.groupby(["date", "coin"]).funding_rate.mean().unstack()
    print("  %-8s %8s %10s %9s %9s %9s" % ("actif", "jours", "moy/an", "pos %", "pire mois", "meilleur"))
    print("  " + "-" * 60)
    lignes = []
    for c in sorted(par_jour.columns):
        s = par_jour[c].dropna()
        if len(s) < 365:
            continue
        an = 100 * s.mean() * 365
        pos = 100 * (s > 0).mean()
        m = s.resample("ME").sum() * 100
        lignes.append((c, len(s), an, pos, m.min(), m.max()))
        print("  %-8s %8d %9.1f %% %8.0f %% %8.2f %% %8.2f %%" % (c, len(s), an, pos, m.min(), m.max()))

    if not lignes:
        print("  pas assez d historique par actif.")
        return

    # Le panier : moyenne des actifs disponibles chaque jour, comme le ferait un portage diversifie.
    panier = par_jour.mean(axis=1).dropna()
    print("\n  PANIER EQUIPONDERE (%d jours, %s -> %s)" % (
        len(panier), panier.index.min().date(), panier.index.max().date()))
    for cout, nom in ((0.0, "brut"), (0.02, "2 %/an de frais"), (0.05, "5 %/an de frais"),
                      (0.10, "10 %/an (frais + emprunt cher)")):
        net = panier.mean() * 365 - cout
        print("    %-32s %+6.2f %% par an" % (nom, 100 * net))
    print()
    m = panier.resample("ME").sum() * 100
    print("    mois positifs        : %.0f %% (%d/%d)" % (100 * (m > 0).mean(), (m > 0).sum(), len(m)))
    print("    pire mois            : %+.2f %%   (%s)" % (m.min(), m.idxmin().date()))
    print("    pire annee           : %+.2f %%" % (panier.resample("YE").sum() * 100).min())
    a = panier.resample("YE").sum() * 100
    for an, v in a.items():
        print("      %d : %+6.2f %%" % (an.year, v))


if __name__ == "__main__":
    main()
