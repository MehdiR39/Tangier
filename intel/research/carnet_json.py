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
# LA BASCULE QUI COMPTE AUJOURD HUI : `BANDE + PAUSE`, en reel depuis le 21/09 09h56. Mido,
# 23/09 : « la page carnet reel est tres bruitee, il faut la mettre a partir du passage en prod
# du nouveau modele ». Les 650 tickets anterieurs viennent d AUTRES regles -- dont
# `FORET REENTRAINEE 6h`, qui a perdu 45,75 EUR en une heure -- et les melanger a la methode en
# service rend toute moyenne illisible. C est la meme date que `cumul_depuis` dans la config et
# que le compteur Telegram : les trois doivent designer le meme instant, sinon la page, le
# telephone et le journal racontent trois histoires.
BASCULE_BANDE = dt.datetime(2026, 9, 21, 9, 56, tzinfo=TZ).timestamp()
# LE PASSAGE AU MODELE FRAIS, 26/09 12h38'30. La strategie ne change PAS (toujours `bande + pause`)
# -- c est le modele dessous qui change, et avec lui la bande, recalibree sur les memes quantiles.
# Cette date ne coupe donc PAS le carnet reel ; elle sert au bras temoin (`bascule_verdict.py`).
BASCULE_MODELE = 1790419110.0
COMBO = os.environ.get("COMBO_DB", "/app/db/papier_combo.sqlite")
CHALLENGER = os.environ.get("CHALLENGER_DB", "/app/db/papier_challenger.sqlite")
V_RESERVE, FIXE_COUT = 17.5845, 0.03524
BANDE_ANCIENNE = (0.20, 0.35)
BANDE_NOUVELLE = (0.17763490200673798, 0.3920447192432126)


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


def modele_en_prod():
    """QUEL MODELE TRADE L ARGENT, EN CE MOMENT -- lu dans le fichier, jamais de memoire.

    MIDO, 20/09 : « FORET REENTRAINEE 6h, ce nom on l a pas dans l app... ». Il l a : c est la
    ligne du carnet PAPIER, 358 tickets. Ce qui manquait, c est que rien ne disait laquelle des
    34 lignes correspond au modele qui achete reellement. On regarde donc 34 courbes sans savoir
    laquelle est en jeu.

    On lit le chemin dans la config qui TOURNE, puis l en-tete du fichier lui-meme : sa recette,
    son seuil, et la date de son dernier reentrainement. Si ce dernier vieillit, c est que
    `prod_reentraine` est mort -- le moteur ne s arrete pas pour autant, il vieillit en silence,
    et la page doit pouvoir le montrer.
    """
    import yaml
    out = {}
    try:
        with open("/app/config/intel.yaml", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        mr = (cfg.get("modele_rapide") or {})
        chemin = mr.get("modele")
        out = {"fichier": os.path.basename(chemin or ""), "chemin": chemin,
               "seuil_config": mr.get("seuil_risque"), "mode": mr.get("mode"),
               "actif": bool(mr.get("enabled"))}
        with open(chemin, encoding="utf-8") as f:
            m = json.load(f)
        out.update({"recette": m.get("recette"), "seuil": m.get("seuil_p80"),
                    "reentraine_le": m.get("reentraine_le"),
                    "entraine_sur": m.get("entraine_sur"),
                    "n_variables": len(m.get("feature_names") or [])})
        # le nom de la LIGNE de la page qui porte la meme recette, pour pouvoir la marquer
        if "foret_marche" in (m.get("recette") or ""):
            out["ligne"] = "FORET REENTRAINEE 6h"
    except Exception as e:  # noqa: BLE001
        out["erreur"] = str(e)[:150]
    return out


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
    # L ARBITRE : chaque candidate contre le MOTEUR, sur les memes tickets et en euros reels. C est
    # la seule mesure qui puisse justifier de changer la production -- tout le reste compare a un
    # temoin papier. Lecture seule, quelques secondes.
    try:
        subprocess.run([sys.executable, "-m", "intel.research.arbitre_prod"], cwd="/app",
                       capture_output=True, text=True, timeout=300)
    except Exception as e:  # noqa: BLE001
        print("carnet_json: arbitre en echec : %s" % str(e)[:200], flush=True)

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
    d["prod"] = modele_en_prod()
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
            # LA STRATEGIE EN SERVICE, depuis le 21/09 : `bande + pause`. Elle n a PAS change le
            # 26/09 -- seul le modele dessous a ete remplace, et la bande recalibree sur les memes
            # quantiles. La periode ne se coupe donc pas la, comme le compteur Telegram ne se coupe
            # pas : ce qui doit rester continu, c est la strategie. (Mido, 26/09 : « on a pas change
            # de strat, on change le modele ».) Le choix ci-dessous isole quand meme le nouveau
            # modele, pour qui veut voir SES tickets seuls.
            # `defaut: true` — LA PERIODE QUI S OUVRE EN PREMIER, et elle est designee ICI, jamais
            # deduite de l ordre de la liste. La page prenait la DERNIERE option par defaut : en
            # ajoutant « depuis le modele frais » a la fin le 26/09, j ai fait disparaitre tout le
            # suivi de Mido sans le vouloir -- il ne voyait plus que 4 tickets. Or la STRATEGIE n a
            # pas change, seul le modele : c est `bande + pause` depuis le 21/09 qui doit s afficher.
            {"cle": "bande", "nom": "La stratégie en service : bande + pause (21/09 09h56)",
             "depuis": BASCULE_BANDE, "defaut": True},
            {"cle": "modele_frais", "nom": "Depuis le modèle frais seul (26/09 12h38)",
             "depuis": BASCULE_MODELE},
        ],
    }


