"""Les regles de la strategie « Telegram, quatre minutes », une par une.

La mesure qui la justifie est dans `intel/engines/telegram_rapide.py`. Ce fichier ne teste pas la
mesure, il teste les regles d execution -- celles dont la violation coute de l argent reel :

    on n achete que sur un OUI lu, jamais sur une lecture ratee
    une lecture ratee se rejoue, un « pas de Telegram » ne se rejoue pas
    on n achete pas sans prix d entree frais : sans prix on ne sait pas ce qu on paye
    on vend AVANT d acheter, pour que le plafond de lignes ne bloque jamais une sortie
    le mode `live` sans cle n envoie rien et n ecrit aucune ligne
    une ligne n est fermee qu une fois

Le cinquieme est celui qui compte le plus : le 10/09 au matin une vente demandee n est pas partie
parce qu un second arret d urgence, non trouve, l a refusee en silence (S5.24).
"""
from __future__ import annotations

import asyncio

import pytest

from intel.context import IntelContext
from intel.db.connection import Database
from intel.engines.telegram_rapide import AGE_MIN, TENUE_S, TelegramRapide
from intel.providers.base import ProviderStatusRegistry
from intel.settings import IntelConfig, Settings

MINT_TG = "Tg" + "1" * 42
MINT_SANS = "No" + "2" * 42
MINT_ILLISIBLE = "Il" + "3" * 42


def _ctx(**cfg) -> IntelContext:
    """`cfg` prend des clefs pointees (`telegram_rapide.mode`), qu on replie en dictionnaire.

    IntelConfig lit des dictionnaires imbriques et resout le chemin pointe a la lecture : une clef
    plate y serait acceptee sans erreur et jamais relue -- le test passerait en testant la valeur
    par defaut au lieu de la valeur posee.
    """
    ctx = IntelContext.__new__(IntelContext)
    ctx.settings = Settings.load(db_path=":memory:", telegram_dry_run=True)
    plat = {"telegram_rapide.enabled": True, "telegram_rapide.mode": "paper",
            "telegram_rapide.mise_eur": 10.0, "telegram_rapide.peage_pct": 2.0,
            "telegram_rapide.max_lignes_simultanees": 6}
    plat.update(cfg)
    imbrique: dict = {}
    for chemin, valeur in plat.items():
        noeud = imbrique
        morceaux = chemin.split(".")
        for m in morceaux[:-1]:
            noeud = noeud.setdefault(m, {})
        noeud[morceaux[-1]] = valeur
    ctx.config = IntelConfig(imbrique)
    assert ctx.config.get("telegram_rapide.mode") == plat["telegram_rapide.mode"]
    ctx.db = Database(":memory:")
    ctx.status = ProviderStatusRegistry(ctx.db)
    ctx.rpc = ctx.blockscout = ctx.dex = None  # type: ignore[assignment]
    ctx.db.execute("CREATE TABLE IF NOT EXISTS solana_stream_launches("
                   " mint TEXT PRIMARY KEY, ts INTEGER, signature TEXT, instruction TEXT,"
                   " vu_par_dexscreener INTEGER)")
    ctx.db.execute("CREATE TABLE IF NOT EXISTS solana_prix_chaine("
                   " pair_id TEXT NOT NULL, mint TEXT, ts INTEGER NOT NULL, age_s INTEGER,"
                   " prix_sol REAL, reserve_base REAL, reserve_sol REAL, PRIMARY KEY(pair_id, ts))")
    return ctx


def _moteur(ctx, fiches: dict) -> TelegramRapide:
    """Le moteur, avec la lecture de metadonnee remplacee par un dictionnaire.

    `fiches[mint]` vaut None pour « illisible » et un dict pour une fiche lue.
    """
    m = TelegramRapide(ctx, client=None)
    m.lectures = []

    async def _faux(mint):
        m.lectures.append(mint)
        return fiches.get(mint, None)

    m._telegram = _faux  # type: ignore[method-assign]
    return m


def _lancement(ctx, mint: str, now: int, age_prix: int = 90, prix: float = 1e-6,
               lecture_vieille_de: int = 0) -> None:
    """Un lancement dans la fenetre d entree, avec une lecture de reserve.

    `lecture_vieille_de` vieillit la LECTURE (son horodatage), ce qui n est pas la meme chose que
    vieillir le jeton (`age_prix`) : le moteur refuse sur la premiere et pas sur la seconde.
    """
    ctx.db.execute("INSERT OR REPLACE INTO solana_stream_launches(mint, ts) VALUES(?,?)",
                   (mint, now - AGE_MIN - 10))
    ctx.db.execute("INSERT OR REPLACE INTO solana_prix_chaine"
                   "(pair_id, mint, ts, age_s, prix_sol) VALUES(?,?,?,?,?)",
                   ("pool-" + mint[:6], mint, now - lecture_vieille_de, age_prix, prix))


