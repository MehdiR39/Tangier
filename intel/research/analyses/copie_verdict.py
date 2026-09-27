"""Copier les portefeuilles gagnants : etape 2, le verdict. PROTOCOLE FIGE AVANT DE VOIR UN RESULTAT (15/09).

DONNEES  data/recherche/copie/echanges.jsonl (copie_collecte.py) : chaque echange reussi des 900 premieres
         secondes de 3 157 pools PumpSwap, prix a la transaction (verifie : ecart median 0,0000 avec la
         serie solana_prix_chaine sur 15 pools). Pools tronques (> 20 000 transactions) exclus et comptes.
PORTEFEUILLES  cles SUR la courbe ed25519 seulement (un pool ou un programme n est pas un trader).
         Parts de plus de 50 SOL ignorees (creations et pools anormaux vus a la sonde).
TRANCHES par naissance du pool, comme le grand balayage : RECHERCHE 60 %, TRI 20 %, TEST FINAL 20 %.
         Un pool d evaluation doit naitre au moins 900 s apres la coupure (fenetres disjointes).

UN PORTEFEUILLE DANS UN POOL  sa premiere action est un ACHAT d au moins 0,05 SOL entre 0 et 600 s.
  rendement propre  (SOL des ventes + jetons restants x dernier prix a 900 s) / SOL des achats - 1
  rendement copie   on achete RETARD s apres son achat, on revend RETARD s apres sa premiere vente
                    (sinon a 900 s) : prix sortie / prix entree - 1 - cout.
  prix a l instant t : prix apres la derniere transaction d age <= t.
  cout              0,017 + 2 x 0,31 / (coffre SOL + reserve virtuelle) a l entree, comme le balayage ;
                    pas d achat si l ordre pese plus de 15 % du pool.
  RETARD            3 s (flux Helius des portefeuilles suivis + atterrissage de notre ordre ; le moteur vend
                    en <= 2 s). 1 s et 6 s rapportes pour information, jamais pour choisir.

MENEURS  portefeuilles vus dans >= k pools de la periode d apprentissage, score moyen > s.
GRILLE   score {propre, copie} x k {3, 5, 10} x s {0, +10 %}  = 12 combinaisons, rien d autre.
TRADE    dans un pool d evaluation : le PREMIER achat eligible d un meneur ; on copie ce meneur, un seul
         trade par pool. Rendements plafonnes a +300 % pour les moyennes.
SELECTION  meneurs appris sur RECHERCHE, evalues sur TRI ; on garde la combinaison a la meilleure moyenne
         TRI avec n >= 50.
TEST     meneurs re-appris sur RECHERCHE + TRI, evalues sur TEST FINAL, lu une fois.
GO       TEST : moyenne >= +1,1 %, sans son meilleur > 0, n >= 30, positive sur chaque moitie du TEST.
TEMOINS  (a) copier TOUS les portefeuilles vus dans >= k pools, sans score ;
         (b) 50 tirages de meneurs AU HASARD parmi ces portefeuilles, meme nombre que les vrais meneurs :
             quelle part fait aussi bien sur le TEST ?
DIAGNOSTIC (ajoute avant tout resultat, ne decide rien) : les gagnants de RECHERCHE gagnent-ils encore par
         eux-memes sur TRI, compare a tous les portefeuilles et aux perdants de RECHERCHE ? Persistance =
         savoir-faire a etudier ; pas de persistance = hasard.
"""
from __future__ import annotations

import json
import os
import sys
from bisect import bisect_right
from collections import defaultdict

import numpy as np

ICI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RACINE = os.path.abspath(os.path.join(ICI, "..", ".."))
D = os.path.join(RACINE, "data", "recherche", "copie")
sys.path.insert(0, ICI)
import grand_balayage as gb  # noqa: E402

FENETRE = 900.0
ACHAT_MAX_AGE = 600.0
ACHAT_MIN_SOL = 0.05
PART_MAX_SOL = 50.0
RETARD = 3.0
MISE_SOL = 0.31
COUT_FIXE = 0.017
IMPACT_MAX = 0.15
GRILLE = [(sc, k, s) for sc in ("propre", "copie") for k in (3, 5, 10) for s in (0.0, 0.10)]

