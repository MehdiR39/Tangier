"""ACHETER SUR LE MODELE : « au plus bas » ET bande de risque 0,20-0,35.

POURQUOI CE MODULE EXISTE. Le moteur de production ne savait faire qu une chose -- acheter les
jetons portant un Telegram a T+60, avec un stop a -30 % et une prise de gain a +50 %. Rejouee sur
la periode ou elle a vraiment tourne, cette regle donne -7,73 % par ticket, et le carnet reel a
fait -6,44 % : les deux concordent. Pendant ce temps une dizaine de regles tournent en papier sans
pouvoir etre essayees, faute de branchement. Mido : « le bot contient deux regles et on a une
dizaine de strats qui tournent en papier, pourquoi tu veux y aller avec la regle Telegram ? »

LA REGLE BRANCHEE ICI, et la raison de chaque morceau :

  depuis_min == 0        le prix a 45 s EST son plus bas depuis la naissance. Le jeton n a fait que
                         descendre, il n a pas rebondi. Seule variable du projet dont l AUC sur les
                         catastrophes et celle sur les gros gains partent de cotes OPPOSES. Elle
                         multiplie les gains >= +50 % par 2,32 (p < 0,0001) sans augmentation
                         mesurable des catastrophes (x1,20, p = 0,232). Journal §3.116.

  0,20 <= risque < 0,35  la bande de probabilite de vidage. Ni trop mort -- les quintiles surs ont
                         0,0 % de gros gains -- ni trop dangereux. Journal §3.100.

  sortie a 240 s, SANS STOP NI PRISE DE GAIN. Mesure decisive : sur la meme regle Telegram, tenir
                         aveuglement 240 s donne +7,24 % par ticket ; ajouter le stop a -30 % fait
                         tomber a +2,11 %, la prise de gain a +50 % a +5,10 %, les deux a +0,62 %.
                         Les deux reflexes coutent 6,6 points. Le stop vend les jetons qui allaient
                         remonter (13 % de ceux qui touchent -30 % finissent au-dessus de -10 %),
                         la prise de gain coupe les x2 et x3 qui portent tout le resultat.

CE QU ON ATTEND DE CETTE MISE EN REEL, et c est le point important : **on ne cherche PAS a gagner
au premier coup.** On cherche les faits que le papier ne peut pas donner -- le cout d execution
d aujourd hui (le 2,62 date du 12-15/09 et n est qu extrapole depuis), si les ordres atterrissent,
si l on se fait sandwicher. Mido a explicitement accepte de perdre pour les obtenir, a hauteur de
~150 EUR.

HONNETETE SUR LA REGLE. Elle a ete gelee le 18/09 a 11h30 et n a donc AUCUN ticket hors echantillon.
Les +5,30 % par ticket qu elle affiche sont les chiffres qui l ont fait CHOISIR, pas une validation
-- exactement ce qu affichait la bande (+3,90 %) avant de mourir hors echantillon. Son verdict gele
tombe a 1 200 tickets. Le present module ne prejuge pas de ce verdict : il sert a mesurer
l EXECUTION, et le choix de la regle ne fait que limiter la casse pendant qu on mesure.

IL FAUT DEUX ACTES POUR QU IL ACHETE, comme partout ici : `modele_rapide.enabled: true` ET
`modele_rapide.mode: live`, plus une cle presente. Tant que l un des trois manque, ce module decide,
enregistre, et n envoie RIEN. Il ecrit dans sa propre table `mr_lignes` et ne touche a aucune autre.
"""
from __future__ import annotations

import json
import logging
import math
import os
from bisect import bisect_right
from typing import Any

log = logging.getLogger(__name__)

A = 45                    # l age de la decision PAR DEFAUT (`age_decision` dans la config)
EXEC_S = 2                # le delai entre la decision et l entree, comme dans la recherche
TENUE_S = 240             # duree de detention PAR DEFAUT : NI stop, NI prise de gain (6,6 pts)

# DECIDER A 75 s AU LIEU DE 45. La famille `FORET 75s` est la seule qui gagne (6/6 criteres,
# 86-91 % de gagnants), et elle decide a 75 s : a 45 s l index ne montre que 88 % des transactions,
# a 75 s il les montre toutes (retard mesure 10-15 s). Deux reglages suffisent a l y amener --
# `age_decision: 75` et `tenue_secondes: 163` -- et un troisieme, `traits_75: true`, fait produire
# au moteur les 15 variables de flux dont ce modele tire 71 % de son information.
#
# POURQUOI 163 ET NON 240. Le modele 75s predit le rendement de 77 s a 240 s, soit 163 secondes de
# detention. Tenir 240 s ferait sortir a 317 s : on deploierait un modele entraine sur une sortie
# qu on ne fait pas -- l erreur corrigee le 20/09 sur FORET GAGNANT.
BANDE = (0.20, 0.35)
# LA RESERVE VIRTUELLE DE PUMPSWAP, en SOL. Le prix est (coffre + 17,5845) / jetons, et c est aussi
# ce qui amortit l impact d un ordre : un pool a coffre nul n a pas une profondeur nulle. Meme
# valeur que dans la table de reference et dans `papier_combo` -- si elle divergeait, le seuil de
# la pause ne designerait plus les memes clotures.
V_RESERVE = 17.5845
MODELE = os.environ.get("MODELE_VIDAGE", "/app/data/recherche/balayage/modele_vidage.json")

# LES VARIABLES DOIVENT ETRE CELLES DE L ENTRAINEMENT, PAS CELLES DE NOTRE MISE.
# `cout` est une VARIABLE DU MODELE, et le filtre d eligibilite « ordre > 15 % du pool » en depend
# aussi. Les calculer avec notre mise reelle donnerait au modele une entree qu il n a jamais vue et
# changerait les jetons retenus : mesure sur 210 pools, 49 basculaient d eligibilite (19 %) et les
# 210 avaient un `cout` different. On reprend donc les constantes EXACTES de `papier_combo`, et la
# mise reelle ne sert qu au DIMENSIONNEMENT DE L ORDRE, jamais aux variables.
MISE_SOL_MODELE, COUT_FIXE_MODELE = 0.31, 0.017

# LE FREIN LIT LE CARNET PAPIER, pas le carnet reel : voir `frein_ouvert`. Le cout retenu pour
# juger « gagnant ou perdant » est celui mesure sur 244 tickets reels -- le meme que partout.
COMBO_DB = os.environ.get("COMBO_DB", "/app/db/papier_combo.sqlite")
COUT_MESURE = 0.0262


def _a_age(ages: list[float], cible: float, tol: float):
    """L index de la lecture la plus proche de cet age, si elle est assez proche."""
    best, ecart = None, tol + 1
    for i, a in enumerate(ages):
        d = abs(a - cible)
        if d < ecart:
            best, ecart = i, d
    return best if ecart <= tol else None


