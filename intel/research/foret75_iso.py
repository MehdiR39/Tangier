"""FORET 75s ISO-MOTEUR : le meme modele gele, prive de ce que le moteur ne saura pas produire.

MIDO, 20/09 : « un truc en mode iso : ajoute le modele sans image, copie de celui de la prod, sans
supprimer celui qui tourne actuellement en iso prod, c est clair ? »

CE QUE C EST. Exactement le modele de `foret_gel75` -- gele le 18/09 23h10, jamais reentraine, on ne
le touche pas -- applique aux memes tickets, mais en remplacant par leur MEDIANE D APPRENTISSAGE les
variables que le moteur ne pourra pas calculer a 75 s. C est donc ce que la production ferait
vraiment, et non ce qu elle ferait dans un monde ou toutes les donnees arrivent a temps.

UNE SEULE VARIABLE MANQUE, ET C EST UNE CORRECTION. Ce carnet a d abord ete gele le 20/09 a 20h12
en privant le modele de SIX variables. Mido : « je comprends pourquoi tu as retire les images, c est
etudie ; pourquoi les autres variables ? ». Il avait raison de separer les deux cas :
    img_l, img_centre, img_h     retirees parce que MESUREES inutiles -- 0 % d importance par
                                 permutation, et en euros +0,97 sigma sur 18 tickets d ecart.
    v1_robots, v1_part_robots    je les avais retirees par CONFORT, en habillant le choix d une
                                 mesure. Verification : les fichiers de `v1_enregistreur` portent
                                 tout l historique (1 082 pools) -- le moteur peut construire la
                                 table portefeuille -> pools au demarrage et la tenir a jour avec
                                 les appels qu il fait de toute facon. FAISABLE, donc reprises.
    reg_moy_20                   idem : c est la moyenne des 20 derniers tickets CLOTURES, une
                                 requete SQL sur `mr_lignes`. FAISABLE, donc reprise.
Le carnet a ete regele avec les images seules absentes, a zero ticket, avant d avoir rien juge.

CE QUE LE REJEU DIT DEJA, et pourquoi ce carnet existe quand meme. Sur 2 675 tickets : avec tout
+0,936 EUR/ticket (397 retenus), sans les six +0,772 (427 retenus). L ecart tient a **18 tickets**,
+38,11 EUR pour un bruit de 39,25 -- **+0,97 sigma, rien de demontre**. Mais c est du REJEU, sur des
tickets deja regardes. Ce carnet le mesure en marche avant, sur des tickets neufs, a cote du carnet
complet qui continue de tourner. Les deux cote a cote diront ce qu un rejeu ne peut pas dire.

SEUIL : le top 10 %, valide par Mido le 20/09 apres avoir fait remarquer que mes totaux ne valaient
rien tant que les lignes ne partaient pas ensemble. Sur periode commune : top 10 % +0,462 EUR/ticket
sur 92 tickets, top 5 % -0,164 sur 24.

Papier, zero euro. Ne touche NI a `foret_gel75`, NI au moteur, NI a aucun autre gel.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
import sys
import time

import numpy as np
import pandas as pd

os.environ.setdefault("AGE_DECISION", "75")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SOURCE = "/app/data/recherche/foret_gel75"          # le modele gele, lu SEULEMENT
DOSSIER = os.environ.get("ISO75_DIR", "/app/data/recherche/foret75_iso")
BASE_DB = os.path.join(DOSSIER, "carnet.sqlite")
COUT = float(os.environ.get("COUT_MESURE", "0.0371"))
MISE = 20.0
PAS_H = 6.0
N_CRITERE, JOURS_CRITERE = 250, 21
TZ = dt.timezone(dt.timedelta(hours=2))
# ce que le MOTEUR ne saura pas produire a 75 s -> mediane d apprentissage, comme le pipeline le
# fait deja pour toute valeur absente.
ABSENTES = ("img_l", "img_centre", "img_h")


def schema(c: sqlite3.Connection) -> None:
    c.execute("CREATE TABLE IF NOT EXISTS decision("
              "  pair TEXT PRIMARY KEY, mint TEXT, t_dec REAL, p REAL, seuil REAL, retenu INTEGER,"
              "  ret_240 REAL)")
    c.execute("CREATE TABLE IF NOT EXISTS gel(cle TEXT PRIMARY KEY, valeur TEXT)")
    c.commit()


def noter() -> None:
    import joblib
    import foret_gel as G

    m = joblib.load(os.path.join(SOURCE, "modele.pkl"))
    s = json.load(open(os.path.join(SOURCE, "seuils.json"), encoding="utf-8"))
    rf, med, garde = m["rf"], m["med"], s["garde"]
    seuil = float(s["seuil10"])

    df, _ = G.table()
    df = df.sort_values("t_dec").reset_index(drop=True)
    X = df[garde].apply(pd.to_numeric, errors="coerce").astype(float).fillna(med).fillna(0.0)
    # LA SEULE DIFFERENCE AVEC `foret_gel75` : les six variables que le moteur n aura pas.
    absentes = [c for c in ABSENTES if c in garde]
    for c in absentes:
        X[c] = float(med[c])

    os.makedirs(DOSSIER, exist_ok=True)
    c = sqlite3.connect(BASE_DB, timeout=60)
    schema(c)
    g = dict(c.execute("SELECT cle, valeur FROM gel"))
    if "t" not in g:
        g["t"] = str(time.time())
        c.execute("INSERT OR REPLACE INTO gel VALUES(?,?)", ("t", g["t"]))
        c.execute("INSERT OR REPLACE INTO gel VALUES(?,?)", ("recette", json.dumps(
            {"modele": "foret_gel75 gele le 18/09 23h10, NON reentraine",
             "seuil": "top 10 pour cent, seuil10 = %.4f" % seuil,
             "absentes": absentes, "cout": COUT,
             "critere_n": N_CRITERE, "critere_jours": JOURS_CRITERE})))
        c.commit()
        print("foret75_iso: GELE a %s · %d variables absentes : %s"
              % (dt.datetime.fromtimestamp(float(g["t"]), TZ).strftime("%d/%m %Hh%M"),
                 len(absentes), ", ".join(absentes)), flush=True)
    gel = float(g["t"])

    t = df["t_dec"].to_numpy(dtype=float)
    r = pd.to_numeric(df["ret_240"], errors="coerce").to_numpy(dtype=float)
    deja = {p for (p,) in c.execute("SELECT pair FROM decision")}
    neufs = [i for i in np.where(t >= gel)[0] if df.at[i, "pair"] not in deja]
    if neufs:
        p = rf.predict_proba(X.iloc[neufs])[:, 1]
        for k, i in enumerate(neufs):
            c.execute("INSERT OR REPLACE INTO decision VALUES(?,?,?,?,?,?,?)",
                      (df.at[i, "pair"], df.at[i, "mint"], float(t[i]), float(p[k]), seuil,
                       int(p[k] >= seuil), float(r[i]) if np.isfinite(r[i]) else None))
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
    print("foret75_iso: %d note(s), %d resultat(s) renseigne(s)" % (len(neufs), maj), flush=True)


def juger(c: sqlite3.Connection, gel: float) -> None:
    L = list(c.execute("SELECT retenu, ret_240 FROM decision WHERE ret_240 IS NOT NULL ORDER BY t_dec"))
    if len(L) < 50:
        print("foret75_iso: %d tickets avec resultat, trop peu pour juger" % len(L), flush=True)
        return
    net = np.array([(1.0 + x[1]) * (1.0 - COUT) - 1.0 for x in L])
    pris = np.array([bool(x[0]) for x in L])
    n, k = len(net), int(pris.sum())
    print("foret75_iso: %d retenus sur %d depuis le gel (critere %d ou %d jours ; jour %.2f)"
          % (k, n, N_CRITERE, JOURS_CRITERE, (time.time() - gel) / 86400.0), flush=True)
    if k < 20:
        return
    v = net[pris]
    sigma = MISE * net.std(ddof=1)
    print("   NIVEAU %+0.3f EUR/ticket (%.2f sig) · contre temoin %+0.3f · %.0f %% de gagnants"
          % (MISE * v.mean(), MISE * v.mean() / (sigma / np.sqrt(k)),
             MISE * (v.mean() - net.mean()), 100 * (v > 0).mean()), flush=True)


def main() -> None:
    while True:
        try:
            noter()
        except Exception as e:  # noqa: BLE001
            print("foret75_iso: %s" % str(e)[:250], flush=True)
        time.sleep(PAS_H * 3600 / 6)


if __name__ == "__main__":
    main()
