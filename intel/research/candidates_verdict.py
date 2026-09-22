"""LES DEUX CANDIDATES GELEES LE 22/09 22h13 — ou en sont-elles ?

Mido, 22/09 : « oui on gele ». Deux remplacantes possibles de `BANDE + PAUSE`, figees AVANT
qu un seul ticket posterieur n existe, avec leur critere ecrit d avance :

  A · PAUSE 25     la meme regle, seuil de pause -0,25 au lieu de -0,30. Choisie par un balayage
                   1re moitie / 2e moitie : +1,767 la ou elle a ete choisie, +4,187 sur la moitie
                   suivante (la production faisait +1,572 puis +3,727). Aucun entrainement.

  B · MODELE FRAIS le meme LightGBM, memes 19 variables, meme cible, reentraine sur les 4 704
                   tickets connus au gel. Sa bande est recalibree sur les QUANTILES qu occupait
                   [0,20 ; 0,35[ chez le modele en service -- sans quoi les memes bornes
                   designeraient d autres jetons. Elle part PERDANTE (+4,021 contre +5,704 sur
                   une fenetre de 1 176 tickets jamais vus), et c est pour ca qu on la mesure au
                   lieu d en debattre.

CRITERE, FIGE — au premier atteint de 200 tickets retenus ou de 14 jours, une candidate ne prend
la place de la production que si, sur les tickets POSTERIEURS au gel :
  (a) elle bat `BANDE + PAUSE` en EUR/ticket sur LES MEMES tickets (comparaison appariee),
  (b) elle est positive en valeur absolue,
  (c) elle bat son propre nul par DECALAGE CIRCULAIRE a p < 0,05.
Sinon : abandon, et on n y revient pas sans raison neuve.

(c) EST LA CONDITION QUE LA PRODUCTION NE FRANCHIT PAS ENCORE (p = 0,04 a 0,07 le 22/09). Une
candidate ne remplace pas sur un match nul : elle doit faire MIEUX, pas aussi mal. Et le nul est
celui du decalage circulaire, jamais le tirage au sort -- une pause appliquee a des rendements
melanges rapporte deja ~+0,38 EUR/ticket par pure mecanique (§3.171).

Lecture seule. Usage : python -m intel.research.candidates_verdict
"""
from __future__ import annotations

import datetime as dt
import json
import os
import random
import sqlite3
import statistics as st

TZ = dt.timezone(dt.timedelta(hours=2))
DOSSIER = os.environ.get("CANDIDATES", "/app/data/recherche/candidates")
COMBO = os.environ.get("COMBO_DB", "/app/db/papier_combo.sqlite")
BANDE = (0.20, 0.35)
V, MISE, FIXE = 17.5845, 20.0, 0.03524
PAUSE_S, TENUE = 1800.0, 242.0
TIRAGES = 3000
random.seed(20260922)


def cout(q: float) -> float:
    return FIXE + 2.0 * (MISE * 0.31 / 30.0) / ((q or 0) + V)


def rejoue(tickets, seuil, duree=PAUSE_S):
    """La pause, appliquee dans l ordre reel. `tickets` : [{t, fin, r}] tries par t."""
    pris, att, bl = [], [], 0.0
    for x in tickets:
        att.sort(key=lambda z: z["fin"])
        while att and att[0]["fin"] <= x["t"]:
            f = att.pop(0)
            if f["r"] <= seuil:
                bl = max(bl, f["fin"] + duree)
        if x["t"] >= bl:
            pris.append(x)
        att.append(x)
    return pris


def nul(tickets, seuil):
    """Le meme filtre sur des rendements decales circulairement : le biais mecanique de la regle."""
    R = [x["r"] for x in tickets]
    if len(R) < 30:
        return []
    out = []
    for _ in range(TIRAGES):
        d = random.randrange(1, len(R))
        perm = R[d:] + R[:d]
        faux = [dict(tickets[i], r=perm[i]) for i in range(len(tickets))]
        p = rejoue(faux, seuil)
        if p:
            out.append(MISE * st.mean(z["r"] for z in p))
    return out


