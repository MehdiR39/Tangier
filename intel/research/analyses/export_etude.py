"""SORT LES DONNEES DE L ETUDE hors du conteneur, pour qu un notebook puisse les lire.

Mido, 23/09 : « le truc qui me fait peur c est qu on est arrive a cette strat par chance. Il faut
une etude poussee pour comprendre pourquoi ca fonctionne, et qu on puisse l ameliorer en cas de
drift. Je te demande un Jupyter ou tu analyses tout, mais vraiment tout. »

POURQUOI UN EXTRAIT ET PAS UNE LECTURE DIRECTE. Les bases vivent dans un volume Docker
(`/app/db`), invisible depuis l hote ou tourne l environnement `qrt` ; et `intel.sqlite` fait
4,3 Go. On depose donc dans `data/etude/` -- qui EST monte sur l hote -- deux tables compactes
(~2 Mo) : tout ce qui est necessaire, rien de plus.

REJOUABLE A VOLONTE : le notebook redevient juste apres un `docker exec ... -m
intel.research.export_etude`. Aucune analyse n est faite ici, uniquement de la copie -- pour que
le notebook reste la seule source de raisonnement et qu on ne puisse pas se retrouver avec deux
verites.

Lecture seule sur les bases.
"""
from __future__ import annotations

import json
import os
import sqlite3

SORTIE = os.environ.get("ETUDE", "/app/data/etude")
COMBO = os.environ.get("COMBO_DB", "/app/db/papier_combo.sqlite")
INTEL = os.environ.get("INTEL_DB", "/app/db/intel.sqlite")


def main() -> None:
    os.makedirs(SORTIE, exist_ok=True)
    import pandas as pd

    # --- LE CARNET PAPIER : chaque jeton juge, ses variables a 45 s et son issue a 240 s. ------
    # C est le seul jeu qui contienne A LA FOIS ce que le modele a vu et ce que le jeton a fait --
    # donc le seul sur lequel on puisse rejouer une regle apres coup.
    cn = sqlite3.connect("file:%s?mode=ro" % COMBO, uri=True, timeout=60)
    d = pd.read_sql_query(
        "SELECT d.pair, d.mint, d.naissance, d.t_dec, d.eligible, d.q, d.V, d.risque, d.regime,"
        " d.n_regime, d.p_entree, d.cout_reduit, d.cout_reel, d.variables,"
        " i.brut_120, i.brut_240, i.ts AS t_issue"
        " FROM decision d LEFT JOIN issue i ON i.pair = d.pair ORDER BY d.t_dec", cn)
    # Les variables sont du JSON dans une colonne : on les eclate en vraies colonnes `v_*`,
    # sinon chaque analyse devrait le refaire et elles finiraient par diverger.
    def _eclate(s):
        try:
            return json.loads(s) if s else {}
        except Exception:  # noqa: BLE001
            return {}
    v = pd.DataFrame([_eclate(x) for x in d["variables"]]).add_prefix("v_")
    d = pd.concat([d.drop(columns=["variables"]), v], axis=1)
    # CSV COMPRESSE, pas du parquet ni du pickle. Le conteneur n a pas `pyarrow`, et son pandas
    # (3.0.6) n est pas celui de l environnement `qrt` de l hote (3.0.3) : un pickle ecrit d un
    # cote et relu de l autre est une panne qui attend. Le CSV ne depend d aucune version.
    d.to_csv(os.path.join(SORTIE, "papier.csv.gz"), index=False, compression="gzip")

    # --- LE CARNET REEL : ce que le moteur a vraiment fait, statut par statut. -----------------
    ci = sqlite3.connect("file:%s?mode=ro" % INTEL, uri=True, timeout=60)
    r = pd.read_sql_query(
        "SELECT mint, pair, mode, statut, naissance, t_dec, risque, depuis_min, q, ts_entree,"
        " prix_entree, mise_eur, tx_achat, ts_sortie, tx_vente, gain_eur, motif"
        " FROM mr_lignes ORDER BY t_dec", ci)
    r.to_csv(os.path.join(SORTIE, "reel.csv.gz"), index=False, compression="gzip")

    # --- LE CONTEXTE, pour que le notebook n ait AUCUN chiffre en dur. -------------------------
    from intel.settings import IntelConfig, Settings
    cfg = IntelConfig.load(Settings.load().config_path)
    meta = {
        "papier": {"lignes": int(len(d)), "colonnes": int(d.shape[1]),
                   "avec_issue": int(d["brut_240"].notna().sum())},
        "reel": {"lignes": int(len(r))},
        "prod": {k: cfg.get("modele_rapide.%s" % k) for k in
                 ("mode", "regle", "mise_eur", "pause_secondes", "pause_seuil",
                  "pause_cout_fixe", "tenue_secondes", "age_decision", "cumul_depuis")},
        "bande": [0.20, 0.35],
        "peage_mesure": 0.0388,
        "nul_pause": 0.384,
    }
    try:
        m = json.load(open("/app/data/recherche/candidates/modele_frais_meta.json"))
        meta["candidates"] = {"gel": m["gel"], "gel_lisible": m["gel_lisible"],
                              "bande_frais": m["bande_frais"]}
    except Exception:  # noqa: BLE001
        pass
    json.dump(meta, open(os.path.join(SORTIE, "contexte.json"), "w"), indent=1)

    print("papier.csv.gz   : %d lignes, %d colonnes (%d avec issue)"
          % (len(d), d.shape[1], meta["papier"]["avec_issue"]))
    print("reel.csv.gz     : %d lignes" % len(r))
    print("contexte.json   : %s" % json.dumps(meta["prod"]))
    print("-> %s" % SORTIE)


if __name__ == "__main__":
    main()