def reel() -> dict:
    """L ARGENT REEL, STRATEGIE PAR STRATEGIE — la seule source de la page « Argent réel ».

    Mido, 27/09 : « l app est trop bordelique, on voit des chiffres on sait pas quelle strat ».
    Il avait raison, et c etait pire que du desordre : `live()` ne lit que `mr_lignes`, donc le
    suiveur G+D (`gd_lignes`, en reel depuis le 25/09) n apparaissait NULLE PART, et tous les
    chiffres « reels » etaient ceux de BANDE + PAUSE sans le dire.

    Chaque strategie porte son nom, sa table, et l instant ou ELLE a commence : BANDE + PAUSE depuis
    le 21/09 09h56 (les tickets de `mr_lignes` d avant sont d AUTRES strategies, mortes). Tout est
    compte par JOUR CALENDAIRE de Paris, jamais en 24 h glissantes (consigne du 20/09).
    """
    STRATS = [("BANDE + PAUSE", "mr_lignes", BASCULE_BANDE),
              ("G+D", "gd_lignes", 0.0)]
    c = sqlite3.connect("file:%s?mode=ro" % INTEL, uri=True, timeout=30)
    out = {"genere": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
           "strategies": []}
    jour0 = dt.datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    try:
        for nom, table, depuis in STRATS:
            try:
                lignes = c.execute(
                    "SELECT ts_entree, ts_sortie, gain_eur, mise_eur, COALESCE(symbole, substr(mint,1,6)),"
                    " statut FROM %s WHERE mode='live' AND tx_achat IS NOT NULL AND ts_entree >= ?"
                    " ORDER BY ts_entree" % table, (depuis,)).fetchall()
                refus = dict(c.execute(
                    "SELECT statut, COUNT(*) FROM %s WHERE mode='live' AND tx_achat IS NULL"
                    " AND t_dec >= ? GROUP BY statut" % table, (jour0,)))
            except sqlite3.Error as e:
                out["strategies"].append({"nom": nom, "erreur": str(e)[:160]})
                continue
            fermes = [x for x in lignes if x[2] is not None]
            par_jour: dict[str, list] = {}
            for te, ts, g, m, s, stt in fermes:
                j = dt.datetime.fromtimestamp(float(ts or te), TZ).strftime("%Y-%m-%d")
                par_jour.setdefault(j, []).append(float(g))
            cum, courbe = 0.0, []
            for te, ts, g, m, s, stt in sorted(fermes, key=lambda x: x[1] or x[0]):
                cum += float(g)
                courbe.append([int(ts or te), round(cum, 2)])
            auj = dt.datetime.now(TZ).strftime("%Y-%m-%d")
            gj = par_jour.get(auj, [])
            out["strategies"].append({
                "nom": nom,
                "depuis": int(lignes[0][0]) if lignes else None,
                "mise": round(float(lignes[-1][3] or 0), 2) if lignes else None,
                "aujourdhui": {"n": len(gj), "gain": round(sum(gj), 2)},
                "total": {"n": len(fermes), "gain": round(sum(float(x[2]) for x in fermes), 2),
                          "gagnants": sum(1 for x in fermes if float(x[2]) > 0)},
                "ouvertes": sum(1 for x in lignes if x[5] == "OUVERTE"),
                "refus_aujourdhui": refus,
                "jours": [{"jour": j, "n": len(v), "gain": round(sum(v), 2)}
                          for j, v in sorted(par_jour.items())],
                "courbe": courbe,
                "derniers": [{"t": int(te), "jeton": s, "mise": m, "gain": g, "statut": stt}
                             for te, ts, g, m, s, stt in lignes[-15:]][::-1],
            })
    finally:
        c.close()
    return out


