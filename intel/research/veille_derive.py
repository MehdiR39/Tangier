"""SURVEILLE LA DERIVE, ET NE RE-OPTIMISE QU A DES CONDITIONS ECRITES D AVANCE.

Mido, 23/09 : « ton etude va te permettre de mettre en place un script auto qui optimise le modele
s il drift ? ». Oui -- mais pas un optimiseur libre.

POURQUOI PAS UN OPTIMISEUR LIBRE. L etude quant a donne un Deflated Sharpe Ratio de 0,185 pour
~35 essais : environ quatre chances sur cinq que le Sharpe observe soit un artefact de SELECTION.
Or chaque re-optimisation est un essai de plus, et le seuil monte avec N :

    N essais       10      35     100     500
    DSR          0,495   0,185   0,065   0,010

Un script qui re-optimise a chaque derive se detruirait donc lui-meme en croyant s ameliorer : il
trouverait toujours une configuration qui brille sur le passe recent, et la barre a franchir
monterait sans que personne ne la regarde.

D OU LA REGLE DE CONSTRUCTION : le compteur d essais est PERSISTANT et CUMULATIF. Chaque
evaluation -- y compris celles de ce script -- l incremente, et la barre monte en consequence. Le
systeme devient donc de plus en plus exigeant avec le temps, ce qui est le comportement correct.

CE QUE CE SCRIPT FAIT
  1. mesure les indicateurs de derive (voir la note d etude) ;
  2. si tout est dans sa zone : il ne fait RIEN, et le dit ;
  3. si une derive est constatee : il evalue la grille PRE-ENREGISTREE en walk-forward, et ne
     propose un remplacant que s il franchit QUATRE conditions a la fois ;
  4. il n applique JAMAIS le changement. Il ecrit un verdict, Mido decide. Un automate qui modifie
     une regle engageant de l argent reel n est pas un automate de surveillance.

Usage : python -m intel.research.veille_derive
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import sys
import time

import numpy as np
from scipy import stats

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from papier_combo import BANDE, GEL_BP, TENUE_S  # noqa: E402

ETAT = os.environ.get("DERIVE_ETAT", "/app/data/recherche/derive_etat.json")
COMBO = os.environ.get("COMBO_DB", "/app/db/papier_combo.sqlite")
V, FIXE_DEF = 17.5845, 0.03524
GAMMA = 0.5772156649

# ---------------------------------------------------------------------------------------------
# CE QUI NE BOUGE PLUS, ET POURQUOI. Mido, 23/09 : « fixe ce qu on pense devrait pas bouger ».
#
# Chaque parametre retire de la grille divise le nombre d essais N, et la barre a franchir croit
# en racine(2 ln N). Retirer les quatre ci-dessous fait passer N de ~35 a 12 : le Deflated Sharpe
# du resultat actuel remonte de 0,185 a 0,439. C est le seul levier gratuit du dispositif --
# raisonner au lieu de balayer.
#
# UN PARAMETRE NE SORT DE LA GRILLE QUE S IL A UN MECANISME, jamais parce qu il donne un bon
# chiffre. Un bon chiffre sans mecanisme, c est precisement ce que le DSR penalise.
#
#   SORTIE A 287 s -- MECANISME ETABLI. Ce marche pompe puis s effondre (81 % des pools retirent
#     leur liquidite une seconde apres le dernier echange). 287 s est la fin de la fenetre de
#     pompe : sur 1 128 tickets apparies, c est le SEUL age positif (+2,909, +2,02 sigma) et la
#     degradation au-dela est monotone jusqu a -15,574 a 1 800 s. On ne le rebalaye plus.
#
#   LA BANDE -- MECANISME ETABLI SUR SA POSITION, PAS SUR SES NOMBRES. Attention, la nuance est
#     tout le sujet et je l ai d abord ecrite de travers. Le mecanisme dit « acheter le MILIEU de
#     la distribution du score » : le cinquieme le plus sur a ZERO gros gain sur 271 tickets --
#     il bouge de 3,1 % quand le peage est de 3,88 %, donc il ne peut pas payer le passage -- et
#     le quatrieme cinquieme est le seul rentable.
#
#     Ce milieu, ce sont les QUANTILES [0,45 ; 0,91]. Les valeurs 0,20 et 0,35 ne sont que la
#     facon dont CE modele-ci les exprime : le meme milieu sur le modele reentraine du 22/09 vaut
#     [0,178 ; 0,392]. Donc ce qui est fixe, c est la position ; les bornes brutes en sont une
#     consequence, et elles DOIVENT etre recalculees a tout changement de modele.
#
#     Deux choses a savoir avant de toucher a ca :
#       - la distribution derive meme a modele constant (la bande fixe attrape 41 a 52 % des
#         tickets selon le jour), donc les bornes fixes ne selectionnent deja pas tout a fait la
#         meme population d un jour a l autre ;
#       - une bande en quantiles glissants a ete testee et ne fait PAS mieux (+1,200 contre
#         +1,330, et pire sans la pause). On garde donc les bornes fixes en service -- en sachant
#         que ce sont des constantes de ce modele, pas des constantes du marche.
#
#   LIGHTGBM -- TRANCHE. Teste contre une foret aleatoire a armes egales sur 1 176 tickets jamais
#     vus : AUC 0,632 contre 0,628, la meme information. Ce n est plus un choix ouvert.
#
#   TENUE = 240 s ET DECISION = 45 s -- hors de portee du rejeu de toute facon : le carnet ne
#     calcule ses variables qu a 45 s. Les 45 s restent le seul reglage sans mecanique ni
#     verification a jour : c est une DETTE, pas une certitude (voir la note d etude).
#
# RESTENT DONC DANS LA GRILLE les deux parametres sans mecanisme : la duree et le seuil de la
# pause. Douze configurations, pas quinze mille.
# ---------------------------------------------------------------------------------------------
GRILLE = [(d, s) for d in (900.0, 1800.0, 2700.0) for s in (-0.20, -0.25, -0.30, -0.40)]

# Le compteur d essais part de 12 -- la taille de CETTE grille -- et non des 35 strategies du
# projet : une fois les quatre parametres ci-dessus sortis par mecanisme, ils ne comptent plus
# comme des essais. C est tout l interet de les fixer.
ESSAIS_DEPART = len(GRILLE)

# LES ZONES DE NORMALITE, mesurees sur six jours (note d etude, section « La derive »).
ZONES = {
    "krach": (0.25, 0.50),        # part des tickets de bande cloturant sous le seuil
    "blocage": (0.70, 0.97),      # part des candidats refuses par la pause
    "part_bande": (0.35, 0.58),   # part des tickets eligibles qui tombent dans la bande
}


def charger_etat() -> dict:
    try:
        return json.load(open(ETAT))
    except Exception:  # noqa: BLE001
        return {"essais": ESSAIS_DEPART, "historique": []}


def enregistrer_etat(e: dict) -> None:
    tmp = ETAT + ".tmp"
    json.dump(e, open(tmp, "w"), indent=1)
    os.replace(tmp, ETAT)


def dsr(sr: float, n: int, sk: float, ku: float, N: int) -> tuple[float, float]:
    """Deflated Sharpe Ratio (Bailey & Lopez de Prado, 2014). Rend (seuil de selection, DSR).

    `sr_star` est le Sharpe qu atteint le MAXIMUM de N strategies sans aucun edge : c est la barre
    que la selection place toute seule. Le DSR est la probabilite que le Sharpe vrai depasse cette
    barre, corrigee de l asymetrie et de l exces de kurtosis -- indispensable ici, la distribution
    ayant un indice de queue de Hill entre 1,5 et 2,4.
    """
    N = max(int(N), 2)
    e = (math.sqrt(1 - GAMMA) * stats.norm.ppf(1 - 1.0 / N)
         + math.sqrt(GAMMA) * stats.norm.ppf(1 - 1.0 / (N * math.e)))
    sr_star = e / math.sqrt(max(n - 1, 1))
    den = math.sqrt(max(1 - sk * sr + (ku / 4.0) * sr * sr, 1e-9))
    return sr_star, float(stats.norm.cdf((sr - sr_star) * math.sqrt(max(n - 1, 1)) / den))


def joue(tk, seuil, duree):
    """La pause, rejouee dans l ordre reel."""
    pris, att, bl = [], [], 0.0
    for x in tk:
        att.sort(key=lambda z: z["fin"])
        while att and att[0]["fin"] <= x["t"]:
            f = att.pop(0)
            if f["r"] <= seuil:
                bl = max(bl, f["fin"] + duree)
        if x["t"] >= bl:
            pris.append(x)
        att.append(x)
    return pris


def main() -> None:
    etat = charger_etat()
    mise, fixe, seuil_prod, duree_prod = 20.0, FIXE_DEF, -0.30, 1800.0
    try:
        from intel.settings import IntelConfig, Settings
        cfg = IntelConfig.load(Settings.load().config_path)
        mise = float(cfg.get("modele_rapide.mise_eur", mise))
        fixe = float(cfg.get("modele_rapide.pause_cout_fixe", fixe))
        seuil_prod = float(cfg.get("modele_rapide.pause_seuil", seuil_prod))
        duree_prod = float(cfg.get("modele_rapide.pause_secondes", duree_prod))
    except Exception:  # noqa: BLE001
        pass

    def cout(q):
        return fixe + 2.0 * (mise * 0.31 / 30.0) / ((q or 0) + V)

    cn = sqlite3.connect("file:%s?mode=ro" % COMBO, uri=True, timeout=30)
    tous, bande = [], []
    for t, r, q, b in cn.execute(
            "SELECT d.t_dec, d.risque, d.q, i.brut_240 FROM decision d JOIN issue i ON i.pair=d.pair"
            " WHERE d.eligible=1 AND i.brut_240 IS NOT NULL AND d.q IS NOT NULL"
            " AND d.risque IS NOT NULL AND d.t_dec>=? ORDER BY d.t_dec", (GEL_BP,)):
        x = {"t": float(t), "fin": float(t) + TENUE_S, "r": min(float(b) - cout(q), 3.0)}
        tous.append(x)
        if BANDE[0] <= float(r) < BANDE[1]:
            bande.append(x)
    if len(bande) < 60:
        print("pas assez de tickets pour juger (%d dans la bande)" % len(bande))
        return

    prod = joue(bande, seuil_prod, duree_prod)
    R = np.array([mise * x["r"] for x in prod])
    n = len(R)

    print("=" * 74)
    print("VEILLE DE DERIVE — %s" % time.strftime("%d/%m/%Y %H:%M"))
    print("=" * 74)

    krach = sum(1 for x in bande if x["r"] <= seuil_prod) / len(bande)
    blocage = 1.0 - len(prod) / len(bande)
    part_bande = len(bande) / max(len(tous), 1)
    mesures = {"krach": krach, "blocage": blocage, "part_bande": part_bande}
    print()
    print("INDICATEURS")
    hors = []
    for cle, (lo, hi) in ZONES.items():
        v = mesures[cle]
        ok = lo <= v <= hi
        if not ok:
            hors.append(cle)
        print("   %-12s %6.1f %%   zone %.0f-%.0f %%   %s"
              % (cle, 100 * v, 100 * lo, 100 * hi, "ok" if ok else "*** HORS ZONE ***"))

    nul = 0.384 * (mise / 20.0)
    m = float(R.mean())
    s = float(R.std(ddof=1)) or 1.0
    sk, ku = float(stats.skew(R)), float(stats.kurtosis(R))
    # BOOTSTRAP PAR BLOCS : les tickets se chevauchent dans le temps (chacun tient 240 s), donc
    # sigma/racine(n) sous-estime l incertitude. Longueur de bloc ~ n^(1/3).
    L = max(2, int(n ** (1 / 3)))
    bb = np.array([np.concatenate(
        [R[i:i + L] for i in np.random.randint(0, n - L + 1, int(np.ceil(n / L)))])[:n].mean()
        for _ in range(4000)])
    p_nul = float(np.mean(bb <= nul))
    sr_star, d = dsr(m / s, n, sk, ku, etat["essais"])
    print()
    print("RESULTAT")
    print("   %d tickets · %+0.3f EUR/ticket · nul %+0.3f" % (n, m, nul))
    print("   bootstrap par blocs : IC95 %+0.3f a %+0.3f · p(<= nul) = %.4f"
          % (np.percentile(bb, 2.5), np.percentile(bb, 97.5), p_nul))
    print("   Sharpe %.4f · barre de selection %.4f (N=%d essais) · DSR %.4f"
          % (m / s, sr_star, etat["essais"], d))

    derive = bool(hors) or m <= nul
    print()
    print("VERDICT")
    if not derive:
        print("   RIEN A FAIRE. Les indicateurs sont dans leur zone et le resultat depasse le nul.")
        print("   Aucune re-optimisation : on ne touche pas a une regle qui tourne.")
        etat["historique"].append({"t": time.time(), "n": n, "moyenne": m, "dsr": d, "derive": False})
        enregistrer_etat(etat)
        return

    print("   DERIVE : %s" % (", ".join(hors) if hors else "resultat sous le nul"))
    print("   Evaluation de la grille pre-enregistree en WALK-FORWARD (2/3 apprentissage, 1/3 test).")
    coupe = int(0.66 * len(bande))
    app, test = bande[:coupe], bande[coupe:]
    lignes = []
    for d_, s_ in GRILLE:
        pa, pt = joue(app, s_, d_), joue(test, s_, d_)
        if len(pa) < 20 or len(pt) < 20:
            continue
        va = np.array([mise * x["r"] for x in pa])
        vt = np.array([mise * x["r"] for x in pt])
        lignes.append((d_, s_, float(va.mean()), float(vt.mean()), len(pt), vt))
    if not lignes:
        print("   pas assez de tickets par configuration pour trancher — on attend.")
        enregistrer_etat(etat)
        return

    # LE MEILLEUR EN APPRENTISSAGE, jamais en test : choisir sur le test serait exactement la
    # fuite que tout ce dispositif existe pour empecher.
    lignes.sort(key=lambda z: -z[2])
    d_, s_, ma, mt, nt, vt = lignes[0]
    etat["essais"] += len(lignes)          # chaque evaluation est un essai : la barre monte
    srt = mt / (float(vt.std(ddof=1)) or 1.0)
    _, d2 = dsr(srt, nt, float(stats.skew(vt)), float(stats.kurtosis(vt)), etat["essais"])
    print()
    print("   meilleur en apprentissage : pause %.0f min / seuil %.2f" % (d_ / 60, s_))
    print("      apprentissage %+0.3f · TEST %+0.3f sur %d tickets" % (ma, mt, nt))
    print("      DSR du test %.4f (N=%d apres cette evaluation)" % (d2, etat["essais"]))

    conditions = [("bat la production en test", mt > m),
                  ("positif en valeur absolue", mt > 0),
                  ("depasse le nul", mt > nul),
                  ("DSR >= 0,50", d2 >= 0.50)]
    print()
    print("   LES QUATRE CONDITIONS :")
    for nom, ok in conditions:
        print("      %-28s %s" % (nom, "OUI" if ok else "non"))
    print()
    if all(ok for _, ok in conditions):
        print("   -> CANDIDAT VALIDE. A GELER, puis juger sur 200 tickets POSTERIEURS avant tout")
        print("      passage en production. Ce script ne change rien de lui-meme.")
    else:
        print("   -> AUCUN REMPLACANT. On garde la regle en service et on continue de mesurer.")
        print("      Re-optimiser sans franchir ces conditions, c est courir apres le bruit.")
    etat["historique"].append({"t": time.time(), "n": n, "moyenne": m, "dsr": d, "derive": True,
                               "candidat": [d_, s_, mt, d2]})
    enregistrer_etat(etat)


if __name__ == "__main__":
    main()
