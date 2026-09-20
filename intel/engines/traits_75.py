"""LES VARIABLES DE LA FORET 75s, PRODUITES PAR LE MOTEUR, EN DIRECT.

Le modele `foret_75s_top10.json` attend 25 variables. Le moteur en produit 5 lui-meme (prix et
liquidite), en deduit 1 (`risque`, la sortie du modele de vidage), et il manque les 19 autres :
15 de FLUX D ORDRES, 1 de REGIME, 3 d IMAGE.

CE MODULE LES FABRIQUE, et rien d autre. Trois sources, trois traitements :

  FLUX (15)     un appel Helius sur le pool, fenetre [naissance - 5 s, naissance + 60 s], puis
                `v1_traits.traits()` -- **la meme fonction que la recherche**, pas une reecriture.
                Mesure du 20/09 : 0,70 s en mediane, 96 % des pools sous les 5 s disponibles entre
                la donnee (70 s) et la decision (75 s).
  REGIME (1)    `reg_moy_20` : la moyenne du rendement des 20 derniers tickets CLOTURES avant la
                decision. Lu dans le carnet papier, comme `tout_table.regime()` le fait.
  IMAGES (3)    ABSENTES, volontairement. Il faudrait chercher l image sur IPFS a 75 s, et elles
                sont MESUREES inutiles : 0 % d importance par permutation, et en euros +0,97 sigma
                -- l ecart tient a 18 tickets sur 2 675, dont **zero** pris seulement AVEC elles.
                Le modele recevra sa mediane d apprentissage, exactement comme le pipeline de
                recherche le fait deja (l image manque sur 49 % des tickets d entrainement).

POURQUOI `None` ET JAMAIS ZERO pour une valeur qu on n a pas. Zero est une INFORMATION -- « aucun
achat », « aucun robot » -- et le modele la traiterait comme telle. `None` fait prendre la mediane
d apprentissage, qui est le traitement d origine. Confondre les deux, c est la regle 10 du projet.
"""
from __future__ import annotations

import glob
import json
import logging
import os
import sqlite3
import sys
import time
from collections import defaultdict

log = logging.getLogger(__name__)

V1_DIR = "/app/data/recherche/v1_avant"
COMBO_DB = os.environ.get("COMBO_DB", "/app/db/papier_combo.sqlite")
# DEUX NOMBRES DIFFERENTS, et les confondre fausse tout. La FENETRE est ce qu on demande a Helius ;
# l AGE DE DECISION est jusqu ou on a le droit de lire. Le premier essai les confondait : le direct
# lisait 60 s quand la table de comparaison s arretait a 45, et les 8 pools testes differaient tous.
FENETRE = 60                       # ce qu on demande a Helius : naissance -> +60 s
AGE_DECISION = 60                  # jusqu ou le modele 75s a le droit de lire (45 pour le 45 s)
FENETRE_REGIME = 20                # les 20 derniers tickets clotures
TENUE_S = 242.0                    # un ticket n est CLOTURE que 242 s apres sa decision
PAGES_MAX = 3                      # au-dela, on decide avec ce qu on a plutot que rater le ticket

# nom chez le moteur -> nom attendu par le modele
RENOMME = {"vol": "px_vol", "q_croiss": "px_q_croiss", "q_croiss_30": "px_q_croiss_30",
           "ret_30": "px_ret_30", "ret_10": "px_ret_10", "ret_60": "px_ret_60",
           "ret_120": "px_ret_120", "q_croiss_60": "px_q_croiss_60", "n_lect": "px_n_lect",
           "ret_naiss": "px_ret_naiss", "dd_max": "px_dd_max", "depuis_min": "px_depuis_min",
           "t_depuis_max": "px_t_depuis_max", "lancements_10min": "px_lancements_10min",
           "heure": "px_heure", "A": "px_A"}


