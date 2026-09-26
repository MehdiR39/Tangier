"""Garde-fous du SUIVEUR G+D -- la seconde instance du moteur, sur sa propre table.

Le suiveur peut SIGNER, et il partage sa classe avec la production. Ce qu on protege, dans l ordre
d importance :

  1. LA PRODUCTION EST INCHANGEE. Toutes les requetes du module nomment toujours `mr_lignes` en
     clair ; c est `_sql` qui substitue la table de l instance. Avec la table par defaut, la
     substitution doit etre un NON-OPERANT -- sinon on a modifie le SQL d un moteur qui tient de
     l argent reel sans le savoir.
  2. LE SUIVEUR N INVENTE RIEN. Il n achete QUE ce que `papier_gd_direct` a marque `pris=1`. Un
     ticket que ce carnet a ecarte -- foule, coffre, tendance, sa propre pause -- ne doit jamais
     passer.
  3. IL SE TAIT QUAND IL NE SAIT PAS. Carnet fige, base illisible, pair absente : la reponse est
     NON. Un `except` qui rendrait True ferait acheter tout ce qui passe -- l erreur exacte qui a
     coute 15,69 EUR le 22/09 sur le cout de la pause.
  4. IL CEDE LE JETON QUE LA PRODUCTION TIENT. 79 % des jetons de G+D sont dans la bande
     0,20-0,35 : sans cette cession, deux lignes porteraient le meme mint et le P&L lu au solde du
     portefeuille deviendrait inattribuable. Et c est le SUIVEUR qui cede, jamais la production.
  5. LA PRISE DE GAIN RESTE DESARMEE POUR LA PRODUCTION. `prise_gain_x` fait partie de la regle
     gelee de G+D (148 de ses 294 sorties), mais sur `BANDE + PAUSE` stop et prise de gain coutent
     6,6 points par ticket. Les y voir apparaitre serait une regression silencieuse.
"""
from __future__ import annotations

import sqlite3

from intel.engines import modele_rapide as mr


def test_la_bande_est_configurable_et_son_defaut_est_celui_de_la_production():
    """Adopter un modele reentraine impose de changer la bande EN MEME TEMPS : un modele frais
    redistribue ses scores, donc [0,20 ; 0,35] designerait d autres jetons."""
    m = _moteur(cfg={"regle": "bande"})
    assert m._bande() == mr.BANDE, "sans config, on garde la bande de la production"
    m2 = _moteur(cfg={"regle": "bande", "bande": [0.17763490200673798, 0.3920447192432126]})
    assert m2._bande() == (0.17763490200673798, 0.3920447192432126)
    assert m2.retenu({}, 0.18) is True, "0,18 est dans la bande fraiche, pas dans celle en service"
    assert m2.retenu({}, 0.36) is True, "0,36 est dans la bande fraiche, pas dans celle en service"
    assert m2.retenu({}, 0.17) is False
    assert m2.retenu({}, 0.40) is False


def test_la_bande_est_lue_AUX_DEUX_ENDROITS():
    """La regle d achat ET la requete de la pause. Ne la changer qu a un seul endroit ferait
    acheter dans une bande et surveiller les clotures d une AUTRE -- la pause ne serait plus celle
    qui a ete mesuree, et rien ne le signalerait."""
    import inspect
    src = inspect.getsource(mr.ModeleRapide.pause_ouverte)
    assert "self._bande()" in src, "la PAUSE lit encore la bande en dur"
    assert "BANDE[0]" not in src and "BANDE[1]" not in src, "reste un usage en dur dans la pause"
    achat = inspect.getsource(mr.ModeleRapide.retenu)
    assert "self._bande()" in achat, "la regle d achat lit encore la bande en dur"


def _moteur(table="gd_lignes", cfg=None, base=None):
    m = mr.ModeleRapide.__new__(mr.ModeleRapide)
    m.table, m.prefixe = table, "suiveur_gd"
    conf = {"regle": "gd_suiveur", "gd_fraicheur": 900.0}
    conf.update(cfg or {})
    m._cfg = lambda cle, defaut: conf.get(cle, defaut)
    m._base = base
    return m


# --- 1. la production est inchangee -----------------------------------------------------------

def test_table_par_defaut_ne_reecrit_rien():
    """Avec `mr_lignes`, la substitution est un non-operant : le SQL de la production est le meme."""
    m = _moteur(table="mr_lignes")
    for sql in ("SELECT mint FROM mr_lignes",
                "INSERT OR IGNORE INTO mr_lignes(mint, pair) VALUES(?,?)",
                "UPDATE mr_lignes SET statut='OUVERTE' WHERE mint=?",
                "SELECT ts FROM solana_prix_chaine WHERE ts > ?"):
        assert m._sql(sql) == sql


def test_table_du_suiveur_redirige_bien():
    m = _moteur(table="gd_lignes")
    assert m._sql("SELECT mint FROM mr_lignes") == "SELECT mint FROM gd_lignes"
    # les autres tables ne sont PAS touchees : le suiveur lit le meme flux de prix que la production
    assert m._sql("SELECT ts FROM solana_prix_chaine") == "SELECT ts FROM solana_prix_chaine"


def test_le_nom_d_index_est_reecrit_lui_aussi():
    """Un nom d index est GLOBAL dans SQLite. Sans cette reecriture, `IF NOT EXISTS` trouverait le
    nom deja pris par `mr_lignes` et la table du suiveur resterait SANS index, en silence."""
    m = _moteur(table="gd_lignes")
    assert m._sql("CREATE INDEX IF NOT EXISTS i_mr_statut ON mr_lignes(statut)") == \
        "CREATE INDEX IF NOT EXISTS i_gd_lignes_statut ON gd_lignes(statut)"
    prod = _moteur(table="mr_lignes")
    assert prod._sql("CREATE INDEX IF NOT EXISTS i_mr_statut ON mr_lignes(statut)") == \
        "CREATE INDEX IF NOT EXISTS i_mr_statut ON mr_lignes(statut)", "la production garde son index"


