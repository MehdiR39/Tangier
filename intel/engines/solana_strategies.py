"""Faire tourner PLUSIEURS strategies en parallele, en argent fictif, sur le meme flux.

Reproche de l operateur le 09/09, et il est juste : « pour gagner avec les memecoins il faut des
strategies multiples qui tournent en continu ». J ai passe une semaine a regler UNE regle -- entrer a
T+2 minutes, sortir a x1,5 ou T+15 -- en payant chaque hypothese en tickets reels, a raison d une
mesure par heure. C est lent, c est cher, et ca ne repond qu a une question a la fois.

Ce module fait l inverse. Chaque strategie est une entree et une sortie, decrites en donnees. A
chaque cycle, tout ce que le moteur a juge et dont on a la courbe est passe dans TOUTES les
strategies, et le resultat de chacune est ecrit dans `sol_strat_resultat`. Rien n est achete : le
carnet reel ne bouge pas.

Ce que ca change concretement :
  - dix hypotheses coutent le meme temps qu une, et zero euro ;
  - une strategie se juge sur son propre historique, pas sur une intuition ;
  - promouvoir une strategie en reel devient une decision chiffree, pas un pari.

Precautions reprises de tout ce qui a ete appris cette semaine, et sans lesquelles les chiffres
mentent :
  - une sortie n est validee que par DEUX releves consecutifs (§3.54 : 7 % des ecarts de prix
    depassent 20 %, et un pic isole cree un gain qui n a jamais existe) ;
  - le peage d aller-retour de 2 % est deduit de chaque ligne (§3.52 : il est fixe et ne depend pas
    de la taille) ;
  - l entree se fait au premier releve a T+2 ou apres, l instant ou le carnet reel achete vraiment,
    et jamais a T+1 ou le rejeu achete un prix qu on ne paie pas (§3.29).
"""
from __future__ import annotations

import logging
from typing import Any

from intel.context import IntelContext
from intel.utils.timeutil import now_ts

log = logging.getLogger(__name__)

TICKET = 20.0
PEAGE = 0.98          # aller-retour mesure a 2 % (§3.52)

