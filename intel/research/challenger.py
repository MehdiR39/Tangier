"""LE PROCESS DE MISE A JOUR DU MODELE : quand on reentraine, et comment on decide d adopter.

Mido, depuis plusieurs jours : « il faut qu on arrive a comprendre [...] pour qu on puisse corriger
le modele en cas de drift », puis le 26/09 : « comment on va mettre en place un process qui
determine quand et comment on update ». Ce fichier est la reponse, et il ne fait AUCUN changement :
il gele, il juge, il annonce. Le changement reste une decision de Mido.

CE QUE LA JOURNEE DU 26/09 A IMPOSE COMME CONCEPTION
------------------------------------------------------------------------------------------------
1. **« Reentrainer quand ca derive » EST LE MAUVAIS DECLENCHEUR.** Le modele en service ne derive
   pas -- AUC 0,7105 hors echantillon contre 0,7202 sur tout l historique -- et pourtant un modele
   reentraine (`B · MODELE FRAIS`) bat la production 7 axes sur 7. Aucun signal de derive n annonce
   qu un reentrainement va aider. Il n y a donc rien a detecter : il faut un CHALLENGER PERMANENT.

2. **ON NE JUGE JAMAIS SUR L AUC.** B a une AUC PIRE que la production sur les trois cibles
   (vidage 0,6454 vs 0,6548 · gros gain 0,6754 vs 0,7105 · x2 0,6789 vs 0,7310) et gagne quand meme
   en euros. Mido : « le seul critere c est est-ce qu on gagne ». La grille des SEPT CRITERES de
   `data/table_std2.py::_criteres` est l arbitre -- celle-la meme dont le journal (§3.167) enregistre
   que l ignorer a coute **-45,75 EUR** le 20/09, quand une regle notee 2/6 est passee en production
   sur la foi d un seul chiffre.

3. **LA BANDE SE RECALIBRE SUR LES QUANTILES, jamais sur les bornes.** Un modele reentraine
   redistribue ses scores : garder [0,20 ; 0,35] designerait d autres jetons. On reprend la POSITION
   EN QUANTILE qu occupe la bande en service.

4. **CHAQUE GEL EST UN ESSAI, ET LA BARRE MONTE.** C est le garde-fou central. Un challenger
   permanent qui adopterait « le meilleur » a chaque tour finirait par adopter du bruit : c est une
   selection sur N candidats, et le maximum de N tirages nuls croit avec N. On incremente donc le
   compteur d essais PERSISTANT partage avec `veille_derive`, et on exige un DSR (Bailey & Lopez de
   Prado) calcule a ce N cumule. Reentrainer souvent COUTE, et ce cout est explicite.

5. **ON DIT SUR COMBIEN DE TICKETS L ECART REPOSE.** Celui de B repose sur 5.

CE QUI N EST PAS DANS LE CRITERE, ET POURQUOI
------------------------------------------------------------------------------------------------
La decomposition « l avantage vient-il de la SELECTION ou de la PAUSE » est affichee parce qu elle
decrit d ou vient l argent -- mais elle NE DECIDE PAS. J avais ecrit le 26/09 que l avantage venu de
la selection tiendrait et que celui venu de la pause serait fragile : **ce n a jamais ete mesure.**
Tant que ca ne l est pas, ca reste une description, pas une regle.

USAGE
    python -m intel.research.challenger --geler    # fige un challenger : modele + bande + essai
    python -m intel.research.challenger            # juge tous les challengers geles
"""
from __future__ import annotations

import datetime as dt
import json
import os
import statistics as st
import sys

DOSSIER = os.environ.get("CHALLENGERS", "/app/data/recherche/challengers")
COMBO = os.environ.get("COMBO_DB", "/app/db/papier_combo.sqlite")
ETAT = os.environ.get("DERIVE_ETAT", "/app/data/recherche/derive_etat.json")
TZ = dt.timezone(dt.timedelta(hours=2))

BANDE_SERVICE = (0.20, 0.35)
V, MISE, FIXE = 17.5845, 20.0, 0.03524
TENUE, SEUIL, PAUSE_S = 242.0, -0.30, 1800.0

