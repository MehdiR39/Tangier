"""LA PAUSE FAIT-ELLE MIEUX QUE LE HASARD, AVEC LES DONNEES D AUJOURD HUI ?

MIDO, 20/09 : « il me semble que tu m avais dit un jour que la pause ne sert a rien et degrade.
Peu importe : teste et note. »

IL SE SOUVENAIT BIEN. §3.111 (18/09) : « spectaculaire, et indistinguable du hasard » -- p = 0,066
sur RISQUE, 0,070 sur la BANDE, et sans ses trois meilleurs tickets la pause tombait a -18 EUR.
Mais c etait sur **14 tickets** pour la bande. Elle en a 86 aujourd hui, et elle survit desormais a
la perte de ses trois meilleurs (+0,80 EUR/ticket). La question se repose donc, et il faut la
reposer avec un test PLUS DUR que celui d alors.

POURQUOI LE TEST DE §3.111 NE SUFFIT PAS. Il tirait des sous-ensembles AU HASARD de la meme taille.
Or la pause ne choisit pas au hasard : elle choisit des PLAGES DE TEMPS (tout ce qui n est pas dans
les 30 min suivant une chute). Un tirage sans structure temporelle est donc un adversaire trop
faible -- il ne sait pas imiter « prendre des paquets d heures consecutives ».

LE TEST D ICI, deux barres au lieu d une :
  A. sous-ensembles au hasard de meme taille  -- comparable a §3.111, gardee pour continuite ;
  B. **DECALAGE CIRCULAIRE DU TEMPS** : on garde la forme exacte des plages de pause, mais on les
     fait glisser de d heures dans le temps. La selection garde sa structure (memes durees, meme
     nombre de plages) et perd seulement son lien avec les VRAIES chutes. Si la pause vaut quelque
     chose, c est parce qu elle reagit aux chutes -- pas parce qu elle prend des paquets d heures.
     C est la barre qui compte.

Papier, zero euro, lecture seule.
"""
from __future__ import annotations

import os
import sqlite3
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

COUT = float(os.environ.get("COUT_MESURE", "0.0367"))
MISE = 25.0
V = 17.5845
TIRAGES = int(os.environ.get("TIRAGES", "2000"))


def charger():
    from papier_combo import BANDE, GEL_BP
    c = sqlite3.connect("file:/app/db/papier_combo.sqlite?mode=ro", uri=True, timeout=30)
    L = []
    for t, risque, q, b in c.execute(
            "SELECT d.t_dec, d.risque, d.q, i.brut_240 FROM decision d JOIN issue i"
            " ON i.pair=d.pair WHERE d.eligible=1 AND i.brut_240 IS NOT NULL"
            " AND d.risque IS NOT NULL AND d.q IS NOT NULL ORDER BY d.t_dec"):
        if not (BANDE[0] <= float(risque) < BANDE[1]) or float(t) < GEL_BP:
            continue
        cout = COUT + 2 * (MISE * 0.31 / 30.0) / (float(q) + V)
        L.append((float(t), MISE * min(float(b) - cout, 3.0)))
    return L


def plages(L, seuil=-0.30, duree=1800.0):
    """Les instants ou la pause est DECLENCHEE : cloture d un ticket sous le seuil.

    La cloture arrive 242 s apres la decision -- une pause declenchee par un ticket qu on ne sait
    pas encore perdant serait de la lecture d avenir.
    """
    return [t + 242.0 for t, r in L if r / MISE <= seuil]


def applique(L, decl, duree=1800.0):
    d = np.asarray(sorted(decl))
    out = []
    for t, r in L:
        if len(d):
            i = np.searchsorted(d, t) - 1
            if i >= 0 and t - d[i] < duree:
                continue                      # en pause
        out.append(r)
    return out


def dit(nom, v):
    if not v:
        print("   %-30s vide" % nom)
        return
    s = sorted(v)
    print("   %-30s %4d tickets · %+7.3f EUR/ticket · %+8.1f EUR · sans 3 %+7.3f"
          % (nom, len(v), sum(v) / len(v), sum(v),
             sum(s[:-3]) / (len(s) - 3) if len(s) > 3 else float("nan")))


def main() -> None:
    L = charger()
    if len(L) < 100:
        print("pause_verdict: %d tickets dans la bande depuis le gel, trop peu" % len(L))
        return
    tous = [r for _, r in L]
    decl = plages(L)
    pris = applique(L, decl)
    k = len(pris)
    duree = (L[-1][0] - L[0][0]) / 3600.0
    print("BANDE depuis le gel de BANDE+PAUSE : %d tickets sur %.1f h · %d declenchements de pause"
          % (len(L), duree, len(decl)))
    dit("la BANDE seule", tous)
    dit("la BANDE avec PAUSE", pris)
    if not k or k == len(L):
        return
    reel = sum(pris) / k
    rng = np.random.default_rng(30)

    print()
    print("BARRE A — sous-ensembles au hasard de meme taille (le test de §3.111)")
    ech = [float(np.mean(rng.choice(tous, k, replace=False))) for _ in range(TIRAGES)]
    ka = sum(1 for x in ech if x >= reel)
    print("   mediane du hasard %+0.3f · 5e-95e centile %+0.3f / %+0.3f"
          % (np.median(ech), np.quantile(ech, 0.05), np.quantile(ech, 0.95)))
    print("   -> %d tirages sur %d font aussi bien (p ~ %.3f)" % (ka, TIRAGES, (ka + 1) / (TIRAGES + 1)))

    print()
    print("BARRE B — MEMES plages de pause, DECALEES dans le temps (la barre qui compte)")
    t0, t1 = L[0][0], L[-1][0]
    span = t1 - t0
    ech2, tailles = [], []
    for _ in range(TIRAGES):
        d = rng.uniform(0, span)
        dec2 = [t0 + ((x - t0 + d) % span) for x in decl]    # decalage circulaire
        v = applique(L, dec2)
        if len(v) >= 10:
            ech2.append(sum(v) / len(v))
            tailles.append(len(v))
    if ech2:
        kb = sum(1 for x in ech2 if x >= reel)
        print("   taille gardee : reelle %d · decalee mediane %d" % (k, int(np.median(tailles))))
        print("   mediane du hasard %+0.3f · 5e-95e centile %+0.3f / %+0.3f"
              % (np.median(ech2), np.quantile(ech2, 0.05), np.quantile(ech2, 0.95)))
        print("   -> %d tirages sur %d font aussi bien (p ~ %.3f)"
              % (kb, len(ech2), (kb + 1) / (len(ech2) + 1)))


if __name__ == "__main__":
    main()