def _cycle(m, now: int) -> dict:
    """Faire tourner un cycle a une heure choisie.

    On remplace l objet `time` VU PAR LE MODULE, et non `time.time` dans tout le processus : figer
    l horloge globale casse la boucle asyncio qui s en sert pour ses echeances.
    """
    import time as _t
    import types

    import intel.engines.telegram_rapide as mod
    vrai = mod.time
    # `gmtime` reste la VRAIE : seule l heure courante est figee, pas la conversion des dates.
    mod.time = types.SimpleNamespace(time=lambda: now, gmtime=_t.gmtime)  # type: ignore[assignment]
    try:
        return asyncio.run(m.cycle())
    finally:
        mod.time = vrai  # type: ignore[assignment]


NOW = 1_800_000_000


def test_coupe_par_defaut_le_moteur_ne_fait_rien():
    ctx = _ctx(**{"telegram_rapide.enabled": False})
    m = _moteur(ctx, {})
    assert _cycle(m, NOW)["status"] == "disabled"
    assert m.lectures == []


def test_on_achete_seulement_ce_qui_a_un_telegram():
    ctx = _ctx()
    _lancement(ctx, MINT_TG, NOW)
    _lancement(ctx, MINT_SANS, NOW)
    m = _moteur(ctx, {MINT_TG: {"telegram": 1, "twitter": 1, "site": 0, "nom": "TG"},
                      MINT_SANS: {"telegram": 0, "twitter": 1, "site": 0, "nom": "NO"}})
    r = _cycle(m, NOW)
    assert r["achetes"] == 1
    lignes = ctx.db.query("SELECT mint, mode, statut FROM tg_lignes")
    assert [l["mint"] for l in lignes] == [MINT_TG]
    assert lignes[0]["mode"] == "paper" and lignes[0]["statut"] == "OUVERTE"


def test_une_lecture_ratee_n_achete_jamais_et_se_rejoue():
    """Ne pas savoir n est pas « non ». Un filtre qui tranche sur une lecture ratee tire au sort."""
    ctx = _ctx()
    _lancement(ctx, MINT_ILLISIBLE, NOW)
    m = _moteur(ctx, {})                       # aucune fiche : tout est illisible
    assert _cycle(m, NOW)["achetes"] == 0
    assert ctx.db.scalar("SELECT COUNT(*) FROM tg_lignes", (), 0) == 0
    # au cycle suivant le meme jeton est RELU, alors qu un « pas de telegram » ne l aurait pas ete
    m2 = _moteur(ctx, {MINT_ILLISIBLE: {"telegram": 1, "twitter": 0, "site": 0, "nom": "IL"}})
    assert _cycle(m2, NOW + 10)["achetes"] == 1


def test_un_pas_de_telegram_ne_se_rejoue_pas():
    ctx = _ctx()
    _lancement(ctx, MINT_SANS, NOW)
    fiches = {MINT_SANS: {"telegram": 0, "twitter": 0, "site": 0, "nom": "NO"}}
    _cycle(_moteur(ctx, fiches), NOW)
    m2 = _moteur(ctx, fiches)
    _cycle(m2, NOW + 10)
    assert m2.lectures == []                   # relire couterait un appel reseau pour rien


def test_sans_lecture_fraiche_on_n_achete_pas():
    """Sans prix d entree frais on ne sait pas ce qu on paye, donc on ne paye pas."""
    ctx = _ctx()
    _lancement(ctx, MINT_TG, NOW, lecture_vieille_de=600)      # la lecture date de dix minutes
    m = _moteur(ctx, {MINT_TG: {"telegram": 1, "twitter": 0, "site": 0, "nom": "TG"}})
    assert _cycle(m, NOW)["achetes"] == 0
    assert m.lectures == []                    # on n a meme pas depense l appel reseau


