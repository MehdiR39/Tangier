"""ENTREE A T+75 CONTRE T+60, PRE-ENREGISTRE le 18/09/2026 a 07h05 UTC (09h05 Paris).

POURQUOI. La production entre a T+60, choisi le 12/09 sur 183 jetons Telegram parce que c etait le
point ou les deux moities s accordaient (+0,197 et +0,194). Mido a demande, a juste titre, pourquoi
on ne deplacerait pas l heure d entree si une autre est meilleure. Mesure faite sur la population
que la production trade REELLEMENT -- les jetons portant un Telegram -- appariee, memes jetons,
meme duree de detention de 240 s, seul l age d entree change :

    entree      T+30     T+45     T+47     T+60      T+75      T+90
    brut       +1,73 %  +5,62 %  +3,53 %  +6,01 %  +10,97 %   +9,81 %
    ecart      -4,27    -0,39    -2,48      ref     +4,97     +3,80
    IC95   [-8,4;-0,1] [-3,4;+2,4] [-5,6;+0,4]   [+1,3;+9,2] [-1,0;+8,7]

T+75 est le seul dont l intervalle exclut zero, et ses deux moities chronologiques sont positives
(+15,94 / +6,01). T+45 -- l heure de MA recherche -- est indiscernable de T+60 sur cette
population : le +0,87 pt que j avais annonce venait d une autre population et ne se transfere pas.

TROIS RAISONS DE NE PAS Y CROIRE ENCORE, ecrites avant de voir la suite.
  1. C est le MEILLEUR DE SIX ages testes. Avec cinq comparaisons, un « significatif » par pur
     hasard arrive environ une fois sur quatre.
  2. L effet FOND DEJA quand l echantillon s elargit : +4,97 pt sur les 364 jetons disponibles aux
     six ages, +3,08 pt sur les 430 disponibles aux deux ages qui nous interessent. C est la
     signature classique d une surestimation par selection.
  3. C est exactement le profil de la BANDE : +3,90 % en echantillon, morte hors echantillon
     (-8,38 % par ticket, §3.111). Une mesure retrospective ne decide rien ici.

PUISSANCE, CALCULEE AVANT DE FIGER. L ecart apparie a un ecart-type de 36,37 pts par ticket.
A 1 000 tickets, on detecte un effet de 3,2 pts avec 80 % de chances. On dimensionne donc sur un
effet PLUS PETIT que l observe, jamais sur l observe. Flux mesure : 57 jetons Telegram par jour,
donc 1 000 tickets ~ 18 jours.

CRITERE, FIGE, au premier atteint de 1 000 tickets posterieurs au gel ou de 21 jours :
  (a) T+75 doit faire MIEUX que T+60 sur EXACTEMENT les memes jetons (comparaison appariee) ;
  (b) l ecart doit rester positif sur les DEUX moities chronologiques ;
  (c) T+75 doit etre positif APRES le cout d execution mesure de 2,62 pts.
Les trois, sinon la piste est abandonnee et ecrite comme telle.

CE QUI NE CHANGE PAS. La production reste a T+60. Ce fichier ne decide rien, ne lance aucun
processus, n ecrit dans aucune base : il relit `solana_social` (le drapeau Telegram) et
`solana_prix_chaine` (les prix), tous deux en LECTURE SEULE. Aucun collecteur en marche n est
touche, aucun des quatre autres gels n est affecte.
"""
from __future__ import annotations

import os
import sqlite3
import statistics as st
from collections import defaultdict

GEL_E75 = 1789715100.0            # 18/09/2026 07h05 UTC = 09h05 Paris
AGE_REF, AGE_TEST = 60, 75        # la production contre le candidat
TENUE_S = 240                     # duree de detention, identique pour les deux
TOL_S = 6                         # tolerance d appariement d une lecture a un age vise
COUT = 0.0262                     # cout d execution mesure sur 244 tickets reels
PLAFOND = 3.0                     # meme plafond que partout ailleurs
N_CRITERE, JOURS_CRITERE = 1000, 21
BASE = os.environ.get("INTEL_DB", "/app/db/intel.sqlite")


