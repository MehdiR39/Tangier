"""LA TRAJECTOIRE DU STOCK : qui tient encore de quoi vider le pool, et qui a deja distribue.

L HYPOTHESE, DE MIDO. « Une partie des effondrements vient de groupes entres tres tot, disposant
encore d un stock enorme par rapport aux acheteurs presents. Ce stock et sa distribution sont
potentiellement observables AVANT l effondrement. Le signal d achat serait une transition : les
premiers detenteurs ont largement distribue, des acheteurs exterieurs continuent d arriver, et
leurs achats absorbent les ventes restantes. »

POURQUOI C EST DIFFERENT DE TOUT CE QU ON A TESTE. Toutes les variables du projet sont des mesures
de PRIX, et elles disent toutes la meme chose : ce qui predit la chute predit aussi la montee (« le
modele mesure la VIE, pas le danger »). Ici on ne mesure pas le prix, on mesure un ETAT -- combien
de munitions restent au-dessus du marche.

ET ÇA EXPLIQUE UN ECHEC QU ON N AVAIT PAS SU EXPLIQUER. L expert detenteurs (§3.110) regarde `sac1`
et `n_sacs5` a UN SEUL INSTANT, 45 s, et il fait -169 EUR sur 269 tickets. L objection de Mido le
demolit exactement : deux jetons peuvent avoir la MEME concentration alors que dans l un le groupe
initial a deja vendu et dans l autre il tient encore de quoi vider le pool. **Une photo ne distingue
pas les deux ; il faut le film.**

CE QU ON MESURE, ET POURQUOI C EST GRATUIT. `getTokenLargestAccounts` rend les vingt plus gros
detenteurs et leurs soldes en **82 ms** (mesure du 17/09). On l appelle a QUATRE ages -- 15, 25, 35
et 45 s -- au lieu d une seule fois. Quatre appels de 82 ms dans une fenetre de 45 s ou le moteur
lit deja le prix chaque seconde : le cout est negligeable.

De ces quatre photos se deduit la trajectoire :
    le plus gros detenteur a-t-il VENDU entre 15 et 45 s, ou tient-il toujours ?
    le top-5 s est-il DILUE (des acheteurs exterieurs entrent) ou reste-t-il fige ?
    combien de fois le stock restant pourrait-il VIDER le pool ?

CE QUE ÇA NE DONNERA PAS, et il faut le savoir avant de mesurer : le LIEN entre portefeuilles. Si
le gros detenteur transfere a trois complices au lieu de vendre, la concentration baisse et on
croira a une distribution alors que le stock est intact. **Ce biais va dans le mauvais sens : il
fait paraitre bons des cas qui ne le sont pas.** Le reconstruire demanderait les transactions du
pool -- `getSignaturesForAddress` bloque plusieurs minutes sur un jeton actif, et 98 % des sorties
passent par un routeur -- donc c est hors de portee dans une fenetre de 45 s.

IL N ECRIT QUE DANS SA PROPRE BASE et lit le moteur en lecture seule. S il tombe, il tombe seul.
Aucun collecteur en marche, aucun des gels, n en depend.
"""
from __future__ import annotations

import base64
import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import base58  # noqa: E402
import copie_collecte as cc  # noqa: E402

BASE_MOTEUR = os.environ.get("INTEL_DB", "/app/db/intel.sqlite")
BASE_ICI = os.environ.get("STOCK_DB", "/app/db/papier_stock.sqlite")
AGES = (15, 25, 35, 45)        # les quatre photos ; la decision se prend a 45 s
TOL = 6                        # tolerance d age : on ne force jamais une lecture trop loin
PAUSE = 2.0                    # la boucle repasse souvent : les fenetres sont courtes
MAX_PAR_TOUR = 12              # plafond : un tour ne doit jamais monopoliser le RPC
BUDGET = 6.0                   # ET un plafond en TEMPS : une photo lente ne doit pas en faire
                               # rater trois autres. Mesure : 270 ms en median, 2,8 s au pire.


