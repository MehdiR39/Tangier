"""Test PAPIER vers l avant de la combinaison regime + risque de vidage (§3.85). Lance le 15/09.

Aucun ordre, aucune cle, aucune ecriture dans la base du moteur (lue en lecture seule). Ecrit dans
/app/db/papier_combo.sqlite.

CE QUI EST TESTE, FIGE AVANT LE DEPART
  population   tout pool PumpSwap suivi par le collecteur (prix corrige, lecture « processed »), vu des
               sa naissance, ou notre ordre de 0,31 SOL pese <= 15 %. « Vu des sa naissance » = premiere
               lecture a <= 32 s en direct : dans l historique les lectures avaient 12 s de retard, et le
               filtre « <= 20 s d age vrai » y retenait les premieres lectures jusqu a ~32 s d horloge
               (ajuste le 15/09 avant toute issue jugee : C6QE45iJ, 5 004 SOL, ecarte a 21 s).
  decision     a 45 s : variables de prix calculees EXACTEMENT comme grand_balayage_table.py.
  risque       probabilite de vidage du modele `modele_vidage.json` (LightGBM exporte, variables de prix
               seulement ; AUC hors echantillon 0,78 / 0,82) ; filtre : <= seuil p80 = 0,2694.
  regime       moyenne des 50 derniers resultats CONNUS (decision 60 s, sortie 240 s, cout reduit, tous
               les pools) ; filtre : > 0.
  entree       lecture la plus proche de 47 s ; sorties : 167 s (H=120) et 287 s (H=240).
  couts        reduit = 1,25 % + impact/2 (depot recupere, priorite baissee) ;
               reel actuel = 1,7 % + impact + 0,5 % (depot).
  CRITERE      ESSENTIEL : regime ET risque, H=120, cout reduit. SECONDAIRE : H=240.
               Apres 14 jours : moyenne >= +1,1 %, sans son meilleur > 0, positive sur les deux moities.
               Sinon : on arrete ce marche.

Lancement : python -m intel.research.papier_combo
Rapport   : python -m intel.research.papier_combo --rapport
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import sys
import time
from bisect import bisect_right

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from arbres import Modele  # noqa: E402

BASE_MOTEUR = os.environ.get("INTEL_DB", "/app/db/intel.sqlite")
BASE_ICI = os.environ.get("PAPIER_COMBO_DB", "/app/db/papier_combo.sqlite")
MODELE = os.environ.get("MODELE_VIDAGE", "/app/data/recherche/balayage/modele_vidage.json")
A, EXEC_S = 45, 2
MISE_SOL, COUT_FIXE = 0.31, 0.017
N_REGIME = 50


def a_age(ages, cible, tol):
    i = bisect_right(ages, cible)
    best = None
    for j in (i - 1, i):
        if 0 <= j < len(ages) and abs(ages[j] - cible) <= tol:
            if best is None or abs(ages[j] - cible) < abs(ages[best] - cible):
                best = j
    return best


PREMIER_MAX_DIRECT = 32


def variables(pts, naissance, lancements, A=A, premier_max=20):
    """pts : [(age, ts, prix, q, reserve_base, v)] tries par age. Rend (variables, e) ou None."""
    ages = [p[0] for p in pts]
    prix = [p[2] for p in pts]
    qs = [p[3] for p in pts]
    v = pts[0][5] or 0.0
    k = bisect_right(ages, A)
    if k < 3 or pts[0][0] > premier_max:
        return None
    e = a_age(ages, A + EXEC_S, 6)
    if e is None:
        return None
    pv, qv = prix[:k], qs[:k]
    if qv[-1] + v <= 0 or MISE_SOL / (qv[-1] + v) > 0.15:
        return None
    logs = [math.log(x) for x in pv]
    diffs = [b - a for a, b in zip(logs, logs[1:])]
    moy = sum(diffs) / len(diffs)
    f = {"n_lect": k, "ret_naiss": pv[-1] / pv[0] - 1, "dd_max": pv[-1] / max(pv) - 1,
         "depuis_min": pv[-1] / min(pv) - 1, "t_depuis_max": A - ages[pv.index(max(pv))],
         "vol": math.sqrt(sum((d - moy) ** 2 for d in diffs) / len(diffs)),
         "q": qv[-1], "q_croiss": qv[-1] / qv[0] - 1 if qv[0] > 0 else float("nan"),
         "heure": int(((naissance + A) % 86400) // 3600), "V": int(v > 0), "A": A,
         "cout": COUT_FIXE + 2 * MISE_SOL / (qv[-1] + v)}
    for w in (10, 30, 60, 120):
        j = a_age(ages, A - w, 6)
        f["ret_%d" % w] = (pv[-1] / prix[j] - 1) if (j is not None and j < k) else float("nan")
    for w in (30, 60):
        j = a_age(ages, A - w, 6)
        f["q_croiss_%d" % w] = (qv[-1] / qs[j] - 1) if (j is not None and j < k and qs[j] > 0) else float("nan")
    t_dec = naissance + A
    f["lancements_10min"] = bisect_right(lancements, t_dec) - bisect_right(lancements, t_dec - 600)
    return f, e


def schema(c):
    c.executescript("""
        CREATE TABLE IF NOT EXISTS ref(pair TEXT PRIMARY KEY, t_fin REAL, r REAL);
        CREATE TABLE IF NOT EXISTS decision(pair TEXT PRIMARY KEY, mint TEXT, naissance REAL, t_dec REAL,
            eligible INTEGER, q REAL, V INTEGER, risque REAL, regime REAL, n_regime INTEGER, p_entree REAL,
            cout_reduit REAL, cout_reel REAL, variables TEXT);
        CREATE TABLE IF NOT EXISTS issue(pair TEXT PRIMARY KEY, brut_120 REAL, brut_240 REAL, ts REAL);
    """)
    # la cotation de la prod, a blanc (27/09) : colonnes AJOUTEES, rien d existant ne change
    have = {r[1] for r in c.execute("PRAGMA table_info(decision)")}
    for col, typ in (("cote_statut", "TEXT"), ("cote_motif", "TEXT"), ("prix_cote", "REAL"),
                     ("age_cote", "REAL")):
        if col not in have:
            c.execute("ALTER TABLE decision ADD COLUMN %s %s" % (col, typ))
    c.commit()


# ============================================================ LA COTATION DE LA PROD, A BLANC
# 27/09, Mido : « papier et reel different, a quoi sert d avoir du papier ». Mesure du jour, ticket
# par ticket sur BANDE + PAUSE : sur les 106 tickets que la prod a achetes, papier +136,92 EUR et reel
# +157,23 -- ils concordent. Tout l ecart venait de 25 tickets que le papier « achetait » au prix du
# pool alors que la prod les refusait : le prix avait deja monte au moment de coter. Rachetes au prix
# cote, ils ne valaient plus +127,71 EUR mais +37,98 -- le papier promettait environ le double du reel.
#
# Le remede : demander, au meme moment, LA MEME cotation que la prod, par LA MEME fonction
# (`prepare_buy`, sans cle : elle cote, applique tous les refus et n assemble rien), avec LES MEMES
# reglages (lus dans `modele_rapide` de la config). On enregistre si la prod aurait pu acheter et a
# quel prix. Les colonnes sont AJOUTEES : `eligible`, `risque`, `brut_240` ne changent pas, donc la
# pause de la prod, qui lit ce carnet, ne voit aucune difference. La cotation tourne dans un FIL a
# part : un Jupiter lent ne doit jamais retarder l ecriture des issues que la pause lit.
COTE_ACTIVE = os.environ.get("PAPIER_COTE", "1") == "1"
_COTES = None


def _reglages_prod() -> dict:
    try:
        import yaml
        m = (yaml.safe_load(open(os.environ.get("INTEL_CONFIG", "/app/config/intel.yaml"))) or {}).get(
            "modele_rapide") or {}
    except Exception:  # noqa: BLE001
        m = {}
    return {"mise": float(m.get("mise_eur", 25.0)), "slip": float(m.get("slippage_achat_pct", 20.0)),
            "impact": float(m.get("max_impact_pct", 15.0)), "ecart": float(m.get("max_ecart_pool_pct", 20.0)),
            "ar": float(m.get("max_aller_retour_pct", 15.0))}


def _coter(pair, mint, prix_pool, naissance):
    """Dans le fil : la cotation de la prod, a blanc, puis l ecriture du resultat."""
    import asyncio
    import httpx
    from intel.execution import solana as sol
    R = _reglages_prod()
    try:
        dec = 6
        try:
            m = sqlite3.connect("file:%s?mode=ro" % BASE_MOTEUR, uri=True, timeout=10)
            r = m.execute("SELECT decimales FROM mint_offre WHERE mint=? LIMIT 1", (mint,)).fetchone()
            m.close()
            if r and r[0] is not None:
                dec = int(r[0])
        except Exception:  # noqa: BLE001
            pass

        async def go():
            async with httpx.AsyncClient() as client:
                taux = await sol.sol_eur(client)
                return await sol.prepare_buy(
                    client, mint=mint, size_eur=R["mise"], sol_eur=taux, slippage_pct=R["slip"],
                    max_impact_pct=R["impact"], prix_pool_sol=float(prix_pool or 0.0), decimales=dec,
                    max_ecart_pool_pct=R["ecart"], max_aller_retour_pct=R["ar"], proprietaire=None)
        tx = asyncio.run(go())
        if tx.get("status") == "BUILT" and int(tx.get("quoted_amount_out") or 0) > 0:
            prix = (int(tx["amount_in"]) / 1e9) / (int(tx["quoted_amount_out"]) / 10 ** dec)
            statut, motif = "ACHETABLE", None
        else:
            prix, statut, motif = None, "REFUSE", str(tx.get("refused_reason") or "")[:200]
    except Exception as exc:  # noqa: BLE001
        prix, statut, motif = None, "ERREUR", str(exc)[:200]
    try:
        c = sqlite3.connect(BASE_ICI, timeout=30)
        c.execute("UPDATE decision SET cote_statut=?, cote_motif=?, prix_cote=?, age_cote=? WHERE pair=?",
                  (statut, motif, prix, time.time() - naissance, pair))
        c.commit()
        c.close()
    except Exception as exc:  # noqa: BLE001
        print("papier_combo: cotation non ecrite (%s)" % str(exc)[:120], flush=True)


def coter_plus_tard(pair, mint, prix_pool, naissance):
    global _COTES
    if not COTE_ACTIVE:
        return
    if _COTES is None:
        from concurrent.futures import ThreadPoolExecutor
        _COTES = ThreadPoolExecutor(max_workers=2)
    _COTES.submit(_coter, pair, mint, prix_pool, naissance)


def tour(ici, moteur, modele):
    now = time.time()
    lancements = sorted(t for (t,) in moteur.execute(
        "SELECT MIN(ts) FROM solana_stream_launches WHERE ts > ? GROUP BY mint", (now - 3 * 3600,)))
    rows = moteur.execute(
        "SELECT pair_id, mint, ts, age_s, prix_sol, reserve_sol, reserve_base, reserve_virtuelle"
        " FROM solana_prix_chaine WHERE ts > ? AND reserve_virtuelle IS NOT NULL AND prix_sol > 0"
        " ORDER BY pair_id, age_s", (now - 1200,)).fetchall()
    pools = {}
    for pair, mint, ts, age, p, xs, xb, v in rows:
        pools.setdefault(pair, {"mint": mint, "pts": []})["pts"].append((age, ts, p, xs, xb, v))
    decides = {r[0] for r in ici.execute("SELECT pair FROM decision")}
    avec_issue = {r[0] for r in ici.execute("SELECT pair FROM issue")}
    avec_ref = {r[0] for r in ici.execute("SELECT pair FROM ref")}
    refs = ici.execute("SELECT t_fin, r FROM ref ORDER BY t_fin").fetchall()
    faits = 0
    for pair, d in pools.items():
        pts = d["pts"]
        naissance = pts[0][1] - pts[0][0]
        age_max = pts[-1][0]
        ages = [p[0] for p in pts]
        # --- decision a 45 s ---
        if pair not in decides and 50 <= age_max <= 120:
            res = variables(pts, naissance, lancements, premier_max=PREMIER_MAX_DIRECT)
            t_dec = naissance + A
            passes = [r for t, r in refs if t <= t_dec][-N_REGIME:]
            regime = sum(passes) / len(passes) if len(passes) == N_REGIME else None
            if res is None:
                ici.execute("INSERT OR IGNORE INTO decision(pair, mint, naissance, t_dec, eligible) VALUES(?,?,?,?,0)",
                            (pair, d["mint"], naissance, t_dec))
            else:
                f, e = res
                v = pts[0][5] or 0.0
                impact = 2 * MISE_SOL / (f["q"] + v)
                # COLONNES NOMMEES : l insertion positionnelle casserait des que la table a les
                # colonnes de cotation ajoutees le 27/09.
                ici.execute("INSERT OR IGNORE INTO decision(pair, mint, naissance, t_dec, eligible, q, V,"
                            " risque, regime, n_regime, p_entree, cout_reduit, cout_reel, variables)"
                            " VALUES(?,?,?,?,1,?,?,?,?,?,?,?,?,?)",
                            (pair, d["mint"], naissance, t_dec, f["q"], f["V"], modele.probabilite(f), regime,
                             len(passes), pts[e][2], 0.0125 + impact / 2, COUT_FIXE + impact + 0.005,
                             json.dumps(f)))
                ici.commit()             # la ligne doit exister quand le fil viendra l annoter
                coter_plus_tard(pair, d["mint"], pts[e][2], naissance)
            faits += 1
        # --- issue des decisions : sorties a 167 s et 287 s ---
        if pair in decides and pair not in avec_issue and age_max >= 297:
            dec = ici.execute("SELECT eligible FROM decision WHERE pair=?", (pair,)).fetchone()
            if dec and dec[0]:
                e = a_age(ages, A + EXEC_S, 6)
                s1, s2 = a_age(ages, A + EXEC_S + 120, 8), a_age(ages, A + EXEC_S + 240, 8)
                b1 = pts[s1][2] / pts[e][2] - 1 if (e is not None and s1 is not None and s1 > e) else None
                b2 = pts[s2][2] / pts[e][2] - 1 if (e is not None and s2 is not None and s2 > e) else None
                ici.execute("INSERT OR IGNORE INTO issue VALUES(?,?,?,?)", (pair, b1, b2, now))
            else:
                ici.execute("INSERT OR IGNORE INTO issue VALUES(?,NULL,NULL,?)", (pair, now))
        # --- resultat de reference du regime : decision 60 s, sortie 240 s, tous les pools ---
        if pair not in avec_ref and age_max >= 312 and pts[0][0] <= PREMIER_MAX_DIRECT:
            res = variables(pts, naissance, lancements, A=60, premier_max=PREMIER_MAX_DIRECT)
            if res is not None:
                f, e = res
                s = a_age(ages, 60 + EXEC_S + 240, 8)
                if s is not None and s > e:
                    brut = pts[s][2] / pts[e][2] - 1
                    r = min(brut - (0.0125 + (f["cout"] - COUT_FIXE) / 2), 3.0)
                    ici.execute("INSERT OR IGNORE INTO ref VALUES(?,?,?)", (pair, naissance + 60 + EXEC_S + 240, r))
    ici.commit()
    return faits


# BANDE DE RISQUE, PRE-ENREGISTREE le 17/09 a 16h30 UTC (18h30 Paris).
#
# CE QU ON A COMPRIS. Le modele de vidage ne mesure pas le danger, il mesure la VIE. Par quintile de
# risque predit, sur les 1 356 premiers tickets : le quintile le plus SUR n a AUCUN gain superieur a
# +50 % (zero sur 271), et 4,1 % de chutes ; le plus risque a 33 % de chutes mais 18 % de gros gains.
# Un jeton incapable de s effondrer est un jeton ou il ne se passe rien. Eviter le risque, c est donc
# aussi eviter le gain -- ce qui explique pourquoi toutes les ponderations continues par le score
# perdent de l argent, et pourquoi le seuil 0,2694 « marchait » : il tombait par accident au milieu
# du quatrieme quintile, le seul rentable.
#
# LA REGLE, FIGEE : acheter seulement si la probabilite de vidage predite est dans [0,20 ; 0,35[.
# Ni trop mort, ni trop dangereux. Le reste inchange : decision a 45 s, sortie a 287 s, cout reduit.
#
# MESURE AU GEL, sur les 1 356 tickets qui ont servi a la TROUVER -- donc a ne pas confondre avec une
# validation : 683 tickets, +3,90 % par ticket, +799 EUR, +2,59 % en retirant ses trois meilleurs,
# positive les trois jours (+339 / +156 / +304), 99,9e centile contre un tirage au hasard de meme
# taille. C est un plateau et non un pic : 0,22-0,32 donne +3,81 %, 0,20-0,30 +4,34 %, 0,24-0,30
# +7,64 %, alors que deborder a 0,25-0,45 fait tomber a -0,18 %.
#
# CRITERE, FIGE : au premier atteint de 300 tickets POSTERIEURS AU GEL ou de 21 jours --
#   moyenne >= +2,00 % par ticket, positive sur les deux moities, positive sans ses trois meilleurs
#   tickets. Sinon la bande est abandonnee. Le seuil de +2 % est celui qui separe cette bande du
#   reste : le hasard donne -0,70 % et le filtre actuel +0,68 %.
GEL_BANDE = 1789662600.0          # 17/09/2026 16h30 UTC
BANDE = (0.20, 0.35)
CRITERE_BANDE = 0.0200


# BANDE + PAUSE, PRE-ENREGISTREE le 17/09 a 21h30 UTC (23h30 Paris).
#
# POURQUOI. Le soir du gel de la bande, la perte n est pas venue d une degradation lente : elle est
# venue d UNE fenetre de deux heures ou 37 tickets sont tombes ensemble (-150 EUR), suivie d une
# autre (-66 EUR). Le marche entier avait tourne. Une pause -- on arrete 30 min apres un ticket qui
# ferme sous -30 % -- est exactement faite pour ca. Rejouee sur cette soiree : elle n a pris AUCUN
# ticket dans les deux mauvaises fenetres, et la bande serait passee de -181 EUR a +48 EUR.
#
# CE QU ELLE N EST PAS. Elle n augmente pas le gain, elle limite la casse. Sur les 2,25 jours
# d avant le gel elle donne +13,03 %/ticket contre +2,78 % pour la bande seule, mais en ne gardant
# que 84 tickets sur 684 : en EUROS par jour, 151 contre 263. Et garder 84 tickets AU HASARD parmi
# les 684 donne +2,78 % en moyenne avec un 95e centile a +14,82 % -- la pause tombe au centile 92,5,
# donc SOUS la barre du hasard. Ce n est pas un filtre qui trouve les bons tickets ; c est une
# reduction d exposition qui coupe les mauvais moments.
#
# HONNETETE. C est le dixieme candidat essaye le 17/09, et il a ete trouve en regardant la soiree
# qui venait de mal se passer. Il ne peut donc etre juge que sur ce qui vient APRES ce gel.
#
# CRITERE, FIGE : au premier atteint de 300 tickets de bande posterieurs au gel ou de 21 jours --
#   (a) le total de BANDE+PAUSE doit depasser celui de BANDE SEULE sur la meme periode, et
#   (b) BANDE+PAUSE doit etre positive.
# La comparaison est APPARIEE (memes tickets, meme marche, seule la regle change), ce qui est bien
# plus puissant qu un seuil absolu -- et c est la seule question qui compte : la pause aide-t-elle ?
GEL_BP = 1789680600.0             # 17/09/2026 21h30 UTC = 23h30 Paris
PAUSE_S, SEUIL_PAUSE = 1800.0, -0.30
TENUE_S = 242.0                   # entree a 47 s, sortie a 287 s


def appliquer_pause(tickets):
    """Ecarte les tickets ouverts pendant les 30 min qui suivent une cloture sous -30 %.

    Le blocage part de la CLOTURE du perdant, pas de son ouverture : c est a ce moment-la qu on
    apprend la perte. Un moteur ne peut pas reagir a une information qu il n a pas encore.
    """
    pris, attente, bloque = [], [], 0.0
    for t in tickets:
        attente.sort(key=lambda z: z["fin"])
        while attente and attente[0]["fin"] <= t["t"]:
            f = attente.pop(0)
            if f["r"] <= SEUIL_PAUSE:
                bloque = max(bloque, f["fin"] + PAUSE_S)
        if t["t"] >= bloque:
            pris.append(t)
        attente.append(t)
    return pris


def rapport_bande_pause(ici):
    """La bande avec pause, comparee a la bande seule sur EXACTEMENT les memes tickets."""
    rows = ici.execute("""SELECT d.t_dec, d.risque, i.brut_240, d.cout_reduit FROM decision d
                          JOIN issue i ON i.pair=d.pair WHERE d.eligible=1 AND i.brut_240 IS NOT NULL
                          AND d.risque IS NOT NULL AND d.t_dec >= ? ORDER BY d.t_dec""",
                       (GEL_BP,)).fetchall()
    b = [{"t": r[0], "fin": r[0] + TENUE_S, "r": min(r[2] - r[3], 3.0)}
         for r in rows if BANDE[0] <= r[1] < BANDE[1]]
    print("\nBANDE + PAUSE · PRE-ENREGISTREE le 17/09 a 23h30 Paris")
    print("   %d ticket(s) de bande depuis le gel, sur les 300 du critere" % len(b))
    if b:
        p = appliquer_pause(b)
        ts = sum(x["r"] for x in b)
        tp = sum(x["r"] for x in p)
        print("   bande seule   : n=%4d · %+7.2f %% · %+7.0f EUR (a 30 EUR)"
              % (len(b), 100 * ts / len(b), 30 * ts))
        if p:
            print("   bande + pause : n=%4d · %+7.2f %% · %+7.0f EUR" % (len(p), 100 * tp / len(p), 30 * tp))
            tenu = tp > ts and tp > 0
            print("   -> la pause apporte %+.0f EUR · %s" % (30 * (tp - ts),
                                                             "CRITERE TENU" if tenu else "critere non atteint"))
        else:
            print("   bande + pause : aucun ticket (pause active tout du long)")
    print("   CRITERE : total(bande+pause) > total(bande seule) ET positif, a 300 tickets ou 21 jours.")


def rapport_bande(ici):
    """La bande de risque, jugee UNIQUEMENT sur les tickets posterieurs a son gel."""
    rows = ici.execute("""SELECT d.t_dec, d.risque, i.brut_240, d.cout_reduit FROM decision d
                          JOIN issue i ON i.pair=d.pair WHERE d.eligible=1 AND i.brut_240 IS NOT NULL
                          AND d.risque IS NOT NULL AND d.t_dec >= ? ORDER BY d.t_dec""",
                       (GEL_BANDE,)).fetchall()
    v = [min(r[2] - r[3], 3.0) for r in rows if BANDE[0] <= r[1] < BANDE[1]]
    print("\nBANDE DE RISQUE [%.2f ; %.2f[ · PRE-ENREGISTREE le 17/09 a 18h30 Paris" % BANDE)
    print("   %d ticket(s) depuis le gel, sur %d juges" % (len(v), len(rows)))
    if v:
        s = sorted(v, reverse=True)
        m = len(v) // 2
        print("   %+.2f %% par ticket · %+.0f EUR · gagnants %.0f %%"
              % (100 * sum(v) / len(v), 30 * sum(v), 100 * sum(1 for x in v if x > 0) / len(v)))
        if len(v) > 3:
            print("   sans les 3 meilleurs %+.2f %% · moities %+.2f %% / %+.2f %%"
                  % (100 * sum(s[3:]) / (len(s) - 3), 100 * sum(v[:m]) / max(m, 1),
                     100 * sum(v[m:]) / max(len(v) - m, 1)))
    print("   CRITERE : >= +%.2f %% par ticket, deux moities > 0, positive sans ses 3 meilleurs,"
          % (100 * CRITERE_BANDE))
    print("   a 300 tickets posterieurs au gel ou 21 jours.")


def rapport(ici):
    rows = ici.execute("""SELECT d.t_dec, d.risque, d.regime, d.cout_reduit, d.cout_reel, i.brut_120, i.brut_240
                          FROM decision d JOIN issue i ON i.pair=d.pair WHERE d.eligible=1 ORDER BY d.t_dec""").fetchall()
    seuil = Modele(MODELE).seuil_p80
    n_ref = ici.execute("SELECT COUNT(*) FROM ref").fetchone()[0]
    if not rows:
        print("aucune decision terminee (references du regime : %d)" % n_ref)
        return
    debut, fin = rows[0][0], rows[-1][0]
    jours = max((fin - debut) / 86400, 1e-9)
    print("depuis %s · %.2f jours · %d decisions terminees · references du regime %d" % (
        time.strftime("%d/%m %H:%M", time.gmtime(debut + 7200)), jours, len(rows), n_ref))
    variantes = {
        "tout": lambda r: True,
        "regime": lambda r: r[2] is not None and r[2] > 0,
        "risque": lambda r: r[1] <= seuil,
        "REGIME + RISQUE": lambda r: r[2] is not None and r[2] > 0 and r[1] <= seuil,
    }
    for H, col in ((120, 5), (240, 6)):
        for cout_nom, ccol in (("reduit", 3), ("reel", 4)):
            print("\nH=%d s, cout %s" % (H, cout_nom))
            for nom, f in variantes.items():
                v = [min(r[col] - r[ccol], 3.0) for r in rows if f(r) and r[col] is not None]
                if not v:
                    print("   %-16s aucun" % nom)
                    continue
                s = sorted(v, reverse=True)
                moit = len(v) // 2
                m1 = sum(v[:moit]) / moit if moit else float("nan")
                m2 = sum(v[moit:]) / (len(v) - moit)
                print("   %-16s n=%4d · moyenne %+.4f · sans best %+.4f · vides %4.1f %% · moities %+.4f / %+.4f · %+.0f EUR/jour a 30 EUR%s"
                      % (nom, len(v), sum(v) / len(v), (sum(s[1:]) / (len(s) - 1)) if len(s) > 1 else float("nan"),
                         100 * sum(1 for x in v if x <= -0.5) / len(v), m1, m2, len(v) / jours * (sum(v) / len(v)) * 30,
                         "   <- CRITERE ESSENTIEL" if (H == 120 and cout_nom == "reduit" and nom == "REGIME + RISQUE") else ""))
    rapport_bande(ici)
    rapport_bande_pause(ici)


def main():
    ici = sqlite3.connect(BASE_ICI, timeout=30)
    schema(ici)
    if "--rapport" in sys.argv:
        rapport(ici)
        return
    moteur = sqlite3.connect("file:%s?mode=ro" % BASE_MOTEUR, uri=True, timeout=30)
    modele = Modele(MODELE)
    print("papier_combo: demarre · modele %d arbres · seuil %.4f" % (len(modele.arbres), modele.seuil_p80), flush=True)
    while True:
        try:
            tour(ici, moteur, modele)
        except Exception as exc:  # noqa: BLE001
            print("papier_combo: tour rate (%s)" % str(exc)[:160], flush=True)
        time.sleep(10)


if __name__ == "__main__":
    main()
