"""FORET 75s REENTRAINEE : la recette du gel 75s, mais les poids ET LE SEUIL se refont toutes les 6 h.

MIDO, 19/09 22h50 : « on peut essayer de reentrainer le modele 75 ? » — puis, devant le resultat et
le defaut qu il avait fait voir, 23h30 : « oui vasy ».

CE QUI EST GELE ICI, ET CE QUI NE L EST PAS. Comme `foret_marche` (45 s), ce n est pas un modele qui
est fige mais une RECETTE : les variables, les reglages, la cadence, la facon de decider. Les poids
se refont toutes les 6 h sur tout ce qui precede. « Une regle qui se reentraine n est pas gelee »
(§ foret_gel) — ce qui est non renegociable, c est la recette ci-dessous, ecrite AVANT le premier
ticket juge.

    population    decision a 75 s, transactions <= 60 s, entree au dernier prix <= 77 s
    variables     les 95 de toutes les sources, reduites aux 25 plus utiles A CHAQUE COUPE
    modele        RandomForest, 300 arbres, min_samples_leaf = 20, random_state = 0
    cible         GAGNANT NET : (1 + ret_240).(1 - cout) - 1 > 0
    cadence       reentrainement toutes les 6 h sur TOUT ce qui precede la coupe
    decision      SEUIL ABSOLU : quantile 0,80 des scores d ENTRAINEMENT (« top 20 % »)
    cout          3,71 pt

POURQUOI LE SEUIL ABSOLU, ET PAS UN CLASSEMENT. C est le defaut trouve le 19/09 au soir (§3.158) :
garder « les 20 % du haut de la fenetre » demande de connaitre les tickets a venir. Un seuil absolu
se compare ticket par ticket, a un nombre connu d avance. Le nombre de tickets retenus varie alors
d une fenetre a l autre, et c est le vrai comportement de la regle — pas un defaut.

CE QUI A ETE MESURE, ET CE QUI NE L A PAS ETE. En marche avant sur 1 586 tickets temoin :
+1,507 EUR/ticket contre le temoin, +3,09 ecarts-types, 1 tirage sur 40 fait aussi bien (p ~ 0,049).
Sur la ligne, pas au-dela. Le NIVEAU (~+1,0 EUR/ticket) n est qu a ~1,9 sigma de zero — donc NON
PROUVE, et c est le niveau qui paie (regle 4). DEUX AVEUX qu il faut ecrire ici plutot que decouvrir
plus tard : (1) le taux de 20 % a ete choisi PARCE QU IL A GAGNE parmi trois taux essayes — c est
exactement pourquoi il faut des tickets jamais regardes ; (2) le cout de 3,71 pt est mesure a 45 s,
l entree a 77 s n est pas la meme population et son cout n a pas encore ete mesure separement.

LE CRITERE, FIGE AVANT LE PREMIER TICKET. Au premier atteint de 400 tickets RETENUS ou de 14 jours,
les CINQ doivent tenir :
    (a) battre le temoin sur sa propre periode ;
    (b) le battre encore sans ses 3 meilleurs tickets ;
    (c) etre positive contre le temoin sur les DEUX moities chronologiques ;
    (d) l ecart depasse 2 fois son bruit — sigma.racine((n-k)/(n.k)), comparaison appariee ;
    (e) LE NIVEAU est positif et depasse 2 fois SON bruit — sigma/racine(k). C est la condition
        qui decide de l argent ; les quatre autres ne parlent que du classement.
400 n est pas un chiffre rond : a +1,0 EUR/ticket de niveau et sigma ~ 9,7 EUR, il faut ~376 tickets
retenus pour que (e) soit seulement ATTEIGNABLE. En dessous le critere serait impossible a
satisfaire et l attente une comedie. Au rythme observe (~453 tickets temoin/jour, 20 % gardes) cela
fait ~4,5 jours.

Papier, zero euro. Base propre. Ne touche ni au moteur, ni aux collecteurs, ni aux autres gels.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
import sys
import time
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
os.environ.setdefault("AGE_DECISION", "75")

DOSSIER = os.environ.get("CARNET75_DIR", "/app/data/recherche/foret75_carnet")
BASE_DB = os.path.join(DOSSIER, "carnet.sqlite")
COUT = float(os.environ.get("COUT_MESURE", "0.0371"))
MISE = 20.0
GARDE = 0.20                       # on retient les 20 % les plus surs, au seuil d entrainement
GARDE_LECTURE = 0.10               # le second seuil, NOTE A COTE et qui ne decide rien (_apprendre)
N_VARIABLES = 25
PAS_H = 6.0
N_CRITERE, JOURS_CRITERE = 400, 14
TZ = dt.timezone(dt.timedelta(hours=2))


def schema(c: sqlite3.Connection) -> None:
    c.execute("CREATE TABLE IF NOT EXISTS decision("
              "  pair TEXT PRIMARY KEY, mint TEXT, t_dec REAL, p REAL, seuil REAL, retenu INTEGER,"
              "  ret_240 REAL, n_entrainement INTEGER, t_modele REAL)")
    for col in ("seuil10 REAL", "retenu10 INTEGER"):
        try:
            c.execute("ALTER TABLE decision ADD COLUMN %s" % col)
        except Exception:  # noqa: BLE001
            pass        # deja la
    c.execute("CREATE TABLE IF NOT EXISTS gel(cle TEXT PRIMARY KEY, valeur TEXT)")
    c.commit()


def _apprendre(X: pd.DataFrame, y: np.ndarray, cols: list[str]):
    """La recette : une foret pour classer les variables, les 25 meilleures, une seconde foret.

    Rend le SEUIL avec le modele — quantile (1 - GARDE) des scores d entrainement. Il est calcule
    sur le passe strict de la fenetre jugee, donc connu avant elle, donc decidable ticket par ticket.
    """
    from sklearn.ensemble import RandomForestClassifier

    def foret(n):
        return RandomForestClassifier(n_estimators=n, min_samples_leaf=20, n_jobs=-1, random_state=0)

    med = X[cols].median()
    XA = X[cols].fillna(med).fillna(0.0)
    imp = foret(200).fit(XA, y).feature_importances_
    gard = [c for _, c in sorted(zip(imp, cols), key=lambda z: -z[0])[:N_VARIABLES]]
    rf = foret(300).fit(XA[gard], y)
    p_tr = rf.predict_proba(XA[gard])[:, 1]
    # LE SEUIL A 10 %, NOTE A COTE, POUR LECTURE -- il ne decide RIEN. Meme dispositif que
    # `foret_gel` depuis le 18/09 (« le seuil a 10 % est note a cote pour lecture, pas pour
    # decision »). MIDO, 20/09 : « on a une strat 75s top 10 reentrainee ? ». Non -- et j avais
    # choisi 20 % PARCE QU ELLE GAGNAIT parmi trois taux essayes, sur un ecart de 0,16 EUR/ticket
    # quand le bruit de ces cases vaut 0,5. J ai donc tranche sur du bruit et ferme la porte a
    # l autre. Noter le second seuil ne modifie aucune decision et rouvre la porte.
    return rf, med[gard], gard, (float(np.quantile(p_tr, 1.0 - GARDE)),
                                 float(np.quantile(p_tr, 1.0 - GARDE_LECTURE)))


def noter() -> None:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import foret_gel as G

    df, cols = G.table()
    df = df.sort_values("t_dec").reset_index(drop=True)
    X = df[cols].apply(pd.to_numeric, errors="coerce").astype(float)
    t = df["t_dec"].to_numpy(dtype=float)
    r = pd.to_numeric(df["ret_240"], errors="coerce").to_numpy(dtype=float)
    net = (1.0 + r) * (1.0 - COUT) - 1.0
    y = (net > 0).astype(int)
    connu = np.isfinite(net)

    os.makedirs(DOSSIER, exist_ok=True)
    c = sqlite3.connect(BASE_DB, timeout=60)
    schema(c)
    g = dict(c.execute("SELECT cle, valeur FROM gel"))
    if "t" not in g:
        # LE GEL : l instant ou la recette est figee. Tout ticket ne AVANT ne sera jamais juge --
        # il a servi a la mesurer, le juger serait se noter soi-meme (§3.125, §3.104).
        g["t"] = str(time.time())
        c.execute("INSERT OR REPLACE INTO gel VALUES(?,?)", ("t", g["t"]))
        c.execute("INSERT OR REPLACE INTO gel VALUES(?,?)", ("recette", json.dumps(
            {"age_decision": 75, "n_variables": N_VARIABLES, "arbres": 300, "feuille_min": 20,
             "garde": GARDE, "decision": "seuil absolu, quantile des scores d entrainement",
             "pas_h": PAS_H, "cout": COUT, "critere_n": N_CRITERE,
             "critere_jours": JOURS_CRITERE, "variables_disponibles": len(cols)})))
        c.commit()
        print("foret75_carnet: RECETTE GELEE a %s · %d variables disponibles · critere %d retenus"
              " ou %d jours" % (dt.datetime.fromtimestamp(float(g["t"]), TZ).strftime("%d/%m %Hh%M"),
                                len(cols), N_CRITERE, JOURS_CRITERE), flush=True)
    gel = float(g["t"])

    deja = {p for (p,) in c.execute("SELECT pair FROM decision")}
    # ON NE JUGE QUE CE QUI NAIT APRES LE GEL, et on part de la premiere coupe qui le suit.
    cur = gel - (gel % (PAS_H * 3600)) + PAS_H * 3600
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
        rf, med, gard, (seuil, seuil10) = _apprendre(X[A], y[A], cols)
        p = rf.predict_proba(X.iloc[neufs][gard].fillna(med).fillna(0.0))[:, 1]
        for k, i in enumerate(neufs):
            c.execute("INSERT OR REPLACE INTO decision(pair, mint, t_dec, p, seuil, retenu,"
                      " ret_240, n_entrainement, t_modele, seuil10, retenu10)"
                      " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                      (df.at[i, "pair"], df.at[i, "mint"], float(t[i]), float(p[k]), seuil,
                       int(p[k] >= seuil), None if not connu[i] else float(r[i]),
                       int(A.sum()), c0, seuil10, int(p[k] >= seuil10)))
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
    print("foret75_carnet: %d ticket(s) note(s), %d resultat(s) renseigne(s)" % (n_neufs, maj),
          flush=True)


def juger(c: sqlite3.Connection, gel: float) -> None:
    L = list(c.execute("SELECT retenu, ret_240 FROM decision WHERE ret_240 IS NOT NULL"
                       " ORDER BY t_dec"))
    if len(L) < 50:
        print("foret75_carnet: %d tickets avec resultat, trop peu pour juger" % len(L), flush=True)
        return
    net = np.array([(1.0 + x[1]) * (1.0 - COUT) - 1.0 for x in L])
    pris = np.array([bool(x[0]) for x in L])
    n, k = len(net), int(pris.sum())
    jours = (time.time() - gel) / 86400.0
    print("foret75_carnet: %d retenus sur %d depuis le gel (critere %d ou %d jours ; jour %.2f)"
          % (k, n, N_CRITERE, JOURS_CRITERE, jours), flush=True)
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
    print("   NIVEAU %+0.3f EUR/ticket (%.2f sig) — c est lui qui paie"
          % (niveau, niveau / bruit_niv if bruit_niv else 0), flush=True)
    if k >= N_CRITERE or jours >= JOURS_CRITERE:
        ok = [ecart > 0, sans3 > 0, h1 > 0 and h2 > 0, ecart > 2 * bruit, niveau > 2 * bruit_niv]
        print("   CRITERE ATTEINT · (a) %s · (b) %s · (c) %s · (d) %s · (e) %s -> %s"
              % (*["OUI" if x else "NON" for x in ok],
                 "LA RECETTE TIENT" if all(ok) else "RECETTE ABANDONNEE"), flush=True)


def main() -> None:
    while True:
        try:
            noter()
        except Exception as e:  # noqa: BLE001
            print("foret75_carnet: %s" % str(e)[:250], flush=True)
        time.sleep(PAS_H * 3600 / 6)          # on repasse toutes les heures, on note ce qui est mur


if __name__ == "__main__":
    main()
