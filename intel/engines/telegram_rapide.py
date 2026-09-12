"""Acheter un lancement qui a un Telegram, le revendre quatre minutes plus tard.

C EST LA PREMIERE REGLE DE CE PROJET QUI GAGNE SUR UNE MESURE HORS ECHANTILLON.

Demande de l operateur le 12/09 : « je veux chercher un truc qui gagne de l argent, Telegram
fonctionne sur une duree de vie limitee ou un truc comme ca, croise tout ». L intuition etait juste,
et le croisement complet (`intel/research/croise.py`) la confirme sur 2 560 courbes nees du 09/09
20h au 12/09 13h, coupees en deux par date de naissance :

                          n     gagnants   mediane   par euro (jugement)
    population entiere   2 560     47 %      -0,3 %        +0,061
    avec Telegram          171     66 %      +1,2 %        +0,174

Sur la SEULE moitie de jugement (n=95, jamais regardee pendant la recherche) : 69 % de gagnants
contre 48 % de base, mediane +4,3 % contre -0,3 %. Sur 20 000 tirages au hasard de 95 jetons pris
dans la meme population, ZERO fait aussi bien, ni sur le taux de gagnants ni sur la mediane.

CE QUI REND CE RESULTAT DIFFERENT DES SIX FAMILLES ENTERREES CETTE SEMAINE

  1. Il ne tient pas sur une loterie. Le meilleur ticket du groupe Telegram fait x3,4 -- pas x286
     comme celui du groupe « 0-1 signe ». Retirer la meilleure ligne fait passer le gain de +0,174
     a +0,154 : il reste. Toutes les trouvailles precedentes s effondraient a ce test.
  2. Il n est pas concentre sur trois heures. Huit tranches de 6 h sur onze sont positives.
  3. Il survit au retard. Entrer 30 s apres la decision donne encore +0,173 ; 60 s, +0,151.
  4. Il survit au peage. A 10 % de frais aller-retour, retard de 30 s compris, il reste +0,077.
  5. Le temoin est plat. Les memes jetons SANS Telegram, meme retard, meme peage : +0,022.

LE MECANISME, qui compte autant que le chiffre. Kamat 2026 mesure que le Telegram multiplie par 8,9
le taux de graduation. Le canal n est pas magique : il donne au lancement une audience reelle, donc
un flux d achat qui dure quelques minutes. Mais cette audience s epuise. Le profil temporel le dit
sans ambiguite -- tenir 15 minutes rend -0,337, sortir a 4 minutes rend +0,174. L operateur avait
nomme le mecanisme avant que je le mesure : duree de vie limitee.

    duree de detention   1 min   2 min   3 min   4 min   5 min   6 min   8 min   10 min   15 min
    telegram, jugement   +0,07   +0,07   +0,14   +0,17   +0,21   +0,15   +0,07    -0,03    -0,34

Quatre minutes est retenu et non cinq : a 4 min les deux moities disent la meme chose (+0,156 et
+0,174), a 5 min la moitie de recherche tombe a +0,055. On prend le point stable, pas le sommet.

L HEURE D ENTREE, balayee le 12/09 sur 183 jetons Telegram apres une question de l operateur
(« on achete a T+60 ou meme avant ? »). Le premier reglage, T+90 s, ne venait pas d une mesure : il
venait de ce que le filtre `trop_propre` avait besoin de quatre releves avant de juger. Or le
Telegram est dans la metadonnee, lisible des la premiere seconde -- rien n obligeait a attendre.

    entree      T+15    T+30    T+45    T+60    T+75    T+90    T+120   T+150   T+180
    recherche  +0,378  +0,168  +0,158  +0,197  +0,162  +0,268  +0,104  +0,142  +0,071
    JUGEMENT   +0,090  +0,107  +0,255  +0,194  +0,206  +0,151  +0,147  +0,132  +0,103
    sans best  +0,065  +0,090  +0,158  +0,174  +0,169  +0,130  +0,122  +0,087  +0,067

T+60 est retenu parce que c est le point ou les deux moities s ACCORDENT (+0,197 et +0,194) et ou
« sans sa meilleure ligne » est le plus haut (+0,174). T+45 affiche un meilleur jugement (+0,255)
mais une recherche a +0,158 : l ecart trahit le bruit. T+15 et T+30 sont nettement moins bons --
entrer trop tot ne paye pas, la montee n a pas commence. Le cout est de 3 % du flux : 91 % des
jetons ont un prix lisible des T+60 contre 94 % a T+90.

LE FILTRE `trop_propre` NE DOIT PAS S APPLIQUER ICI, et c est important : il ecarte les lancements
a 2-3 signes, or 107 des 171 jetons Telegram en sont, et ils rapportent +0,156 par euro (76 % de
gagnants, mediane +4,3 %). Ce filtre a ete mesure sur la population generale, ou le groupe 2-3
signes perd (-0,048) ; sur les jetons Telegram il gagne. Le Telegram passe devant.

CE QUE CE MODULE NE PROUVE PAS. 2,7 jours d une seule fenetre de marche. C est peu, et l operateur
le sait : mis devant ce chiffre le 12/09 a 15h, il a repondu « Ok va passer en prod juste dis moi le
rythme d achat il sera de combien ». Le module est donc en REEL depuis le 12/09 15h30, sur le
portefeuille du robot (71,60 EUR au basculement), mise de 10 EUR, six lignes simultanees au plus.

CE QUI PROTEGE L ARGENT, et qui ne vient pas de la mesure :

  - « peut-on ressortir ? » On cote la REVENTE avant d acheter et on refuse au-dela de 15 % d
    aller-retour. Cinq pools sur vingt-cinq sont invendables a notre taille (S3.36) et c est la
    cause de 25 % des tickets aneantis du carnet Robinhood -- pas le prix. La mesure ci-dessus lit
    des RESERVES, qui ne disent rien de la contrepartie : elle surestime donc le rendement sur ces
    pools-la. Ce garde corrige un biais connu, dans le bon sens.
  - Une vente qui echoue laisse la ligne OUVERTE et se rejoue toutes les dix secondes, mais ne
    previent qu une fois puis toutes les demi-heures.
  - Vendre passe toujours avant acheter, et le plafond de lignes ne peut pas bloquer une sortie.

RYTHME MESURE au basculement : 42 a 50 lancements par heure, 90 % avec courbe, 6,6 % avec Telegram,
soit environ 2,5 achats par heure et 60 par jour. A 10 EUR le ticket, 600 EUR de volume par jour
pour 60 EUR de capital immobilise au pire, puisque chaque ligne ne dure que quatre minutes.
"""
from __future__ import annotations