class ModeleRapide:
    """Decide a 45 s sur le modele, achete a 47 s, revend a 287 s. Rien d autre."""

    def __init__(self, ctx, client, prefixe: str = "modele_rapide",
                 table: str = "mr_lignes") -> None:
        """`prefixe` et `table` permettent une SECONDE instance sans toucher a la premiere.

        POURQUOI CE PARAMETRAGE, et pourquoi il ne peut pas casser la production. Mido a demande
        (25/09) de faire tourner `G+D` en reel EN PARALLELE de `BANDE + PAUSE`, « sans casser ce qui
        tourne ». Deux instances de cette classe le permettent -- mais elles doivent ecrire dans DEUX
        tables, sinon le registre des couts (`cout_registre.py`, `cout_glissement.py`,
        `cout_reserve.py`, `calibration_live.py`, qui ne filtrent que sur `mode='live'`) moyennerait
        deux regles aux pools de tailles differentes, et le 3,88 % qui evalue TOUTES les lignes de la
        page deriverait en silence. Le cumul Telegram et la page melangeraient de meme les deux.

        LA GARANTIE. Aucune des ~33 requetes SQL de ce module n a ete reecrite : elles nomment
        toujours `mr_lignes` en clair. C est `_q` / `_x` qui substituent `self.table`, et quand
        `self.table == "mr_lignes"` la substitution est un NON-OPERANT. La production execute donc
        le meme SQL qu avant, par construction et non par relecture.
        """
        self.ctx, self.client = ctx, client
        self._base = ctx.db
        self.prefixe, self.table = prefixe, table
        self._modele = None
        self._vus: set[str] = set()
        # mint -> (nombre d echecs de vente, instant de la derniere alerte). Une position
        # qu on n arrive pas a vendre est de l argent BLOQUE : elle doit reveiller
        # l operateur, seul a pouvoir vendre a la main, au lieu de retenter en silence.
        self._echecs: dict[str, tuple[int, float]] = {}

    def _cfg(self, cle: str, defaut: Any) -> Any:
        return self.ctx.config.get("%s.%s" % (self.prefixe, cle), defaut)

    # --- acces a la base, avec la table de CETTE instance ---------------------
    # Les deux seules portes par lesquelles ce module lit et ecrit. Voir `__init__`.

    def _sql(self, sql: str) -> str:
        """Le SQL de CETTE instance. Pour la production, la fonction est l IDENTITE -- au sens strict :
        on ne passe meme pas par un `replace`, donc aucun chemin ne peut la modifier.

        LE NOM D INDEX EST REECRIT AUSSI, et ce n est pas un detail : dans SQLite un nom d index est
        GLOBAL a la base, pas attache a sa table. `CREATE INDEX IF NOT EXISTS i_mr_statut ON
        gd_lignes(statut)` aurait donc trouve le nom deja pris par `mr_lignes` et n aurait RIEN fait
        -- la table du suiveur serait restee sans index, en silence.
        """
        if self.table == "mr_lignes":
            return sql
        return (sql.replace("mr_lignes", self.table)
                   .replace("i_mr_statut", "i_%s_statut" % self.table))

    # `self._base` est la MEME base que `self.ctx.db` -- l alias existe pour que ces deux methodes
    # ne s appellent pas elles-memes : partout ailleurs dans ce module, l acces direct a la base a
    # ete remplace par `self._q(...)` / `self._x(...)`, et si les deux lignes ci-dessous passaient
    # par le meme chemin elles boucleraient a l infini.
    def _q(self, sql: str, params: Any = ()) -> Any:
        return self._base.query(self._sql(sql), params)

    def _x(self, sql: str, params: Any = ()) -> Any:
        return self._base.execute(self._sql(sql), params)

    def _traits75(self):
        """L objet qui fabrique les variables de flux. Cree une seule fois : il porte l historique
        des portefeuilles, dont la lecture prend quelques secondes."""
        if getattr(self, "_t75", None) is None:
            from intel.engines.traits_75 import Traits75  # noqa: PLC0415
            self._t75 = Traits75(age_max=int(self._cfg("age_v1", 60)))
        return self._t75

    def _charge_risque(self):
        """LE MODELE DE VIDAGE, charge en SECOND quand le decideur a besoin de `risque` en entree.

        La foret 75s utilise `risque` -- la probabilite de vidage -- comme une de ses 25 variables.
        Il faut donc deux modeles : celui qui produit cette variable, et celui qui decide. Les
        confondre donnerait au decideur sa propre sortie en entree.
        """
        if getattr(self, "_mr", None) is None:
            import sys
            d = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research")
            if d not in sys.path:
                sys.path.insert(0, d)
            from ensemble import Ensemble  # noqa: PLC0415
            chemin = self._cfg("modele_risque",
                               "/app/data/recherche/balayage/foret_vidage_fige_15-09.json")
            self._mr = Ensemble(chemin)
            log.info("modele_rapide: modele de RISQUE charge depuis %s (seuil %.4f)",
                     os.path.basename(chemin), self._mr.seuil_p80)
        return self._mr

    def _charge_modele(self):
        """Charge le modele de vidage, quel que soit son FORMAT.

        Deux formats coexistent dans le projet et exposent la meme interface (`probabilite`,
        `seuil_p80`) :
            `tree_info`  export LightGBM direct         -> `arbres.Modele`   (modele_vidage.json)
            `modeles`    enveloppe d ensemble, n>=1     -> `ensemble.Ensemble` (foret_vidage.json)
        On choisit d apres le CONTENU du fichier, pas d apres son nom : brancher la foret ne doit
        pas demander de se souvenir de quel loader va avec quel fichier.
        """
        # RECHARGER QUAND LE FICHIER CHANGE. Le modele etait charge UNE FOIS et garde en memoire :
        # un modele reentraine toutes les 6 h n aurait jamais ete pris en compte avant un
        # redemarrage, et on aurait cru tourner dessus. On compare donc la date du fichier a
        # chaque cycle -- une lecture de metadonnee, negligeable a cote d un cycle de decision.
        chemin = self._cfg("modele", MODELE)
        try:
            horodate = os.path.getmtime(chemin)
        except OSError:
            horodate = None
        if self._modele is None or (chemin, horodate) != getattr(self, "_modele_source", None):
            import sys
            d = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research")
            if d not in sys.path:
                sys.path.insert(0, d)
            with open(chemin, encoding="utf-8") as f:
                forme = json.load(f)
            if "tree_info" in forme:
                from arbres import Modele  # noqa: PLC0415
                self._modele = Modele(chemin)
                n = len(self._modele.arbres)
            elif "modeles" in forme:
                from ensemble import Ensemble  # noqa: PLC0415
                self._modele = Ensemble(chemin)
                n = sum(len(m.get("tree_info") or []) for m in forme["modeles"])
            else:
                raise ValueError("modele_rapide: format inconnu pour %s (ni tree_info ni modeles)"
                                 % chemin)
            self._modele_source = (chemin, horodate)
            log.info("modele_rapide: modele charge depuis %s (%d arbres, seuil %.4f)",
                     os.path.basename(chemin), n, self._modele.seuil_p80)
        return self._modele

    # ---------------------------------------------------------------- decision

    def _variables(self, pts, naissance, lancements, age_entree=None):
        """Les memes variables que la recherche, calculees sur les memes lectures.

        `pts` : [(age, prix, reserve_sol, reserve_base, reserve_virtuelle)] tries par age.
        Rend None des qu une condition d eligibilite manque -- on ne devine jamais une variable.
        """
        age_entree = A + EXEC_S if age_entree is None else age_entree
        ages = [p[0] for p in pts]
        prix = [p[1] for p in pts]
        qs = [p[2] for p in pts]
        v = pts[0][4] or 0.0
        k = bisect_right(ages, A)
        if k < 3 or pts[0][0] > 32:
            return None
        # EXIGER UNE LECTURE PRES DE L INSTANT D ENTREE, comme la recherche. Sans ce controle le
        # moteur accepterait des pools que `papier_combo` ecarte : mesure sur 510 pools, exactement
        # 3 basculaient. Un prix d entree extrapole n est pas un prix qu on peut payer.
        # L INSTANT D ENTREE SUIT L AGE DE DECISION, pas les variables. Les variables de prix
        # restent calculees a 45 s -- c est ainsi que le modele 75s a ete entraine : `px_*` vient
        # des variables enregistrees par `papier_combo` a 45 s, seul le FLUX passe a 60 s et le
        # rendement a 77 -> 240 s. Mais on achete a l age de decision + 2 s, donc c est LA qu il
        # faut une lecture de prix. Exiger 47 s quand on entre a 77 refuserait des pools valides
        # et en accepterait d autres sans prix payable.
        if _a_age(ages, age_entree, 6) is None:
            return None
        if qs[k - 1] + v <= 0 or MISE_SOL_MODELE / (qs[k - 1] + v) > 0.15:
            return None                      # ordre trop gros pour le pool : on n y va pas
        pv, qv = prix[:k], qs[:k]
        logs = [math.log(x) for x in pv if x > 0]
        if len(logs) < 2:
            return None
        diffs = [b - a for a, b in zip(logs, logs[1:])]
        moy = sum(diffs) / len(diffs)
        f = {"n_lect": k, "ret_naiss": pv[-1] / pv[0] - 1, "dd_max": pv[-1] / max(pv) - 1,
             "depuis_min": pv[-1] / min(pv) - 1, "t_depuis_max": A - ages[pv.index(max(pv))],
             "vol": math.sqrt(sum((d - moy) ** 2 for d in diffs) / len(diffs)),
             "q": qv[-1], "q_croiss": qv[-1] / qv[0] - 1 if qv[0] > 0 else float("nan"),
             "heure": int(((naissance + A) % 86400) // 3600), "V": int(v > 0), "A": A,
             "cout": COUT_FIXE_MODELE + 2 * MISE_SOL_MODELE / (qv[-1] + v)}
        for w in (10, 30, 60, 120):
            j = _a_age(ages, A - w, 6)
            f["ret_%d" % w] = (pv[-1] / prix[j] - 1) if (j is not None and j < k) else float("nan")
        for w in (30, 60):
            j = _a_age(ages, A - w, 6)
            f["q_croiss_%d" % w] = (qv[-1] / qs[j] - 1) if (j is not None and j < k and qs[j] > 0) else float("nan")
        t_dec = naissance + A
        f["lancements_10min"] = bisect_right(lancements, t_dec) - bisect_right(lancements, t_dec - 600)
        return f

    def _age(self) -> int:
        """L age auquel on decide. 45 par defaut, 75 pour la foret a 75 s."""
        return int(self._cfg("age_decision", A))

    def _tenue(self) -> float:
        """Combien de temps on tient. Doit correspondre a la SORTIE sur laquelle le modele a ete
        entraine, pas a une habitude : 240 s pour le modele a 45 s, 163 s pour celui a 75 s."""
        return float(self._cfg("tenue_secondes", TENUE_S))

    def _bande(self) -> tuple[float, float]:
        """LES BORNES DE LA BANDE, lues dans la config. Defaut = celles de la production.

        POURQUOI ELLES NE PEUVENT PLUS ETRE EN DUR. Adopter un modele reentraine impose de changer
        la bande EN MEME TEMPS : un modele frais redistribue ses scores, et garder [0,20 ; 0,35]
        designerait d autres jetons -- ce ne serait plus la regle mesuree. `challenger.py` calcule
        la bande du challenger sur les QUANTILES qu occupe celle en service, et c est ce couple-la
        qu on lit ici.

        ET ELLES SONT LUES AUX DEUX ENDROITS QUI COMPTENT : la regle d achat (`retenu`) et la
        requete de la PAUSE (`pause_ouverte`). Les changer a un seul endroit ferait acheter dans une
        bande et surveiller les clotures d une autre -- la pause ne serait plus celle qui a ete
        mesuree, sans que rien ne le signale.
        """
        b = self._cfg("bande", None)
        if not b:
            return BANDE
        return (float(b[0]), float(b[1]))

    def _seuil(self) -> float:
        """Le seuil de decision, qu il soit ecrit dans la config ou porte par le modele.

        `seuil_risque: auto` le prend dans le FICHIER du modele. C est indispensable des lors que
        le modele se reentraine : ses scores se redistribuent a chaque entrainement, et un nombre
        fige dans la config ne garderait plus la meme proportion de tickets -- il deriverait en
        silence, exactement comme le seuil des gels (§3.158 : 40 tickets gardes la ou il en
        fallait 110).

        UN SEUL ENDROIT POUR CETTE LECTURE, et c est le but de cette methode : `seuil_risque` etait
        lu a DEUX endroits, et le second faisait `float(...)` directement. Avec `auto` il aurait
        lance une exception a chaque cycle -- rattrapee par un `except` qui fait « laisser passer »
        le frein, donc sans rien casser de visible et sans que personne ne le sache.
        """
        brut = self._cfg("seuil_risque", 0.2694)
        if isinstance(brut, str) and brut.strip().lower() == "auto":
            return float(self._charge_modele().seuil_p80)
        return float(brut)

    def retenu(self, f: dict, risque: float, regle: str | None = None,
               pair: str | None = None) -> bool:
        """La regle en service. NaN ecarte AVANT toute comparaison.

        Une comparaison avec NaN est toujours fausse : sans ce garde-fou un ticket dont
        `depuis_min` manque basculerait silencieusement du mauvais cote.

        POURQUOI LA REGLE EST CONFIGURABLE, et pourquoi le defaut est `risque`.
        `bas_bande` a d abord ete branchee sur la foi de +5,30 % par ticket -- mais ce chiffre
        portait sur TOUTE la periode, alors que la BANDE qu elle contient etait deja morte hors
        echantillon depuis son gel du 17/09 18h30. Coupe a cette date, la conjonction donne
        **-7,10 %** par ticket et **-16,91 %** sans ses trois meilleurs : pire que le temoin
        (-3,57 %). Mido : « pourquoi t as choisi de mettre en prod BAS + BANDE sachant que t as
        decide hier que bande c est de la merde ». Il avait raison.

        Sur cette meme periode hors echantillon, la moins mauvaise regle est `risque` :
        **-0,11 %** par ticket sur 408 tickets, contre -3,57 % pour le temoin. Aucune n est
        positive -- on ne choisit pas une gagnante, on choisit celle qui coute le moins cher
        pendant qu on mesure l EXECUTION.

        Toute regle ajoutee ici doit etre justifiee sur des tickets POSTERIEURS a son propre gel,
        jamais sur la periode qui l a fait choisir.
        """
        r = (regle or self._cfg("regle", "risque")).lower()
        if r == "risque":
            # `seuil_risque: auto` -> le seuil vient du FICHIER du modele, pas de la config.
            # Indispensable des lors que le modele se reentraine : ses scores se redistribuent a
            # chaque entrainement, et un seuil fige dans la config ne garderait plus la meme
            # proportion de tickets -- il deriverait en silence. C est exactement la derive
            # mesuree sur les gels (40 tickets gardes la ou il en fallait 110, §3.158).
            return risque <= self._seuil()
        if r == "bande":
            # LA BANDE SEULE, sans la condition `depuis_min == 0` de `bas_bande`. C est la regle
            # mesuree par `BANDE + PAUSE` : 25,2 % de gros gains contre 10 % au marche (p = 0,000),
            # +2,52 EUR/ticket sur 107 tickets. Son NIVEAU n est pas prouve (+1,27 sigma, il faudrait
            # 266 tickets) mais c est la seule ligne du projet qui rapporte, et elle est branchee
            # sur decision de Mido -- qui rappelle qu il faut quelque chose en production, sinon le
            # registre des couts ne se remplit plus et plus aucune strategie n est evaluable.
            lo, hi = self._bande()
            return lo <= risque < hi
        if r == "bas_bande":
            x = f.get("depuis_min")
            if x is None or x != x:
                return False
            lo, hi = self._bande()
            return float(x) <= 1e-9 and lo <= risque < hi
        if r == "bas":
            x = f.get("depuis_min")
            if x is None or x != x:
                return False
            return float(x) <= 1e-9
        if r == "gd_suiveur":
            return self._gd_a_dit_oui(pair)
        log.warning("modele_rapide: regle inconnue '%s' — aucun achat", r)
        return False

    # ------------------------------------------------------------- suiveur G+D

    def _gd_a_dit_oui(self, pair: str | None) -> bool:
        """La regle `G+D` : on EXECUTE ce que le carnet papier `papier_gd_direct` a decide.

        POURQUOI SUIVRE ET NE PAS REIMPLEMENTER. G+D demande trois conditions -- acheteurs uniques
        avant 45 s <= 74, coffre (SOL + reserve virtuelle) < 100 SOL, tendance > 0 -- et ce moteur
        n en calcule AUCUNE : ses variables de decision n ont ni la foule, ni le coffre en SOL, ni la
        tendance. Les reimplementer voudrait dire refaire le compteur d acheteurs uniques, celui qui
        est FAUX tant qu on ne resout pas le saut de routeur dans le bloc -- 98 % des sorties du pool
        vont a un routeur. On deploierait alors une regle DIFFERENTE de celle mesuree, l erreur exacte
        du 22/09 sur le cout de la pause (trois achats de nuit hors regle, -15,69 EUR).

        `papier_gd_direct.py` fait deja tout cela EN DIRECT a 45 s -- l appel RPC compris -- et ecrit
        sa ligne. On lit sa decision : la regle executee est la sienne par construction. C est le meme
        procede que `pause_ouverte`, qui lit deja le carnet papier de la bande.

        CE QU ON NE FAIT PAS : on ne lit QUE `pris=1`. Un ticket que son carnet a ecarte -- pour la
        foule, le coffre, la tendance, sa propre pause ou l executabilite -- n est pas achete ici.

        FRAICHEUR. Si le processus papier est mort, sa table se fige et le suiveur ne trouverait plus
        rien -- il n acheterait donc rien, ce qui est le bon comportement par defaut. On verifie en
        plus que sa DERNIERE ligne est recente : une table qui ne bouge plus doit faire taire le
        suiveur, jamais le faire acheter a l aveugle (meme raison que `pause_fraicheur`).
        """
        if not pair:
            return False
        import sqlite3 as _sq  # noqa: PLC0415
        from intel.utils.timeutil import now_ts  # noqa: PLC0415
        chemin = str(self._cfg("gd_db", "/app/db/papier_gd.sqlite"))
        try:
            cn = _sq.connect("file:%s?mode=ro" % chemin, uri=True, timeout=5)
            try:
                dernier = cn.execute("SELECT MAX(t_dec) FROM decision").fetchone()[0]
                if dernier is None:
                    return False
                if now_ts() - float(dernier) > float(self._cfg("gd_fraicheur", 900.0)):
                    log.warning("suiveur G+D: carnet papier fige depuis %.0f s — aucun achat",
                                now_ts() - float(dernier))
                    return False
                ligne = cn.execute(
                    "SELECT 1 FROM decision WHERE pair = ? AND pris = 1 LIMIT 1",
                    (str(pair),)).fetchone()
                return ligne is not None
            finally:
                cn.close()
        except Exception as e:  # noqa: BLE001
            # ON N ACHETE PAS quand on ne sait pas. Un `except` qui rendrait True ferait acheter
            # TOUT ce qui passe des que la base est illisible -- l erreur corrigee sur la pause.
            log.warning("suiveur G+D: carnet papier illisible (%s) — aucun achat", e)
            return False

    def _mint_deja_en_prod(self, mint: str) -> bool:
        """VRAI si la production tient deja ce jeton. Le suiveur CEDE alors le ticket.

        POURQUOI. Le P&L se lit sur le SOLDE DU PORTEFEUILLE : un jeton, une ligne. Deux instances
        qui achetent le meme mint rendent les deux comptabilites inattribuables. Et le recouvrement
        n est pas rare : **79 % des jetons de G+D sont dans la bande 0,20-0,35** (218 sur 276 dont on
        connait le score), soit ~4 collisions par jour a l observe du 25/09.

        C EST LE SUIVEUR QUI CEDE, jamais la production : celle-ci n a pas ete modifiee d une ligne.
        Le ticket cede est enregistre avec son propre statut, pour qu on puisse chiffrer ce qu il
        aurait rapporte au lieu de le perdre de vue.
        """
        if self.table == "mr_lignes":
            return False                      # la production, elle, ne cede a personne
        r = self._base.query(
            "SELECT 1 FROM mr_lignes WHERE mint = ? AND statut IN"
            " ('OUVERTE','ATTENTE','FERMEE') AND tx_achat IS NOT NULL LIMIT 1", (str(mint),))
        return bool(r)

    # ---------------------------------------------------------------- frein

    def pause_ouverte(self, now: float) -> bool:
        """LA PAUSE DE `BANDE + PAUSE` : on n achete pas dans les 30 min qui suivent une cloture
        sous -30 % DANS LA BANDE. True si l on peut acheter.

        POURQUOI LA SOURCE EST LE CARNET PAPIER, et pas nos propres tickets. La regle mesuree se
        declenche sur le flux ENTIER de la bande -- `appliquer_pause` empile TOUS les tickets de
        bande dans sa file d attente, y compris ceux qu elle a elle-meme ecartes. Un moteur qui ne
        regarderait que ses propres achats verrait moins de clotures, se releverait plus souvent et
        prendrait plus de tickets que ce qui a ete mesure : ce ne serait plus la meme regle. C est
        aussi le piege du BLOCAGE CIRCULAIRE deja constate sur le frein le 18/09 (10 jetons refuses
        sur 12, la fenetre ne pouvant plus bouger).

        CAUSALITE. Le blocage part de la CLOTURE du perdant (t_dec + 242 s), pas de son ouverture :
        c est a ce moment-la qu on apprend la perte. Reagir a l ouverture serait lire l avenir.

        EN CAS DE DOUTE ON LAISSE PASSER -- table illisible, pas d historique : la pause s ouvre.
        Un garde-fou qui bloque quand il ne sait pas finit par tout bloquer en silence.
        """
        if not bool(self._cfg("pause_enabled", False)):
            return True
        import sqlite3 as _sq
        duree = float(self._cfg("pause_secondes", 1800.0))
        seuil = float(self._cfg("pause_seuil", -0.30))
        # LE COUT AVEC LEQUEL ON JUGE « -30 % ». On n utilise PLUS `d.cout_reduit` : cette colonne
        # vaut 1,54 % en moyenne alors que le peage MESURE sur l argent reel est de 3,88 % (404
        # tickets). Un jeton qui a vraiment perdu 32 % apparaissait donc a -29,7 % et ne declenchait
        # pas la pause. Constate le 22/09 : trois achats de nuit que la regle correctement chiffree
        # refusait, -15,69 EUR. La pause deployee etait plus permissive que la pause mesuree -- donc
        # les tickets qu on accumulait ne jugeaient pas la bonne regle.
        #
        # On recompose le cout comme le fait la table de reference : une part FIXE (frais de
        # protocole, priorite, reseau) plus l IMPACT sur le pool, qui depend du coffre `q`. La part
        # fixe est calee pour que la moyenne retombe sur les 3,88 % mesures a 10 EUR de mise.
        fixe = float(self._cfg("pause_cout_fixe", 0.03705))
        mise = float(self._cfg("mise_eur", 10.0))
        k = 2.0 * (mise * 0.31 / 30.0)          # coefficient d impact, en SOL par unite de coffre
        try:
            cn = _sq.connect("file:%s?mode=ro" % self._cfg("combo_db", COMBO_DB), uri=True, timeout=5)
            try:
                # LE CARNET PAPIER EST-IL VIVANT ? Si `papier_combo` n ecrit plus, la fenetre se vide
                # et la requete ci-dessous ne trouve AUCUNE cloture -- ce que l ancien code lisait
                # comme « rien ne s est effondre, on peut acheter ». La pause disparaissait donc
                # exactement pendant les pannes. Le 21/09 la coupure Helius a dure 102 minutes.
                # On distingue les deux cas : une source MUETTE bloque, une source VIVANTE sans
                # cloture autorise. C est l absence d information qui bloque, pas l absence de perte.
                dernier = cn.execute("SELECT MAX(t_dec) FROM decision").fetchone()[0]
                if dernier is None or now - float(dernier) > float(self._cfg("pause_fraicheur", 900.0)):
                    log.warning("modele_rapide: PAUSE — le carnet papier n a rien ecrit depuis "
                                "%.0f min, on ne sait pas : on n achete pas",
                                (now - float(dernier)) / 60 if dernier is not None else -1)
                    return False
                # les tickets de BANDE dont la sortie est tombee dans la fenetre de pause
                lignes = cn.execute(
                    "SELECT MIN(i.brut_240 - (? + ? / (COALESCE(d.q, 0) + ?)))"
                    " FROM decision d JOIN issue i"
                    " ON i.pair = d.pair WHERE d.eligible = 1 AND i.brut_240 IS NOT NULL"
                    " AND d.risque IS NOT NULL AND d.risque >= ? AND d.risque < ?"
                    " AND d.t_dec + ? > ? AND d.t_dec + ? <= ?",
                    (fixe, k, V_RESERVE, self._bande()[0], self._bande()[1],
                     TENUE_S, now - duree, TENUE_S, now)).fetchone()
            finally:
                cn.close()
        except Exception as exc:  # noqa: BLE001
            # UNE SOURCE ILLISIBLE BLOQUE, ELLE N AUTORISE PLUS. Meme raison que ci-dessus : ne pas
            # savoir n est pas une raison d acheter. Le risque inverse -- tout bloquer en silence --
            # est couvert par l alerte : cette ligne est en WARNING et le compteur de tickets
            # s arrete, ce qui se voit.
            log.warning("modele_rapide: PAUSE — carnet papier illisible (%s), on n achete pas",
                        str(exc)[:80])
            return False
        pire = lignes[0] if lignes else None
        if pire is not None and float(pire) <= seuil:
            log.info("modele_rapide: PAUSE — une cloture a %.1f %% dans les %.0f dernieres minutes",
                     100 * float(pire), duree / 60)
            return False
        return True

    def frein_ouvert(self, now: float) -> bool:
        """Le marche autorise-t-il d acheter ? True si le frein ne s applique pas.

        LE FREIN NE CHOISIT PAS LES JETONS : il suspend les ACHATS quand les `frein_fenetre`
        derniers tickets CLOTURES ont majoritairement perdu. C est le seul signal du projet qui
        porte sur le MARCHE et non sur le jeton, et le seul qui survive hors echantillon au retrait
        de ses trois meilleurs tickets :

            hors echantillon (458 tickets)      net      sans ses 3 meilleurs
            sans frein                        +0,54 %          -0,82 %
            AVEC frein                        +2,27 %          +0,55 %

        L effet tient de 10 a 50 de fenetre (+1,63 a +2,27 %) : c est une colline, pas un pic, donc
        la valeur exacte de la fenetre importe peu. Journal §3.121.

        CAUSALITE, le point critique : un ticket decide a t ne rend son resultat qu a t+240 s. On ne
        compte donc QUE les tickets dont la SORTIE est passee. Compter un ticket encore ouvert
        reviendrait a lire l avenir -- c est ce qui a fabrique de faux regimes plus tot dans ce
        projet.

        EN CAS DE DOUTE, ON LAISSE PASSER. Trop peu d historique, table illisible : le frein s ouvre.
        Un garde-fou qui bloque quand il ne sait pas finirait par tout bloquer en silence.
        """
        if not bool(self._cfg("frein_enabled", True)):
            return True
        fen = int(self._cfg("frein_fenetre", 20))
        seuil = float(self._cfg("frein_seuil", 0.50))
        # LA SOURCE EST LE CARNET PAPIER, PAS LE CARNET REEL. Deux raisons, toutes deux mesurees.
        #
        # 1. BLOCAGE CIRCULAIRE. Lu sur `mr_lignes`, le frein se nourrit de ses propres decisions :
        #    pour se rouvrir il faut un nouveau ticket gagnant, mais pour avoir un ticket il faut
        #    qu il s ouvre. Constate en production le 18/09 -- 10 jetons refuses sur 12 en une
        #    demi-heure, et la fenetre ne pouvait plus jamais bouger. Le carnet papier, lui, decide
        #    en continu qu on achete ou non.
        #
        # 2. UNE SOURCE CLAIRSEMEE TUE LE FREIN. Mesure hors echantillon, en sous-echantillonnant
        #    le papier a la densite du reel (1 ticket sur 10) :
        #        source dense,      20 derniers : +1,77 %  (sans 3 best +0,05)
        #        source clairsemee, 20 derniers : +0,27 %  (sans 3 best -1,06) = AUCUN FREIN
        #    Faute d historique suffisant il ne se prononce jamais et laisse tout passer.
        #
        # C est aussi la source sur laquelle le frein a ete MESURE et GELE, donc la seule qui soit
        # fidele a ce qu on a valide. Une fenetre en TEMPS a ete testee et fait moins bien
        # (+1,34 % au mieux, negative sans ses trois meilleurs) : l intuition d elegance etait
        # fausse, la mesure tranche.
        # Connexion SEPAREE et en LECTURE SEULE : on ne touche pas au handle du moteur, et le
        # carnet papier ne doit jamais pouvoir etre ecrit depuis ici.
        import sqlite3 as _sq
        try:
            cn = _sq.connect("file:%s?mode=ro" % self._cfg("combo_db", COMBO_DB), uri=True, timeout=5)
            lignes = cn.execute(
                "SELECT i.brut_240 FROM decision d JOIN issue i ON i.pair = d.pair"
                " WHERE d.eligible = 1 AND i.brut_240 IS NOT NULL AND d.risque IS NOT NULL"
                " AND d.risque <= ? AND d.t_dec + ? <= ?"
                " ORDER BY d.t_dec DESC LIMIT ?",
                (self._seuil(), self._tenue(), now, fen)).fetchall()
            cn.close()
        except Exception as exc:  # noqa: BLE001
            log.warning("modele_rapide: frein illisible (%s) — on laisse passer", str(exc)[:80])
            return True
        if len(lignes) < fen:
            return True                     # pas encore assez d historique : on n invente pas
        gagnants = sum(1 for r in lignes if float(r[0] or 0) - COUT_MESURE > 0)
        ouvert = (gagnants / fen) > seuil
        if not ouvert:
            log.info("modele_rapide: FREIN ferme — %d gagnants sur les %d derniers (seuil %.0f %%)",
                     gagnants, fen, 100 * seuil)
        return ouvert

    # ---------------------------------------------------------------- schema

    def _schema(self) -> None:
        self._x(
            "CREATE TABLE IF NOT EXISTS mr_lignes("
            "  mint TEXT PRIMARY KEY, pair TEXT, symbole TEXT, mode TEXT, statut TEXT,"
            "  naissance REAL, t_dec REAL, risque REAL, depuis_min REAL, q REAL,"
            "  ts_entree INTEGER, prix_entree REAL, mise_eur REAL, tx_achat TEXT,"
            "  ts_sortie INTEGER, prix_sortie REAL, tx_vente TEXT, gain_eur REAL,"
            "  motif TEXT, variables TEXT)")
        self._x("CREATE INDEX IF NOT EXISTS i_mr_statut ON mr_lignes(statut)")
        # `impact_annonce` : ce que le routeur annonce AVANT l achat (`priceImpactPct`). Ajoute le
        # 19/09 a 22h sur une table qui existait deja, donc par ALTER et non dans le CREATE : les
        # lignes anterieures restent a NULL, ce qui est exact -- on ne l enregistrait pas.
        try:
            self._x("ALTER TABLE mr_lignes ADD COLUMN impact_annonce REAL")
        except Exception:  # noqa: BLE001
            pass                                  # la colonne existe deja

    # ---------------------------------------------------------------- cycle

    async def cycle(self) -> dict[str, Any]:
        from intel.utils.timeutil import now_ts

        self._schema()
        now = now_ts()
        live = str(self._cfg("mode", "paper")).lower() == "live"
        mise = float(self._cfg("mise_eur", 20.0))

        # --- plafonds, verifies AVANT toute decision -------------------------
        jour = self._q(
            "SELECT COUNT(*) n, COALESCE(SUM(gain_eur), 0) g FROM mr_lignes"
            " WHERE mode='live' AND ts_entree >= ?", (now - 86400,))
        n_jour = int(jour[0]["n"] or 0) if jour else 0
        perte_jour = float(jour[0]["g"] or 0.0) if jour else 0.0
        # `max_ordres_jour: 0` DESACTIVE le plafond en nombre d ordres. J en avais impose un a 40
        # sans que l operateur l ait demande, et il a arrete le carnet en pleine journee alors
        # qu il venait de dire de laisser tourner. Ce qu il a accepte, c est un BUDGET.
        max_jour = int(self._cfg("max_ordres_jour", 0))
        perte_max = float(self._cfg("max_perte_jour_eur", 150.0))
        bloque = live and ((max_jour > 0 and n_jour >= max_jour) or perte_jour <= -perte_max)
        if bloque:
            log.info("modele_rapide: plafond atteint (%d ordres, %+.0f EUR) — plus d achat aujourd'hui",
                     n_jour, perte_jour)

        modele = self._charge_modele()
        age_dec = self._age()
        traits75 = bool(self._cfg("traits_75", False))
        fenetre = int(self._cfg("fenetre_minutes", 15))
        lancements = sorted(float(r["ts"]) for r in self._q(
            "SELECT ts FROM solana_stream_launches WHERE ts > ?", (now - 3600,)))

        # --- ce qui est encore decidable ------------------------------------
        deja = {str(r["mint"]) for r in self._q("SELECT mint FROM mr_lignes")}
        pools = self._q(
            "SELECT pair_id, mint, MIN(ts - age_s) AS naissance, MAX(age_s) AS age"
            " FROM solana_prix_chaine WHERE ts > ? GROUP BY pair_id", (now - fenetre * 60,))
        decides = achetes = 0
        for p in pools:
            mint = str(p["mint"] or "")
            if not mint or mint in deja or (p["age"] or 0) < age_dec + EXEC_S:
                continue
            # LA FIN DE LA FENETRE D ENTREE. 120 s pour la production, qui n a pas de contrainte sur
            # l age d entree. Le SUIVEUR G+D en a une, et elle est chiffree : sa regle gelee entre
            # « au plus tot 47 s, au plus tard 55 s », parce qu entrer a 65 s au lieu de 47 coute
            # **-3,65 points par ticket** (mesure appariee sur 306 pools, 16/09) -- tout l avantage.
            # Or on ne peut PAS garantir d avoir vu la decision du carnet papier a 47 s : `t_dec` y
            # est un age NOMINAL (naissance + 45), pas un instant d ecriture, et son appel RPC pour
            # compter la foule ajoute un delai qui n est stocke nulle part. On ne parie donc pas sur
            # la course : on borne la fenetre, et un ticket arrive trop tard est PERDU, pas achete.
            if (p["age"] or 0) > age_dec + EXEC_S + float(self._cfg("fenetre_entree_s", 120)):
                continue                     # trop tard : la fenetre d entree est passee
            lect = self._q(
                "SELECT age_s, prix_sol, reserve_sol, reserve_base, reserve_virtuelle"
                " FROM solana_prix_chaine WHERE pair_id = ? ORDER BY age_s", (p["pair_id"],))
            pts = [(float(r["age_s"] or 0), float(r["prix_sol"] or 0), float(r["reserve_sol"] or 0),
                    float(r["reserve_base"] or 0), float(r["reserve_virtuelle"] or 0))
                   for r in lect if (r["prix_sol"] or 0) > 0]
            if len(pts) < 3:
                continue
            f = self._variables(pts, float(p["naissance"] or 0), lancements,
                                age_entree=age_dec + EXEC_S)
            if f is None:
                continue
            if traits75:
                # LE MODELE 75s ATTEND 25 VARIABLES, dont `risque` -- la sortie du modele de
                # vidage -- et 15 de flux d ordres qu il faut aller chercher sur la chaine.
                # `variables()` rend None si le flux est illisible : on ne decide alors PAS,
                # plutot que de decider sur des medianes en croyant suivre un modele.
                f = self._traits75().variables(
                    f, float(self._charge_risque().probabilite(f)), str(p["pair_id"]), mint,
                    float(p["naissance"] or 0), float(pts[-1][4] or 0))
                if f is None:
                    continue
            risque = float(modele.probabilite(f))
            decides += 1
            garde = self.retenu(f, risque, pair=str(p["pair_id"]))
            deja.add(mint)
            # LE SUIVEUR CEDE LE JETON QUE LA PRODUCTION TIENT DEJA (un jeton, une ligne). Place
            # APRES `retenu` pour que le statut distingue « la regle n en voulait pas » de « la regle
            # en voulait mais la prod l avait deja » -- sans quoi on ne pourrait pas chiffrer le cout
            # de la cession. Non-operant pour la production, qui ne cede a personne.
            if garde and self._mint_deja_en_prod(mint):
                self._x(
                    "INSERT OR IGNORE INTO mr_lignes(mint, pair, mode, statut, naissance, t_dec,"
                    " risque, depuis_min, q, motif, variables) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (mint, str(p["pair_id"]), "live" if live else "paper", "CEDEE",
                     float(p["naissance"] or 0), now, risque, f.get("depuis_min"), f.get("q"),
                     "jeton deja tenu par la production", json.dumps(f, default=str)))
                continue
            if not garde:
                self._x(
                    "INSERT OR IGNORE INTO mr_lignes(mint, pair, mode, statut, naissance, t_dec,"
                    " risque, depuis_min, q, variables) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (mint, str(p["pair_id"]), "live" if live else "paper", "ECARTEE",
                     float(p["naissance"] or 0), now, risque, f.get("depuis_min"), f.get("q"),
                     json.dumps(f, default=str)))
                continue
            # UN TICKET BLOQUE PAR LE PLAFOND NE DOIT PAS COMPTER COMME UN ORDRE. Sinon la ligne
            # est enregistree avec un `ts_entree`, le plafond la compte au cycle suivant, et il se
            # verrouille TOUT SEUL de plus en plus : les fantomes entrent dans la fenetre glissante
            # plus vite que les vrais ordres n en sortent, donc la reprise du lendemain n arrive
            # jamais. Constate en production le 18/09 -- 40 ordres reels mais 46 comptes en une
            # demi-heure. Ces lignes restaient en outre OUVERTE pour toujours, `_sortir` exigeant
            # un `tx_achat`. On les enregistre donc comme BLOQUEE, sans `ts_entree`, ce qui garde
            # la trace de la decision sans polluer ni le compteur ni le carnet.
            # LE FREIN EST EVALUE ICI, pas dans `retenu` : il ne choisit pas le jeton, il suspend
            # l achat. Un ticket refuse par le frein garde donc sa trace avec son statut propre --
            # on saura combien il en a ecartes et ce qu ils auraient donne.
            # LA PAUSE AVANT LE FREIN : elle s applique aussi en PAPIER, contrairement au frein.
            # Le frein est un garde-fou de production ; la pause est une PARTIE DE LA REGLE -- un
            # carnet papier qui l ignorerait ne mesurerait pas `BANDE + PAUSE` mais la bande seule,
            # et les deux different de 755 EUR sur leur histoire.
            if not self.pause_ouverte(now):
                self._x(
                    "INSERT OR IGNORE INTO mr_lignes(mint, pair, mode, statut, naissance, t_dec,"
                    " risque, depuis_min, q, motif, variables) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (mint, str(p["pair_id"]), "live" if live else "paper", "PAUSE",
                     float(p["naissance"] or 0), now, risque, f.get("depuis_min"), f.get("q"),
                     "pause apres une cloture sous -30 % dans la bande", json.dumps(f, default=str)))
                continue
            if live and not bloque and not self.frein_ouvert(now):
                self._x(
                    "INSERT OR IGNORE INTO mr_lignes(mint, pair, mode, statut, naissance, t_dec,"
                    " risque, depuis_min, q, motif, variables) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (mint, str(p["pair_id"]), "live", "FREIN",
                     float(p["naissance"] or 0), now, risque, f.get("depuis_min"), f.get("q"),
                     "frein du marche ferme", json.dumps(f, default=str)))
                continue
            if live and bloque:
                self._x(
                    "INSERT OR IGNORE INTO mr_lignes(mint, pair, mode, statut, naissance, t_dec,"
                    " risque, depuis_min, q, motif, variables) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (mint, str(p["pair_id"]), "live", "BLOQUEE",
                     float(p["naissance"] or 0), now, risque, f.get("depuis_min"), f.get("q"),
                     "plafond journalier atteint", json.dumps(f, default=str)))
                continue
            e = _a_age([x[0] for x in pts], A + EXEC_S, 6)
            prix_e = pts[e][1] if e is not None else pts[-1][1]
            self._x(
                "INSERT OR IGNORE INTO mr_lignes(mint, pair, mode, statut, naissance, t_dec,"
                " risque, depuis_min, q, ts_entree, prix_entree, mise_eur, variables)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (mint, str(p["pair_id"]), "live" if live else "paper", "OUVERTE",
                 float(p["naissance"] or 0), now, risque, f.get("depuis_min"), f.get("q"),
                 now, prix_e, mise, json.dumps(f, default=str)))
            achetes += 1
            if live:
                # `prix_e` est le prix du pool que NOUS avons lu, pas une promesse du routeur :
                # c est lui qui permet de refuser une cotation trop chere (voir `_acheter_reel`).
                await self._acheter_reel(mint, mise, f, risque, prix_e)
        # VENDRE ET COMPTER NE SONT JAMAIS BLOQUES. Un plafond doit arreter les ACHATS, jamais les
        # ventes : sinon atteindre 40 ordres laisserait les positions ouvertes indefiniment, sans
        # personne pour les fermer. Le plafond protege du risque, il ne doit pas en creer un.
        #
        # ET PAS DAVANTAGE PAR LE MODE. `_sortir` et `_compter` filtrent DEJA `mode='live'` dans
        # leur propre SQL : les conditionner EN PLUS au mode du moment a laisse, le 20/09 a 19h30,
        # deux positions REELLES achetees onze minutes plus tot sans personne pour les vendre --
        # quatorze heures de detention sur une regle qui tient 240 s, et aucun comptage, donc ni
        # P&L ni plafond de perte. Un basculement en papier doit arreter les ACHATS ; il ne doit
        # jamais abandonner l argent deja engage. On entretient donc les lignes reelles tant qu il
        # en reste, quel que soit le mode affiche.
        reste = self._q(
            "SELECT COUNT(*) n FROM mr_lignes WHERE mode='live' AND tx_achat IS NOT NULL"
            " AND (statut IN ('OUVERTE','ATTENTE')"
            "      OR (statut='FERMEE' AND gain_eur IS NULL AND ts_sortie >= ?))",
            (now - 6 * 3600,))
        if live or (int(reste[0]["n"] or 0) if reste else 0):
            # CONFIRMER AVANT DE VENDRE : une ligne encore en ATTENTE n est pas OUVERTE, donc
            # `_sortir` ne la verrait pas. Si la chaine a dit oui pendant les 240 s de tenue, elle
            # doit etre passee en OUVERTE avant que la vente ne cherche qui sortir.
            await self._confirmer(now)
            await self._sortir(now)
            await self._compter(now)
        return {"status": "ok", "decides": decides, "retenus": achetes, "mode": "live" if live else "paper"}

    # ---------------------------------------------------------------- reel

    def _decimales(self, mint: str) -> int:
        """Les decimales du jeton, lues en base ; 6 par defaut (le standard pump.fun).

        Elles servent a convertir la cotation en prix par jeton pour la comparer au prix du pool.
        Se tromper ici deplacerait la comparaison d un facteur 10 et ferait refuser tout ou rien,
        donc on prefere la valeur ENREGISTREE quand elle existe.
        """
        try:
            r = self._q("SELECT decimales FROM mint_offre WHERE mint = ? LIMIT 1", (mint,))
            if r and r[0]["decimales"] is not None:
                return int(r[0]["decimales"])
        except Exception:  # noqa: BLE001
            pass
        return 6

    async def _acheter_reel(self, mint: str, mise: float, f: dict, risque: float,
                            prix_pool: float = 0.0) -> None:
        """Envoie l ordre. Toute erreur ferme la ligne : on ne garde jamais une position fantome."""
        from intel.execution import solana as sol
        cle = self._cfg("cle_fichier", None)
        rpc, proprio = sol.rpc_url(), sol.signer_address(cle)
        if not rpc or not proprio:
            log.warning("modele_rapide: mode live mais aucune cle — aucun ordre envoye")
            self._x("UPDATE mr_lignes SET statut='ANNULEE', motif=? WHERE mint=?",
                                ("aucune cle", mint))
            return
        # LE TAUX SE LIT SUR LE MARCHE, JAMAIS EN DUR. Le 08/09 le carnet supposait 180 EUR/SOL
        # alors qu il valait 96 : un ticket annonce a 5 EUR en engageait 2,67, et tous les gains
        # etaient rapportes 88 % trop haut. `sol_eur` lit le marche et met en cache quelques minutes.
        try:
            taux = await sol.sol_eur(self.client)
        except Exception:  # noqa: BLE001
            log.warning("modele_rapide: taux SOL illisible — achat reporte plutot que mal dimensionne")
            self._x("UPDATE mr_lignes SET statut='ANNULEE', motif=? WHERE mint=?",
                                ("taux SOL illisible", mint))
            return
        try:
            tx = await sol.prepare_buy(
                self.client, mint=mint, size_eur=mise,
                sol_eur=taux,
                slippage_pct=float(self._cfg("slippage_achat_pct", 20.0)),
                max_impact_pct=float(self._cfg("max_impact_pct", 15.0)),
                # ================================================================================
                # 19/09 20h50, accord de Mido : LES DEUX GARDES D ENTREE, ENFIN BRANCHES.
                # Ils existaient depuis le 14/09, mesures positifs, passes par `telegram_rapide` --
                # et ce moteur-ci, celui qui engage l argent, ne les passait pas. Leurs valeurs par
                # defaut dans `prepare_buy` valent 0, c est-a-dire DESACTIVE : on a donc achete
                # trois mois sans aucun des deux.
                #
                # POURQUOI MAINTENANT. La dissection du cout ce soir (§3.156) : le marche donne
                # +2,68 %/ticket, l execution en prend 3,71 %. Il manque UN point. Ces deux gardes
                # attaquent exactement les deux facons de perdre a l ACHAT.
                #
                # 1. ECART A LA COTATION. Le routeur cote parfois bien au-dessus du pool. Mesure du
                #    14/09, 60 tickets : ecart median +5,8 %, p90 +32,8 %, max +74 % -- et les trois
                #    plus grosses pertes du jour etaient des achats payes 28 a 59 % trop cher.
                #        sans plafond   0 % refuses   -52,58 EUR
                #        plus de 20 %  18 % refuses  +130,02 EUR  <- retenu
                #        plus de 10 %  40 % refuses   -54,25 EUR  (jette trop)
                #    Ne coute AUCUN appel : `prix_pool` est le prix que le collecteur a deja lu.
                # 2. PEUT-ON RESSORTIR ? On cote la revente AVANT d acheter. Mesure du 09/09 sur
                #    25 pools : 5 sont invendables a notre taille et causent 25 % des tickets
                #    aneantis. L impact affiche ne suffit pas -- il est symetrique en moyenne, et
                #    c est sur les pools asymetriques qu il ne dit rien. Coute une cotation.
                #
                # CRITERE D ARRET, FIXE AVANT : on debranche si a 200 tickets reels le cout mesure
                # (`cout_registre.py`) n a pas baisse d au moins 0,5 point. Pas de renegociation.
                # ================================================================================
                prix_pool_sol=float(prix_pool or 0.0),
                decimales=int(self._decimales(mint)),
                max_ecart_pool_pct=float(self._cfg("max_ecart_pool_pct", 20.0)),
                max_aller_retour_pct=float(self._cfg("max_aller_retour_pct", 15.0)),
                # PRIORITE D ACHAT, distincte de celle de la vente depuis le 19/09 (§3.153). Un
                # achat rate ne coute RIEN -- on ne prend pas le ticket. Une vente ratee laisse une
                # position ouverte sur un jeton qui s effondre, et on a mesure que garder aggrave
                # toujours. Les deux jambes n ont donc pas le meme prix acceptable.
                priorite_lamports=int(self.ctx.config.get(
                    "solana.priority_fee_lamports_achat",
                    self.ctx.config.get("solana.priority_fee_lamports", 0) or 0) or 0),
                proprietaire=proprio)
            if tx.get("status") != "BUILT" or not tx.get("tx"):
                raise RuntimeError(tx.get("refused_reason") or "transaction non assemblee")
            h = await sol.send(self.client, rpc, sol.sign(tx["tx"], cle))
            # L IMPACT ANNONCE PAR LE ROUTEUR, enregistre a partir du 19/09 22h. Il etait lu depuis
            # toujours et jete aussitot -- `prepare_buy` le renvoie sous le nom trompeur
            # `slippage_pct`, mais c est bien `priceImpactPct` de la cotation.
            #
            # POURQUOI IL COMPTE. La variable `cout` que le modele utilise est une FORMULE
            # (0,017 + 2.mise_SOL/(q+V)) : elle annonce 0,21 % en median quand le cout reel mesure
            # est de 3,29 %, et elle correle a r = +0,025 avec lui -- c est-a-dire pas du tout. Or
            # elle porte 21 % de l importance du modele en production : un cinquieme du modele
            # repose sur un chiffre faux. L impact du routeur, lui, annonce 2,65 % de median sur le
            # marche vivant, le bon ordre de grandeur, et il est connu AVANT d acheter.
            #
            # On l enregistre sans rien en faire pour l instant. Dans quelques jours on saura
            # comment il predit le cout reel, et on reglera les seuils SUR UNE MESURE au lieu de les
            # deviner -- et il deviendra une variable de modele, probablement meilleure que la
            # formule qu il remplacerait.
            try:
                self._x(
                    "UPDATE mr_lignes SET tx_achat=?, impact_annonce=? WHERE mint=?",
                    (h, float(tx.get("slippage_pct") or 0.0), mint))
            except Exception:  # noqa: BLE001
                self._x("UPDATE mr_lignes SET tx_achat=? WHERE mint=?", (h, mint))
            # ON N ANNONCE RIEN ENCORE. Une signature dit que la transaction est PARTIE, jamais
            # qu elle a abouti. Le 23/09 un achat est revenu avec sa signature, le carnet a ouvert
            # une ligne de 20 EUR et le telephone a recu un « achete » vert -- alors que la chaine
            # l avait rejetee (InstructionError Custom 6001, slippage). Les jetons sont partis a une
            # autre adresse, la ligne n a jamais pu etre ni vendue ni comptee, et Mido a cherche un
            # message de vente qui ne pouvait pas exister.
            #
            # La ligne reste donc en ATTENTE : `_confirmer` la passera en OUVERTE et previendra
            # quand la chaine aura dit oui, ou l ecrira ECHOUEE si elle dit non. `ts_entree` garde
            # l heure de l ACHAT, donc les 240 s de tenue courent depuis le bon instant.
            self._x("UPDATE mr_lignes SET statut='ATTENTE' WHERE mint=?", (mint,))
            log.info("modele_rapide: achat envoye %s — %s (en attente de la chaine)",
                     mint[:10], h[:16])
        except Exception as exc:  # noqa: BLE001
            self._x("UPDATE mr_lignes SET statut='ANNULEE', motif=? WHERE mint=?",
                                (str(exc)[:160], mint))
            log.warning("modele_rapide: achat refuse %s (%s)", mint[:10], str(exc)[:100])

    async def _confirmer(self, now: float) -> None:
        """La chaine a-t-elle accepte nos achats ? Tant qu elle n a pas repondu, rien n est vrai.

        Trois issues, et elles appellent trois gestes opposes :
          ok      -> la ligne s ouvre pour de bon, et C EST LA qu on previent.
          echec   -> la transaction a ete rejetee par le programme. Aucun jeton, aucun euro
                     engage (hors frais de reseau). La ligne est ECHOUEE et sa mise remise a
                     zero, sinon elle compterait comme un ordre dans les plafonds et dans le
                     nombre de tickets : le 23/09 le carnet annoncait 62 achats pour 61 reels.
          attente -> la chaine n a pas encore publie. On repasse au cycle suivant.

        LE DELAI EST PLAFONNE. Une transaction dont le blockhash a expire n arrive jamais et ne
        rend jamais d erreur non plus : sans plafond la ligne resterait ATTENTE pour toujours, et
        `_sortir` ne la verrait pas puisqu il ne regarde que les OUVERTE.
        """
        from intel.execution import solana as sol
        lignes = self._q(
            "SELECT mint, ts_entree, mise_eur, risque, q, tx_achat FROM mr_lignes"
            " WHERE mode='live' AND statut='ATTENTE' AND tx_achat IS NOT NULL")
        if not lignes:
            return
        rpc = sol.rpc_url()
        limite = float(self._cfg("confirmation_secondes", 90.0))
        for l in lignes:
            mint = str(l["mint"])
            age = now - float(l["ts_entree"] or now)
            etat = await sol.statut_tx(self.client, rpc, str(l["tx_achat"]))
            if etat == "attente":
                if age > limite:
                    self._x(
                        "UPDATE mr_lignes SET statut='ECHOUEE', mise_eur=0, ts_sortie=?, motif=?"
                        " WHERE mint=?", (now, "jamais confirmee apres %.0f s" % limite, mint))
                    log.warning("modele_rapide: achat %s jamais confirme apres %.0f s", mint[:10], limite)
                continue
            if etat == "echec":
                self._x(
                    "UPDATE mr_lignes SET statut='ECHOUEE', mise_eur=0, ts_sortie=?, motif=?"
                    " WHERE mint=?", (now, "rejetee par la chaine", mint))
                log.warning("modele_rapide: achat %s REJETE par la chaine", mint[:10])
                # Une alerte breve : l operateur a vu partir un ordre, il doit savoir qu il n a
                # pas eu lieu. Sans chiffre de cumul -- il n y a rien a cumuler.
                await self._prevenir(
                    "⚪ <b>%s…</b> achat <b>rejeté par la chaîne</b> — aucun jeton, aucun euro "
                    "engagé\n<i>slippage ou pool déplacé entre la cotation et la signature</i>"
                    % mint[:8])
                continue
            self._x("UPDATE mr_lignes SET statut='OUVERTE' WHERE mint=?", (mint,))
            log.info("modele_rapide: ACHAT confirme %s", mint[:10])
            await self._prevenir(
                "🟢 <b>%s…</b> acheté · <i>%s</i>\n"
                "%.2f EUR · risque %.3f · coffre %.0f SOL · revente dans %d min"
                % (mint[:8], self._cfg("nom_regle", "au plus bas + bande"),
                   float(l["mise_eur"] or 0), float(l["risque"] or 0), float(l["q"] or 0),
                   round(self._tenue() / 60)))

    def _gain_atteint(self, now: float) -> set[str]:
        """Les mints dont le prix du pool a touche `prise_gain_x` fois le prix d entree.

        VIDE POUR LA PRODUCTION, et il faut que ca reste vide : `BANDE + PAUSE` tient 240 s SANS
        stop ni prise de gain, et c est mesure -- sur la regle Telegram, tenir aveuglement donne
        +7,24 % par ticket, la prise de gain a +50 % le ramene a +5,10 %, le stop a +2,11 %, les deux
        a +0,62 %. Les deux reflexes coutent 6,6 points. Le defaut `prise_gain_x: 0` les desactive.

        POURQUOI LE SUIVEUR G+D EN A UNE, LUI. Sa regle gelee dit : « premiere lecture >= entree
        x 1,25, puis on vend a la lecture suivante ». Ce n est pas un detail de sa regle -- **148 de
        ses 294 sorties sont des prises de gain**, soit la moitie. Un suiveur qui tiendrait
        aveuglement 240 s executerait donc une AUTRE regle que celle mesuree sur la moitie de ses
        tickets. C est exactement l ecart qui a coute -15,69 EUR le 22/09 sur le cout de la pause.

        LE DECLENCHEUR EST LE PRIX DU POOL, comme dans le carnet papier -- pas une cotation du
        routeur : c est gratuit (la lecture existe deja) et c est le meme signal que celui qui a ete
        mesure. La cotation, elle, sert a la VENTE, une ligne plus bas.

        LE DELAI DE 2 s du carnet papier (« on vend a la lecture SUIVANTE ») est ici joue par la
        latence reelle -- cotation, signature, atterrissage -- qui depasse 2 s. Ce n est pas
        identique a la lettre, et c est note comme tel plutot que presente comme equivalent.
        """
        # `or 0.0` : une cle absente peut rendre None selon la source de config, et `float(None)`
        # leverait -- dans une methode appelee a chaque cycle de vente, une exception ici empecherait
        # de VENDRE. Le defaut desarme la prise de gain, jamais l inverse.
        x = float(self._cfg("prise_gain_x", 0.0) or 0.0)
        if x <= 1.0:
            return set()
        vus: set[str] = set()
        for l in self._q(
                "SELECT mint, pair, prix_entree, ts_entree FROM mr_lignes"
                " WHERE mode='live' AND statut='OUVERTE' AND tx_achat IS NOT NULL"
                " AND prix_entree > 0 AND ts_entree > ?", (now - self._tenue(),)):
            r = self._q(
                "SELECT MAX(prix_sol) p FROM solana_prix_chaine WHERE pair_id = ? AND ts >= ?",
                (str(l["pair"]), float(l["ts_entree"] or 0)))
            haut = float(r[0]["p"] or 0) if r else 0.0
            if haut >= x * float(l["prix_entree"]):
                vus.add(str(l["mint"]))
        return vus

    async def _sortir(self, now: float) -> None:
        """Vend tout ce qui a passe TENUE_S -- et, si `prise_gain_x` est arme, ce qui l a touche."""
        from intel.execution import solana as sol
        cle = self._cfg("cle_fichier", None)
        rpc, proprio = sol.rpc_url(), sol.signer_address(cle)
        gagnants = self._gain_atteint(now)
        a_vendre = list(self._q(
            "SELECT mint, ts_entree FROM mr_lignes WHERE mode='live' AND statut='OUVERTE'"
            " AND tx_achat IS NOT NULL AND ts_entree <= ?", (now - self._tenue(),)))
        if gagnants:
            vus = {str(l["mint"]) for l in a_vendre}
            a_vendre += [l for l in self._q(
                "SELECT mint, ts_entree FROM mr_lignes WHERE mode='live' AND statut='OUVERTE'"
                " AND tx_achat IS NOT NULL") if str(l["mint"]) in gagnants - vus]
        for l in a_vendre:
            mint = str(l["mint"])
            try:
                solde = await sol.token_balance(self.client, rpc, proprio, mint)
            except Exception as exc:  # noqa: BLE001
                await self._echec_vente(mint, "solde illisible : %s" % str(exc)[:60], now)
                continue
            if not solde:
                self._x("UPDATE mr_lignes SET statut='FERMEE', ts_sortie=?, motif=?"
                                    " WHERE mint=?", (now, "solde nul sur la chaine", l["mint"]))
                continue
            try:
                tx = await sol.prepare_sell(
                    self.client, mint=str(l["mint"]), amount=solde,
                    slippage_pct=float(self._cfg("slippage_vente_pct", 25.0)),
                    proprietaire=proprio,
                    priorite_lamports=int(self.ctx.config.get("solana.priority_fee_lamports", 0) or 0))
                if tx.get("status") != "BUILT" or not tx.get("tx"):
                    raise RuntimeError(tx.get("refused_reason") or "vente non assemblee")
                h = await sol.send(self.client, rpc, sol.sign(tx["tx"], cle))
                self._x(
                    "UPDATE mr_lignes SET statut='FERMEE', ts_sortie=?, tx_vente=?, motif=?"
                    " WHERE mint=?", (now, h, "sortie a %d s" % self._tenue(), l["mint"]))
                log.info("modele_rapide: VENTE %s — %s", str(l["mint"])[:10], h[:16])
                self._echecs.pop(mint, None)
                # PAS D ALERTE ICI. La vente vient de partir, son resultat n est pas encore lu sur
                # la chaine : un message a cet instant repeterait le cumul PRECEDENT et donnerait
                # l illusion que le ticket est compte deux fois -- c est exactement ce que
                # l operateur a vu sur son telephone. Un seul message porte un chiffre, celui du
                # comptage, et il arrive quelques secondes plus tard.
            except Exception as exc:  # noqa: BLE001
                await self._echec_vente(mint, str(exc)[:80], now)

    # ---------------------------------------------------------------- alertes

    async def _prevenir(self, texte: str, critique: bool = False) -> None:
        """Le canal de CE carnet, jamais celui de l ancien.

        Demande de l operateur au moment du passage en reel : « remets a zero les messages Telegram
        pour qu on ne soit pas pollue par l ancien P&L de l ancien bot ». La separation n est pas un
        reglage qu on pourrait oublier de mettre a jour : ce module ne LIT que `mr_lignes`, donc un
        chiffre de l ancien carnet ne peut pas y entrer, meme par erreur.
        """
        if not critique and not bool(self._cfg("alertes", True)):
            return
        # QUAND DEUX INSTANCES PARLENT DANS LE MEME CANAL, IL FAUT SAVOIR LAQUELLE. Sans cette
        # etiquette le suiveur G+D et la production enverraient des messages identiques et un 🟢
        # serait inattribuable -- or c est sur ces messages que l operateur suit son argent.
        etiq = self._cfg("etiquette", None)
        if etiq:
            texte = "%s %s" % (etiq, texte)
        from intel.alerts.telegram import TelegramSender
        try:
            await TelegramSender(
                self.ctx.settings,
                chat_id=self._cfg("canal", self.ctx.config.get("telegram_rapide.canal", None)),
                token=self._jeton()).send(texte)
        except Exception as exc:  # noqa: BLE001
            log.info("modele_rapide: alerte non envoyee (%s)", str(exc)[:80])

    def _jeton(self) -> str | None:
        import os
        var = self._cfg("jeton_variable", self.ctx.config.get("telegram_rapide.jeton_variable", None))
        if var:
            v = (os.environ.get(str(var)) or "").strip()
            if v:
                return v
        return None

    def _cumul(self) -> str:
        """Le cumul de LA METHODE EN SERVICE, lu sur `mr_lignes`.

        Une ligne dont le resultat n est pas encore lu sur la chaine n entre pas dans le total,
        plutot que d y entrer a zero.

        LE TOTAL REPART A LA MISE EN SERVICE D UNE METHODE, il ne cumule pas depuis le 18/09.
        Mido, 21/09 : « t as pas remis a 0 le message Telegram, on a toujours les chiffres anciens
        256 / 658 -- remets les chiffres a partir qu on a mis en place la nouvelle strat ». Il a
        raison et ce n est pas cosmetique : additionner `BANDE + PAUSE` avec les 650 tickets des
        regles qui l ont precedee -- dont `FORET REENTRAINEE 6h`, qui a perdu 45,75 EUR en une
        heure -- rend le chiffre du telephone incapable de dire si ce qui tourne AUJOURD HUI
        gagne. C est le meme defaut de lecture que le P&L en 24 h glissantes.

        `cumul_depuis` est l instant (epoch) de la mise en service. A CHANGER en meme temps que la
        methode, jamais separement : le total doit toujours porter sur UNE regle. Zero = tout
        l historique, comme avant.
        """
        depuis = float(self._cfg("cumul_depuis", 0) or 0)
        # LE DEBUT DU JOUR CALENDAIRE, heure de Paris. Mido, 20/09 : « t as un modele en test qui
        # fait +50 et tu preferes garder celui qui fait +10 ? » -- le P&L en 24 H GLISSANTES
        # masquait la tendance du jour. Depuis, tout compte rendu part du jour calendaire.
        # ET ON LIT LE VRAI FUSEAU, pas un « +2 » en dur : fin octobre Paris passe a +1, et une
        # journee decalee d une heure ferait compter des tickets de la veille dans le jour.
        import datetime as _dt
        try:
            from zoneinfo import ZoneInfo
            _tz = ZoneInfo("Europe/Paris")
        except Exception:  # noqa: BLE001
            _tz = _dt.timezone(_dt.timedelta(hours=2))
        _minuit = _dt.datetime.now(_tz).replace(hour=0, minute=0, second=0,
                                                microsecond=0).timestamp()
        try:
            r = self._q(
                "SELECT COUNT(*) n, COALESCE(SUM(gain_eur),0) g, COALESCE(SUM(mise_eur),0) m,"
                " SUM(CASE WHEN gain_eur > 0 THEN 1 ELSE 0 END) w FROM mr_lignes"
                " WHERE mode='live' AND gain_eur IS NOT NULL AND ts_entree >= ?", (depuis,))
            j = self._q(
                "SELECT COUNT(*) n, COALESCE(SUM(gain_eur),0) g, COALESCE(SUM(mise_eur),0) m,"
                " SUM(CASE WHEN gain_eur > 0 THEN 1 ELSE 0 END) w FROM mr_lignes"
                " WHERE mode='live' AND gain_eur IS NOT NULL AND ts_entree >= ?",
                (max(depuis, _minuit),))
            o = self._q(
                "SELECT COUNT(*) n, COALESCE(SUM(mise_eur),0) m FROM mr_lignes"
                " WHERE mode='live' AND statut='OUVERTE' AND tx_achat IS NOT NULL"
                " AND ts_entree >= ?", (depuis,))
        except Exception:  # noqa: BLE001
            return ""
        n = int(r[0]["n"] or 0) if r else 0
        nj = int(j[0]["n"] or 0) if j else 0
        # LA DATE EST DERIVEE DE `cumul_depuis`, jamais ecrite en dur : une date figee dans le
        # texte survivrait au changement de methode et mentirait sans que rien ne le signale.
        # C est exactement ce qui vient d arriver avec « depuis le 18/09 ».
        quand = (_dt.datetime.fromtimestamp(depuis, _tz)
                 .strftime("depuis le %d/%m %Hh%M") if depuis else "tout l historique")
        # `nom_court` : le pied de message dit A QUELLE REGLE ce total appartient, et c est lu sur un
        # telephone. Le nom technique de la regle fait l affaire pour la production (`BANDE`) mais pas
        # pour le suiveur, ou il donnerait `GD_SUIVEUR`. Defaut = le nom technique, donc la production
        # est inchangee.
        bloc = ["", "━━━━━━━━━━━━━━",
                "<i>%s · %s</i>" % (str(self._cfg("nom_court", self._cfg("regle", "?"))).upper(),
                                    quand)]
        # DEUX LIGNES, JAMAIS UNE. Demande de Mido le 23/09 : « separe P&L du jour et P&L total ».
        # Un total qui grossit cache une journee qui saigne -- c est exactement ce qui s etait
        # passe le 20/09 avec `FORET REENTRAINEE`, ou le cumul restait flatteur pendant que la
        # journee perdait 45,75 EUR en une heure. Le jour vient EN PREMIER : c est lui qui dit ce
        # qui se passe maintenant.
        if nj:
            gj, mj, wj = float(j[0]["g"]), float(j[0]["m"]) or 1.0, int(j[0]["w"] or 0)
            bloc.append("<b>aujourd'hui</b>  %+.2f EUR · %d trades, %.0f %% won, %+.3f/eur"
                        % (gj, nj, 100.0 * wj / nj, gj / mj))
        else:
            bloc.append("<b>aujourd'hui</b>  aucun ticket compte")
        if n:
            g, m, w = float(r[0]["g"]), float(r[0]["m"]) or 1.0, int(r[0]["w"] or 0)
            bloc.append("<b>total</b>       %+.2f EUR · %d trades, %.0f %% won, %+.3f/eur"
                        % (g, n, 100.0 * w / n, g / m))
        else:
            bloc.append("<b>total</b>       aucun ticket encore compte sur la chaine")
        if o and int(o[0]["n"] or 0):
            bloc.append("%d position(s) ouverte(s), %.0f EUR engages" % (int(o[0]["n"]), float(o[0]["m"])))
        return "\n".join(bloc)

    async def _echec_vente(self, mint: str, raison: str, now: float) -> None:
        """Une vente qui ne passe pas est de l ARGENT BLOQUE, pas un incident technique.

        On retente a chaque cycle -- c est voulu, un pool illiquide peut redevenir vendable -- mais
        on PREVIENT, parce que seul l operateur peut alors vendre a la main. Et on ne previent pas
        toutes les cinq secondes : une alerte au troisieme echec, puis une par demi-heure. Sans ce
        frein, une seule position invendable noierait le canal sous sept cents messages par heure et
        les vraies alertes deviendraient invisibles.
        """
        n, derniere = self._echecs.get(mint, (0, 0.0))
        n += 1
        log.warning("modele_rapide: vente refusee %s (%d echecs) — %s", mint[:10], n, raison)
        if n == 3 or (n > 3 and now - derniere >= 1800):
            await self._prevenir(
                "⚠️ <b>%s…</b> INVENDABLE — %d tentatives\n<i>%s</i>\n"
                "Argent bloqué : une vente à la main peut être nécessaire." % (mint[:8], n, raison),
                critique=True)
            derniere = now
        self._echecs[mint] = (n, derniere)

    async def _compter(self, now: float) -> None:
        """Le P&L se lit sur le SOLDE DU PORTEFEUILLE, jamais sur une cotation.

        Sans ce comptage, `gain_eur` resterait NULL : le plafond de perte ne se declencherait
        JAMAIS, et surtout on ne mesurerait pas le cout d execution -- c est-a-dire la seule raison
        pour laquelle ce carnet tourne en reel. On additionne la variation de solde de l ACHAT
        (negative, frais compris) et celle de la VENTE (positive), et c est tout.

        Separe de la vente : une transaction fraichement diffusee n est pas encore confirmee et
        `sol_delta` rend None pendant quelques secondes. On rejoue a chaque cycle tant que le compte
        manque, au lieu de bloquer la vente dessus.
        """
        from intel.execution import solana as sol
        a_compter = self._q(
            "SELECT mint, tx_achat, tx_vente FROM mr_lignes WHERE mode='live' AND statut='FERMEE'"
            " AND gain_eur IS NULL AND tx_achat IS NOT NULL AND tx_vente IS NOT NULL"
            " AND ts_sortie >= ?", (now - 6 * 3600,))
        if not a_compter:
            return
        rpc = sol.rpc_url()
        proprio = sol.signer_address(self._cfg("cle_fichier", None))
        if not rpc or not proprio:
            return
        for l in a_compter:
            try:
                da = await sol.sol_delta(self.client, rpc, str(l["tx_achat"]), proprio)
                dv = await sol.sol_delta(self.client, rpc, str(l["tx_vente"]), proprio)
                if da is None or dv is None:
                    continue                 # pas encore confirmee : on rejouera
                taux = await sol.sol_eur(self.client)
            except Exception:  # noqa: BLE001
                continue
            gain = (da + dv) * taux
            self._x(
                "UPDATE mr_lignes SET gain_eur=?, motif=? WHERE mint=?",
                (gain, "compte sur la chaine : %+.5f SOL" % (da + dv), l["mint"]))
            log.info("modele_rapide: %s compte sur la chaine — %+.5f SOL soit %+.2f EUR",
                     str(l["mint"])[:10], da + dv, gain)
            await self._prevenir("%s <b>%s…</b> %+.2f EUR <i>(compté sur la chaîne)</i>%s"
                                 % ("✅" if gain > 0 else "❌", str(l["mint"])[:8], gain, self._cumul()))
