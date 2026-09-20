"""FORET GAGNANT 20 % : la bonne question, posee au meme instant que le moteur.

MIDO, 20/09 : « OUI OUI vas-y, tu penses que tu vas me dire j'ai trouve probablement une meilleure
piste et je te dirai non ? ». Il a raison : un carnet papier ne coute rien, c'est un arbitrage de
recherche, pas une decision d'argent.

POURQUOI CELUI-CI. §3.159 : les trois regles du projet qui apprenaient le VIDAGE (`net_240 <= -50 %`)
selectionnent l'IMMOBILITE, parce que le moyen le plus sur de ne pas s'effondrer est de ne pas
bouger. Mesure : leur cinquieme le plus sur bouge de 3,1 % quand le peage est de 3,71 % -- il monte
de 2,2 %, on paie 3,71 %, on perd. C'est une soustraction, pas une statistique. La cible « gagnant
net » contient deja « pas d'effondrement » (un jeton effondre n'est jamais gagnant) et n'a pas ce
defaut : elle retire 4 vidages sur 10 la ou « vidage » n'en retire que 2.

CE QUI EST GELE : UNE RECETTE, pas des poids. Ecrite avant le premier ticket juge.
    population    decision a 45 s, comme le moteur en production
    variables     les 18 de prix et de liquidite, SANS aucune variable de cout (§3.157)
    modele        RandomForest, 300 arbres, min_samples_leaf = 20, random_state = 0
    cible         GAGNANT NET : (1 + ret_240).(1 - cout) - 1 > 0
    cadence       reentrainement toutes les 6 h sur TOUT ce qui precede la coupe
    decision      SEUIL ABSOLU : on garde les scores >= quantile 0,80 de l'ENTRAINEMENT
    cout          3,71 pt

CE QUI A ETE MESURE, ET CE QUI NE L'A PAS ETE. En marche avant sur 2 633 tickets temoin :
+0,470 EUR/ticket en ARGENT (le temoin perd -0,496), +0,966 contre le temoin, +2,52 sigma, et
POSITIF SUR LES DEUX MOITIES chronologiques (+1,13 et +0,82) -- le test qui avait tue le frein.
MAIS **p = 0,115** contre une barre du hasard qui corrige les neuf cases regardees : NON PROUVE.
C'est exactement pour ca que ce carnet existe : les 578 tickets du test, je les ai deja vus.

LE CRITERE, FIGE AVANT LE PREMIER TICKET, et il a DEUX echeances parce que les deux questions ne
demandent pas le meme nombre de tickets -- sigma vaut 10,43 EUR par ticket a 20 EUR de mise :
  ECHEANCE 1, a 400 tickets RETENUS (~2 000 temoin, ~3 jours) -- « fait-elle mieux que le marche ? »
    (a) battre le temoin sur sa propre periode ;
    (b) le battre encore sans ses 3 meilleurs tickets ;
    (c) etre positive contre le temoin sur les DEUX moities chronologiques ;
    (d) l'ecart depasse 2 fois son bruit apparie, sigma.racine((n-k)/(n.k)) ;
    (e) le NIVEAU est positif (positif seulement : le prouver demande l'echeance 2).
    Les cinq, sinon la piste est abandonnee et ecrite comme telle.
  ECHEANCE 2, a 2 000 tickets RETENUS (~16 jours) -- « gagne-t-elle de l'argent ? »
    (f) le NIVEAU depasse 2 fois SON bruit, sigma/racine(k). A +0,470 EUR/ticket il faut
        k > 1 971 : c'est le prix de la preuve, et aucune echeance plus courte ne peut la donner.
  Dire « prouvee » avant l'echeance 2 serait mentir : l'echeance 1 ne juge qu'un classement, et un
  classement ne paie rien (regle 4). Voir `VIDAGE 80 %` : meilleur sigma du test, et -0,204 EUR.

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

DOSSIER = os.environ.get("GAGNANT_DIR", "/app/data/recherche/foret_gagnant")
BASE_DB = os.path.join(DOSSIER, "carnet.sqlite")
TABLE = "/app/data/recherche/tout/table.pkl"
COUT = float(os.environ.get("COUT_MESURE", "0.0371"))
MISE = 20.0
GARDE = 0.20
PAS_H = 6.0
N_ECHEANCE_1, N_ECHEANCE_2, JOURS_MAX = 400, 2000, 21
TZ = dt.timezone(dt.timedelta(hours=2))
VARIABLES = ["px_n_lect", "px_ret_naiss", "px_dd_max", "px_depuis_min", "px_t_depuis_max", "px_vol",
             "q", "px_q_croiss", "px_ret_10", "px_ret_30", "px_ret_60", "px_ret_120",
             "px_q_croiss_30", "px_q_croiss_60", "px_lancements_10min", "px_heure", "V", "px_A"]


def schema(c: sqlite3.Connection) -> None:
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
    df = df[df["eligible"] == 1].sort_values("t_dec").reset_index(drop=True)
    cols = [v for v in VARIABLES if v in df.columns and df[v].notna().sum() >= 100]

    os.makedirs(DOSSIER, exist_ok=True)
    c = sqlite3.connect(BASE_DB, timeout=60)
    schema(c)
    g = dict(c.execute("SELECT cle, valeur FROM gel"))
    if "t" not in g:
        g["t"] = str(time.time())
        c.execute("INSERT OR REPLACE INTO gel VALUES(?,?)", ("t", g["t"]))
        c.execute("INSERT OR REPLACE INTO gel VALUES(?,?)", ("recette", json.dumps(
            {"cible": "gagnant net", "variables": cols, "arbres": 300, "feuille_min": 20,
             "garde": GARDE, "decision": "seuil absolu, quantile 0,80 des scores d entrainement",
             "pas_h": PAS_H, "cout": COUT, "echeance_1": N_ECHEANCE_1,
             "echeance_2": N_ECHEANCE_2, "jours_max": JOURS_MAX})))
        c.commit()
        print("foret_gagnant: RECETTE GELEE a %s · %d variables · echeances %d puis %d retenus"
              % (dt.datetime.fromtimestamp(float(g["t"]), TZ).strftime("%d/%m %Hh%M"),
                 len(cols), N_ECHEANCE_1, N_ECHEANCE_2), flush=True)
    gel = float(g["t"])

    X = df[cols].apply(pd.to_numeric, errors="coerce").astype(float)
    r = pd.to_numeric(df["ret_240"], errors="coerce").to_numpy(dtype=float)
    net = (1.0 + r) * (1.0 - COUT) - 1.0
    y = (net > 0).astype(int)                     # LA CIBLE : gagnant net, et rien d autre
    connu = np.isfinite(net)
    t = df["t_dec"].to_numpy(dtype=float)
    deja = {p for (p,) in c.execute("SELECT pair FROM decision")}

    cur = gel - (gel % (PAS_H * 3600)) + PAS_H * 3600      # on ne juge que l apres-gel
    fin = time.time()
    n_neufs = 0
    while cur < fin:
        c0, c1 = cur, cur + PAS_H * 3600
        cur = c1
        A = (t < c0) & connu
        J = (t >= c0) & (t < c1)
        if A.sum() < 300 or J.sum() == 0:
            continue
        neufs = [i for i in np.where(J)[0] if df.at[i, "pair"] not in deja]
        if not neufs:
            continue
        med = X[A].median()
        XA = X[A].fillna(med).fillna(0.0)
        rf = RandomForestClassifier(n_estimators=300, min_samples_leaf=20, n_jobs=-1,
                                    random_state=0).fit(XA, y[A])
        # SEUIL ABSOLU pris sur l entrainement : connu avant la fenetre, donc decidable ticket par
        # ticket. On garde les scores les plus HAUTS -- ici la classe 1 est ce qu on cherche.
        seuil = float(np.quantile(rf.predict_proba(XA)[:, 1], 1.0 - GARDE))
        p = rf.predict_proba(X.iloc[neufs].fillna(med).fillna(0.0))[:, 1]
        for k, i in enumerate(neufs):
            c.execute("INSERT OR REPLACE INTO decision VALUES(?,?,?,?,?,?,?,?)",
                      (df.at[i, "pair"], float(t[i]), float(p[k]), seuil, int(p[k] >= seuil),
                       float(r[i]) if connu[i] else None, int(A.sum()), c0))
            n_neufs += 1
        c.commit()

    maj = 0
    res = pd.Series(r, index=df["pair"])
    for (pair,) in list(c.execute("SELECT pair FROM decision WHERE ret_240 IS NULL")):
        if pair in res.index and np.isfinite(res[pair]):
            c.execute("UPDATE decision SET ret_240=? WHERE pair=?", (float(res[pair]), pair))
            maj += 1
    c.commit()
    juger(c, gel)
    c.close()
    print("foret_gagnant: %d ticket(s) note(s), %d resultat(s) renseigne(s)" % (n_neufs, maj),
          flush=True)


def juger(c: sqlite3.Connection, gel: float) -> None:
    L = list(c.execute("SELECT retenu, ret_240 FROM decision WHERE ret_240 IS NOT NULL"
                       " ORDER BY t_dec"))
    if len(L) < 50:
        print("foret_gagnant: %d tickets avec resultat, trop peu pour juger" % len(L), flush=True)
        return
    net = np.array([(1.0 + x[1]) * (1.0 - COUT) - 1.0 for x in L])
    pris = np.array([bool(x[0]) for x in L])
    n, k = len(net), int(pris.sum())
    jours = (time.time() - gel) / 86400.0
    print("foret_gagnant: %d retenus sur %d depuis le gel (echeances %d puis %d ; jour %.2f)"
          % (k, n, N_ECHEANCE_1, N_ECHEANCE_2, jours), flush=True)
    if k < 20:
        return
    v = net[pris]
    sigma = MISE * net.std(ddof=1)
    ecart = MISE * (v.mean() - net.mean())
    niveau = MISE * v.mean()
    s = np.sort(v)
    mi = k // 2
    h1 = MISE * (v[:mi].mean() - net.mean())
    h2 = MISE * (v[mi:].mean() - net.mean())
    sans3 = MISE * (s[:-3].mean() - net.mean())
    bruit = sigma * np.sqrt((n - k) / (n * k)) if 0 < k < n else float("inf")
    bruit_niv = sigma / np.sqrt(k)
    print("   contre temoin %+0.3f (%.2f sig) · sans 3 %+0.3f · moities %+0.3f / %+0.3f"
          % (ecart, ecart / bruit if bruit else 0, sans3, h1, h2), flush=True)
    print("   NIVEAU %+0.3f EUR/ticket (%.2f sig) — la seule colonne qui paie"
          % (niveau, niveau / bruit_niv if bruit_niv else 0), flush=True)
    if k >= N_ECHEANCE_1 or jours >= JOURS_MAX:
        ok = [ecart > 0, sans3 > 0, h1 > 0 and h2 > 0, ecart > 2 * bruit, niveau > 0]
        print("   ECHEANCE 1 · (a) %s · (b) %s · (c) %s · (d) %s · (e) %s -> %s"
              % (*["OUI" if x else "NON" for x in ok],
                 "elle trie mieux que le marche" if all(ok) else "PISTE ABANDONNEE"), flush=True)
    if k >= N_ECHEANCE_2:
        print("   ECHEANCE 2 · le NIVEAU depasse-t-il 2 fois son bruit ? %s"
              % ("OUI -- ELLE GAGNE DE L ARGENT" if niveau > 2 * bruit_niv else "NON"), flush=True)


def main() -> None:
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    while True:
        try:
            noter()
        except Exception as e:  # noqa: BLE001
            print("foret_gagnant: %s" % str(e)[:250], flush=True)
        time.sleep(PAS_H * 3600 / 6)


if __name__ == "__main__":
    main()
