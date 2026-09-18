"""`sac1` MELANGE DEUX ETATS OPPOSES : ce que ca fait au verdict d `expert_detenteurs`.

CE QU ON A DECOUVERT. `social_collecte` enregistre `sac1`, la part du plus gros compte-jeton, sans
exclure le coffre du pool. Diagnostic sur 200 lignes, en resolvant le proprietaire de chaque compte
et en le comparant a l adresse du pool :

    le plus gros detenteur etait le COFFRE       56 %   sac1 median 20,3 %
    le plus gros detenteur etait un PORTEFEUILLE 44 %   sac1 median 78,6 %

Ce ne sont pas des mesures bruitees autour d une meme grandeur : ce sont DEUX VARIABLES EMPILEES,
et elles decrivent les situations les plus opposees qui soient. Coffre = l offre est enfermee dans
le pool, personne ne peut la deverser. Portefeuille a 78,6 % = un seul acteur tient de quoi vider le
pool plusieurs fois.

LA QUESTION. `expert_detenteurs` (§3.110) fait -169 EUR sur 269 tickets et a ferme la piste de la
concentration. Mais il jugeait `sac1`. **Un verdict negatif sur une variable contaminee ne condamne
pas la grandeur qu elle pretendait mesurer** -- il condamne la mesure. Est-ce que separer les deux
populations fait apparaitre ce que leur melange effacait ?

LE CRITERE, ECRIT AVANT DE REGARDER LE RESULTAT. Un ecart ne compte que s il passe les QUATRE :

 1. il survit au retrait des 3 MEILLEURS tickets (c est ce controle, pas le p, qui a demasque
    toutes les fausses pistes du projet) ;
 2. il a le meme SIGNE sur les deux moities chronologiques ;
 3. il bat un tirage ALEATOIRE de meme taille -- une regle qui garde peu de tickets doit battre le
    hasard, pas la moyenne generale ;
 4. il reste apres le cout mesure de 2,62 points.

Et le resultat se lit sur la MEDIANE autant que sur la moyenne : sur des queues epaisses la moyenne
est le pire estimateur (regle 5).

LE VERDICT, ET IL N EST PAS CELUI QU ON CHERCHAIT. La contamination est REELLE et demontree : sur
571 jetons, 209 fois le coffre, 106 fois un vrai portefeuille, 256 non classables. Mais l ecart de
rendement entre les deux groupes -- -9,94 % contre -2,77 % -- **ne peut pas etre cru**, et la raison
est plus grave qu un simple manque de donnees.

Pour classer un jeton d hier, il faut resoudre le proprietaire de son compte-jeton AUJOURD HUI. Or
un compte ferme ne se relit plus, et 256 le sont -- verifie un par un, ce ne sont pas des echecs
d appel groupe. **« Le compte est-il encore lisible ? » est donc une information du FUTUR par
rapport a l instant de la decision a 45 s.** Et elle n est pas anodine : le groupe non classable a
une mediane de +13,98 % contre -2,60 % pour les classables, seize points d ecart.

Classer sur cette base, c est trier avec le resultat -- la meme famille d erreur que le `sort()` sur
`(predicteur, resultat)` qui avait produit un faux Q3 a +30,64 % (regle 2).

**CONSEQUENCE : l histoire ne peut pas repondre, seule une collecte EN AVANT le peut.** C est
exactement ce que fait `stock_collecte.py`, qui resout le proprietaire A 15-45 s, quand le compte
existe forcement. Ce script-ci ne sert donc qu a une chose, mais elle compte : montrer que le
verdict -169 EUR d `expert_detenteurs` portait sur une variable qui empilait deux etats opposes, et
qu il ne ferme donc PAS la question de la concentration.
"""
from __future__ import annotations

import base64
import os
import random
import sqlite3
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import base58  # noqa: E402
import copie_collecte as cc  # noqa: E402

SOCIAL = os.environ.get("SOCIAL_DB", "/app/db/papier_social.sqlite")
COMBO = os.environ.get("COMBO_DB", "/app/db/papier_combo.sqlite")
COUT = 0.0262                  # le cout d execution MESURE sur 244 tickets reels
LOT = 40                       # comptes par appel getMultipleAccounts
TIRAGES = 2000


def proprietaires(comptes: list[str]) -> dict[str, str | None]:
    """L adresse du portefeuille derriere chaque compte-jeton (octets 32-64 d un compte SPL)."""
    out: dict[str, str | None] = {}
    for i in range(0, len(comptes), LOT):
        lot = comptes[i:i + LOT]
        r = cc.rpc({"jsonrpc": "2.0", "id": 1, "method": "getMultipleAccounts",
                    "params": [lot, {"encoding": "base64"}]})
        vals = ((r or {}).get("value") or [None] * len(lot))
        for ta, info in zip(lot, vals):
            try:
                out[ta] = base58.b58encode(base64.b64decode(info["data"][0])[32:64]).decode()
            except Exception:  # noqa: BLE001
                out[ta] = None            # compte ferme ou illisible : on ne devine pas
    return out


def apres_cout(r: float) -> float:
    """Le cout est MULTIPLICATIF. En additif il cree un motif monotone entierement faux (regle 3)."""
    return (1.0 + r) * (1.0 - COUT) - 1.0


def decris(nom: str, rs: list[float]) -> None:
    if not rs:
        print("  %-28s aucun ticket" % nom)
        return
    net = [apres_cout(x) for x in rs]
    sans3 = sorted(net)[:-3] if len(net) > 3 else []
    print("  %-28s n=%3d   moy %+7.2f %%   med %+7.2f %%   sans 3 meilleurs %+7.2f %%"
          % (nom, len(net), 100 * st.mean(net), 100 * st.median(net),
             100 * st.mean(sans3) if sans3 else float("nan")))