def schema(c: sqlite3.Connection) -> None:
    # Une ligne par (jeton, age) : le format brut. Les variables derivees -- « a-t-il vendu ? »,
    # « de quoi vider le pool combien de fois ? » -- se calculent a l ANALYSE, sur les resultats
    # connus a l instant de la decision. Cette separation est ce qui les empeche de fuir.
    c.executescript("""
        CREATE TABLE IF NOT EXISTS photo(
            pair TEXT NOT NULL, mint TEXT, age INTEGER NOT NULL, t REAL, naissance REAL,
            offre REAL, coffre REAL,
            s1 REAL, s2 REAL, s3 REAL, s5 REAL, s10 REAL, s20 REAL,
            hors_pool REAL, s1_hp REAL, s2_hp REAL, s5_hp REAL, s10_hp REAL,
            w1 TEXT, w1_est_coffre INTEGER, coffre_vu INTEGER, wallets TEXT,
            n_comptes INTEGER, erreur TEXT,
            PRIMARY KEY (pair, age));
        CREATE INDEX IF NOT EXISTS i_photo_mint ON photo(mint);
        CREATE TABLE IF NOT EXISTS meta(cle TEXT PRIMARY KEY, valeur TEXT);
    """)
    c.commit()


def photo(mint: str, pool: str) -> dict:
    """Les vingt plus gros detenteurs, en PORTEFEUILLES, coffre du pool exclu.

    DEUX PIEGES, tous deux mesures le 18/09, tous deux corriges ici.

    1. `getTokenLargestAccounts` rend des COMPTES-JETONS, pas des portefeuilles. Un portefeuille a
       un compte-jeton DIFFERENT par jeton : garder l adresse technique interdit de relier un meme
       acteur d un lancement au suivant, qui est precisement ce que l hypothese demande ensuite.
       `getMultipleAccounts` donne le proprietaire (octets 32-64 d un compte SPL) en un seul appel.

    2. Le plus gros detenteur est TANTOT le coffre du pool TANTOT un vrai portefeuille -- sur six
       pools : 54,8 % et 50,1 % etaient le coffre, 79,3 % et 79,4 % etaient des portefeuilles. Ce
       sont les deux situations les plus OPPOSEES qui soient : dans la premiere l offre est dans le
       pool et personne ne peut la deverser, dans la seconde un seul acteur tient de quoi vider le
       pool plusieurs fois. Les confondre donnerait le meme chiffre aux deux. C est le piege qui
       avait rendu `sac_wallet` inutilisable (654 jetons, 654 portefeuilles distincts : c etait le
       coffre, unique par construction). Le coffre se reconnait sans appel supplementaire : c est
       le compte dont le proprietaire est le POOL lui-meme, et `pair_id` est l adresse du pool.

    L offre se lit au meme instant, jamais en theorie : sur un jeton qui vient de naitre les deux
    n ont rien a voir.
    """
    r = cc.rpc({"jsonrpc": "2.0", "id": 1, "method": "getTokenLargestAccounts", "params": [mint]})
    vals = (r or {}).get("value") or []
    if not vals:
        return {"erreur": "aucun compte"}
    sup = cc.rpc({"jsonrpc": "2.0", "id": 1, "method": "getTokenSupply", "params": [mint]})
    total = float(((sup or {}).get("value") or {}).get("uiAmount") or 0)
    if total <= 0:
        return {"erreur": "offre nulle"}

    comptes = [str(v["address"]) for v in vals]
    montants = [float(v["uiAmount"] or 0) for v in vals]
    mc = cc.rpc({"jsonrpc": "2.0", "id": 1, "method": "getMultipleAccounts",
                 "params": [comptes, {"encoding": "base64"}]})
    infos = ((mc or {}).get("value") or [None] * len(comptes))
    prop = []
    for info in infos:
        try:
            d = base64.b64decode(info["data"][0])
            prop.append(base58.b58encode(d[32:64]).decode())
        except Exception:  # noqa: BLE001
            prop.append(None)          # illisible : on ne devine pas, on laisse vide

    # le coffre du pool, retire du classement ; s il n est pas identifie on le dit, on ne suppose pas
    garde = [(p_, m) for p_, m in zip(prop, montants) if p_ != pool]
    vu = sum(1 for p_ in prop if p_ == pool)
    hp = sorted((m for _, m in garde), reverse=True)
    cum = lambda k: sum(sorted(montants, reverse=True)[:k]) / total
    cum_hp = lambda k: (sum(hp[:k]) / total) if hp else None

    return {"offre": total, "n_comptes": len(vals), "coffre_vu": vu,
            "w1": prop[0], "w1_est_coffre": int(prop[0] == pool),
            "wallets": ",".join(x or "?" for x, _ in zip(prop, montants)),
            "s1": cum(1), "s2": cum(2), "s3": cum(3), "s5": cum(5), "s10": cum(10), "s20": cum(20),
            "hors_pool": sum(hp) / total,
            "s1_hp": cum_hp(1), "s2_hp": cum_hp(2), "s5_hp": cum_hp(5), "s10_hp": cum_hp(10)}