def test_un_jeton_vieux_avec_une_lecture_fraiche_reste_achetable():
    """La regle porte sur la fraicheur de la LECTURE. Confondre les deux avait fait tourner le
    moteur une demi-heure sans juger un seul candidat : la fenetre d entree va jusqu a 180 s et le
    plafond portait sur l age du jeton, fixe a 100 s."""
    ctx = _ctx()
    _lancement(ctx, MINT_TG, NOW, age_prix=175, lecture_vieille_de=2)
    m = _moteur(ctx, {MINT_TG: {"telegram": 1, "twitter": 0, "site": 0, "nom": "TG"}})
    assert _cycle(m, NOW)["achetes"] == 1


def test_la_ligne_se_ferme_a_quatre_minutes_avec_le_bon_gain():
    ctx = _ctx()
    _lancement(ctx, MINT_TG, NOW, prix=1.0)
    m = _moteur(ctx, {MINT_TG: {"telegram": 1, "twitter": 0, "site": 0, "nom": "TG"}})
    _cycle(m, NOW)
    plus_tard = NOW + TENUE_S + 5
    ctx.db.execute("INSERT OR REPLACE INTO solana_prix_chaine"
                   "(pair_id, mint, ts, age_s, prix_sol) VALUES(?,?,?,?,?)",
                   ("pool-" + MINT_TG[:6], MINT_TG, plus_tard, 350, 1.5))
    r = _cycle(_moteur(ctx, {}), plus_tard)
    assert r["vendus"] == 1
    l = ctx.db.query("SELECT statut, prix_sortie, gain_eur FROM tg_lignes")[0]
    assert l["statut"] == "FERMEE" and l["prix_sortie"] == pytest.approx(1.5)
    # 10 EUR a x1,5 moins 2 % de peage : 10 * (1,5 * 0,98 - 1) = +4,70
    assert l["gain_eur"] == pytest.approx(4.70, abs=0.01)


def test_la_sortie_lit_le_pool_de_l_entree_et_pas_un_autre():
    """Apparier par POOL, jamais par jeton. Un jeton gradue a plusieurs pools ; melanger un prix
    d entree pris sur l un et un prix de sortie pris sur l autre invente un resultat (S3.43)."""
    ctx = _ctx()
    _lancement(ctx, MINT_TG, NOW, prix=1.0)                 # pool « pool-Tg1111 », entree a 1,0
    _cycle(_moteur(ctx, {MINT_TG: {"telegram": 1, "twitter": 0, "site": 0, "nom": "TG"}}), NOW)
    tard = NOW + TENUE_S + 5
    # un SECOND pool du meme jeton, plus recent et a un tout autre prix
    ctx.db.execute("INSERT OR REPLACE INTO solana_prix_chaine"
                   "(pair_id, mint, ts, age_s, prix_sol) VALUES(?,?,?,?,?)",
                   ("autre-pool", MINT_TG, tard, 400, 50.0))
    ctx.db.execute("INSERT OR REPLACE INTO solana_prix_chaine"
                   "(pair_id, mint, ts, age_s, prix_sol) VALUES(?,?,?,?,?)",
                   ("pool-" + MINT_TG[:6], MINT_TG, tard - 1, 399, 2.0))
    _cycle(_moteur(ctx, {}), tard)
    l = ctx.db.query("SELECT prix_sortie, gain_eur FROM tg_lignes")[0]
    assert l["prix_sortie"] == pytest.approx(2.0)           # pas 50,0
    assert l["gain_eur"] == pytest.approx(9.60, abs=0.01)   # 10 * (2 * 0,98 - 1)


def test_une_ligne_fermee_ne_se_referme_pas():
    ctx = _ctx()
    _lancement(ctx, MINT_TG, NOW, prix=1.0)
    _cycle(_moteur(ctx, {MINT_TG: {"telegram": 1, "twitter": 0, "site": 0, "nom": "TG"}}), NOW)
    tard = NOW + TENUE_S + 5
    assert _cycle(_moteur(ctx, {}), tard)["vendus"] == 1
    assert _cycle(_moteur(ctx, {}), tard + 30)["vendus"] == 0


def test_on_vend_avant_d_acheter_meme_au_plafond():
    """Le plafond de lignes ne doit jamais empecher une SORTIE. Sinon une position mure reste
    coincee parce que d autres sont ouvertes -- exactement la forme de l incident du 10/09."""
    ctx = _ctx(**{"telegram_rapide.max_lignes_simultanees": 1})
    _lancement(ctx, MINT_TG, NOW, prix=1.0)
    _cycle(_moteur(ctx, {MINT_TG: {"telegram": 1, "twitter": 0, "site": 0, "nom": "TG"}}), NOW)
    tard = NOW + TENUE_S + 5
    _lancement(ctx, MINT_SANS, tard, prix=1.0)
    r = _cycle(_moteur(ctx, {MINT_SANS: {"telegram": 1, "twitter": 0, "site": 0, "nom": "NO"}}), tard)
    assert r["vendus"] == 1 and r["achetes"] == 1


