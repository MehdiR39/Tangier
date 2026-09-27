"""Le jeu d apprentissage, et le garde-fou qui empeche de s en servir trop tot.

Demande de l operateur le 09/09 : ajouter du ML. La reponse honnete tient en un chiffre -- on
dispose d environ 150 exemples etiquetes pour huit variables. Un modele apprendrait le bruit et
sortirait un score magnifique qui ne vaudrait rien, ce qui est EXACTEMENT l erreur commise quatre
fois a la main dans la meme journee : grosses capitalisations, stop suiveur, historique du createur,
plafond de capitalisation. Chaque fois un resultat spectaculaire, chaque fois un artefact.

Ce fichier fait donc deux choses, et refuse la troisieme :
  1. il construit le jeu -- une ligne par lancement juge, les variables connues AU MOMENT de la
     decision, et l etiquette calculee sur la courbe qui a suivi ;
  2. il dit combien d exemples on a et ce qui manque ;
  3. il n entraine rien tant que l echantillon est sous `--minimum` (mille par defaut).

Les variables sont volontairement celles qu on possede a la decision, jamais une seule mesuree
apres. C est la faute classique et elle donne des modeles parfaits qui perdent tout en reel.

Etiquettes disponibles, au choix :
  `gain`      le resultat net de la regle de production, peage de 2 % deduit ;
  `monte`     le prix a-t-il traverse x1,3 avant la sortie ;
  `effondre`  le prix est-il passe sous x0,7.

Usage :
    python -m intel.research.sol_ml                # etat du jeu
    python -m intel.research.sol_ml --exporter x.csv
    python -m intel.research.sol_ml --entrainer    # refuse sous le minimum
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from typing import Any

sys.path.insert(0, "/app")

TICKET = 20.0
PEAGE = 0.98
VARIABLES = ("payers", "trades", "ratio", "market_cap", "liquidity_usd", "age_s",
             "chg_m5", "trades_30s", "uniq_payers_30s", "accel")


def jeu(db: str) -> list[dict[str, Any]]:
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    courbes: dict[str, list[tuple[float, float]]] = {}
    for r in c.execute("SELECT pair_id, age_min, price_usd FROM solana_suivi WHERE price_usd>0 "
                       "ORDER BY pair_id, age_min"):
        courbes.setdefault(r["pair_id"], []).append((float(r["age_min"] or 0), float(r["price_usd"])))

    out = []
    for j in c.execute(
            "SELECT j.pair_id, j.ts, j.payers, j.trades, j.market_cap, j.liquidity_usd, j.age_s,"
            " j.chg_m5, o.trades_30s, o.uniq_payers_30s FROM solana_judgements j"
            " LEFT JOIN solana_observations o ON o.pair_id=j.pair_id"):
        pts = courbes.get(j["pair_id"])
        if not pts or len(pts) < 6:
            continue
        ent = [(a, p) for a, p in pts if a >= 2]
        if not ent:
            continue
        a0, px0 = ent[0]
        fen = [(a, p / px0) for a, p in pts if a0 < a <= a0 + 30]
        if len(fen) < 3:
            continue
        # sortie confirmee par deux releves (§3.54)
        mult = None
        for i, (_a, m) in enumerate(fen):
            suiv = fen[i + 1][1] if i + 1 < len(fen) else None
            if m <= 0.7 and suiv is not None and suiv <= 0.7:
                mult = 0.7
                break
            if m >= 1.5 and suiv is not None and suiv >= 1.5:
                mult = 1.5
                break
        if mult is None:
            mult = fen[-1][1]
        d = dict(j)
        # Deux champs melangent une vraie valeur et une panne de mesure, et il faut les separer
        # avant tout apprentissage (audit du 09/09) :
        #   - `uniq_payers_30s` vaut 0 sur 684 lignes, dont 332 qui declarent PLUS DE DIX echanges
        #     dans les memes trente secondes. Zero acheteur pour cent echanges est impossible :
        #     l enrichissement Helius a echoue et le code a ecrit 0 au lieu d inconnu. Les 352
        #     autres zeros sont legitimes -- zero echange, donc zero acheteur.
        #   - `liquidity_usd` vaut exactement 0,00 sur 201 lignes qui affichent 181 echanges en
        #     mediane : le champ est absent, pas nul.
        # Un jeu d apprentissage avec des trous non declares est pire qu un petit jeu propre : le
        # modele apprend a reconnaitre la panne. C est exactement ce qui a fait sortir
        # « liquidity_usd < 8,83 » comme meilleure regle, alors qu elle ne selectionnait que les
        # lignes ou la donnee manque.
        t30 = d.get("trades_30s") or 0
        p30 = d.get("uniq_payers_30s")
        if p30 == 0 and t30 > 0:
            p30 = None                      # mesure ratee, pas une vraie absence d acheteurs
            d["uniq_payers_30s"] = None
        if not d.get("liquidity_usd"):
            d["liquidity_usd"] = None
        d["ratio"] = (d.get("trades") or 0) / max(d.get("payers") or 1, 1)
        d["accel"] = (float(d.get("payers") or 0) / p30) if p30 else None
        d["gain"] = (mult * PEAGE - 1) * TICKET
        d["monte"] = int(max(m for _a, m in fen) >= 1.3)
        d["effondre"] = int(min(m for _a, m in fen) <= 0.7)
        out.append(d)
    out.sort(key=lambda x: x["ts"])
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="/app/db/intel.sqlite")
    ap.add_argument("--minimum", type=int, default=1000,
                    help="en dessous, on n entraine pas : le modele apprendrait le bruit")
    ap.add_argument("--exporter")
    ap.add_argument("--entrainer", action="store_true")
    args = ap.parse_args()

    d = jeu(args.db)
    print(f"  {len(d)} exemples etiquetes · {len(VARIABLES)} variables")
    if not d:
        return
    manquantes = {v: sum(1 for x in d if x.get(v) is None) for v in VARIABLES}
    for v, n in sorted(manquantes.items(), key=lambda x: -x[1]):
        if n:
            print(f"    {v:<18}{n:>5} valeurs manquantes ({n / len(d):.0%})")
    pos = sum(1 for x in d if x["gain"] > 0)
    print(f"  etiquettes : {pos}/{len(d)} gagnants ({pos / len(d):.0%}) · "
          f"{sum(x['monte'] for x in d)} montent · {sum(x['effondre'] for x in d)} s effondrent")

    if args.exporter:
        import csv
        with open(args.exporter, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=["ts", *VARIABLES, "gain", "monte", "effondre"],
                               extrasaction="ignore")
            w.writeheader()
            w.writerows(d)
        print(f"  exporte vers {args.exporter}")

    if args.entrainer:
        if len(d) < args.minimum:
            print(f"\n  ON N ENTRAINE PAS : {len(d)} exemples pour {len(VARIABLES)} variables, il en")
            print(f"  faut au moins {args.minimum}. En dessous, un modele apprend le bruit et rend un")
            print("  score flatteur qui ne survit pas -- c est l erreur commise quatre fois a la main")
            print("  le 09/09, chaque fois avec un resultat spectaculaire et chaque fois un artefact.")
            reste = args.minimum - len(d)
            print(f"  Il manque {reste} exemples, soit environ {reste / 58:.0f} h de collecte au")
            print("  rythme actuel de 58 lancements juges par heure.")
            return
        print("\n  echantillon suffisant : entrainement sur la premiere moitie, jugement sur la")
        print("  seconde, jamais regardee -- meme discipline que les balayages manuels (§3.45).")


if __name__ == "__main__":
    main()
