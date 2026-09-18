"""Garde-fous du moteur qui achete sur le modele.

Ce module peut SIGNER. Ce qu on protege, dans l ordre d importance :
  1. il faut TROIS choses pour qu il envoie un ordre -- enabled, mode live, et une cle ;
  2. la regle est bien « depuis_min == 0 ET 0,20 <= risque < 0,35 », et un NaN ne passe JAMAIS ;
  3. il n y a NI stop NI prise de gain -- ils coutent 6,6 pts par ticket, les remettre serait une
     regression silencieuse ;
  4. les plafonds (ordres par jour, perte par jour) sont lus AVANT toute decision ;
  5. il n ecrit que dans sa propre table.
"""
from __future__ import annotations

import inspect

from intel.engines import modele_rapide as mr


def test_la_regle_exige_les_deux_conditions():
    m = mr.ModeleRapide.__new__(mr.ModeleRapide)
    # au plus bas ET dans la bande -> retenu
    assert m.retenu({"depuis_min": 0.0}, 0.25) is True
    assert m.retenu({"depuis_min": 1e-12}, 0.20) is True
    # au plus bas mais hors bande -> refuse
    assert m.retenu({"depuis_min": 0.0}, 0.19) is False
    assert m.retenu({"depuis_min": 0.0}, 0.35) is False, "0,35 est exclu, la bande est [0,20 ; 0,35["
    # dans la bande mais pas au plus bas -> refuse
    assert m.retenu({"depuis_min": 0.02}, 0.25) is False


def test_un_nan_ne_passe_jamais():
    """Une comparaison avec NaN est toujours fausse : sans garde-fou le ticket passerait en silence."""
    m = mr.ModeleRapide.__new__(mr.ModeleRapide)
    assert m.retenu({"depuis_min": float("nan")}, 0.25) is False
    assert m.retenu({}, 0.25) is False
    assert m.retenu({"depuis_min": None}, 0.25) is False


def test_aucun_stop_ni_prise_de_gain_dans_le_code():
    """Les deux seuils coutent 6,6 pts par ticket. Leur absence est une DECISION, pas un oubli."""
    src = inspect.getsource(mr)
    for interdit in ("take_profit", "stop_loss", "prise_de_gain"):
        assert interdit not in src, "%s reintroduit : il coute 6,6 pts par ticket" % interdit
    # la sortie est bien a duree fixe
    assert mr.TENUE_S == 240


def test_la_bande_et_l_age_sont_ceux_de_la_recherche():
    assert mr.BANDE == (0.20, 0.35)
    assert mr.A == 45, "la decision se prend a 45 s, comme dans papier_combo"
    assert mr.EXEC_S == 2, "l entree est a 47 s, comme dans la recherche"


def test_trois_actes_necessaires_pour_signer():
    """enabled, mode live, et une cle. Le code doit exiger les trois."""
    src = inspect.getsource(mr.ModeleRapide.cycle)
    assert 'self._cfg("mode", "paper")' in src, "le mode doit etre lu, et defaut a paper"
    assert '"live"' in src
    achat = inspect.getsource(mr.ModeleRapide._acheter_reel)
    assert "signer_address" in achat and "aucune cle" in achat, \
        "sans cle, aucun ordre ne doit partir et la ligne doit etre annulee"


def test_les_plafonds_sont_lus_avant_la_decision():
    """Un plafond verifie apres coup ne protege de rien."""
    src = inspect.getsource(mr.ModeleRapide.cycle)
    i_plafond = src.index("max_ordres_jour")
    i_decision = src.index("self.retenu(")
    assert i_plafond < i_decision, "les plafonds doivent etre evalues avant toute decision"
    assert "max_perte_jour_eur" in src


def test_n_ecrit_que_dans_sa_propre_table():
    """On cherche les tables VISEES par du SQL, pas le mot dans une phrase."""
    import re
    src = inspect.getsource(mr)
    cibles = set()
    for motif in (r"INSERT\s+(?:OR\s+\w+\s+)?INTO\s+(\w+)", r"UPDATE\s+(\w+)\s+SET",
                  r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)", r"DELETE\s+FROM\s+(\w+)"):
        cibles |= {m.lower() for m in re.findall(motif, src, re.I)}
    assert cibles == {"mr_lignes"}, "il n ecrit que dans mr_lignes, or il vise %s" % sorted(cibles)


def test_l_ordre_trop_gros_pour_le_pool_est_refuse():
    """Le garde-fou historique : un ordre de plus de 15 % du pool n est pas executable."""
    src = inspect.getsource(mr.ModeleRapide._variables)
    assert "0.15" in src, "la limite d impact a 15 % du pool doit rester"


def test_mode_paper_par_defaut():
    """Le defaut doit etre inoffensif : si la config manque, on ne signe pas."""
    src = inspect.getsource(mr.ModeleRapide.cycle)
    assert '"mode", "paper"' in src


def test_vendre_et_compter_ne_sont_jamais_bloques_par_un_plafond():
    """Un plafond doit arreter les ACHATS, jamais les ventes -- sinon il cree le risque qu il evite."""
    src = inspect.getsource(mr.ModeleRapide.cycle)
    i_bloque = src.index("bloque = live and")
    i_sortir = src.index("await self._sortir(now)")
    ligne = src[src.rindex("\n", 0, i_sortir):i_sortir]
    assert "not bloque" not in ligne, "la vente ne doit pas dependre du plafond"
    assert "await self._compter(now)" in src, "sans comptage, le plafond de perte ne se declenche jamais"


def test_le_pnl_se_lit_sur_le_solde_du_portefeuille():
    """Jamais sur une cotation : le 08/09 le carnet annonçait +5,05 EUR pour +2,54 reels."""
    src = inspect.getsource(mr.ModeleRapide._compter)
    assert "sol_delta" in src and "tx_achat" in src and "tx_vente" in src
    assert "prix_sortie" not in src, "le gain ne se calcule pas a partir d un prix"


def test_le_taux_sol_est_lu_sur_le_marche():
    """Un taux en dur est une erreur comptable silencieuse (08/09 : 180 EUR contre 96 reels)."""
    src = inspect.getsource(mr.ModeleRapide._acheter_reel)
    assert "await sol.sol_eur(" in src
    assert "sol_eur=taux" in src
    assert "taux SOL illisible" in src, "si le taux manque, l achat doit etre reporte"


def test_une_vente_qui_echoue_alerte_au_lieu_de_boucler_en_silence():
    """Une position invendable est de l argent BLOQUE : seul l operateur peut vendre a la main."""
    src = inspect.getsource(mr.ModeleRapide._echec_vente)
    assert "critique=True" in src, "l alerte doit partir meme si les alertes sont coupees"
    assert "1800" in src, "il faut un frein : sinon 700 messages par heure"
    assert "n == 3" in src, "on alerte au 3e echec, pas au premier"
    # et le compteur doit etre remis a zero quand la vente finit par passer
    assert "self._echecs.pop(" in inspect.getsource(mr.ModeleRapide._sortir)


def test_un_solde_illisible_ne_passe_pas_en_silence():
    """Le `continue` muet d origine aurait boucle indefiniment sans rien dire."""
    src = inspect.getsource(mr.ModeleRapide._sortir)
    i = src.index("token_balance")
    assert "_echec_vente" in src[i:i + 400], "un solde illisible doit compter comme un echec de vente"