# --- cle sur la courbe ed25519 (meme test que solders Pubkey.is_on_curve) ---
_P = 2 ** 255 - 19
_D = (-121665 * pow(121666, _P - 2, _P)) % _P
_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_SQRT_M1 = pow(2, (_P - 1) // 4, _P)


def b58(s):
    n = 0
    for ch in s:
        n = n * 58 + _B58.index(ch)
    raw = n.to_bytes(32, "big") if n.bit_length() <= 256 else None
    return raw


def sur_courbe(adresse) -> bool:
    try:
        b = b58(adresse)
    except ValueError:
        return False
    if b is None:
        return False
    y = int.from_bytes(b, "little") & ((1 << 255) - 1)
    if y >= _P:
        return False
    u = (y * y - 1) % _P
    v = (_D * y * y + 1) % _P
    x2 = u * pow(v, _P - 2, _P) % _P
    if x2 == 0:
        return True
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P:
        x = x * _SQRT_M1 % _P
        if (x * x - x2) % _P:
            return False
    return True


def charger():
    pools_ref = json.load(open(os.path.join(D, "pools.json")))
    naiss = np.sort([p["naissance"] for p in pools_ref])
    c1, c2 = naiss[int(0.6 * len(naiss))], naiss[int(0.8 * len(naiss))]
    ids, courbe = {}, {}
    pools, exclus = [], defaultdict(int)
    for ligne in open(os.path.join(D, "echanges.jsonl"), encoding="utf-8"):
        d = json.loads(ligne)
        if d.get("erreur"):
            exclus["erreur"] += 1
            continue
        if d.get("tronque"):
            exclus["tronque"] += 1
            continue
        e = d["echanges"]
        if not e:
            exclus["vide"] += 1
            continue
        ages = np.array([x[0] for x in e], float)
        prix = np.array([x[2] if x[2] else np.nan for x in e], float)
        q = np.array([x[3] for x in e], float)
        par_w = {}
        for x in e:
            age = x[0]
            for o, dt, ds in x[4]:
                if not o or abs(ds) > PART_MAX_SOL or dt == 0:
                    continue
                ok = courbe.get(o)
                if ok is None:
                    ok = courbe[o] = sur_courbe(o)
                if not ok:
                    continue
                w = ids.setdefault(o, len(ids))
                r = par_w.get(w)
                if r is None:
                    if dt < 0:                       # premiere action = vente : stock venu d ailleurs
                        par_w[w] = False
                        continue
                    r = par_w[w] = {"fb": age, "fb_sol": -ds, "bs": 0.0, "bt": 0.0, "ss": 0.0, "st": 0.0, "fs": None}
                if r is False:
                    continue
                if dt > 0:
                    r["bs"] += -ds
                    r["bt"] += dt
                else:
                    r["ss"] += ds
                    r["st"] += -dt
                    if r["fs"] is None:
                        r["fs"] = age
        recs = [(w, r["fb"], r["fb_sol"], r["bs"], r["bt"], r["ss"], r["st"], r["fs"]) for w, r in par_w.items()
                if r and 0 <= r["fb"] <= ACHAT_MAX_AGE and r["fb_sol"] >= ACHAT_MIN_SOL]
        t0 = d["naissance"]
        tr = "R" if t0 < c1 else ("T" if t0 < c2 else "F")
        pools.append({"pair": d["pair"], "t0": t0, "V": d["V"], "ages": ages, "prix": prix, "q": q,
                      "recs": recs, "tranche": tr, "c_debut": {"R": -np.inf, "T": c1, "F": c2}[tr]})
    return pools, ids, dict(exclus), (c1, c2)


def prix_a(p, t):
    i = bisect_right(p["ages"], t) - 1
    return (p["prix"][max(i, 0)], p["q"][max(i, 0)])


def copie(p, fb, fs, retard):
    pe, qe = prix_a(p, fb + retard)
    if not (pe > 0) or MISE_SOL / (qe + p["V"]) > IMPACT_MAX:
        return None
    ps, _ = prix_a(p, min(fs + retard, FENETRE) if fs is not None else FENETRE)
    if not (ps > 0):
        return None
    return ps / pe - 1 - (COUT_FIXE + 2 * MISE_SOL / (qe + p["V"]))


def scores(pools_app):
    """Par portefeuille : liste des rendements propres et des rendements copie sur la periode d apprentissage."""
    propre, cop = defaultdict(list), defaultdict(list)
    for p in pools_app:
        dernier = prix_a(p, FENETRE)[0]
        for w, fb, fb_sol, bs, bt, ss, st, fs in p["recs"]:
            if bs <= 0:
                continue
            reste = max(bt - st, 0.0)
            propre[w].append(min((ss + reste * dernier) / bs - 1, gb.PLAFOND))
            c = copie(p, fb, fs, RETARD)
            if c is not None:
                cop[w].append(min(c, gb.PLAFOND))
    return propre, cop


def meneurs(propre, cop, sc, k, s):
    src = propre if sc == "propre" else cop
    return {w for w, v in src.items() if len(propre[w]) >= k and np.mean(v) > s}


def evaluer(pools_eval, chefs, retard=RETARD):
    rend, t0s = [], []
    for p in pools_eval:
        cand = [(fb, fs) for w, fb, fb_sol, bs, bt, ss, st, fs in p["recs"] if w in chefs]
        if not cand:
            continue
        fb, fs = min(cand, key=lambda z: z[0])
        c = copie(p, fb, fs, retard)
        if c is not None:
            rend.append(c)
            t0s.append(p["t0"])
    return np.array(rend), np.array(t0s)


def fmt(s):
    return ("%+.4f n=%-5d sb %+.4f" % (s["moy"], s["n"], s["sb1"])) if s else "trop peu"


def main():
    pools, ids, exclus, (c1, c2) = charger()
    par_tr = defaultdict(list)
    for p in pools:
        par_tr[p["tranche"]].append(p)
    ev = {t: [p for p in par_tr[t] if p["t0"] >= p["c_debut"] + FENETRE] for t in "TF"}
    print("pools lus : %d (exclus %s) · portefeuilles : %d · R %d / T %d / F %d (evaluables T %d, F %d)" % (
        len(pools), exclus, len(ids), len(par_tr["R"]), len(par_tr["T"]), len(par_tr["F"]), len(ev["T"]), len(ev["F"])))

    # --- selection : appris sur R, evalue sur T ---
    propre, cop = scores(par_tr["R"])
    print("\nSELECTION (meneurs appris sur RECHERCHE, evalues sur TRI)")
    res = []
    for sc, k, s in GRILLE:
        chefs = meneurs(propre, cop, sc, k, s)
        r, _ = evaluer(ev["T"], chefs)
        st = gb.stats(r)
        print("  score %-6s k>=%-3d s>%+.2f  meneurs %-6d TRI %s" % (sc, k, s, len(chefs), fmt(st)))
        if st and st["n"] >= 50:
            res.append(((sc, k, s), st))
    # DIAGNOSTIC DE PERSISTANCE (ajoute le 15/09 avant tout resultat, question de l operateur : « des bons
    # traders qui reussissent ») -- ne decide rien. Les portefeuilles gagnants sur RECHERCHE gagnent-ils encore,
    # par EUX-MEMES, sur TRI ? Si non, leur reussite etait du hasard et il n y a rien a apprendre d eux.
    propre_T, _ = scores(ev["T"])
    print("\nPERSISTANCE (rendement PROPRE sur TRI, par pool, plafonne a +300 %)")
    for k in (3, 5, 10):
        vus = {w for w, v in propre.items() if len(v) >= k}
        for lib, grp in (("tous (k>=%d)" % k, vus),
                         ("gagnants R moy > 0", {w for w in vus if np.mean(propre[w]) > 0}),
                         ("gagnants R moy > +10 %", {w for w in vus if np.mean(propre[w]) > 0.10}),
                         ("perdants R moy < 0", {w for w in vus if np.mean(propre[w]) < 0})):
            vals = [x for w in grp for x in propre_T.get(w, [])]
            nw = sum(1 for w in grp if w in propre_T)
            print("  %-26s portefeuilles %-6d actifs sur TRI %-5d  %s" % (lib, len(grp), nw, fmt(gb.stats(vals))))
    base = {k: gb.stats(evaluer(ev["T"], {w for w, v in propre.items() if len(v) >= k})[0]) for k in (3, 5, 10)}
    for k, st in base.items():
        print("  TEMOIN tous les portefeuilles k>=%-3d            TRI %s" % (k, fmt(st)))
    if not res:
        print("aucune combinaison avec n >= 50 sur TRI")
        return
    (sc, k, s), sT = max(res, key=lambda z: z[1]["moy"])
    print("RETENUE : score %s, k >= %d, s > %+.2f" % (sc, k, s))

    # --- test final : appris sur R + T, evalue sur F, lu une fois ---
    propre2, cop2 = scores(par_tr["R"] + par_tr["T"])
    chefs = meneurs(propre2, cop2, sc, k, s)
    rF, tF = evaluer(ev["F"], chefs)
    sF = gb.stats(rF)
    jours = (max(p["t0"] for p in ev["F"]) - min(p["t0"] for p in ev["F"])) / 86400
    mil = np.median(tF) if len(tF) else 0
    h1, h2 = gb.stats(rF[tF < mil]), gb.stats(rF[tF >= mil])
    go = bool(sF) and sF["n"] >= 30 and sF["moy"] >= gb.OBJ and sF["sb1"] > 0 and bool(h1) and bool(h2) and h1["moy"] > 0 and h2["moy"] > 0
    print("\nTEST FINAL (%d meneurs, %.1f jours)" % (len(chefs), jours))
    print("  %s · mediane %+.4f · moitie 1 %s · moitie 2 %s" % (fmt(sF), np.median(rF) if len(rF) else np.nan, fmt(h1), fmt(h2)))
    if sF:
        print("  %.0f trades/jour x %+.4f x 30 EUR = %+.1f EUR/jour" % (sF["n"] / jours, sF["moy"], sF["n"] / jours * sF["moy"] * 30))
    for ret in (1.0, 6.0):
        print("  (information) retard %.0f s : %s" % (ret, fmt(gb.stats(evaluer(ev["F"], chefs, ret)[0]))))
    tous = {w for w, v in propre2.items() if len(v) >= k}
    print("  TEMOIN tous les portefeuilles k>=%d (%d) : %s" % (k, len(tous), fmt(gb.stats(evaluer(ev["F"], tous)[0]))))
    rng = np.random.default_rng(15)
    pool_w = sorted(tous)
    mieux = 0
    for _ in range(50):
        hasard = set(rng.choice(pool_w, size=min(len(chefs), len(pool_w)), replace=False).tolist())
        sh = gb.stats(evaluer(ev["F"], hasard)[0])
        if sh and sF and sh["moy"] >= sF["moy"]:
            mieux += 1
    print("  TEMOIN hasard : %d tirages sur 50 font aussi bien" % mieux)
    print("\nVERDICT : %s" % ("GO" if go else "NON"))


if __name__ == "__main__":
    main()
