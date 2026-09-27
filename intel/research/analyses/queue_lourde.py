"""ATTRAPE-T-ELLE LES GROS COUPS PLUS SOUVENT QUE LE HASARD ? Le bon test sur un marche a queue lourde.

MIDO, 21/09 : « sur des memecoins tu t attends a quoi, que ta selection fasse 100 % ? Depuis hier tu
dis que c est les 3 meilleurs qui portent -- mais c est un gros P&L, non ? »

IL A RAISON, ET C EST UN DEFAUT DE MA METHODE. Sur ce marche **5 % des jetons portent 315 % du
rendement total** (§3.156) : sans eux la moyenne tombe a -6,08 %. Donc TOUTE strategie qui gagne
aura son P&L concentre sur quelques tickets. Exiger « positive sans ses 3 meilleurs », c est exiger
qu elle gagne SANS le mecanisme qui fait gagner -- un critere qui elimine par construction ce qu on
cherche. Je l ai applique toute la journee du 20/09, et il a sorti `BANDE + PAUSE` des candidates.

LE BON TEST, et il repond a la vraie question. Une strategie chanceuse attrape autant de gros coups
qu un tirage au sort de la meme taille ; une bonne strategie en attrape PLUS. On compare donc, a
nombre de tickets EGAL et sur le meme vivier :
    le taux de gros gains qu elle attrape    contre celui d un tirage au hasard
    l argent qu elle en tire                 contre celui d un tirage au hasard
« Gros gain » n est pas un seuil invente : c est le seuil au-dela duquel un ticket paie plusieurs
tickets perdants -- on le prend au 90e centile du vivier, et on verifie que la conclusion ne change
pas au 95e ni au 80e.

CE QUE CE TEST NE FAIT PAS. Il ne dit pas si la strategie rapporte plus qu en prendre plus : garder
18 tickets sur 161 peut donner un meilleur EUR/ticket et beaucoup moins d euros. Cette question-la
est repondue a cote, par `EUR/jour`, et les deux se lisent ensemble.

Papier, lecture seule.
"""
from __future__ import annotations

import os
import sqlite3
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

COUT, MISE, V = 0.0367, 25.0, 17.5845
TIRAGES = int(os.environ.get("TIRAGES", "5000"))
CENTILES = (0.80, 0.90, 0.95)


def cout(q):
    return COUT + 2 * (MISE * 0.31 / 30.0) / ((q or 0) + V)


def vivier():
    """Le vivier et la selection de BANDE + PAUSE, depuis le gel de la regle."""
    from papier_combo import BANDE, GEL_BP, TENUE_S, appliquer_pause
    c = sqlite3.connect("file:/app/db/papier_combo.sqlite?mode=ro", uri=True, timeout=30)
    bp = []
    for pair, t, risque, q, b in c.execute(
            "SELECT d.pair, d.t_dec, d.risque, d.q, i.brut_240 FROM decision d JOIN issue i"
            " ON i.pair=d.pair WHERE d.eligible=1 AND i.brut_240 IS NOT NULL AND d.q IS NOT NULL"
            " ORDER BY d.t_dec"):
        if BANDE[0] <= risque < BANDE[1] and float(t) >= GEL_BP:
            bp.append({"pair": pair, "t": float(t), "fin": float(t) + TENUE_S,
                       "r": min(float(b) - cout(q), 3.0)})
    pris = {x["pair"] for x in appliquer_pause(bp)}
    tous = np.array([MISE * x["r"] for x in bp])
    sel = np.array([MISE * x["r"] for x in bp if x["pair"] in pris])
    return tous, sel


def main() -> None:
    tous, sel = vivier()
    n, k = len(tous), len(sel)
    if k < 10 or k >= n:
        print("queue_lourde: %d retenus sur %d, rien a comparer" % (k, n))
        return
    rng = np.random.default_rng(21)
    print("vivier %d tickets · la regle en garde %d (%.0f %%)" % (n, k, 100 * k / n))
    print("   elle rapporte %+.2f EUR (%+0.3f/ticket) · tout prendre rapporte %+.2f (%+0.3f/ticket)"
          % (sel.sum(), sel.mean(), tous.sum(), tous.mean()))
    print()
    print("   %-22s %12s %14s %10s" % ("« gros gain » =", "elle en a", "le hasard en a", "p"))
    for c_ in CENTILES:
        seuil = float(np.quantile(tous, c_))
        vrai = int((sel >= seuil).sum())
        ech = np.array([int((rng.choice(tous, k, replace=False) >= seuil).sum())
                        for _ in range(TIRAGES)])
        p = (int((ech >= vrai).sum()) + 1) / (TIRAGES + 1)
        print("   %-22s %12s %14s %10.3f"
              % ("au-dela de %+.1f EUR (c%d)" % (seuil, 100 * c_),
                 "%d" % vrai, "%.1f en moyenne" % ech.mean(), p))
    print()
    # et l argent, pas seulement le comptage : attraper 3 gros coups mediocres n est pas la meme
    # chose qu en attraper 3 enormes.
    ech = np.array([rng.choice(tous, k, replace=False).sum() for _ in range(TIRAGES)])
    p = (int((ech >= sel.sum()).sum()) + 1) / (TIRAGES + 1)
    print("   EN ARGENT : elle fait %+.2f EUR · le hasard fait %+.2f en mediane (5e-95e %+.0f / %+.0f)"
          % (sel.sum(), float(np.median(ech)), float(np.quantile(ech, .05)),
             float(np.quantile(ech, .95))))
    print("   -> %d tirages sur %d font aussi bien (p ~ %.3f)"
          % (int((ech >= sel.sum()).sum()), TIRAGES, p))
    print()
    print("   Rappel : ce test dit si elle SELECTIONNE mieux que le hasard, pas si elle rapporte")
    print("   plus que de prendre davantage de tickets. Les deux se lisent ensemble.")


if __name__ == "__main__":
    main()