# Chaque strategie : un nom, un filtre d entree sur ce qu on sait au jugement, et une sortie.
# Les filtres sont des bornes, pas du code : une strategie doit pouvoir etre lue et discutee.
STRATEGIES: list[dict[str, Any]] = [
    # --- la regle en production, pour reference ---
    {"nom": "prod_t30", "acheteurs": 75, "trades_max": 600, "cap": (25_000, 50_000),
     "tp": 1.5, "stop": 0.7, "hold": 30},
    {"nom": "prod_t15", "acheteurs": 75, "trades_max": 600, "cap": (25_000, 50_000),
     "tp": 1.5, "stop": 0.7, "hold": 15},
    # --- ouvrir la capitalisation, que le balayage designe sans trancher ---
    {"nom": "cap_large", "acheteurs": 75, "trades_max": 600, "cap": (25_000, 500_000),
     "tp": 1.5, "stop": 0.7, "hold": 30},
    {"nom": "cap_toute", "acheteurs": 75, "trades_max": 600, "cap": (0, 10 ** 12),
     "tp": 1.5, "stop": 0.7, "hold": 30},
    # --- la foule, dans les deux sens ---
    {"nom": "foule_forte", "acheteurs": 150, "trades_max": 600, "cap": (25_000, 500_000),
     "tp": 1.5, "stop": 0.7, "hold": 30},
    {"nom": "sans_plancher", "acheteurs": 0, "trades_max": 600, "cap": (25_000, 500_000),
     "tp": 1.5, "stop": 0.7, "hold": 30},
    # --- sorties : objectif haut, stop serre, stop large ---
    {"nom": "objectif_x2", "acheteurs": 75, "trades_max": 600, "cap": (25_000, 500_000),
     "tp": 2.0, "stop": 0.7, "hold": 30},
    {"nom": "stop_serre", "acheteurs": 75, "trades_max": 600, "cap": (25_000, 500_000),
     "tp": 1.5, "stop": 0.85, "hold": 30},
    {"nom": "sans_stop", "acheteurs": 75, "trades_max": 600, "cap": (25_000, 500_000),
     "tp": 1.5, "stop": 0.0, "hold": 30},
    # --- la duree, le seul parametre coherent a ce jour (§3.56) ---
    {"nom": "long_t60", "acheteurs": 75, "trades_max": 600, "cap": (25_000, 500_000),
     "tp": 1.5, "stop": 0.7, "hold": 60},
    {"nom": "court_t5", "acheteurs": 75, "trades_max": 600, "cap": (25_000, 500_000),
     "tp": 1.3, "stop": 0.8, "hold": 5},
    # --- ANALYSE TECHNIQUE, dans les limites de ce qu on peut lire a T+2 minutes ---
    # A l entree on n a que deux points de prix derriere soi : moyennes mobiles, RSI et figures
    # sont hors de portee, ils demandent des dizaines de bougies. Restent deux mesures reelles,
    # collectees et jamais utilisees : la VITESSE (variation du prix sur cinq minutes, chg_m5)
    # et l ACCELERATION DE LA FOULE (acheteurs a 60 s rapportes aux acheteurs a 30 s).
    # Premiere lecture du 09/09 : les lancements deja en hausse de plus de 100 % gagnent 70 % du
    # temps contre 31 % pour les autres -- sur 43 pools, donc a confirmer, mais c est la seule
    # variable qui separait quoi que ce soit.
    {"nom": "ta_momentum", "acheteurs": 75, "trades_max": 600, "cap": (25_000, 500_000),
     "chg_min": 100, "tp": 1.5, "stop": 0.7, "hold": 30},
    {"nom": "ta_calme", "acheteurs": 75, "trades_max": 600, "cap": (25_000, 500_000),
     "chg_max": 25, "tp": 1.5, "stop": 0.7, "hold": 30},
    {"nom": "ta_chute", "acheteurs": 75, "trades_max": 600, "cap": (25_000, 500_000),
     "chg_max": -10, "tp": 1.5, "stop": 0.7, "hold": 30},
    # L accelaration : une foule qui double entre 30 et 60 secondes n est pas la meme qu une foule
    # deja constituee a 30 s et qui stagne. Le rapport separe un elan d un bundle qui s essouffle.
    {"nom": "ta_accel", "acheteurs": 75, "trades_max": 600, "cap": (25_000, 500_000),
     "accel_min": 2.0, "tp": 1.5, "stop": 0.7, "hold": 30},
    {"nom": "ta_accel_fort", "acheteurs": 75, "trades_max": 600, "cap": (25_000, 500_000),
     "accel_min": 3.0, "tp": 1.5, "stop": 0.7, "hold": 30},
    # --- la densite, dans l autre sens : acheter ce que la regle ecarte ---
    {"nom": "dense", "acheteurs": 75, "trades_min": 600, "trades_max": 10 ** 9,
     "cap": (25_000, 500_000), "tp": 1.5, "stop": 0.7, "hold": 30},
]


def _sortie(pts: list[tuple[float, float]], tp: float, stop: float, hold: float) -> float | None:
    """Multiple obtenu, sorties confirmees par deux releves consecutifs."""
    ent = [(a, p) for a, p in pts if a >= 2]
    if not ent:
        return None
    a0, px0 = ent[0]
    fen = [(a, p / px0) for a, p in pts if a0 < a <= a0 + hold]
    for i, (_a, m) in enumerate(fen):
        suiv = fen[i + 1][1] if i + 1 < len(fen) else None
        if stop and m <= stop and suiv is not None and suiv <= stop:
            return stop
        if tp and m >= tp and suiv is not None and suiv >= tp:
            return tp
    return fen[-1][1] if fen else None


def _passe(s: dict[str, Any], j: dict[str, Any]) -> bool:
    cap = j.get("market_cap") or 0
    lo, hi = s["cap"]
    chg = j.get("chg_m5")
    accel = j.get("accel")
    if "chg_min" in s and (chg is None or chg < s["chg_min"]):
        return False
    if "chg_max" in s and (chg is None or chg > s["chg_max"]):
        return False
    if "accel_min" in s and (accel is None or accel < s["accel_min"]):
        return False
    return (int(j.get("payers") or 0) >= int(s.get("acheteurs", 0))
            and int(j.get("trades") or 0) < int(s.get("trades_max", 10 ** 9))
            and int(j.get("trades") or 0) >= int(s.get("trades_min", 0))
            and (not lo or cap >= lo) and cap < hi)


