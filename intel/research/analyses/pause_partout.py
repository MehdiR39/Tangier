"""LA PAUSE, APPLIQUEE AU CARNET REEL — et ensuite a toutes les pistes prometteuses.

MIDO, 20/09 : « je pense que ça vaut le coup de tester la pause sur toutes les strats qui sont
prometteuses, mais commençons par le moteur de la prod. »

CE QUE LA PAUSE EST. Apres un ticket qui se CLOTURE sous -30 %, on n achete plus pendant 30 min.
Rien d autre : pas de selection de jeton, pas de modele. Un interrupteur qui reagit a ce qui vient
de se passer sur NOTRE propre flux.

POURQUOI LE CARNET REEL D ABORD. C est le seul endroit ou les euros sont des euros : `gain_eur` est
lu sur le portefeuille, pas reconstruit a partir d un prix. Aucun modele de cout ne s interpose.
Et c est le flux sur lequel la pause serait effectivement branchee si elle marchait.

LES DEUX BARRES, comme en §3.162 -- et la seconde est celle qui compte :
  A. sous-ensembles au hasard de meme taille. Adversaire faible : il ne sait pas imiter « prendre
     des paquets d heures consecutives ».
  B. LES MEMES PLAGES DE PAUSE, DECALEES circulairement dans le temps. Meme nombre, memes durees ;
     seul le lien avec les VRAIES chutes est rompu. Si la pause vaut quelque chose, c est parce
     qu elle reagit aux chutes, pas parce qu elle decoupe le temps en morceaux.

CE QUE §3.111 ET §3.162 ONT DEJA ETABLI, pour ne pas le redecouvrir :
  - declenchee sur TOUT le marche, la pause ne se releve jamais (une chute toutes les 6 min pour
    une pause de 30) -- ce n est plus une strategie, c est un arret ;
  - sur le flux de la BANDE : barre A p = 0,016, barre B p = 0,060, et 3 tickets sur 80 portent
    91 % du gain. Non retenue.

Papier, zero euro, lecture seule. Ne decide rien : mesure.
"""
from __future__ import annotations

import os
import sqlite3
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SEUIL = float(os.environ.get("PAUSE_SEUIL", "-0.30"))
DUREE = float(os.environ.get("PAUSE_DUREE", "1800"))
TIRAGES = int(os.environ.get("TIRAGES", "2000"))


def carnet_reel():
    """(t_decision, t_cloture, gain en EUR, mise) du carnet REEL, en euros lus au portefeuille."""
    c = sqlite3.connect("file:/app/db/intel.sqlite?mode=ro", uri=True, timeout=30)
    L = []
    for te, ts, g, m in c.execute(
            "SELECT ts_entree, ts_sortie, gain_eur, mise_eur FROM mr_lignes"
            " WHERE mode='live' AND gain_eur IS NOT NULL AND ts_entree IS NOT NULL"
            " ORDER BY ts_entree"):
        mise = float(m or 10.0)
        L.append((float(te), float(ts) if ts else float(te) + 242.0, float(g), mise))
    return L


def applique(L, decl, dedans=False):
    """Les tickets HORS des plages de pause -- ou DEDANS si `dedans`.

    MIDO, 20/09, apres le resultat sur le carnet reel : « tu nous racontes la merde, il y en a un
    autre que tu rates ». Il avait raison : la mesure disait que la pause ECARTE des tickets a
    -0,22 EUR et GARDE ceux a -1,30. J ai conclu « la pause est mauvaise » sans voir que l inverse
    est alors un signal -- acheter PREFERENTIELLEMENT dans les 30 min qui suivent une chute.
    D ou ce parametre : le meme code mesure la regle et son contraire.
    """
    d = np.asarray(sorted(decl))
    out = []
    for te, _, g, _ in L:
        en_pause = False
        if len(d):
            i = np.searchsorted(d, te) - 1
            en_pause = i >= 0 and te - d[i] < DUREE
        if en_pause == dedans:
            out.append(g)
    return out


