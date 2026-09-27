"""Test combine : les petits effets vrais s additionnent-ils jusqu a 50 EUR par jour ?

REGLES FIGEES LE 15/09 AVANT D AVOIR LANCE LE CALCUL. Aucune ne sera changee apres lecture.

POPULATIONS
  SIMULEE  jetons « propre » (3 signes) du coffre : entree a la lecture la plus proche de T+60 s
           (45-90 s), sortie a +240 s (+/- 45 s), cout d execution reel 0,010 par euro.
  REELLE   nos tickets propres en argent reel, gain lu sur le portefeuille (cout reel inclus).

HISTORIQUE (ce qu on savait AVANT d entrer)
  detenteur  plus gros portefeuille a T+30 s s il a >= 5 % de l offre (sacs_migration.jsonl)
  financeur  compte qui a finance ce portefeuille (financeurs.jsonl) ; un financeur de plus de 25
             detenteurs est une plateforme et ne relie rien.
  un jeton j compte dans l historique de k si son issue etait connue avant l entree de k :
  naissance_j + 300 s < naissance_k + 60 s. Vidage de j = rapport de prix a +240 s <= 0,5.

VARIANTES (deux, pas plus)
  BASE  la regle actuelle.
  A     n entre PAS si le detenteur OU son financeur a deja un vidage dans l historique.
  B     A + vente sur cascade : si une lecture tombe de 30 % sous le plus haut des 10 dernieres
        secondes, on sort -- au prix de la lecture si la chute fait moins de 50 %, sinon a 43 % du
        plus haut (mediane mesuree en chaine sur 14 crashs propres, vente 2 s apres le signal).

JUGEMENT
  coupure par date de naissance, premiere moitie RECHERCHE, seconde JUGEMENT.
  OBJECTIF 50 EUR/JOUR  =  sur le JUGEMENT : niveau >= +0,011 par euro, sans son meilleur ticket
  > 0, vidages < 11,9 %. Sinon : NON.
"""
from __future__ import annotations

import json
import os
import sqlite3
import statistics as st
from collections import Counter, defaultdict

D = "/app/data/recherche"
COFFRE = os.path.join(D, "archive_solana.sqlite")
COUT = 0.010
PLATEFORME = 25
OBJECTIF = 0.011
POINT_MORT_VIDAGE = 0.119
MISE = 30.0
SORTIE_CRASH = 0.43


def charger():
    c = sqlite3.connect("file:%s?mode=ro" % COFFRE, uri=True, timeout=60)
    offre = {m: float(o) for m, o in c.execute("SELECT mint, offre FROM mint_offre") if o}
    marque = {m: t for m, t in c.execute("SELECT mint, telegram FROM tg_juges")}
    sac = {}
    for l in open(os.path.join(D, "sacs_migration.jsonl"), encoding="utf-8"):
        d = json.loads(l)
        if d.get("erreur") or not d.get("instants"):
            continue
        top = d["instants"].get("30", [])
        s = offre.get(d["mint"], 1e9)
        sac[d["mint"]] = {"w": top[0][0] if top and top[0][1] / s >= 0.05 else None, "nais": d["naissance"]}
    fin = {}
    for l in open(os.path.join(D, "financeurs.jsonl"), encoding="utf-8"):
        d = json.loads(l)
        if d.get("financeur"):
            fin[d["wallet"]] = d["financeur"]
    taille = Counter(fin.values())
    fin = {w: (f if taille[f] <= PLATEFORME else None) for w, f in fin.items()}
    courbes = defaultdict(list)
    for r in c.execute("""SELECT p.mint, p.pair_id, p.ts, p.age_s, p.prix_sol, p.reserve_sol FROM solana_prix_chaine p
                          JOIN pool_quote q ON q.pool=p.pair_id AND q.est_sol=1 WHERE p.prix_sol>0
                          ORDER BY p.pair_id, p.ts"""):
        courbes[r[1]].append({"mint": r[0], "ts": r[2], "age": r[3], "p": r[4], "x": r[5]})
    return c, marque, sac, fin, courbes


