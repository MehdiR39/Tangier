"""LA table standard : tout ce qui a reellement tourne, par jour, avec la derniere journee coupee
en deux -- avant et depuis le dernier point -- pour voir ce que les nouveaux tickets ont apporte.

Usage : python table_std.py [heure de coupe, ex 14:44]
"""
import sqlite3, json, sys, os, datetime as dt
import statistics as _st
MISE = float(os.environ.get("MISE", "25"))
CAUTION = os.environ.get("CAUTION", "recuperee") == "payee"   # Mido, 19/09 09h30 : la table ENTIERE en caution recuperee (CAUTION=payee pour l ancien chiffre)
V, SOL_EUR, PRIO, PROTO, DEPOT = 17.5845, 0.31/30.0, 0.048, 0.0111, 0.00203928
_K = [1.0]
def cout(q):
    """Cout PAR TICKET : frais de pool + priorite + impact selon la taille du coffre, recale
    pour que sa moyenne a 30 EUR vaille les 2,62 pts mesures sur 236 tickets reels."""
    return _K[0]*(PROTO + PRIO/MISE + 2*SOL_EUR*MISE/((q or 0)+V) + (DEPOT/(SOL_EUR*MISE) if CAUTION else 0))
from collections import defaultdict
sys.path.insert(0, "/app/intel/research")
import papier_gd_direct as P
from papier_combo import BANDE, GEL_BANDE, GEL_BP, appliquer_pause, TENUE_S
from ensemble import Ensemble, GEL_ENSEMBLE, CHEMIN, CHEMIN_FORET
import os as _os
GEL_DETENTEURS = 1789693200.0
CHEMIN_DET = _os.environ.get("DETENTEURS_VIDAGE", "/app/data/recherche/balayage/detenteurs_vidage.json")
from piste_foule import GEL_FOULE, SEUIL_FOULE

# La coupe est l heure du TABLEAU PRECEDENT, pas une heure fixe : l operateur veut voir ce qui
# s est ajoute depuis la derniere fois qu il a regarde. On la retient dans un fichier pour ne pas
# avoir a s en souvenir, et on l ecrase a la fin par l heure du tableau qu on vient de sortir.
MEMO = "/app/db/table_corrigee_dernier.txt"
import os
if len(sys.argv) > 1:
    COUPE_H = sys.argv[1]
elif os.path.exists(MEMO):
    COUPE_H = open(MEMO).read().strip()
else:
    COUPE_H = "00:00"
hh, mm = (int(x) for x in COUPE_H.split(":"))
auj = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=2)
COUPE = dt.datetime(auj.year, auj.month, auj.day, hh, mm, tzinfo=dt.timezone.utc).timestamp() - 7200
j = lambda t: dt.datetime.fromtimestamp(t + 7200, dt.timezone.utc).strftime("%d/%m")
DERNIER = auj.strftime("%d/%m")
res, debuts = defaultdict(lambda: defaultdict(list)), {}


SERIE = {}                 # nom -> [(instant, rendement net)] : pour comparer chacun au TEMOIN
                           # sur SA propre periode. « tout le monde gagne » n est pas un resultat :
                           # le seul critere est de faire mieux que prendre tout sans filtre.


# INSTANT DE LA PHOTO, fige au demarrage. Le script met une minute a tourner et lit la MEME base
# a plusieurs moments : le temoin au debut, les strategies gelees a la fin. Des tickets arrivent
# entre-temps, et la derniere colonne montrait alors des filtres avec PLUS de tickets que le
# temoin -- impossible, puisque le temoin prend tout. Mido l a vu le 19/09. Tout ce qui arrive
# apres cet instant attendra la prochaine table.
T_PHOTO = dt.datetime.now(dt.timezone.utc).timestamp()


def ranger(nom, t, r):
    if t > T_PHOTO:
        return
    SERIE.setdefault(nom, []).append((t, r))
    # la journee en cours compte DEUX fois : dans son total a jour, et dans la tranche
    # « depuis le dernier point » qui montre ce qui vient de s ajouter.
    if j(t) != DERNIER:
        res[nom][j(t)].append(r)
    else:
        res[nom]["_avant" if t < COUPE else "_apres"].append(r)
        res[nom]["_jour"].append(r)
    debuts[nom] = min(debuts.get(nom, 1e18), t)


c = sqlite3.connect("file:/app/db/papier_combo.sqlite?mode=ro", uri=True, timeout=30)
_qs = [r[0] for r in c.execute("SELECT q FROM decision WHERE eligible=1 AND q IS NOT NULL")]
_K[0] = 0.0262 / _st.mean(PROTO + PRIO/30 + 2*SOL_EUR*30/((q or 0)+V) + DEPOT/(SOL_EUR*30) for q in _qs)

