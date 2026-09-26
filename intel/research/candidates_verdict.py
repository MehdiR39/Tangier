"""LES DEUX CANDIDATES GELEES LE 22/09 22h13 — ou en sont-elles ?

Mido, 22/09 : « oui on gele ». Deux remplacantes possibles de `BANDE + PAUSE`, figees AVANT
qu un seul ticket posterieur n existe, avec leur critere ecrit d avance :

  A · PAUSE 25     la meme regle, seuil de pause -0,25 au lieu de -0,30. Choisie par un balayage
                   1re moitie / 2e moitie : +1,767 la ou elle a ete choisie, +4,187 sur la moitie
                   suivante (la production faisait +1,572 puis +3,727). Aucun entrainement.

  B · MODELE FRAIS le meme LightGBM, memes 19 variables, meme cible, reentraine sur les 4 704
                   tickets connus au gel. Sa bande est recalibree sur les QUANTILES qu occupait
                   [0,20 ; 0,35[ chez le modele en service -- sans quoi les memes bornes
                   designeraient d autres jetons. Elle part PERDANTE (+4,021 contre +5,704 sur
                   une fenetre de 1 176 tickets jamais vus), et c est pour ca qu on la mesure au
                   lieu d en debattre.

CRITERE, FIGE — au premier atteint de 200 tickets retenus ou de 14 jours, une candidate ne prend
la place de la production que si, sur les tickets POSTERIEURS au gel :
  (a) elle bat `BANDE + PAUSE` en EUR/ticket sur LES MEMES tickets (comparaison appariee),
  (b) elle est positive en valeur absolue,
  (c) elle bat son propre nul par DECALAGE CIRCULAIRE a p < 0,05.
Sinon : abandon, et on n y revient pas sans raison neuve.

(c) EST LA CONDITION QUE LA PRODUCTION NE FRANCHIT PAS ENCORE (p = 0,04 a 0,07 le 22/09). Une
candidate ne remplace pas sur un match nul : elle doit faire MIEUX, pas aussi mal. Et le nul est
celui du decalage circulaire, jamais le tirage au sort -- une pause appliquee a des rendements
melanges rapporte deja ~+0,38 EUR/ticket par pure mecanique (§3.171).

Lecture seule. Usage : python -m intel.research.candidates_verdict
"""
from __future__ import annotations

import datetime as dt
import json
import os
import random
import sqlite3
import statistics as st

TZ = dt.timezone(dt.timedelta(hours=2))
DOSSIER = os.environ.get("CANDIDATES", "/app/data/recherche/candidates")
COMBO = os.environ.get("COMBO_DB", "/app/db/papier_combo.sqlite")
BANDE = (0.20, 0.35)
V, MISE, FIXE = 17.5845, 20.0, 0.03524
PAUSE_S, TENUE = 1800.0, 242.0
TIRAGES = 3000
random.seed(20260922)


def cout(q: float) -> float:
    return FIXE + 2.0 * (MISE * 0.31 / 30.0) / ((q or 0) + V)


def rejoue(tickets, seuil, duree=PAUSE_S):
    """La pause, appliquee dans l ordre reel. `tickets` : [{t, fin, r}] tries par t."""
    pris, att, bl = [], [], 0.0
    for x in tickets:
        att.sort(key=lambda z: z["fin"])
        while att and att[0]["fin"] <= x["t"]:
            f = att.pop(0)
            if f["r"] <= seuil:
                bl = max(bl, f["fin"] + duree)
        if x["t"] >= bl:
            pris.append(x)
        att.append(x)
    return pris


def nul(tickets, seuil):
    """Le meme filtre sur des rendements decales circulairement : le biais mecanique de la regle."""
    R = [x["r"] for x in tickets]
    if len(R) < 30:
        return []
    out = []
    for _ in range(TIRAGES):
        d = random.randrange(1, len(R))
        perm = R[d:] + R[:d]
        faux = [dict(tickets[i], r=perm[i]) for i in range(len(tickets))]
        p = rejoue(faux, seuil)
        if p:
            out.append(MISE * st.mean(z["r"] for z in p))
    return out


def dis(nom, pris, seuil, tickets):
    if len(pris) < 10:
        print("   %-26s %5d tickets — trop peu pour juger" % (nom, len(pris)))
        return None
    m = MISE * st.mean(x["r"] for x in pris)
    n = nul(tickets, seuil)
    p = (sum(1 for z in n if z >= m) / len(n)) if n else float("nan")
    print("   %-26s %5d tickets %+8.3f EUR/ticket · nul %+0.3f · p = %.4f%s"
          % (nom, len(pris), m, st.mean(n) if n else 0.0, p, "  <-- (c) FRANCHI" if p < 0.05 else ""))
    return m