def _a_age(pts: list[tuple[float, float]], cible: float):
    """La lecture la plus proche de cet age, si elle est assez proche. Sinon rien -- on ne devine pas."""
    b = min(pts, key=lambda r: abs(r[0] - cible), default=None)
    return b if b and abs(b[0] - cible) <= TOL_S else None


def paires(ici: sqlite3.Connection, depuis: float = GEL_E75) -> list[tuple[float, float, float]]:
    """(naissance, rendement a T+60, rendement a T+75) pour chaque jeton Telegram ne apres le gel."""
    tg = {m for (m,) in ici.execute(
        "SELECT DISTINCT mint FROM solana_social WHERE telegram = 1 AND mint IS NOT NULL")}
    if not tg:
        return []
    chem: dict[str, list[tuple[float, float]]] = defaultdict(list)
    naissance: dict[str, float] = {}
    mints: dict[str, str] = {}
    for pair, mint, ts, age, p in ici.execute(
            "SELECT pair_id, mint, ts, age_s, prix_sol FROM solana_prix_chaine"
            " WHERE prix_sol > 0 ORDER BY pair_id, age_s"):
        chem[pair].append((age, p))
        mints[pair] = mint
        naissance.setdefault(pair, ts - age)
    out = []
    for pair, pts in chem.items():
        if mints.get(pair) not in tg or naissance.get(pair, 0) < depuis:
            continue
        e0, s0 = _a_age(pts, AGE_REF), _a_age(pts, AGE_REF + TENUE_S)
        e1, s1 = _a_age(pts, AGE_TEST), _a_age(pts, AGE_TEST + TENUE_S)
        if not (e0 and s0 and e1 and s1) or s0[0] <= e0[0] or s1[0] <= e1[0]:
            continue
        out.append((naissance[pair],
                    min(s0[1] / e0[1] - 1, PLAFOND),
                    min(s1[1] / e1[1] - 1, PLAFOND)))
    out.sort()
    return out


def rapport(ici: sqlite3.Connection, mise: float = 25.0) -> None:
    v = paires(ici)
    print("\nENTREE T+75 vs T+60 · PRE-ENREGISTRE le 18/09 a 09h05 Paris")
    print("   %d jeton(s) Telegram depuis le gel, sur les %d du critere" % (len(v), N_CRITERE))
    if not v:
        print("   CRITERE : (a) mieux que T+60 apparie, (b) les deux moities, (c) positif apres 2,62 pts.")
        return
    r60 = [x[1] for x in v]
    r75 = [x[2] for x in v]
    d = [b - a for a, b in zip(r60, r75)]
    m = len(v) // 2
    for nom, r in (("T+60 (production)", r60), ("T+75 (candidat)", r75)):
        net = st.mean(r) - COUT
        print("   %-20s brut %+6.2f %% · net %+6.2f %% · %+7.0f EUR"
              % (nom, 100 * st.mean(r), 100 * net, mise * net * len(r)))
    print("   ecart apparie      %+.2f pt · moities %+.2f / %+.2f"
          % (100 * st.mean(d), 100 * st.mean(d[:m]), 100 * st.mean(d[m:])))
    a = st.mean(d) > 0
    b = len(v) >= 4 and st.mean(d[:m]) > 0 and st.mean(d[m:]) > 0
    c = st.mean(r75) - COUT > 0
    print("   (a) mieux que T+60 : %s · (b) deux moities : %s · (c) positif apres cout : %s"
          % ("oui" if a else "NON", "oui" if b else "NON", "oui" if c else "NON"))
    print("   -> %s" % ("CRITERE TENU" if (a and b and c) else "critere non atteint a ce stade"))
    print("   CRITERE, a %d tickets ou %d jours : les trois, sinon la piste est abandonnee."
          % (N_CRITERE, JOURS_CRITERE))


if __name__ == "__main__":
    rapport(sqlite3.connect("file:%s?mode=ro" % BASE, uri=True, timeout=60))