# ------------------------------------------------------------------ LE COUT REELLEMENT PAYE
# Le 2,62 ci-dessus vient de `calibration_corrigee` : reel contre un prix SIMULE CORRIGE, sur
# 236 tickets d un ancien carnet. Ce n est PAS la meme grandeur que « ce que coute un aller-retour
# par rapport au mouvement de prix du jeton ». Mesure le 18/09 sur les 92 tickets du carnet reel,
# multiplicativement, 1 - (1+reel)/(1+brut) :
#
#     moyenne 6,55 pt · IC95 [3,52 ; 10,03] · mediane 3,69 · sans ses 3 extremes 4,38
#
# **2,62 est HORS de cet intervalle.** La table le gardait quand meme parce que je traitais les
# deux mesures comme interchangeables. Elles ne le sont pas, et l ecart n est pas cosmetique :
# sur la meme fenetre et la meme regle, la table annonce -2,14 % par ticket la ou le carnet reel
# fait -8,63 %.
#
# On imprime donc les DEUX totaux cote a cote : l ancien garde la comparabilite avec l historique,
# le nouveau dit ce que ca aurait coute. La surcharge est PLATE -- a 20 EUR la formule rend 2,83 pt
# quel que soit le coffre (mediane = moyenne) -- donc l appliquer par ticket est exact.
# 4,69 pt : le cout REEL, mesure EN EUROS sur les 92 tickets du carnet du 18/09 --
#   engage 1 840,00 EUR · gain theorique (mouvement 47->287 s) -72,64 · gain reel -158,85
#   -> 86,21 EUR de cout, soit 4,69 pt par ticket.
# Le 6,55 affiche jusqu au 19/09 10h20 etait une MOYENNE MULTIPLICATIVE des couts par ticket : elle
# donne le meme poids a un ticket qui chute de 90 % -- ou un euro de frais pese enormement en
# relatif -- qu a un ticket normal. Pour ADDITIONNER DES EUROS, c est la mesure en euros qu il faut.
# Confirmation independante : `calibration_live` trouve 4,69 comme cout plat qui fait coincider le
# reel et le papier. La fenetre est la meme des deux cotes (entree 47 s, sortie 287 s), verifie.
# 4,25 pt = le cout mesure AVANT les deux corrections du 19/09. Depuis :
#   caution recuperee (module actif)            -1,06 pt
#   priorite d achat 500 000 -> 100 000         -0,21 pt
# soit 2,98 pt aujourd hui. COUT_MESURE=0.0425 redonne le tableau d avant les corrections.
# =====================================================================================
# LE COUT EST 2,98 pt. FIGE LE 19/09. NE PLUS LE RECALCULER.
#
# D OU IL VIENT, chaque terme mesure, pas devine :
#   4,25 pt   cout d execution PUR, sur la fenetre reellement utilisee par chaque ticket (entree a
#             54 s, pas 47), 92 tickets reels, transactions relues une par une sur la chaine.
#             Decompose : pool 1,11 + priorite 0,48 + caution 1,06 + impact 0,43 + 1,17 inexplique.
#  -1,06 pt   la CAUTION. 92 comptes-jetons vides trouves le 19/09, 14,47 EUR bloques. Le module
#             `recuperation` est ACTIF depuis 09h30 (`recuperation.enabled: true`, verifie).
#  -0,21 pt   la PRIORITE D ACHAT, passee de 500 000 a 100 000 lamports (`priority_fee_lamports_achat`,
#             verifie ; la VENTE reste a 500 000). On payait 22x le 99e centile du marche.
#  = 2,98 pt
# Les deux retraits sont des changements de CODE verifies dans la config qui tourne, pas des
# hypotheses. Ce qui n est pas encore verifie, c est que la realite les confirme : 12 tickets depuis
# la bascule, le cout y lit 10,66 pt +/- 13,70 -- l intervalle va de -3 a +24, donc rien. Il faut
# ~100 tickets ; a 12 ordres/jour, huit jours.
#
# POURQUOI CE PAVE. Le 19/09 j ai donne a Mido 2,98 puis 5,37 puis 4,69 dans la meme journee :
# 5,37 melangeait les periodes avant et apres la bascule, et 4,69 jetait le travail du matin par
# sur-correction apres qu il m ait repris. Il a repondu « t'es pas possible ». Regle : ce fichier
# part de 2,98 et n en bouge plus jusqu aux ~100 tickets. COUT_MESURE=0.0425 pour revoir la table
# avant les economies -- explicitement, jamais par defaut.
COUT_MESURE = float(os.environ.get("COUT_MESURE", "0.0298"))
# CORRIGE le 19/09 : la caution etait SOUSTRAITE DEUX FOIS. Le 2,98 ci-dessus la deduit deja
# (4,25 - 1,06 - 0,21) ; ce bloc la rededuisait, et la ligne d en-tete une troisieme fois -- la table
# appliquait 2,19 pt et en affichait 1,40 au lieu de 2,98, soit 0,20 EUR par ticket de trop sur
# CHAQUE case. Le sens par defaut est desormais : COUT_MESURE = caution RECUPEREE, point.
# CAUTION=payee rajoute la part de caution pour retrouver ce que les tickets historiques ont
# reellement paye -- c est le seul cas ou l on touche a COUT_MESURE.
if CAUTION:
    COUT_MESURE += DEPOT / (SOL_EUR * MISE)
