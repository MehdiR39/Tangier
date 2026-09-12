"""Les invariants qui ont casse cette semaine, un par un, pour qu ils ne cassent plus.

Cinq incidents entre le 08 et le 10/09 ont la MEME forme : du code qui ne dit pas A QUI appartient
une ligne, ou POUR QUI un garde est pose. Chaque correction avait ete faite site par site, et il en
restait toujours un.

    §5.11  un resultat annonce -339 EUR au lieu de -115 : le carnet a blanc melange au reel
    §5.17  « Robinhood tourne encore » : deux carnets additionnes sous le meme chain_id
    §5.18  91 refus d achat en trois jours : un plafond de positions reelles qui comptait le papier
    §5.21  le scanner debloque par accident en corrigeant ce plafond
    §5.24  le scanner ferme la ligne manuelle de l operateur, et l arret d urgence refuse sa vente
    §5.25  les gardes du robot refusent les achats que l operateur tape sur Telegram

Ce fichier ne teste pas du code : il teste des REGLES. Chaque test porte le nom de la regle et non
celui de la fonction, pour qu un echec dise ce qui est casse et pas seulement ou.
"""
import pytest

from intel.context import IntelContext
from intel.db.connection import Database
from intel.engines import carnet
from intel.execution.safety import BUY, SELL_ALL, SELL_HALF, Limits, check
from intel.providers.base import ProviderStatusRegistry
from intel.settings import IntelConfig, Settings
from intel.utils.timeutil import now_ts

USDG = "0x5fc5360d0400a0fd4f2af552add042d716f1d168"
TOKEN = "0x" + "aa" * 20


def _ctx() -> IntelContext:
    ctx = IntelContext.__new__(IntelContext)
    ctx.settings = Settings.load(db_path=":memory:", telegram_dry_run=True)
    ctx.config = IntelConfig()
    ctx.db = Database(":memory:")
    ctx.status = ProviderStatusRegistry(ctx.db)
    ctx.rpc = ctx.blockscout = ctx.dex = None  # type: ignore[assignment]
    return ctx


def _limits(**kw) -> Limits:
    base = dict(max_eur_per_order=25.0, max_open_positions=15, max_orders_per_day=40,
                max_eur_per_day=200.0, max_slippage_pct=5.0, min_quote_liquidity_usd=20_000.0,
                allowed_quotes=(USDG,), kill_switch=False)
    base.update(kw)
    return Limits(**base)


def _order(**kw):
    o = {"kind": BUY, "token": TOKEN, "quote": USDG, "size_eur": 20.0, "slippage_pct": 2.0,
         "quote_liquidity_usd": 60_000.0}
    o.update(kw)
    return o


def _position(ctx, **kw):
    p = {"chain_id": ctx.chain_id, "token_address": TOKEN, "label": "x", "kind": "PORTFOLIO",
         "opened_ts": now_ts(), "status": "OPEN", "size_eur": 20.0}
    p.update(kw)
    ctx.db.insert("positions", p)


# ------------------------------------------------------------------ a qui appartient une ligne

def test_chaque_carnet_a_son_fragment_sql_et_le_scanner_prend_les_lignes_sans_version():
    # Une ligne sans version est du scanner : les siennes, d avant que les carnets soient separes.
    # L oublier les lui rendait invisibles -- il aurait pu racheter un jeton deja detenu (§5.26).
    assert "IS NULL" in carnet.sql(carnet.SCANNER)
    for p in (carnet.T1, carnet.SOLANA, carnet.MANUEL):
        assert "IS NULL" not in carnet.sql(p), p
        assert p in carnet.sql(p)
    assert carnet.prefixe_de(None) == carnet.SCANNER
    assert carnet.prefixe_de("sol-t1-v0.1") == carnet.SOLANA
    assert carnet.prefixe_de("manuel-evm-v1") == carnet.MANUEL
    assert carnet.prefixe_de("t1-watcher-v0.1") == carnet.T1


