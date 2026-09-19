"""D OU VIENNENT LES 2,38 POINTS « INEXPLIQUES » ? Le taux reellement preleve, jambe par jambe.

MIDO, 19/09 : « on ne gagne pas parce que les couts bouffent tout ? » -- oui, et la mesure le dit :
le marche donne +2,68 % par ticket, l execution en prend 3,71 %. Le point d equilibre est a 2,68 %.
Il manque UN point. Et les deux tiers du cout (2,38 pt) sont un poste qu on n a jamais ouvert.

L HYPOTHESE A TESTER. Ma formule compte la commission du pool a 0,25 % par jambe. On avait mesure
0,94 %/jambe de perte contre la formule du produit constant (§ memoire). Si 0,94 est le vrai taux,
il explique 1,4 point des 2,38 -- et ce ne serait pas « inexplique » mais du GLISSEMENT, qui se
reduit (taille d ordre, moment d envoi, decoupage).

COMMENT ON MESURE, sans supposer quoi que ce soit. Une transaction Solana porte les soldes des
comptes AVANT et APRES (`preTokenBalances` / `postTokenBalances`, `preBalances` / `postBalances`).
On lit donc les reserves du pool a l instant exact de NOTRE echange, et on resout :

    achat   jetons_recus = R_jetons . dSOL(1-f) / (R_sol + V + dSOL(1-f))
    vente   sol_recu     = (R_sol + V) . dJetons(1-f) / (R_jetons + dJetons(1-f))

`f` est alors le taux EFFECTIF de la jambe : commission du pool plus tout ce qui s y ajoute. Il
contient l impact de notre propre ordre ? NON : la formule du produit constant l inclut deja, c est
justement ce qu elle calcule. Donc `f` est ce qui reste APRES l impact -- la vraie commission, plus
l eventuel glissement si la reserve a bouge entre la lecture et l execution.

CE QUE LE RESULTAT DECIDERA :
  f ~ 0,25 % des deux cotes  -> le pool prend ce qu il annonce, l inexplique est ailleurs
  f nettement au-dessus      -> on sait ou part l argent, et de combien
  f asymetrique achat/vente  -> le probleme est d un cote, et on sait lequel corriger
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time

import numpy as np

INTEL = os.environ.get("INTEL_DB", "/app/db/intel.sqlite")
SORTIE = "/app/data/cout_glissement.json"
V_RESERVE = 17.5845
WSOL = "So11111111111111111111111111111111111111112"


def rpc(corps):
    import urllib.request
    req = urllib.request.Request(os.environ["SOLANA_RPC_URL"], data=json.dumps(corps).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.load(r).get("result")


def etat(sig, pair, mint):
    """Les reserves du pool AVANT et APRES notre echange, lues dans la transaction elle-meme.

    Le pool detient deux comptes-jetons : un de WSOL et un du jeton. On les reconnait par leur
    proprietaire (`owner` = l adresse du pool) et leur mint. `preTokenBalances` donne l etat avant.
    """
    r = rpc({"jsonrpc": "2.0", "id": 1, "method": "getTransaction",
             "params": [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 1}]})
    if not r or not r.get("meta"):
        return None
    m = r["meta"]
    out = {"frais": m["fee"] / 1e9}
    for cle, champ in (("avant", "preTokenBalances"), ("apres", "postTokenBalances")):
        sol = jet = None
        for b in m.get(champ) or []:
            if b.get("owner") != pair:
                continue
            q = b.get("uiTokenAmount", {}).get("uiAmount")
            if b.get("mint") == WSOL:
                sol = float(q or 0)
            elif b.get("mint") == mint:
                jet = float(q or 0)
        if sol is None or jet is None:
            return None
        out[cle] = (sol, jet)
    return out


def taux_achat(R_sol, R_jet, d_sol, jetons_recus):
    """Le taux effectif `f` tel que la formule du produit constant rende `jetons_recus`."""
    if d_sol <= 0 or jetons_recus <= 0:
        return None
    # jetons = R_jet . x / (R_sol + V + x) avec x = d_sol (1-f)  ->  on isole x puis f
    x = jetons_recus * (R_sol + V_RESERVE) / (R_jet - jetons_recus)
    return 1.0 - x / d_sol


def taux_vente(R_sol, R_jet, d_jet, sol_recu):
    if d_jet <= 0 or sol_recu <= 0:
        return None
    x = sol_recu * R_jet / ((R_sol + V_RESERVE) - sol_recu)
    return 1.0 - x / d_jet


def main() -> None:
    tx = json.load(open("/app/data/recherche/tx_reelles.json", encoding="utf-8"))
    ci = sqlite3.connect("file:%s?mode=ro" % INTEL, uri=True, timeout=30)
    sigs = {p: (a, v) for p, a, v in ci.execute(
        "SELECT pair, tx_achat, tx_vente FROM mr_lignes WHERE mode='live'"
        " AND tx_achat IS NOT NULL AND tx_vente IS NOT NULL")}
    ci.close()

    lignes = []
    for t in tx:
        mint, pair = t[0], t[1]
        if pair not in sigs:
            continue
        sa, sv = sigs[pair]
        jetons_a, sol_a = float(t[7][0]), -float(t[7][1])          # achat : + jetons, - SOL
        jetons_v, sol_v = -float(t[8][0]), float(t[8][1])          # vente : - jetons, + SOL
        try:
            ea, ev = etat(sa, pair, mint), etat(sv, pair, mint)
        except Exception:  # noqa: BLE001
            continue
        if not ea or not ev:
            continue
        fa = taux_achat(ea["avant"][0], ea["avant"][1], sol_a, jetons_a)
        fv = taux_vente(ev["avant"][0], ev["avant"][1], jetons_v, sol_v)
        if fa is None or fv is None:
            continue
        lignes.append({"pair": pair, "t": t[3], "mise": t[5], "gain": t[6],
                       "f_achat": round(100 * fa, 4), "f_vente": round(100 * fv, 4),
                       "sol_achat": sol_a, "sol_vente": sol_v,
                       "R_sol_achat": ea["avant"][0], "R_sol_vente": ev["avant"][0],
                       "part_pool_achat": round(100 * sol_a / (ea["avant"][0] + V_RESERVE), 3)})
        time.sleep(0.12)

    if not lignes:
        print("cout_glissement: aucune transaction exploitable")
        return
    a = np.array([x["f_achat"] for x in lignes])
    v = np.array([x["f_vente"] for x in lignes])
    json.dump({"genere": time.time(), "n": len(lignes), "lignes": lignes},
              open(SORTIE, "w"), ensure_ascii=False)

    def bloc(nom, x):
        q = np.percentile(x, [10, 25, 50, 75, 90])
        print("   %-8s n=%3d · moyenne %6.3f %% · mediane %6.3f %% · quartiles %6.3f / %6.3f"
              % (nom, len(x), x.mean(), np.median(x), q[1], q[3]))

    print("TAUX EFFECTIF PRELEVE PAR JAMBE, contre la formule du produit constant")
    print("   (la commission annoncee du pool est de 0,25 %% par jambe)")
    print()
    bloc("ACHAT", a)
    bloc("VENTE", v)
    bloc("ALLER-RETOUR", a + v)
    print()
    print("   au-dessus de 0,25 %% : achat %.0f %% des tickets · vente %.0f %%"
          % (100 * (a > 0.25).mean(), 100 * (v > 0.25).mean()))
    print()
    print("CE QUE CA REPRESENTE SUR LE COUT TOTAL")
    print("   ma formule compte      0,500 pt (2 x 0,25 %%)")
    print("   la mesure dit          %.3f pt" % (a + v).mean())
    print("   -> ecart               %+.3f pt, a retirer de l inexplique (2,38 pt)"
          % ((a + v).mean() - 0.5))


if __name__ == "__main__":
    main()