_COUT_APPLIQUE = _st.mean(cout(q) for q in _qs)
SUP = COUT_MESURE - _COUT_APPLIQUE
for t, risque, regime, cr, b240, q in c.execute(
        "SELECT d.t_dec, d.risque, d.regime, d.cout_reduit, i.brut_240, d.q FROM decision d"
        " JOIN issue i ON i.pair=d.pair WHERE d.eligible=1 AND i.brut_240 IS NOT NULL AND d.q IS NOT NULL"):
    # CORRECTION du 17/09 23h : on utilisait `cout_reduit` (1,57 pt median), alors que le cout
    # total REEL mesure de bout en bout sur 236 tickets vaut 2,62 pts (JOURNAL 4113). Les lignes
    # du collecteur large, plus bas, utilisaient deja 2,62 : seules les cinq lignes de
    # papier_combo etaient fausses, d environ 1 point par ticket.
    r = min(b240 - cout(q), 3.0)
    ranger("temoin sans filtre", t, r)
    if regime is not None and regime > 0:
        ranger("regime seul", t, r)
    if risque <= 0.2694:
        ranger("RISQUE seul (modele)", t, r)
    if regime is not None and regime > 0 and risque <= 0.2694:
        ranger("regime + risque", t, r)
    # La bande ne compte QUE depuis son gel : avant, ce sont les tickets qui l ont choisie,
    # les afficher comme un resultat serait se mentir.
    if BANDE[0] <= risque < BANDE[1] and t >= GEL_BANDE:
        ranger("BANDE 0,20-0,35 (gelee)", t, r)

# Les tests geles les plus recents : bande+pause, et les deux modeles notes en parallele.
# Chacun ne compte QUE depuis son propre gel.
_bp = []
_ens = {}
try:
    _ens = {"ENSEMBLE de 12 (gele)": Ensemble(CHEMIN), "FORET ALEATOIRE (gelee)": Ensemble(CHEMIN_FORET)}
except Exception:
    _ens = {}
for t, risque, regime, cr, b240, q, var in c.execute(
        "SELECT d.t_dec, d.risque, d.regime, d.cout_reduit, i.brut_240, d.q, d.variables FROM decision d"
        " JOIN issue i ON i.pair=d.pair WHERE d.eligible=1 AND i.brut_240 IS NOT NULL"
        " AND d.q IS NOT NULL AND d.variables IS NOT NULL ORDER BY d.t_dec"):
    r = min(b240 - cout(q), 3.0)
    if BANDE[0] <= risque < BANDE[1] and t >= GEL_BP:
        _bp.append({"t": t, "fin": t + TENUE_S, "r": r})
    if t >= GEL_ENSEMBLE and _ens:
        f = json.loads(var)
        for nom_m, m in _ens.items():
            if m.probabilite(f) <= m.seuil_p80:
                ranger(nom_m, t, r)
for x in appliquer_pause(_bp):
    ranger("BANDE + PAUSE (gelee)", x["t"], x["r"])

# EXPERT DETENTEURS : la conjonction prix ET detention, gelee a 03h00. Il faut joindre
# papier_social, que seul ce collecteur-la remplit.
try:
    _det = Ensemble(CHEMIN_DET)
except Exception:
    _det = None
if _det is not None:
    c.execute("ATTACH DATABASE 'file:/app/db/papier_social.sqlite?mode=ro' AS S")
    for t, risque, b240, q, sac1, n5 in c.execute(
            "SELECT d.t_dec, d.risque, i.brut_240, d.q, s.sac1, s.n_sacs5 FROM decision d"
            " JOIN issue i ON i.pair=d.pair JOIN S.jeton s ON s.pair=d.pair"
            " WHERE d.eligible=1 AND i.brut_240 IS NOT NULL AND d.risque IS NOT NULL"
            " AND d.q IS NOT NULL AND s.sac1 IS NOT NULL ORDER BY d.t_dec"):
        if t >= GEL_DETENTEURS and risque <= 0.2694 and _det.probabilite(
                {"sac1": sac1, "n_sacs5": n5}) <= _det.seuil_p80:
            ranger("PRIX + DETENTEURS (gele)", t, min(b240 - cout(q), 3.0))
    if "PRIX + DETENTEURS (gele)" not in res:
        res["PRIX + DETENTEURS (gele)"]["_vide"] = []
        debuts["PRIX + DETENTEURS (gele)"] = GEL_DETENTEURS

# PISTE FOULE : la bande croisee avec le nombre d acheteurs, que seul le collecteur large connait.
c.execute("ATTACH DATABASE 'file:/app/db/papier_large.sqlite?mode=ro' AS L")
for t, risque, b240, q, foule in c.execute(
        "SELECT d.t_dec, d.risque, i.brut_240, d.q, g.acheteurs FROM decision d"
        " JOIN issue i ON i.pair=d.pair JOIN L.decision g ON g.pair=d.pair"
        " WHERE d.eligible=1 AND i.brut_240 IS NOT NULL AND d.risque IS NOT NULL"
        " AND d.q IS NOT NULL AND g.acheteurs IS NOT NULL ORDER BY d.t_dec"):
    if BANDE[0] <= risque < BANDE[1] and t >= GEL_FOULE and foule >= SEUIL_FOULE:
        ranger("PISTE FOULE (gelee)", t, min(b240 - cout(q), 3.0))
# Les deux modeles notes en parallele doivent APPARAITRE meme a zero ticket : une ligne absente
# se lit comme une ligne oubliee, pas comme une ligne qui n a pas encore demarre.
for _n in ("ENSEMBLE de 12 (gele)", "FORET ALEATOIRE (gelee)"):
    if _n not in res:
        res[_n]["_vide"] = []
        debuts[_n] = GEL_ENSEMBLE