def _cout_pool(q):
    return FIXE_COUT + 2.0 * (25.0 * 0.31 / 30.0) / ((q or 0) + V_RESERVE)


def _rejoue(tk):
    """La pause de la regle : 30 min apres une cloture sous -30 %. `tk` : [{t, fin, r}]."""
    pris, att, bl = [], [], 0.0
    for x in sorted(tk, key=lambda z: z["t"]):
        att.sort(key=lambda z: z["fin"])
        while att and att[0]["fin"] <= x["t"]:
            f = att.pop(0)
            if f["r"] <= -0.30:
                bl = max(bl, f["fin"] + 1800.0)
        if x["t"] >= bl:
            pris.append(x)
        att.append(x)
    return pris


def _se_part(rs: list, seuil: float) -> float:
    """L ecart-type d une PART. Sans lui, un taux affiche se lit comme s il etait exact."""
    n = len(rs)
    if n < 2:
        return 0.0
    p = sum(1 for x in rs if x >= seuil) / n
    return (p * (1.0 - p) / n) ** 0.5


def _tranche(v: list, lab: str) -> dict:
    """Une population, sur 3 jours contre sa reference, avec le sigma de la DIFFERENCE."""
    p_r = sum(1 for x in v[0] if x >= 0.50) / len(v[0])
    p_a = sum(1 for x in v[1] if x >= 0.50) / len(v[1])
    se = (_se_part(v[0], 0.50) ** 2 + _se_part(v[1], 0.50) ** 2) ** 0.5
    return {"nom": lab,
            "pct_3j": round(100.0 * p_r, 1), "n_3j": len(v[0]),
            "pct_ref": round(100.0 * p_a, 1), "n_ref": len(v[1]),
            "ecart_pt": round(100.0 * (p_r - p_a), 1),
            "ic_pt": round(196.0 * se, 1),
            "sigma": round((p_r - p_a) / se, 2) if se else 0.0}


def _queue_haute(par_jour: dict) -> dict:
    """LA QUEUE HAUTE, LISSEE SUR 3 JOURS — et LAQUELLE des deux a bouge.

    27/09, §0.2 undecies. Tout l argent vient de la queue haute : la degradation du flux de la BANDE
    du 24 au 27/09 (−1,01 EUR/ticket) est ENTIEREMENT l amincissement de sa part de gros gains,
    17,5 % → 14,7 %, le taux de krach (37,8 → 38,6) et la taille du gros gain (+1,223 → +1,206)
    etant stables. Verification : 0,028 x 1,21 x 25 EUR = 0,85 sur 1,01 mesure.

    ET C EST LA QUE LA PAGE DOIT DISTINGUER DEUX CHOSES, parce que le decoupage par population
    retourne le diagnostic :
      - la queue du MARCHE (tous les pools eligibles) est **PLATE** : 9,6 % → 9,3 %, −0,37 sigma ;
      - la queue de la BANDE a **MINCI** : 17,5 % → 14,7 %, −1,81 sigma ;
      - et la zone qu on ecarte comme trop sure (< 0,20) a **EPAISSI** : 1,6 % → 2,7 %, +1,84 sigma.
    Le marche n a pas change : **la queue est sortie de la bande** pour aller dans la zone qu on
    n achete pas. C est une derive de concept -- `modele_vidage.json` est inchange depuis le 15/09 --
    donc « c est moi », pas « c est le marche », et la reponse n est pas dans la regle mais dans le
    modele. Le rapport `bande / marche` est ce qui le dit : x1,66 → x1,82 → x1,58.

    Pourquoi 3 jours et pas 1 : a ~280 pools/jour le bruit sur une part est de ±2,2 pt, donc les
    −2,8 pt qui expliquent tout valent 1 sigma sur une journee. En dessous de 2 sigma, rien a lire.
    """
    j = sorted(par_jour)
    if len(j) < 5:
        return {"lisible": False}
    rec, ref = j[-3:], j[:-3]

    def pop(filtre):
        return ([x["r"] for d in rec for x in par_jour[d] if filtre(x)],
                [x["r"] for d in ref for x in par_jour[d] if filtre(x)])

    tout = pop(lambda x: True)
    if len(tout[0]) < 100 or len(tout[1]) < 100:
        return {"lisible": False}
    dans = pop(lambda x: BANDE_ANCIENNE[0] <= x["risque"] < BANDE_ANCIENNE[1])
    sur = pop(lambda x: x["risque"] < BANDE_ANCIENNE[0])
    out = {"lisible": True, "jours_recents": rec,
           "marche": _tranche(tout, "le marche entier"),
           "bande": _tranche(dans, "la bande, celle qu on achete") if min(map(len, dans)) >= 80 else None,
           "sur": _tranche(sur, "plus sur que la bande (ecarte)") if min(map(len, sur)) >= 80 else None}
    # le pouvoir de concentration : ce que la bande multiplie la queue du marche
    if out["bande"]:
        for cle in ("3j", "ref"):
            m, b = out["marche"]["pct_%s" % cle], out["bande"]["pct_%s" % cle]
            out["conc_%s" % cle] = round(b / m, 2) if m else None
        gg = [x for x in dans[0] + dans[1] if x >= 0.50]
        taille = (sum(gg) / len(gg)) if gg else 0.0
        out["cout_eur_ticket"] = round(
            (out["bande"]["ecart_pt"] / 100.0) * taille * float(MISE_TABLE), 3)
    return out


