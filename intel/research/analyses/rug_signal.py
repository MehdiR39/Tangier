"""Le retrait de liquidite se voit-il venir dans les echanges qui le precedent ?

81 % des pools qui passent la barre T+1 voient leur liquidite retiree une seconde apres leur
dernier echange (§3.4 du journal). Quand c est fait, il ne reste aucune contrepartie a aucun prix :
IRREGULARHEADS a monte de 283 %, puis le PoolManager s est vide, et nos 574 000 milliards de jetons
n ont plus d acheteur. Vingt-neuf tentatives de vente, toutes refusees.

Aucun filtre d entree ne protege de ca -- le pool est sain quand on achete, le retrait vient apres.
La seule defense est de sortir avant. La question est donc : les dernieres secondes avant un retrait
ressemblent-elles a quelque chose ?

On ne regarde QUE des donnees confirmees. Il ne s agit pas de courir apres une transaction en
attente pour la doubler : ce serait un autre metier, avec ses propres risques, et ce n est pas ce
qu on construit ici. Il s agit de reconnaitre un motif dans ce que la chaine a deja publie.

Trois signatures testees sur la derniere minute avant le dernier echange :
  1. la part des ventes monte-t-elle ?
  2. le rythme des echanges s effondre-t-il, ou s emballe-t-il ?
  3. un gros porteur sort-il avant les autres ?
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
from typing import Any

BPM = 600          # blocs par minute
POOL_MANAGER = "0x8366a39cc670b4001a1121b8f6a443a643e40951"


def charge(db: str, limite: int) -> list[dict[str, Any]]:
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    retenus = []
    for r in c.execute("SELECT pair_id, feat_json FROM rp_snap WHERE t_min=1"):
        n = (json.loads(r["feat_json"] or "{}").get("trades_5m") or 0)
        if 27 <= n <= 60:
            retenus.append(r["pair_id"])
        if len(retenus) >= limite:
            break

    out = []
    for pid in retenus:
        pool = c.execute("SELECT * FROM rp_pool WHERE pair_id=?", (pid,)).fetchone()
        if pool is None or not pool["token_address"]:
            continue
        sw = c.execute("SELECT block, amount0, amount1 FROM rp_swap WHERE pair_id=? ORDER BY block, log_index",
                       (pid,)).fetchall()
        if len(sw) < 12:
            continue
        c0 = bool(pool["is_c0"])
        dernier = sw[-1]["block"]
        # Retrait : des jetons quittent le PoolManager APRES le dernier echange.
        pull = c.execute("SELECT MIN(block) b FROM rp_transfer WHERE token_address=? AND lower(from_address)=? "
                         "AND block>?", (pool["token_address"], POOL_MANAGER, dernier)).fetchone()["b"]
        # v4 rend les deltas du cote de l appelant : jeton positif = achat.
        def cote(s: sqlite3.Row) -> int:
            return int(s["amount0"] if c0 else s["amount1"])

        derniere_min = [s for s in sw if s["block"] > dernier - BPM]
        avant = [s for s in sw if dernier - 2 * BPM < s["block"] <= dernier - BPM]
        if len(derniere_min) < 4 or len(avant) < 4:
            continue
        part_v = sum(1 for s in derniere_min if cote(s) < 0) / len(derniere_min)
        part_v_avant = sum(1 for s in avant if cote(s) < 0) / len(avant)
        out.append({
            "pid": pid, "retire": pull is not None,
            "part_ventes": part_v, "part_ventes_avant": part_v_avant,
            "hausse_ventes": part_v - part_v_avant,
            "rythme": len(derniere_min) / max(len(avant), 1),
            "grosse_vente": max((abs(cote(s)) for s in derniere_min if cote(s) < 0), default=0)
                            / max(statistics.median([abs(cote(s)) for s in derniere_min]) or 1, 1),
        })
    return out


def bande(rows: list[dict[str, Any]], cle: str, cuts: tuple[float, ...], titre: str) -> None:
    print(f"\n  {titre}")
    print(f"    {'bande':>18}{'n':>6}{'retires ensuite':>18}")
    edges = [(-1e9, cuts[0])] + [(cuts[i], cuts[i + 1]) for i in range(len(cuts) - 1)] + [(cuts[-1], 1e9)]
    for lo, hi in edges:
        g = [r for r in rows if lo < r[cle] <= hi]
        if len(g) < 8:
            continue
        lab = f"<= {hi:g}" if lo < -1e8 else (f"> {lo:g}" if hi > 1e8 else f"{lo:g} a {hi:g}")
        print(f"    {lab:>18}{len(g):>6}{sum(1 for r in g if r['retire']) / len(g):>17.0%}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="/app/data/research.sqlite")
    ap.add_argument("--limit", type=int, default=500)
    args = ap.parse_args()
    rows = charge(args.db, args.limit)
    if len(rows) < 20:
        print(f"  seulement {len(rows)} pools exploitables : echantillon trop mince")
        return
    base = sum(1 for r in rows if r["retire"]) / len(rows)
    print(f"  {len(rows)} pools passant la barre · {base:.0%} voient leur liquidite retiree ensuite")
    print("  (c est le taux de base : un signal utile doit s en ecarter nettement)")
    bande(rows, "part_ventes", (0.3, 0.5, 0.7), "part des ventes dans la derniere minute")
    bande(rows, "hausse_ventes", (-0.1, 0.1, 0.3), "hausse de la part des ventes par rapport a la minute d avant")
    bande(rows, "rythme", (0.5, 1.0, 2.0), "rythme des echanges, derniere minute contre la precedente")
    bande(rows, "grosse_vente", (3, 10, 30), "plus grosse vente rapportee a la vente mediane")


if __name__ == "__main__":
    main()