def critere_a(nom, pris_c, pris_p, offerts, drapeau_c, drapeau_p, seuil_c, seuil_p=-0.30):
    """LE CRITERE (a) : la candidate bat-elle la production SUR LES MEMES TICKETS ?

    POURQUOI CETTE FONCTION EXISTE. Jusqu au 26/09 ce critere n etait calcule pour AUCUNE des deux
    candidates : la seule ligne affichee, « ecart A - production », etait la difference de deux
    moyennes NON appariees, portant sur des sous-ensembles differents (79 tickets d un cote, 70 ou
    101 de l autre). C est exactement la comparaison qui trompe quand les deux regles ne jugent pas
    les memes jetons -- et Mido l a vu sur le graphe de l app avant moi.

    CE QU EST UNE COMPARAISON APPARIEE POUR UNE REGLE DE SELECTION. Elle n est pas ce qu on croit :
    un ticket que les DEUX prennent rend exactement la meme chose des deux cotes, donc la difference
    y est nulle par construction. **Tout l ecart vient donc des EXCLUSIFS** -- ce que l une prend et
    que l autre refuse. C est cette decomposition qui est la vraie comparaison appariee ici.

    LA BARRE N EST PAS CHANGEE. Le critere gele dit « elle bat la production en EUR/ticket », et la
    significativite est portee par le critere (c), separement. Exiger ici en plus un intervalle qui
    exclut zero, ce serait DURCIR APRES COUP une barre ecrite d avance -- l erreur exacte commise sur
    le frein. On calcule donc (a) comme il est ecrit, en COMPARAISON PONCTUELLE, et on affiche le
    bruit a cote pour que personne ne lise le point comme une preuve.

    LE BRUIT EST CELUI DE L ECART, jamais celui des deux niveaux separement : les deux regles voient
    le MEME marche, donc leurs erreurs sont correlees et deux intervalles separes se recouvriraient
    pour rien. On rejoue donc les DEUX regles sur chaque tirage, en BLOCS (L ~ n^(1/3)) parce que les
    tickets se chevauchent dans le temps.
    """
    if len(pris_c) < 10 or len(pris_p) < 10:
        print("   %-26s trop peu de tickets pour le critere (a)" % nom)
        return None
    ic = {x["i"] for x in pris_c}
    ip = {x["i"] for x in pris_p}
    par_i = {x["i"]: x for x in offerts}

    def moy(ids):
        return MISE * st.mean(par_i[i]["r"] for i in ids) if ids else float("nan")

    def dit(etiq, ids):
        if not ids:
            print("      %-24s aucun" % etiq)
        else:
            print("      %-24s n=%-4d %+8.3f EUR/ticket" % (etiq, len(ids), moy(ids)))

    mc, mp = moy(ic), moy(ip)
    ecart = mc - mp
    print("   %s — critere (a), sur les MEMES tickets" % nom)
    dit("communs aux deux", ic & ip)
    dit("exclusifs production", ip - ic)
    dit("exclusifs candidate", ic - ip)
    print("      ecart candidate - production : %+0.3f EUR/ticket  ->  (a) %s"
          % (ecart, "FRANCHI" if ecart > 0 else "NON franchi"))

    # le bruit de l ECART, les deux regles rejouees ensemble sur chaque tirage
    try:
        import numpy as np
    except Exception:  # noqa: BLE001
        return ecart
    n = len(offerts)
    L = max(2, int(round(n ** (1 / 3))))
    # L ESPACEMENT REEL DOIT ETRE PRESERVE, et c est essentiel ici. Une premiere version replacait
    # les tickets a 60 s d intervalle regulier : ca DETRUIT les rafales d arrivee, et comme la pause
    # dure 1800 s elle bloquait alors bien plus que dans la realite -- le monde reechantillonne ne
    # ressemblait plus au monde observe (A ressortait a p = 0,81 pour un ecart observe de +0,84).
    # On garde donc les ecarts de temps A L INTERIEUR de chaque bloc, et on raboute les blocs avec
    # l ecart median du flux.
    ecarts_t = [offerts[k + 1]["t"] - offerts[k]["t"] for k in range(n - 1)]
    gap = st.median(ecarts_t) if ecarts_t else 60.0
    diffs = []
    for _ in range(600):
        dep = np.random.randint(0, max(1, n - L + 1), int(np.ceil(n / L)))
        ech, curseur = [], 0.0
        for d in dep:
            bloc = offerts[d:d + L]
            if not bloc:
                continue
            t0 = bloc[0]["t"]
            for x in bloc:
                t = curseur + (x["t"] - t0)
                ech.append(dict(x, t=t, fin=t + TENUE))
            curseur += (bloc[-1]["t"] - t0) + gap
        ech = ech[:n]
        pc = rejoue([x for x in ech if x[drapeau_c]], seuil_c)
        pp = rejoue([x for x in ech if x[drapeau_p]], seuil_p)
        if len(pc) >= 10 and len(pp) >= 10:
            diffs.append(MISE * st.mean(x["r"] for x in pc) - MISE * st.mean(x["r"] for x in pp))
    if diffs:
        lo, hi = np.percentile(diffs, [2.5, 97.5])
        print("      bruit de cet ecart (bootstrap par blocs, L=%d) : IC95 %+0.2f a %+0.2f · "
              "p(candidate <= prod) = %.3f%s"
              % (L, lo, hi, float(np.mean(np.array(diffs) <= 0)),
                 "" if (lo > 0 or hi < 0) else "  [ecart NON distinguable de zero]"))
    # CONCENTRATION : un ecart porte par deux tickets n est pas un ecart.
    for etiq, pris in ((" production", pris_p), (" candidate ", pris_c)):
        v = sorted((MISE * x["r"] for x in pris), reverse=True)
        tot = sum(v)
        print("      %s : total %+8.2f EUR · 3 meilleurs %+.2f (%.0f %%) · SANS eux %+0.3f/ticket"
              % (etiq, tot, sum(v[:3]), 100 * sum(v[:3]) / tot if tot else float("nan"),
                 st.mean(v[3:]) if len(v) > 3 else float("nan")))
    return ecart