def marche() -> dict:
    """LE MARCHE LUI-MEME, jour par jour — « c est moi ou c est le marche ? »

    Mido, 26/09 : « ajoute des indicateurs marche, car quand moi je perds de l argent je sais pas si
    c est le marche ou mes strats ». C est la question que la page ne savait pas trancher : elle
    montrait le resultat de la strategie sans jamais dire ce que le marche offrait CE JOUR-LA.

    CE QU ON MESURE, sur TOUS les pools eligibles -- pas seulement ceux qu on achete :
      rendement    ce que rapporte un pool eligible pris au hasard, net du peage. C EST LE TEMOIN :
                   s il est a -2 EUR, perdre 2 EUR par ticket est le tarif du jour, pas une faute.
      effondrement la part des pools qui tombent sous -50 %. Le danger ambiant.
      gros gains   la part au-dessus de +50 % et de x2. **C est de la que vient tout l argent** : la
                   strategie vit de la queue, donc un jour sans queue est un jour sans gain, quelle
                   que soit la regle.
      volume       combien de pools eligibles par jour. Peu de pools = peu d occasions.

    ET L ECART, qui est la vraie reponse : ce que NOTRE regle a fait moins ce que le marche offrait.
    Un ecart positif un jour de perte veut dire que la regle a bien travaille dans un marche mauvais.
    """
    out = {"jours": [], "erreur": None}
    try:
        c = sqlite3.connect("file:%s?mode=ro" % COMBO, uri=True, timeout=30)
        depuis = time.time() - 10 * 86400
        lignes = list(c.execute(
            "SELECT d.t_dec, d.risque, d.q, i.brut_240 FROM decision d JOIN issue i"
            " ON i.pair = d.pair WHERE d.eligible = 1 AND i.brut_240 IS NOT NULL"
            " AND d.q IS NOT NULL AND d.risque IS NOT NULL AND d.t_dec >= ? ORDER BY d.t_dec",
            (depuis,)))
    except Exception as e:  # noqa: BLE001
        out["erreur"] = str(e)[:200]
        return out

    par_jour: dict[str, list] = {}
    for t, r, q, b in lignes:
        net = min(float(b) - _cout_pool(q), 3.0)
        j = dt.datetime.fromtimestamp(float(t), TZ).strftime("%Y-%m-%d")
        par_jour.setdefault(j, []).append({"t": float(t), "fin": float(t) + 242.0,
                                           "r": net, "risque": float(r)})
    mise = float(MISE_TABLE)
    for j in sorted(par_jour):
        v = par_jour[j]
        rs = [x["r"] for x in v]
        n = len(rs)
        # ce que la REGLE aurait pris ce jour-la, pour l ecart au marche
        bande = [x for x in v if BANDE_ANCIENNE[0] <= x["risque"] < BANDE_ANCIENNE[1]]
        pris = _rejoue(bande) if bande else []
        out["jours"].append({
            "jour": j, "n": n,
            "marche_eur": round(mise * (sum(rs) / n), 3),
            "marche_median": round(mise * sorted(rs)[n // 2], 3),
            "effondrement_pct": round(100.0 * sum(1 for x in rs if x <= -0.50) / n, 1),
            "gros_gains_pct": round(100.0 * sum(1 for x in rs if x >= 0.50) / n, 1),
            "gros_gains_ic": round(196.0 * _se_part(rs, 0.50), 1),
            "x2_pct": round(100.0 * sum(1 for x in rs if x >= 1.00) / n, 1),
            "regle_eur": round(mise * (sum(x["r"] for x in pris) / len(pris)), 3) if pris else None,
            "regle_n": len(pris),
            "ecart": (round(mise * (sum(x["r"] for x in pris) / len(pris) - sum(rs) / n), 3)
                      if pris else None),
        })
    out["queue"] = _queue_haute(par_jour)
    return out


def bascule() -> dict:
    """L ANCIEN MODELE CONTRE LE NOUVEAU, depuis le passage du 26/09 — meme logique que
    `bascule_verdict.py`, mais pour la page.

    Mido : « il faut continuer a suivre l ancien modele pour savoir si on a bien fait de changer ».
    Chaque bras lit SA PROPRE pause sur SON PROPRE flux : croiser la bande de l un avec le flux de
    l autre fabriquerait un troisieme objet qui n a jamais tourne nulle part.
    """
    out = {"bascule": BASCULE_MODELE, "bras": [], "erreur": None,
           "pour_trancher": 411}   # mesure du 26/09 : 411 tickets/bras a 50 % de puissance
    mise = float(MISE_TABLE)
    for nom, chemin, bnd in (("ancien (témoin)", COMBO, BANDE_ANCIENNE),
                             ("nouveau (en prod)", CHALLENGER, BANDE_NOUVELLE)):
        try:
            c = sqlite3.connect("file:%s?mode=ro" % chemin, uri=True, timeout=30)
            tk = []
            for t, r, q, b in c.execute(
                    "SELECT d.t_dec, d.risque, d.q, i.brut_240 FROM decision d JOIN issue i"
                    " ON i.pair = d.pair WHERE d.eligible = 1 AND i.brut_240 IS NOT NULL"
                    " AND d.q IS NOT NULL AND d.risque IS NOT NULL AND d.t_dec >= ?",
                    (BASCULE_MODELE,)):
                if bnd[0] <= float(r) < bnd[1]:
                    tk.append({"t": float(t), "fin": float(t) + 242.0,
                               "r": min(float(b) - _cout_pool(q), 3.0)})
            pris = _rejoue(tk)
            v = [mise * x["r"] for x in pris]
            out["bras"].append({
                "nom": nom, "bande": list(bnd), "offerts": len(tk), "n": len(v),
                "niveau": round(sum(v) / len(v), 3) if v else None,
                "total": round(sum(v), 2) if v else None,
                "gros_gains_pct": (round(100.0 * sum(1 for x in v if x >= mise * 0.50) / len(v), 1)
                                   if v else None),
                "gagnants_pct": (round(100.0 * sum(1 for x in v if x > 0) / len(v), 1) if v else None),
            })
        except Exception as e:  # noqa: BLE001
            out["bras"].append({"nom": nom, "erreur": str(e)[:120]})
    return out


def _challengers() -> dict:
    """Les modeles geles en papier (B, C, D) et leur verdict, pour la page. Meme calcul que
    `challenger.juger()`."""
    from intel.research.challenger import resume
    return {"genere": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "modeles": resume()}


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
            # LE MARCHE ET LA BASCULE, a la meme cadence que la table. Chacun dans son `try` :
            # ils lisent d autres bases, et une base illisible ne doit pas emporter la page entiere.
            for nom, fn in (("carnet_marche.json", marche), ("carnet_bascule.json", bascule),
                            ("carnet_challengers.json", _challengers)):
                try:
                    ecrire(nom, fn())
                except Exception as e:  # noqa: BLE001
                    print("carnet_json: %s EN ECHEC : %s" % (nom, str(e)[:200]), flush=True)
            prochaine_table = time.time() + PAS_TABLE
        try:
            d = live()
            if d:
                ecrire("carnet_live.json", d)
        except Exception as e:  # noqa: BLE001
            print("carnet_json: LIVE EN ECHEC : %s" % str(e)[:200], flush=True)
        try:
            ecrire("carnet_reel.json", reel())
        except Exception as e:  # noqa: BLE001
            print("carnet_json: REEL EN ECHEC : %s" % str(e)[:200], flush=True)
        time.sleep(max(1, PAS_LIVE - (time.time() - t)))


if __name__ == "__main__":
    main()