for nom, base in (("G+D a 45 s (gele)", "/app/db/papier_gd.sqlite"),
                  ("G+D a 30 s (gele)", "/app/db/papier_gd30.sqlite")):
    c = sqlite3.connect("file:%s?mode=ro" % base, uri=True, timeout=30)
    for t, n in c.execute("SELECT d.t_dec, i.net FROM decision d JOIN issue i ON i.pair=d.pair"
                          " WHERE d.pris=1 AND i.net IS NOT NULL"):
        ranger(nom, t, n)

c = sqlite3.connect("file:/app/db/papier_large.sqlite?mode=ro", uri=True, timeout=30)
L = []
for t, tend, n_ach, p0, jal, coffre in c.execute(
        "SELECT d.t_dec, d.tendance, d.acheteurs, d.prix_entree, i.jalons, d.coffre FROM decision d"
        " JOIN issue i ON i.pair=d.pair WHERE d.pris=1 AND i.jalons IS NOT NULL ORDER BY d.t_dec"):
    o = json.loads(jal)
    fin, s = o.get("h287"), o.get("s1.25")
    ok = isinstance(s, dict) and s.get("age") is not None and s["age"] <= P.FIN_S and "apres" in s
    px = s["apres"] if ok else fin
    if px and p0:
        L.append({"t": t, "fin": t + 244, "tend": tend, "n": n_ach,  # noqa
                  "r": min(px / p0 - 1, P.PLAFOND) - cout(coffre)})


def pause(sel):
    pris, att, bl = [], [], 0.0
    for l in sel:
        att.sort(key=lambda z: z["fin"])
        while att and att[0]["fin"] <= l["t"]:
            f = att.pop(0)
            if f["r"] <= P.SEUIL_PAUSE:  # meme seuil, cout inclus
                bl = max(bl, f["fin"] + P.PAUSE)
        if l["t"] >= bl:
            pris.append(l)
        att.append(l)
    return pris


for nom, f, p in (("coffre seul", lambda l: True, False),
                  ("G  foule <= 74", lambda l: (l["n"] or 0) <= 74, True),
                  ("D  tendance > 0", lambda l: (l["tend"] or 0) > 0, False),
                  ("D+F  tendance + pause", lambda l: (l["tend"] or 0) > 0, True),
                  ("G+D  les trois", lambda l: (l["n"] or 0) <= 74 and (l["tend"] or 0) > 0, True)):
    sel = [l for l in L if f(l)]
    for l in (pause(sel) if p else sel):
        ranger(nom, l["t"], l["r"])

# Les jours passes sont decouverts dans les donnees : les figer en dur faisait disparaitre une
# colonne entiere au passage de minuit (le 17/09 a saute le 18 a 00h02).
_passes = sorted({j for d in res.values() for j in d if not j.startswith("_")},
                 key=lambda z: (z[3:], z[:2]))
COLS = _passes + ["_avant", "_apres", "_jour"]
# Fin de chaque colonne, pour savoir si une case vide est un « x » (n existait pas) ou un « 0 ».

# ENTREE T+75 contre T+60, gelee le 18/09 a 07h05 UTC. ATTENTION : population DIFFERENTE de toutes
# les autres lignes -- les jetons portant un Telegram, ceux que la production trade reellement, et
# non le flux de papier_combo. Entree a 75 s, sortie 240 s plus tard, cout plat de 2,62 pts.
try:
    from entree_75 import paires as _p75, GEL_E75, COUT as _C75
    _ic = sqlite3.connect("file:/app/db/intel.sqlite?mode=ro", uri=True, timeout=60)
    for _n75, _r60, _r75 in _p75(_ic):
        ranger("ENTREE T+75 (gelee)*", _n75, min(_r75 - _C75, 3.0))
    if "ENTREE T+75 (gelee)*" not in res:
        res["ENTREE T+75 (gelee)*"]["_vide"] = []
        debuts["ENTREE T+75 (gelee)*"] = GEL_E75
except Exception as _e75:
    print("   (ligne T+75 indisponible : %s)" % str(_e75)[:90])

# FORET FLUX 30 s, gelee le 19/09 a 16h26. Elle ne lit AUCUN prix : seulement qui achete et qui
# vend dans les 30 premieres secondes -- la seule vue que l index des transactions montre surement
# a l instant de decider (il retarde de 10 a 15 s). `foret_flux.py` depose ses tickets retenus ;
# la table les relit. Un gel qu on ne voit pas dans la table est un gel qu on oubliera.
try:
    _ff = json.load(open("/app/data/recherche/foret_flux/tickets.json", encoding="utf-8"))
    for _t, _r in _ff["tickets"]:
        ranger("FORET FLUX 30s (gelee)", float(_t), float(_r))
    if "FORET FLUX 30s (gelee)" not in res:
        res["FORET FLUX 30s (gelee)"]["_vide"] = []
        debuts["FORET FLUX 30s (gelee)"] = _ff["gel"]
except FileNotFoundError:
    pass
except Exception as _eff:
    print("   (ligne FORET FLUX indisponible : %s)" % str(_eff)[:90])


