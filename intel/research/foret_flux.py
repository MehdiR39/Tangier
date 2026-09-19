"""FORET DE VIDAGE NOURRIE AU FLUX D ORDRES, gelee -- papier, zero euro.

CE QUI L AMENE (19/09, §3.155 et la suite). La foret en service tient a 86 % sur la LIQUIDITE, et
trier sur `q` seul capture presque tout son avantage : ajouter des variables de prix ne pouvait rien
apporter. Le flux d ordres des premieres secondes -- qui achete, combien, combien de vendeurs, et
surtout combien de portefeuilles VENDENT SANS AVOIR ACHETE -- est d une autre nature. En marche
avant il bat le temoin de +0,430 EUR/ticket, et 1 tirage sur 100 seulement fait aussi bien.

POURQUOI 30 SECONDES ET NON 45. L index des transactions retarde de 10 a 15 s (mesure sur 7 pools
vivants : a 45 s on voit 88 % de la fenetre en median, 61 % au pire ; il faut +15 s de marge pour
tout voir). Donc a l instant de decider, seules les transactions d age <= 30 s sont surement
visibles. Et la vue tronquee n est pas un pis-aller : elle fait MIEUX que la vue complete --
+0,600 EUR/ticket a 35 s contre +0,335 a 45 s, et sur 40 marches avant permutees essayant les six
troncatures, AUCUNE n egale la vraie (p ~ 0,024). Les dernieres secondes diluaient le signal.

CE MODELE N EST DONC PAS UN PARI SUR DES DONNEES QU ON N A PAS : il apprend exactement la vue que
le moteur aurait, a la seconde pres.

CRITERE, FIGE AVANT LE PREMIER TICKET -- l erreur du frein fut de le fixer apres avoir vu le score.
Au premier atteint de 600 tickets posterieurs au gel ou de 14 jours, les QUATRE doivent tenir :
    (a) battre le temoin sur sa propre periode ;
    (b) le battre encore sans ses 3 meilleurs tickets ;
    (c) etre positive contre le temoin sur les DEUX moities chronologiques ;
    (d) l ecart depasse 2 fois son propre bruit -- sigma x racine(m/(n.k)), la comparaison etant
        appariee (on garde un sous-ensemble des tickets du temoin).
600 tickets n est pas un chiffre rond choisi au hasard : a +0,6 EUR/ticket et sigma = 14 EUR, il en
faut 543 pour que (d) soit atteignable. En dessous, le critere serait impossible a satisfaire et
l attente serait une comedie.

Si les quatre tiennent, ce fichier est au FORMAT du moteur (`modeles`/`tree_info`) : le brancher ne
demandera aucune reecriture. S il en manque un seul, la piste est close et on l ecrit.
"""
from __future__ import annotations

import collections
import datetime as dt
import glob
import json
import os
import sqlite3
import statistics as st
import sys
import time

import numpy as np

DOSSIER = os.environ.get("FLUX_DIR", "/app/data/recherche/foret_flux")
V1 = "/app/data/recherche/v1_avant"
PAPIER = "/app/db/papier_combo.sqlite"
MODELE = "/app/data/recherche/balayage/foret_flux.json"
AGE_FLUX = int(os.environ.get("AGE_FLUX", "30"))     # ce que l index montre surement a 45 s
RECURRENT = 5
COUT = float(os.environ.get("COUT_MESURE", "0.0417"))
MISE = 20.0
GARDE = 0.80                                          # meme proportion que la foret en service
N_CRITERE, JOURS_CRITERE = 600, 14
TZ = dt.timezone(dt.timedelta(hours=2))
PAS = 600.0


def pools():
    """Les pools de `v1_avant`, tries par naissance : l ordre compte pour l historique des robots."""
    out = []
    for f in sorted(glob.glob(os.path.join(V1, "*.jsonl"))):
        with open(f, encoding="utf-8") as fh:
            for ligne in fh:
                try:
                    d = json.loads(ligne)
                except Exception:  # noqa: BLE001
                    continue
                if d.get("tx"):
                    out.append((float(d.get("naissance") or 0), d))
    out.sort(key=lambda x: x[0])
    return out


