"""VERDICT DU GEL DU 18/09 01h30 : la loterie des tirages coutait-elle de l argent ?

LE CRITERE, TEL QU IL A ETE FIGE le 17/09 a 23h30 UTC dans `ensemble.py`, mot pour mot :
    « au premier atteint de 1 000 tickets posterieurs au gel ou de 21 jours, l ensemble doit faire
      MIEUX que le modele en service sur EXACTEMENT les memes tickets. La comparaison est appariee
      -- meme marche, memes jetons, seul le score change. »

CE QUI EST COMPARE :
    modele en service   `modele_vidage.json`, LightGBM, UN tirage, seuil p80 = 0,2694 -- c est lui
                        qui decide dans le livre depuis le debut (regle `risque`)
    ENSEMBLE de 12      `ensemble_vidage.json`, la moyenne de douze entrainements identiques
    FORET ALEATOIRE     `foret_vidage.json` -- notee en parallele, mais elle N EST PAS la question
                        pre-enregistree : elle est rapportee a part et ne peut pas, a elle seule,
                        justifier une decision.

POURQUOI L ENSEMBLE. Mesure du 18/09 : 96 entrainements identiques sur les memes donnees donnent
de -252 a +348 EUR, 30 % des tirages PERDENT. Le modele en service est un de ces tirages et il
etait au-dessus de la moyenne : de la chance, pas une qualite. L ensemble ne cherche pas a gagner
plus, il supprime cette loterie.

CE QU ON RAPPORTE, au-dela du oui/non : le NIVEAU en euros apres cout mesure (2,98 pt), le meme
sans ses 3 meilleurs tickets, les deux moities chronologiques, et le bruit propre de la comparaison
appariee -- parce qu un ecart plus petit que son bruit ne se depense pas (regle 23).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
import sys

import numpy as np

sys.path.insert(0, "/app/intel/research")
from ensemble import CHEMIN, CHEMIN_FORET, GEL_ENSEMBLE, Ensemble, N_CRITERE  # noqa: E402

BASE = "/app/db/papier_combo.sqlite"
MODELE = os.environ.get("MODELE_VIDAGE", "/app/data/recherche/balayage/modele_vidage.json")
COUT = float(os.environ.get("COUT_MESURE", "0.0298"))
MISE = 20.0
TZ = dt.timezone(dt.timedelta(hours=2))


def main() -> None:
    from papier_combo import Modele
    service = Modele(MODELE)
    modeles = {
        "modele en service (1 tirage)": (lambda f: service.probabilite(f), service.seuil_p80),
    }
    for nom, chemin in (("ENSEMBLE de 12", CHEMIN), ("FORET ALEATOIRE", CHEMIN_FORET)):
        try:
            m = Ensemble(chemin)
            modeles[nom] = (m.probabilite, m.seuil_p80)
        except Exception as e:  # noqa: BLE001
            print("!! %s illisible : %s" % (nom, e))

    c = sqlite3.connect("file:%s?mode=ro" % BASE, uri=True, timeout=60)
    lignes = []
    for t, cr, b240, q, var in c.execute(
            "SELECT d.t_dec, d.cout_reduit, i.brut_240, d.q, d.variables FROM decision d"
            " JOIN issue i ON i.pair=d.pair WHERE d.eligible=1 AND i.brut_240 IS NOT NULL"
            " AND d.q IS NOT NULL AND d.variables IS NOT NULL AND d.t_dec >= ? ORDER BY d.t_dec",
            (GEL_ENSEMBLE,)):
        f = json.loads(var)
        r = min((1.0 + float(b240)) * (1.0 - COUT) - 1.0, 3.0)
        lignes.append((float(t), r, f))

    n = len(lignes)
    d0 = dt.datetime.fromtimestamp(GEL_ENSEMBLE, TZ)
    d1 = dt.datetime.fromtimestamp(lignes[-1][0], TZ) if lignes else d0
    print("VERDICT DU GEL · %s -> %s · %d tickets notes (critere : %d)"
          % (d0.strftime("%d/%m %Hh%M"), d1.strftime("%d/%m %Hh%M"), n, N_CRITERE))
    print("cout %.2f pt · mise %.0f EUR · rendement plafonne a +300 %%" % (100 * COUT, MISE))
    if n < N_CRITERE:
        print("\n   critere PAS ENCORE ATTEINT -- rien a conclure")
        return
    print()

    tous = np.array([r for _, r, _ in lignes])
    mi = n // 2
    res = {}
    for nom, (proba, seuil) in modeles.items():
        pris = np.array([i for i, (_, _, f) in enumerate(lignes) if proba(f) <= seuil])
        v = tous[pris]
        h1 = tous[[i for i in pris if i < mi]]
        h2 = tous[[i for i in pris if i >= mi]]
        s = np.sort(v)
        res[nom] = {"pris": set(pris.tolist()), "v": v, "tot": MISE * v.sum(),
                    "par": MISE * v.mean(), "sans3": MISE * s[:-3].mean(),
                    "h1": MISE * h1.sum(), "h2": MISE * h2.sum(), "n": len(v)}

    print("   %-28s %6s %11s %11s %11s %10s %10s" %
          ("", "n pris", "TOTAL EUR", "EUR/ticket", "sans 3 meil", "1re moitie", "2e moitie"))
    print("   %-28s %6d %+10.2f %+10.3f %+10.3f %+9.2f %+9.2f" %
          ("TEMOIN : tout prendre", n, MISE * tous.sum(), MISE * tous.mean(),
           MISE * np.sort(tous)[:-3].mean(), MISE * tous[:mi].sum(), MISE * tous[mi:].sum()))
    for nom in modeles:
        r = res[nom]
        print("   %-28s %6d %+10.2f %+10.3f %+10.3f %+9.2f %+9.2f" %
              (nom, r["n"], r["tot"], r["par"], r["sans3"], r["h1"], r["h2"]))

    print()
    print("LA QUESTION PRE-ENREGISTREE : l ENSEMBLE de 12 fait-il MIEUX que le modele en service ?")
    a, b = res.get("ENSEMBLE de 12"), res["modele en service (1 tirage)"]
    if not a:
        print("   ensemble illisible -- verdict impossible")
        return
    ecart = a["tot"] - b["tot"]
    # bruit de la comparaison APPARIEE : seuls les tickets ou les deux modeles different comptent
    seul_a = a["pris"] - b["pris"]
    seul_b = b["pris"] - a["pris"]
    diff = sorted(seul_a | seul_b)
    sig = MISE * tous.std(ddof=1)
    bruit = sig * np.sqrt(len(diff)) if diff else float("inf")
    print("   ensemble %+.2f EUR · service %+.2f EUR · ECART %+.2f EUR" % (a["tot"], b["tot"], ecart))
    print("   ils ne different que sur %d tickets sur %d (%d pris par l ensemble seul, %d par le service seul)"
          % (len(diff), n, len(seul_a), len(seul_b)))
    print("   bruit de cet ecart : %.2f EUR -> %+.2f ecart-type%s"
          % (bruit, ecart / bruit if bruit else 0.0,
             "" if bruit else " (aucun ticket ne les separe)"))
    print()
    verdict = "PASSE" if ecart > 0 else "ECHOUE"
    print("   -> L ENSEMBLE %s le critere (il devait faire MIEUX : %+.2f EUR)" % (verdict, ecart))
    if abs(ecart) < 2 * bruit:
        print("      MAIS l ecart est plus petit que deux fois son bruit : il ne se depense pas.")
        print("      Le critere pre-enregistre est binaire, la realite ne l est pas -- ce chiffre")
        print("      dit que la loterie coute PEU, pas qu elle coute ce montant-la.")

    print()
    print("A PART, ET NON PRE-ENREGISTREE : la FORET ALEATOIRE")
    f = res.get("FORET ALEATOIRE")
    if f:
        print("   %+.2f EUR contre %+.2f pour le service, soit %+.2f EUR d ecart sur %d tickets"
              % (f["tot"], b["tot"], f["tot"] - b["tot"], n))
        print("   positive sans ses 3 meilleurs : %s · sur les deux moities : %s"
              % ("OUI" if f["sans3"] > 0 else "NON",
                 "OUI" if (f["h1"] > 0 and f["h2"] > 0) else "NON"))
        print("   Elle n a PAS de critere pre-enregistre a cette date : ce chiffre est une")
        print("   observation, pas un verdict, et ne peut pas justifier a lui seul une mise reelle.")


if __name__ == "__main__":
    main()
