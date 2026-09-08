"""Rejoue toutes les variantes de la regle T+1 sur les mêmes lancements, hors ligne.

Le 08/09/2026 le seuil Solana a ete change trois fois en trois heures, chaque fois sur un
echantillon trop petit, et chaque changement a remis le compteur d experience a zero. C est de
l ajustement au bruit, en production, avec de l argent reel. Cet outil existe pour que ca ne se
reproduise pas : il compare vingt variantes sur les memes pools, sans engager un euro, pendant que
la regle reelle ne bouge plus.

Il ne lit que ce que le moteur a deja observe -- `t1_observations` pour les pools juges,
`swap_events` pour ce qu ils sont devenus -- donc il ne touche ni au chemin d execution ni au
reseau.

LE POINT QUI DECIDE DE TOUT : un pool qui s arrete est une perte SECHE, pas une sortie au dernier
prix. Mesure du 08/09 sur seize lignes reelles : les lignes invendables font une mediane de 12
echanges apres notre achat, les lignes vendues 296. Un simulateur qui suppose qu on revend toujours
au dernier prix affiche 82 % de gagnants la ou le carnet reel perdait avec 46 % d invendables.
Ici, sous `min_trades_apres`, la mise entiere est perdue.
"""
from __future__ import annotations

import argparse
import sqlite3
import statistics
from dataclasses import dataclass
from typing import Any

BLOCKS_PER_MIN = 600
TICKET = 5.0
GAS = 0.02
FRAIS_PCT = 0.30          # par sens


@dataclass(frozen=True)
class Variante:
    nom: str
    min_m1: int = 27
    max_m1: int = 60
    min_m2: int = 0            # confirmation en deuxieme minute ; 0 = pas de confirmation
    tp: float = 2.0            # objectif de sortie ; 0 = vendre a la fin de la fenetre
    fenetre_min: float = 5.0
    entree_min: float = 1.0    # a quelle minute on achete


def price_from_sqrt(sqrt_x96: int, token_is_c0: bool) -> float:
    if sqrt_x96 <= 0:
        return 0.0
    p = (sqrt_x96 / (2 ** 96)) ** 2         # currency1 par currency0
    return p if token_is_c0 else (1.0 / p if p else 0.0)


def charge(db: str, chain_id: int, limite: int) -> list[dict[str, Any]]:
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    pools = c.execute(
        "SELECT o.pool_id, o.token_address, o.first_swap_block, o.swaps_first_minute, p.token_is_currency0 "
        "FROM t1_observations o JOIN pairs p ON p.chain_id=o.chain_id AND p.pair_id=o.pool_id "
        "WHERE o.chain_id=? AND o.first_swap_block IS NOT NULL LIMIT ?", (chain_id, limite)).fetchall()
    out = []
    for p in pools:
        sw = c.execute(
            "SELECT block_number, sqrt_price_x96 FROM swap_events WHERE chain_id=? AND pair_id=? "
            "ORDER BY block_number, log_index", (chain_id, p["pool_id"])).fetchall()
        if len(sw) < 10:
            continue
        b0 = int(p["first_swap_block"])
        c0 = bool(p["token_is_currency0"])
        chemin = [((int(s["block_number"]) - b0) / BLOCKS_PER_MIN,
                   price_from_sqrt(int(s["sqrt_price_x96"] or 0), c0)) for s in sw]
        chemin = [(t, px) for t, px in chemin if px > 0]
        if len(chemin) < 5:
            continue
        m1 = int(p["swaps_first_minute"] or 0)
        m2 = sum(1 for t, _ in chemin if 1.0 < t <= 2.0)
        out.append({"pool": p["pool_id"], "m1": m1, "m2": m2, "chemin": chemin,
                    "n_total": len(chemin)})
    return out


def resultat(r: dict[str, Any], v: Variante, min_trades_apres: int) -> float:
    """Euros nets d un ticket sous cette variante. Un pool qui s arrete = mise perdue."""
    apres = [x for x in r["chemin"] if x[0] > v.entree_min]
    if not apres:
        return -TICKET - GAS
    if len(apres) < min_trades_apres:
        return -TICKET - GAS                       # personne pour racheter : sac mort
    px0 = apres[0][1]
    dedans = [x for x in apres if x[0] <= v.entree_min + v.fenetre_min]
    if not dedans:
        return -TICKET - GAS
    if px0 <= 0:
        return -TICKET - GAS
    mult = v.tp if (v.tp and any(px / px0 >= v.tp for _t, px in dedans)) else dedans[-1][1] / px0
    # Un prix d entree quasi nul produit des multiples absurdes -- la variante sans objectif a
    # affiche une moyenne a 1.45e52 avant ce plafond. Au-dela de x50 sur cinq minutes, c est du
    # bruit de precision, pas un gain qu on aurait encaisse.
    mult = min(mult, 50.0)
    return TICKET * mult * (1 - FRAIS_PCT / 100) ** 2 - TICKET - GAS


