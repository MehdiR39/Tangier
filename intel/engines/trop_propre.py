"""Ecarter les lancements qui ont l'air TROP propres pendant leurs premieres secondes.

MESURE (§3.66, 09/09). La lecture des reserves en chaine (§3.65) a ouvert la zone T+12 s a T+90 s,
que rien n avait jamais observee dans ce projet. Trois signes, tous du genre « ca se passe bien »,
mesures avant T+90 s :

    le prix est au-dessus de son point de depart        (var >= +0,7 %)
    il n a JAMAIS baisse depuis le depart               (creux >= 0)
    la liquidite a grossi                               (liq_var >= +0,35 %)

Taux de VIDAGE du pool selon le nombre de signes reunis, moitie de decouverte / moitie de jugement :

    0-1 signe     4 %  (n=26)     6 %  (n=32)
    2-3 signes   43 %  (n=28)    27 %  (n=22)      base globale 19 %

Coherent des deux cotes, monotone des deux cotes ; sur 5 000 tirages au hasard de meme taille dans
la moitie de jugement, 3,9 % font aussi mal. Et le filtre ne coupe pas les ailes en coupant les
pertes : le groupe propre a MOINS de vidages (5 % contre 38 %) ET PLUS de gros gagnants (44 % contre
32 % atteignent x1,5 ; 20 % contre 10 % atteignent x3).

    esperance    tout        -0,109/euro (n=109)
                 0-1 signe   +0,006/euro
                 2-3 signes  -0,244/euro

MECANISME, qui compte autant que le chiffre. Un pool controle n a pas de pression vendeuse reelle,
donc pas de creux : l absence de degat est le signe qu il n y a personne en face. Un vrai lancement
a un flux a deux sens, donc desordonne. Ce filtre ne predit pas un prix -- il detecte une mise en
scene.

CE QU IL FAUT SAVOIR AVANT DE S EN SERVIR. Le groupe retenu est a +0,006/euro, c est-a-dire ZERO, et
c est de l in-sample : decoupe en deux, le meme filtre donne -0,223 puis +0,189. On ne peut donc pas
affirmer qu il gagne. Ce qu on peut affirmer, et qui suffit a le poser, c est que le groupe ECARTE
est negatif dans les DEUX moities (-0,338 et -0,277 pour trois signes). Ecarter un groupe perdant
des deux cotes ne peut pas coûter plus cher que de continuer a l acheter.

Le verdict viendra de `intel/research/premiere_minute.py --avant`, sur les courbes nees apres la
coupure du 09/09 21h39.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

T_DECISION = 90          # secondes : la fenetre observee avant de decider
SEUIL_VAR = 0.007        # +0,7 % : le prix est au-dessus de son depart
SEUIL_LIQ = 0.0035       # +0,35 % : la liquidite a grossi
MIN_POINTS = 4           # sous ce nombre de releves, on n a pas vu la fenetre : on ne juge pas


def signes(ctx, mint: str) -> tuple[int, dict[str, Any]] | None:
    """Combien de signes « trop beau » ce lancement montre-t-il ? None si on n a pas la donnee.

    Renvoyer None quand la courbe manque est essentiel : un filtre qui ecarte ce qu il n a pas
    mesure ne filtre pas, il echantillonne au hasard. Le collecteur ne couvre que PumpSwap et rate
    les pools qui ne sont pas encore indexes ; ces lancements passent sans jugement, comme avant.
    """
    try:
        pts = ctx.db.query(
            "SELECT age_s, prix_sol, reserve_sol FROM solana_prix_chaine"
            " WHERE mint=? AND age_s<=? AND prix_sol>0 ORDER BY age_s", (mint, T_DECISION))
    except Exception:  # noqa: BLE001
        return None
    if len(pts) < MIN_POINTS:
        return None
    p0 = float(pts[0]["prix_sol"])
    r0 = float(pts[0]["reserve_sol"] or 0)
    if p0 <= 0:
        return None
    mult = [float(x["prix_sol"]) / p0 for x in pts]
    var = mult[-1] - 1.0
    creux = min(mult) - 1.0
    liq_var = (float(pts[-1]["reserve_sol"] or 0) / r0 - 1.0) if r0 > 0 else None

    n = 0
    n += 1 if var >= SEUIL_VAR else 0
    n += 1 if creux >= 0 else 0
    n += 1 if (liq_var is not None and liq_var >= SEUIL_LIQ) else 0
    return n, {"var": var, "creux": creux, "liq_var": liq_var,
               "points": len(pts), "debut_s": int(pts[0]["age_s"])}


def ecarter(ctx, mint: str, symbol: str, seuil: int = 2) -> bool:
    """True si le lancement doit etre ecarte. Silencieux quand la donnee manque."""
    r = signes(ctx, mint)
    if r is None:
        return False
    n, d = r
    if n < seuil:
        return False
    log.info("solana: %s ecarte — %d/3 signes « trop propre » sur %d releves des T+%ds "
             "(prix %+.1f %%, creux %+.1f %%, liquidite %s) : %d %% de ces pools sont vides (§3.66)",
             symbol, n, d["points"], d["debut_s"], 100 * d["var"], 100 * d["creux"],
             ("%+.1f %%" % (100 * d["liq_var"])) if d["liq_var"] is not None else "inconnue",
             43 if n >= 3 else 27)
    return True
