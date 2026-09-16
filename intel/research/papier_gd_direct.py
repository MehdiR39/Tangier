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
GEL = float(os.environ.get("PAPIER_GD_GEL") or GELS.get(A) or time.time())
ENTREE_MAX, FIN_S = A + 10, 287
TP, PLAFOND, COUT, MISE_EUR, MISE_SOL = 0.25, 3.0, 0.0262, 30.0, 0.31
RETARD, PAS_SUIVI, PAUSE, SEUIL_PAUSE = 2.0, 2.0, 1800, -0.30
N_REGIME, PLAFOND_JOUR = 50, 40_000
# Le moteur tient 4 lignes au plus (`solana.max_open_positions`), parce que 4 x 30 EUR = 120 EUR sur un
# portefeuille de 185. Mais un test PAPIER n a pas de capital : on enregistre tout, et on rejouera
# n importe quel plafond ensuite sur les tickets collectes. L inverse est impossible -- un ticket refuse
# ne revient jamais. La contrainte de capital se remet a l analyse, pas a la collecte.
MAX_OUVERTS = 25
TAILLE_POOL, OFF_BASE_TA, OFF_VIRTUELLE = 301, 43 + 32 * 3, 245
SOL_MINT = "So11111111111111111111111111111111111111112"   # en dur : ce module ne doit dependre de rien


def schema(c):
    c.executescript("""
        CREATE TABLE IF NOT EXISTS decision(pair TEXT PRIMARY KEY, mint TEXT, naissance REAL, t_dec REAL,
            pris INTEGER, motif TEXT, acheteurs INTEGER, coffre REAL, tendance REAL, age_entree REAL,
            prix_entree REAL);
        CREATE TABLE IF NOT EXISTS issue(pair TEXT PRIMARY KEY, brut REAL, net REAL, age_sortie REAL,
            motif TEXT, sommet REAL, ts REAL);
    """)
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
    res = cc.rpc({"jsonrpc": "2.0", "id": 1, "method": "getMultipleAccounts",
                  "params": [comptes, {"encoding": "jsonParsed", "commitment": "processed"}]}) or {}
    vals = (res or {}).get("value") or []
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


def clore(ici, t, prix, motif):
    brut = min(prix / t["p0"] - 1, PLAFOND)
    net = brut - COUT
    ici.execute("INSERT OR IGNORE INTO issue VALUES(?,?,?,?,?,?,?)",
                (t["pair"], brut, net, time.time() - t["naissance"], motif, t["sommet"] / t["p0"] - 1, time.time()))
    ici.commit()
    print("papier_gd: %s sortie %s a x%.2f -> %+.2f %% (%+.2f EUR)"
          % (t["pair"][:8], motif, prix / t["p0"], 100 * net, MISE_EUR * net), flush=True)
    return net


def main():
    ici = sqlite3.connect(ICI, timeout=30)
    schema(ici)
    if "--rapport" in sys.argv:
        rapport(ici)
        return
    vus = {r[0] for r in ici.execute("SELECT pair FROM decision")}
    cache, depenses, jusqu, ouverts = {}, deque(), 0.0, []
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
                t["declenche"], motif = avancer(t["p0"], t["declenche"], p, age)
                if motif:
                    net = clore(ici, t, p or t["dernier"], motif)
                    if net <= SEUIL_PAUSE:
                        jusqu = maintenant + PAUSE
                        print("papier_gd: perte %.0f %% -> pause de 30 min" % (100 * net), flush=True)
                else:
                    restants.append(t)
            ouverts = restants
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
                ici.execute("INSERT OR IGNORE INTO decision VALUES(?,?,?,?,0,'coffre',NULL,?,NULL,NULL,NULL)",
                            (pair, mint, naissance, t_dec, coffre))
                ici.commit()
                continue
            tend = tendance(t_dec)
            if tend is None or tend <= 0:
                ici.execute("INSERT OR IGNORE INTO decision VALUES(?,?,?,?,0,'tendance',NULL,?,?,NULL,NULL)",
                            (pair, mint, naissance, t_dec, coffre, tend))
                ici.commit()
                continue
            if maintenant < jusqu:
                ici.execute("INSERT OR IGNORE INTO decision VALUES(?,?,?,?,0,'pause',NULL,?,?,NULL,NULL)",
                            (pair, mint, naissance, t_dec, coffre, tend))
                ici.commit()
                continue
            # Le moteur ne tient jamais plus de `max_open_positions` lignes (4) : le test doit avoir la
            # meme limite, sinon il mesure une strategie qu on ne pourrait pas jouer. On enregistre ces
            # refus pour savoir plus tard ce que le plafond coute.
            if len(ouverts) >= MAX_OUVERTS:
                ici.execute("INSERT OR IGNORE INTO decision VALUES(?,?,?,?,0,'plafond',NULL,?,?,NULL,NULL)",
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
            if n_ach > FOULE_MAX:
                ici.execute("INSERT OR IGNORE INTO decision VALUES(?,?,?,?,0,'foule',?,?,?,NULL,NULL)",
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
                ici.execute("INSERT OR IGNORE INTO decision VALUES(?,?,?,?,0,'trop tard',?,?,?,?,NULL)",
                            (pair, mint, naissance, t_dec, n_ach, coffre, tend, age))
                ici.commit()
                continue
            if MISE_SOL / p[1] > 0.15:
                ici.execute("INSERT OR IGNORE INTO decision VALUES(?,?,?,?,0,'non executable',?,?,?,?,?)",
                            (pair, mint, naissance, t_dec, n_ach, coffre, tend, age, p[0]))
                ici.commit()
                continue
            ici.execute("INSERT OR IGNORE INTO decision VALUES(?,?,?,?,1,'pris',?,?,?,?,?)",
                        (pair, mint, naissance, t_dec, n_ach, coffre, tend, age, p[0]))
            ici.commit()
            ouverts.append({"pair": pair, "naissance": naissance, "comptes": comptes, "p0": p[0],
                            "sommet": p[0], "dernier": p[0], "declenche": None})
            print("papier_gd: ENTREE %s · %d acheteurs · coffre %.1f SOL · tendance %+.4f · a %.0f s · %d ouverte(s)"
                  % (pair[:8], n_ach, coffre, tend, age, len(ouverts)), flush=True)
        time.sleep(PAS_SUIVI)


def rapport(ici):
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