# AU PLUS BAS, gele le 18/09 a 08h00 UTC : le prix a 45 s EST son plus bas depuis la naissance.
# Meme flux que les autres lignes (papier_combo), donc directement comparable au temoin.
try:
    from au_plus_bas import au_plus_bas as _apb, GEL_APB
    _cb = sqlite3.connect("file:/app/db/papier_combo.sqlite?mode=ro", uri=True, timeout=30)
    for _t, _vj, _q, _b in _cb.execute(
            "SELECT d.t_dec, d.variables, d.q, i.brut_240 FROM decision d JOIN issue i ON i.pair=d.pair"
            " WHERE d.eligible=1 AND i.brut_240 IS NOT NULL AND d.variables IS NOT NULL"
            " AND d.q IS NOT NULL ORDER BY d.t_dec"):
        if _t < GEL_APB:
            continue
        try:
            _f = json.loads(_vj)
        except Exception:
            continue
        if _apb(_f):
            ranger("AU PLUS BAS (gele)", _t, min(_b - cout(_q), 3.0))
    if "AU PLUS BAS (gele)" not in res:
        res["AU PLUS BAS (gele)"]["_vide"] = []
        debuts["AU PLUS BAS (gele)"] = GEL_APB
except Exception as _eapb:
    print("   (ligne AU PLUS BAS indisponible : %s)" % str(_eapb)[:90])


# AU PLUS BAS + BANDE, gele le 18/09 a 09h30 UTC : les deux moities d une strategie gagnante.
try:
    from bas_bande import retenu as _rbb, GEL_BB
    _cb2 = sqlite3.connect("file:/app/db/papier_combo.sqlite?mode=ro", uri=True, timeout=30)
    for _t, _vj, _rq, _q, _b in _cb2.execute(
            "SELECT d.t_dec, d.variables, d.risque, d.q, i.brut_240 FROM decision d"
            " JOIN issue i ON i.pair=d.pair WHERE d.eligible=1 AND i.brut_240 IS NOT NULL"
            " AND d.variables IS NOT NULL AND d.q IS NOT NULL ORDER BY d.t_dec"):
        if _t < GEL_BB: continue
        try: _f = json.loads(_vj)
        except Exception: continue
        if _rbb(_f, _rq): ranger("BAS + BANDE (gele)", _t, min(_b - cout(_q), 3.0))
    if "BAS + BANDE (gele)" not in res:
        res["BAS + BANDE (gele)"]["_vide"] = []
        debuts["BAS + BANDE (gele)"] = GEL_BB
except Exception as _ebb:
    print("   (ligne BAS + BANDE indisponible : %s)" % str(_ebb)[:90])


# RISQUE + FREIN sur le taux de gagnants, gele le 18/09 a 15h00 UTC. Le frein ne change pas le
# choix du jeton : il suspend les achats quand le taux de gagnants des 20 derniers tickets CLOTURES
# est <= 50 %. Causalite stricte -- un ticket decide a t ne rend son resultat qu a t+242 s.
try:
    from frein_taux import GEL_FREIN, FENETRE, SEUIL, SEUIL_RISQUE, TENUE_S as TEN_F
    import bisect as _bi
    _cf = sqlite3.connect("file:/app/db/papier_combo.sqlite?mode=ro", uri=True, timeout=30)
    _tk = [(t, q, min(b - 0.0262, 3.0)) for t, q, b in _cf.execute(
        "SELECT d.t_dec, d.q, i.brut_240 FROM decision d JOIN issue i ON i.pair=d.pair"
        " WHERE d.eligible=1 AND i.brut_240 IS NOT NULL AND d.risque IS NOT NULL"
        " AND d.q IS NOT NULL AND d.risque <= ? ORDER BY d.t_dec", (SEUIL_RISQUE,))]
    _clos = sorted((t + TEN_F, r) for t, _q, r in _tk)
    _tc = [x[0] for x in _clos]
    for _t, _q, _r in _tk:
        if _t < GEL_FREIN:
            continue
        _i = _bi.bisect_right(_tc, _t)
        if _i < FENETRE:
            continue
        _v = [_clos[k][1] for k in range(_i - FENETRE, _i)]
        if sum(1 for y in _v if y > 0) / FENETRE > SEUIL:
            ranger("RISQUE + FREIN (gele)", _t, _r)
    if "RISQUE + FREIN (gele)" not in res:
        res["RISQUE + FREIN (gele)"]["_vide"] = []
        debuts["RISQUE + FREIN (gele)"] = GEL_FREIN
except Exception as _ef:
    print("   (ligne RISQUE + FREIN indisponible : %s)" % str(_ef)[:90])


