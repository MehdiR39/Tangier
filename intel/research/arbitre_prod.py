"""CHAQUE CANDIDATE CONTRE LE MOTEUR, SUR LES MEMES TICKETS ET EN EUROS REELS.

MIDO, 20/09 : « go vas-y, feel free de faire ce que tu veux de l app ».

LA QUESTION, ET POURQUOI C EST LA SEULE QUI PEUT JUSTIFIER DE CHANGER LA PRODUCTION. Toutes les
lignes de la page comparent une strategie a un TEMOIN PAPIER. Aucune ne dit : « sur les tickets que
le moteur a REELLEMENT achetes, qu aurait dit la candidate ? ». C est pourtant la seule mesure qui
porte sur de vrais euros -- `gain_eur` est lu sur le portefeuille -- et la seule qui reponde a la
question qu on se pose vraiment : est-ce que ce modele-la aurait fait mieux que celui qui tourne.

POURQUOI C EST BEAUCOUP PLUS RAPIDE QU UN NIVEAU. C est une comparaison APPARIEE : memes tickets,
meme marche, memes couts reellement payes. La variance du marche s annule. §3.165 l a montre --
0,14 EUR/ticket devenait lisible la ou un niveau absolu demande 3 000 tickets. Prouver que
`GAGNANT 20 %` gagne de l argent coute ~2 000 tickets ; prouver qu elle fait mieux que le moteur en
coute bien moins, parce qu on ne mesure que la DIFFERENCE.

CE QUE CE SCRIPT NE PEUT PAS FAIRE, et il faut le dire avant de lire ses chiffres :
  - une candidate qui decide a 75 s ne peut pas etre comparee au moteur, qui achete a 47 s : ce ne
    sont pas les memes tickets au meme instant. Elles sont marquees comme telles et exclues ;
  - il ne voit que les tickets que le moteur a ACHETES. Une candidate qui aurait pris des tickets
    que le moteur a refuses ne peut pas etre creditee pour eux ici -- ce test dit seulement
    « aurait-elle mieux trie CE QUE le moteur a pris », pas « aurait-elle trouve mieux ailleurs ».

Papier, zero euro, lecture seule. Ecrit `arbitre.json` pour la page.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3

import numpy as np

SORTIE = os.environ.get("ARBITRE_JSON", "/app/data/arbitre.json")
INTEL = "/app/db/intel.sqlite"

# nom affiche -> (base, colonne de decision, meme instant de decision que le moteur ?)
CANDIDATES = [
    ("FORET GAGNANT 20 %", "/app/data/recherche/foret_gagnant/carnet.sqlite", "retenu", True),
    ("FORET GAGNANT 10 % (lecture)", "/app/data/recherche/foret_gagnant/carnet.sqlite", "retenu10", True),
    ("FORET GAGNANT 5 % (lecture)", "/app/data/recherche/foret_gagnant/carnet.sqlite", "retenu05", True),
    ("FORET REENTRAINEE 6h", "/app/data/recherche/foret_marche/carnet.sqlite", "retenu", True),
    ("FORET 45s top 5 % (gelee)", "/app/db/papier_foret.sqlite", "retenu05", True),
    ("FORET 45s top 10 % (lecture)", "/app/db/papier_foret.sqlite", "retenu10", True),
    ("FORET 75s top 5 % (gelee)", "/app/db/papier_foret75.sqlite", "retenu05", False),
    ("FORET 75s REENTRAINEE 20 %", "/app/data/recherche/foret75_carnet/carnet.sqlite", "retenu", False),
]


def reel():
    c = sqlite3.connect("file:%s?mode=ro" % INTEL, uri=True, timeout=30)
    return {p: (float(g), float(m or 10.0), float(t)) for p, g, m, t in c.execute(
        "SELECT pair, gain_eur, mise_eur, ts_entree FROM mr_lignes"
        " WHERE mode='live' AND gain_eur IS NOT NULL AND pair IS NOT NULL AND ts_entree IS NOT NULL")}


def decisions(chemin, col):
    if not os.path.exists(chemin):
        return {}
    c = sqlite3.connect("file:%s?mode=ro" % chemin, uri=True, timeout=30)
    try:
        if col not in [x[1] for x in c.execute("PRAGMA table_info(decision)")]:
            return {}
        return {p: bool(k) for p, k in c.execute(
            "SELECT pair, %s FROM decision WHERE %s IS NOT NULL" % (col, col))}
    except sqlite3.Error:
        return {}


def main() -> None:
    R = reel()
    out = {"genere": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
           "n_reel": len(R), "lignes": []}
    for nom, chemin, col, comparable in CANDIDATES:
        D = decisions(chemin, col)
        communs = [p for p in D if p in R]
        e = {"nom": nom, "comparable": comparable, "n_commun": len(communs)}
        if comparable and len(communs) >= 10:
            gardes = np.array([R[p][0] for p in communs if D[p]])
            jetes = np.array([R[p][0] for p in communs if not D[p]])
            tous = np.array([R[p][0] for p in communs])
            e["n_gardes"], e["n_jetes"] = len(gardes), len(jetes)
            e["moteur_eur_ticket"] = round(float(tous.mean()), 4)
            e["moteur_total"] = round(float(tous.sum()), 2)
            if len(gardes) and len(jetes):
                e["candidate_eur_ticket"] = round(float(gardes.mean()), 4)
                e["candidate_total"] = round(float(gardes.sum()), 2)
                e["ecarte_eur_ticket"] = round(float(jetes.mean()), 4)
                # Le bruit de la DIFFERENCE entre « ce qu elle garde » et « tout prendre » :
                # sous-ensemble d un meme lot, donc sigma.racine((n-k)/(n.k)) et non sigma/racine(k)
                # (regle 22 -- c est l erreur qui m a fait declarer un test rate le 19/09).
                n_, k_ = len(tous), len(gardes)
                s = float(tous.std(ddof=1))
                bruit = s * ((n_ - k_) / (n_ * k_)) ** 0.5 if 0 < k_ < n_ else float("inf")
                d = float(gardes.mean() - tous.mean())
                e["ecart"] = round(d, 4)
                e["bruit"] = round(bruit, 4)
                e["sigmas"] = round(d / bruit, 2) if bruit else None
                # ce que ca ferait sur la journee, au rythme reel
                jours = (max(R[p][2] for p in communs) - min(R[p][2] for p in communs)) / 86400.0
                if jours >= 0.3:
                    e["eur_jour_gagnes"] = round(d * k_ / jours, 1)
        out["lignes"].append(e)
    with open(SORTIE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)

    print("ARBITRE : %d tickets reels clotures" % len(R))
    print("   %-30s %7s %8s %11s %11s %8s" % ("", "communs", "gardes", "moteur", "candidate", "sigma"))
    for e in out["lignes"]:
        if not e.get("comparable"):
            print("   %-30s  — decide a 75 s, pas comparable au moteur qui achete a 47 s" % e["nom"][:30])
        elif "ecart" not in e:
            print("   %-30s %7d  (trop peu en commun pour lire)" % (e["nom"][:30], e["n_commun"]))
        else:
            print("   %-30s %7d %8d %+11.4f %+11.4f %+8.2f"
                  % (e["nom"][:30], e["n_commun"], e["n_gardes"],
                     e["moteur_eur_ticket"], e["candidate_eur_ticket"], e["sigmas"] or 0))


if __name__ == "__main__":
    main()
