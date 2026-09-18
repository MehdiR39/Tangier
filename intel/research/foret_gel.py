"""FORET DE GAIN, 25 VARIABLES, TOP 5 % -- GELEE le 19/09/2026 a 04h30 Paris. Papier, zero euro.

AMENDEMENT AVANT LE PREMIER TICKET. Gelee a 04h00 sur les 72 variables ; a 04h30, AUCUN ticket
n avait encore ete note (le premier passage ne fait qu entrainer). Mido : « go 1 » -- moins de
variables. La seule modification de modelisation qui ait aide en marche avant (§3.136 : selection
des 25 plus utiles a chaque coupe, +1,89 % contre +1,05 %, sans-3 -0,54 contre -1,30). Regle
amendee et gel re-date, sans qu aucune donnee posterieure au gel n ait ete regardee.

CE QUI EST GELE, ET POURQUOI CELUI-LA. Apres quatre jours ou tout s est effondre hors echantillon,
une chose a tenu : une foret entrainee a reconnaitre « net_240 > 0 apres le cout reel de 6,55 »
sur les 107 variables de toutes les sources classe gagnants et perdants avec un AUC de 0,65 a
0,82 sur 9 fenetres sur 9, chacune au-dessus du maximum de 20 permutations (§3.139). Le classement
est reel. En argent, une seule cellule est positive sans ses 3 meilleurs tickets : les 5 % les plus
surs, +4,40 % par ticket, 91 % de gagnants, 58 tickets, p ~ 0,12 (§3.140). Changer de modele
(§3.136) ou de cible (§3.141) ne l ameliore pas. Seuls des tickets peuvent la confirmer ou la tuer.

LA REGLE, EXECUTABLE ET CAUSALE.
  Toutes les PAS_H heures :
    1. rebatir la table unique (tout_table) ;
    2. NOTER les tickets nes depuis le dernier passage avec le modele sauve AU PASSAGE PRECEDENT --
       donc entraine avant leur naissance : c est la marche avant, faite en avant ;
    3. renseigner le resultat (ret_240) des tickets notes qui l ont maintenant ;
    4. reentrainer sur tout ce qui precede, calculer les seuils (quantiles 0,95 et 0,90 des scores
       d ENTRAINEMENT), sauver pour le passage suivant.
  Un ticket est RETENU si sa probabilite >= seuil des 5 % les plus surs. Le seuil a 10 % est note
  a cote pour lecture, pas pour decision.
  Seuls les tickets AVEC donnees de transactions sont notes (le collecteur v1 s arrete au quota).

LE CRITERE, FIGE AVANT LES DONNEES, au premier atteint de 250 tickets retenus ou de 21 jours :
  (a) net moyen > 0 au cout 6,55 ;
  (b) positif sans ses 3 meilleurs tickets ;
  (c) positif sur les deux moities chronologiques ;
  (d) au moins 80 % de gagnants ;
  (e) au-dessus de 200 permutations des resultats (95e centile).
  Les cinq, sinon la piste est abandonnee et ecrite comme telle.

CE QUI NE CHANGE PAS. Aucun euro. Base propre (papier_foret.sqlite). Ne lit les autres bases qu en
lecture seule. Ne touche ni au moteur, ni aux collecteurs, ni aux autres gels.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
import warnings

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

GEL = 1789785000.0                    # 19/09/2026 02h30 UTC = 04h30 Paris (amende, voir en-tete)
N_VARIABLES = 25                      # les 25 plus utiles sur le passe, a chaque reentrainement
DOSSIER = "/app/data/recherche/foret_gel"
TABLE = "/app/data/recherche/tout/table.pkl"
BASE = "/app/db/papier_foret.sqlite"
COUT = 0.0655
PAS_H = 6
N_CRITERE, JOURS_CRITERE = 250, 21
EXCLUES = {"tg_poste"}


def schema(c: sqlite3.Connection) -> None:
    c.executescript("""
        CREATE TABLE IF NOT EXISTS decision(
            pair TEXT PRIMARY KEY, mint TEXT, t_dec REAL, p REAL, seuil05 REAL, seuil10 REAL,
            retenu05 INTEGER, retenu10 INTEGER, modele_t REAL, ret_240 REAL, net REAL);
        CREATE TABLE IF NOT EXISTS meta(cle TEXT PRIMARY KEY, valeur TEXT);
    """)
    c.commit()


def table() -> tuple[pd.DataFrame, list[str]]:
    import tout_table
    tout_table.main()
    df = pd.read_pickle(TABLE)
    variables = [v for v in df.attrs["VARIABLES"] if v not in EXCLUES]
    df = df[(df["eligible"] == 1) & df["v1_n_achats"].notna()].sort_values("t_dec").reset_index(drop=True)
    X = df[variables].apply(pd.to_numeric, errors="coerce").astype(float)
    garde = [v for v in variables if X[v].notna().sum() >= 100 and X[v].nunique(dropna=True) >= 2]
    df[garde] = X[garde]
    return df, garde


def entrainer(df: pd.DataFrame, garde: list[str], now: float) -> None:
    A = df[(df["t_dec"] < now) & df["ret_240"].notna()]
    if len(A) < 300:
        print("foret_gel: %d tickets, trop peu pour entrainer" % len(A), flush=True)
        return
    med = A[garde].median()
    XA = A[garde].fillna(med).fillna(0.0)
    y = (((1 + A["ret_240"]) * (1 - COUT) - 1) > 0).astype(int).to_numpy()
    # SELECTION SUR LE PASSE SEULEMENT : une premiere foret sur toutes les variables donne leur
    # utilite, on garde les 25 premieres, on reentraine dessus. Le jugement ne voit que la seconde.
    rf0 = RandomForestClassifier(n_estimators=200, min_samples_leaf=20, n_jobs=-1, random_state=0).fit(XA, y)
    garde = [g for _, g in sorted(zip(rf0.feature_importances_, garde), reverse=True)[:N_VARIABLES]]
    XA = XA[garde]
    med = med[garde]
    rf = RandomForestClassifier(n_estimators=300, min_samples_leaf=20, n_jobs=-1, random_state=0).fit(XA, y)
    p_tr = rf.predict_proba(XA)[:, 1]
    seuils = {"seuil05": float(np.quantile(p_tr, 0.95)), "seuil10": float(np.quantile(p_tr, 0.90)),
              "modele_t": now, "n_entrainement": int(len(A)), "garde": garde}
    os.makedirs(DOSSIER, exist_ok=True)
    joblib.dump({"rf": rf, "med": med}, os.path.join(DOSSIER, "modele.pkl"))
    json.dump(seuils, open(os.path.join(DOSSIER, "seuils.json"), "w"))
    print("foret_gel: modele entraine sur %d tickets · %d variables · seuil 5 %% = %.3f · seuil 10 %% = %.3f"
          % (len(A), len(garde), seuils["seuil05"], seuils["seuil10"]), flush=True)
    print("foret_gel: variables gardees : %s" % ", ".join(garde), flush=True)


def noter(c: sqlite3.Connection, df: pd.DataFrame) -> int:
    """Note les tickets nes depuis le modele sauve, avec CE modele (entraine avant eux)."""
    chemin = os.path.join(DOSSIER, "modele.pkl")
    if not os.path.exists(chemin):
        return 0
    m = joblib.load(chemin)
    s = json.load(open(os.path.join(DOSSIER, "seuils.json")))
    garde = s["garde"]
    deja = {p for (p,) in c.execute("SELECT pair FROM decision")}
    N = df[(df["t_dec"] >= s["modele_t"]) & ~df["pair"].isin(deja)]
    if N.empty:
        return 0
    XN = N[garde].fillna(m["med"]).fillna(0.0)
    p = m["rf"].predict_proba(XN)[:, 1]
    for (pair, mint, t), pi in zip(N[["pair", "mint", "t_dec"]].itertuples(index=False), p):
        c.execute("INSERT OR IGNORE INTO decision(pair, mint, t_dec, p, seuil05, seuil10, retenu05, retenu10, modele_t)"
                  " VALUES(?,?,?,?,?,?,?,?,?)",
                  (pair, mint, float(t), float(pi), s["seuil05"], s["seuil10"],
                   int(pi >= s["seuil05"]), int(pi >= s["seuil10"]), s["modele_t"]))
    c.commit()
    return len(N)


def resultats(c: sqlite3.Connection, df: pd.DataFrame) -> None:
    connu = df[df["ret_240"].notna()].set_index("pair")["ret_240"]
    for (pair,) in c.execute("SELECT pair FROM decision WHERE ret_240 IS NULL").fetchall():
        if pair in connu.index:
            r = float(connu[pair])
            c.execute("UPDATE decision SET ret_240 = ?, net = ? WHERE pair = ?", (r, (1 + r) * (1 - COUT) - 1, pair))
    c.commit()


def rapport(c: sqlite3.Connection) -> None:
    rows = c.execute("SELECT t_dec, net FROM decision WHERE retenu05 = 1 AND net IS NOT NULL ORDER BY t_dec").fetchall()
    n = len(rows)
    jours = (time.time() - GEL) / 86400.0
    print("foret_gel: %d ticket(s) retenus depuis le gel (critere %d ou %d jours ; jour %.1f)"
          % (n, N_CRITERE, JOURS_CRITERE, jours), flush=True)
    if n < 10:
        return
    v = np.array([x[1] for x in rows])
    s = np.sort(v)
    h = n // 2
    a = v.mean() > 0
    b = s[:-3].mean() > 0
    cc = v[:h].mean() > 0 and v[h:].mean() > 0
    d = (v > 0).mean() >= 0.80
    print("   net %+.2f %% · sans3 %+.2f %% · moities %+.2f / %+.2f · gagnants %.0f %%"
          % (100 * v.mean(), 100 * s[:-3].mean(), 100 * v[:h].mean(), 100 * v[h:].mean(), 100 * (v > 0).mean()))
    print("   (a) net > 0 : %s · (b) sans 3 : %s · (c) moities : %s · (d) >= 80 %% gagnants : %s"
          % tuple("oui" if x else "NON" for x in (a, b, cc, d)))
    if n >= N_CRITERE or jours >= JOURS_CRITERE:
        print("   -> ECHEANCE ATTEINTE : lancer la permutation (e) et ecrire le verdict au journal", flush=True)


def main() -> None:
    os.makedirs(DOSSIER, exist_ok=True)
    c = sqlite3.connect(BASE, timeout=30)
    schema(c)
    print("foret_gel: demarre · gel %s · pas %d h" % (time.strftime("%d/%m %H:%M", time.localtime(GEL)), PAS_H), flush=True)
    while True:
        t0 = time.time()
        try:
            df, garde = table()
            n = noter(c, df)
            resultats(c, df)
            entrainer(df, garde, t0)
            print("foret_gel: %d ticket(s) note(s) ce passage" % n, flush=True)
            rapport(c)
        except Exception as exc:  # noqa: BLE001
            print("foret_gel: passage rate (%s)" % str(exc)[:200], flush=True)
        time.sleep(max(60.0, PAS_H * 3600 - (time.time() - t0)))


if __name__ == "__main__":
    main()
