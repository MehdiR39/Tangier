"""LES VARIABLES DE FLUX D ORDRES, calculees UNE SEULE FOIS ET AU MEME ENDROIT.

MIDO, 20/09 : « comment ca c est le CODE, a quoi tu sers ? ». Il avait raison. J avais presente le
risque de divergence entre la recherche et le moteur comme une reserve a verifier plus tard ; c est
un risque qu on SUPPRIME, pas qu on surveille.

POURQUOI CE MODULE EXISTE. La foret 75s s appuie a 71 % sur le flux d ordres. Ces variables sont
calculees aujourd hui dans `tout_table.transactions()`, sur les fichiers de `v1_enregistreur`. Pour
brancher le modele, le MOTEUR doit les calculer aussi, en direct a 75 s. Les ecrire deux fois, c est
garantir qu elles finiront par differer d un filtre d age, d un signe ou d un arrondi -- et le
modele recevrait alors des valeurs portant le bon nom sans vouloir dire la meme chose. Ce projet a
deja eu un bug de SIGNE achat/vente dans `features.py`, et un modele qui depensait 12 % de ses
branchements sur trois variables 100 % vides a l execution (regle 10).

Donc : une fonction, deux appelants. `tout_table` l appelle en rejouant l historique (avec `vus`,
l historique des portefeuilles, pour les variables de robots) ; le moteur l appelle sans (`vus=None`)
et recevra `None` pour `v1_robots` et `v1_part_robots` -- mesure le 20/09 : les abandonner coute
-0,065 EUR/ticket sur 2 675 tickets, sous le bruit.

AUCUNE LOGIQUE NOUVELLE ICI. C est le corps de `tout_table.transactions()`, deplace tel quel.
"""
from __future__ import annotations

import statistics as st
from collections import defaultdict

RECURRENT = 5                      # un portefeuille vu dans >= 5 pools ANTERIEURS est un « robot »


def traits(tx: list, age_max: int, vus: dict | None = None, pair: str | None = None) -> dict:
    """Les 15 variables de flux d un pool, a partir de ses transactions brutes.

    `tx`      la liste enregistree par `v1_enregistreur` : [age, version, parts, coffre_sol,
              coffre_jetons, n_signataires, payeur], ou `parts` = [[proprietaire, d_jetons, d_SOL]].
    `age_max` l age au-dela duquel on ignore une transaction. **C est l instant de decision** : 45
              pour la foret a 45 s, 60 pour celle a 75 s. Une transaction plus recente serait de la
              lecture d avenir.
    `vus`     portefeuille -> ensemble des pools ou il a deja ete vu AVANT celui-ci. Absent chez le
              moteur, qui n a pas cet etat global : `v1_robots` et `v1_part_robots` valent alors
              None, et le modele leur substituera sa mediane d apprentissage.
    """
    achats: list[float] = []
    ventes: list[float] = []
    acheteurs: set[str] = set()
    vendeurs: set[str] = set()
    premier = None
    robots, sol_robots = 0, 0.0
    sol_par_wallet: defaultdict[str, float] = defaultdict(float)
    jet_par_wallet: defaultdict[str, float] = defaultdict(float)

    for t in tx or []:
        try:
            age, parts = int(t[0]), t[2]
        except Exception:  # noqa: BLE001
            continue
        if age > age_max:
            continue
        for p in parts or []:
            try:
                q, dj, ds = str(p[0]), float(p[1]), float(p[2])
            except Exception:  # noqa: BLE001
                continue
            sol_par_wallet[q] += ds
            jet_par_wallet[q] += dj
            if dj > 0 and ds < 0:
                achats.append(-ds)
                acheteurs.add(q)
                if premier is None:
                    premier = age
                if vus is not None and len(vus[q]) >= RECURRENT:   # recurrent AVANT ce jeton
                    robots += 1
                    sol_robots += -ds
            elif dj < 0 and ds > 0:
                ventes.append(ds)
                vendeurs.add(q)

    sans_achat = [v for q, v in sol_par_wallet.items() if v > 0 and q not in acheteurs]
    sa, sv = sum(achats), sum(ventes)
    gini = None
    if len(achats) >= 2:
        a = sorted(achats)
        n = len(a)
        gini = (2 * sum((i + 1) * x for i, x in enumerate(a)) / (n * sum(a)) - (n + 1) / n) \
            if sum(a) > 0 else None
    if vus is not None and pair is not None:
        for q in acheteurs:
            vus[q].add(pair)

    return {
        "v1_n_achats": len(achats), "v1_n_ventes": len(ventes),
        "v1_acheteurs": len(acheteurs), "v1_vendeurs": len(vendeurs),
        "v1_sol_achats": sa, "v1_sol_ventes": sv,
        "v1_ratio_ventes": (sv / sa) if sa > 0 else None,
        "v1_premier_achat": premier,
        "v1_achat_median": st.median(achats) if achats else None,
        "v1_achat_max": max(achats) if achats else None,
        "v1_gini_achats": gini,
        # sans historique des portefeuilles, ces deux-la ne sont pas calculables : None, pas zero.
        # Zero serait un MENSONGE -- « aucun robot » au lieu de « je ne sais pas » -- et le modele
        # le prendrait pour une information.
        "v1_robots": robots if vus is not None else None,
        "v1_part_robots": ((sol_robots / sa) if sa > 0 else None) if vus is not None else None,
        "v1_vendeurs_sans_achat": len(sans_achat),
        "v1_sol_sans_achat": sum(sans_achat),
        "v1_part_sans_achat": (sum(sans_achat) / sv) if sv > 0 else None,
    }
