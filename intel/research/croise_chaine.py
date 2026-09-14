"""Juger un signal sur les prix lus AUX RESERVES, pas chez DexScreener.

RAISON D ETRE. Toute la regle Telegram vient des courbes DexScreener : 2 560 lancements, coupes en
deux, 0 sur 20 000 au test du hasard. Elle tourne en reel depuis le 12/09. Mais recherche et
production partagent la meme source de prix, et une source a ses biais -- rafraichissement a
30-60 s, indexation absente avant T+1,5 min. Un effet qui ne serait qu une propriete de ce capteur
survivrait a toutes nos verifications sans exister sur le marche.

Ici les prix viennent des reserves du pool, lues sur la chaine (`solana_prix_chaine`). Autre
capteur, autre cadence, autre zone temporelle couverte. Ce jeu n a servi a choisir aucun seuil :
il est JUGEMENT EN ENTIER, sans coupure.

TROIS CONDITIONS, sans lesquelles le chiffre ne vaut rien :

  1. pools verifies -- seulement ceux reellement adosses au WSOL (`pool_quote`, voir
     `pools_propres.py`). 9,9 % ne le sont pas, et c est ce qui avait fabrique une fausse
     decouverte le 13/09 ;
  2. contrainte d execution AVANT mesure -- on n evalue que les jetons ou notre ordre passe sous
     15 % d impact. Mesurer un rendement la ou l on ne peut pas transiger produit un majorant ;
  3. test du hasard porte par la statistique qui porte l effet. Sur une queue epaisse la moyenne
     d un tirage varie tellement qu aucun effet reel ne s en distingue : la frequence des gros
     tickets, elle, se compte sur plusieurs tickets et ne peut pas etre portee par un seul coup.

RESULTAT DU 14/09, sortie a 4 min, 911 tickets executables :
    TELEGRAM         51   +0,116 par euro   sans best +0,061   16 % au-dessus de x1,9
    pas de Telegram 860   -0,039            sans best -0,045    2 %
    twitter seul    499   -0,067    ·    site seul 382   -0,063
    frequence >= x1,5 : 27 % contre 5 %, rapport x5,6, hasard 0,000 %
    frequence >= x1,9 : 16 % contre 2 %, rapport x7,5, hasard 0,000 %

CE MODULE N ACHETE RIEN, NE VEND RIEN, NE SIGNE RIEN.

Usage :
    python -m intel.research.croise_chaine [--tenue 240 300]
"""
from __future__ import annotations

import argparse
import random
import sqlite3
import statistics as st
import sys

sys.path.insert(0, "/app")

SOL_EUR = 94.06            # 14/09 ; simple facteur d echelle, sans effet sur les rapports
PEAGE = 0.024              # aller-retour mesure sur le carnet reel
MISE_EUR = 50.0
IMPACT_MAX = 0.15
AGE_MIN, AGE_MAX = 55, 180
TOLERANCE_S = 45           # ecart admis entre la sortie visee et le releve le plus proche


def charger(db: str) -> tuple[dict, dict]:
    c = sqlite3.connect("file:" + db + "?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    marque = {r["mint"]: dict(tg=r["telegram"], tw=r["twitter"], site=r["site"])
              for r in c.execute("SELECT mint, telegram, twitter, site FROM tg_juges")}
    courbes: dict[str, list] = {}
    for r in c.execute(
            "SELECT p.mint, p.age_s, p.prix_sol, p.reserve_sol, p.ts FROM solana_prix_chaine p"
            " JOIN pool_quote q ON q.pool = p.pair_id AND q.est_sol = 1"
            " WHERE p.prix_sol > 0 ORDER BY p.mint, p.age_s"):
        if r["mint"] in marque:
            courbes.setdefault(r["mint"], []).append(dict(r))
    return marque, courbes


def tickets(marque: dict, courbes: dict, tenue_s: int) -> list[dict]:
    """Un ticket par jeton. Entree au premier releve dans la fenetre, sortie `tenue_s` plus tard."""
    mise_sol = MISE_EUR / SOL_EUR
    out = []
    for mint, pts in courbes.items():
        e = next((p for p in pts if AGE_MIN <= p["age_s"] <= AGE_MAX), None)
        if not e or e["prix_sol"] <= 0 or e["reserve_sol"] <= 0:
            continue
        if mise_sol / e["reserve_sol"] > IMPACT_MAX:      # condition 2, avant toute mesure
            continue
        apres = [p for p in pts if p["age_s"] > e["age_s"]]
        if not apres:
            continue
        s = min(apres, key=lambda p: abs(p["age_s"] - (e["age_s"] + tenue_s)))
        if abs(s["age_s"] - (e["age_s"] + tenue_s)) > TOLERANCE_S:
            continue
        out.append(dict(mint=mint, ts=e["ts"], **marque[mint],
                        gain=(s["prix_sol"] / e["prix_sol"]) * (1 - PEAGE) - 1))
    return out