def cascade(chemin, depart, p_entree, fin_ts):
    """Premier prix de sortie sur cascade entre l entree et fin_ts, ou None."""
    lu = [x for x in chemin if depart <= x["ts"] <= fin_ts]
    for i in range(1, len(lu)):
        ref = max(x["p"] for x in lu[:i + 1] if lu[i]["ts"] - x["ts"] <= 10.5)
        chute = lu[i]["p"] / ref - 1
        if chute <= -0.30:
            return ref * SORTIE_CRASH if chute <= -0.5 else lu[i]["p"]
    return None


def simules(marque, sac, courbes):
    out = []
    for pair, pts in courbes.items():
        mint = pts[0]["mint"]
        if mint not in marque or marque[mint] or mint not in sac:
            continue
        av = [x for x in pts if x["age"] <= 90]
        e = min((x for x in pts if 45 <= x["age"] <= 90), key=lambda x: abs(x["age"] - 60), default=None)
        if len(av) < 3 or not e or not e["x"] or 0.31 / e["x"] > 0.15:
            continue
        p0, l0 = av[0]["p"], av[0]["x"] or 0
        signes = (int(e["p"] / p0 - 1 >= 0.007) + int(min(x["p"] for x in av) / p0 - 1 >= 0)
                  + int(((e["x"] / l0 - 1) if l0 > 0 else 0) >= 0.0035))
        if signes != 3:
            continue
        s = min((x for x in pts if x["age"] > e["age"]), key=lambda x: abs(x["age"] - (e["age"] + 240)), default=None)
        if not s or abs(s["age"] - (e["age"] + 240)) > 45:
            continue
        base = s["p"] / e["p"] - 1
        pc = cascade(pts, e["ts"], e["p"], s["ts"])
        out.append({"mint": mint, "nais": sac[mint]["nais"], "w": sac[mint]["w"], "vide": base <= -0.5,
                    "r_base": base - COUT, "r_casc": ((pc if pc is not None else s["p"]) / e["p"] - 1) - COUT})
    return out


def issues_historiques(marque, sac, courbes):
    """Vidage ou non de TOUS les jetons dont on connait le detenteur (quel que soit leur groupe)."""
    h = []
    for pair, pts in courbes.items():
        mint = pts[0]["mint"]
        if mint not in sac or not sac[mint]["w"]:
            continue
        e = min((x for x in pts if 45 <= x["age"] <= 90), key=lambda x: abs(x["age"] - 60), default=None)
        if not e:
            continue
        s = min((x for x in pts if x["age"] > e["age"]), key=lambda x: abs(x["age"] - (e["age"] + 240)), default=None)
        if not s or abs(s["age"] - (e["age"] + 240)) > 45:
            continue
        h.append((sac[mint]["nais"], sac[mint]["w"], s["p"] / e["p"] <= 0.5))
    return sorted(h)


def marque_historique(tickets, hist, fin):
    for t in tickets:
        w = t["w"]
        f = fin.get(w) if w else None
        deja = [(n, hw, v) for n, hw, v in hist if n + 300 < t["nais"] + 60 and v]
        t["exclu"] = bool(w) and any(hw == w or (f and fin.get(hw) == f) for _, hw, _ in deja)
    return tickets


def ligne(lib, v, jours):
    if len(v) < 10:
        return "  %-22s n=%4d  trop peu" % (lib, len(v)), None
    s = sorted(v, reverse=True)
    niveau, sb, vides = st.mean(s), st.mean(s[1:]), sum(1 for x in s if x <= -0.5) / len(s)
    par_jour = len(v) / jours
    return ("  %-22s n=%4d  niveau %+.4f  sans best %+.4f  vides %4.1f %%  %4.0f tickets/j  %+6.0f EUR/j"
            % (lib, len(v), niveau, sb, 100 * vides, par_jour, par_jour * niveau * MISE)), (niveau, sb, vides)


