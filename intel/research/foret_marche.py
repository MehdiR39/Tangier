"""LA METHODE REENTRAINEE, en iso-prod : une RECETTE gelee, des poids qui se remettent a jour.

MIDO, 19/09 22h20 : « on crée en mode iso-prod ta méthode RF réentraînée sans la variable coût ? »

CE QU ON GELE ICI, ET LA DIFFERENCE AVEC LES AUTRES GELS. Tous les gels du projet figent des POIDS :
`foret_vidage.json` a ete entraine une fois le 15/09 et applique les memes arbres depuis. Celui-ci
fige une RECETTE -- les variables, les reglages, la cadence de reentrainement, la proportion gardee
-- et laisse les poids se refaire toutes les 6 h sur tout ce qui precede. C est un objet different,
et il faut le dire : « une regle qui se reentraine n est pas gelee » (§ foret_gel). Ce qui est gele,
donc non renegociable, c est la recette ci-dessous, ecrite AVANT le premier ticket juge.

    variables     les 18 de prix et de liquidite, SANS aucune variable de cout
    modele        RandomForest, 300 arbres, min_samples_leaf = 20, random_state = 0
    cible         vidage : net_240 <= -50 % au cout applique
    cadence       reentrainement toutes les 6 h sur TOUT ce qui precede la coupe
    decision      on gardait les 80 % de plus faible probabilite de vidage
    cout          3,71 pt, le cout mesure au lamport (§3.156)

POURQUOI SANS LE COUT. Mesure du 19/09 au soir : la variable `cout` que le modele en production
utilise DEGRADE la methode -- +0,281 avec elle contre +0,363 sans, en marche avant sur les memes
tickets. Et elle porte 21 % de l importance du modele en prod. Ce n est donc pas une omission, c est
un choix mesure. (La version « recalee sur le vrai cout » donne exactement le meme resultat que la
formule : les deux ne different que d une CONSTANTE, qu un arbre ignore. Le vrai test attend
l impact annonce par le routeur, enregistre depuis le 19/09 22h.)

CE QUE LA METHODE A DEJA MONTRE, et qui justifie de lui donner un carnet : en marche avant sur
2 353 tickets temoin, +0,363 EUR/ticket contre le temoin, soit +2,83 ecarts-types.

CRITERE, FIGE AVANT LE PREMIER TICKET. Au premier atteint de 1 200 tickets retenus ou de 14 jours,
les QUATRE doivent tenir :
    (a) battre le temoin sur sa propre periode ;
    (b) le battre encore sans ses 3 meilleurs tickets ;
    (c) etre positive contre le temoin sur les DEUX moities chronologiques ;
    (d) l ecart depasse 2 fois son propre bruit -- sigma x racine(m/(n.k)), comparaison appariee.
1 200 n est pas un chiffre rond : a +0,363 EUR/ticket et sigma 14 EUR, il faut ~1 490 tickets temoin
(donc ~1 200 gardes) pour que (d) soit seulement ATTEIGNABLE. En dessous le critere serait
impossible a satisfaire et l attente une comedie.

Papier, zero euro. Base propre. Ne touche ni au moteur, ni aux collecteurs, ni aux autres gels.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
import time

import numpy as np
import pandas as pd

DOSSIER = os.environ.get("MARCHE_DIR", "/app/data/recherche/foret_marche")
BASE_DB = os.path.join(DOSSIER, "carnet.sqlite")
TABLE = "/app/data/recherche/tout/table.pkl"
COUT = float(os.environ.get("COUT_MESURE", "0.0371"))
MISE = 20.0
GARDE = 0.80
PAS_H = 6.0
N_CRITERE, JOURS_CRITERE = 1200, 14
TZ = dt.timezone(dt.timedelta(hours=2))
VARIABLES = ["px_n_lect", "px_ret_naiss", "px_dd_max", "px_depuis_min", "px_t_depuis_max", "px_vol",
             "q", "px_q_croiss", "px_ret_10", "px_ret_30", "px_ret_60", "px_ret_120",
             "px_q_croiss_30", "px_q_croiss_60", "px_lancements_10min", "px_heure", "V", "px_A"]


def schema(c):
    c.execute("CREATE TABLE IF NOT EXISTS decision("
              "  pair TEXT PRIMARY KEY, t_dec REAL, p REAL, seuil REAL, retenu INTEGER,"
              "  ret_240 REAL, n_entrainement INTEGER, t_modele REAL)")
    c.execute("CREATE TABLE IF NOT EXISTS gel(cle TEXT PRIMARY KEY, valeur TEXT)")
    c.commit()


def noter() -> None:
    import tout_table
    from sklearn.ensemble import RandomForestClassifier
    tout_table.main()
    df = pd.read_pickle(TABLE)
    df = df[(df["eligible"] == 1)].sort_values("t_dec").reset_index(drop=True)
    cols = [v for v in VARIABLES if v in df.columns and df[v].notna().sum() >= 100]

    os.makedirs(DOSSIER, exist_ok=True)
    c = sqlite3.connect(BASE_DB, timeout=60)
    schema(c)
    g = dict(c.execute("SELECT cle, valeur FROM gel"))
    if "t" not in g:
        # LE GEL : l instant ou la recette est figee. Tout ticket ne AVANT ne sera jamais juge --
        # il a servi a entrainer, le juger serait se noter soi-meme.
        g["t"] = str(time.time())
        c.execute("INSERT OR REPLACE INTO gel(cle,valeur) VALUES(?,?)", ("t", g["t"]))
        c.execute("INSERT OR REPLACE INTO gel(cle,valeur) VALUES(?,?)",
                  ("recette", json.dumps({"variables": cols, "arbres": 300, "feuille_min": 20,
                                          "garde": GARDE, "pas_h": PAS_H, "cout": COUT,
                                          "critere_n": N_CRITERE, "critere_jours": JOURS_CRITERE})))
        c.commit()
        print("foret_marche: RECETTE GELEE a %s · %d variables · critere %d tickets ou %d jours"
              % (dt.datetime.fromtimestamp(float(g["t"]), TZ).strftime("%d/%m %Hh%M"),
                 len(cols), N_CRITERE, JOURS_CRITERE), flush=True)
    gel = float(g["t"])

    X = df[cols].apply(pd.to_numeric, errors="coerce").astype(float)
    y = ((1.0 + pd.to_numeric(df["ret_240"], errors="coerce")) * (1.0 - COUT) - 1.0 <= -0.5)
    t = df["t_dec"].to_numpy(dtype=float)
    deja = {p for (p,) in c.execute("SELECT pair FROM decision")}

    # On avance coupe par coupe depuis le gel : a chaque coupe, entrainer sur TOUT ce qui precede
    # (avec un resultat connu), noter les tickets de la fenetre suivante. Aucun ticket n est note
    # par un modele qui l a vu.
    # ON NE JUGE QUE CE QUI NAIT APRES LE GEL. La premiere version partait de la coupe de 6 h qui
    # PRECEDE le gel : les poids restaient propres (chaque ticket etait note par un modele entraine
    # avant lui) mais la RECETTE, elle, avait ete choisie a 21h23 en connaissant deja le resultat du
    # test de marche avant. Juger des tickets anterieurs, c est se noter sur une periode qu on a
    # regardee -- l erreur exacte du frein (§3.125) et de la bande (§3.104). On part donc a la
    # premiere coupe SUIVANT le gel, et les tickets d avant ne comptent jamais.
    depart = gel - (gel % (PAS_H * 3600)) + PAS_H * 3600
    fin = time.time()
    n_neufs = 0
    cur = depart
    while cur < fin:
        c0, c1 = cur, cur + PAS_H * 3600
        cur = c1
        A = (t < c0) & y.notna().to_numpy()
        J = (t >= c0) & (t < c1)
        if A.sum() < 300 or J.sum() == 0:
            continue
        neufs = [i for i in np.where(J)[0] if df.at[i, "pair"] not in deja]
        if not neufs:
            continue
        med = X[A].median()
        rf = RandomForestClassifier(n_estimators=300, min_samples_leaf=20, n_jobs=-1,
                                    random_state=0).fit(X[A].fillna(med).fillna(0),
                                                        y[A].astype(int))
        p = rf.predict_proba(X.iloc[neufs].fillna(med).fillna(0))[:, 1]
        seuil = float(np.quantile(rf.predict_proba(X[A].fillna(med).fillna(0))[:, 1], GARDE))
        for k, i in enumerate(neufs):
            r = df.at[i, "ret_240"]
            c.execute("INSERT OR REPLACE INTO decision VALUES(?,?,?,?,?,?,?,?)",
                      (df.at[i, "pair"], float(t[i]), float(p[k]), seuil,
                       int(p[k] <= seuil), None if pd.isna(r) else float(r),
                       int(A.sum()), c0))
            n_neufs += 1
        c.commit()

    # renseigner les resultats devenus connus
    maj = 0
    for pair, in list(c.execute("SELECT pair FROM decision WHERE ret_240 IS NULL")):
        s = df.loc[df["pair"] == pair, "ret_240"]
        if len(s) and pd.notna(s.iloc[0]):
            c.execute("UPDATE decision SET ret_240=? WHERE pair=?", (float(s.iloc[0]), pair))
            maj += 1
    c.commit()
    juger(c, gel)
    c.close()
    print("foret_marche: %d ticket(s) note(s), %d resultat(s) renseigne(s)" % (n_neufs, maj), flush=True)


def juger(c, gel: float) -> None:
    L = list(c.execute("SELECT t_dec, p, seuil, retenu, ret_240 FROM decision"
                       " WHERE ret_240 IS NOT NULL ORDER BY t_dec"))
    if len(L) < 50:
        print("foret_marche: %d tickets avec resultat, trop peu pour juger" % len(L), flush=True)
        return
    net = np.array([(1.0 + r) * (1.0 - COUT) - 1.0 for _, _, _, _, r in L])
    pris = np.array([bool(x[3]) for x in L])
    n, k = len(net), int(pris.sum())
    jours = (time.time() - gel) / 86400.0
    print("foret_marche: %d retenus sur %d depuis le gel (critere %d ou %d jours ; jour %.2f)"
          % (k, n, N_CRITERE, JOURS_CRITERE, jours), flush=True)
    if k < 20:
        return
    v = net[pris]
    ecart = MISE * (v.mean() - net.mean())
    s = np.sort(v)
    sans3 = MISE * (s[:-3].mean() - net.mean())
    mi = k // 2
    h1 = MISE * (v[:mi].mean() - net.mean())
    h2 = MISE * (v[mi:].mean() - net.mean())
    sigma = MISE * net.std(ddof=1)
    bruit = sigma * np.sqrt((n - k) / (n * k)) if 0 < k < n else float("inf")
    print("   contre le temoin %+0.3f · sans 3 %+0.3f · moities %+0.3f / %+0.3f · %.2f sigma"
          % (ecart, sans3, h1, h2, ecart / bruit if bruit else 0), flush=True)
    if k >= N_CRITERE or jours >= JOURS_CRITERE:
        ok = [ecart > 0, sans3 > 0, h1 > 0 and h2 > 0, ecart > 2 * bruit]
        print("   CRITERE ATTEINT · (a) %s · (b) %s · (c) %s · (d) %s -> %s"
              % (*["OUI" if x else "NON" for x in ok],
                 "LA METHODE TIENT" if all(ok) else "METHODE ABANDONNEE"), flush=True)


def main() -> None:
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    while True:
        try:
            noter()
        except Exception as e:  # noqa: BLE001
            print("foret_marche: %s" % str(e)[:250], flush=True)
        time.sleep(PAS_H * 3600 / 6)          # on repasse toutes les heures, on note ce qui est mur


if __name__ == "__main__":
    main()
