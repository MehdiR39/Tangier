"""Le simulateur corrige colle-t-il enfin a l argent reel ? (15/09)

DEUX DEFAUTS DU COLLECTEUR `prix_chaine.py`, prouves en chaine le 15/09 :

  1. RESERVE VIRTUELLE. Un pool PumpSwap issu d une migration pump.fun porte, a l octet 245 de son
     compte (301 octets), un u64 de 17,5845 SOL. Les echanges se font au prix
     (SOL du coffre + 17,5845) / jetons, pas SOL du coffre / jetons. Mesure sur nos 239 achats et 239
     ventes : reserve implicite 17,94 / 17,27 SOL en mediane (l ecart = les frais). Les pools a 0 a cet
     octet echangent bien au prix du coffre (verifie). Le collecteur lisait donc un prix trop bas de
     17,6 / (q + 17,6) : -18 % sur un pool frais de 80 SOL, -1 % a 1 400 SOL.
  2. RETARD. Lecture sans `commitment` = « finalized » : 31 slots, 12,4 s derriere la chaine, mais
     horodatee a l heure de la lecture.

CE QUE FAIT CE SCRIPT. Pour nos tickets reels, trois rendements sur le meme jeton et la meme duree :
  BRUT      lectures telles quelles, entree a l age reel d achat, sortie apres la duree reelle ;
  CORRIGE   prix = (reserve_sol + V) / reserve_base, et lectures decalees de 12 s (la lecture
            etiquetee t montre l etat de t-12 s) ;
  REEL      gain lu sur le portefeuille.
Si CORRIGE ~ REEL a un cout fixe pres, le simulateur est enfin fiable.
"""
from __future__ import annotations

import json
import os
import sqlite3
import statistics as st
from collections import defaultdict

D = "/app/data/recherche"
RETARD_S = 12
V_PUMP = 17.5845


def charger():
    c = sqlite3.connect("file:%s?mode=ro" % os.path.join(D, "archive_solana.sqlite"), uri=True, timeout=60)
    V = json.load(open(os.path.join(D, "reserve_virtuelle.json")))
    chemins = defaultdict(list)
    for pair, ts, age, p, xb, xs in c.execute(
            "SELECT pair_id, ts, age_s, prix_sol, reserve_base, reserve_sol FROM solana_prix_chaine"
            " WHERE prix_sol > 0 ORDER BY pair_id, ts"):
        chemins[pair].append((ts, age, p, xb, xs))
    return c, V, chemins


def prix_corrige(V, pair, xb, xs):
    v = V.get(pair)
    if v is None or (v != 0 and abs(v - V_PUMP) > 0.001):
        return None                       # disposition inconnue : on ne devine pas
    return (xs + v) / xb if xb else None


def a_l_heure(chemin, t, tol=8):
    """La lecture la plus proche de l instant t."""
    best = min(chemin, key=lambda r: abs(r[0] - t), default=None)
    return best if best and abs(best[0] - t) <= tol else None


def main():
    c, V, chemins = charger()
    rows = []
    for mint, pair, te, ts_s, gain, mise, meth in c.execute(
            "SELECT mint, pair_id, ts_entree, ts_sortie, gain_eur, mise_eur, methode FROM tg_lignes"
            " WHERE mode='live' AND gain_eur IS NOT NULL AND methode IN ('propre','telegram')"):
        ch = chemins.get(pair)
        if not ch:
            continue
        e_b, s_b = a_l_heure(ch, te), a_l_heure(ch, ts_s)
        e_c, s_c = a_l_heure(ch, te + RETARD_S), a_l_heure(ch, ts_s + RETARD_S)
        if not (e_b and s_b and e_c and s_c):
            continue
        pe, ps = prix_corrige(V, pair, e_c[3], e_c[4]), prix_corrige(V, pair, s_c[3], s_c[4])
        if not pe or not ps:
            continue
        rows.append({"meth": meth, "reel": gain / mise, "brut": s_b[2] / e_b[2] - 1, "corrige": ps / pe - 1})
    print("tickets reels comparables : %d" % len(rows))
    for m in ("propre", "telegram", None):
        v = [r for r in rows if m is None or r["meth"] == m]
        if not v:
            continue
        brut, cor, reel = (st.mean(r[k] for r in v) for k in ("brut", "corrige", "reel"))
        print("\n%s (%d tickets)" % ((m or "TOUS").upper(), len(v)))
        print("   simulation BRUTE    %+.4f par euro   ecart au reel %+.4f" % (brut, reel - brut))
        print("   simulation CORRIGEE %+.4f par euro   ecart au reel %+.4f" % (cor, reel - cor))
        print("   REEL                %+.4f par euro" % reel)
        dif = sorted(r["reel"] - r["corrige"] for r in v)
        print("   ecart reel - corrige, ticket par ticket : mediane %+.4f · p25 %+.4f · p75 %+.4f"
              % (st.median(dif), dif[len(dif) // 4], dif[3 * len(dif) // 4]))


if __name__ == "__main__":
    main()