def main() -> None:
    meta_f = os.path.join(DOSSIER, "modele_frais_meta.json")
    if not os.path.exists(meta_f):
        print("pas de gel trouve dans %s" % DOSSIER)
        return
    meta = json.load(open(meta_f))
    gel = float(meta["gel"])
    print("LES CANDIDATES GELEES LE %s" % meta["gel_lisible"])
    ecoule = (dt.datetime.now(TZ).timestamp() - gel) / 86400.0
    print("   %.1f jour(s) ecoules sur les 14 de l echeance" % ecoule)
    print()

    c = sqlite3.connect("file:%s?mode=ro" % COMBO, uri=True, timeout=30)
    lignes = []
    for t, vj, q, b, risq in c.execute(
            "SELECT d.t_dec, d.variables, d.q, i.brut_240, d.risque FROM decision d"
            " JOIN issue i ON i.pair=d.pair WHERE d.eligible=1 AND i.brut_240 IS NOT NULL"
            " AND d.q IS NOT NULL AND d.risque IS NOT NULL AND d.t_dec >= ? ORDER BY d.t_dec",
            (gel,)):
        lignes.append((float(t), vj, float(q), float(b), float(risq)))
    if not lignes:
        print("   aucun ticket posterieur au gel — revenir plus tard")
        return
    print("   %d tickets juges depuis le gel" % len(lignes))
    print()

    # UN SEUL FLUX, PORTANT LES DRAPEAUX DE TOUTES LES REGLES. Indispensable au critere (a) : sans
    # identite par ticket on ne peut pas dire lesquels sont communs et lesquels sont exclusifs, et
    # c est la seule chose qui puisse creer un ecart entre deux regles de selection.
    # `B` est mis a False d office et rempli plus bas si le modele frais est lisible.
    offerts = [{"i": i, "t": t, "fin": t + TENUE, "r": min(b - cout(q), 3.0),
                "prod": BANDE[0] <= r < BANDE[1], "B": False}
               for i, (t, vj, q, b, r) in enumerate(lignes)]

    prod = [x for x in offerts if x["prod"]]
    print("   LA PRODUCTION, pour reference")
    ref = dis("BANDE + PAUSE (-0,30)", rejoue(prod, -0.30), -0.30, prod)
    pris_prod = rejoue(prod, -0.30)
    print()
    print("   LES CANDIDATES")
    a = dis("A · PAUSE 25 (-0,25)", rejoue(prod, -0.25), -0.25, prod)
    pris_a = rejoue(prod, -0.25)

    na, nb = meta["bande_frais"]
    modele = os.path.join(DOSSIER, "modele_frais.json")
    pris_b = None
    if os.path.exists(modele):
        try:
            import lightgbm as lgb
            import numpy as np
            boost = lgb.Booster(model_file=modele)
            var = meta["variables"]
            X, ok = [], []
            for i, (t, vj, q, b, r) in enumerate(lignes):
                try:
                    f = json.loads(vj)
                except Exception:  # noqa: BLE001
                    continue
                # `float(f.get(k)) if ... is not None` et JAMAIS `float(f.get(k) or nan)` :
                # `0.0 or nan` vaut nan, donc cette seconde forme transforme tout ZERO en manquant
                # et deplace les scores du modele. Erreur commise et corrigee le 26/09.
                X.append([float(f.get(k)) if f.get(k) is not None else np.nan for k in var])
                ok.append(i)
            s = boost.predict(np.array(X, dtype=float))
            for k, i in enumerate(ok):
                offerts[i]["B"] = bool(na <= s[k] < nb)
            frais = [x for x in offerts if x["B"]]
            dis("B · MODELE FRAIS", rejoue(frais, -0.30), -0.30, frais)
            pris_b = rejoue(frais, -0.30)
        except Exception as exc:  # noqa: BLE001
            print("   B · MODELE FRAIS — illisible (%s)" % str(exc)[:70])

    print()
    print("   ECHEANCE : 200 tickets retenus OU 14 jours. (a) battre la production sur les memes")
    print("   tickets · (b) etre positive · (c) p < 0,05 contre le decalage circulaire.")
    print()
    if ref is not None and a is not None:
        critere_a("A · PAUSE 25", pris_a, pris_prod, offerts, "prod", "prod", -0.25, -0.30)
        print()
    if pris_b is not None:
        critere_a("B · MODELE FRAIS", pris_b, pris_prod, offerts, "B", "prod", -0.30, -0.30)


if __name__ == "__main__":
    main()