def tour(ici: sqlite3.Connection, moteur: sqlite3.Connection) -> int:
    """Pour chaque pool encore jeune, prend la photo de l age atteint qui manque."""
    now = time.time()
    rows = moteur.execute(
        "SELECT pair_id, mint, MIN(ts - age_s) AS naissance, MAX(age_s) AS age, MAX(reserve_sol)"
        " FROM solana_prix_chaine WHERE ts > ? GROUP BY pair_id", (now - 600,)).fetchall()
    faites = {(p, a) for p, a in ici.execute("SELECT pair, age FROM photo")}

    # LE PLUS URGENT D ABORD. L age n est connu qu a la granularite du moteur -- `prix_chaine`
    # ecrit toutes les 10 s -- donc une fenetre peut se fermer pendant qu on photographie ailleurs.
    # On classe par temps restant croissant : ce qui va expirer passe avant ce qui peut attendre.
    # `naissance` est ecrit dans la ligne, pour que l analyse recalcule l age REEL et non le vise.
    a_faire = []
    for pair, mint, naissance, age_max, coffre in rows:
        if not mint or age_max is None:
            continue
        for a in AGES:
            if (pair, a) in faites:
                continue
            reel = now - naissance
            # la photo ne vaut que si l age VISE est atteint sans etre depasse de trop : une photo
            # a 60 s pour l age 15 ne dit rien de ce qu on cherche
            if not (a <= reel <= a + TOL):
                continue
            a_faire.append((a + TOL - reel, pair, mint, naissance, a, coffre))
    a_faire.sort(key=lambda x: x[0])

    n, t0 = 0, time.time()
    for _, pair, mint, naissance, a, coffre in a_faire:
            if n >= MAX_PAR_TOUR or time.time() - t0 > BUDGET:
                break
            try:
                d = photo(mint, pair)          # `pair` EST l adresse du pool : le coffre s en deduit
            except Exception as exc:  # noqa: BLE001
                d = {"erreur": str(exc)[:120]}
            ici.execute(
                "INSERT OR IGNORE INTO photo(pair, mint, age, t, naissance, offre, coffre, s1, s2,"
                " s3, s5,"
                " s10, s20, hors_pool, s1_hp, s2_hp, s5_hp, s10_hp, w1, w1_est_coffre, coffre_vu,"
                " wallets, n_comptes, erreur)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (pair, mint, a, now, naissance, d.get("offre"), coffre, d.get("s1"), d.get("s2"), d.get("s3"),
                 d.get("s5"), d.get("s10"), d.get("s20"), d.get("hors_pool"), d.get("s1_hp"),
                 d.get("s2_hp"), d.get("s5_hp"), d.get("s10_hp"), d.get("w1"),
                 d.get("w1_est_coffre"), d.get("coffre_vu"), d.get("wallets"), d.get("n_comptes"),
                 d.get("erreur")))
            faites.add((pair, a))
            n += 1
    ici.commit()
    return n


def main() -> None:
    ici = sqlite3.connect(BASE_ICI, timeout=30)
    schema(ici)
    moteur = sqlite3.connect("file:%s?mode=ro" % BASE_MOTEUR, uri=True, timeout=30)
    print("stock_collecte: demarre · ages %s · base %s" % (list(AGES), BASE_ICI), flush=True)
    dernier = 0.0
    while True:
        t0 = time.time()
        try:
            tour(ici, moteur)
            if t0 - dernier >= 300:
                dernier = t0
                tot, comp = ici.execute(
                    "SELECT COUNT(*), (SELECT COUNT(*) FROM (SELECT pair FROM photo"
                    "  WHERE erreur IS NULL GROUP BY pair HAVING COUNT(*) = ?))",
                    (len(AGES),)).fetchone()
                print("stock_collecte: %d photos · %d jetons COMPLETS" % (tot, comp or 0), flush=True)
        except Exception as exc:  # noqa: BLE001
            print("stock_collecte: tour rate (%s)" % str(exc)[:160], flush=True)
        time.sleep(max(0.0, PAUSE - (time.time() - t0)))


if __name__ == "__main__":
    main()
