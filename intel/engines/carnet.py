"""Quel carnet possede une ligne de `positions` ?

La table `positions` sert quatre carnets, et rien dans son nom ne le dit :

    intel-*    le scanner Robinhood
    t1-*       le carnet T+1 Robinhood
    sol-*      le carnet Solana
    manuel-*   les lignes de l operateur, sur les deux chaines

Cinq incidents en deux jours ont la meme cause : une requete qui cherche « une position sur ce
jeton » sans dire POUR QUEL CARNET, et qui ramasse celle d un autre. Le dernier, le 10/09 a 03h06,
a fait fermer par le scanner la ligne manuelle DOGSHIT de l operateur, sur un pic que le suivi
manuel avait ecrit dans une colonne de prix (§5.24). Les quatre precedents : §5.11, §5.17, §5.18,
§5.21.

Chaque correction avait ete faite site par site. Celle-ci est le site unique : tout code qui
cherche une position d un carnet passe par ici, et une requete sur `positions` qui filtre
`token_address` sans filtrer `model_version` est desormais un defaut a corriger, pas un style.
"""
from __future__ import annotations

SCANNER = "intel-"
T1 = "t1-"
SOLANA = "sol-"
MANUEL = "manuel-"
TOUS = (SCANNER, T1, SOLANA, MANUEL)


def sql(prefixe: str) -> str:
    """Le fragment SQL « cette ligne appartient a ce carnet », a coller apres un AND.

    Une ligne SANS version appartient au scanner -- ce sont les siennes, d avant que les carnets
    soient distingues, et `prefixe_de` le dit deja pour le code Python. La premiere version de ce
    fragment l oubliait et rendait ces lignes invisibles au scanner : il aurait pu racheter un jeton
    qu il detient deja, et une de ses ventes serait partie « quantite inconnue ». Defaut trouve par
    `tests/intel_tests/test_fastlane.py`, qui existait depuis le debut et que je n avais jamais
    lance (§5.26).
    """
    assert prefixe in TOUS, prefixe
    if prefixe == SCANNER:
        return "(model_version IS NULL OR model_version LIKE '" + SCANNER + "%')"
    return "model_version LIKE '" + prefixe + "%'"


SCANNER_SQL = sql(SCANNER)


def prefixe_de(model_version) -> str:
    """Le carnet d une decision ou d une ligne, d apres sa version. Le scanner par defaut : les
    seules lignes sans version sont les siennes, d avant que les carnets soient distingues."""
    mv = str(model_version or "")
    for p in TOUS:
        if mv.startswith(p):
            return p
    return SCANNER


def est_manuel(model_version) -> bool:
    """Cet ordre vient-il de l operateur, et non d un moteur ?

    Les gardes du robot ne sont pas les gardes de l operateur. Deux fois le 10/09 au matin, un
    verrou pose pour arreter un carnet a bloque les ordres tapes a la main sur Telegram :
    `solana.mode: paper`, pose pour arreter le carnet Solana, refusait les achats manuels ; et
    `execution.kill_switch`, pose pour arreter le scanner Robinhood, refusait les achats manuels
    EVM. Un ordre manuel est une decision prise par un humain qui a le graphique sous les yeux ;
    il a ses propres plafonds, sous `manuel:` dans la configuration (§5.25).
    """
    return str(model_version or "").startswith(MANUEL)
