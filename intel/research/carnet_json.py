"""Alimente la page de suivi locale : deux fichiers JSON dans `data/`, relus par Streamlit.

POURQUOI CE PROCESSUS. Mido, 19/09 : « au lieu de passer par Claude pourquoi pas la faire dans un
streamlit avec une adresse locale ? » -- et il a raison. Une page qui depend de ma session s arrete
avec elle ; celle-ci tourne toute seule, ne coute rien, et peut relire le carnet reel toutes les
vingt secondes au lieu du quart d heure.

LE CHEMIN DES DONNEES. `/app/db` est un volume Docker : l hote ne sait pas le lire. `/app/data`, lui,
est monte depuis `C:\\Users\\Osiris\\Documents\\Tangier\\data`. C est donc par la qu on passe : ce
processus, DANS le conteneur, ecrit deux fichiers que Streamlit lit DEHORS, sans docker exec.

DEUX RYTHMES, parce que les deux grandeurs ne bougent pas a la meme vitesse :
    carnet.json       la table entiere (`table_std2.py`, 17 s de calcul) toutes les 5 minutes.
                      ~25 tickets par heure sur 2 600 : la rafraichir plus vite ne montrerait rien.
    carnet_live.json  le carnet REEL toutes les 20 s -- achats, P&L du jour, et l etat du budget
                      de perte. C est ca qui bouge, et c est l argent de Mido.

UNE SEULE SOURCE. La table n est pas recalculee ici : on relance le script que Mido lit dans son
terminal, avec sa sortie JSON. Deux vues du meme chiffre finissent toujours par diverger, et il
faut alors deviner laquelle croire.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
import subprocess
import sys
import time

DATA = os.environ.get("CARNET_DIR", "/app/data")
INTEL = os.environ.get("INTEL_DB", "/app/db/intel.sqlite")
MISE_TABLE = os.environ.get("MISE", "25")
PAS_TABLE = int(os.environ.get("PAS_TABLE", "300"))
PAS_LIVE = int(os.environ.get("PAS_LIVE", "20"))
# Le plafond que le moteur applique : perte cumulee sur 24 h GLISSANTES, pas sur la journee
# calendaire (`modele_rapide.py`). C est ce qui a bloque 229 achats le 19/09 alors que la journee
# elle-meme etait positive -- la page doit donc montrer la fenetre glissante, pas le total du jour.
PERTE_MAX = float(os.environ.get("MAX_PERTE_JOUR_EUR", "150"))
TZ = dt.timezone(dt.timedelta(hours=2))
# Les deux bascules du 19/09, qui coupent le carnet reel en trois regimes qu il ne faut pas
# melanger : avant, on payait la caution et une priorite d achat cinq fois trop chere ; depuis
# 15h30, c est la foret aleatoire qui decide et la mise est a 10 EUR au lieu de 20.
BASCULE_ECO = dt.datetime(2026, 9, 19, 10, 53, tzinfo=TZ).timestamp()
BASCULE_FORET = dt.datetime(2026, 9, 19, 15, 30, tzinfo=TZ).timestamp()


def ecrire(nom, obj):
    """Ecriture atomique : Streamlit relit en boucle et ne doit jamais tomber sur un fichier a moitie."""
    tmp = os.path.join(DATA, nom + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, os.path.join(DATA, nom))


def cout_mesure():
    """LE COUT, calcule depuis le carnet REEL a chaque passage. Jamais cite de memoire.

    Le 19/09 j ai donne cinq chiffres differents a Mido dans la journee -- 4,25 / 4,69 / 2,98 /
    5,37 / 4,1 -- parce que je le ressortais de tete au lieu de le lire, chaque fois sur un
    perimetre un peu different. Sa reponse : « tu le dis cinq fois aujourd hui ».

    DEFINITION, UNE SEULE : sur les tickets presents des DEUX cotes, ce que le prix du jeton a fait
    (papier brut) moins ce que le portefeuille a encaisse, divise par les euros deployes. C est
    exactement l ecart qui empeche le papier et le reel de coincider, donc le seul cout qui compte.
    Pondere en euros et non moyenne de ratios : un cout qu on multipliera par des euros se mesure
    en euros (regle 20).

    Renvoie aussi la mesure DEPUIS LA BASCULE du 19/09 10h53 (caution recuperee + priorite d achat
    divisee par cinq) : c est elle qui dira si les economies tiennent, quand elle aura assez de
    tickets. Tant qu elle en a moins de MIN_TICKETS, on ne s en sert pas -- on se contente de dire
    combien il en manque.
    """
    MIN_TICKETS = 60
    BASCULE = dt.datetime(2026, 9, 19, 10, 53, tzinfo=TZ).timestamp()
    ci = sqlite3.connect("file:%s?mode=ro" % INTEL, uri=True, timeout=30)
    cp = sqlite3.connect("file:/app/db/papier_combo.sqlite?mode=ro", uri=True, timeout=30)
    try:
        pap = {p: float(b) for p, b in cp.execute(
            "SELECT pair, brut_240 FROM issue WHERE brut_240 IS NOT NULL")}
        lignes = []
        for p, t, g, m in ci.execute(
                "SELECT pair, ts_entree, gain_eur, mise_eur FROM mr_lignes"
                " WHERE mode='live' AND gain_eur IS NOT NULL AND ts_entree IS NOT NULL"):
            if p in pap:
                lignes.append((float(t), float(g), float(m or 20.0), pap[p]))
    finally:
        ci.close()
        cp.close()

    def pt(s):
        if not s:
            return None
        dep = sum(x[2] for x in s)
        brut = sum(x[2] * x[3] for x in s)
        reel = sum(x[1] for x in s)
        return round(100 * (brut - reel) / dep, 2) if dep else None

    apres = [x for x in lignes if x[0] >= BASCULE]
    return {
        "tout": pt(lignes), "n_tout": len(lignes),
        "avant": pt([x for x in lignes if x[0] < BASCULE]),
        "apres": pt(apres), "n_apres": len(apres),
        "min_tickets": MIN_TICKETS, "manque": max(0, MIN_TICKETS - len(apres)),
        "retenu": pt(apres) if len(apres) >= MIN_TICKETS else pt(lignes),
        "sur_quoi": ("les %d tickets depuis la bascule" % len(apres)) if len(apres) >= MIN_TICKETS
                    else ("les %d tickets du carnet reel (il en manque %d apres la bascule"
                          " pour mesurer l effet des economies)" % (len(lignes), max(0, MIN_TICKETS - len(apres)))),
    }


def table():
    """Relance `table_std2.py` avec sa sortie JSON, et recopie le texte pour l onglet brut."""
    # Nom distinct du « .tmp » d `ecrire`, sinon les deux se marchent dessus : le script ecrit son
    # JSON, `ecrire` ecrase le meme fichier puis le renomme, et le nettoyage ne trouve plus rien.
    # Le registre des couts d abord : il ajoute les tickets nouvellement clotures, decomposes au
    # centime, et regenere `cout_serie.json`. Append-only, donc relancer ne refait jamais l histoire.
    try:
        subprocess.run([sys.executable, "-m", "intel.research.cout_registre"], cwd="/app",
                       capture_output=True, text=True, timeout=600)
    except Exception as e:  # noqa: BLE001
        print("carnet_json: registre des couts en echec : %s" % str(e)[:200], flush=True)

    brut = os.path.join(DATA, "carnet.brut.json")
    c = cout_mesure()
    env = dict(os.environ, MISE=MISE_TABLE, JSON=brut)
    if c.get("retenu"):
        env["COUT_MESURE"] = "%.6f" % (c["retenu"] / 100.0)     # la table tourne sur le cout LU
    r = subprocess.run([sys.executable, "data/table_std2.py"], cwd="/app", env=env,
                       capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout)[-400:])
    with open(brut, encoding="utf-8") as f:
        d = json.load(f)
    d["texte"] = r.stdout
    d["cout_detail"] = c
    ecrire("carnet.json", d)
    os.remove(brut)
    return len(d.get("lignes") or [])


def live():
    """Le carnet REEL : ce que le moteur a fait, et si le budget de perte le bloque en ce moment."""
    c = sqlite3.connect("file:%s?mode=ro" % INTEL, uri=True, timeout=30)
    try:
        now = time.time()
        cols = [r[1] for r in c.execute("PRAGMA table_info(mr_lignes)")]
        if "gain_eur" not in cols:
            return None
        Q = "mode='live'"
        fenetre = c.execute(
            "SELECT COUNT(*), COALESCE(SUM(gain_eur),0) FROM mr_lignes WHERE %s AND ts_entree >= ?"
            % Q, (now - 86400,)).fetchone()
        jour0 = dt.datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        jour = c.execute(
            "SELECT COUNT(*), COALESCE(SUM(gain_eur),0) FROM mr_lignes WHERE %s AND ts_entree >= ?"
            % Q, (jour0,)).fetchone()
        statuts = dict(c.execute("SELECT statut, COUNT(*) FROM mr_lignes WHERE %s AND t_dec >= ?"
                                 " GROUP BY statut" % Q, (jour0,)))
        motifs = dict(c.execute("SELECT motif, COUNT(*) FROM mr_lignes WHERE %s AND t_dec >= ?"
                                " AND motif IS NOT NULL GROUP BY motif ORDER BY 2 DESC LIMIT 5" % Q,
                                (jour0,)))
        ouvertes = c.execute("SELECT COUNT(*) FROM mr_lignes WHERE %s AND statut='OUVERTE'" % Q).fetchone()[0]
        derniers = [
            {"t": t, "symbole": s, "mise": m, "gain": g, "statut": st, "risque": rq}
            for t, s, m, g, st, rq in c.execute(
                "SELECT t_dec, COALESCE(symbole, substr(mint,1,6)), mise_eur, gain_eur, statut, risque"
                " FROM mr_lignes WHERE %s AND tx_achat IS NOT NULL ORDER BY t_dec DESC LIMIT 40" % Q)]
        total = c.execute("SELECT COUNT(*), COALESCE(SUM(gain_eur),0) FROM mr_lignes"
                          " WHERE %s AND gain_eur IS NOT NULL" % Q).fetchone()
        # TOUS les tickets fermes, pas seulement les 40 derniers : une distribution se lit sur
        # l ensemble, et un histogramme sur 40 points ne montre que du hasard.
        cp = sqlite3.connect("file:/app/db/papier_combo.sqlite?mode=ro", uri=True, timeout=30)
        brut = {p: float(b) for p, b in cp.execute(
            "SELECT pair, brut_240 FROM issue WHERE brut_240 IS NOT NULL")}
        cp.close()
        # `brut_pct` sur les tickets PRIS aussi : c est la seule grandeur comparable avec les
        # tickets ecartes, qu on n a jamais achetes. Sans elle on ne peut pas repondre a « la foret
        # a-t-elle ecarte des mauvais ou des bons ? » -- il faut les mettre sur la meme echelle.
        gains = [{"t": int(t), "gain": round(float(g), 4), "mise": float(m or 20.0),
                  "brut_pct": round(100 * brut[p], 3) if p in brut else None}
                 for p, t, g, m in c.execute(
                     "SELECT pair, ts_entree, gain_eur, mise_eur FROM mr_lignes WHERE %s"
                     " AND gain_eur IS NOT NULL AND ts_entree IS NOT NULL ORDER BY ts_entree" % Q)]
        # LES TICKETS EVITES. On ne les a pas achetes, donc `gain_eur` est vide -- mais le carnet
        # PAPIER connait ce que leur prix a fait (`brut_240`). On peut donc dire ce qu ils auraient
        # rapporte, cout deduit. C est la seule facon de savoir si nos refus nous protegent ou nous
        # coutent : le 19/09 les tickets bloques par le budget etaient MEILLEURS (+2,91 %) que ceux
        # qu on a joues (-0,21 %). Mido : « on peut aussi suivre les tickets evites ? »
        evites = []
        try:
            pap = brut
            for p, t, st_, mo in c.execute(
                    "SELECT pair, t_dec, statut, motif FROM mr_lignes WHERE %s"
                    " AND tx_achat IS NULL AND t_dec IS NOT NULL ORDER BY t_dec" % Q):
                if p in pap:
                    evites.append({"t": int(t), "statut": st_, "motif": (mo or "")[:60],
                                   "brut_pct": round(100 * pap[p], 3)})
        except Exception:  # noqa: BLE001
            evites = []

        # courbe cumulee du reel, dans l ordre des sorties
        cum, courbe = 0.0, []
        for t, g in c.execute("SELECT ts_sortie, gain_eur FROM mr_lignes WHERE %s AND gain_eur IS NOT NULL"
                              " AND ts_sortie IS NOT NULL ORDER BY ts_sortie" % Q):
            cum += float(g)
            courbe.append([int(t), round(cum, 2)])
    finally:
        c.close()
    perte = float(fenetre[1] or 0.0)
    return {
        "genere": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "fenetre_24h": {"n": fenetre[0], "gain": round(perte, 2),
                        "plafond": -PERTE_MAX, "bloque": perte <= -PERTE_MAX,
                        "marge": round(perte + PERTE_MAX, 2)},
        "jour": {"n": jour[0], "gain": round(float(jour[1] or 0.0), 2)},
        "statuts": statuts, "motifs": motifs, "ouvertes": ouvertes,
        "total": {"n": total[0], "gain": round(float(total[1] or 0.0), 2)},
        "derniers": derniers, "courbe": courbe, "gains": gains, "evites": evites,
        # Les instants qui coupent l histoire du carnet reel en regimes comparables. Sans eux la
        # page melange des periodes qui n ont ni le meme modele ni la meme mise, et toute moyenne
        # devient un melange. Mido, 19/09 : « contrains-toi aux ordres depuis le passage a la foret,
        # ou mets un truc qui permet de choisir ».
        "regimes": [
            {"cle": "tout", "nom": "Tout le carnet réel", "depuis": None},
            {"cle": "economies", "nom": "Depuis les économies (19/09 10h53)", "depuis": BASCULE_ECO},
            {"cle": "foret", "nom": "Depuis la forêt + mise 10 € (19/09 15h30)", "depuis": BASCULE_FORET},
        ],
    }


def main() -> None:
    print("carnet_json: demarre · table %d s · live %d s · vers %s" % (PAS_TABLE, PAS_LIVE, DATA), flush=True)
    prochaine_table = 0.0
    while True:
        t = time.time()
        if t >= prochaine_table:
            try:
                n = table()
                print("carnet_json: table ecrite (%d lignes)" % n, flush=True)
            except Exception as e:  # noqa: BLE001
                print("carnet_json: TABLE EN ECHEC : %s" % str(e)[:300], flush=True)
                ecrire("carnet_erreur.json", {"quand": dt.datetime.now(TZ).isoformat(timespec="seconds"),
                                              "erreur": str(e)[:600]})
            prochaine_table = time.time() + PAS_TABLE
        try:
            d = live()
            if d:
                ecrire("carnet_live.json", d)
        except Exception as e:  # noqa: BLE001
            print("carnet_json: LIVE EN ECHEC : %s" % str(e)[:200], flush=True)
        time.sleep(max(1, PAS_LIVE - (time.time() - t)))


if __name__ == "__main__":
    main()
