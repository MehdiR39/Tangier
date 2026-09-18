"""FREIN SUR LE TAUX DE GAGNANTS RECENT, PRE-ENREGISTRE le 18/09/2026 a 15h00 UTC (17h00 Paris).

D OU ÇA VIENT. Mido, apres une journee ou j avais declare le regime de marche mort : « j arrive pas
a croire qu on rate pas un truc -- la on a un taux de +64 %, peu de positions perdantes, et on
arrive pas a trouver un switch de regime ou un frein quand le marche va changer ». Il avait raison,
et l erreur etait de conception : **j avais teste 45 formulations du regime, et AUCUNE n etait un
TAUX.** Toutes portaient sur le rendement MOYEN -- ecrase par quelques tickets a +200 %, donc trop
bruite pour montrer quoi que ce soit. Le taux de gagnants est borne entre 0 et 1, insensible aux
queues : le signal y est visible.

CE QUI EST MESURE, sur `RISQUE seul` (1 373 tickets), avec une CAUSALITE STRICTE -- seuls les
tickets deja CLOTURES a l instant de la decision comptent (t+242 s), jamais ceux encore ouverts :

    quartile du taux recent (20 derniers)     45 %     55 %     65 %     75 %
    NET du ticket suivant                   -3,84 %  -0,92 %  +1,55 %  +2,83 %

**Monotone sur les quatre quartiles.** Et la fenetre de 50 tickets, independante, donne la meme
forme : -3,30 / -0,99 / +1,18 / +3,09 %. C est la premiere fois dans ce projet qu une variable de
marche ordonne le net sans zigzaguer.

LA REGLE FIGEE : ne pas acheter quand le taux de gagnants des 20 derniers tickets CLOTURES est
inferieur ou egal a 50 %. Le seuil n est pas ajuste sur les donnees : 50 % est la frontiere
NATURELLE -- plus de perdants que de gagnants recemment. Un seuil optimise serait invalide d avance.

CE QUI N EST PAS DEMONTRE, et il faut le dire avant de voir la suite. S abstenir sous 50 % donne
+1,47 % par ticket contre -0,09 % pour le temoin, mais **p = 0,152** contre un tirage au hasard de
meme taille -- et j ai essaye TROIS fenetres, donc il faudrait nettement mieux que 0,05, pas juste
0,05. La monotonie sur 4 quartiles x 2 fenetres est un fait a part, structurellement plus dur a
obtenir par hasard qu un seul p, mais elle a ete constatee APRES coup.

PUISSANCE, CALCULEE AVANT DE FIGER. L ecart-type du net est de 74 points par ticket : detecter
+1,5 pt en argent demanderait ~19 000 tickets. C est hors d atteinte. On juge donc sur ce qui est
mesurable a taille raisonnable -- l ORDRE des quartiles, qui se lit avec une correlation de rang.
Pour detecter rho = 0,068 a 80 %, il faut ~1 700 tickets ; flux mesure ~350 tickets/jour de
`RISQUE seul`, soit ~5 jours.

CRITERE, FIGE, au premier atteint de 1 500 tickets posterieurs au gel ou de 21 jours :
  (a) la correlation de rang entre le taux recent et le net du ticket suivant doit rester POSITIVE ;
  (b) le premier quartile doit rester le PIRE et le quatrieme le MEILLEUR ;
  (c) s abstenir sous 50 % doit faire MIEUX que tout prendre, sur EXACTEMENT les memes tickets.
Les trois, sinon la piste est abandonnee et ecrite comme telle.

CE QUI NE CHANGE PAS. La production ne lit pas ce fichier : elle continue d acheter sans frein.
Lecture seule sur `papier_combo`, aucun processus lance, aucune base ecrite.
"""
from __future__ import annotations

import bisect
import os
import sqlite3
import statistics as st

GEL_FREIN = 1789736400.0          # 18/09/2026 15h00 UTC = 17h00 Paris
FENETRE = 20                      # le nombre de tickets clotures qu on regarde en arriere
SEUIL = 0.50                      # frontiere NATURELLE, pas un seuil ajuste
SEUIL_RISQUE = 0.2694             # la regle de base : `RISQUE seul`
COUT, TENUE_S, PLAFOND = 0.0262, 242.0, 3.0
N_CRITERE, JOURS_CRITERE = 1500, 21
BASE = os.environ.get("COMBO_DB", "/app/db/papier_combo.sqlite")