def variables(P, age_max=AGE_FLUX):
    """Les 16 variables, sur les transactions d age <= age_max SEULEMENT.

    L historique des portefeuilles est reconstruit chronologiquement et mis a jour APRES chaque
    pool : un robot est recurrent parce qu il a ete vu sur des pools NES AVANT celui-ci. Sans cette
    precaution le compte regarderait l avenir (regle 17).
    """
    vus = collections.defaultdict(set)
    feats = {}
    for naiss, d in P:
        achats, ventes = [], []
        acheteurs, vendeurs = set(), set()
        premier, robots, sol_robots = None, 0, 0.0
        sol_par_wallet = collections.defaultdict(float)
        for tx in d.get("tx") or []:
            try:
                age, parts = int(tx[0]), tx[2]
            except Exception:  # noqa: BLE001
                continue
            if age > age_max:
                continue
            for p in parts or []:
                try:
                    w, dj, ds = str(p[0]), float(p[1]), float(p[2])
                except Exception:  # noqa: BLE001
                    continue
                sol_par_wallet[w] += ds
                if dj > 0 and ds < 0:
                    achats.append(-ds)
                    acheteurs.add(w)
                    if premier is None:
                        premier = age
                    if len(vus[w]) >= RECURRENT:
                        robots += 1
                        sol_robots += -ds
                elif dj < 0 and ds > 0:
                    ventes.append(ds)
                    vendeurs.add(w)
        sans = [v for w, v in sol_par_wallet.items() if v > 0 and w not in acheteurs]
        sa, sv = sum(achats), sum(ventes)
        gini = None
        if len(achats) >= 2 and sa > 0:
            a = sorted(achats)
            k = len(a)
            gini = 2 * sum((i + 1) * x for i, x in enumerate(a)) / (k * sa) - (k + 1) / k
        feats[d["pair"]] = {
            "naissance": naiss,
            "v1_n_achats": len(achats), "v1_n_ventes": len(ventes),
            "v1_acheteurs": len(acheteurs), "v1_vendeurs": len(vendeurs),
            "v1_sol_achats": sa, "v1_sol_ventes": sv,
            "v1_ratio_ventes": (sv / sa) if sa > 0 else None,
            "v1_premier_achat": premier,
            "v1_achat_median": st.median(achats) if achats else None,
            "v1_achat_max": max(achats) if achats else None,
            "v1_gini_achats": gini, "v1_robots": robots,
            "v1_part_robots": (sol_robots / sa) if sa > 0 else None,
            "v1_vendeurs_sans_achat": len(sans), "v1_sol_sans_achat": sum(sans),
            "v1_part_sans_achat": (sum(sans) / sv) if sv > 0 else None,
        }
        for w in acheteurs:
            vus[w].add(d["pair"])
    return feats


NOMS = ["v1_n_achats", "v1_n_ventes", "v1_acheteurs", "v1_vendeurs", "v1_sol_achats",
        "v1_sol_ventes", "v1_ratio_ventes", "v1_premier_achat", "v1_achat_median",
        "v1_achat_max", "v1_gini_achats", "v1_robots", "v1_part_robots",
        "v1_vendeurs_sans_achat", "v1_sol_sans_achat", "v1_part_sans_achat"]


def cibles():
    """`brut_240` et `q`, depuis le carnet papier de reference."""
    c = sqlite3.connect("file:%s?mode=ro" % PAPIER, uri=True, timeout=30)
    try:
        return {p: (float(b), float(q or 0), float(t))
                for p, b, q, t in c.execute(
                    "SELECT d.pair, i.brut_240, d.q, d.t_dec FROM decision d JOIN issue i"
                    " ON i.pair=d.pair WHERE d.eligible=1 AND i.brut_240 IS NOT NULL")}
    finally:
        c.close()


def _arbre(t, i=0):
    """Un arbre sklearn -> la structure que `ensemble.Ensemble` sait descendre.

    Meme convention que sklearn : `valeur <= seuil` part a GAUCHE. La feuille porte la proportion
    de la classe 1 ; `Ensemble` les MOYENNE quand `sigmoide` est faux -- c est exactement ce que
    fait une foret aleatoire. Le format est donc natif pour elle, pas un detournement.
    """
    if t.children_left[i] == -1:
        v = t.value[i][0]
        return {"leaf_value": float(v[1] / v.sum()) if v.sum() else 0.0}
    return {"split_feature": int(t.feature[i]), "threshold": float(t.threshold[i]),
            "default_left": True, "missing_type": "None",
            "left_child": _arbre(t, t.children_left[i]),
            "right_child": _arbre(t, t.children_right[i])}


