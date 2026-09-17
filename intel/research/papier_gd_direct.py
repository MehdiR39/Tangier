"""G+D joue en PAPIER, en direct, avec les yeux du bot d aujourd hui (2 s). Gele le 16/09 a 16h20 UTC.

Aucun ordre, aucune cle, aucune signature. Ecrit dans /app/db/papier_gd.sqlite et nulle part ailleurs.

POURQUOI UN PROCESSUS A PART, et pas une relecture comme `papier_gd.py`. Le compte des acheteurs vient de
`v1_enregistreur`, qui n ecrit sa ligne qu apres 70 s : en relecture on ne pourrait entrer qu a ~65 s. Or entrer
a 65 s au lieu de 47 s coute **-3,65 points par ticket** (+5,36 % -> +1,70 %, mesure appariee sur les 306 pools
ou on voit chaque transaction, 16/09) -- soit tout l avantage. Il fallait donc decider a 45 s en direct.

LA REGLE, FIGEE AVANT LE DEPART
  population   tout pool PumpSwap suivi par `solana_prix_chaine`, ordre de 0,31 SOL <= 15 % du coffre a l entree.
  G            acheteurs uniques avant 45 s <= 74  ET  coffre (SOL + reserve virtuelle) < 100 SOL.
  D            tendance > 0 = moyenne des 50 derniers resultats connus (table `ref` de papier_combo.sqlite).
  entree       des que la decision est prise, au plus tot 47 s, au plus tard 55 s (au-dela on renonce :
               a 65 s la regle ne vaut plus rien, mesure ci-dessus).
  sortie       lecture du pool toutes les 2 s ; premiere lecture >= entree x 1,25 -> on vend a la lecture
               suivante >= 2 s plus tard ; sinon a 287 s. Gain plafonne a +300 %.
  pause        apres un ticket clos a <= -30 %, plus d entree pendant 30 min.
  cout         2,62 points par ticket (calibration sur 236 tickets reels).
  CRITERE      au bout de 300 tickets ou de 21 jours : moyenne >= +4,5 % par ticket, positive sur les deux
               moities, positive sans son meilleur ticket. Sinon la regle est abandonnee.
  A SAVOIR     le backtest donne +9,71 % par ticket, mais 77 % de son total vient d UNE journee (10/09) et
               3 tickets sur 126 en font les deux tiers. Une journee normale y vaut +14 EUR, pas +52.

ECONOMIE DES CREDITS. Les deux filtres gratuits (coffre, tendance) passent d abord : ils lisent la base, pas la
chaine. Seuls les survivants -- environ un pool sur cinq -- coutent un appel `getTransactionsForAddress` pour
compter les acheteurs. Le suivi a 2 s ne tourne que sur les tickets ouverts.

Lancement : python -m intel.research.papier_gd_direct
Rapport   : python -m intel.research.papier_gd_direct --rapport
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import os
import sqlite3
import struct
import sys
import time
from collections import deque

import base58

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import copie_collecte as cc  # noqa: E402

BASE = os.environ.get("INTEL_DB", "/app/db/intel.sqlite")
BASE_COMBO = os.environ.get("PAPIER_COMBO_DB", "/app/db/papier_combo.sqlite")
ICI = os.environ.get("PAPIER_GD_DB", "/app/db/papier_gd.sqlite")
# ATTENTION : l heure de l operateur est celle de PARIS, UTC+2 en septembre. Premiere version de ce
# fichier : gel a 16h20 « UTC » alors qu il etait 14h08 UTC -- le test serait reste inerte deux heures
# sans rien juger, et je l aurais annonce comme demarre. Mido l a vu a la minute (« 16h25 il est 16:07 »).
# Toute heure ecrite ici est en UTC, toute heure dite a l operateur est a Paris.
# Chaque age de decision a SON gel, a l instant ou il a ete decide : 45 s le 16/09 a 14h10 UTC,
# 30 s le 16/09 a 16h10 UTC (apres la mesure des ages d entree). Un test ne juge que des pools nes
# apres son propre gel, sinon ce n est plus un test vers l avant.
GELS = {45: dt.datetime(2026, 9, 16, 14, 10, tzinfo=dt.timezone.utc).timestamp(),
        30: dt.datetime(2026, 9, 16, 16, 10, tzinfo=dt.timezone.utc).timestamp()}

FOULE_MAX, COFFRE_MAX = 74, 100.0
# L AGE DE DECISION est le seul reglage variable : on en fait tourner deux en parallele, 45 s (le
# reglage historique, jamais compare a rien) et 30 s. Mesure du 16/09 sur 3 268 pools, meme regle,
# meme sortie, seul l age change : a 30 s +8,05 % par ticket sur 200 tickets (moities +5,03 / +11,08),
# a 45 s +5,02 % sur 115 (moities +15,02 / -4,80). Le pic a 30 s peut etre du hasard -- quatre ages
# testes -- mais la STABILITE des deux moities, elle, ne l est pas. D ou ce second test, gele a part.
A = int(os.environ.get("PAPIER_GD_AGE", "45"))
# REGLE = "large" : on prend TOUT ce qui passe le coffre, sans regarder la foule, la tendance ni la
# pause -- mais on enregistre leurs valeurs A L INSTANT DE LA DECISION. On peut alors evaluer apres
# coup n importe quelle regle (coffre seul, D, G, D+F, G+D) sur exactement les memes tickets, ce qu un
# test par regle ne permet pas : chacun verrait des pools differents et on comparerait des periodes.
# L inverse est impossible -- un ticket refuse ne revient jamais.
REGLE = os.environ.get("PAPIER_GD_REGLE", "gd")
GEL = float(os.environ.get("PAPIER_GD_GEL") or GELS.get(A) or time.time())
ENTREE_MAX, FIN_S = A + 10, 287
TP, PLAFOND, COUT, MISE_EUR, MISE_SOL = 0.25, 3.0, 0.0262, 30.0, 0.31
RETARD, PAS_SUIVI, PAUSE, SEUIL_PAUSE = 2.0, 2.0, 1800, -0.30
N_REGIME, PLAFOND_JOUR = 50, 40_000
# Le moteur tient 4 lignes au plus (`solana.max_open_positions`), parce que 4 x 30 EUR = 120 EUR sur un
# portefeuille de 185. Mais un test PAPIER n a pas de capital : on enregistre tout, et on rejouera
# n importe quel plafond ensuite sur les tickets collectes. L inverse est impossible -- un ticket refuse
# ne revient jamais. La contrainte de capital se remet a l analyse, pas a la collecte.
# En mode large les positions sont tenues 30 min au lieu de 5 : la nuit ca fait ~14 simultanees
# (mesure : 0,5 ticket/minute), mais le flux de journee est trois a quatre fois plus dense. Comme
# `prix_multiples` decoupe desormais ses lectures par 100 comptes, le plafond n est plus dicte par
# l API : 120 laisse de la marge sans jamais refuser un ticket aux heures pleines.
MAX_OUVERTS = 120 if os.environ.get("PAPIER_GD_REGLE") == "large" else 25

# EMISSION VERS LE MOTEUR, inerte par defaut. Mise a 1, chaque ticket pris ecrit AUSSI une ligne dans
# la table `decisions` du moteur, avec un `model_version` a part : c est la SEULE chose qui separe deux
# carnets (§5.17), et `_positions` ne regarde que le sien, donc ces lignes ne declenchent rien tant
# qu on ne branche pas deliberement l execution dessus. C est la premiere des quatre etapes avant le
# reel : ecrire, verifier que l ecrit correspond au decide, executer a blanc, rejouer en deux moities.
EMETTRE = os.environ.get("PAPIER_GD_EMETTRE") == "1"
MODELE_GD = os.environ.get("PAPIER_GD_MODELE", "sol-gd-v0.1")
CHAIN_ID = os.environ.get("INTEL_CHAIN_ID", "4663")
MISE_EMISE = float(os.environ.get("PAPIER_GD_MISE_EUR", "10"))
TAILLE_POOL, OFF_BASE_TA, OFF_VIRTUELLE = 301, 43 + 32 * 3, 245
SOL_MINT = "So11111111111111111111111111111111111111112"   # en dur : ce module ne doit dependre de rien
SLIPPAGE_BPS = int(os.environ.get("PAPIER_GD_SLIPPAGE_BPS", "2500"))   # 25 %, comme le moteur a la vente
LAMPORTS = 1_000_000_000


def schema(c):
    c.executescript("""
        CREATE TABLE IF NOT EXISTS decision(pair TEXT PRIMARY KEY, mint TEXT, naissance REAL, t_dec REAL,
            pris INTEGER, motif TEXT, acheteurs INTEGER, coffre REAL, tendance REAL, age_entree REAL,
            prix_entree REAL);
        CREATE TABLE IF NOT EXISTS issue(pair TEXT PRIMARY KEY, brut REAL, net REAL, age_sortie REAL,
            motif TEXT, sommet REAL, ts REAL);
        CREATE TABLE IF NOT EXISTS meta(cle TEXT PRIMARY KEY, valeur TEXT);
    """)
    # Mesure ISO-PROD, ajoutee le 17/09 : ce que le ROUTEUR cote reellement, a l entree et a la
    # sortie. `net` reste le calcul sur le prix du pool moins 2,62 pts ; `net_reel` est le
    # rendement d un aller-retour reellement cote. Les deux cote a cote disent enfin de combien le
    # cout forfaitaire se trompe.
    # Le COUT DU RETARD, mesure et non suppose : on recote la meme entree quelques secondes plus tard.
    # Entre la decision et le remplissage il y a la file du moteur (cotation, construction, envoi,
    # confirmation) et je supposais 2 s. `jetons_2s`, `jetons_5s`, `jetons_10s` disent ce qu on aurait
    # vraiment recu a chacun de ces retards -- l ecart avec `jetons_cotes` est le prix de la lenteur.
    for table, col in (("decision", "jetons_cotes REAL"), ("decision", "impact_entree REAL"),
                       ("decision", "jetons_2s REAL"), ("decision", "jetons_5s REAL"),
                       ("decision", "jetons_10s REAL"),
                       ("issue", "sol_recu REAL"), ("issue", "net_reel REAL"),
                       ("issue", "impact_sortie REAL"), ("issue", "jalons TEXT"),
                       ("issue", "sol_recu_4min REAL"), ("issue", "net_reel_4min REAL")):
        try:
            c.execute("ALTER TABLE %s ADD COLUMN %s" % (table, col))
        except Exception:  # noqa: BLE001
            pass
    c.commit()


# --- lectures de la chaine -------------------------------------------------------------------------

def comptes_du_pool(pool, cache):
    """(base_ta, quote_ta, reserve virtuelle) lus une fois dans le compte du pool."""
    if pool in cache:
        return cache[pool]
    res = cc.rpc({"jsonrpc": "2.0", "id": 1, "method": "getAccountInfo",
                  "params": [pool, {"encoding": "base64", "commitment": "processed"}]}) or {}
    data = ((res or {}).get("value") or {}).get("data")
    if not data:
        return None
    try:
        d = base64.b64decode(data[0])
        if len(d) < TAILLE_POOL:
            return None
        base_ta = base58.b58encode(d[OFF_BASE_TA:OFF_BASE_TA + 32]).decode()
        quote_ta = base58.b58encode(d[OFF_BASE_TA + 32:OFF_BASE_TA + 64]).decode()
        v = struct.unpack_from("<Q", d, OFF_VIRTUELLE)[0] / 1e9
    except Exception:  # noqa: BLE001
        return None
    cache[pool] = (base_ta, quote_ta, v if 0.0 <= v <= 50.0 else 0.0)
    return cache[pool]


def prix_du_pool(comptes):
    """(prix en SOL par jeton, coffre SOL total) lus dans les deux reserves. None si illisible."""
    base_ta, quote_ta, v = comptes
    res = cc.rpc({"jsonrpc": "2.0", "id": 1, "method": "getMultipleAccounts",
                  "params": [[base_ta, quote_ta], {"encoding": "jsonParsed", "commitment": "processed"}]}) or {}
    vals = (res or {}).get("value") or []
    if len(vals) < 2 or not vals[0] or not vals[1]:
        return None
    try:
        if vals[1]["data"]["parsed"]["info"].get("mint") != SOL_MINT:
            return None                                   # le second compte n est pas du SOL (§3.82)
        b = float(vals[0]["data"]["parsed"]["info"]["tokenAmount"]["uiAmountString"])
        q = float(vals[1]["data"]["parsed"]["info"]["tokenAmount"]["uiAmountString"])
    except Exception:  # noqa: BLE001
        return None
    return ((q + v) / b, q + v) if b > 0 else None


def acheteurs_avant(pair, mint, t0, V):
    """Acheteurs uniques dans les 45 premieres secondes. Un appel, ~10 credits."""
    opts = {"transactionDetails": "full", "sortOrder": "asc", "limit": 1000, "encoding": "jsonParsed",
            "maxSupportedTransactionVersion": 1,
            "filters": {"blockTime": {"gte": int(t0) - 5, "lte": int(t0) + A}, "status": "succeeded"}}
    res = cc.rpc({"jsonrpc": "2.0", "id": 1, "method": "getTransactionsForAddress",
                  "params": [pair, opts]}) or {}
    qui, n = set(), 0
    for tx in res.get("data") or []:
        n += 1
        a = cc.analyser(tx, pair, mint, V or 0.0, t0)
        if not a:
            continue
        for o, djetons, dsol in a[4]:
            if o and djetons > 0:
                qui.add(o)
    return len(qui), n


# --- etat du moteur, gratuit ----------------------------------------------------------------------

def candidats(vus, maintenant):
    """Les pools nes il y a 44 a 52 s, avec leur premiere lecture de coffre."""
    c = sqlite3.connect("file:%s?mode=ro" % BASE, uri=True, timeout=60)
    c.row_factory = sqlite3.Row
    out = []
    for r in c.execute(
            "SELECT p.pair_id, p.mint, MIN(p.ts - p.age_s) naissance,"
            "       MIN(p.reserve_sol + COALESCE(p.reserve_virtuelle, 0)) coffre"
            " FROM solana_prix_chaine p WHERE p.ts > ? AND p.reserve_virtuelle IS NOT NULL"
            " GROUP BY p.pair_id", (maintenant - 300,)):
        if r["pair_id"] in vus or not r["naissance"]:
            continue
        age = maintenant - r["naissance"]
        if A - 1 <= age <= A + 7 and r["naissance"] >= GEL:
            out.append((r["pair_id"], r["mint"], float(r["naissance"]), float(r["coffre"] or 0)))
    c.close()
    return out


def tendance(t_dec):
    c = sqlite3.connect("file:%s?mode=ro" % BASE_COMBO, uri=True, timeout=60)
    v = [x[0] for x in c.execute("SELECT r FROM ref WHERE t_fin <= ? ORDER BY t_fin DESC LIMIT ?",
                                 (t_dec, N_REGIME))]
    c.close()
    return (sum(v) / len(v)) if len(v) == N_REGIME else None


# --- la boucle ------------------------------------------------------------------------------------

# En mode large on suit jusqu a 30 MINUTES, la duree de detention de la production, et on note des
# jalons : les prix a plusieurs horizons, et le premier passage par chaque seuil avec le prix qu on
# obtiendrait 2 s plus tard. Ca permet de rejouer APRES COUP n importe quelle sortie -- la notre
# (+25 % ou 287 s) comme celle du moteur (x1,5, stop 0,7, echeance 1800 s) -- sur les memes tickets.
# Sans ca on ne peut comparer que des entrees, et l operateur a raison : la sortie compte autant.
SUIVI_MAX = 1800 if os.environ.get("PAPIER_GD_REGLE") == "large" else FIN_S
HORIZONS = (167, 287, 600, 900, 1200, 1500, 1800)
SEUILS = (1.25, 1.5, 2.0, 0.7)


def jalonner(t, prix, age):
    """Note les horizons franchis et les premiers passages de seuil. Modifie `t` en place."""
    for h in HORIZONS:
        if age >= h and ("h%d" % h) not in t["jalons"]:
            t["jalons"]["h%d" % h] = prix
    for s in SEUILS:
        cle = "s%s" % s
        atteint = prix >= t["p0"] * s if s > 1 else prix <= t["p0"] * s
        if atteint and cle not in t["jalons"]:
            t["jalons"][cle] = {"age": round(age, 1), "prix": prix}
        # le prix REELLEMENT obtenable 2 s apres le franchissement, seule sortie honnete
        j = t["jalons"].get(cle)
        if isinstance(j, dict) and "apres" not in j and age >= j["age"] + RETARD:
            j["apres"] = prix


def avancer(p0, declenche, prix, age):
    """La decision de sortie, isolee et SANS effet de bord, pour pouvoir la tester.

    Rend (nouveau declenche, motif de sortie ou None). Le declenchement et la vente sont deux
    instants distincts : on constate le franchissement de +25 %, puis on vend a la premiere lecture
    au moins RETARD secondes plus tard -- c est le delai d execution, et c est la seule convention
    honnete (§3.96 : vendre au prix du declenchement gonflait les resultats de 20 a 40 %).
    """
    if prix is None:
        return declenche, ("echeance" if age > FIN_S + 20 else None)
    if declenche is None and prix >= p0 * (1 + TP):
        return age, None
    if declenche is not None and age >= declenche + RETARD:
        return declenche, "prise de gain"
    if age >= FIN_S:
        return declenche, "echeance"
    return declenche, None


def prix_multiples(ouverts):
    """UNE seule lecture de chaine pour toutes les positions ouvertes. Rend {pair: prix}.

    C est ce qui rend le suivi parallele moins cher que l ancien suivi d un seul ticket : deux
    comptes par position dans un seul `getMultipleAccounts`, au lieu d un appel par position.
    """
    if not ouverts:
        return {}
    comptes = []
    for t in ouverts:
        comptes += [t["comptes"][0], t["comptes"][1]]
    # `getMultipleAccounts` n accepte que 100 comptes : on decoupe, sinon le plafond de positions
    # serait dicte par une limite d API plutot que par la strategie. En journee le flux est trois a
    # quatre fois plus dense que la nuit et 45 positions simultanees seraient atteintes.
    vals = []
    for d in range(0, len(comptes), 100):
        res = cc.rpc({"jsonrpc": "2.0", "id": 1, "method": "getMultipleAccounts",
                      "params": [comptes[d:d + 100],
                                 {"encoding": "jsonParsed", "commitment": "processed"}]}) or {}
        lot = (res or {}).get("value") or []
        if len(lot) < len(comptes[d:d + 100]):
            lot = lot + [None] * (len(comptes[d:d + 100]) - len(lot))   # garder l alignement
        vals += lot
    out = {}
    for i, t in enumerate(ouverts):
        a, b = (vals[2 * i] if 2 * i < len(vals) else None), (vals[2 * i + 1] if 2 * i + 1 < len(vals) else None)
        if not a or not b:
            continue
        try:
            if b["data"]["parsed"]["info"].get("mint") != SOL_MINT:
                continue                                   # le second compte n est pas du SOL (§3.82)
            base = float(a["data"]["parsed"]["info"]["tokenAmount"]["uiAmountString"])
            quote = float(b["data"]["parsed"]["info"]["tokenAmount"]["uiAmountString"])
        except Exception:  # noqa: BLE001
            continue
        if base > 0:
            out[t["pair"]] = (quote + t["comptes"][2]) / base
    return out


def emettre(pair, mint, n_ach, coffre, tend, age, prix_sol):
    """Ecrit la decision dans la table du moteur, sous un `model_version` a part. N execute rien.

    Le prix est en SOL par jeton -- c est ce qu on a lu dans le pool. Le carnet du moteur, lui, stocke
    des dollars pour les lignes T+1 : on ne melange pas les deux, d ou le `model_version` distinct et
    l unite ecrite noir sur blanc dans metrics_json.
    """
    if not EMETTRE:
        return None
    try:
        c = sqlite3.connect(BASE, timeout=30)
        cur = c.execute(
            "INSERT INTO decisions(ts, chain_id, token_address, label, kind, reason, price, size_eur,"
            " sent, metrics_json, model_version) VALUES(?,?,?,?,'BUY',?,?,?,0,?,?)",
            (int(time.time()), CHAIN_ID, mint, (mint or pair)[:8],
             "G+D a %d s · %d acheteurs, coffre %.1f SOL, tendance %+.4f" % (A, n_ach, coffre, tend),
             prix_sol, MISE_EMISE,
             json.dumps({"pair": pair, "age_decision": A, "age_entree": round(age, 1),
                         "acheteurs": n_ach, "coffre_sol": round(coffre, 3), "tendance": round(tend, 6),
                         "prix_unite": "SOL par jeton", "objectif": TP, "echeance_s": FIN_S}),
             MODELE_GD))
        c.commit()
        rid = cur.lastrowid
        c.close()
        return rid
    except Exception as exc:  # noqa: BLE001
        print("papier_gd: emission impossible (%s)" % str(exc)[:90], flush=True)
        return None


JUP = "https://lite-api.jup.ag/swap/v1/quote"


def coter(entree, sortie, montant):
    """La VRAIE cotation du routeur, celle que le moteur utiliserait pour passer l ordre.

    Rend le montant recu (en unites de `sortie`), ou None. C est ce qui rend la mesure iso-prod :
    elle contient le glissement, l impact et les frais de route, au lieu du cout forfaitaire de
    2,62 points calibre sur d anciens tickets a un tout autre rythme. Ne signe rien, ne construit
    aucune transaction -- une cotation est une lecture.
    """
    import urllib.request
    url = "%s?inputMint=%s&outputMint=%s&amount=%d&slippageBps=%d" % (
        JUP, entree, sortie, int(montant), int(SLIPPAGE_BPS))
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Tangier/1.0"}),
                                   timeout=10)
        d = json.loads(r.read().decode())
        return int(d["outAmount"]), float(d.get("priceImpactPct") or 0)
    except Exception:  # noqa: BLE001
        return None


def clore(ici, t, prix, motif):
    brut = min(prix / t["p0"] - 1, PLAFOND)
    net = brut - COUT
    # ISO-PROD : ce que le routeur nous rendrait vraiment en revendant les jetons qu il nous aurait
    # donnes a l entree. L aller-retour cote contient tous les couts, sans aucune hypothese.
    sol_recu = net_reel = impact = None
    if t.get("jetons"):
        q = coter(t["mint"], SOL_MINT, t["jetons"])
        if q:
            sol_recu, impact = q[0] / LAMPORTS, q[1]
            net_reel = min(sol_recu / MISE_SOL - 1, PLAFOND)
    q4 = t.get("q4")
    sol4 = (q4[0] / LAMPORTS) if q4 else None
    net4 = min(sol4 / MISE_SOL - 1, PLAFOND) if sol4 else None
    ici.execute("INSERT OR IGNORE INTO issue(pair, brut, net, age_sortie, motif, sommet, ts,"
                " sol_recu, net_reel, impact_sortie, jalons, sol_recu_4min, net_reel_4min)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (t["pair"], brut, net, time.time() - t["naissance"], motif,
                 t["sommet"] / t["p0"] - 1, time.time(), sol_recu, net_reel, impact,
                 json.dumps(t.get("jalons") or {}) if t.get("jalons") else None, sol4, net4))
    ici.commit()
    print("papier_gd: %s sortie %s a x%.2f -> %+.2f %% (%+.2f EUR)%s"
          % (t["pair"][:8], motif, prix / t["p0"], 100 * net, MISE_EUR * net,
             (" · routeur %+.2f %%" % (100 * net_reel)) if net_reel is not None else ""), flush=True)
    return net


def gel_de(ici):
    """Le gel est ECRIT DANS LA BASE a la premiere execution, et relu ensuite.

    Sans ca, chaque relance devait recevoir son gel par variable d environnement : un oubli, et le
    test recommencait a zero -- ou pire, jugeait des pools nes avant sa propre decision, ce qui
    n est plus un test vers l avant. Le chien de garde relance sans rien savoir : c est a la base
    de se souvenir.
    """
    global GEL
    r = ici.execute("SELECT valeur FROM meta WHERE cle='gel'").fetchone()
    if r:
        GEL = float(r[0])
    elif "--rapport" in sys.argv:
        pass                    # un rapport LIT, il n ecrit jamais : il ne doit pas poser un gel
    else:
        ici.execute("INSERT INTO meta VALUES('gel', ?)", (str(GEL),))
        ici.execute("INSERT OR REPLACE INTO meta VALUES('regle', ?)", (REGLE,))
        ici.execute("INSERT OR REPLACE INTO meta VALUES('age', ?)", (str(A),))
        ici.commit()
    return GEL


def main():
    ici = sqlite3.connect(ICI, timeout=30)
    schema(ici)
    gel_de(ici)
    if "--rapport" in sys.argv:
        rapport(ici)
        return
    # Un redemarrage perd les positions en cours : elles restent « prises » sans issue, et l analyse
    # les compterait comme des tickets alors qu on ne connait pas leur sortie. On les marque
    # explicitement interrompues -- avec `jalons` vide, donc ecartees par le rapport -- plutot que de
    # les laisser disparaitre en silence. Le chien de garde redemarre, cela arrivera encore.
    orphelines = ici.execute(
        "SELECT pair FROM decision WHERE pris=1 AND pair NOT IN (SELECT pair FROM issue)").fetchall()
    for (p,) in orphelines:
        ici.execute("INSERT OR IGNORE INTO issue(pair, motif, ts) VALUES(?, 'interrompu', ?)",
                    (p, time.time()))
    if orphelines:
        ici.commit()
        print("papier_gd: %d position(s) perdue(s) au redemarrage, marquees interrompues"
              % len(orphelines), flush=True)
    vus = {r[0] for r in ici.execute("SELECT pair FROM decision")}
    cache, depenses, jusqu, ouverts, recotes = {}, deque(), 0.0, [], []
    print("papier_gd_direct: demarre · gel %s · %d pools deja juges · %d positions au plus"
          % (dt.datetime.fromtimestamp(GEL, dt.timezone.utc).strftime("%d/%m %H:%M UTC"), len(vus), MAX_OUVERTS),
          flush=True)
    while True:
        maintenant = time.time()
        # --- 1. LES POSITIONS OUVERTES D ABORD, toujours, avant tout travail lent. Une seule lecture
        #        de chaine pour toutes. C est ce qui garantit la cadence de 2 s sur les sorties.
        if ouverts:
            # Une panne reseau passagere ne doit PAS tuer le test : `avancer` sait deja quoi faire
            # d une lecture absente (elle garde la position). Le 16/09 a 21h10, une erreur DNS d une
            # seconde a fait sortir l exception de la boucle et arrete le test a 30 s au bout de
            # trois heures -- sur treize jours de collecte, c est la seule chose qui compte vraiment.
            try:
                prix = prix_multiples(ouverts)
            except Exception as exc:  # noqa: BLE001
                prix = {}
                print("papier_gd: prix illisibles (%s)" % str(exc)[:90], flush=True)
            restants = []
            for t in ouverts:
                age = maintenant - t["naissance"]
                p = prix.get(t["pair"])
                if p:
                    t["sommet"] = max(t["sommet"], p)
                    t["dernier"] = p
                    if REGLE == "large":
                        jalonner(t, p, age)
                # La cotation de SORTIE doit se prendre a l horizon qu on compare, pas a la fin du
                # suivi : en mode large la position est gardee 30 min pour pouvoir rejouer la regle
                # du moteur, mais la regle de production qu on veut comparer vend a 4 MINUTES. Sans
                # cette cotation-la, `net_reel` mesurerait une detention de 30 min qu on met en face
                # d un calcul a 4 min -- deux durees differentes, comparaison fausse.
                if REGLE == "large" and t.get("jetons") and "q4" not in t and age >= FIN_S:
                    try:
                        t["q4"] = coter(t["mint"], SOL_MINT, t["jetons"])
                    except Exception:  # noqa: BLE001
                        t["q4"] = None
                if REGLE == "large":
                    # on ne ferme qu a l horizon le plus lointain : la sortie se rejoue apres coup
                    motif = "suivi complet" if age >= SUIVI_MAX else None
                else:
                    t["declenche"], motif = avancer(t["p0"], t["declenche"], p, age)
                if motif:
                    net = clore(ici, t, p or t["dernier"], motif)
                    if net <= SEUIL_PAUSE:
                        jusqu = maintenant + PAUSE
                        print("papier_gd: perte %.0f %% -> pause de 30 min" % (100 * net), flush=True)
                else:
                    restants.append(t)
            ouverts = restants
        # les recotations dues : elles mesurent le prix de la lenteur, sans rien bloquer
        if recotes:
            restantes = []
            for rc in recotes:
                if rc["quand"] > maintenant:
                    restantes.append(rc)
                    continue
                try:
                    q = coter(SOL_MINT, rc["mint"], MISE_SOL * LAMPORTS)
                except Exception:  # noqa: BLE001
                    q = None
                if q:
                    ici.execute("UPDATE decision SET %s=? WHERE pair=?" % rc["col"], (q[0], rc["pair"]))
                    ici.commit()
            recotes = restantes
        while depenses and depenses[0][0] < maintenant - 86400:
            depenses.popleft()
        if sum(x for _, x in depenses) >= PLAFOND_JOUR:
            time.sleep(PAS_SUIVI)
            continue
        try:
            lot = candidats(vus, maintenant)
        except Exception as exc:  # noqa: BLE001
            print("papier_gd: base illisible (%s)" % str(exc)[:100], flush=True)
            time.sleep(10)
            continue
        for pair, mint, naissance, coffre in lot:
            vus.add(pair)
            t_dec = naissance + A
            # --- les deux filtres GRATUITS d abord : ils ne touchent pas la chaine ---
            # CHAQUE ecriture est validee tout de suite. Premiere version : les rejets « coffre » et
            # « tendance » n avaient pas de commit, et comme aucun ticket n etait pris, rien n etait
            # jamais valide -- la base paraissait vide et j ai cru que le test ne voyait aucun pool.
            if coffre >= COFFRE_MAX:
                ici.execute("INSERT OR IGNORE INTO decision(pair, mint, naissance, t_dec, pris, motif, acheteurs, coffre, tendance, age_entree, prix_entree) VALUES(?,?,?,?,0,'coffre',NULL,?,NULL,NULL,NULL)",
                            (pair, mint, naissance, t_dec, coffre))
                ici.commit()
                continue
            tend = tendance(t_dec)
            if REGLE != "large" and (tend is None or tend <= 0):
                ici.execute("INSERT OR IGNORE INTO decision(pair, mint, naissance, t_dec, pris, motif, acheteurs, coffre, tendance, age_entree, prix_entree) VALUES(?,?,?,?,0,'tendance',NULL,?,?,NULL,NULL)",
                            (pair, mint, naissance, t_dec, coffre, tend))
                ici.commit()
                continue
            if REGLE != "large" and maintenant < jusqu:
                ici.execute("INSERT OR IGNORE INTO decision(pair, mint, naissance, t_dec, pris, motif, acheteurs, coffre, tendance, age_entree, prix_entree) VALUES(?,?,?,?,0,'pause',NULL,?,?,NULL,NULL)",
                            (pair, mint, naissance, t_dec, coffre, tend))
                ici.commit()
                continue
            # Le moteur ne tient jamais plus de `max_open_positions` lignes (4) : le test doit avoir la
            # meme limite, sinon il mesure une strategie qu on ne pourrait pas jouer. On enregistre ces
            # refus pour savoir plus tard ce que le plafond coute.
            if len(ouverts) >= MAX_OUVERTS:
                ici.execute("INSERT OR IGNORE INTO decision(pair, mint, naissance, t_dec, pris, motif, acheteurs, coffre, tendance, age_entree, prix_entree) VALUES(?,?,?,?,0,'plafond',NULL,?,?,NULL,NULL)",
                            (pair, mint, naissance, t_dec, coffre, tend))
                ici.commit()
                continue
            # --- seulement maintenant on paie une lecture de la chaine ---
            try:
                n_ach, n_tx = acheteurs_avant(pair, mint, naissance, 0.0)
            except Exception as exc:  # noqa: BLE001
                print("papier_gd: acheteurs illisibles %s (%s)" % (pair[:8], str(exc)[:70]), flush=True)
                continue
            depenses.append((time.time(), max(10, n_tx // 10)))
            if REGLE != "large" and n_ach > FOULE_MAX:
                ici.execute("INSERT OR IGNORE INTO decision(pair, mint, naissance, t_dec, pris, motif, acheteurs, coffre, tendance, age_entree, prix_entree) VALUES(?,?,?,?,0,'foule',?,?,?,NULL,NULL)",
                            (pair, mint, naissance, t_dec, n_ach, coffre, tend))
                ici.commit()
                continue
            try:
                comptes = comptes_du_pool(pair, cache)
                age = time.time() - naissance
                p = prix_du_pool(comptes) if comptes else None
            except Exception as exc:  # noqa: BLE001
                print("papier_gd: pool illisible %s (%s)" % (pair[:8], str(exc)[:70]), flush=True)
                continue
            if not p or age > ENTREE_MAX:
                ici.execute("INSERT OR IGNORE INTO decision(pair, mint, naissance, t_dec, pris, motif, acheteurs, coffre, tendance, age_entree, prix_entree) VALUES(?,?,?,?,0,'trop tard',?,?,?,?,NULL)",
                            (pair, mint, naissance, t_dec, n_ach, coffre, tend, age))
                ici.commit()
                continue
            if MISE_SOL / p[1] > 0.15:
                ici.execute("INSERT OR IGNORE INTO decision(pair, mint, naissance, t_dec, pris, motif, acheteurs, coffre, tendance, age_entree, prix_entree) VALUES(?,?,?,?,0,'non executable',?,?,?,?,?)",
                            (pair, mint, naissance, t_dec, n_ach, coffre, tend, age, p[0]))
                ici.commit()
                continue
            ici.execute("INSERT OR IGNORE INTO decision(pair, mint, naissance, t_dec, pris, motif, acheteurs, coffre, tendance, age_entree, prix_entree) VALUES(?,?,?,?,1,'pris',?,?,?,?,?)",
                        (pair, mint, naissance, t_dec, n_ach, coffre, tend, age, p[0]))
            ici.commit()
            # ISO-PROD : on demande au routeur ce qu on recevrait vraiment pour notre mise. C est la
            # cotation que le moteur utiliserait ; elle contient glissement, impact et frais de route.
            q = coter(SOL_MINT, mint, MISE_SOL * LAMPORTS) if mint else None
            if q:
                ici.execute("UPDATE decision SET jetons_cotes=?, impact_entree=? WHERE pair=?",
                            (q[0], q[1], pair))
                ici.commit()
                # et ce qu on recevrait si la file du moteur nous faisait arriver 2, 5 ou 10 s plus tard
                for retard, col in ((2.0, "jetons_2s"), (5.0, "jetons_5s"), (10.0, "jetons_10s")):
                    recotes.append({"pair": pair, "mint": mint, "quand": time.time() + retard, "col": col})
            ouverts.append({"pair": pair, "naissance": naissance, "comptes": comptes, "p0": p[0],
                            "sommet": p[0], "dernier": p[0], "declenche": None, "jalons": {},
                            "mint": mint, "jetons": q[0] if q else None})
            rid = emettre(pair, mint, n_ach, coffre, tend, age, p[0])
            print("papier_gd: ENTREE %s · %d acheteurs · coffre %.1f SOL · tendance %+.4f · a %.0f s · %d ouverte(s)%s"
                  % (pair[:8], n_ach, coffre, tend, age, len(ouverts),
                     (" · decision #%d emise" % rid) if rid else ""), flush=True)
        time.sleep(PAS_SUIVI)


def rapport_large(ici):
    """Toutes les regles evaluees sur LES MEMES tickets, ceux collectes en mode large.

    C est le seul montage qui permet de les comparer : un test par regle verrait des pools
    differents, donc on comparerait des periodes de marche plutot que des regles.
    """
    lignes = []
    for t_dec, fin, n_ach, coffre, tendance, p0, jal, net_reel, net4 in ici.execute(
            "SELECT d.t_dec, d.naissance + 289, d.acheteurs, d.coffre, d.tendance, d.prix_entree,"
            " i.jalons, i.net_reel, i.net_reel_4min FROM decision d JOIN issue i ON i.pair = d.pair"
            " WHERE d.pris = 1 ORDER BY d.t_dec"):
        j = json.loads(jal) if jal else {}
        if not j:
            continue            # ticket interrompu par un redemarrage : sortie inconnue, on l ecarte
        lignes.append({"t": t_dec, "fin": fin, "n_ach": n_ach, "coffre": coffre, "tend": tendance,
                       "p0": p0, "j": j, "net_reel": net_reel, "net4": net4})
    if not lignes:
        n = ici.execute("SELECT COUNT(*) FROM decision WHERE pris=1").fetchone()[0]
        print("collecte large : %d tickets pris, aucun termine pour l instant" % n)
        return
    jours = max((lignes[-1]["t"] - lignes[0]["t"]) / 86400, 1e-9)
    print("collecte LARGE (coffre < %.0f SOL) · %d tickets termines sur %.2f jour(s)"
          % (COFFRE_MAX, len(lignes), jours))

    def pause(sel):
        pris, att, bl = [], [], 0.0
        for l in sel:
            att.sort(key=lambda z: z["fin"])
            while att and att[0]["fin"] <= l["t"]:
                f = att.pop(0)
                if f["net"] <= SEUIL_PAUSE:
                    bl = max(bl, f["fin"] + PAUSE)
            if l["t"] >= bl:
                pris.append(l)
            att.append(l)
        return pris

    def issue_de(l, sortie):
        """Le rendement NET selon la regle de sortie choisie, reconstruit depuis les jalons.

        C est ce qui permet de comparer nos regles A CELLES DE LA PRODUCTION sur les memes tickets :
        `tg` = tenir 240 s puis vendre (telegram_rapide, TENUE_S=240), `moteur` = x1,5 ou stop 0,7
        ou 1800 s (carnet solana). Le prix retenu apres un franchissement est toujours celui d au
        moins 2 s plus tard, jamais celui du declenchement.
        """
        j, p0 = l["j"], l["p0"]
        if not j or not p0:
            return None
        fin = j.get("h287")

        def franchi(cle, avant):
            """Le seuil, SEULEMENT s il a ete franchi avant l echeance de la regle.

            Sans cette borne on vend a un prix qui n existe qu APRES la fermeture de la position :
            un jeton qui touche +25 % a 314 s alors que la regle sort a 287 s comptait quand meme
            comme une prise de gain. C est du look-ahead, et ca donnait 100 % de gagnants sur les
            huit premiers tickets de la nuit du 17/09 -- impossible, et c est ce qui l a trahi.
            """
            s = j.get(cle)
            if not isinstance(s, dict) or s.get("age") is None or s["age"] > avant:
                return None
            return s

        # On ne vend JAMAIS au prix du declenchement : il faut le prix d au moins 2 s plus tard,
        # sinon on suppose une execution instantanee et on gonfle le resultat de 20 a 40 % (§3.96).
        # Si ce prix-la manque, on considere que la sortie n a pas eu lieu -- prudent, jamais flatteur.
        apres_de = lambda s: s.get("apres") if (s and "apres" in s) else None

        if sortie == "tg":                       # 4 minutes pile, la regle de production
            px = fin
        elif sortie == "tp25":                   # la notre : +25 % avant 287 s, sinon 287 s
            px = apres_de(franchi("s1.25", FIN_S)) or fin
        elif sortie == "tp25stop":
            # la notre PLUS un stop a 0,7 : aucune de nos regles n en a, et le carnet du moteur,
            # qui en a un, encaissait bien mieux sur les premiers tickets de la nuit du 17/09.
            # On prend celui des deux seuils qui arrive EN PREMIER, jamais le plus flatteur.
            haut, bas = franchi("s1.25", FIN_S), franchi("s0.7", FIN_S)
            ah = haut.get("age") if haut else None
            ab_ = bas.get("age") if bas else None
            if ah is not None and (ab_ is None or ah <= ab_):
                px = apres_de(haut) or fin
            elif ab_ is not None:
                px = apres_de(bas) or fin
            else:
                px = fin
        elif sortie == "moteur":                 # x1,5, stop 0,7, echeance 1800 s
            haut, bas = franchi("s1.5", 1800), franchi("s0.7", 1800)
            aa = haut.get("age") if haut else None
            ab = bas.get("age") if bas else None
            echeance = j.get("h1800") or j.get("h1500") or j.get("h1200") or fin
            if aa is not None and (ab is None or aa <= ab):
                px = apres_de(haut) or echeance
            elif ab is not None:
                px = apres_de(bas) or echeance
            else:
                px = echeance
        else:
            px = fin
        if not px:
            return None
        return min(px / p0 - 1, PLAFOND) - COUT

    G = lambda l: (l["n_ach"] or 0) <= FOULE_MAX
    D = lambda l: (l["tend"] or 0) > 0
    PROD = lambda l: (l["n_ach"] or 0) >= 75          # le plancher du carnet solana en service
    print("   %-34s %5s %11s %10s %11s %9s" % ("regle", "n", "par ticket", "total", "sans best", "gagnants"))
    for nom, f, p, sortie in (
            ("PROD moteur : >=75, x1,5/1800 s", PROD, False, "moteur"),
            ("PROD telegram : sortie 4 min", lambda l: True, False, "tg"),
            ("coffre seul + sortie 4 min", lambda l: True, False, "tg"),
            ("coffre seul + gain +25 %", lambda l: True, False, "tp25"),
            ("coffre + gain +25 % + STOP 0,7", lambda l: True, False, "tp25stop"),
            ("coffre + pause", lambda l: True, True, "tp25"),
            ("G  + foule <= 74", G, True, "tp25"),
            ("G  + foule + STOP 0,7", G, True, "tp25stop"),
            ("D  + tendance > 0", D, False, "tp25"),
            ("D+F  tendance + pause", D, True, "tp25"),
            ("G+D  les trois", lambda l: G(l) and D(l), True, "tp25"),
            ("G+D + STOP 0,7", lambda l: G(l) and D(l), True, "tp25stop")):
        for l in lignes:
            l["net"] = issue_de(l, sortie)
        sel = [l for l in lignes if f(l) and l["net"] is not None]
        pris = pause(sel) if p else sel
        if not pris:
            print("   %-34s aucun ticket" % nom)
            continue
        v = sorted((l["net"] for l in pris), reverse=True)
        moy = sum(v) / len(v)
        sans = (sum(v[1:]) / (len(v) - 1)) if len(v) > 1 else float("nan")
        print("   %-34s %5d %+10.2f %% %+9.0f E %+10.2f %% %8.0f %%" % (
            nom, len(v), 100 * moy, MISE_EUR * sum(v), 100 * sans,
            100 * sum(1 for x in v if x > 0) / len(v)))
    # On compare ce qui est comparable : la cotation REELLE prise a 4 min contre le calcul sur le
    # prix du pool a 4 min. Comparer la cotation de fin de suivi (30 min) au calcul a 4 min
    # melangerait deux durees de detention et donnerait un ecart qui ne veut rien dire.
    paires = [(l["net4"], issue_de(l, "tg")) for l in lignes if l["net4"] is not None]
    paires = [(a, b) for a, b in paires if b is not None]
    if paires:
        reel = sum(a for a, _ in paires) / len(paires)
        pool = sum(b for _, b in paires) / len(paires)
        print("\n   ISO-PROD, sur %d tickets ou les deux mesures existent, MEME horizon (4 min) :" % len(paires))
        print("      aller-retour reellement cote par le routeur : %+.2f %% par ticket" % (100 * reel))
        print("      calcul sur le prix du pool - 2,62 pts        : %+.2f %% par ticket" % (100 * pool))
        print("      -> le forfait se trompe de %+.2f point par ticket" % (100 * (reel - pool)))
    longs = [l["net_reel"] for l in lignes if l["net_reel"] is not None]
    if longs:
        print("   (pour information, la meme cotation prise en fin de suivi, 30 min : %+.2f %%)"
              % (100 * sum(longs) / len(longs)))
    print("\n   Tickets collectes sans filtre autre que le coffre : chaque regle est jugee sur")
    print("   exactement les memes pools, aux memes instants. Verdict a 300 tickets ou 21 jours.")
    print("   RESERVE sur les deux lignes PROD : on rejoue leur SORTIE, pas leur entree complete.")
    print("   Le carnet solana entre a T+1 min sur des criteres DexScreener (liquidite, capitalisation)")
    print("   qu on n enregistre pas, et telegram_rapide entre entre 55 et 180 s sur un signal Telegram")
    print("   qui ne se rejoue pas. Ces lignes disent donc ce que LEURS SORTIES valent sur NOS entrees,")
    print("   ce qui est deja la moitie de la question, mais pas la production a l identique.")


def rapport(ici):
    if REGLE == "large":
        rapport_large(ici)
        return
    rows = ici.execute("SELECT d.t_dec, i.net, i.motif FROM decision d JOIN issue i ON i.pair=d.pair"
                       " WHERE d.pris=1 ORDER BY d.t_dec").fetchall()
    n_vus = ici.execute("SELECT COUNT(*) FROM decision").fetchone()[0]
    motifs = dict(ici.execute("SELECT motif, COUNT(*) FROM decision GROUP BY motif").fetchall())
    print("pools juges %d · %s" % (n_vus, " · ".join("%s %d" % kv for kv in sorted(motifs.items()))))
    if not rows:
        print("aucun ticket termine")
        return
    v = [r[1] for r in rows]
    jours = max((rows[-1][0] - rows[0][0]) / 86400, 1e-9)
    s = sorted(v, reverse=True)
    m = len(v) // 2
    # Pas d euros par jour avant d avoir une vraie duree : sur quelques heures le chiffre n a
    # aucun sens et se lit pourtant comme une promesse.
    par_jour = ("%+.0f EUR/jour" % (MISE_EUR * sum(v) / jours)) if jours >= 0.5 else "EUR/jour : trop tot"
    print("tickets %d sur %.2f jour(s) · %+.2f %% par ticket · %+.0f EUR · %s"
          % (len(v), jours, 100 * sum(v) / len(v), MISE_EUR * sum(v), par_jour))
    print("  sans le meilleur %+.2f %% · gagnants %.0f %% · moities %+.2f %% / %+.2f %%"
          % (100 * sum(s[1:]) / max(len(s) - 1, 1), 100 * sum(1 for x in v if x > 0) / len(v),
             100 * sum(v[:m]) / max(m, 1), 100 * sum(v[m:]) / max(len(v) - m, 1)))
    print("  CRITERE : >= +4,5 %% par ticket, deux moities > 0, positif sans le meilleur, a 300 tickets ou 21 jours")


if __name__ == "__main__":
    main()