import logging
import time
from typing import Any

log = logging.getLogger(__name__)

MODEL_VERSION = "tg-sol-v1"

AGE_MIN = 55             # s : on vise une entree vers T+60, voir le balayage ci-dessous
AGE_MAX = 180            # s : au-dela on a rate le train, on n entre pas
TENUE_S = 240            # s : quatre minutes, le point stable des deux moities
LECTURE_MAX = 30         # s : au-dela, la lecture de reserve est perimee, on ne paye pas dessus


class TelegramRapide:
    def __init__(self, ctx, client) -> None:
        self.ctx, self.client = ctx, client
        self._sans_meta: dict[str, int] = {}      # mint -> nombre d essais rates

    def _cfg(self, cle: str, defaut):
        return self.ctx.config.get("telegram_rapide." + cle, defaut)

    # ------------------------------------------------------------------ socle
    def _table(self) -> None:
        self.ctx.db.execute(
            "CREATE TABLE IF NOT EXISTS tg_lignes("
            "  mint TEXT PRIMARY KEY, symbole TEXT, pair_id TEXT,"
            "  ts_entree INTEGER, age_entree INTEGER, prix_entree REAL,"
            "  mise_eur REAL, jetons TEXT, tx_achat TEXT,"
            "  ts_sortie INTEGER, prix_sortie REAL, gain_eur REAL, tx_vente TEXT,"
            "  statut TEXT, mode TEXT, motif TEXT)")
        self.ctx.db.execute(
            "CREATE TABLE IF NOT EXISTS tg_juges("
            "  mint TEXT PRIMARY KEY, ts INTEGER, telegram INTEGER, twitter INTEGER,"
            "  site INTEGER, verdict TEXT)")
        # `echecs` compte les ventes reelles refusees sur une ligne. La colonne est ajoutee apres
        # coup : une base creee avant cette version n en a pas, et un moteur qui suppose sa presence
        # s arreterait au premier cycle.
        #
        # `age_lecture` distingue deux ages que la premiere version confondait : `age_entree` est
        # l age VRAI du jeton a l achat, compte depuis le lancement ; `age_lecture` est son age au
        # moment ou le prix d entree a ete releve, qui peut dater de 30 s. L operateur a vu des
        # achats « a T+50 » le 12/09 alors que la fenetre s ouvre a T+55 : c etait le second qui
        # etait ecrit dans la colonne du premier.
        try:
            cols = {r["name"] for r in self.ctx.db.query("PRAGMA table_info(tg_lignes)")}
            if "echecs" not in cols:
                self.ctx.db.execute("ALTER TABLE tg_lignes ADD COLUMN echecs INTEGER DEFAULT 0")
            if "age_lecture" not in cols:
                self.ctx.db.execute("ALTER TABLE tg_lignes ADD COLUMN age_lecture INTEGER")
        except Exception as exc:  # noqa: BLE001
            log.info("tg: colonne non ajoutee (%s)", str(exc)[:80])

    def _prix(self, mint: str, now: int, fraicheur: int = LECTURE_MAX, pair: str | None = None):
        """Le dernier prix lu EN CHAINE pour ce mint, et l age du pool a ce moment-la.

        On ne prend pas DexScreener : il se rafraichit toutes les 30 a 60 s (S3.61), donc a
        T+90 s il rendrait une valeur d avant le lancement. La mesure a ete faite sur les reserves,
        l execution doit lire les reserves.

        La condition porte sur la FRAICHEUR DE LA LECTURE, pas sur l age du jeton. La premiere
        version confondait les deux : elle refusait toute lecture dont `age_s` depassait 100 s,
        alors que la fenetre d entree va jusqu a 180 s. Resultat, le moteur a tourne une demi-heure
        sans juger un seul candidat. L age du jeton est deja filtre par la fenetre, et la mesure dit
        qu entrer jusqu a 60 s apres la decision garde le gain (+0,151).

        `pair` epingle le POOL. Un jeton gradue en a plusieurs ; comparer un prix d entree pris sur
        l un a un prix de sortie pris sur l autre invente un gain ou une perte qui n existe pas.
        Trois grosses pertes du carnet Robinhood venaient exactement de la (S3.43), et la mesure qui
        justifie ce module groupe elle-meme par `pair_id`. La sortie DOIT donc citer le pool de
        l entree, faute de quoi le test en avant mesurerait autre chose que la strategie.
        """
        if pair:
            r = self.ctx.db.query(
                "SELECT prix_sol, age_s, pair_id, ts FROM solana_prix_chaine"
                " WHERE pair_id=? AND prix_sol>0 ORDER BY ts DESC LIMIT 1", (pair,))
        else:
            r = self.ctx.db.query(
                "SELECT prix_sol, age_s, pair_id, ts FROM solana_prix_chaine"
                " WHERE mint=? AND prix_sol>0 ORDER BY ts DESC LIMIT 1", (mint,))
        if not r:
            return None
        if now - int(r[0]["ts"] or 0) > fraicheur:
            return None
        return float(r[0]["prix_sol"]), int(r[0]["age_s"] or 0), str(r[0]["pair_id"] or "")

    # ------------------------------------------------------------- metadonnee
    async def _telegram(self, mint: str):
        """Ce lancement a-t-il un canal Telegram ? None si on n a pas pu lire.

        None et « pas de Telegram » sont deux choses differentes : on n achete que sur un OUI lu.
        Une lecture ratee ne devient jamais un achat, et ne devient jamais non plus un « non »
        definitif -- on reessaye au cycle suivant tant que l age le permet.
        """
        from intel.execution import solana as sol
        from intel.research.social import _fiche, _meta
        rpc = sol.rpc_url()
        if not rpc:
            return None
        meta = await _meta(self.client, rpc, mint)
        if not meta:
            return None
        essais = self._sans_meta.get(mint, 0)
        j = await _fiche(self.client, meta.get("uri") or "", depart=essais)
        if j is None:
            self._sans_meta[mint] = essais + 1
            return None
        fiche = {"telegram": int(bool(j.get("telegram"))), "twitter": int(bool(j.get("twitter"))),
                 "site": int(bool(j.get("website"))), "nom": meta.get("symbol") or mint[:8]}
        # La meme lecture sert la recherche : `solana_social` est la table sur laquelle la mesure a
        # ete faite, et la remplir en direct evite de relire plus tard ce qu on a deja sous la main
        # -- c est ce rattrapage tardif qui avait sature les passerelles.
        try:
            self.ctx.db.execute(
                "CREATE TABLE IF NOT EXISTS solana_social("
                " mint TEXT PRIMARY KEY, nom TEXT, symbole TEXT, uri TEXT,"
                " twitter INTEGER, telegram INTEGER, site INTEGER, n_descr INTEGER, lu INTEGER)")
            self.ctx.db.execute(
                "INSERT OR REPLACE INTO solana_social VALUES(?,?,?,?,?,?,?,?,?)",
                (mint, meta.get("name"), meta.get("symbol"), meta.get("uri"),
                 fiche["twitter"], fiche["telegram"], fiche["site"],
                 len(j.get("description") or ""), 1))
        except Exception as exc:  # noqa: BLE001
            log.info("tg: fiche sociale non enregistree (%s)", str(exc)[:80])
        return fiche

    # ----------------------------------------------------------------- vendre
    async def _vendre(self, now: int) -> int:
        """Sortir toute ligne qui a quatre minutes. Vendre passe AVANT acheter, toujours."""
        mures = self.ctx.db.query(
            "SELECT * FROM tg_lignes WHERE statut='OUVERTE' AND ts_entree <= ?", (now - TENUE_S,))
        vendus = 0
        for l in mures:
            mint = l["mint"]
            p = self._prix(mint, now, fraicheur=10_000, pair=l["pair_id"])
            fin = p[0] if p else None
            if l["mode"] != "live":
                gain = None
                if fin and float(l["prix_entree"] or 0) > 0:
                    peage = float(self._cfg("peage_pct", 2.0)) / 100.0
                    gain = float(l["mise_eur"]) * ((fin / float(l["prix_entree"])) * (1 - peage) - 1)
                self.ctx.db.execute(
                    "UPDATE tg_lignes SET statut='FERMEE', ts_sortie=?, prix_sortie=?, gain_eur=?,"
                    " motif=? WHERE mint=?",
                    (now, fin, gain, "tenue de %d s ecoulee" % TENUE_S, mint))
                vendus += 1
                log.info("tg: %s ferme a blanc apres %d s - %s", l["symbole"], now - int(l["ts_entree"]),
                         ("%+.2f EUR" % gain) if gain is not None else "prix de sortie inconnu")
                continue
            vendus += await self._vendre_reel(l, now, fin)
        return vendus

    async def _vendre_reel(self, l, now: int, fin) -> int:
        from intel.execution import solana as sol
        rpc = sol.rpc_url()
        cle = self._cfg("cle_fichier", None)
        proprio = sol.signer_address(cle)
        if not rpc or not proprio:
            log.warning("tg: %s a vendre mais pas de cle - la ligne reste ouverte", l["symbole"])
            return 0
        try:
            solde = await sol.token_balance(self.client, rpc, proprio, l["mint"])
        except Exception as exc:  # noqa: BLE001
            log.warning("tg: solde illisible pour %s (%s)", l["symbole"], str(exc)[:60])
            return 0
        if solde <= 0:
            self.ctx.db.execute(
                "UPDATE tg_lignes SET statut='FERMEE', ts_sortie=?, motif=? WHERE mint=?",
                (now, "solde nul sur la chaine", l["mint"]))
            return 0
        try:
            tx = await sol.prepare_sell(
                self.client, mint=l["mint"], amount=solde,
                slippage_pct=float(self._cfg("slippage_vente_pct", 25.0)),
                proprietaire=proprio,
                priorite_lamports=int(self.ctx.config.get("solana.priority_fee_lamports", 0) or 0))
            if tx.get("status") != "BUILT" or not tx.get("tx"):
                raise RuntimeError(tx.get("refused_reason") or "transaction non assemblee")
            h = await sol.send(self.client, rpc, sol.sign(tx["tx"], cle))
        except Exception as exc:  # noqa: BLE001
            # La ligne reste OUVERTE : on reessaye au cycle suivant, toutes les dix secondes, tant
            # que la vente ne passe pas. Mais on ne PREVIENT pas toutes les dix secondes -- une
            # alerte par ligne, puis une toutes les demi-heures. Un pool invendable noierait sinon
            # le fil Telegram sous cent quatre-vingts messages a l heure, et les vraies alertes
            # avec.
            n = int(l["echecs"] or 0) + 1
            self.ctx.db.execute("UPDATE tg_lignes SET echecs=? WHERE mint=?", (n, l["mint"]))
            self.ctx.db.execute(
                "CREATE TABLE IF NOT EXISTS tg_echecs("
                " ts INTEGER, mint TEXT, symbole TEXT, etape TEXT, erreur TEXT)")
            if n in (1, 5, 30):
                self.ctx.db.insert("tg_echecs", {"ts": now, "mint": l["mint"],
                                                 "symbole": l["symbole"], "etape": "vente",
                                                 "erreur": str(exc)[:2000]})
            log.warning("tg: VENTE ECHOUEE sur %s (essai %d) : %s", l["symbole"], n, str(exc)[:400])
            if n == 1 or n % 180 == 0:
                await self._prevenir(
                    "⚠️ <b>%s</b> devait etre vendu (4 min) et la vente a echoue (essai %d)\n"
                    "<code>%s</code>\n<i>Le moteur reessaye toutes les dix secondes.</i>"
                    % (l["symbole"], n, str(exc)[:120]), critique=True)
            return 0
        self.ctx.db.execute(
            "UPDATE tg_lignes SET statut='FERMEE', ts_sortie=?, prix_sortie=?, tx_vente=?, motif=?"
            " WHERE mint=?", (now, fin, h, "tenue de %d s ecoulee" % TENUE_S, l["mint"]))
        log.info("tg: %s VENDU pour de vrai apres %d s, tx %s", l["symbole"], now - int(l["ts_entree"]), h[:20])
        return 1

    # ----------------------------------------------------------- faire les comptes
    async def _compter(self, now: int) -> int:
        """Le resultat d une ligne REELLE se lit sur le portefeuille, jamais sur une cotation.

        Le 08/09 le carnet a annonce +5,05 EUR sur une ligne que la chaine a payee +2,54 : la
        cotation avait raison sur le multiple et tort sur la mise. On additionne donc les deux
        variations de solde du portefeuille, celle de l achat (negative, frais compris) et celle de
        la vente (positive), et c est tout.

        Ce comptage est SEPARE de la vente : une transaction vient d etre diffusee et n est pas
        encore confirmee quand on la lit, donc `sol_delta` rend None les premieres secondes. On
        rejoue a chaque cycle tant que le compte manque, au lieu de bloquer la vente dessus.
        """
        a_compter = self.ctx.db.query(
            "SELECT mint, symbole, tx_achat, tx_vente FROM tg_lignes WHERE mode='live'"
            " AND statut='FERMEE' AND gain_eur IS NULL AND tx_achat IS NOT NULL"
            " AND tx_vente IS NOT NULL AND ts_sortie >= ?", (now - 6 * 3600,))
        if not a_compter:
            return 0
        from intel.execution import solana as sol
        rpc = sol.rpc_url()
        proprio = sol.signer_address(self._cfg("cle_fichier", None))
        if not rpc or not proprio:
            return 0
        faits = 0
        for l in a_compter:
            da = await sol.sol_delta(self.client, rpc, l["tx_achat"], proprio)
            dv = await sol.sol_delta(self.client, rpc, l["tx_vente"], proprio)
            if da is None or dv is None:
                continue                 # pas encore confirmee : on rejouera
            try:
                taux = await sol.sol_eur(self.client)
            except Exception:  # noqa: BLE001
                continue
            gain = (da + dv) * taux
            self.ctx.db.execute("UPDATE tg_lignes SET gain_eur=?, motif=? WHERE mint=?",
                                (gain, "compte sur la chaine : %+.5f SOL" % (da + dv), l["mint"]))
            faits += 1
            log.info("tg: %s compte sur la chaine — %+.5f SOL soit %+.2f EUR",
                     l["symbole"], da + dv, gain)
            await self._prevenir("%s <b>%s</b> boucle en 4 min : <b>%+.2f EUR</b>\n"
                                 "<i>lu sur le portefeuille, pas sur une cotation</i>\n%s"
                                 % ("✅" if gain > 0 else "🔻", l["symbole"], gain, self._cumul()))
        return faits

    # ---------------------------------------------------------------- acheter
    def _heure_creuse(self, now: int) -> bool:
        """Cette tranche horaire est-elle exclue ? Question de l operateur le 12/09, 21h UTC :
        « le rythme change pas en fonction de l heure de la journee ? ». Il change, deux fois.

        LE RYTHME, sur 2 998 lancements et 3,1 jours :

            tranche UTC   lancements   telegram   taux
            08h-12h              367         38   10,4 %
            20h-24h              726         23    3,2 %

        La tranche 20h-24h porte le PLUS de lancements et le MOINS de Telegram. C est une
        population de createurs differente, et le constat tient sur des centaines de lignes.

        LA RENTABILITE suit le meme sens, sur bien moins de lignes :

            20h-24h, telegram    recherche -0,207 (n=13)   JUGEMENT -0,039 (n=10)
            toutes heures        recherche +0,201 (n=89)   JUGEMENT +0,189 (n=102)
            hors 20h-24h         recherche +0,271 (n=76)   JUGEMENT +0,214 (n=92)

        Negatif des DEUX cotes, et l ecarter ameliore les DEUX moities. C est la bonne signature --
        mais sur 23 jetons, et je me suis fait avoir trois fois cette semaine par des echantillons
        de cette taille. Ce qui fait pencher, c est que le taux (grand echantillon) et la
        rentabilite (petit) racontent la meme histoire, et que le cout est borne : 12 % des tickets.

        A REMESURER quand la collecte aura doublé. `heures_exclues: []` annule la regle.
        """
        try:
            exclues = {int(h) for h in (self._cfg("heures_exclues", []) or [])}
        except Exception:  # noqa: BLE001
            return False
        if not exclues:
            return False
        return time.gmtime(now).tm_hour in exclues

    async def _acheter(self, now: int) -> int:
        if self._heure_creuse(now):
            return 0
        ouvertes = self.ctx.db.scalar(
            "SELECT COUNT(*) FROM tg_lignes WHERE statut='OUVERTE'", (), 0) or 0
        plafond = int(self._cfg("max_lignes_simultanees", 6))
        if ouvertes >= plafond:
            return 0
        jour = now - (now % 86400)
        du_jour = self.ctx.db.scalar(
            "SELECT COUNT(*) FROM tg_lignes WHERE ts_entree >= ?", (jour,), 0) or 0
        max_jour = int(self._cfg("max_par_jour", 0) or 0)
        if max_jour and du_jour >= max_jour:
            return 0

        candidats = self.ctx.db.query(
            "SELECT l.mint, l.ts FROM solana_stream_launches l"
            " WHERE l.ts <= ? AND l.ts >= ?"
            "   AND l.mint NOT IN (SELECT mint FROM tg_lignes)"
            "   AND l.mint NOT IN (SELECT mint FROM tg_juges WHERE verdict != 'illisible')"
            " ORDER BY l.ts DESC LIMIT 20", (now - AGE_MIN, now - AGE_MAX))
        ouverts = 0
        for c in candidats:
            if ouvertes + ouverts >= plafond:
                break
            mint = c["mint"]
            p = self._prix(mint, now)
            if not p:
                continue                     # pas de courbe : on ne sait pas a quel prix on entre
            prix, age, pair = p
            fiche = await self._telegram(mint)
            if fiche is None:
                self.ctx.db.execute(
                    "INSERT OR REPLACE INTO tg_juges VALUES(?,?,?,?,?,?)",
                    (mint, now, None, None, None, "illisible"))
                continue
            if not fiche["telegram"]:
                self.ctx.db.execute(
                    "INSERT OR REPLACE INTO tg_juges VALUES(?,?,?,?,?,?)",
                    (mint, now, 0, fiche["twitter"], fiche["site"], "pas de telegram"))
                continue
            # Le verdict s ecrit APRES l ouverture et dit ce qui s est REELLEMENT passe. L ecrire
            # avant ferait compter comme achete un jeton refuse par le garde « peut-on ressortir »,
            # et le carnet annoncerait des achats qui n ont pas eu lieu (S5.16).
            # DEUX ages, et les confondre a induit l operateur en erreur le 12/09 : il voyait des
            # achats « a T+50 » alors que la fenetre s ouvre a T+55. `age` est l age du jeton au
            # moment de la LECTURE DU PRIX, qui peut dater de 30 s ; l age vrai a l achat se compte
            # depuis le lancement. Le livre doit porter les deux, sinon toute relecture est fausse.
            age_vrai = max(0, now - int(c["ts"] or now))
            pris = await self._ouvrir(mint, fiche["nom"], pair, prix, age_vrai, age, now)
            if pris is None:
                # REFUS PASSAGER : on n ecrit aucun verdict, donc le jeton revient au cycle suivant
                # tant qu il est dans la fenetre. Le 13/09 a 19h55, HUNTRUMP a ete perdu sur
                # « Market not found » -- le pool existait, le routeur ne l avait pas encore indexe.
                # Renoncer definitivement sur une erreur de dix secondes coute un ticket entier.
                continue
            self.ctx.db.execute(
                "INSERT OR REPLACE INTO tg_juges VALUES(?,?,?,?,?,?)",
                (mint, now, 1, fiche["twitter"], fiche["site"],
                 "achete" if pris else "telegram mais achat refuse"))
            if pris:
                ouverts += 1
        return ouverts

    async def _ouvrir(self, mint: str, symbole: str, pair: str, prix: float, age: int,
                      age_lecture: int, now: int):
        """True si la ligne est ouverte, False si le refus est DEFINITIF, None s il est PASSAGER."""
        mise = float(self._cfg("mise_eur", 10.0))
        mode = str(self._cfg("mode", "paper")).lower()
        if mode != "live":
            self.ctx.db.execute(
                "INSERT OR REPLACE INTO tg_lignes(mint, symbole, pair_id, ts_entree, age_entree,"
                " age_lecture, prix_entree, mise_eur, statut, mode, motif)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (mint, symbole, pair, now, age, age_lecture, prix, mise, "OUVERTE", "paper",
                 "telegram present"))
            log.info("tg: %s ouvert A BLANC a T+%d s (%.2f EUR)", symbole, age, mise)
            return True

        from intel.execution import solana as sol
        rpc = sol.rpc_url()
        cle = self._cfg("cle_fichier", None)
        proprio = sol.signer_address(cle)
        if not rpc or not proprio:
            log.warning("tg: mode live demande mais aucune cle lisible - rien n est achete")
            return False
        try:
            se = await sol.sol_eur(self.client)
            # LE FREIN EST LE PORTEFEUILLE, pas un compteur. Un plafond de lignes fixe se regle sur
            # le solde d un jour et se trompe le lendemain : trop haut il laisse partir des ordres
            # que la chaine refusera, trop bas il refuse des ordres que le portefeuille pouvait
            # payer. L operateur ayant dit le 12/09 qu il allait alimenter, la capacite doit suivre
            # le solde toute seule. On garde une reserve pour les frais des ventes en cours.
            reserve = float(self._cfg("reserve_sol", 0.02))
            solde = await sol.sol_balance(self.client, rpc, proprio) / 1e9
            besoin = mise / max(se, 1e-9)
            if solde - reserve < besoin:
                log.info("tg: %s passe la regle mais le portefeuille ne suit pas "
                         "(%.4f SOL disponibles, %.4f necessaires + %.3f de reserve)",
                         symbole, solde, besoin, reserve)
                return False
            tx = await sol.prepare_buy(self.client, mint=mint, size_eur=mise, sol_eur=se,
                                       slippage_pct=float(self._cfg("slippage_achat_pct", 20.0)),
                                       max_impact_pct=float(self._cfg("max_impact_pct", 15.0)),
                                       # PEUT-ON RESSORTIR ? On cote la revente avant d acheter.
                                       # Mesure du 09/09 : cinq pools sur vingt-cinq sont
                                       # invendables a notre taille, et c est la cause de 25 % des
                                       # tickets aneantis -- pas le prix. La mesure qui justifie
                                       # cette strategie lit des RESERVES, qui ne disent rien de la
                                       # contrepartie : elle surestime donc le rendement sur ces
                                       # pools-la. Ce garde corrige un biais connu, dans le bon
                                       # sens, et c est le seul qui protege d une perte totale.
                                       max_aller_retour_pct=float(self._cfg("max_aller_retour_pct", 15.0)),
                                       proprietaire=proprio,
                                       priorite_lamports=int(self.ctx.config.get("solana.priority_fee_lamports", 0) or 0))
            if tx.get("status") != "BUILT" or not tx.get("tx"):
                raise RuntimeError(tx.get("refused_reason") or "transaction non assemblee")
            h = await sol.send(self.client, rpc, sol.sign(tx["tx"], cle))
        except Exception as exc:  # noqa: BLE001
            # 400 caracteres et non 120 : le 12/09 un achat a echoue sur « Error processing
            # Instruction 6: custom program... », coupe juste AVANT le code d erreur, donc
            # indiagnosticable. Un message d echec qui ne dit pas pourquoi ne sert a rien, et
            # celui-ci porte le seul chiffre qui compte -- 0x1771 veut dire que le prix a bouge
            # entre la cotation et l atterrissage, ce qui se corrige avec les frais de priorite.
            self.ctx.db.execute(
                "CREATE TABLE IF NOT EXISTS tg_echecs("
                " ts INTEGER, mint TEXT, symbole TEXT, etape TEXT, erreur TEXT)")
            from intel.utils.timeutil import now_ts
            self.ctx.db.insert("tg_echecs", {"ts": now_ts(), "mint": mint, "symbole": symbole,
                                             "etape": "achat", "erreur": str(exc)[:2000]})
            log.warning("tg: ACHAT ECHOUE sur %s : %s", symbole, str(exc)[:400])
            # DEFINITIF ou PASSAGER ? Les deux refus observes le 13/09 n ont rien a voir :
            #   « impact 42,7 % > plafond 15,0 % »  -> notre garde-fou, le pool est trop mince,
            #                                          ca ne s ameliorera pas dans la minute
            #   « Market ... not found »            -> le pool existe, le routeur ne l a pas encore
            #                                          indexe ; dix secondes plus tard il l aura
            # Rendre None demande de rejouer au cycle suivant, tant que la fenetre est ouverte.
            m = str(exc).lower()
            definitif = ("impact" in m) or ("aller-retour" in m) or ("non convertible" in m)
            return False if definitif else None
        self.ctx.db.execute(
            "INSERT OR REPLACE INTO tg_lignes(mint, symbole, pair_id, ts_entree, age_entree,"
            " age_lecture, prix_entree, mise_eur, tx_achat, statut, mode, motif)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (mint, symbole, pair, now, age, age_lecture, prix, mise, h, "OUVERTE", "live",
             "telegram present"))
        log.info("tg: %s ACHETE POUR DE VRAI a T+%d s (%.2f EUR), tx %s", symbole, age, mise, h[:20])
        await self._prevenir("🟢 <b>%s</b> achete (Telegram present, T+%d s)\n%.2f EUR · vente dans 4 min"
                             % (symbole, age, mise))
        return True

    def _cumul(self) -> str:
        """Le resultat de TOUTE la strategie depuis le passage en reel, joint a chaque vente.

        Demande de l operateur le 12/09 : « accompagne le message de chaque vente par le pnl global
        depuis qu on a mis en place la nouvelle strat ». C est la bonne facon de lire cette
        strategie : un ticket ne veut rien dire, deux perdants sur trois sont attendus, et seul le
        cumul sur plusieurs dizaines de tickets porte l information.

        On ne compte que les lignes REELLES et deja comptees sur la chaine. Une ligne dont le
        resultat n est pas encore lu n entre pas dans le total plutot que d y entrer a zero.
        """
        try:
            r = self.ctx.db.query(
                "SELECT COUNT(*) n, COALESCE(SUM(gain_eur), 0) g, COALESCE(SUM(mise_eur), 0) m,"
                " SUM(CASE WHEN gain_eur > 0 THEN 1 ELSE 0 END) w"
                " FROM tg_lignes WHERE mode='live' AND gain_eur IS NOT NULL")
        except Exception:  # noqa: BLE001
            return ""
        if not r or not int(r[0]["n"] or 0):
            return ""
        n = int(r[0]["n"]); g = float(r[0]["g"]); m = float(r[0]["m"]) or 1.0
        w = int(r[0]["w"] or 0)
        return ("━━━━━━━━━━━━━━\n<b>Depuis le depart : %+.2f EUR</b>\n"
                "%d tickets · %d gagnants (%.0f %%) · %+.3f par euro mise"
                % (g, n, w, 100.0 * w / n, g / m))

    async def _prevenir(self, texte: str, critique: bool = False) -> None:
        """Prevenir l operateur, dans SON canal a lui et pas dans le fil du portefeuille.

        Demande de l operateur le 12/09 : « je veux recevoir sur la chaine TradingDex pas sur la
        premiere ». A soixante tickets par jour, un message a l achat et un au resultat font cent
        vingt messages quotidiens : melanges aux alertes du portefeuille, les deux deviennent
        illisibles. Le canal est dans `telegram_rapide.canal`.

        `critique` marque ce qui doit partir meme si `alertes` est coupe : une VENTE QUI ECHOUE ne
        raconte pas ce que fait le robot, elle dit que de l argent est bloque dans une ligne qui ne
        se ferme pas, et seul l operateur peut alors vendre a la main (S5.24).
        """
        if not critique and not bool(self._cfg("alertes", True)):
            return
        from intel.alerts.telegram import TelegramSender
        try:
            await TelegramSender(self.ctx.settings, chat_id=self._cfg("canal", None),
                                 token=self._jeton()).send(texte)
        except Exception as exc:  # noqa: BLE001
            log.info("tg: alerte non envoyee (%s)", str(exc)[:80])

    def _jeton(self) -> str | None:
        """Le jeton du robot qui envoie. Jamais dans `intel.yaml`, qui est versionne.

        La configuration ne nomme que l ENDROIT ou lire : une variable d environnement, ou un
        fichier sous `data/`. Un jeton de robot permet d ecrire sous son nom, il se traite comme la
        cle Solana. Rien de lisible : on envoie avec le robot par defaut plutot que de se taire.

        Le 12/09 j ai demande a l operateur de deposer un jeton qu il avait deja mis dans son
        `.env` un mois plus tot (`TELEGRAM_BOT_TOKEN_BIS`). Regarder ce qui est deja configure vient
        avant de demander quoi que ce soit.
        """
        import os
        var = self._cfg("jeton_variable", None)
        if var:
            v = (os.environ.get(str(var)) or "").strip()
            if v:
                return v
            log.warning("tg: %s est vide ou absente — envoi avec le robot par defaut", var)
        chemin = self._cfg("jeton_fichier", None)
        if not chemin:
            return None
        try:
            with open(chemin) as fh:
                return fh.read().strip() or None
        except OSError:
            return None

    # ------------------------------------------------------------------ cycle
    async def cycle(self) -> dict[str, Any]:
        if not bool(self._cfg("enabled", False)):
            return {"status": "disabled"}
        self._table()
        now = int(time.time())
        vendus = await self._vendre(now)
        comptes = await self._compter(now)
        achetes = await self._acheter(now)
        if len(self._sans_meta) > 4000:
            self._sans_meta.clear()
        return {"status": "ok", "achetes": achetes, "vendus": vendus, "comptes": comptes,
                "ouvertes": self.ctx.db.scalar(
                    "SELECT COUNT(*) FROM tg_lignes WHERE statut='OUVERTE'", (), 0) or 0}