def main():
    c, marque, sac, fin, courbes = charger()
    hist = issues_historiques(marque, sac, courbes)
    T = sorted(marque_historique(simules(marque, sac, courbes), hist, fin), key=lambda t: t["nais"])
    print("SIMULE PROPRE : %d jetons · historique : %d jetons dont %d vides · exclus par A : %d"
          % (len(T), len(hist), sum(1 for h in hist if h[2]), sum(1 for t in T if t["exclu"])))
    moit = len(T) // 2
    verdicts = {}
    for nom, part in (("RECHERCHE", T[:moit]), ("JUGEMENT", T[moit:])):
        jours = max((part[-1]["nais"] - part[0]["nais"]) / 86400, 1e-9) * 2   # la moitie des tickets
        print("\n%s (%s -> %s)" % (nom, part[0]["nais"], part[-1]["nais"]))
        for lib, v in (("BASE", [t["r_base"] for t in part]),
                       ("A  filtre historique", [t["r_base"] for t in part if not t["exclu"]]),
                       ("B  A + cascade", [t["r_casc"] for t in part if not t["exclu"]])):
            texte, stats = ligne(lib, v, max((part[-1]["nais"] - part[0]["nais"]) / 86400, 1e-9))
            print(texte)
            if nom == "JUGEMENT":
                verdicts[lib] = stats
    print("\nVERDICT (jugement, objectif +0,011/euro, sans best > 0, vidages < 11,9 %) :")
    for lib, s in verdicts.items():
        ok = s and s[0] >= OBJECTIF and s[1] > 0 and s[2] < POINT_MORT_VIDAGE
        print("  %-22s %s" % (lib, "ATTEINT -> confirmation en papier" if ok else "NON"))

    # --- controle sur l argent reel ---
    crash = json.load(open(os.path.join(D, "2026-09-15_autopsie", "crash_sortie.json")))
    R = []
    for mint, pair, te, ts_s, gain, mise in c.execute(
            "SELECT mint, pair_id, ts_entree, ts_sortie, gain_eur, mise_eur FROM tg_lignes"
            " WHERE mode='live' AND methode='propre' AND gain_eur IS NOT NULL"):
        if mint not in sac:
            continue
        pts = courbes.get(pair, [])
        av = [x for x in pts if x["ts"] <= te]
        ap = [x for x in pts if te < x["ts"] <= ts_s]
        r = gain / mise
        rc = r
        if av and ap:
            p_sortie = ap[-1]["p"]
            chemin = [av[-1]] + ap
            for i in range(1, len(chemin)):
                ref = max(x["p"] for x in chemin[:i + 1] if chemin[i]["ts"] - x["ts"] <= 10.5)
                chute = chemin[i]["p"] / ref - 1
                if chute <= -0.30:
                    p_new = (ref * (1 + crash[mint]["r"]["5"]) if mint in crash
                             else (ref * SORTIE_CRASH if chute <= -0.5 else chemin[i]["p"]))
                    rc = (1 + r) * p_new / p_sortie - 1
                    break
        R.append({"mint": mint, "nais": sac[mint]["nais"], "w": sac[mint]["w"], "gain": gain, "mise": mise,
                  "r": r, "rc": rc})
    R = sorted(marque_historique(R, hist, fin), key=lambda t: t["nais"])
    print("\nARGENT REEL, carnet propre (%d tickets avec detenteur reconstruit) :" % len(R))
    moit = len(R) // 2
    for nom, part in (("1re moitie", R[:moit]), ("2de moitie", R[moit:]), ("TOUT", R)):
        base = sum(t["gain"] for t in part)
        a = sum(t["gain"] for t in part if not t["exclu"])
        b = sum(t["rc"] * t["mise"] for t in part if not t["exclu"])
        print("  %-10s BASE %+8.2f EUR · A %+8.2f EUR (%d exclus) · B %+8.2f EUR"
              % (nom, base, a, sum(1 for t in part if t["exclu"]), b))


if __name__ == "__main__":
    main()
