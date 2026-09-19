"""LA RESERVE VIRTUELLE EST-ELLE VRAIMENT 17,5845 SOL ? Resolue sur nos propres echanges.

LE DOUTE. `cout_glissement.py` mesure un taux effectif de 2,09 % a l achat, et ce taux CORRELE a
-0,79 avec la taille du pool : petit pool, taux eleve. Une commission ne fait jamais ca -- elle est
la meme quelle que soit la taille. Ce qui varie avec la taille, c est l IMPACT. Or la formule du
produit constant est censee deja l inclure... sauf si la constante qu elle utilise est fausse.

CE QUI EST EN JEU, et ce n est pas un detail. Tout le projet lit le prix comme
    prix = (coffre_SOL + V) / coffre_jetons,   V = 17,5845
Si V est faux, `brut_240` est faux, donc « le marche donne +2,68 % » est faux, donc le cout mesure
comme (brut - reel) l est aussi. On aurait passe la journee a comparer des strategies sur une regle
graduee de travers.

COMMENT ON TRANCHE, sans rien supposer. Chaque ticket donne DEUX echanges sur le MEME pool, avec les
reserves exactes lues dans la transaction elle-meme (`preTokenBalances`). Deux equations, deux
inconnues -- f la commission, V la reserve :
    achat   jetons = R_j . d_sol(1-f) / (R_s + V + d_sol(1-f))
    vente   sol    = (R_s' + V) . d_jet(1-f) / (R_j' + d_jet(1-f))
On resout par bissection sur V, ticket par ticket. Si V ressort proche de 17,58 partout, la
constante est bonne et le taux d achat eleve vient d ailleurs. Si V ressort tres different, c est
elle le probleme, et une part de ce qu on appelle « cout » n a jamais existe.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time

import numpy as np

WSOL = "So11111111111111111111111111111111111111112"
V_SUPPOSEE = 17.5845
SORTIE = "/app/data/cout_reserve.json"


def rpc(corps):
    import urllib.request
    req = urllib.request.Request(os.environ["SOLANA_RPC_URL"], data=json.dumps(corps).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.load(r).get("result")


def reserves(sig, pair, mint):
    """(SOL, jetons) du pool AVANT l echange, lus dans la transaction."""
    r = rpc({"jsonrpc": "2.0", "id": 1, "method": "getTransaction",
             "params": [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 1}]})
    if not r or not r.get("meta"):
        return None
    sol = jet = None
    for b in r["meta"].get("preTokenBalances") or []:
        if b.get("owner") != pair:
            continue
        q = b.get("uiTokenAmount", {}).get("uiAmount")
        if b.get("mint") == WSOL:
            sol = float(q or 0)
        elif b.get("mint") == mint:
            jet = float(q or 0)
    return (sol, jet) if sol is not None and jet is not None else None


def resoudre(Rs_a, Rj_a, dsol, jetons, Rs_v, Rj_v, djet, sol):
    """(f, V) tels que les DEUX jambes s expliquent par le meme couple."""
    def f_achat(V):
        den = Rj_a - jetons
        if den <= 0:
            return None
        return 1.0 - (jetons * (Rs_a + V) / den) / dsol

    def f_vente(V):
        den = (Rs_v + V) - sol
        if den <= 0:
            return None
        return 1.0 - (sol * Rj_v / den) / djet

    def ecart(V):
        a, b = f_achat(V), f_vente(V)
        return None if a is None or b is None else a - b

    lo, hi = 0.01, 20000.0
    el, eh = ecart(lo), ecart(hi)
    if el is None or eh is None or el * eh > 0:
        return None, None
    for _ in range(300):
        mid = (lo + hi) / 2
        em = ecart(mid)
        if em is None:
            return None, None
        if el * em <= 0:
            hi, eh = mid, em
        else:
            lo, el = mid, em
    V = (lo + hi) / 2
    return f_achat(V), V


def main() -> None:
    tx = json.load(open("/app/data/recherche/tx_reelles.json", encoding="utf-8"))
    ci = sqlite3.connect("file:/app/db/intel.sqlite?mode=ro", uri=True, timeout=30)
    sigs = {p: (a, v) for p, a, v in ci.execute(
        "SELECT pair, tx_achat, tx_vente FROM mr_lignes WHERE mode='live'"
        " AND tx_achat IS NOT NULL AND tx_vente IS NOT NULL")}
    ci.close()

    out = []
    for t in tx:
        mint, pair = t[0], t[1]
        if pair not in sigs:
            continue
        sa, sv = sigs[pair]
        jetons_a, sol_a = float(t[7][0]), -float(t[7][1])
        jetons_v, sol_v = -float(t[8][0]), float(t[8][1])
        try:
            Ra, Rv = reserves(sa, pair, mint), reserves(sv, pair, mint)
        except Exception:  # noqa: BLE001
            continue
        if not Ra or not Rv:
            continue
        f, V = resoudre(Ra[0], Ra[1], sol_a, jetons_a, Rv[0], Rv[1], jetons_v, sol_v)
        if f is None:
            continue
        out.append({"pair": pair, "f": round(100 * f, 4), "V": round(V, 3),
                    "R_sol": Ra[0], "R_jet": Ra[1], "sol_achat": sol_a,
                    "part": round(100 * sol_a / (Ra[0] + V_SUPPOSEE), 3)})
        time.sleep(0.12)

    if not out:
        print("cout_reserve: rien a resoudre")
        return
    json.dump({"genere": time.time(), "n": len(out), "lignes": out}, open(SORTIE, "w"))
    V = np.array([x["V"] for x in out])
    f = np.array([x["f"] for x in out])
    bons = (f > 0) & (f < 10)
    print("RESOLU SUR %d TICKETS (deux jambes, deux inconnues)" % len(out))
    print()
    q = np.percentile(V[bons], [10, 25, 50, 75, 90])
    print("RESERVE VIRTUELLE V, resolue :")
    print("   supposee par le projet : %.4f SOL" % V_SUPPOSEE)
    print("   mediane resolue        : %.3f SOL" % np.median(V[bons]))
    print("   quartiles              : %.3f / %.3f" % (q[1], q[3]))
    print("   deciles                : %.3f / %.3f" % (q[0], q[4]))
    print()
    qf = np.percentile(f[bons], [25, 50, 75])
    print("COMMISSION f, resolue en meme temps :")
    print("   mediane %.3f %% · quartiles %.3f / %.3f" % (qf[1], qf[0], qf[2]))
    print()
    proche = np.abs(V[bons] - V_SUPPOSEE) / V_SUPPOSEE < 0.25
    print("   V a moins de 25 %% de 17,58 : %.0f %% des tickets" % (100 * proche.mean()))
    print()
    if np.median(V[bons]) > 2 * V_SUPPOSEE:
        print("   -> LA CONSTANTE EST FAUSSE. Le prix, donc `brut_240`, donc le cout mesure")
        print("      comme (brut - reel), reposent tous sur une reserve sous-estimee.")
    elif np.median(V[bons]) < V_SUPPOSEE / 2:
        print("   -> la constante est SUR-estimee.")
    else:
        print("   -> la constante tient. Le taux d achat eleve vient d ailleurs.")


if __name__ == "__main__":
    main()