def geler():
    """Entraine UNE fois sur tout ce qui precede, et ecrit le modele au format du moteur.

    RANDOM FOREST, et non LightGBM. Mido, 19/09 : « pourquoi t'as choisi LightGBM a la place de
    RF ? ». J avais pris LightGBM parce que les modeles deja geles sont a son format et que le
    moteur savait le lire -- un argument de PLOMBERIE, pas de statistique. Or toute l etude qui a
    etabli le +0,430 EUR/ticket tournait sur une RandomForest (300 arbres, min_samples_leaf=20).
    Geler un autre algorithme que celui qui a produit le resultat, c est geler autre chose.
    Et la mesure lui donne raison : en marche avant, RF 0,689 d AUC contre 0,615 pour le LightGBM
    que j avais gele (qui affichait 0,996 sur ses propres donnees -- il avait appris par coeur).
    """
    from sklearn.ensemble import RandomForestClassifier
    P = pools()
    F = variables(P)
    C = cibles()
    X, y = [], []
    for pair, f in F.items():
        if pair not in C:
            continue
        brut, q, t = C[pair]
        net = (1.0 + brut) * (1.0 - COUT) - 1.0
        X.append([f.get(n) for n in NOMS])
        y.append(1 if net <= -0.5 else 0)
    X = np.array(X, dtype=float)
    y = np.array(y)
    if len(y) < 400 or len(set(y)) < 2:
        raise RuntimeError("pas assez de donnees pour geler : %d lignes" % len(y))
    med = {n: float(np.nanmedian(X[:, i])) if np.isfinite(X[:, i]).any() else 0.0
           for i, n in enumerate(NOMS)}
    Xr = np.array([[med[n] if not np.isfinite(r[i]) else r[i] for i, n in enumerate(NOMS)]
                   for r in X])
    rf = RandomForestClassifier(n_estimators=300, min_samples_leaf=20, n_jobs=-1,
                                random_state=0).fit(Xr, y)
    p = rf.predict_proba(Xr)[:, 1]
    sortie = {"feature_names": NOMS, "n_modeles": 1, "sigmoide": False,
              "seuil_p80": float(np.quantile(p, GARDE)), "medianes": med,
              "modeles": [{"tree_info": [{"tree_structure": _arbre(e.tree_)}
                                         for e in rf.estimators_]}],
              "entraine_sur": "v1_avant, %d pools, flux <= %d s, RandomForest 300 arbres "
                              "(min_samples_leaf 20), cout %.2f pt, gel %s"
                              % (len(y), AGE_FLUX, 100 * COUT,
                                 dt.datetime.now(TZ).strftime("%d/%m %Hh%M"))}
    os.makedirs(os.path.dirname(MODELE), exist_ok=True)
    with open(MODELE, "w", encoding="utf-8") as f:
        json.dump(sortie, f)
    os.makedirs(DOSSIER, exist_ok=True)
    with open(os.path.join(DOSSIER, "gel.json"), "w", encoding="utf-8") as f:
        json.dump({"gel": time.time(), "n_entrainement": len(y), "age_flux": AGE_FLUX,
                   "seuil_p80": sortie["seuil_p80"], "vidages": int(y.sum()),
                   "critere": {"n": N_CRITERE, "jours": JOURS_CRITERE,
                               "conditions": ["battre le temoin", "sans ses 3 meilleurs",
                                              "les deux moities", "ecart > 2 x son bruit"]}}, f)
    print("foret_flux: GELEE · %d pools d entrainement (%d vidages) · seuil p80 %.4f · flux <= %d s"
          % (len(y), int(y.sum()), sortie["seuil_p80"], AGE_FLUX), flush=True)
    return sortie


def juger(gel):
    """Note tous les pools NES APRES le gel, et applique le critere quand il est atteint."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from ensemble import Ensemble
    m = Ensemble(MODELE)
    P = [(t, d) for t, d in pools()]
    F = variables(P)
    C = cibles()
    pris, tem = [], []
    for pair, f in F.items():
        if pair not in C or f["naissance"] < gel["gel"]:
            continue
        brut, q, t = C[pair]
        r = min((1.0 + brut) * (1.0 - COUT) - 1.0, 3.0)
        tem.append((t, r))
        if m.probabilite({n: f.get(n) for n in NOMS}) <= m.seuil_p80:
            pris.append((t, r))
    n = len(pris)
    jours = (time.time() - gel["gel"]) / 86400.0
    print("foret_flux: %d ticket(s) retenus sur %d depuis le gel (critere %d ou %d jours ; jour %.2f)"
          % (n, len(tem), N_CRITERE, JOURS_CRITERE, jours), flush=True)
    if n < 20:
        return
    v = np.array([r for _, r in pris])
    t_ = np.array([r for _, r in tem])
    ecart = MISE * (v.mean() - t_.mean())
    s = np.sort(v)
    sans3 = MISE * (s[:-3].mean() - t_.mean())
    mi = n // 2
    h1 = MISE * (v[:mi].mean() - t_.mean())
    h2 = MISE * (v[mi:].mean() - t_.mean())
    sigma = MISE * t_.std(ddof=1)
    bruit = sigma * np.sqrt((len(t_) - n) / (len(t_) * n)) if 0 < n < len(t_) else float("inf")
    print("   contre le temoin %+0.3f · sans 3 %+0.3f · moities %+0.3f / %+0.3f · bruit %.3f (%.2f sigma)"
          % (ecart, sans3, h1, h2, bruit, ecart / bruit if bruit else 0), flush=True)
    if n >= N_CRITERE or jours >= JOURS_CRITERE:
        ok = [ecart > 0, sans3 > 0, h1 > 0 and h2 > 0, ecart > 2 * bruit]
        print("   CRITERE ATTEINT · (a) %s · (b) %s · (c) %s · (d) %s -> %s"
              % (*["OUI" if x else "NON" for x in ok],
                 "LA PISTE TIENT" if all(ok) else "PISTE CLOSE"), flush=True)


def main() -> None:
    os.makedirs(DOSSIER, exist_ok=True)
    chemin_gel = os.path.join(DOSSIER, "gel.json")
    if not os.path.exists(chemin_gel):
        geler()
    while True:
        try:
            with open(chemin_gel, encoding="utf-8") as f:
                gel = json.load(f)
            juger(gel)
        except Exception as e:  # noqa: BLE001
            print("foret_flux: %s" % str(e)[:200], flush=True)
        time.sleep(PAS)


if __name__ == "__main__":
    main()