def main() -> None:
    s = sqlite3.connect("file:%s?mode=ro" % SOCIAL, uri=True)
    c = sqlite3.connect("file:%s?mode=ro" % COMBO, uri=True)
    res = {p: r for p, r in c.execute("SELECT pair, r FROM ref WHERE r IS NOT NULL")}
    rows = [x for x in s.execute(
        "SELECT pair, mint, sac_wallet, sac1, n_sacs5, t_vu FROM jeton"
        " WHERE erreur IS NULL AND sac_wallet IS NOT NULL ORDER BY t_vu")
        if x[0] in res]
    print("%d jetons ont A LA FOIS une mesure de detenteurs et un resultat" % len(rows))
    if not rows:
        return

    prop = proprietaires([x[2] for x in rows])
    coffre, portef, illisible = [], [], []
    for pair, mint, ta, sac1, n5, t in rows:
        p = prop.get(ta)
        if p is None:
            illisible.append((t, sac1, res[pair]))
        elif p == pair:
            coffre.append((t, sac1, res[pair]))
        else:
            portef.append((t, sac1, res[pair]))
    print("  coffre du pool : %d · vrai portefeuille : %d · compte illisible (ferme ?) : %d"
          % (len(coffre), len(portef), len(illisible)))
    print()

    print("RENDEMENT APRES COUT, SELON CE QU ETAIT LE PLUS GROS DETENTEUR")
    decris("le COFFRE du pool", [r for _, _, r in coffre])
    decris("un VRAI portefeuille", [r for _, _, r in portef])
    tout = [r for _, _, r in coffre] + [r for _, _, r in portef]
    decris("tous (ce que voyait sac1)", tout)
    print()

    # LE GROUPE QUI DECIDE SI TOUT LE RESTE VAUT QUELQUE CHOSE. Un compte-jeton illisible est un
    # compte FERME. Un coffre se ferme quand la liquidite est retiree -- un rug. Un portefeuille se
    # ferme quand son detenteur a tout vendu. Les deux se ferment, donc ces jetons ne sont PAS
    # manquants au hasard : si leur rendement differe des autres, classer sur un compte encore
    # lisible est une selection par la SURVIE, et tout ecart mesure plus haut peut n etre que ca.
    print("LE GROUPE ECARTE -- c est lui qui decide si le reste veut dire quelque chose")
    decris("compte FERME (non classable)", [r for _, _, r in illisible])
    decris("compte encore lisible", tout)
    print()

    # Les memes quatre criteres, appliques a l ecart PRINCIPAL et pas seulement au sous-decoupage.
    print("L ECART COFFRE / PORTEFEUILLE passe-t-il les criteres ?")
    for nom, grp in (("coffre", coffre), ("portefeuille", portef)):
        g = sorted(grp)
        h = len(g) // 2
        a = st.mean([apres_cout(r) for _, _, r in g[:h]])
        b = st.mean([apres_cout(r) for _, _, r in g[h:]])
        print("  %-13s 1re moitie %+6.2f %%   2e moitie %+6.2f %%   %s"
              % (nom, 100 * a, 100 * b,
                 "meme signe" if (a > 0) == (b > 0) else "SIGNE OPPOSE -> instable"))
    base = [apres_cout(r) for _, _, r in coffre] + [apres_cout(r) for _, _, r in portef]
    vrai = st.mean([apres_cout(r) for _, _, r in portef])
    k, mieux = len(portef), 0
    for _ in range(TIRAGES):
        if st.mean(random.sample(base, k)) <= vrai:
            mieux += 1
    print("  un tirage AU HASARD de %d tickets fait moins bien dans %.1f %% des cas"
          % (k, 100 * mieux / TIRAGES))
    print()

    # Le portefeuille lourd : la moitie la plus concentree des cas NON-coffre. C est la seule
    # formulation testee, decidee avant de voir les rendements, pour ne pas balayer des seuils.
    if len(portef) >= 20:
        med = st.median([x[1] for x in portef])
        lourd = [x for x in portef if x[1] >= med]
        leger = [x for x in portef if x[1] < med]
        print("PARMI LES VRAIS PORTEFEUILLES, coupes a leur mediane (sac1 = %.1f %%)" % (100 * med))
        decris("stock LOURD (>= mediane)", [r for _, _, r in lourd])
        decris("stock LEGER (< mediane)", [r for _, _, r in leger])
        print()

        # 2. meme signe sur les deux moities chronologiques
        for nom, grp in (("LOURD", lourd), ("LEGER", leger)):
            g = sorted(grp)
            h = len(g) // 2
            a = st.mean([apres_cout(r) for _, _, r in g[:h]]) if h else float("nan")
            b = st.mean([apres_cout(r) for _, _, r in g[h:]]) if h else float("nan")
            print("  %s : 1re moitie %+6.2f %%   2e moitie %+6.2f %%   %s"
                  % (nom, 100 * a, 100 * b,
                     "meme signe" if (a > 0) == (b > 0) else "SIGNE OPPOSE -> instable"))
        print()

        # 3. le tirage aleatoire de meme taille : la regle bat-elle le hasard, pas la moyenne ?
        base = [apres_cout(r) for _, _, r in portef]
        vrai = st.mean([apres_cout(r) for _, _, r in lourd])
        k, mieux = len(lourd), 0
        for _ in range(TIRAGES):
            if st.mean(random.sample(base, k)) <= vrai:
                mieux += 1
        print("  un tirage AU HASARD de %d tickets fait moins bien dans %.1f %% des cas"
              % (k, 100 * mieux / TIRAGES))
        print("  (il faut ~95 %% pour que l ecart ne soit pas du hasard ; ~50 %% = aucun signal)")


if __name__ == "__main__":
    main()