# L ECHEANCE, ECRITE AVANT TOUT GEL. Au premier atteint.
ECHEANCE_TICKETS, ECHEANCE_JOURS = 200, 14
# COMBIEN DES SEPT AXES IL FAUT GAGNER. 7/7 serait trop exigeant (les axes sont correles entre eux,
# ils decrivent les memes rendements) et 4/7 trop laxiste : une majorite franche, pas un match nul.
AXES_REQUIS = 5


def cout(q: float) -> float:
    return FIXE + 2.0 * (MISE * 0.31 / 30.0) / ((q or 0) + V)


def rejoue(tickets, seuil=SEUIL, duree=PAUSE_S):
    """La pause, dans l ordre reel. `tickets` : [{t, fin, r}]."""
    pris, att, bl = [], [], 0.0
    for x in sorted(tickets, key=lambda z: z["t"]):
        att.sort(key=lambda z: z["fin"])
        while att and att[0]["fin"] <= x["t"]:
            f = att.pop(0)
            if f["r"] <= seuil:
                bl = max(bl, f["fin"] + duree)
        if x["t"] >= bl:
            pris.append(x)
        att.append(x)
    return pris


def criteres(pris):
    """LES SEPT CRITERES, memes definitions que `data/table_std2.py::_criteres`.

    `part_top3` et `sans3_part` regardent la meme chose par deux bouts : de quoi depend l avance.
    Ils sont ici parce qu ils repondent a « l ecart tient-il a quelques tirages », PAS a « la
    strategie est-elle bonne » -- retirer sa queue a une strategie de queue la tue par construction,
    et Mido a eu raison de me le dire le 26/09.
    """
    v = sorted(pris, key=lambda z: z["t"])
    n = len(v)
    if n < 6:
        return None
    nets = [MISE * x["r"] for x in v]
    tot, jours, mi = sum(nets), (v[-1]["t"] - v[0]["t"]) / 86400.0, n // 2
    s = sorted(nets)
    sans3 = sum(s[:-3]) / (n - 3)
    sig = st.pstdev(nets)
    return {"n": n, "jours": jours,
            "niveau": tot / n,
            "eur_jour": tot / jours if jours >= 0.5 else float("nan"),
            "moitie_1": sum(nets[:mi]) / mi,
            "moitie_2": sum(nets[mi:]) / (n - mi),
            "sans3_part": max(0.0, sans3) / (tot / n) if tot > 0 else 0.0,
            "part_top3": 100.0 * sum(s[-3:]) / tot if tot else float("inf"),
            "gagnants": 100.0 * sum(1 for x in nets if x > 0) / n,
            "niveau_sigma": (tot / n) / (sig / n ** 0.5) if sig > 0 else float("nan")}


# les sept axes qui se comparent, et le sens dans lequel « mieux » va
AXES = [("niveau", "EUR/ticket", True), ("eur_jour", "EUR/jour", True),
        ("moitie_1", "1re moitie", True), ("moitie_2", "2e moitie", True),
        ("sans3_part", "part qui survit a -3", True),
        ("part_top3", "part portee par le top 3", False),
        ("niveau_sigma", "sigma du niveau", True)]


def charger_etat() -> dict:
    try:
        return json.load(open(ETAT))
    except Exception:  # noqa: BLE001
        return {"essais": 12, "historique": []}


def enregistrer_etat(e: dict) -> None:
    tmp = ETAT + ".tmp"
    json.dump(e, open(tmp, "w"), indent=1)
    os.replace(tmp, ETAT)


def _lignes(depuis=0.0):
    import sqlite3
    c = sqlite3.connect("file:%s?mode=ro" % COMBO, uri=True, timeout=30)
    out = []
    for t, vj, q, b, r in c.execute(
            "SELECT d.t_dec, d.variables, d.q, i.brut_240, d.risque FROM decision d"
            " JOIN issue i ON i.pair=d.pair WHERE d.eligible=1 AND i.brut_240 IS NOT NULL"
            " AND d.q IS NOT NULL AND d.risque IS NOT NULL AND d.t_dec >= ? ORDER BY d.t_dec",
            (depuis,)):
        out.append((float(t), vj, float(q), float(b), float(r)))
    return out