# RISQUE + IPFS, gele le 18/09 a 16h00 UTC : n acheter que si les metadonnees sont sur IPFS, donc
# pas servies par une USINE A JETONS (j7tracker, uxento, usepaid, vortexdeployer). On ne nomme
# aucune usine : on exige la bonne reponse, donc une plateforme nouvelle est ecartee d office.
try:
    from usine import GEL_USINE, est_usine, SEUIL_RISQUE as SR_U
    _cu = sqlite3.connect("file:/app/db/papier_combo.sqlite?mode=ro", uri=True, timeout=30)
    _cu.execute("ATTACH DATABASE 'file:/app/db/intel.sqlite?mode=ro' AS MU")
    for _t, _uri, _q, _b in _cu.execute(
            "SELECT d.t_dec, o.uri, d.q, i.brut_240 FROM decision d JOIN issue i ON i.pair=d.pair"
            " JOIN MU.solana_social o ON o.mint=d.mint"
            " WHERE d.eligible=1 AND i.brut_240 IS NOT NULL AND d.risque IS NOT NULL"
            " AND d.q IS NOT NULL AND d.risque <= ? ORDER BY d.t_dec", (SR_U,)):
        if _t < GEL_USINE:
            continue
        _u = est_usine(_uri)
        if _u is False:          # IPFS : on garde. None (illisible) : on ecarte par prudence.
            ranger("RISQUE + IPFS (gele)", _t, min(_b - cout(_q), 3.0))
    if "RISQUE + IPFS (gele)" not in res:
        res["RISQUE + IPFS (gele)"]["_vide"] = []
        debuts["RISQUE + IPFS (gele)"] = GEL_USINE
except Exception as _eu:
    print("   (ligne RISQUE + IPFS indisponible : %s)" % str(_eu)[:90])

# FORET DE GAIN, 25 variables, gelee le 18/09 a 21h10 UTC (23h10 Paris) -- §3.142. Elle note dans
# sa propre base (papier_foret.sqlite) les tickets nes APRES le modele sauve au passage precedent ;
# on lit ici ceux qu elle a RETENUS (p >= seuil des 5 % les plus surs) et dont le resultat est connu.
# Le brut et le coffre viennent de papier_combo, pour que le cout soit calcule comme sur les autres
# lignes. La ligne « top 10 % » est une LECTURE, pas la regle gelee.
GEL_FORET = 1789765800.0
for _age, _base in (("45", "/app/db/papier_foret.sqlite"), ("75", "/app/db/papier_foret75.sqlite")):
    _n5, _n10 = "FORET %ss top 5 %% (gelee)" % _age, "FORET %ss top 10 %% (lecture)" % _age
    try:
        _cf = sqlite3.connect("file:%s?mode=ro" % _base, uri=True, timeout=30)
        _cf.execute("ATTACH DATABASE 'file:/app/db/papier_combo.sqlite?mode=ro' AS PC")
        # le brut vient de la base du gel lui-meme (son entree, son horizon) ; le coffre de papier_combo
        for _t, _r5, _r10, _q, _b in _cf.execute(
                "SELECT f.t_dec, f.retenu05, f.retenu10, d.q, f.ret_240 FROM decision f"
                " JOIN PC.decision d ON d.pair = f.pair"
                " WHERE f.ret_240 IS NOT NULL AND d.q IS NOT NULL ORDER BY f.t_dec"):
            if _r5:
                ranger(_n5, _t, min(_b - cout(_q), 3.0))
            if _r10:
                ranger(_n10, _t, min(_b - cout(_q), 3.0))
    except Exception as _ef:
        print("   (lignes %s indisponibles : %s)" % (_n5, str(_ef)[:90]))
    for _nom in (_n5, _n10):
        if _nom not in res:
            res[_nom]["_vide"] = []
            debuts[_nom] = GEL_FORET

_minuit = dt.datetime(auj.year, auj.month, auj.day, tzinfo=dt.timezone.utc).timestamp() - 7200
FINS = {"_avant": COUPE, "_apres": 1e18, "_jour": 1e18}
for _i, _j in enumerate(_passes):
    FINS[_j] = _minuit - 86400 * (len(_passes) - 1 - _i)
ORDRE = ["temoin sans filtre", "regime seul", "RISQUE seul (modele)", "regime + risque", "G+D a 45 s (gele)", "G+D a 30 s (gele)",
         "coffre seul", "G  foule <= 74", "D  tendance > 0", "D+F  tendance + pause", "G+D  les trois", "BANDE 0,20-0,35 (gelee)", "BANDE + PAUSE (gelee)",
         "PISTE FOULE (gelee)", "ENSEMBLE de 12 (gele)", "FORET ALEATOIRE (gelee)", "PRIX + DETENTEURS (gele)", "AU PLUS BAS (gele)", "BAS + BANDE (gele)", "RISQUE + FREIN (gele)", "RISQUE + IPFS (gele)", "FORET 45s top 5 % (gelee)", "FORET 45s top 10 % (lecture)", "FORET 75s top 5 % (gelee)", "FORET 75s top 10 % (lecture)", "FORET FLUX 30s (gelee)", "ENTREE T+75 (gelee)*"]
print("TOUT CE QUI A REELLEMENT TOURNE · mise %.0f EUR · caution %s" % (MISE, "payee" if CAUTION else "RECUPEREE"))
print("COUT : %.2f pt PARTOUT (cases et total). Mesure sur les 92 tickets reels du 18/09, transactions relues sur la"
      " chaine : 4,25 pt · moins la caution recuperee (1,06) · moins la priorite d achat divisee par 5 (0,21)."
      % (100 * COUT_MESURE))
