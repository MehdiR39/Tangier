"""SORTIR PLUS TOT PAIE-T-IL ? La seule facon de le savoir sans se mentir.

LA QUESTION, DE MIDO : « ils sortent avant nous ils gagnent, nous on sort apres on perd ? »

POURQUOI ON NE PEUT PAS Y REPONDRE AVEC LES ROBOTS. `qui_gagne.py` a montre que les positions
bouclees en moins de 60 s rapportent (+4 623 SOL, robuste au retrait des 20 meilleures). Mais la
part des positions qui ONT PU etre bouclees s effondre quand on entre tard -- 40,7 % pour une entree
a 1-5 s, **4,9 %** pour une entree a 50-60 s -- et le taux de gagnants monte exactement quand cette
part s effondre (55,6 % -> 79,7 %). **C est la signature d une selection, pas d un avantage** : on
n observe que ceux qui ont REUSSI a vendre vite, c est-a-dire ceux dont le prix est monte tout de
suite. Classer la-dessus, c est classer avec le resultat.

POURQUOI NOS PROPRES TICKETS REPONDENT, EUX. Chez nous la sortie est IMPOSEE par une regle, pas
choisie par un acteur. Sur `prix_rapide` on a un prix CHAQUE SECONDE de 35 a 310 s pour 420 pools :
chaque ticket a donc un prix a 60, 90, 120, 180 et 240 s. **Aucun ticket ne peut manquer a l appel a
une heure et pas a une autre** -- la selection qui ruine la mesure precedente est structurellement
impossible ici.

CE QUI EST TENU CONSTANT, et c est tout l interet : les MEMES tickets, la MEME entree a 47 s, le
MEME cout. Un aller-retour coute pareil qu on sorte a 60 ou a 240 s -- un achat, une vente -- donc
la comparaison ne depend pas du cout. Seule l heure de sortie change.

CONVENTION D EXECUTABILITE, appliquee sans exception (regle 7 de la discipline) : on entre au
DERNIER prix lisible a 47 s ou avant, on sort au PREMIER prix lisible a l heure visee ou apres.
Jamais le prix de l instant vise s il n a pas ete observe.
"""
from __future__ import annotations

import os
import sqlite3
import statistics as st

PRIX = os.environ.get("PRIX_DB", "/app/db/prix_rapide.sqlite")
COMBO = os.environ.get("COMBO_DB", "/app/db/papier_combo.sqlite")
ENTREE = 47                    # l instant ou le moteur achete reellement
SORTIES = (60, 75, 90, 120, 150, 180, 210, 240, 270)
COUT = 0.0262                  # identique pour toutes les sorties : un aller-retour
SEUIL = 0.2694                 # le seuil de la regle en production


def net(r: float) -> float:
    """Multiplicatif. En additif le cout cree un motif monotone entierement faux (regle 3)."""
    return (1.0 + r) * (1.0 - COUT) - 1.0


def decris(nom: str, v: list[float]) -> None:
    if len(v) < 5:
        print("   %-12s n=%4d  trop peu" % (nom, len(v)))
        return
    s = sorted(v)
    h = len(v) // 2
    print("   %-12s n=%4d  moy %+7.2f %%  med %+7.2f %%  sans 3 meil. %+7.2f %%  gagnants %4.1f %%"
          % (nom, len(v), 100 * st.mean(v), 100 * st.median(v), 100 * st.mean(s[:-3]),
             100 * sum(1 for x in v if x > 0) / len(v)))


def main() -> None:
    c = sqlite3.connect("file:%s?mode=ro" % PRIX, uri=True)
    series: dict[str, list[tuple[float, float]]] = {}
    for pair, age, p in c.execute(
            "SELECT pair, age_s, prix_sol FROM prix WHERE prix_sol > 0 ORDER BY pair, age_s"):
        series.setdefault(pair, []).append((float(age), float(p)))

    # les tickets que la regle en PRODUCTION retient, pour repondre sur NOTRE carnet et pas sur
    # un flux quelconque ; le temoin (tous les pools) est affiche a cote.
    retenus = set()
    try:
        d = sqlite3.connect("file:%s?mode=ro" % COMBO, uri=True)
        retenus = {p for (p,) in d.execute(
            "SELECT pair FROM decision WHERE risque IS NOT NULL AND risque <= ?", (SEUIL,))}
    except Exception as exc:  # noqa: BLE001
        print("(regle de production illisible : %s)" % str(exc)[:60])

    # un ticket n est garde que s il a un prix AUX DEUX BOUTS de TOUTES les sorties testees :
    # comparer des sorties sur des populations differentes serait exactement le biais qu on fuit.
    tickets: dict[str, dict[int, float]] = {}
    for pair, pts in series.items():
        avant = [p for a, p in pts if a <= ENTREE]
        if not avant:
            continue
        p0 = avant[-1]
        sorties = {}
        for s in SORTIES:
            apres = [p for a, p in pts if a >= s]
            if apres:
                sorties[s] = apres[0]
        if len(sorties) == len(SORTIES):
            tickets[pair] = {s: net(sorties[s] / p0 - 1.0) for s in SORTIES}

    print("%d pools ont un prix a 47 s ET a chacune des %d sorties testees"
          % (len(tickets), len(SORTIES)))
    print("Cout applique : %.2f pts, IDENTIQUE pour toutes les sorties (un aller-retour)" % (100 * COUT))

    for nom, sel in (("TOUS LES POOLS (temoin)", set(tickets)),
                     ("LES TICKETS QUE LA REGLE RETIENT (risque <= %.4f)" % SEUIL,
                      set(tickets) & retenus)):
        if len(sel) < 20:
            print("\n%s : %d tickets, trop peu pour conclure" % (nom, len(sel)))
            continue
        print()
        print("%s -- %d tickets" % (nom, len(sel)))
        ordre = sorted(sel)
        for s in SORTIES:
            v = [tickets[p][s] for p in ordre]
            decris("sortie %3d s" % s, v)

        # moities chronologiques : un ecart qui change de signe entre les deux ne vaut rien
        print("   -- par moitie chronologique (moyenne) --")
        h = len(ordre) // 2
        print("   %-12s %12s %12s" % ("", "1re moitie", "2e moitie"))
        for s in SORTIES:
            a = st.mean([tickets[p][s] for p in ordre[:h]])
            b = st.mean([tickets[p][s] for p in ordre[h:]])
            print("   sortie %3d s %11.2f %% %11.2f %%" % (s, 100 * a, 100 * b))


if __name__ == "__main__":
    main()