def serie(ici: sqlite3.Connection) -> list[tuple[float, float]]:
    """(instant de decision, net) pour tous les tickets de `RISQUE seul`, tries."""
    return [(t, min(b - COUT, PLAFOND)) for t, b in ici.execute(
        "SELECT d.t_dec, i.brut_240 FROM decision d JOIN issue i ON i.pair = d.pair"
        " WHERE d.eligible = 1 AND i.brut_240 IS NOT NULL AND d.risque IS NOT NULL"
        " AND d.risque <= ? ORDER BY d.t_dec", (SEUIL_RISQUE,))]


def taux_recents(R: list[tuple[float, float]]) -> list[tuple[float, float, float]]:
    """(instant, taux de gagnants des FENETRE derniers CLOTURES, net du ticket).

    La causalite est le point critique : un ticket decide a t ne rend son resultat qu a t+242 s.
    On ne regarde donc que les tickets dont la CLOTURE precede t. Utiliser les tickets encore
    ouverts reviendrait a lire l avenir, et c est exactement ce qui a fabrique de faux regimes
    plus tot dans ce projet.
    """
    clos = sorted((t + TENUE_S, x) for t, x in R)
    tc = [x[0] for x in clos]
    out = []
    for t, x in R:
        i = bisect.bisect_right(tc, t)
        if i < FENETRE:
            continue
        v = [clos[k][1] for k in range(i - FENETRE, i)]
        out.append((t, sum(1 for y in v if y > 0) / FENETRE, x))
    return out


def _spearman(a: list[float], b: list[float]) -> float:
    def rg(v):
        o = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(o):
            j = i
            while j + 1 < len(o) and v[o[j + 1]] == v[o[i]]:
                j += 1
            m = (i + j) / 2 + 1
            for z in range(i, j + 1):
                r[o[z]] = m
            i = j + 1
        return r
    x, y = rg(a), rg(b)
    mx, my = st.mean(x), st.mean(y)
    num = sum((p - mx) * (u - my) for p, u in zip(x, y))
    den = (sum((p - mx) ** 2 for p in x) * sum((u - my) ** 2 for u in y)) ** 0.5
    return num / den if den else 0.0


def rapport(ici: sqlite3.Connection, mise: float = 25.0) -> None:
    D = [z for z in taux_recents(serie(ici)) if z[0] >= GEL_FREIN]
    print("\nFREIN SUR LE TAUX DE GAGNANTS · PRE-ENREGISTRE le 18/09 a 17h00 Paris")
    print("   %d ticket(s) depuis le gel, sur les %d du critere" % (len(D), N_CRITERE))
    if len(D) < 40:
        print("   CRITERE : correlation positive, Q1 le pire et Q4 le meilleur, et s abstenir")
        print("             sous %.0f %% doit battre tout prendre sur les memes tickets." % (100 * SEUIL))
        return
    rho = _spearman([z[1] for z in D], [z[2] for z in D])
    S = sorted(D, key=lambda z: z[1])
    q = len(S) // 4
    nets = []
    for k in range(4):
        s = S[k * q:(k + 1) * q] if k < 3 else S[3 * q:]
        nets.append(st.mean(z[2] for z in s))
        print("   Q%d  taux %3.0f %% · n=%4d · net %+6.2f %%"
              % (k + 1, 100 * st.median(z[1] for z in s), len(s), 100 * nets[-1]))
    tous = [z[2] for z in D]
    gard = [z[2] for z in D if z[1] > SEUIL]
    print("   correlation de rang : %+.3f" % rho)
    if gard:
        print("   tout prendre  n=%4d · %+6.2f %% · %+7.0f EUR" % (len(tous), 100 * st.mean(tous), mise * sum(tous)))
        print("   avec le frein n=%4d · %+6.2f %% · %+7.0f EUR" % (len(gard), 100 * st.mean(gard), mise * sum(gard)))
    a = rho > 0
    b = nets[0] == min(nets) and nets[3] == max(nets)
    d = bool(gard) and st.mean(gard) > st.mean(tous)
    print("   (a) correlation positive : %s · (b) Q1 pire et Q4 meilleur : %s · (c) le frein aide : %s"
          % ("oui" if a else "NON", "oui" if b else "NON", "oui" if d else "NON"))
    print("   -> %s" % ("CRITERE TENU" if (a and b and d) else "critere non atteint a ce stade"))
    print("   CRITERE, a %d tickets ou %d jours : les trois, sinon abandon." % (N_CRITERE, JOURS_CRITERE))


if __name__ == "__main__":
    rapport(sqlite3.connect("file:%s?mode=ro" % BASE, uri=True, timeout=60))