class Traits75:
    """Fabrique les variables de la foret 75s. Un objet, pour garder l historique des portefeuilles."""

    def __init__(self, avant: float | None = None, age_max: int = AGE_DECISION) -> None:
        """`avant` borne l historique aux pools nes AVANT cet instant.

        Inutile en production -- tout ce qui est dans les fichiers y est deja anterieur -- mais
        indispensable pour VERIFIER le module contre la recherche : celle-ci construit son
        historique pool par pool, dans l ordre de naissance, donc un pool ancien n a jamais vu
        ceux qui le suivent. Sans cette borne, la verification comparait un historique complet a
        un historique tronque et les deux ne pouvaient pas coincider.
        """
        self._vus: defaultdict[str, set] = defaultdict(set)
        self._age_max = age_max
        self._charge_historique(avant, age_max)

    def _charge_historique(self, avant: float | None = None,
                           age_max: int = AGE_DECISION) -> None:
        """L historique portefeuille -> pools, lu une fois au demarrage dans `v1_avant`.

        C est ce qui permet `v1_robots` et `v1_part_robots` -- « ce portefeuille a-t-il deja ete vu
        dans au moins 5 pools ANTERIEURS ». Je les avais d abord abandonnees en disant que le moteur
        n avait pas cet etat ; Mido : « pourquoi les autres variables ? ». Verification faite, les
        fichiers portent tout l historique et le lire prend quelques secondes.
        """
        t0, n = time.time(), 0
        for f in sorted(glob.glob(os.path.join(V1_DIR, "*.jsonl"))):
            try:
                with open(f, encoding="utf-8") as fh:
                    for ligne in fh:
                        try:
                            d = json.loads(ligne)
                        except ValueError:
                            continue
                        pair = d.get("pair")
                        if not pair:
                            continue
                        if avant is not None and float(d.get("naissance") or 0) >= avant:
                            continue          # ne jamais compter un pool posterieur
                        n += 1
                        for tx in d.get("tx") or []:
                            # LE MEME FILTRE D AGE QUE LE CALCUL. Sans lui, l historique comptait
                            # des acheteurs de la 46e a la 60e seconde que la recherche ignore a
                            # 45 s -- et `v1_robots` differait sur 6 pools sur 8. Un portefeuille
                            # n entre dans l historique que s il a achete AVANT l instant de
                            # decision, exactement comme dans `tout_table`.
                            try:
                                if int(tx[0]) > age_max:
                                    continue
                            except (TypeError, ValueError, IndexError):
                                continue
                            for p in (tx[2] if len(tx) > 2 else None) or []:
                                try:
                                    q, dj, ds = str(p[0]), float(p[1]), float(p[2])
                                except (TypeError, ValueError, IndexError):
                                    continue
                                if dj > 0 and ds < 0:
                                    self._vus[q].add(pair)
            except OSError:
                continue
        log.info("traits_75: historique charge · %d pools · %d portefeuilles · %.1f s",
                 n, len(self._vus), time.time() - t0)

    # ------------------------------------------------------------------ le regime
    def regime(self, maintenant: float) -> float | None:
        """La moyenne des 20 derniers tickets CLOTURES avant cet instant.

        « Cloture » et non « decide » : un ticket decide il y a 100 s n a pas encore de resultat, et
        s en servir serait lire l avenir. Meme definition que `tout_table.regime()`.
        """
        try:
            c = sqlite3.connect("file:%s?mode=ro" % COMBO_DB, uri=True, timeout=5)
            try:
                lignes = c.execute(
                    "SELECT i.brut_240 FROM decision d JOIN issue i ON i.pair = d.pair"
                    " WHERE d.eligible = 1 AND i.brut_240 IS NOT NULL AND d.t_dec + ? <= ?"
                    " ORDER BY d.t_dec DESC LIMIT ?",
                    (TENUE_S, maintenant, FENETRE_REGIME)).fetchall()
            finally:
                c.close()
        except sqlite3.Error as exc:
            log.warning("traits_75: regime illisible (%s)", str(exc)[:80])
            return None
        v = [float(x[0]) for x in lignes if x[0] is not None]
        return (sum(v) / len(v)) if len(v) >= 5 else None       # < 5 : on ne sait pas, donc None

    # ------------------------------------------------------------------ le flux d ordres
    def flux(self, pair: str, mint: str, naissance: float, V: float,
             age_max: int = AGE_DECISION) -> dict:
        """Les 15 variables de flux, via Helius puis `v1_traits.traits()`.

        PAGES_MAX borne l appel : un pool a 3 000 transactions demande 5 pages et 10 s, ce qui
        ferait rater la decision. On prefere decider sur les premieres pages que ne pas decider --
        et on le dit dans les journaux plutot que de le laisser passer en silence.
        """
        d = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research")
        if d not in sys.path:
            sys.path.insert(0, d)
        import copie_collecte as cc            # noqa: PLC0415
        from v1_traits import traits           # noqa: PLC0415

        jeton, pages, ev = None, 0, []
        while pages < PAGES_MAX:
            opts = {"transactionDetails": "full", "sortOrder": "asc", "limit": 1000,
                    "encoding": "jsonParsed", "maxSupportedTransactionVersion": 1,
                    "filters": {"blockTime": {"gte": int(naissance) - 5,
                                              "lte": int(naissance) + FENETRE},
                                "status": "succeeded"}}
            if jeton:
                opts["paginationToken"] = jeton
            res = cc.rpc({"jsonrpc": "2.0", "id": 1, "method": "getTransactionsForAddress",
                          "params": [pair, opts]}) or {}
            pages += 1
            for tx in res.get("data") or []:
                a = cc.analyser(tx, pair, mint, V or 0.0, naissance)
                age = (tx.get("blockTime") or naissance) - naissance
                parts = [[o, dj, ds] for o, dj, ds in a[4]] if a else []
                ev.append([age, tx.get("version"), parts, a[3] if a else None,
                           a[5] if a else None, 0, None])
            jeton = res.get("paginationToken")
            if not jeton:
                break
        if jeton:
            log.info("traits_75: %s tronque a %d pages -- on decide avec ce qu on a",
                     pair[:10], PAGES_MAX)
        return traits(ev, age_max, vus=self._vus, pair=pair)

    # ------------------------------------------------------------------ l assemblage
    def variables(self, f_moteur: dict, risque: float, pair: str, mint: str,
                  naissance: float, V: float) -> dict | None:
        """Le dictionnaire complet attendu par le modele, ou None si le flux est illisible.

        None et non un dictionnaire incomplet : un pool dont on ne sait rien ne doit pas etre
        decide sur des medianes -- ce serait acheter au hasard en croyant suivre un modele.
        """
        t0 = time.time()
        try:
            v1 = self.flux(pair, mint, naissance, V)
        except Exception as exc:  # noqa: BLE001
            log.warning("traits_75: flux illisible pour %s (%s)", pair[:10], str(exc)[:80])
            return None
        if not v1.get("v1_n_achats"):
            return None                        # aucun achat lu : on ne decide pas
        out = dict(v1)
        out.update({RENOMME.get(k, k): v for k, v in f_moteur.items()})
        out["risque"] = float(risque)
        out["reg_moy_20"] = self.regime(time.time())
        log.debug("traits_75: %s · %d variables · %.2f s", pair[:10], len(out), time.time() - t0)
        return out
