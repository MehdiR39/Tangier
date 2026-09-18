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


def _moteur(regle="risque", seuil=0.2694):
    m = mr.ModeleRapide.__new__(mr.ModeleRapide)
    m._cfg = lambda cle, defaut: {"regle": regle, "seuil_risque": seuil}.get(cle, defaut)
    return m


def test_regle_risque_seul():
    """La regle en service : le seuil p80 du modele, rien d autre."""
    m = _moteur("risque")
    assert m.retenu({}, 0.2694) is True, "le seuil est inclusif"
    assert m.retenu({}, 0.2695) is False
    assert m.retenu({"depuis_min": 0.9}, 0.10) is True, "depuis_min ne joue PAS dans cette regle"


def test_regle_bas_bande_exige_les_deux_conditions():
    m = _moteur("bas_bande")
    assert m.retenu({"depuis_min": 0.0}, 0.25) is True
    assert m.retenu({"depuis_min": 1e-12}, 0.20) is True
    assert m.retenu({"depuis_min": 0.0}, 0.19) is False
    assert m.retenu({"depuis_min": 0.0}, 0.35) is False, "0,35 est exclu, la bande est [0,20 ; 0,35["
    assert m.retenu({"depuis_min": 0.02}, 0.25) is False


def test_une_regle_inconnue_n_achete_RIEN():
    """Une faute de frappe dans la config ne doit jamais faire acheter au hasard."""
    assert _moteur("nimportequoi").retenu({"depuis_min": 0.0}, 0.25) is False


def test_un_nan_ne_passe_jamais():
    """Une comparaison avec NaN est toujours fausse : sans garde-fou le ticket passerait en silence."""
    m = _moteur("bas_bande")
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


def test_un_seul_message_porte_un_chiffre():
    """Le message de vente repeterait le cumul PRECEDENT : le ticket semblerait compte deux fois."""
    src = inspect.getsource(mr.ModeleRapide._sortir)
    assert "_cumul()" not in src, "la vente ne doit pas afficher de cumul, il n est pas encore a jour"
    assert "_cumul()" in inspect.getsource(mr.ModeleRapide._compter), \
        "le cumul s affiche au COMPTAGE, seul instant ou il est juste"


def test_un_ticket_bloque_par_le_plafond_ne_compte_pas_comme_un_ordre():
    """Sinon le plafond se verrouille TOUT SEUL : les lignes fantomes entrent dans la fenetre
    glissante plus vite que les vrais ordres n en sortent, et la reprise du lendemain n arrive
    jamais. Constate en production le 18/09 : 40 ordres reels, 46 comptes."""
    src = inspect.getsource(mr.ModeleRapide.cycle)
    i_bloque = src.index("if live and bloque:")
    bloc = src[i_bloque:i_bloque + 700]
    assert "BLOQUEE" in bloc, "un ticket bloque doit avoir son propre statut"
    assert "ts_entree" not in bloc, "une ligne bloquee ne doit PAS porter de ts_entree"
    assert "continue" in bloc, "elle ne doit pas poursuivre vers l achat"
    # l ACHAT lui-meme ne doit plus etre conditionne au plafond : on n atteint cette ligne que si
    # le garde-fou ci-dessus a laisse passer. Un `if not bloque` a cet endroit signifierait que la
    # ligne OUVERTE est ecrite meme quand le plafond bloque -- le defaut qu on corrige ici.
    i_achat = src.index("await self._acheter_reel(")
    ligne_achat = src[src.rindex("\n", 0, i_achat):i_achat]
    assert "bloque" not in ligne_achat, "l achat ne doit plus dependre du plafond a cet endroit"


def test_une_ligne_sans_ordre_ne_reste_jamais_ouverte():
    """`_sortir` exige un tx_achat : une ligne OUVERTE sans ordre ne serait jamais fermee."""
    src = inspect.getsource(mr.ModeleRapide.cycle)
    i = src.index('"OUVERTE"')
    avant = src[:i]
    # l insertion OUVERTE doit etre precedee du garde-fou du plafond
    assert "if live and bloque:" in avant


def test_le_frein_ne_compte_que_les_tickets_clotures():
    """Compter un ticket encore ouvert serait lire l avenir."""
    src = inspect.getsource(mr.ModeleRapide.frein_ouvert)
    assert "d.t_dec + ? <= ?" in src, "seuls les tickets dont la SORTIE est passee comptent"
    assert "brut_240 IS NOT NULL" in src, "un resultat pas encore lu ne doit pas compter"


def test_le_frein_lit_le_carnet_PAPIER_pas_le_reel():
    """Lu sur le carnet reel il se bloque en boucle : pour se rouvrir il faut un ticket gagnant,
    pour avoir un ticket il faut qu il s ouvre. Constate en production le 18/09. Et une source
    clairsemee le neutralise (+0,27 % contre +1,77 % en source dense, hors echantillon)."""
    import re
    src = inspect.getsource(mr.ModeleRapide.frein_ouvert)
    # on vise le SQL, pas la prose : `mr_lignes` est cite dans le commentaire qui explique
    # justement pourquoi on ne l utilise pas
    lues = {m.lower() for m in re.findall(r"FROM\s+(\w+)", src, re.I)}
    assert "mr_lignes" not in lues, "le frein ne doit PAS lire le carnet reel, or il vise %s" % sorted(lues)
    assert "decision" in lues, "il lit papier_combo"
    assert "mode=ro" in src, "et en lecture seule"


def test_le_frein_laisse_passer_en_cas_de_doute():
    """Un garde-fou qui bloque quand il ne sait pas finirait par tout bloquer en silence."""
    src = inspect.getsource(mr.ModeleRapide.frein_ouvert)
    assert "len(lignes) < fen" in src and "return True" in src
    i = src.index("except Exception")
    assert "return True" in src[i:i+300], "une table illisible doit ouvrir le frein, pas le fermer"


def test_le_frein_ne_choisit_pas_les_jetons():
    """Il suspend l achat ; la selection reste dans `retenu`."""
    assert "frein" not in inspect.getsource(mr.ModeleRapide.retenu)
    src = inspect.getsource(mr.ModeleRapide.cycle)
    assert "self.frein_ouvert(now)" in src
    assert "'FREIN'" in src or '"FREIN"' in src, "un ticket freine garde sa trace"


def test_le_plafond_d_ordres_peut_etre_desactive():
    """`max_ordres_jour: 0` doit DESACTIVER le plafond, pas le mettre a zero -- sinon il bloquerait
    tout. Le plafond en nombre d ordres n a jamais ete demande par l operateur ; seul le BUDGET
    de perte l a ete."""
    src = inspect.getsource(mr.ModeleRapide.cycle)
    assert "max_jour > 0 and n_jour >= max_jour" in src, \
        "un max_jour de 0 doit desactiver le plafond, pas tout bloquer"
    assert '"max_ordres_jour", 0' in src, "le defaut doit etre : pas de plafond d ordres"
    # la protection en EUROS, elle, reste inconditionnelle
    assert "perte_jour <= -perte_max" in src