def test_le_plafond_de_lignes_simultanees_tient():
    ctx = _ctx(**{"telegram_rapide.max_lignes_simultanees": 2})
    fiches = {}
    for i in range(4):
        mint = "M%d" % i + "z" * 42
        _lancement(ctx, mint, NOW, prix=1.0)
        fiches[mint] = {"telegram": 1, "twitter": 0, "site": 0, "nom": "M%d" % i}
    assert _cycle(_moteur(ctx, fiches), NOW)["achetes"] == 2


def test_alertes_coupees_mais_une_vente_en_echec_previent_toujours():
    """L operateur ne veut pas d un message par achat et par vente (soixante tickets par jour).
    Mais une vente qui echoue ne raconte pas ce que fait le robot : elle dit que de l argent est
    bloque dans une ligne qui ne se ferme pas, et seul l operateur peut alors vendre a la main.
    Couper celle-la serait couper le fil qui a manque la nuit du 10/09 (S5.24)."""
    envoyes: list[str] = []

    canaux: list = []

    class _FauxEnvoyeur:
        def __init__(self, settings, chat_id=None, token=None): canaux.append(chat_id)
        async def send(self, texte): envoyes.append(texte)

    # On intercepte l ENVOI, pas `_prevenir` : remplacer `_prevenir` ferait tester le faux au lieu
    # de la regle. `_prevenir` fait `from intel.alerts.telegram import TelegramSender`, donc c est
    # l attribut du module qu il faut remplacer.
    import intel.alerts.telegram as tg_mod
    vrai = tg_mod.TelegramSender
    tg_mod.TelegramSender = _FauxEnvoyeur  # type: ignore[assignment]
    try:
        coupe = _moteur(_ctx(**{"telegram_rapide.alertes": False}), {})
        asyncio.run(coupe._prevenir("achete quelque chose"))       # routine
        asyncio.run(coupe._prevenir("boucle : +7,69 EUR"))         # routine
        assert envoyes == []
        asyncio.run(coupe._prevenir("VENTE ECHOUEE", critique=True))
        assert envoyes == ["VENTE ECHOUEE"]

        envoyes.clear(); canaux.clear()
        allume = _moteur(_ctx(**{"telegram_rapide.alertes": True,
                                 "telegram_rapide.canal": "-100999"}), {})
        asyncio.run(allume._prevenir("achete quelque chose"))
        assert envoyes == ["achete quelque chose"]
        # et ca part dans SON canal, pas dans le fil du portefeuille
        assert canaux == ["-100999"]
    finally:
        tg_mod.TelegramSender = vrai  # type: ignore[assignment]