print("  ce qui reste, structurel : swap 1,90 (0,94 %/jambe) · impact 0,20 · priorite vente 0,26 · dispersion 0,6.")
print("")
print("* ENTREE T+75 : AUTRE population -- les jetons Telegram (ceux de la production), pas le flux papier_combo.")
print("x = la strategie n existait pas · 0 = elle existait et n a rien pris (ou resultat pas encore connu)")
ENTETES = _passes + [DERNIER + " -> " + COUPE_H, COUPE_H + " -> maintenant", DERNIER + " TOTAL"]
# ETROIT=1 : la version telephone. Mido lit la table sur son mobile, qui coupe a droite -- et il a
# donc lu pendant des jours une colonne qui n etait pas la bonne. Une table qui ne tient pas dans
# l ecran de celui qui la lit est une table fausse.
ETROIT = os.environ.get("ETROIT") == "1"
# LARGEUR DU NOM, calculee sur la plus longue ligne au lieu d etre devinee. Un nom plus long que la
# colonne poussait TOUT le reste de la ligne vers la droite : les colonnes ne tombaient plus les unes
# sous les autres et la table devenait illisible (Mido, 19/09). On ne tronque pas non plus : un nom
# coupe au milieu (« FORET 75s top 10 % (lectur ») ne se reconnait pas d une ligne a l autre.
LNOM = max(len(n) for n in ORDRE)
if ETROIT:
    print("%-*s %7s %9s %9s" % (LNOM, "", "n", "depuis gel", "aujourd hui"))
else:
    print("%-*s %13s %s %12s" % (LNOM, "", "depuis", " ".join("%17s" % c for c in ENTETES), "TOTAL"))
for nom in ORDRE:
    if nom not in res:
        continue
    cel, tot, n_tot = [], 0.0, 0
    for c in COLS:
        v = res[nom].get(c)
        if v:
            # UN SEUL COUT PARTOUT, le reel (5,56 pt). L ancienne formule (1,82) restait affichee a
            # cote « pour comparer » et ne servait qu a tromper : c est elle qui annoncait
            # -2,14 %/ticket quand le carnet reel faisait -8,63 % sur la meme fenetre. Chaque case
            # porte donc la surcharge SUP, comme le total.
            euros = MISE * (sum(v) - len(v) * SUP)
            if c != "_jour":
                tot += euros
                n_tot += len(v)
            cel.append("%+12.0f E(%3d)" % (euros, len(v)))
        else:
            # Une case vide veut dire DEUX choses tres differentes, et les confondre trompe :
            #   « x »  la strategie n existait pas encore a cette date ;
            #   « 0 »  elle existait et n a rien pris -- soit elle a refuse, soit le resultat
            #          n est pas encore connu (le collecteur large suit 1 800 s, donc ses
            #          lignes ont une demi-heure de retard).
            cel.append("%17s" % ("x" if debuts[nom] > FINS[c] else "0"))
    # la surcharge est plate, donc le total au cout mesure se deduit exactement du NOMBRE de
    # tickets : inutile de rejouer la table, et aucune approximation cachee.
    if ETROIT:
        j = res[nom].get("_jour") or []
        jour = MISE * (sum(j) - len(j) * SUP)
        print("%-*s %7d %+8.0f E %+8.0f E" % (LNOM, nom, n_tot, tot, jour))
    else:
        print("%-*s %13s %s %+9.0f E(%3d)" % (
            LNOM, nom, dt.datetime.fromtimestamp(debuts[nom] + 7200, dt.timezone.utc).strftime("%d/%m %Hh%M"),
            " ".join(cel), tot, n_tot))


# ---------------------------------------------------------------- BATTRE LE MARCHE
# Chaque strategie contre le TEMOIN sur SA propre fenetre : meme marche, meme periode, seule la
# selection change. C est la seule comparaison qui dise si une regle apporte quelque chose.
tem = sorted(SERIE.get("temoin sans filtre", []))
if tem:
    print()
    print("CONTRE LE TEMOIN, sur la periode de CHAQUE strategie (meme marche, meme heures)")
    print("   %-*s %6s %10s %10s %10s %9s" % (LNOM, "", "n", "EUR/ticket", "temoin", "ecart", "sur 1000"))
    lignes = []
    for nom in ORDRE:
        v = SERIE.get(nom) or []
        # SEUIL A 5, pas 20. Une ligne jeune doit figurer AVEC les autres -- la page trace son
        # incertitude a +/- 2 ecarts-types, et sur 6 tickets cette barre est enorme : elle dit la
        # verite mieux qu une absence, qui laisse croire que la strategie n existe pas.
        if nom == "temoin sans filtre" or len(v) < 5:
            continue
        t0 = min(x[0] for x in v)
        ref = [r for t, r in tem if t >= t0]
        # Le TEMOIN sur la meme fenetre : 10 tickets suffisent pour qu une ligne jeune figure au
        # classement. Sa barre d incertitude sera enorme, et c est precisement l information utile.
        if len(ref) < 10:
            continue
        a_ = MISE * sum(r for _, r in v) / len(v)
        b_ = MISE * sum(ref) / len(ref)
        lignes.append((a_ - b_, nom, len(v), a_, b_))
    for d, nom, n, a_, b_ in sorted(lignes, reverse=True):
        print("   %-*s %6d %+9.3f %+9.3f %+9.3f %+8.0f E" % (LNOM, nom, n, a_, b_, d, 1000 * d))