def dis(nom, pris, seuil, tickets):
    if len(pris) < 10:
        print("   %-26s %5d tickets — trop peu pour juger" % (nom, len(pris)))
        return None
    m = MISE * st.mean(x["r"] for x in pris)
    n = nul(tickets, seuil)
    p = (sum(1 for z in n if z >= m) / len(n)) if n else float("nan")
    print("   %-26s %5d tickets %+8.3f EUR/ticket · nul %+0.3f · p = %.4f%s"
          % (nom, len(pris), m, st.mean(n) if n else 0.0, p, "  <-- (c) FRANCHI" if p < 0.05 else ""))
    return m


def main() -> None:
    meta_f = os.path.join(DOSSIER, "modele_frais_meta.json")
    if not os.path.exists(meta_f):
        print("pas de gel trouve dans %s" % DOSSIER)
        return
    meta = json.load(open(meta_f))
    gel = float(meta["gel"])
    print("LES CANDIDATES GELEES LE %s" % meta["gel_lisible"])
    ecoule = (dt.datetime.now(TZ).timestamp() - gel) / 86400.0
    print("   %.1f jour(s) ecoules sur les 14 de l echeance" % ecoule)
    print()

    c = sqlite3.connect("file:%s?mode=ro" % COMBO, uri=True, timeout=30)
    lignes = []
    for t, vj, q, b, risq in c.execute(
            "SELECT d.t_dec, d.variables, d.q, i.brut_240, d.risque FROM decision d"
            " JOIN issue i ON i.pair=d.pair WHERE d.eligible=1 AND i.brut_240 IS NOT NULL"
            " AND d.q IS NOT NULL AND d.risque IS NOT NULL AND d.t_dec >= ? ORDER BY d.t_dec",
            (gel,)):
        lignes.append((float(t), vj, float(q), float(b), float(risq)))
    if not lignes:
        print("   aucun ticket posterieur au gel — revenir plus tard")
        return
    print("   %d tickets juges depuis le gel" % len(lignes))
    print()

    def paquet(garde):
        return [{"t": t, "fin": t + TENUE, "r": min(b - cout(q), 3.0)}
                for t, vj, q, b, r in lignes if garde(vj, r)]

    prod = paquet(lambda vj, r: BANDE[0] <= r < BANDE[1])
    print("   LA PRODUCTION, pour reference")
    ref = dis("BANDE + PAUSE (-0,30)", rejoue(prod, -0.30), -0.30, prod)
    print()
    print("   LES CANDIDATES")
    a = dis("A · PAUSE 25 (-0,25)", rejoue(prod, -0.25), -0.25, prod)

    na, nb = meta["bande_frais"]
    modele = os.path.join(DOSSIER, "modele_frais.json")
    if os.path.exists(modele):
        try:
            import lightgbm as lgb
            import numpy as np
            boost = lgb.Booster(model_file=modele)
            var = meta["variables"]
            X, ok = [], []
            for t, vj, q, b, r in lignes:
                try:
                    f = json.loads(vj)
                except Exception:  # noqa: BLE001
                    continue
                X.append([float(f.get(k)) if f.get(k) is not None else np.nan for k in var])
                ok.append((t, q, b))
            s = boost.predict(np.array(X, dtype=float))
            frais = [{"t": ok[i][0], "fin": ok[i][0] + TENUE,
                      "r": min(ok[i][2] - cout(ok[i][1]), 3.0)}
                     for i in range(len(ok)) if na <= s[i] < nb]
            frais.sort(key=lambda z: z["t"])
            dis("B · MODELE FRAIS", rejoue(frais, -0.30), -0.30, frais)
        except Exception as exc:  # noqa: BLE001
            print("   B · MODELE FRAIS — illisible (%s)" % str(exc)[:70])

    print()
    print("   ECHEANCE : 200 tickets retenus OU 14 jours. (a) battre la production sur les memes")
    print("   tickets · (b) etre positive · (c) p < 0,05 contre le decalage circulaire.")
    if ref is not None and a is not None:
        print("   ecart A - production : %+0.3f EUR/ticket" % (a - ref))


if __name__ == "__main__":
    main()