def stat(g: list[dict]) -> dict | None:
    if len(g) < 3:
        return None
    v = [x["gain"] for x in g]
    best = max(v)
    sans = [x for x in v if x != best] or v
    return dict(n=len(v), pe=sum(v) / len(v), med=st.median(v),
                sans=sum(sans) / len(sans), win=sum(1 for x in v if x > 0) / len(v),
                gros=sum(1 for x in v if x > 0.9) / len(v))


def ligne(lib: str, s: dict | None) -> str:
    if not s:
        return "  %-26s      --" % lib
    return ("  %-26s %5d %+9.3f %+9.3f %+11.3f %8.0f %% %7.0f %%"
            % (lib, s["n"], s["pe"], s["med"], s["sans"], 100 * s["win"], 100 * s["gros"]))


def hasard_moyenne(tous: list[dict], k: int, cible: float, n: int = 20000, seed: int = 11):
    """Part des tirages de k tickets au hasard dont la MOYENNE atteint `cible`."""
    v = [x["gain"] for x in tous]
    if k < 3 or k >= len(v):
        return None
    random.seed(seed)
    return sum(1 for _ in range(n) if sum(random.sample(v, k)) / k >= cible) / n


def hasard_frequence(tous: list[dict], k: int, seuil: float, atteints: int,
                     n: int = 20000, seed: int = 13):
    """Part des tirages de k tickets au hasard qui comptent au moins `atteints` gains >= `seuil`.

    C est le test qui compte : contrairement a la moyenne, cette statistique ne peut pas etre
    portee par un seul gros ticket."""
    v = [x["gain"] for x in tous]
    if k < 3 or k >= len(v):
        return None
    random.seed(seed)
    return sum(1 for _ in range(n)
               if sum(1 for g in random.sample(v, k) if g >= seuil) >= atteints) / n


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="/app/db/intel.sqlite")
    ap.add_argument("--tenue", type=int, nargs="*", default=[240, 300])
    a = ap.parse_args()
    marque, courbes = charger(a.db)
    if not courbes:
        print("  aucune courbe sur pool verifie -- lancer d abord intel.research.pools_propres")
        return

    for tenue in a.tenue:
        T = tickets(marque, courbes, tenue)
        if len(T) < 30:
            print("  tenue %ds : %d tickets seulement, on ne conclut pas" % (tenue, len(T)))
            continue
        tg = [x for x in T if x["tg"]]
        non = [x for x in T if not x["tg"]]
        print()
        print("=" * 92)
        print("  SORTIE A %d MIN · %d tickets executables, prix lus aux reserves"
              % (tenue // 60, len(T)))
        print("  %-26s %5s %9s %9s %11s %9s %8s"
              % ("", "n", "par euro", "mediane", "sans best", "gagnants", ">= x1,9"))
        print(ligne("TELEGRAM", stat(tg)))
        print(ligne("pas de Telegram", stat(non)))
        print(ligne("twitter seul", stat([x for x in T if x["tw"] and not x["tg"]])))
        print(ligne("site seul", stat([x for x in T if x["site"] and not x["tg"]])))
        print(ligne("aucun reseau", stat([x for x in T
                                          if not x["tw"] and not x["site"] and not x["tg"]])))
        s = stat(tg)
        if not s or not non:
            continue
        print()
        print("  TEST DU HASARD (20 000 tirages de %d tickets parmi %d)" % (len(tg), len(T)))
        h = hasard_moyenne(T, len(tg), s["pe"])
        reste = sorted(tg, key=lambda x: -x["gain"])[1:]
        h2 = hasard_moyenne(T, len(reste), sum(x["gain"] for x in reste) / len(reste))
        print("    sur la moyenne           : %6.2f %%" % (100 * h))
        print("    sans son meilleur ticket : %6.2f %%" % (100 * h2))
        print("    sur la FREQUENCE des gros tickets, qu un seul coup ne peut pas porter :")
        for seuil, lib in ((0.5, "x1,5"), (0.9, "x1,9"), (2.0, "x3")):
            k = sum(1 for x in tg if x["gain"] >= seuil)
            b = sum(1 for x in non if x["gain"] >= seuil)
            pa, pb = k / len(tg), b / len(non)
            hf = hasard_frequence(T, len(tg), seuil, k)
            print("      >= %-5s %3d/%3d %3.0f %%  contre %3d/%3d %3.0f %%  rapport %-6s hasard %6.3f %%"
                  % (lib, k, len(tg), 100 * pa, b, len(non), 100 * pb,
                     ("x%.1f" % (pa / pb)) if pb else "inf", 100 * hf if hf is not None else -1))


if __name__ == "__main__":
    main()