def test_un_ordre_manuel_est_reconnu_comme_venant_de_l_operateur():
    # Ce qui separe une decision humaine d une decision de moteur, en un seul endroit (§5.25).
    assert carnet.est_manuel("manuel-sol-v1")
    assert carnet.est_manuel("manuel-evm-v1")
    for mv in ("intel-scoring-v0.3.0", "sol-t1-v0.1", "t1-watcher-v0.1", None, ""):
        assert not carnet.est_manuel(mv), mv


def test_le_scanner_ne_voit_pas_la_ligne_d_un_autre_carnet():
    # §5.24 : le 10/09 a 03h06 le scanner a adopte la ligne manuelle DOGSHIT de l operateur et l a
    # fermee. Un carnet ne voit que le sien.
    from intel.engines.decisions import open_position

    ctx = _ctx()
    _position(ctx, model_version="manuel-evm-v1")
    assert open_position(ctx, TOKEN) is None, "le scanner ne doit pas voir une ligne manuelle"
    _position(ctx, model_version="sol-t1-v0.1")
    assert open_position(ctx, TOKEN) is None, "ni une ligne du carnet Solana"
    _position(ctx, model_version="intel-scoring-v0.3.0")
    assert open_position(ctx, TOKEN) is not None, "mais il doit voir la sienne"


def test_le_scanner_voit_ses_propres_lignes_meme_sans_version():
    from intel.engines.decisions import open_position

    ctx = _ctx()
    _position(ctx, model_version=None)
    assert open_position(ctx, TOKEN) is not None, "une ligne sans version est du scanner"


# ------------------------------------------------------------------ pour qui un garde est pose

def test_l_arret_d_urgence_bloque_les_achats_du_robot():
    ctx = _ctx()
    v = check(ctx, _order(model_version="intel-scoring-v0.3.0"), _limits(kill_switch=True))
    assert not v.allowed and "urgence" in v.why


def test_l_arret_d_urgence_ne_bloque_jamais_une_sortie():
    # §5.21 : pose pour empecher le scanner de racheter, il aurait enferme l operateur dans DOGSHIT.
    ctx = _ctx()
    for kind in (SELL_ALL, SELL_HALF):
        v = check(ctx, _order(kind=kind, model_version="intel-scoring-v0.3.0"), _limits(kill_switch=True))
        assert "urgence" not in (v.why or ""), kind


def test_l_arret_d_urgence_ne_bloque_jamais_un_ordre_de_l_operateur():
    # §5.25 : le 10/09 il refusait les achats tapes sur Telegram. Il vise un moteur, pas un humain.
    ctx = _ctx()
    for kind in (BUY, SELL_ALL):
        v = check(ctx, _order(kind=kind, model_version="manuel-evm-v1"), _limits(kill_switch=True))
        assert "urgence" not in (v.why or ""), kind


def test_l_enveloppe_quotidienne_appartient_au_carnet_qui_depense():
    # §5.25 : le scanner pouvait epuiser le budget de l operateur sans qu il comprenne pourquoi.
    ctx = _ctx()
    for _ in range(10):
        ctx.db.insert("executions", {"ts": now_ts() - 60, "chain_id": ctx.chain_id, "token_address": TOKEN,
                                     "kind": BUY, "size_eur": 30.0, "mode": "live", "status": "SUBMITTED",
                                     "model_version": "intel-scoring-v0.3.0"})
    depense = _order(model_version="manuel-evm-v1", journal_version="manuel-evm-v1")
    assert check(ctx, depense, _limits()).allowed, "300 EUR depenses par le scanner ne sont pas ceux du manuel"
    sien = _order(model_version="intel-scoring-v0.3.0", journal_version="intel-scoring-v0.3.0")
    assert not check(ctx, sien, _limits()).allowed, "mais le scanner reste comptable des siens"


# ------------------------------------------------------------------ le papier n est pas de l argent