def evaluer(ctx: IntelContext, fenetre_h: int = 48) -> dict[str, Any]:
    """Passer chaque lancement juge dans toutes les strategies. Aucun achat."""
    db = ctx.db
    try:
        db.execute("CREATE TABLE IF NOT EXISTS sol_strat_resultat("
                   "  strategie TEXT NOT NULL, pair_id TEXT NOT NULL, ts INTEGER,"
                   "  multiple REAL, net_eur REAL, PRIMARY KEY (strategie, pair_id))")
    except Exception as exc:  # noqa: BLE001
        log.info("strategies : table indisponible (%s)", str(exc)[:80])
        return {"status": "erreur"}

    depuis = now_ts() - fenetre_h * 3600
    courbes: dict[str, list[tuple[float, float]]] = {}
    for r in db.query("SELECT pair_id, age_min, price_usd FROM solana_suivi "
                      "WHERE price_usd > 0 AND ts > ? ORDER BY pair_id, age_min", (depuis,)):
        courbes.setdefault(r["pair_id"], []).append((float(r["age_min"] or 0), float(r["price_usd"])))

    juges = {}
    for r in db.query(
            "SELECT j.pair_id, j.ts, j.payers, j.trades, j.market_cap, j.chg_m5, j.liquidity_usd,"
            " j.age_s, o.trades_30s, o.uniq_payers_30s FROM solana_judgements j"
            " LEFT JOIN solana_observations o ON o.pair_id=j.pair_id WHERE j.ts > ?", (depuis,)):
        d = dict(r)
        p30 = d.get("uniq_payers_30s") or 0
        d["accel"] = (float(d.get("payers") or 0) / p30) if p30 else None
        juges[d["pair_id"]] = d

    ecrits = 0
    for s in STRATEGIES:
        deja = {r["pair_id"] for r in db.query(
            "SELECT pair_id FROM sol_strat_resultat WHERE strategie=?", (s["nom"],))}
        for pid, pts in courbes.items():
            if pid in deja or len(pts) < 6:
                continue
            j = juges.get(pid)
            if not j or not _passe(s, j):
                continue
            m = _sortie(sorted(pts), s["tp"], s["stop"], s["hold"])
            if m is None:
                continue
            try:
                db.execute("INSERT OR IGNORE INTO sol_strat_resultat VALUES(?,?,?,?,?)",
                           (s["nom"], pid, int(j["ts"]), m, (m * PEAGE - 1) * TICKET))
                ecrits += 1
            except Exception:  # noqa: BLE001
                pass
    return {"status": "ok", "strategies": len(STRATEGIES), "lignes": ecrits}


def classement(ctx: IntelContext) -> list[dict[str, Any]]:
    """Le tableau qui decide : chaque strategie, son resultat, et sa moitie hors echantillon."""
    out = []
    for s in STRATEGIES:
        lignes = [dict(r) for r in ctx.db.query(
            "SELECT ts, net_eur FROM sol_strat_resultat WHERE strategie=? ORDER BY ts", (s["nom"],))]
        if len(lignes) < 8:
            out.append({"nom": s["nom"], "n": len(lignes)})
            continue
        v = [x["net_eur"] for x in lignes]
        h = len(v) // 2
        tri = sorted(v, reverse=True)
        coupe = max(1, len(tri) // 10)
        out.append({"nom": s["nom"], "n": len(v), "net": sum(v) / len(v),
                    "moitie1": sum(v[:h]) / max(h, 1), "moitie2": sum(v[h:]) / max(len(v) - h, 1),
                    "robuste": sum(tri[coupe:]) / max(len(tri) - coupe, 1),
                    "gagnants": sum(1 for x in v if x > 0) / len(v)})
    return sorted(out, key=lambda x: x.get("robuste", -99), reverse=True)