def test_les_requetes_du_module_nomment_toujours_mr_lignes():
    """Aucune requete n a ete reecrite a la main : c est ce qui rend la substitution sure."""
    src = inspect_source()
    assert "FROM gd_lignes" not in src and "INTO gd_lignes" not in src, (
        "une requete code la table du suiveur en dur : la substitution ne la protege plus")


def inspect_source():
    import inspect
    return inspect.getsource(mr)


# --- 2 et 3. le suiveur n achete que ce que le carnet papier a pris --------------------------

def _carnet(tmp_path, lignes, t_dernier):
    """Un faux `papier_gd.sqlite` : (pair, pris) et l instant de la derniere decision."""
    p = tmp_path / "papier_gd.sqlite"
    c = sqlite3.connect(str(p))
    c.execute("CREATE TABLE decision(pair TEXT, t_dec REAL, pris INTEGER)")
    for pair, pris in lignes:
        c.execute("INSERT INTO decision VALUES(?,?,?)", (pair, t_dernier, pris))
    c.commit()
    c.close()
    return str(p)


def test_achete_ce_que_le_carnet_a_pris(tmp_path, monkeypatch):
    import intel.utils.timeutil as tu
    monkeypatch.setattr(tu, "now_ts", lambda: 1000.0)
    chemin = _carnet(tmp_path, [("POOL_OUI", 1), ("POOL_NON", 0)], 999.0)
    m = _moteur(cfg={"gd_db": chemin})
    assert m.retenu({}, 0.5, pair="POOL_OUI") is True
    assert m.retenu({}, 0.5, pair="POOL_NON") is False, "un ticket ecarte par le carnet n est pas achete"
    assert m.retenu({}, 0.5, pair="INCONNU") is False
    assert m.retenu({}, 0.5, pair=None) is False, "sans pair on ne peut rien verifier : donc NON"


def test_carnet_fige_fait_taire_le_suiveur(tmp_path, monkeypatch):
    """Le processus papier est mort : sa table ne bouge plus. On n achete pas a l aveugle."""
    import intel.utils.timeutil as tu
    monkeypatch.setattr(tu, "now_ts", lambda: 10_000.0)
    chemin = _carnet(tmp_path, [("POOL_OUI", 1)], 999.0)     # 9 001 s de retard
    m = _moteur(cfg={"gd_db": chemin, "gd_fraicheur": 900.0})
    assert m.retenu({}, 0.5, pair="POOL_OUI") is False


def test_base_illisible_ne_fait_pas_acheter():
    m = _moteur(cfg={"gd_db": "/chemin/qui/n/existe/pas.sqlite"})
    assert m.retenu({}, 0.5, pair="POOL_OUI") is False


def test_carnet_vide_ne_fait_pas_acheter(tmp_path):
    chemin = _carnet(tmp_path, [], 0.0)
    m = _moteur(cfg={"gd_db": chemin})
    assert m.retenu({}, 0.5, pair="POOL_OUI") is False


# --- 4. la cession du jeton deja tenu par la production --------------------------------------

class _FausseBase:
    def __init__(self, mints):
        self.mints = mints

    def query(self, sql, params=()):
        return [{"1": 1}] if str(params[0]) in self.mints else []


def test_le_suiveur_cede_le_jeton_tenu_par_la_production():
    m = _moteur(table="gd_lignes", base=_FausseBase({"DEJA"}))
    assert m._mint_deja_en_prod("DEJA") is True
    assert m._mint_deja_en_prod("LIBRE") is False


def test_la_production_ne_cede_jamais():
    """Elle n a pas ete modifiee : avec sa table, la question ne se pose meme pas."""
    m = _moteur(table="mr_lignes", base=_FausseBase({"DEJA"}))
    assert m._mint_deja_en_prod("DEJA") is False


# --- 5. la prise de gain reste desarmee pour la production -----------------------------------

def test_prise_de_gain_desarmee_par_defaut():
    """Sans `prise_gain_x`, aucune lecture de prix n est meme faite : la production tient 240 s."""
    m = _moteur(table="mr_lignes", cfg={})
    m._q = lambda *a, **k: (_ for _ in ()).throw(AssertionError("la production a lu les prix !"))
    assert m._gain_atteint(1000.0) == set()


def test_prise_de_gain_desarmee_si_none_ou_un():
    for v in (None, 0, 0.0, 1.0):
        m = _moteur(cfg={"prise_gain_x": v})
        m._q = lambda *a, **k: (_ for _ in ()).throw(AssertionError("lecture de prix inattendue"))
        assert m._gain_atteint(1000.0) == set(), "prise_gain_x=%r doit desarmer" % (v,)


def test_prise_de_gain_declenche_au_bon_multiple():
    """x1,25 : on sort a +25 %, pas a +24 %. C est le seuil de la regle gelee de G+D."""
    lignes = [{"mint": "M1", "pair": "P1", "prix_entree": 100.0, "ts_entree": 500.0},
              {"mint": "M2", "pair": "P2", "prix_entree": 100.0, "ts_entree": 500.0}]
    hauts = {"P1": 125.0, "P2": 124.0}

    m = _moteur(cfg={"prise_gain_x": 1.25, "tenue_secondes": 240.0})

    def q(sql, params=()):
        if "MAX(prix_sol)" in sql:
            return [{"p": hauts[str(params[0])]}]
        return lignes
    m._q = q
    assert m._gain_atteint(600.0) == {"M1"}