def evalue(rows: list[dict[str, Any]], v: Variante, min_trades_apres: int) -> dict[str, Any] | None:
    gardes = [r for r in rows
              if v.min_m1 <= r["m1"] and (not v.max_m1 or r["m1"] <= v.max_m1)
              and r["m2"] >= v.min_m2]
    if len(gardes) < 10:
        return None
    nets = [resultat(r, v, min_trades_apres) for r in gardes]
    morts = sum(1 for r in gardes if len([x for x in r["chemin"] if x[0] > v.entree_min]) < min_trades_apres)
    s = sorted(nets, reverse=True)
    k = max(1, int(len(s) * 0.9))
    return {"n": len(nets), "gagnants": sum(1 for x in nets if x > 0) / len(nets),
            "par_euro": sum(nets) / len(nets) / TICKET,
            "mediane": statistics.median(nets) / TICKET,
            "sans_haut": sum(s[len(s) - k:]) / k / TICKET,
            "morts": morts / len(gardes)}


VARIANTES = [
    Variante("27-60, achat a T+1 (regle actuelle)"),
    Variante("27-60, confirmation 10 en 2e min", min_m2=10, entree_min=2.0),
    Variante("27-60, confirmation 20 en 2e min", min_m2=20, entree_min=2.0),
    Variante("27-60, confirmation 30 en 2e min", min_m2=30, entree_min=2.0),
    Variante("27-60, confirmation 50 en 2e min", min_m2=50, entree_min=2.0),
    Variante("20-60, confirmation 30 en 2e min", min_m1=20, min_m2=30, entree_min=2.0),
    Variante("27-100, confirmation 30 en 2e min", max_m1=100, min_m2=30, entree_min=2.0),
    Variante("27 et plus, confirmation 30 en 2e min", max_m1=0, min_m2=30, entree_min=2.0),
    Variante("27-60, conf 30, sortie x1.5", min_m2=30, entree_min=2.0, tp=1.5),
    Variante("27-60, conf 30, sortie x3", min_m2=30, entree_min=2.0, tp=3.0),
    Variante("27-60, conf 30, vendre a T+5 sans objectif", min_m2=30, entree_min=2.0, tp=0.0),
    Variante("27-60, conf 30, fenetre 10 min", min_m2=30, entree_min=2.0, fenetre_min=10.0),
    Variante("27-60, conf 30, fenetre 3 min", min_m2=30, entree_min=2.0, fenetre_min=3.0),
]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="/app/db/intel.sqlite")
    ap.add_argument("--chain-id", type=int, default=4663)
    ap.add_argument("--limit", type=int, default=8000)
    ap.add_argument("--morts-sous", type=int, default=30,
                    help="moins de N echanges apres l entree = pool mort, mise perdue")
    args = ap.parse_args()

    rows = charge(args.db, args.chain_id, args.limit)
    if not rows:
        print("aucun pool exploitable")
        return
    print(f"  {len(rows)} pools observes en direct avec un chemin de prix exploitable")
    print(f"  un pool faisant moins de {args.morts_sous} echanges apres l entree compte "
          f"pour une mise entierement perdue\n")
    print(f"  {'variante':<40}{'n':>5}{'gagnants':>10}{'par euro':>11}"
          f"{'mediane':>10}{'sans 10% haut':>14}{'morts':>8}")
    for v in VARIANTES:
        r = evalue(rows, v, args.morts_sous)
        if r is None:
            print(f"  {v.nom:<40}    trop peu de lignes")
            continue
        print(f"  {v.nom:<40}{r['n']:>5}{r['gagnants']:>9.0%}{r['par_euro']:>+11.3f}"
              f"{r['mediane']:>+10.3f}{r['sans_haut']:>+14.3f}{r['morts']:>7.0%}")


if __name__ == "__main__":
    main()