def barre(nom, L, decl, reel, k, rng, dedans=False):
    tous = [g for _, _, g, _ in L]
    t0, t1 = L[0][0], L[-1][0]
    span = max(t1 - t0, 1.0)
    ech, tailles = [], []
    for _ in range(TIRAGES):
        if nom == "A":
            ech.append(float(np.mean(rng.choice(tous, k, replace=False))))
        else:
            dec = [t0 + ((x - t0 + rng.uniform(0, span)) % span) for x in decl]
            v = applique(L, dec, dedans)
            if len(v) >= 10:
                ech.append(float(np.mean(v)))
                tailles.append(len(v))
    if not ech:
        return
    ks = sum(1 for x in ech if x >= reel)
    extra = (" · taille decalee mediane %d" % int(np.median(tailles))) if tailles else ""
    print("   BARRE %s : mediane du hasard %+0.4f · 5e-95e %+0.4f / %+0.4f%s"
          % (nom, np.median(ech), np.quantile(ech, 0.05), np.quantile(ech, 0.95), extra))
    print("      -> %d sur %d font aussi bien (p ~ %.3f)" % (ks, len(ech), (ks + 1) / (len(ech) + 1)))


def main() -> None:
    L = carnet_reel()
    if len(L) < 100:
        print("pause_partout: %d tickets reels, trop peu" % len(L))
        return
    n = len(L)
    heures = (L[-1][0] - L[0][0]) / 3600.0
    # LE DECLENCHEUR : l instant de CLOTURE d un ticket tombe sous le seuil. Utiliser l instant de
    # DECISION serait de la lecture d avenir -- on ne sait pas encore qu il sera mauvais.
    decl = [ts for _, ts, g, m in L if g / m <= SEUIL]
    pris = applique(L, decl)
    k = len(pris)
    tot_tous = sum(g for _, _, g, _ in L)
    print("CARNET REEL : %d tickets sur %.1f h · %d chutes sous %.0f %% (une toutes les %.1f min)"
          % (n, heures, len(decl), 100 * SEUIL, 60 * heures / max(len(decl), 1)))
    print("   sans pause  %4d tickets · %+8.4f EUR/ticket · %+9.2f EUR" % (n, tot_tous / n, tot_tous))
    if not k:
        print("   AVEC PAUSE : plus aucun ticket -- elle ne se releve jamais (cf. §3.111)")
        return
    s = sorted(pris)
    print("   avec pause  %4d tickets · %+8.4f EUR/ticket · %+9.2f EUR · sans 3 %+0.4f"
          % (k, sum(pris) / k, sum(pris), sum(s[:-3]) / (k - 3) if k > 3 else float("nan")))
    print("   elle ecarte %d tickets (%.0f %%), qui valaient %+0.2f EUR au total"
          % (n - k, 100 * (n - k) / n, tot_tous - sum(pris)))
    if k == n:
        return
    print()
    rng = np.random.default_rng(31)
    print("LA PAUSE (acheter HORS des 30 min qui suivent une chute)")
    barre("A", L, decl, sum(pris) / k, k, rng)
    barre("B", L, decl, sum(pris) / k, k, rng)

    # L INVERSE : acheter SEULEMENT dans les 30 min qui suivent une chute.
    dedans = applique(L, decl, dedans=True)
    kd = len(dedans)
    if kd >= 20:
        sd = sorted(dedans)
        print()
        print("L INVERSE (acheter SEULEMENT dans les 30 min qui suivent une chute)")
        print("   %4d tickets · %+8.4f EUR/ticket · %+9.2f EUR · sans 3 %+0.4f"
              % (kd, sum(dedans) / kd, sum(dedans), sum(sd[:-3]) / (kd - 3)))
        mi = kd // 2
        print("   deux moities : %+0.4f / %+0.4f · %.0f %% de gagnants"
              % (sum(dedans[:mi]) / mi, sum(dedans[mi:]) / (kd - mi),
                 100 * sum(1 for x in dedans if x > 0) / kd))
        barre("A", L, decl, sum(dedans) / kd, kd, rng, dedans=True)
        barre("B", L, decl, sum(dedans) / kd, kd, rng, dedans=True)


if __name__ == "__main__":
    main()