# ------------------------------------------------------------------ SORTIE JSON (page de suivi)
# JSON=chemin ecrit exactement les memes nombres que ce qui vient d etre imprime, pour la page web.
# UNE SEULE SOURCE : la page ne recalcule rien, sinon deux vues du meme chiffre finiraient par
# diverger et il faudrait deviner laquelle croire.
_sortie = os.environ.get("JSON")
if _sortie:
    _t0 = min((min(x[0] for x in v) for v in SERIE.values() if v), default=0)

    def _courbe(v, pas=3600):
        """Cumul en euros, un point par heure -- assez fin pour la forme, assez court pour le web.

        Le premier point vaut ZERO, a l instant du premier ticket. Sans lui, la courbe demarre au
        cumul de la premiere heure (le temoin a +80 EUR, regime+risque a -20) et les departs
        semblent decales sans raison -- Mido l a vu sur la page le 19/09.
        """
        v = sorted(v)
        if not v:
            return []
        # Le zero est pose au DEBUT du premier seau, et chaque point porte la FIN du sien : sinon le
        # point de depart tombe apres le premier seau (son instant exact est posterieur au plancher
        # de l heure) et la courbe recule dans le temps sur son premier segment.
        out, cum, seau = [[int(v[0][0] // pas) * pas, 0.0]], 0.0, None
        for t, r in v:
            cum += MISE * (r - SUP)
            s = int(t // pas) * pas + pas
            if s != seau:
                out.append([s, round(cum, 2)])
                seau = s
            else:
                out[-1][1] = round(cum, 2)
        return out

    def _par_jour(v):
        """Le gain de CHAQUE journee, separement -- pas le cumul.

        Le graphique cumule est ecrase par le temoin (2 672 tickets, -2 100 EUR) : les lignes a
        60 tickets y sont des traits plats colles a zero. Par jour, chacune se lit a son echelle.
        Mido, 19/09 : « je veux un autre plus bas avec les perf par jour ».
        """
        par = {}
        for t, r in v:
            k = dt.datetime.fromtimestamp(t + 7200, dt.timezone.utc).strftime("%Y-%m-%d")
            e = par.setdefault(k, [0.0, 0])
            e[0] += MISE * (r - SUP)
            e[1] += 1
        return [{"jour": k, "gain": round(g, 2), "n": n} for k, (g, n) in sorted(par.items())]

    _lignes = []
    for nom in ORDRE:
        v = SERIE.get(nom) or []
        if not v:
            # Une strategie DECLAREE mais qui n a encore aucun ticket doit apparaitre quand meme,
            # a zero : c est ainsi qu on voit un gel tout neuf demarrer au lieu de se demander s il
            # a ete branche. Mido, 19/09 : « t'as ajoute le nouveau gel ? je peux le voir ? ».
            if nom in res:
                _lignes.append({"nom": nom, "n": 0, "total": 0.0, "par_ticket": 0.0,
                                "jour": 0.0, "n_jour": 0, "debut": debuts.get(nom),
                                "courbe": [], "par_jour": []})
            continue
        n = len(v)
        total = MISE * (sum(r for _, r in v) - n * SUP)
        j = res[nom].get("_jour") or []
        _lignes.append({
            "nom": nom, "n": n, "total": round(total, 2),
            "par_ticket": round(total / n, 4),
            "jour": round(MISE * (sum(j) - len(j) * SUP), 2), "n_jour": len(j),
            "debut": debuts.get(nom), "courbe": _courbe(v), "par_jour": _par_jour(v),
        })
    # ECART-TYPE D UN TICKET, mesure sur le temoin -- toute la population, sans selection. C est lui
    # qui fixe ce qu on peut distinguer du hasard : un ecart plus petit que son propre bruit ne se
    # depense pas. Sans ce chiffre, un classement en euros bruts met en tete les lignes les MOINS
    # nombreuses, donc les plus bruyantes (Mido, 19/09 : « bande + pause c'est de la merde et
    # finalement c'est ce qui marche ? » -- non : 58 tickets, 1,2 ecart-type).
    _nets = [MISE * (r - SUP) for _, r in (SERIE.get("temoin sans filtre") or [])]
    _sigma = (_st.pstdev(_nets) if len(_nets) > 1 else 0.0)
    for _l in _lignes:
        _l["bruit"] = round(_sigma / (_l["n"] ** 0.5), 4) if _l["n"] else None
    _contre = []
    if tem:
        for d, nom, n, a_, b_ in sorted(lignes, reverse=True):
            bruit = _sigma / (n ** 0.5) if n else None
            _contre.append({"nom": nom, "n": n, "par_ticket": round(a_, 4), "temoin": round(b_, 4),
                            "ecart": round(d, 4), "sur_1000": round(1000 * d, 1),
                            "bruit": round(bruit, 4) if bruit else None,
                            "sigmas": round(d / bruit, 2) if bruit else None})
    json.dump({
        "genere": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "mise": MISE, "cout_pt": round(100 * COUT_MESURE, 2), "caution": not CAUTION,
        "sigma_ticket": round(_sigma, 3),
        "debut_donnees": _t0, "lignes": _lignes, "contre_temoin": _contre,
    }, open(_sortie, "w"), ensure_ascii=False)
    print("\nJSON ecrit : %s" % _sortie)

# on retient l heure de CE tableau pour que le prochain coupe ici
try:
    with open(MEMO, "w") as f:
        f.write((dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=2)).strftime("%H:%M"))
except Exception:
    pass