def test_le_resultat_reel_se_lit_sur_le_portefeuille():
    """Le 08/09 le carnet a annonce +5,05 EUR sur une ligne payee +2,54 par la chaine : la cotation
    avait raison sur le multiple et tort sur la mise. Le gain d une ligne reelle est la somme des
    deux variations de solde, frais compris, et rien d autre."""
    ctx = _ctx(**{"telegram_rapide.mode": "live"})
    ctx.db.execute(
        "CREATE TABLE IF NOT EXISTS tg_lignes("
        " mint TEXT PRIMARY KEY, symbole TEXT, pair_id TEXT, ts_entree INTEGER, age_entree INTEGER,"
        " prix_entree REAL, mise_eur REAL, jetons TEXT, tx_achat TEXT, ts_sortie INTEGER,"
        " prix_sortie REAL, gain_eur REAL, tx_vente TEXT, statut TEXT, mode TEXT, motif TEXT,"
        " echecs INTEGER DEFAULT 0)")
    ctx.db.execute(
        "INSERT INTO tg_lignes(mint, symbole, ts_entree, mise_eur, tx_achat, tx_vente, ts_sortie,"
        " statut, mode, prix_entree, prix_sortie) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (MINT_TG, "TG", NOW - 300, 10.0, "txA", "txV", NOW - 60, "FERMEE", "live", 1.0, 2.0))

    m = _moteur(ctx, {})
    deltas = {"txA": -0.1050, "txV": +0.1890}      # achat frais compris, puis vente

    class _FauxSol:
        SOL_MINT = "So1"
        @staticmethod
        def rpc_url(): return "http://rpc"
        @staticmethod
        def signer_address(f=None): return "PROPRIO"
        @staticmethod
        async def sol_delta(cl, rpc, tx, owner): return deltas.get(tx)
        @staticmethod
        async def sol_eur(cl): return 100.0

    # `from intel.execution import solana` lit l ATTRIBUT du paquet, pas `sys.modules` : remplacer
    # l entree de `sys.modules` ne changerait rien et le test passerait a cote.
    import intel.execution as paquet
    import intel.execution.solana  # noqa: F401  -- sans cet import l attribut n existe pas encore
    vrai = paquet.solana
    paquet.solana = _FauxSol  # type: ignore[assignment]
    try:
        r = _cycle(m, NOW)
    finally:
        paquet.solana = vrai  # type: ignore[assignment]
    assert r["comptes"] == 1
    # (-0,1050 + 0,1890) SOL x 100 EUR/SOL = +8,40 EUR, et surtout PAS 10 x (2,0 - 1) = +10
    assert ctx.db.query("SELECT gain_eur FROM tg_lignes")[0]["gain_eur"] == pytest.approx(8.40, abs=0.01)


def test_le_jeton_du_robot_se_lit_dans_un_fichier_et_jamais_dans_la_config(tmp_path):
    """Un jeton de robot permet d ecrire sous son nom : il se depose dans un fichier sous `data/`,
    qui n entre pas dans le depot, comme la cle Solana. Absent, on retombe sur le robot par defaut
    au lieu de ne rien envoyer."""
    import os
    f = tmp_path / "jeton"
    f.write_text("  123:ABC  \n", encoding="utf-8")
    m = _moteur(_ctx(**{"telegram_rapide.jeton_fichier": str(f)}), {})
    assert m._jeton() == "123:ABC"                       # lu et nettoye

    # une variable d environnement passe AVANT le fichier : c est la ou vit deja le jeton de
    # l operateur (`TELEGRAM_BOT_TOKEN_BIS`), et je le lui avais redemande pour rien le 12/09.
    os.environ["JETON_POUR_TEST"] = " 999:XYZ "
    try:
        par_var = _moteur(_ctx(**{"telegram_rapide.jeton_variable": "JETON_POUR_TEST",
                                  "telegram_rapide.jeton_fichier": str(f)}), {})
        assert par_var._jeton() == "999:XYZ"
        # variable nommee mais vide : on retombe sur le fichier, pas sur le silence
        os.environ["JETON_POUR_TEST"] = ""
        assert par_var._jeton() == "123:ABC"
    finally:
        os.environ.pop("JETON_POUR_TEST", None)

    absent = _moteur(_ctx(**{"telegram_rapide.jeton_fichier": str(tmp_path / "rien")}), {})
    assert absent._jeton() is None                       # illisible -> robot par defaut
    assert _moteur(_ctx(), {})._jeton() is None          # non configure -> robot par defaut

    vide = tmp_path / "vide"
    vide.write_text("   \n", encoding="utf-8")
    assert _moteur(_ctx(**{"telegram_rapide.jeton_fichier": str(vide)}), {})._jeton() is None


def test_un_achat_refuse_ecrit_l_erreur_entiere():
    """Un message d echec qui ne dit pas pourquoi ne sert a rien. Le 12/09 un achat a echoue sur
    « Error processing Instruction 6: custom program... », coupe juste AVANT le code d erreur."""
    LONG = "Transaction simulation failed: Error processing Instruction 6: " + "x" * 300 + " 0x1771"

    class _S:
        SOL_MINT = "So1"
        @staticmethod
        def rpc_url(): return "http://rpc"
        @staticmethod
        def signer_address(f=None): return "PROPRIO"
        @staticmethod
        async def sol_eur(cl): return 100.0
        @staticmethod
        async def sol_balance(cl, rpc, a): return int(50 * 1e9)
        @staticmethod
        async def prepare_buy(*a, **k): raise RuntimeError(LONG)

    ctx = _ctx(**{"telegram_rapide.mode": "live"})
    _lancement(ctx, MINT_TG, NOW, prix=1.0)
    m = _moteur(ctx, {MINT_TG: {"telegram": 1, "twitter": 0, "site": 0, "nom": "TG"}})
    import intel.execution as paquet
    import intel.execution.solana  # noqa: F401  -- sans cet import l attribut n existe pas encore
    vrai = paquet.solana
    paquet.solana = _S  # type: ignore[assignment]
    try:
        assert _cycle(m, NOW)["achetes"] == 0
    finally:
        paquet.solana = vrai  # type: ignore[assignment]
    e = ctx.db.query("SELECT etape, erreur FROM tg_echecs")
    assert len(e) == 1 and e[0]["etape"] == "achat"
    assert "0x1771" in e[0]["erreur"], "le code d erreur doit survivre a la troncature"


def test_chaque_vente_annonce_le_cumul_depuis_le_depart():
    """Demande de l operateur : un ticket ne veut rien dire, seul le cumul porte l information.
    Une ligne dont le resultat n est pas encore lu sur la chaine ne doit PAS compter comme zero."""
    ctx = _ctx()
    ctx.db.execute(
        "CREATE TABLE IF NOT EXISTS tg_lignes("
        " mint TEXT PRIMARY KEY, symbole TEXT, pair_id TEXT, ts_entree INTEGER, age_entree INTEGER,"
        " prix_entree REAL, mise_eur REAL, jetons TEXT, tx_achat TEXT, ts_sortie INTEGER,"
        " prix_sortie REAL, gain_eur REAL, tx_vente TEXT, statut TEXT, mode TEXT, motif TEXT,"
        " echecs INTEGER DEFAULT 0)")
    m = _moteur(ctx, {})
    assert m._cumul() == ""                       # aucun ticket : on n annonce rien

    for i, (gain, mise, mode) in enumerate(
            [(+14.79, 20.0, "live"), (-3.35, 20.0, "live"), (+7.69, 10.0, "live"),
             (None, 20.0, "live"),                 # pas encore comptee sur la chaine
             (+99.0, 10.0, "paper")]):             # a blanc : hors cumul
        ctx.db.execute(
            "INSERT INTO tg_lignes(mint, symbole, ts_entree, mise_eur, gain_eur, statut, mode)"
            " VALUES(?,?,?,?,?,?,?)", ("M%d" % i, "T%d" % i, NOW, mise, gain, "FERMEE", mode))

    t = m._cumul()
    assert "+19.13 EUR" in t                      # 14,79 - 3,35 + 7,69, sans le papier ni l attente
    assert "3 tickets" in t
    assert "2 gagnants" in t
    assert "+0.383" in t                          # 19,13 / 50 EUR mises


def test_les_heures_exclues_bloquent_l_achat_mais_jamais_la_vente():
    """La tranche 20h-24h UTC est ecartee (voir le module). Mais une heure creuse ne doit pas
    empecher de SORTIR d une ligne ouverte avant : ce serait garder une position quatre heures de
    plus qu il ne faut, exactement l inverse de la strategie."""
    import calendar
    # 21h UTC : dans la tranche exclue
    t21 = calendar.timegm((2026, 9, 12, 21, 30, 0, 0, 0, 0))
    t18 = calendar.timegm((2026, 9, 12, 18, 30, 0, 0, 0, 0))

    ctx = _ctx(**{"telegram_rapide.heures_exclues": [20, 21, 22, 23]})
    _lancement(ctx, MINT_TG, t21, prix=1.0)
    m = _moteur(ctx, {MINT_TG: {"telegram": 1, "twitter": 0, "site": 0, "nom": "TG"}})
    assert _cycle(m, t21)["achetes"] == 0
    assert m.lectures == []                      # on ne depense meme pas l appel reseau

    # a 18h30 le meme jeton est achete
    ctx2 = _ctx(**{"telegram_rapide.heures_exclues": [20, 21, 22, 23]})
    _lancement(ctx2, MINT_TG, t18, prix=1.0)
    m2 = _moteur(ctx2, {MINT_TG: {"telegram": 1, "twitter": 0, "site": 0, "nom": "TG"}})
    assert _cycle(m2, t18)["achetes"] == 1

    # une ligne ouverte a 19h58 se vend bien apres 20h00, en pleine heure exclue
    t_ouv = calendar.timegm((2026, 9, 12, 19, 58, 0, 0, 0, 0))
    t_fin = t_ouv + TENUE_S + 10               # 20h02, dans la tranche exclue
    assert __import__("time").gmtime(t_ouv).tm_hour == 19
    assert __import__("time").gmtime(t_fin).tm_hour == 20
    ctx3 = _ctx(**{"telegram_rapide.heures_exclues": [20, 21, 22, 23]})
    _lancement(ctx3, MINT_TG, t_ouv, prix=1.0)
    m3 = _moteur(ctx3, {MINT_TG: {"telegram": 1, "twitter": 0, "site": 0, "nom": "TG"}})
    _cycle(m3, t_ouv)
    assert ctx3.db.scalar("SELECT COUNT(*) FROM tg_lignes WHERE statut='OUVERTE'", (), 0) == 1
    assert _cycle(_moteur(ctx3, {}), t_fin)["vendus"] == 1

    # liste vide : la regle est annulee
    ctx4 = _ctx(**{"telegram_rapide.heures_exclues": []})
    _lancement(ctx4, MINT_TG, t21, prix=1.0)
    m4 = _moteur(ctx4, {MINT_TG: {"telegram": 1, "twitter": 0, "site": 0, "nom": "TG"}})
    assert _cycle(m4, t21)["achetes"] == 1


def test_le_portefeuille_est_le_frein_et_suit_les_fonds():
    """Un plafond de lignes fixe se regle sur le solde d un jour et se trompe le lendemain. Avant
    chaque achat reel le moteur verifie que le portefeuille peut payer, donc la capacite suit les
    virements toute seule -- et un ordre que la chaine refuserait ne part jamais."""
    appels: list = []

    def _sol(solde_sol: float):
        class _S:
            SOL_MINT = "So1"
            @staticmethod
            def rpc_url(): return "http://rpc"
            @staticmethod
            def signer_address(f=None): return "PROPRIO"
            @staticmethod
            async def sol_eur(cl): return 100.0            # 1 SOL = 100 EUR
            @staticmethod
            async def sol_balance(cl, rpc, a): return int(solde_sol * 1e9)
            @staticmethod
            async def prepare_buy(*a, **k):
                appels.append("achat")
                return {"status": "BUILT", "tx": "TX"}
            @staticmethod
            def sign(tx, f=None): return "SIGNE"
            @staticmethod
            async def send(cl, rpc, s): return "HASH"
        return _S

    import intel.execution as paquet
    import intel.execution.solana  # noqa: F401  -- sans cet import l attribut n existe pas encore
    vrai = paquet.solana
    try:
        # mise de 20 EUR = 0,20 SOL, plus 0,02 de reserve : il faut 0,22 SOL
        for solde, attendu in ((0.15, 0), (0.21, 0), (0.50, 1)):
            appels.clear()
            ctx = _ctx(**{"telegram_rapide.mode": "live", "telegram_rapide.mise_eur": 20.0,
                          "telegram_rapide.reserve_sol": 0.02})
            _lancement(ctx, MINT_TG, NOW, prix=1.0)
            m = _moteur(ctx, {MINT_TG: {"telegram": 1, "twitter": 0, "site": 0, "nom": "TG"}})
            paquet.solana = _sol(solde)  # type: ignore[assignment]
            r = _cycle(m, NOW)
            assert r["achetes"] == attendu, "solde %.2f SOL" % solde
            assert len(appels) == attendu
            # et rien n est ecrit au carnet quand le portefeuille ne suit pas
            assert ctx.db.scalar("SELECT COUNT(*) FROM tg_lignes", (), 0) == attendu
    finally:
        paquet.solana = vrai  # type: ignore[assignment]


def test_mode_live_sans_cle_n_ecrit_aucune_ligne():
    """Deux actes deliberes pour l argent reel. Un seul ne suffit pas, et surtout : un achat reel
    refuse ne doit PAS laisser une ligne ouverte qu une vente irait ensuite chercher."""
    ctx = _ctx(**{"telegram_rapide.mode": "live", "telegram_rapide.cle_fichier": None})
    _lancement(ctx, MINT_TG, NOW, prix=1.0)
    m = _moteur(ctx, {MINT_TG: {"telegram": 1, "twitter": 0, "site": 0, "nom": "TG"}})
    assert _cycle(m, NOW)["achetes"] == 0
    assert ctx.db.scalar("SELECT COUNT(*) FROM tg_lignes", (), 0) == 0


def test_un_achat_refuse_ne_se_compte_pas_comme_achete():
    """Le carnet ne doit jamais annoncer un achat qui n a pas eu lieu (S5.16). Le garde « peut-on
    ressortir » refuse des jetons qui ONT un Telegram : le verdict doit le dire."""
    ctx = _ctx()
    _lancement(ctx, MINT_TG, NOW, prix=1.0)
    m = _moteur(ctx, {MINT_TG: {"telegram": 1, "twitter": 0, "site": 0, "nom": "TG"}})

    async def _refuse(*a, **k):
        return False
    m._ouvrir = _refuse  # type: ignore[method-assign]
    assert _cycle(m, NOW)["achetes"] == 0
    v = ctx.db.query("SELECT verdict, telegram FROM tg_juges WHERE mint=?", (MINT_TG,))[0]
    assert v["telegram"] == 1
    assert v["verdict"] == "telegram mais achat refuse"
    assert ctx.db.scalar("SELECT COUNT(*) FROM tg_lignes", (), 0) == 0


def test_le_livre_note_l_age_VRAI_a_l_achat_et_pas_celui_de_la_lecture():
    """L operateur a vu des achats « a T+50 » alors que la fenetre s ouvre a T+55. Ce n etait pas
    l execution mais le livre : la colonne portait l age du jeton au moment de la LECTURE du prix,
    qui peut dater de 30 s. Les deux ages doivent etre notes separement, sinon toute relecture des
    entrees est fausse."""
    ctx = _ctx()
    # lancement il y a 70 s, mais la lecture de prix date de 12 s et portait alors age_s=58
    ctx.db.execute("INSERT OR REPLACE INTO solana_stream_launches(mint, ts) VALUES(?,?)",
                   (MINT_TG, NOW - 70))
    ctx.db.execute("INSERT OR REPLACE INTO solana_prix_chaine"
                   "(pair_id, mint, ts, age_s, prix_sol) VALUES(?,?,?,?,?)",
                   ("p", MINT_TG, NOW - 12, 58, 1.0))
    m = _moteur(ctx, {MINT_TG: {"telegram": 1, "twitter": 0, "site": 0, "nom": "TG"}})
    assert _cycle(m, NOW)["achetes"] == 1
    l = ctx.db.query("SELECT age_entree, age_lecture FROM tg_lignes")[0]
    assert l["age_entree"] == 70, "l age note doit etre celui de l ACHAT"
    assert l["age_lecture"] == 58, "l age de la lecture doit rester disponible"
    assert l["age_entree"] >= AGE_MIN


def test_on_vise_bien_une_entree_vers_soixante_secondes():
    """Le balayage du 12/09 place le point stable a T+60 : les deux moities y disent la meme chose
    (+0,197 et +0,194) et « sans best » y est le plus haut. T+90 etait herite du filtre
    `trop_propre`, qui avait besoin de quatre releves -- pas d une mesure."""
    from intel.engines import telegram_rapide as mod
    assert 45 <= mod.AGE_MIN <= 70, "la fenetre doit s ouvrir autour de T+60, pas de T+90"
    assert mod.AGE_MAX > mod.AGE_MIN + 60, "il faut de la marge pour rattraper un prix en retard"


def test_la_fenetre_d_entree_est_fermee_avant_et_apres():
    ctx = _ctx()
    fiches = {MINT_TG: {"telegram": 1, "twitter": 0, "site": 0, "nom": "TG"}}
    # trop jeune : le lancement a 10 s, on ne decide pas encore
    ctx.db.execute("INSERT OR REPLACE INTO solana_stream_launches(mint, ts) VALUES(?,?)",
                   (MINT_TG, NOW - 10))
    ctx.db.execute("INSERT OR REPLACE INTO solana_prix_chaine"
                   "(pair_id, mint, ts, age_s, prix_sol) VALUES(?,?,?,?,?)",
                   ("p", MINT_TG, NOW, 10, 1.0))
    assert _cycle(_moteur(ctx, fiches), NOW)["achetes"] == 0
    # trop vieux : le train est parti
    ctx.db.execute("UPDATE solana_stream_launches SET ts=? WHERE mint=?", (NOW - 900, MINT_TG))
    assert _cycle(_moteur(ctx, fiches), NOW)["achetes"] == 0


def test_le_plafond_par_jour_compte_les_lignes_fermees_aussi():
    """Un plafond quotidien qui ne compterait que les lignes ouvertes ne plafonnerait rien : a
    quatre minutes de tenue, il n y a presque jamais de ligne ouverte."""
    ctx = _ctx(**{"telegram_rapide.max_par_jour": 1})
    _lancement(ctx, MINT_TG, NOW, prix=1.0)
    _cycle(_moteur(ctx, {MINT_TG: {"telegram": 1, "twitter": 0, "site": 0, "nom": "TG"}}), NOW)
    tard = NOW + TENUE_S + 5
    _cycle(_moteur(ctx, {}), tard)             # la premiere est fermee
    _lancement(ctx, MINT_SANS, tard, prix=1.0)
    r = _cycle(_moteur(ctx, {MINT_SANS: {"telegram": 1, "twitter": 0, "site": 0, "nom": "NO"}}), tard + 5)
    assert r["achetes"] == 0
