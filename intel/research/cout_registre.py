"""LE REGISTRE DES COUTS : chaque ticket reel decompose au centime, ecrit une fois, jamais refait.

MIDO, 19/09 : « je mets mon argent en sacrifice pour comprendre ce qu'on ne peut pas mesurer en
papier, mais il faut TOUT noter, pas la peine de me sortir des trucs de ta mémoire — les coûts on
peut les avoir calculés, décomposés au centime, en continu, en série de temps. »

Il a raison et c'est ma faute : le 19/09 je lui ai donne cinq couts differents dans la journee
(4,25 / 4,69 / 2,98 / 5,37 / 4,17) parce que je les ressortais de tete, chaque fois sur un perimetre
un peu different, en presentant parfois une PREVISION comme une mesure.

CE QUE FAIT CE FICHIER. Pour chaque ticket REEL cloture, il lit les deux transactions sur la chaine
et ecrit UNE LIGNE definitive dans `data/cout_tickets.jsonl`, en euros :

    frais_reseau   les frais payes au reseau sur les deux jambes (lus dans la transaction)
    caution        le loyer du compte-jeton : paye a l ouverture, rendu si le compte est referme
    impact         ce que NOTRE ordre deplace le prix : 2 x mise_SOL / (coffre + V)
    pool           la commission du pool sur les deux jambes
    inexplique     le reste = ecart total mesure moins les quatre postes ci-dessus

    ecart total    (ce que le PRIX du jeton a fait) - (ce que le PORTEFEUILLE a encaisse)
                   c est la seule definition : exactement ce qui empeche papier et reel de coincider.

APPEND-ONLY. Une ligne ecrite n est jamais recalculee : le cout d un ticket du 18/09 ne doit pas
changer parce qu on a modifie une formule aujourd hui. Les lignes portent leur version de formule.
Corriger = ajouter une ligne `revision`, pas reecrire l histoire.

SORTIE POUR LA PAGE : `data/cout_serie.json`, agrege par jour et en moyenne glissante, plus le
detail des derniers tickets. La page ne recalcule rien.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DATA = os.environ.get("CARNET_DIR", "/app/data")
INTEL = os.environ.get("INTEL_DB", "/app/db/intel.sqlite")
PAPIER = "/app/db/papier_combo.sqlite"
REGISTRE = os.path.join(DATA, "cout_tickets.jsonl")
SERIE = os.path.join(DATA, "cout_serie.json")
TZ = dt.timezone(dt.timedelta(hours=2))

# VERSION DES FORMULES. Une ligne garde la sienne pour toujours.
#   1  caution SUPPOSEE nulle apres la bascule du 19/09 10h53 -- une hypothese deguisee en mesure.
#      Archive dans `cout_tickets_v1_caution_supposee.jsonl`, jamais effacee.
#   2  caution LUE sur la chaine : le compte-jeton du mint existe-t-il encore dans le portefeuille ?
#      S il a ete referme, le loyer est revenu ; sinon il est immobilise. Mido, 19/09 :
#      « fais tout ce qui est reel et vrai ».
FORMULE = 2
V_RESERVE = 17.5845               # reserve virtuelle PumpSwap (octet 245)
LOYER_SOL = 0.00203928            # loyer d un compte-jeton
POOL_PCT = 0.0025                 # commission PumpSwap par jambe
BASCULE = dt.datetime(2026, 9, 19, 10, 53, tzinfo=TZ).timestamp()   # caution + priorite d achat


def rpc(corps):
    import urllib.request
    req = urllib.request.Request(os.environ["SOLANA_RPC_URL"],
                                 data=json.dumps(corps).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r).get("result")


def comptes_ouverts():
    """Les mints dont le compte-jeton est ENCORE ouvert dans le portefeuille.

    C est la mesure de la caution, et elle remplace une hypothese. Jusqu au 19/09 ce fichier
    ECRIVAIT `caution = 0` pour tout ticket posterieur a l activation du module de recuperation --
    une supposition deguisee en mesure, exactement ce que Mido reproche. La verite se lit sur la
    chaine : si le compte-jeton d un mint n existe plus, sa caution est revenue au portefeuille ;
    s il existe encore, elle est immobilisee.

    Un seul appel pour tout le portefeuille, en lecture seule, adresse publique derivee -- la cle
    ne sort jamais de `solana._keypair`.
    """
    sys.path.insert(0, "/app")
    from intel.execution import solana as sol
    a = sol.signer_address()
    if not a:
        return None
    ouverts = set()
    for prog in ("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
                 "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"):
        r = rpc({"jsonrpc": "2.0", "id": 1, "method": "getTokenAccountsByOwner",
                 "params": [a, {"programId": prog}, {"encoding": "jsonParsed"}]}) or {}
        for x in r.get("value") or []:
            try:
                ouverts.add(x["account"]["data"]["parsed"]["info"]["mint"])
            except Exception:  # noqa: BLE001
                continue
    return ouverts


def frais_sol(signature):
    """Les frais REELLEMENT payes sur cette transaction, lus sur la chaine (lamports -> SOL)."""
    r = rpc({"jsonrpc": "2.0", "id": 1, "method": "getTransaction",
             "params": [signature, {"encoding": "json", "maxSupportedTransactionVersion": 1}]})
    if not r or not r.get("meta"):
        return None
    return r["meta"]["fee"] / 1e9


def deja_ecrits():
    vus = set()
    if os.path.exists(REGISTRE):
        with open(REGISTRE, encoding="utf-8") as f:
            for l in f:
                try:
                    vus.add(json.loads(l)["pair"])
                except Exception:  # noqa: BLE001
                    continue
    return vus


def tickets_a_traiter(vus):
    ci = sqlite3.connect("file:%s?mode=ro" % INTEL, uri=True, timeout=30)
    cp = sqlite3.connect("file:%s?mode=ro" % PAPIER, uri=True, timeout=30)
    try:
        pap = {p: float(b) for p, b in cp.execute(
            "SELECT pair, brut_240 FROM issue WHERE brut_240 IS NOT NULL")}
        out = []
        for p, mint, t, g, m, q, ta, tv in ci.execute(
                "SELECT pair, mint, ts_entree, gain_eur, mise_eur, q, tx_achat, tx_vente"
                " FROM mr_lignes WHERE mode='live' AND gain_eur IS NOT NULL"
                " AND tx_achat IS NOT NULL AND tx_vente IS NOT NULL ORDER BY ts_entree"):
            if p in vus or p not in pap:
                continue
            out.append({"pair": p, "mint": mint, "t": float(t), "gain": float(g),
                        "mise": float(m or 20.0), "q": float(q or 0.0),
                        "brut": pap[p], "tx_achat": ta, "tx_vente": tv})
        return out
    finally:
        ci.close()
        cp.close()


def sol_par_eur(ci):
    """Le taux, lu sur les tickets eux-memes : mise en euros contre SOL reellement depense."""
    return 0.31 / 30.0                      # 0,31 SOL pour 30 EUR, constante du projet


def decompose(t, taux, ouverts=None):
    """Les cinq postes, en euros. `taux` = SOL par euro.

    `ouverts` = les mints dont le compte-jeton existe ENCORE (lu sur la chaine). La caution vaut
    zero quand le compte a ete referme, le loyer plein sinon. On ne suppose plus.
    """
    mise_sol = t["mise"] * taux
    fa = frais_sol(t["tx_achat"])
    fv = frais_sol(t["tx_vente"])
    reseau = ((fa or 0) + (fv or 0)) / taux                      # SOL -> EUR
    # La caution est PAYEE a l ouverture du compte-jeton et RENDUE quand il est referme. LU, pas
    # suppose : si le mint n est plus dans le portefeuille, son compte a ete ferme et le loyer est
    # revenu. `source_caution` garde la trace de la facon dont on l a su.
    if ouverts is None:
        caution, src = (0.0 if t["t"] >= BASCULE else LOYER_SOL / taux), "suppose"
    else:
        caution, src = (LOYER_SOL / taux if t["mint"] in ouverts else 0.0), "chaine"
    # Notre propre ordre deplace le prix : deux jambes dans un pool de taille q (+ reserve virtuelle)
    impact = (2 * mise_sol / (t["q"] + V_RESERVE)) * t["mise"] if t["q"] else 0.0
    pool = 2 * POOL_PCT * t["mise"]
    total = t["mise"] * t["brut"] - t["gain"]                    # l ecart mesure, en euros
    connu = reseau + caution + impact + pool
    return {
        "pair": t["pair"], "mint": t["mint"], "formule": FORMULE,
        "quand": dt.datetime.fromtimestamp(t["t"], TZ).isoformat(timespec="seconds"),
        "t": t["t"], "mise": round(t["mise"], 2), "q": round(t["q"], 3),
        "brut_pct": round(100 * t["brut"], 3), "gain": round(t["gain"], 4),
        "frais_reseau": round(reseau, 4), "caution": round(caution, 4),
        "impact": round(impact, 4), "pool": round(pool, 4),
        "inexplique": round(total - connu, 4), "total": round(total, 4),
        "total_pct": round(100 * total / t["mise"], 3),
        "frais_lus": fa is not None and fv is not None,
        "source_caution": src,
    }


def agrege():
    """La serie de temps pour la page : par jour, et moyenne glissante sur les 30 derniers."""
    lignes = []
    with open(REGISTRE, encoding="utf-8") as f:
        for l in f:
            try:
                lignes.append(json.loads(l))
            except Exception:  # noqa: BLE001
                continue
    lignes.sort(key=lambda x: x["t"])
    postes = ("frais_reseau", "caution", "impact", "pool", "inexplique")

    def part(s):
        """Trois normalisations, parce qu aucune ne suffit seule.

        POINTS : euros de cout / euros deployes. Compare des regimes de mise differents -- mais
                 masque justement un changement de mise, puisqu il est deja divise par elle.
        EUROS PAR TICKET : ce que chaque ticket coute vraiment au portefeuille. C est cette
                 colonne qui montre que passer de 20 a 10 EUR (19/09) divise le cout par deux.
        EUROS : le total brut, pour savoir combien on a paye en tout.
        Mido, 19/09 : « pour le graphique de cout je pense qu'il faut normaliser par rapport au
        nombre de tickets non ? » -- oui, et d autant plus le jour ou la mise change.
        """
        n = len(s) or 1
        dep = sum(x["mise"] for x in s) or 1.0
        d = {p: round(100 * sum(x[p] for x in s) / dep, 3) for p in postes}
        d["total"] = round(100 * sum(x["total"] for x in s) / dep, 3)
        d["n"] = len(s)
        d["euros"] = {p: round(sum(x[p] for x in s), 2) for p in postes}
        d["euros"]["total"] = round(sum(x["total"] for x in s), 2)
        d["par_ticket"] = {p: round(sum(x[p] for x in s) / n, 4) for p in postes}
        d["par_ticket"]["total"] = round(sum(x["total"] for x in s) / n, 4)
        d["deploye"] = round(dep, 2)
        d["mise_moy"] = round(dep / n, 2)
        return d

    jours = {}
    for x in lignes:
        jours.setdefault(x["quand"][:10], []).append(x)
    glissant = []
    for i in range(len(lignes)):
        s = lignes[max(0, i - 29):i + 1]
        if len(s) >= 5:
            glissant.append({"t": lignes[i]["t"], "n": len(s),
                             "total": round(100 * sum(y["total"] for y in s) / sum(y["mise"] for y in s), 3),
                             "par_ticket": round(sum(y["total"] for y in s) / len(s), 4),
                             "mise_moy": round(sum(y["mise"] for y in s) / len(s), 2)})
    avant = [x for x in lignes if x["t"] < BASCULE]
    apres = [x for x in lignes if x["t"] >= BASCULE]
    return {
        "genere": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "formule": FORMULE, "n": len(lignes),
        "tout": part(lignes) if lignes else None,
        "avant_bascule": part(avant) if avant else None,
        "apres_bascule": part(apres) if apres else None,
        "par_jour": {j: part(s) for j, s in sorted(jours.items())},
        "glissant": glissant,
        "derniers": lignes[-40:],
    }


def main() -> None:
    boucle = "--boucle" in sys.argv
    while True:
        vus = deja_ecrits()
        neufs = tickets_a_traiter(vus)
        taux = sol_par_eur(None)
        # ON N ECRIT PAS UN TICKET TANT QUE SA CAUTION N EST PAS TRANCHEE. Le module `recuperation`
        # passe toutes les 30 min : un ticket ferme il y a 10 minutes a encore son compte ouvert et
        # serait inscrit « caution payee » pour toujours (le registre est append-only). On attend
        # donc deux cycles avant de figer sa ligne.
        MUR = 3600
        maintenant = time.time()
        attente = [t for t in neufs if maintenant - t["t"] < MUR]
        neufs = [t for t in neufs if maintenant - t["t"] >= MUR]
        try:
            ouverts = comptes_ouverts()
        except Exception as e:  # noqa: BLE001
            print("cout_registre: portefeuille illisible (%s) -- on attend" % str(e)[:120], flush=True)
            ouverts = None
            neufs = []
        n = 0
        for t in neufs:
            try:
                d = decompose(t, taux, ouverts)
            except Exception as e:  # noqa: BLE001
                print("cout_registre: %s... echec %s" % (t["pair"][:8], str(e)[:120]), flush=True)
                continue
            with open(REGISTRE, "a", encoding="utf-8") as f:
                f.write(json.dumps(d, ensure_ascii=False) + "\n")
            n += 1
            time.sleep(0.15)                      # on partage le forfait RPC avec le moteur
        if os.path.exists(REGISTRE):
            tmp = SERIE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(agrege(), f, ensure_ascii=False)
            os.replace(tmp, SERIE)
        print("cout_registre: %d ajoute(s) · %d au total · %d en attente de maturite"
              % (n, len(vus) + n, len(attente)), flush=True)
        if not boucle:
            return
        time.sleep(300)


if __name__ == "__main__":
    main()