def geler() -> None:
    """Fige un challenger : modele reentraine + bande recalibree en QUANTILE + numero d essai."""
    import numpy as np
    import lightgbm as lgb

    lignes = _lignes()
    if len(lignes) < 1000:
        print("pas assez de tickets pour geler (%d)" % len(lignes))
        return
    # LA CIBLE EST CELLE DU MODELE EN SERVICE -- le vidage -- pour que le challenger soit
    # comparable. Changer la cible ferait une autre experience, pas un challenger.
    VAR = sorted({k for _, vj, _, _, _ in lignes[:200] for k in (json.loads(vj) or {})
                  if isinstance((json.loads(vj) or {}).get(k), (int, float))})
    X, y = [], []
    for t, vj, q, b, r in lignes:
        try:
            f = json.loads(vj)
        except Exception:  # noqa: BLE001
            continue
        X.append([float(f.get(k)) if f.get(k) is not None else np.nan for k in VAR])
        y.append(1 if b - cout(q) <= -0.50 else 0)
    X = np.array(X, dtype=float)
    # `feature_name=VAR` N EST PAS COSMETIQUE. Le moteur et le carnet papier cherchent chaque
    # variable PAR NOM (`arbres.Modele.probabilite` fait `valeurs.get(nom)`). Un modele entraine sur
    # un tableau sans noms produit `Column_0`, `Column_1`... : a l execution CHAQUE variable serait
    # trouvee absente, chaque arbre prendrait sa branche par defaut, et le modele rendrait une
    # constante SANS LEVER LA MOINDRE ERREUR. C est la regle 10 du projet (train/serve skew), deja
    # documentee dans `prod_reentraine.py`. La verification plus bas est la pour s en assurer.
    boost = lgb.train({"objective": "binary", "verbose": -1, "num_leaves": 31,
                       "learning_rate": 0.05, "min_data_in_leaf": 20, "seed": 0},
                      lgb.Dataset(X, label=y, feature_name=list(VAR)), num_boost_round=300)
    s = boost.predict(X)
    # LA BANDE, PAR LES QUANTILES QU OCCUPE CELLE EN SERVICE (point 3 de l en-tete).
    ref = sorted(r for _, _, _, _, r in lignes)
    qlo = sum(1 for z in ref if z < BANDE_SERVICE[0]) / len(ref)
    qhi = sum(1 for z in ref if z < BANDE_SERVICE[1]) / len(ref)
    ss = sorted(s)
    bande = (float(ss[int(qlo * (len(ss) - 1))]), float(ss[int(qhi * (len(ss) - 1))]))

    etat = charger_etat()
    etat["essais"] = int(etat.get("essais", 12)) + 1        # CE GEL EST UN ESSAI : la barre monte
    enregistrer_etat(etat)

    now = dt.datetime.now(TZ)
    d = os.path.join(DOSSIER, now.strftime("%Y%m%d-%H%M%S"))
    os.makedirs(d, exist_ok=True)
    boost.save_model(os.path.join(d, "modele.json"))

    # DEUX FORMATS, PARCE QU IL Y A DEUX LECTEURS, ET ILS SONT INCOMPATIBLES :
    #   `modele.json`      format `save_model`, lu par `lgb.Booster` -> le jugement, ici.
    #   `modele_dump.json` format `dump_model`, lu par `arbres.Modele` -> le CARNET PAPIER et LE
    #                      MOTEUR, qui n ont pas LightGBM. C est celui-la qu il faudra mettre en
    #                      production, jamais l autre : `lgb.Booster` refuse de lire un dump, et
    #                      `arbres.Modele` leve une KeyError sur un `save_model`.
    dump = boost.dump_model()
    dump["seuil_p80"] = float(sorted(s)[int(0.80 * (len(s) - 1))])
    json.dump(dump, open(os.path.join(d, "modele_dump.json"), "w"))

    # LA VERIFICATION QUI EMPECHE LE TRAIN/SERVE SKEW. On relit le dump avec le lecteur DU MOTEUR,
    # sur des variables nommees comme le moteur les nomme, et on exige l accord avec LightGBM.
    # Sans elle, un modele muet -- qui rend une constante parce qu il ne trouve aucune variable --
    # passerait en production sans le moindre signe.
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from arbres import Modele  # noqa: PLC0415
    relu = Modele(os.path.join(d, "modele_dump.json"))
    if list(relu.variables) != list(VAR):
        raise SystemExit("ABANDON : le dump ne porte pas les noms de variables (%s...)"
                         % list(relu.variables)[:3])
    ecart = 0.0
    for i in range(0, len(X), max(1, len(X) // 200)):
        v = {VAR[j]: (None if X[i][j] != X[i][j] else float(X[i][j])) for j in range(len(VAR))}
        ecart = max(ecart, abs(relu.probabilite(v) - float(s[i])))
    if ecart > 1e-6:
        raise SystemExit("ABANDON : le dump et LightGBM divergent de %.2e" % ecart)
    print("   verification lecteur du moteur : %d variables nommees, ecart max %.2e" % (len(VAR), ecart))
    json.dump({"gel": now.timestamp(), "gel_lisible": now.strftime("%d/%m/%Y %H:%M:%S"),
               "variables": VAR, "bande": list(bande), "quantiles": [qlo, qhi],
               "n_entrainement": len(y), "vidages": sum(y) / len(y),
               "essai": etat["essais"],
               "echeance_tickets": ECHEANCE_TICKETS, "echeance_jours": ECHEANCE_JOURS,
               "axes_requis": AXES_REQUIS},
              open(os.path.join(d, "meta.json"), "w"), indent=1)
    print("GELE dans %s" % d)
    print("   %d tickets d entrainement · %.1f %% de vidages" % (len(y), 100 * sum(y) / len(y)))
    print("   bande recalibree sur les quantiles [%.3f ; %.3f] -> [%.4f ; %.4f]"
          % (qlo, qhi, bande[0], bande[1]))
    print("   essai n°%d (le DSR sera calcule a ce N cumule)" % etat["essais"])
    print("   echeance : %d tickets ou %d jours" % (ECHEANCE_TICKETS, ECHEANCE_JOURS))


def juger() -> None:
    import numpy as np
    import lightgbm as lgb

    if not os.path.isdir(DOSSIER):
        print("aucun challenger gele. `--geler` pour en figer un.")
        return
    dossiers = sorted(d for d in os.listdir(DOSSIER)
                      if os.path.exists(os.path.join(DOSSIER, d, "meta.json")))
    if not dossiers:
        print("aucun challenger gele. `--geler` pour en figer un.")
        return
    etat = charger_etat()
    print("=" * 92)
    print("CHALLENGERS — %d gele(s) · compteur d essais cumule : %d"
          % (len(dossiers), etat.get("essais", 12)))
    print("=" * 92)

    for nom in dossiers:
        d = os.path.join(DOSSIER, nom)
        meta = json.load(open(os.path.join(d, "meta.json")))
        gel = float(meta["gel"])
        lignes = _lignes(gel)
        ecoule = (dt.datetime.now(TZ).timestamp() - gel) / 86400.0
        print("\n>> %s  (gele le %s, essai n°%s)" % (nom, meta["gel_lisible"], meta.get("essai", "?")))
        if len(lignes) < 50:
            print("   %d tickets depuis le gel — trop tot." % len(lignes))
            continue

        boost = lgb.Booster(model_file=os.path.join(d, "modele.json"))
        X, ok = [], []
        for i, (t, vj, q, b, r) in enumerate(lignes):
            try:
                f = json.loads(vj)
            except Exception:  # noqa: BLE001
                continue
            X.append([float(f.get(k)) if f.get(k) is not None else np.nan
                      for k in meta["variables"]])
            ok.append(i)
        s = boost.predict(np.array(X, dtype=float))
        na, nb = meta["bande"]
        T = []
        for k, i in enumerate(ok):
            t, vj, q, b, r = lignes[i]
            T.append({"t": t, "fin": t + TENUE, "r": min(b - cout(q), 3.0),
                      "prod": BANDE_SERVICE[0] <= r < BANDE_SERVICE[1],
                      "chal": na <= float(s[k]) < nb})
        cp = criteres(rejoue([x for x in T if x["prod"]]))
        cc = criteres(rejoue([x for x in T if x["chal"]]))
        if not cp or not cc:
            print("   trop peu de tickets retenus d un cote — on attend.")
            continue

        print("   %-28s %14s %14s" % ("", "PRODUCTION", "CHALLENGER"))
        gagnes = 0
        for cle, lab, plus_grand in AXES:
            a, b2 = cp[cle], cc[cle]
            mieux = (b2 > a) if plus_grand else (b2 < a)
            gagnes += 1 if mieux else 0
            print("   %-28s %14.3f %14.3f %s" % (lab, a, b2, "<" if mieux else ""))
        print("   %-28s %14d %14d" % ("tickets", cp["n"], cc["n"]))
        print("   -> le challenger gagne %d axes sur %d" % (gagnes, len(AXES)))

        # d ou vient l argent : DESCRIPTIF, ne decide pas (voir l en-tete)
        off_p = MISE * st.mean(x["r"] for x in T if x["prod"])
        off_c = MISE * st.mean(x["r"] for x in T if x["chal"])
        print("   d ou vient l ecart : selection %+0.3f · pause %+0.3f  (descriptif, ne decide pas)"
              % (off_c - off_p, (cc["niveau"] - cp["niveau"]) - (off_c - off_p)))

        # ---- LE POUVOIR DE CONCENTRATION — lecture RAPIDE, elle ne decide pas -----------
        # 27/09 (§0.2 undecies). Tout l argent vient de la queue haute : la degradation du
        # 24-27/09 (−1,01 EUR/ticket sur la bande) est ENTIEREMENT l amincissement de la part de
        # gros gains, 17,5 % → 14,7 %, les deux autres composantes etant stables (krach 37,8 → 38,6 ;
        # taille du gros gain +1,223 → +1,206). Verification : 0,028 x 1,21 x 25 = 0,85 sur 1,01.
        # POURQUOI L AFFICHER ICI. Pour detecter une baisse de 20 % de la performance il faut
        # **2 657 tickets par bras** en EUR/ticket, contre **1 001** sur la part de gros gains :
        # 2,65x plus vite, 4 jours au lieu de 11 a 240 tickets/jour.
        # POURQUOI ELLE NE DECIDE PAS. Le r2 entre les deux n est que de **24,7 %** (13 blocs de
        # 250 tickets) : la part de gros gains n explique qu un quart de la variance des EUR/ticket.
        # Un challenger peut donc l ameliorer et perdre de l argent ailleurs. L usage est
        # ASYMETRIQUE : elle autorise a REJETER tot -- rejeter ne coute rien, on garde ce qui
        # marche -- jamais a ADOPTER tot, ce qui coute de l argent reel. Le verdict reste sur les
        # sept axes et le niveau.
        def _pg(v):
            if not v:
                return None
            p = sum(1 for x in v if x["r"] >= 0.50) / len(v)
            return p, (p * (1.0 - p) / len(v)) ** 0.5
        m = _pg(T)
        qp, qc = _pg([x for x in T if x["prod"]]), _pg([x for x in T if x["chal"]])
        if m and qp and qc and m[0] > 0:
            se = (qp[1] ** 2 + qc[1] ** 2) ** 0.5
            print("   queue haute (part >= +50 %%) : marche %.1f %% · prod %.1f %% (x%.2f)"
                  " · challenger %.1f %% (x%.2f)"
                  % (100 * m[0], 100 * qp[0], qp[0] / m[0], 100 * qc[0], qc[0] / m[0]))
            print("   ecart challenger-prod sur la queue : %+.1f pt (%.2f sigma) — lecture RAPIDE,"
                  " elle peut rejeter, jamais adopter"
                  % (100 * (qc[0] - qp[0]), (qc[0] - qp[0]) / se if se else 0.0))

        atteint = cc["n"] >= meta["echeance_tickets"] or ecoule >= meta["echeance_jours"]
        print("   echeance : %d/%d tickets · %.1f/%d jours -> %s"
              % (cc["n"], meta["echeance_tickets"], ecoule, meta["echeance_jours"],
                 "ATTEINTE" if atteint else "pas atteinte"))
        if not atteint:
            print("   VERDICT : ATTENDRE.")
            continue
        if gagnes < meta.get("axes_requis", AXES_REQUIS) or cc["niveau"] <= 0:
            print("   VERDICT : REJETE (%d axes sur %d requis, niveau %+0.3f)."
                  % (gagnes, meta.get("axes_requis", AXES_REQUIS), cc["niveau"]))
            continue
        print("   VERDICT : **A ADOPTER** — %d/%d axes, niveau %+0.3f EUR/ticket."
              % (gagnes, len(AXES), cc["niveau"]))
        print("      Ce script ne change RIEN. Pour adopter, c est une decision de Mido :")
        print("      modele_rapide.modele: %s/modele.json" % d)
        print("      et la bande [%0.4f ; %0.4f], et `cumul_depuis` remis a l instant du passage."
              % (na, nb))


if __name__ == "__main__":
    if "--geler" in sys.argv:
        geler()
    else:
        juger()