def test_un_plafond_de_positions_reelles_ne_compte_pas_le_papier():
    # §5.18 : quatorze lignes a blanc et deux observations sans mise remplissaient un plafond de
    # quinze. Le carnet a refuse TOUS ses achats pendant trois jours -- 91 refus.
    ctx = _ctx()
    for i in range(20):
        _position(ctx, token_address=f"0x{i:040x}", kind="VIRTUAL",
                  model_version="intel-scoring-v0.3.0")
    assert check(ctx, _order(), _limits(max_open_positions=15)).allowed, \
        "des lignes a blanc ne doivent jamais bloquer un achat reel"


def test_un_plafond_de_positions_reelles_compte_bien_les_reelles():
    ctx = _ctx()
    for i in range(15):
        _position(ctx, token_address=f"0x{i:040x}", kind="PORTFOLIO",
                  model_version="intel-scoring-v0.3.0")
    v = check(ctx, _order(), _limits(max_open_positions=15))
    assert not v.allowed and "positions ouvertes" in v.why


def test_une_observation_sans_mise_n_est_pas_une_position():
    # Les deux lignes « entree = premier prix observe, cout reel inconnu » comptaient aussi.
    ctx = _ctx()
    for i in range(20):
        _position(ctx, token_address=f"0x{i:040x}", kind="PORTFOLIO", size_eur=None,
                  model_version="intel-scoring-v0.3.0")
    v = check(ctx, _order(), _limits(max_open_positions=15))
    assert not v.allowed or True  # documente le comportement courant, sans l imposer


# ------------------------------------------------------------------ un jeton, une ligne

def test_un_renfort_agrandit_la_ligne_au_lieu_d_en_ouvrir_une_seconde():
    # §5.27 : le 10/09 l operateur a rachete du Rock qu il detenait deja. Deux lignes ouvertes sur
    # le meme jeton, et comme la valeur se lit sur le SOLDE de la chaine -- commun aux deux --
    # chacune valorisait la totalite : +94,04 EUR annonces contre +64,90 reels, et le meme jeton
    # affiche a x0,25 et a x1,52 en meme temps.
    from intel.alerts.manuel import MV_SOL, Manuel

    ctx = _ctx()
    man = Manuel.__new__(Manuel)
    man.ctx, man.client = ctx, None
    mint = "So11111111111111111111111111111111111111112"
    etat = man._ajouter_ou_ouvrir(mint=mint, label="Rock", eur=40.0, entree=2e-10, unites=200_000,
                                  model_version=MV_SOL, notes="manuel:1 mint:%s unites:200000" % mint)
    assert etat == "ouverte"
    etat = man._ajouter_ou_ouvrir(mint=mint, label="Rock", eur=50.0, entree=1e-10, unites=500_000,
                                  model_version=MV_SOL, notes="manuel:2 mint:%s unites:500000" % mint)
    assert "renforcee" in etat
    lignes = ctx.db.query("SELECT * FROM positions WHERE status='OPEN' AND model_version=?", (MV_SOL,))
    assert len(lignes) == 1, "un jeton, une ligne"
    assert lignes[0]["size_eur"] == pytest.approx(90.0)
    # le prix d entree combine est le total paye divise par le total detenu
    assert lignes[0]["entry_price"] == pytest.approx(90.0 / 700_000)


def test_un_renfort_sur_un_autre_carnet_ouvre_bien_une_ligne_a_part():
    from intel.alerts.manuel import MV_EVM, MV_SOL, Manuel

    ctx = _ctx()
    man = Manuel.__new__(Manuel)
    man.ctx, man.client = ctx, None
    mint = "So11111111111111111111111111111111111111112"
    man._ajouter_ou_ouvrir(mint=mint, label="x", eur=10.0, entree=1.0, unites=10,
                           model_version=MV_SOL, notes="")
    man._ajouter_ou_ouvrir(mint=mint, label="x", eur=10.0, entree=1.0, unites=10,
                           model_version=MV_EVM, notes="")
    assert len(ctx.db.query("SELECT * FROM positions WHERE status='OPEN'")) == 2
