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

A = 45                    # l age de la decision
EXEC_S = 2                # le delai entre la decision et l entree, comme dans la recherche
TENUE_S = 240             # duree de detention : NI stop, NI prise de gain (ils coutent 6,6 pts)
BANDE = (0.20, 0.35)
MODELE = os.environ.get("MODELE_VIDAGE", "/app/data/recherche/balayage/modele_vidage.json")

# LES VARIABLES DOIVENT ETRE CELLES DE L ENTRAINEMENT, PAS CELLES DE NOTRE MISE.
# `cout` est une VARIABLE DU MODELE, et le filtre d eligibilite « ordre > 15 % du pool » en depend
# aussi. Les calculer avec notre mise reelle donnerait au modele une entree qu il n a jamais vue et
# changerait les jetons retenus : mesure sur 210 pools, 49 basculaient d eligibilite (19 %) et les
# 210 avaient un `cout` different. On reprend donc les constantes EXACTES de `papier_combo`, et la
# mise reelle ne sert qu au DIMENSIONNEMENT DE L ORDRE, jamais aux variables.
MISE_SOL_MODELE, COUT_FIXE_MODELE = 0.31, 0.017


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

    def __init__(self, ctx, client) -> None:
        self.ctx, self.client = ctx, client
        self._modele = None
        self._vus: set[str] = set()
        # mint -> (nombre d echecs de vente, instant de la derniere alerte). Une position
        # qu on n arrive pas a vendre est de l argent BLOQUE : elle doit reveiller
        # l operateur, seul a pouvoir vendre a la main, au lieu de retenter en silence.
        self._echecs: dict[str, tuple[int, float]] = {}

    def _cfg(self, cle: str, defaut: Any) -> Any:
        return self.ctx.config.get("modele_rapide.%s" % cle, defaut)

    def _charge_modele(self):
        if self._modele is None:
            import sys
            d = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research")
            if d not in sys.path:
                sys.path.insert(0, d)
            from arbres import Modele  # noqa: PLC0415
            self._modele = Modele(self._cfg("modele", MODELE))
            log.info("modele_rapide: modele charge (%d arbres, seuil %.4f)",
                     len(self._modele.arbres), self._modele.seuil_p80)
        return self._modele

    # ---------------------------------------------------------------- decision

    def _variables(self, pts, naissance, lancements):
        """Les memes variables que la recherche, calculees sur les memes lectures.

        `pts` : [(age, prix, reserve_sol, reserve_base, reserve_virtuelle)] tries par age.
        Rend None des qu une condition d eligibilite manque -- on ne devine jamais une variable.
        """
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
        if _a_age(ages, A + EXEC_S, 6) is None:
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

    def retenu(self, f: dict, risque: float) -> bool:
        """Les DEUX conditions de la regle gelee. NaN ecarte AVANT toute comparaison.

        Une comparaison avec NaN est toujours fausse : sans ce garde-fou un ticket dont
        `depuis_min` manque basculerait silencieusement du mauvais cote.
        """
        x = f.get("depuis_min")
        if x is None or x != x:
            return False
        return float(x) <= 1e-9 and BANDE[0] <= risque < BANDE[1]

    # ---------------------------------------------------------------- schema

    def _schema(self) -> None:
        self.ctx.db.execute(
            "CREATE TABLE IF NOT EXISTS mr_lignes("
            "  mint TEXT PRIMARY KEY, pair TEXT, symbole TEXT, mode TEXT, statut TEXT,"
            "  naissance REAL, t_dec REAL, risque REAL, depuis_min REAL, q REAL,"
            "  ts_entree INTEGER, prix_entree REAL, mise_eur REAL, tx_achat TEXT,"
            "  ts_sortie INTEGER, prix_sortie REAL, tx_vente TEXT, gain_eur REAL,"
            "  motif TEXT, variables TEXT)")
        self.ctx.db.execute("CREATE INDEX IF NOT EXISTS i_mr_statut ON mr_lignes(statut)")

    # ---------------------------------------------------------------- cycle

    async def cycle(self) -> dict[str, Any]:
        from intel.utils.timeutil import now_ts

        self._schema()
        now = now_ts()
        live = str(self._cfg("mode", "paper")).lower() == "live"
        mise = float(self._cfg("mise_eur", 20.0))

        # --- plafonds, verifies AVANT toute decision -------------------------
        jour = self.ctx.db.query(
            "SELECT COUNT(*) n, COALESCE(SUM(gain_eur), 0) g FROM mr_lignes"
            " WHERE mode='live' AND ts_entree >= ?", (now - 86400,))
        n_jour = int(jour[0]["n"] or 0) if jour else 0
        perte_jour = float(jour[0]["g"] or 0.0) if jour else 0.0
        max_jour = int(self._cfg("max_ordres_jour", 40))
        perte_max = float(self._cfg("max_perte_jour_eur", 150.0))
        bloque = live and (n_jour >= max_jour or perte_jour <= -perte_max)
        if bloque:
            log.info("modele_rapide: plafond atteint (%d ordres, %+.0f EUR) — plus d achat aujourd'hui",
                     n_jour, perte_jour)

        modele = self._charge_modele()
        fenetre = int(self._cfg("fenetre_minutes", 15))
        lancements = sorted(float(r["ts"]) for r in self.ctx.db.query(
            "SELECT ts FROM solana_stream_launches WHERE ts > ?", (now - 3600,)))

        # --- ce qui est encore decidable ------------------------------------
        deja = {str(r["mint"]) for r in self.ctx.db.query("SELECT mint FROM mr_lignes")}
        pools = self.ctx.db.query(
            "SELECT pair_id, mint, MIN(ts - age_s) AS naissance, MAX(age_s) AS age"
            " FROM solana_prix_chaine WHERE ts > ? GROUP BY pair_id", (now - fenetre * 60,))
        decides = achetes = 0
        for p in pools:
            mint = str(p["mint"] or "")
            if not mint or mint in deja or (p["age"] or 0) < A + EXEC_S:
                continue
            if (p["age"] or 0) > A + EXEC_S + 120:
                continue                     # trop tard : la fenetre d entree est passee
            lect = self.ctx.db.query(
                "SELECT age_s, prix_sol, reserve_sol, reserve_base, reserve_virtuelle"
                " FROM solana_prix_chaine WHERE pair_id = ? ORDER BY age_s", (p["pair_id"],))
            pts = [(float(r["age_s"] or 0), float(r["prix_sol"] or 0), float(r["reserve_sol"] or 0),
                    float(r["reserve_base"] or 0), float(r["reserve_virtuelle"] or 0))
                   for r in lect if (r["prix_sol"] or 0) > 0]
            if len(pts) < 3:
                continue
            f = self._variables(pts, float(p["naissance"] or 0), lancements)
            if f is None:
                continue
            risque = float(modele.probabilite(f))
            decides += 1
            garde = self.retenu(f, risque)
            deja.add(mint)
            if not garde:
                self.ctx.db.execute(
                    "INSERT OR IGNORE INTO mr_lignes(mint, pair, mode, statut, naissance, t_dec,"
                    " risque, depuis_min, q, variables) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (mint, str(p["pair_id"]), "live" if live else "paper", "ECARTEE",
                     float(p["naissance"] or 0), now, risque, f.get("depuis_min"), f.get("q"),
                     json.dumps(f, default=str)))
                continue
            e = _a_age([x[0] for x in pts], A + EXEC_S, 6)
            prix_e = pts[e][1] if e is not None else pts[-1][1]
            self.ctx.db.execute(
                "INSERT OR IGNORE INTO mr_lignes(mint, pair, mode, statut, naissance, t_dec,"
                " risque, depuis_min, q, ts_entree, prix_entree, mise_eur, variables)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (mint, str(p["pair_id"]), "live" if live else "paper", "OUVERTE",
                 float(p["naissance"] or 0), now, risque, f.get("depuis_min"), f.get("q"),
                 now, prix_e, mise, json.dumps(f, default=str)))
            achetes += 1
            if live and not bloque:
                await self._acheter_reel(mint, mise, f, risque)
        # VENDRE ET COMPTER NE SONT JAMAIS BLOQUES. Un plafond doit arreter les ACHATS, jamais les
        # ventes : sinon atteindre 40 ordres laisserait les positions ouvertes indefiniment, sans
        # personne pour les fermer. Le plafond protege du risque, il ne doit pas en creer un.
        if live:
            await self._sortir(now)
            await self._compter(now)
        return {"status": "ok", "decides": decides, "retenus": achetes, "mode": "live" if live else "paper"}

    # ---------------------------------------------------------------- reel

    async def _acheter_reel(self, mint: str, mise: float, f: dict, risque: float) -> None:
        """Envoie l ordre. Toute erreur ferme la ligne : on ne garde jamais une position fantome."""
        from intel.execution import solana as sol
        cle = self._cfg("cle_fichier", None)
        rpc, proprio = sol.rpc_url(), sol.signer_address(cle)
        if not rpc or not proprio:
            log.warning("modele_rapide: mode live mais aucune cle — aucun ordre envoye")
            self.ctx.db.execute("UPDATE mr_lignes SET statut='ANNULEE', motif=? WHERE mint=?",
                                ("aucune cle", mint))
            return
        # LE TAUX SE LIT SUR LE MARCHE, JAMAIS EN DUR. Le 08/09 le carnet supposait 180 EUR/SOL
        # alors qu il valait 96 : un ticket annonce a 5 EUR en engageait 2,67, et tous les gains
        # etaient rapportes 88 % trop haut. `sol_eur` lit le marche et met en cache quelques minutes.
        try:
            taux = await sol.sol_eur(self.client)
        except Exception:  # noqa: BLE001
            log.warning("modele_rapide: taux SOL illisible — achat reporte plutot que mal dimensionne")
            self.ctx.db.execute("UPDATE mr_lignes SET statut='ANNULEE', motif=? WHERE mint=?",
                                ("taux SOL illisible", mint))
            return
        try:
            tx = await sol.prepare_buy(
                self.client, mint=mint, size_eur=mise,
                sol_eur=taux,
                slippage_pct=float(self._cfg("slippage_achat_pct", 20.0)),
                max_impact_pct=float(self._cfg("max_impact_pct", 15.0)),
                priorite_lamports=int(self.ctx.config.get("solana.priority_fee_lamports", 0) or 0),
                proprietaire=proprio)
            if tx.get("status") != "BUILT" or not tx.get("tx"):
                raise RuntimeError(tx.get("refused_reason") or "transaction non assemblee")
            h = await sol.send(self.client, rpc, sol.sign(tx["tx"], cle))
            self.ctx.db.execute("UPDATE mr_lignes SET tx_achat=? WHERE mint=?", (h, mint))
            log.info("modele_rapide: ACHAT %s — %s", mint[:10], h[:16])
            await self._prevenir(
                "🟢 <b>%s…</b> acheté · <i>au plus bas + bande</i>\n"
                "%.2f EUR · risque %.3f · coffre %.0f SOL · revente dans 4 min"
                % (mint[:8], mise, risque, float(f.get("q", 0.0) or 0.0)))
        except Exception as exc:  # noqa: BLE001
            self.ctx.db.execute("UPDATE mr_lignes SET statut='ANNULEE', motif=? WHERE mint=?",
                                (str(exc)[:160], mint))
            log.warning("modele_rapide: achat refuse %s (%s)", mint[:10], str(exc)[:100])

    async def _sortir(self, now: float) -> None:
        """Vend tout ce qui a passe TENUE_S. AUCUN seuil : ni stop, ni prise de gain."""
        from intel.execution import solana as sol
        cle = self._cfg("cle_fichier", None)
        rpc, proprio = sol.rpc_url(), sol.signer_address(cle)
        for l in self.ctx.db.query(
                "SELECT mint, ts_entree FROM mr_lignes WHERE mode='live' AND statut='OUVERTE'"
                " AND tx_achat IS NOT NULL AND ts_entree <= ?", (now - TENUE_S,)):
            mint = str(l["mint"])
            try:
                solde = await sol.token_balance(self.client, rpc, proprio, mint)
            except Exception as exc:  # noqa: BLE001
                await self._echec_vente(mint, "solde illisible : %s" % str(exc)[:60], now)
                continue
            if not solde:
                self.ctx.db.execute("UPDATE mr_lignes SET statut='FERMEE', ts_sortie=?, motif=?"
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
                self.ctx.db.execute(
                    "UPDATE mr_lignes SET statut='FERMEE', ts_sortie=?, tx_vente=?, motif=?"
                    " WHERE mint=?", (now, h, "sortie a %d s" % TENUE_S, l["mint"]))
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
        """Le cumul de CE carnet seulement, lu sur `mr_lignes`.

        Une ligne dont le resultat n est pas encore lu sur la chaine n entre pas dans le total,
        plutot que d y entrer a zero.
        """
        try:
            r = self.ctx.db.query(
                "SELECT COUNT(*) n, COALESCE(SUM(gain_eur),0) g, COALESCE(SUM(mise_eur),0) m,"
                " SUM(CASE WHEN gain_eur > 0 THEN 1 ELSE 0 END) w FROM mr_lignes"
                " WHERE mode='live' AND gain_eur IS NOT NULL")
            o = self.ctx.db.query(
                "SELECT COUNT(*) n, COALESCE(SUM(mise_eur),0) m FROM mr_lignes"
                " WHERE mode='live' AND statut='OUVERTE' AND tx_achat IS NOT NULL")
        except Exception:  # noqa: BLE001
            return ""
        n = int(r[0]["n"] or 0) if r else 0
        bloc = ["", "━━━━━━━━━━━━━━", "<i>carnet MODELE (depuis le 18/09)</i>"]
        if n:
            g, m, w = float(r[0]["g"]), float(r[0]["m"]) or 1.0, int(r[0]["w"] or 0)
            bloc.append("%+.2f EUR · %d trades, %.0f %% won, %+.3f/eur"
                        % (g, n, 100.0 * w / n, g / m))
        else:
            bloc.append("aucun ticket encore compte sur la chaine")
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
        a_compter = self.ctx.db.query(
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
            self.ctx.db.execute(
                "UPDATE mr_lignes SET gain_eur=?, motif=? WHERE mint=?",
                (gain, "compte sur la chaine : %+.5f SOL" % (da + dv), l["mint"]))
            log.info("modele_rapide: %s compte sur la chaine — %+.5f SOL soit %+.2f EUR",
                     str(l["mint"])[:10], da + dv, gain)
            await self._prevenir("%s <b>%s…</b> %+.2f EUR <i>(compté sur la chaîne)</i>%s"
                                 % ("✅" if gain > 0 else "❌", str(l["mint"])[:8], gain, self._cumul()))
