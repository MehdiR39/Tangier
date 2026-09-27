"""CARNET TANGIER — la page de suivi, en local, sans dépendre de personne.

Mido, 19/09 : « au lieu de passer par Claude pourquoi pas la faire dans un streamlit avec une
adresse locale ? » Elle tourne sur son PC, ne coûte rien, et continue quand ma session s'arrête.

D'OÙ VIENNENT LES CHIFFRES. `/app/db` est un volume Docker que l'hôte ne sait pas lire ; `data/`,
lui, est monté depuis le disque. `intel/research/carnet_json.py`, DANS le conteneur, y écrit deux
fichiers que cette page relit DEHORS :

    data/carnet.json       la table entière, régénérée toutes les 5 min par `table_std2.py` —
                           exactement ce que Mido lit dans son terminal, texte brut compris.
    data/carnet_live.json  le carnet RÉEL, toutes les 20 s : achats, P&L, et l'état du budget.

DEUX RYTHMES D'AFFICHAGE, parce que les deux grandeurs ne bougent pas pareil : le bandeau du réel
se rafraîchit toutes les 5 s, la table toutes les 60 s. Rien n'est recalculé ici — une page qui
refait les calculs finit par afficher un autre nombre que le terminal, et il faut alors deviner
lequel croire.

LANCEMENT :
    C:/Users/Osiris/miniconda3/envs/qrt/python.exe -m streamlit run data/carnet_app.py
"""
from __future__ import annotations

import datetime as dt
import json
import os

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

RACINE = os.path.dirname(os.path.abspath(__file__))
F_TABLE = os.path.join(RACINE, "carnet.json")
F_LIVE = os.path.join(RACINE, "carnet_live.json")
F_ERR = os.path.join(RACINE, "carnet_erreur.json")
F_MARCHE = os.path.join(RACINE, "carnet_marche.json")
TZ = dt.timezone(dt.timedelta(hours=2))

GAIN, PERTE, ACCENT, DOUX = "#3f9c6d", "#c9564b", "#d4a03c", "#8b9098"
TEINTES = ["#d4a03c", "#5cab7a", "#d4695e", "#6b9ec9", "#b98ac7", "#c9a06b", "#7fb3a3", "#c78fa0"]
# LES TROIS TEINTES DES VARIANTES, choisies par le validateur et non a l oeil : or / vert /
# violet passent la bande de clarte, le plancher de chroma, la separation daltonienne et le
# plancher en vision normale. Le triplet naturel (les trois premieres de TEINTES) ECHOUE --
# #5cab7a et #6b9ec9 sont a 13,6 en vision normale, sous le plancher de 15, et #6b9ec9 est
# sous le plancher de chroma. La paire or/vert reste a 7,3 en daltonien (cible 8), d ou les
# ETIQUETTES DIRECTES au bout de chaque courbe : l identite ne tient jamais a la couleur seule.
VARIANTES_T = ["#d4a03c", "#5cab7a", "#b98ac7"]


def _alpha(hexa, a):
    """La meme teinte, transparente -- pour les bandes d incertitude."""
    h = hexa.lstrip("#")
    return "rgba(%d,%d,%d,%s)" % (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), a)


st.set_page_config(page_title="Carnet Tangier", page_icon="📓", layout="wide")
st.markdown("""<style>
  .block-container{padding-top:2.2rem; padding-bottom:3rem; max-width:1500px}
  [data-testid="stMetricValue"]{font-size:1.5rem; font-variant-numeric:tabular-nums}
  [data-testid="stMetricLabel"]{font-size:.72rem; letter-spacing:.07em; text-transform:uppercase}
  .bandeau{border:1px solid rgba(128,128,128,.25); border-radius:10px; padding:14px 18px; margin-bottom:6px}
  .bloque{border-color:#c9564b; background:rgba(201,86,75,.08)}
  .ouvert{border-color:#3f9c6d; background:rgba(63,156,109,.07)}
  code, .mono{font-variant-numeric:tabular-nums}
</style>""", unsafe_allow_html=True)


def lire(chemin, defaut=None):
    try:
        with open(chemin, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return defaut


def age(iso):
    """Âge de la donnée ET heure du rendu. Une page figée doit se dénoncer.

    L'âge seul ne suffit pas : Streamlit ne rafraîchit ses blocs que tant qu'un onglet est
    activement connecté. Une session qui décroche continue d'afficher son dernier rendu — âge
    compris, donc figé sur une valeur rassurante. Mido, 19/09 : « tu te fous de moi ? elle y est
    pas » — la page lui servait un rendu de 21h37 alors que la donnée datait de 21h45.
    On affiche donc AUSSI l'heure à laquelle ce bloc a été dessiné : si elle cesse d'avancer,
    la page est morte et ça se voit.
    """
    maintenant = dt.datetime.now(TZ).strftime("%H:%M:%S")
    try:
        d = dt.datetime.fromisoformat(iso)
        s = (dt.datetime.now(dt.timezone.utc) - d).total_seconds()
        vieux = ("il y a %.0f s" % s) if s < 90 else ("il y a %.0f min" % (s / 60))
    except Exception:
        vieux = "?"
    return "%s · affiché à %s" % (vieux, maintenant)


def heure(ts):
    """Un instant unix -> jour et heure de Paris. Les dates du projet se lisent toutes en Paris."""
    try:
        return dt.datetime.fromtimestamp(float(ts), TZ).strftime("%d/%m %H:%M")
    except Exception:
        return "—"


def eur(v, d=0):
    """Format francais : espace pour les milliers, virgule decimale, vrai signe moins.
    (`"%,.*f"` n existe pas en Python -- il faut `format`, sinon ValueError a l ouverture.)"""
    return ("+" if v >= 0 else "−") + format(abs(v), ",.%df" % d).replace(",", " ").replace(".", ",")


# ================================================================ L'ARGENT RÉEL (rythme rapide)
F_REEL = os.path.join(RACINE, "carnet_reel.json")
# UNE COULEUR PAR STRATÉGIE, la même partout sur la page, et le NOM écrit à côté de chaque chiffre.
# Mido, 27/09 : « on voit des chiffres, on sait pas quelle strat ». L'ancien bloc ne lisait que
# `mr_lignes` : G+D, en réel depuis le 25/09, n'apparaissait nulle part, et un bandeau affichait
# encore un plafond de −150 € en 24 h glissantes alors que les plafonds sont supprimés et que le
# P&L se lit par jour calendaire.
COULEUR_STRAT = {"BANDE + PAUSE": "#d4a03c", "G+D": "#6b9ec9"}


@st.fragment(run_every=10)
def argent_reel():
    R = lire(F_REEL)
    if not R or not R.get("strategies"):
        st.info("Pas encore de données — `carnet_json.py` écrit `carnet_reel.json` toutes les 20 s.")
        return
    S = [s for s in R["strategies"] if "erreur" not in s]
    for s in R["strategies"]:
        if "erreur" in s:
            st.error("%s : illisible (%s)" % (s["nom"], s["erreur"]))

    # ---- 1. AUJOURD'HUI, en haut, une colonne par stratégie + le total ----
    st.subheader("Aujourd'hui (jour calendaire, heure de Paris)")
    c = st.columns(len(S) + 1)
    for col, s in zip(c, S):
        col.metric(s["nom"], eur(s["aujourdhui"]["gain"], 2) + " €",
                   "%d tickets · mise %s €" % (s["aujourdhui"]["n"], eur(s["mise"] or 0).lstrip("+")),
                   delta_color="off")
    c[-1].metric("TOTAL des deux", eur(sum(s["aujourdhui"]["gain"] for s in S), 2) + " €",
                 "%d positions ouvertes" % sum(s["ouvertes"] for s in S), delta_color="off")

    # ---- 2. DEPUIS LE DÉBUT de chaque stratégie ----
    st.subheader("Depuis le début de chaque stratégie")
    c = st.columns(len(S) + 1)
    for col, s in zip(c, S):
        t = s["total"]
        col.metric(s["nom"], eur(t["gain"], 2) + " €",
                   "%d tickets · %d %% gagnants · depuis le %s"
                   % (t["n"], round(100 * t["gagnants"] / t["n"]) if t["n"] else 0, heure(s["depuis"])),
                   delta_color="off")
    c[-1].metric("TOTAL des deux", eur(sum(s["total"]["gain"] for s in S), 2) + " €", delta_color="off")

    fig = go.Figure()
    for s in S:
        if not s["courbe"]:
            continue
        x = pd.to_datetime([p[0] for p in s["courbe"]], unit="s", utc=True).tz_convert("Europe/Paris")
        y = [p[1] for p in s["courbe"]]
        fig.add_trace(go.Scatter(x=x, y=y, mode="lines", name=s["nom"],
                                 line=dict(color=COULEUR_STRAT.get(s["nom"], DOUX), width=2),
                                 hovertemplate="%{x|%d/%m %H:%M}<br>" + s["nom"] +
                                               " : <b>%{y:+.2f} €</b><extra></extra>"))
        fig.add_annotation(x=x[-1], y=y[-1], text="<b>%s</b> %s €" % (s["nom"], eur(y[-1])),
                           showarrow=False, xanchor="left", xshift=6,
                           font=dict(color=COULEUR_STRAT.get(s["nom"], DOUX)))
    fig.add_hline(y=0, line=dict(color=DOUX, width=1, dash="dot"))
    fig.update_layout(height=300, margin=dict(l=0, r=150, t=6, b=0), yaxis_title="€ cumulés, réels",
                      legend=dict(orientation="h", y=-.18),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig, use_container_width=True)

    # ---- 3. JOUR PAR JOUR, une colonne par stratégie ----
    st.subheader("Jour par jour")
    jours = sorted({j["jour"] for s in S for j in s["jours"]}, reverse=True)
    lignes = []
    for j in jours:
        ligne, tot = {"jour": dt.date.fromisoformat(j).strftime("%a %d/%m")}, 0.0
        for s in S:
            v = next((x for x in s["jours"] if x["jour"] == j), None)
            ligne[s["nom"] + " €"] = round(v["gain"], 2) if v else None
            ligne[s["nom"] + " tickets"] = v["n"] if v else 0
            tot += v["gain"] if v else 0.0
        ligne["TOTAL €"] = round(tot, 2)
        lignes.append(ligne)
    st.dataframe(pd.DataFrame(lignes), use_container_width=True, hide_index=True)

    # ---- 4. LES DERNIERS TICKETS, avec leur stratégie ----
    st.subheader("Les derniers tickets")
    der = []
    for s in S:
        for x in s["derniers"]:
            der.append({"quand": heure(x["t"]), "_t": x["t"], "stratégie": s["nom"],
                        "jeton": x["jeton"], "mise €": x["mise"],
                        "gain €": round(x["gain"], 2) if x["gain"] is not None else None,
                        "statut": x["statut"]})
    der = sorted(der, key=lambda z: -z["_t"])[:25]
    for d_ in der:
        d_.pop("_t")
    st.dataframe(pd.DataFrame(der), use_container_width=True, hide_index=True, height=360)
    st.caption("argent réel, lu dans la base du moteur · %s" % age(R["genere"]))




# =============================================================== LA TABLE (rythme lent)
@st.fragment(run_every=60)
def arbitre():
    """LA SEULE MESURE QUI PEUT JUSTIFIER DE CHANGER LA PRODUCTION.

    Toutes les autres lignes de cette page comparent une stratégie à un TÉMOIN PAPIER. Celle-ci
    demande : sur les tickets que le moteur a RÉELLEMENT achetés, qu'aurait dit la candidate ?
    Les euros sont lus au portefeuille, pas reconstruits depuis un prix — aucun modèle de coût ne
    s'interpose. Et comme c'est apparié (mêmes tickets, même marché), ça tranche beaucoup plus vite
    qu'un niveau absolu : §3.165 a rendu lisible 0,14 €/ticket là où un niveau en demande 3 000.
    """
    A = lire(os.path.join(RACINE, "arbitre.json"))
    if not A:
        return
    st.subheader("Chaque candidate contre le moteur")
    st.caption("Sur les tickets que le moteur a **réellement achetés** — %d clôturés, %s. "
               "Euros lus au portefeuille. C'est la seule comparaison qui porte sur de vrais euros ; "
               "tout le reste de cette page se mesure contre un témoin papier."
               % (A.get("n_reel", 0), age(A.get("genere"))))
    lignes, notes_ = [], []
    for e in A.get("lignes", []):
        if not e.get("comparable"):
            notes_.append("**%s** — décide à 75 s, le moteur achète à 47 s : pas les mêmes tickets "
                          "au même instant, donc non comparable." % e["nom"])
            continue
        if "ecart" not in e:
            notes_.append("**%s** — %d ticket(s) en commun, trop peu pour lire."
                          % (e["nom"], e.get("n_commun", 0)))
            continue
        lignes.append({
            "candidate": e["nom"], "tickets": e["n_commun"], "gardés": e["n_gardes"],
            "le moteur €/tick": e["moteur_eur_ticket"], "la candidate €/tick": e["candidate_eur_ticket"],
            "ce qu'elle écarte": e["ecarte_eur_ticket"], "écart": e["ecart"],
            "σ": e.get("sigmas"), "€/jour gagnés": e.get("eur_jour_gagnes"),
        })
    if lignes:
        st.dataframe(pd.DataFrame(lignes).sort_values("écart", ascending=False),
                     use_container_width=True, hide_index=True)
        st.caption("*ce qu'elle écarte* est le gain moyen des tickets qu'elle aurait refusés : "
                   "s'il est plus bas que celui du moteur, elle jette bien. **σ est le bruit de la "
                   "DIFFÉRENCE**, pas du niveau — un sous-ensemble du même lot, donc "
                   "σ·√((n−k)/(n·k)) et non σ/√k. Sous 2, rien n'est démontré.")
    for n_ in notes_:
        st.caption("· " + n_)


def table_complete():
    D = lire(F_TABLE)
    err = lire(F_ERR)
    if err:
        st.error("Dernière régénération de la table en échec (%s) : %s"
                 % (err.get("quand", "?"), str(err.get("erreur"))[:300]))
    if not D:
        st.warning("`data/carnet.json` absent.")
        return

    c = st.columns(4)
    temoin = next((l for l in D["lignes"] if l["nom"] == "temoin sans filtre"), None)
    top = (D["contre_temoin"] or [None])[0]
    c[0].metric("Coût appliqué", "%.2f pt" % D["cout_pt"], "caution récupérée", delta_color="off")
    if temoin:
        c[1].metric("Témoin — tout prendre", eur(temoin["total"]) + " €",
                    "%d tickets · %s €/ticket" % (temoin["n"], eur(temoin["par_ticket"], 3)),
                    delta_color="off")
    if top:
        c[2].metric("Meilleure ligne", top["nom"][:22],
                    "%s €/ticket contre le témoin" % eur(top["ecart"], 3), delta_color="off")
    c[3].metric("Mise", "%.0f €" % D["mise"], "par ticket", delta_color="off")
    st.caption("table · %s" % age(D["genere"]))

    # ============================================================ LES CANDIDATES, choisies seules
    # MIDO, 20/09 : « je trouve qu'il manque des indicateurs d'analyse pour les strats ; on
    # sélectionne les gagnantes automatiquement et on les analyse ». La page montrait des
    # RÉSULTATS mais jamais ce qui va les TRANCHER, et elle laissait trier à l'œil — c'est
    # comme ça que BANDE + PAUSE est restée en tête trois jours alors que 91 % de son gain
    # tenait à trois tickets (§3.163).
    # CE QUI TRADE L ARGENT, EN HAUT ET AVANT TOUT LE RESTE. Mido, 20/09 : « FORET REENTRAINEE 6h,
    # ce nom on l a pas dans l app... ». Il y etait -- mais rien ne disait laquelle des 34 lignes
    # correspond au modele qui achete REELLEMENT. On regardait 34 courbes sans savoir laquelle
    # etait en jeu.
    P = D.get("prod") or {}
    if P and not P.get("erreur"):
        vieux = ""
        if P.get("reentraine_le"):
            try:
                t_ = dt.datetime.fromisoformat(P["reentraine_le"])
                h_ = (dt.datetime.now(t_.tzinfo) - t_).total_seconds() / 3600.0
                vieux = " · réentraîné il y a **%.1f h**%s" % (
                    h_, "  ⚠️ il devrait l'être toutes les 6 h" if h_ > 8 else "")
            except ValueError:
                pass
        st.success(
            "**EN PRODUCTION : %s**  \n"
            "Recette : %s  \nSeuil %s · %d variables · entraîné sur %s tickets%s  \n"
            "La ligne de cette page qui porte la même recette est **%s** — mais c'est son carnet "
            "PAPIER : mêmes règles, tickets différents."
            % (P.get("fichier") or "?", P.get("recette") or "?",
               ("%.4f" % P["seuil"]) if P.get("seuil") else "?", P.get("n_variables") or 0,
               P.get("entraine_sur") or "?", vieux, P.get("ligne") or "aucune"),
            icon="💰")

    st.subheader("Les candidates")
    CRIT = [
        ("gagne de l'argent", lambda l: (l.get("niveau") or 0) > 0),
        ("et par jour", lambda l: (l.get("eur_jour") or 0) > 0),
        ("sur les DEUX moitiés", lambda l: (l.get("moitie_1") or 0) > 0 and (l.get("moitie_2") or 0) > 0),
        ("garde ≥ 50 % sans ses 3 meilleurs", lambda l: (l.get("sans3_part") or 0) >= 0.5),
        ("plus de 50 % de gagnants", lambda l: (l.get("gagnants_pct") or 0) > 50),
        ("assez de tickets pour se lire (≥ 50)", lambda l: (l.get("n") or 0) >= 50),
    ]
    notes = []
    for l in D["lignes"]:
        if l["nom"] == "temoin sans filtre" or not (l.get("n") or 0):
            continue
        ok = [nom_ for nom_, f in CRIT if f(l)]
        notes.append((len(ok), l, ok))
    notes.sort(key=lambda z: (-z[0], -(z[1].get("niveau") or 0)))
    retenues_auto = [z for z in notes if z[0] == len(CRIT)]
    if not retenues_auto:
        st.info("Aucune ligne ne passe les %d critères aujourd'hui. Les meilleures en passent %d."
                % (len(CRIT), notes[0][0] if notes else 0))
        retenues_auto = notes[:3]
    for score, l, ok in retenues_auto[:5]:
        manque = [nom_ for nom_, _ in CRIT if nom_ not in ok]
        with st.container(border=True):
            c1, c2, c3, c4 = st.columns([3, 1, 1, 1])
            c1.markdown("**%s**  \n%d/%d critères" % (l["nom"], score, len(CRIT)))
            c2.metric("€/ticket", "%+.2f" % (l.get("niveau") or 0))
            c3.metric("€/jour", "%+.0f" % (l.get("eur_jour") or 0))
            c4.metric("gagnants", "%.0f %%" % (l.get("gagnants_pct") or 0))
            if manque:
                st.caption("⚠️ ne passe pas : " + " · ".join(manque))
            # CE QUI VA LA TRANCHER, et quand. Sans ça la page dit où on en est, jamais ce qu'on attend.
            e, quoi = l.get("echeance"), l.get("echeance_quoi")
            if e:
                fait = l["n"]
                reste = max(0, e - fait)
                vit = (l.get("tickets_jour") or 0)
                st.progress(min(1.0, fait / e),
                            text="échéance : %d / %d %s%s" % (fait, e, quoi or "tickets",
                                 (" — encore ~%.1f jour(s)" % (reste / vit)) if vit > 0 and reste else
                                 (" — ÉCHÉANCE ATTEINTE" if not reste else "")))
            else:
                st.caption("Aucun critère écrit d'avance pour cette ligne — elle ne pourra jamais "
                           "être déclarée prouvée, seulement observée.")
            d_ = l.get("deciles")
            if d_ and l.get("part_top3") is not None:
                st.caption("Ses 3 meilleurs tickets portent **%.0f %%** du gain. "
                           "Répartition, du pire au meilleur décile : %s"
                           % (100 * l["part_top3"], " · ".join("%+.1f" % x for x in d_)))

    st.divider()
    arbitre()
    st.divider()
    st.subheader("Contre le témoin")
    st.caption("Une stratégie qui n'a tourné qu'un bon après-midi paraît brillante par accident. "
               "Chacune est comparée à « acheter tout » **sur sa propre période** — même marché, "
               "mêmes heures.")
    st.caption("**La barre noire est l'incertitude (±2 écarts-types).** Tant qu'elle traverse le "
               "trait du zéro, l'écart ne se distingue pas du hasard, si grand soit-il : un ticket "
               "vaut %s € d'écart-type, donc 55 tickets suffisent à fabriquer ±%s € par pur hasard. "
               "Les lignes qui ne franchissent pas leur bruit sont affichées en sourdine."
               % (eur(D.get("sigma_ticket") or 0, 2).lstrip("+"),
                  eur(2 * (D.get("sigma_ticket") or 0) / 55 ** .5, 2).lstrip("+")))
    ct = pd.DataFrame(D["contre_temoin"])
    if not ct.empty and "bruit" in ct:
        net = ct["sigmas"].abs() >= 2
        couleurs = [(GAIN if v >= 0 else PERTE) if s else
                    ("rgba(63,156,109,.28)" if v >= 0 else "rgba(201,86,75,.28)")
                    for v, s in zip(ct["ecart"], net)]
        fig = go.Figure(go.Bar(
            x=ct["ecart"], y=ct["nom"], orientation="h", marker_color=couleurs,
            error_x=dict(type="data", array=2 * ct["bruit"], color=DOUX, thickness=1.4, width=3),
            customdata=ct[["n", "par_ticket", "temoin", "sigmas"]].values,
            hovertemplate="<b>%{y}</b><br>écart %{x:+.3f} €/ticket — "
                          "<b>%{customdata[3]:+.2f} écart-type</b><br>"
                          "%{customdata[0]} tickets · elle %{customdata[1]:+.3f} · "
                          "témoin %{customdata[2]:+.3f}<extra></extra>"))
        fig.update_layout(height=max(320, 26 * len(ct)), margin=dict(l=0, r=10, t=6, b=0),
                          xaxis_title="€ par ticket, écart au témoin (barre = ±2 écarts-types)",
                          yaxis=dict(autorange="reversed"),
                          paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
        fig.add_vline(x=0, line=dict(color=DOUX, width=1))
        st.plotly_chart(fig, use_container_width=True)

        surs = ct[net]
        if surs.empty:
            st.info("**Aucune stratégie ne franchit son propre bruit.** Rien n'est encore prouvé, "
                    "ni dans un sens ni dans l'autre.")
        else:
            for _, r in surs.iterrows():
                mot = "bat le marché" if r["ecart"] > 0 else "fait pire que ne rien filtrer"
                (st.success if r["ecart"] > 0 else st.error)(
                    "**%s** %s : %s €/ticket sur %d tickets, soit %s écarts-types."
                    % (r["nom"], mot, eur(r["ecart"], 3), r["n"], eur(r["sigmas"], 2)))

        st.caption("Le classement par écart-type, qui est le seul comparable :")
        cl = ct[["nom", "n", "ecart", "bruit", "sigmas"]].copy()
        cl["|σ|"] = cl["sigmas"].abs()
        cl = cl.sort_values("|σ|", ascending=False).drop(columns="|σ|")
        cl.columns = ["stratégie", "tickets", "écart €/ticket", "son bruit", "écarts-types"]
        st.dataframe(cl, use_container_width=True, hide_index=True,
                     height=min(700, 36 * len(cl) + 40))

    # ------------------------------------------------- fonctionnement de la PROD
    # COMMENT LA REGLE SE COMPORTE, pas ce qu elle rapporte. Mido a demande trois fois « pourquoi
    # ca fait deux heures qu on n achete pas » -- et la reponse tient a une distinction que rien
    # n affichait : ECARTEE = hors bande, le MODELE a dit non ; PAUSE = dans la bande, la PAUSE a
    # dit non. Tout vient de `mr_lignes`, le carnet REEL.
    _F = D.get("fonctionnement") or {}
    if _F and "erreur" not in _F:
        st.subheader("Comment la règle tourne, en production")
        _en = _F.get("en_pause")
        _dep = _F.get("pause_depuis")
        c = st.columns(5)
        c[0].metric("Décisions", "%d" % _F["decides"])
        c[1].metric("Hors bande", "%d" % _F["hors_bande"],
                    "%.0f %% du flux" % (100.0 * _F["hors_bande"] / max(_F["decides"], 1)))
        c[2].metric("Bloqués par la pause", "%d" % _F["bloques"],
                    "%.0f %% de la bande"
                    % (100.0 * _F["bloques"] / max(_F["bloques"] + _F["achetes"] + _F["annules"], 1)))
        c[3].metric("Achetés", "%d" % _F["achetes"],
                    ("%d refusés à l'exécution" % _F["annules"]) if _F.get("annules") else None,
                    delta_color="off")
        if _en and _dep:
            c[4].metric("En pause depuis",
                        "%.0f min" % ((_F["maintenant"] - _dep) / 60.0), "elle bloque", delta_color="off")
        else:
            c[4].metric("Pause", "ouverte", "elle laisse acheter", delta_color="off")
        _da = _F.get("dernier_achat")
        st.caption("**%d périodes de pause** depuis la mise en production · durée médiane "
                   "**%s min**, la plus longue **%s min**. Dernier achat : **%s**."
                   % (_F.get("n_pauses", 0), _F.get("duree_mediane"), _F.get("duree_max"),
                      (pd.to_datetime(_da, unit="s", utc=True).tz_convert("Europe/Paris")
                       .strftime("%d/%m %Hh%M")) if _da else "aucun"))

        # L ENTONNOIR. Une barre par etage, du flux entier a ce qui a ete achete : on voit d un
        # coup lequel des deux filtres coupe, et de combien.
        _et = [("décisions", _F["decides"], DOUX),
               ("dans la bande", _F["bloques"] + _F["achetes"] + _F["annules"], ACCENT),
               ("passent la pause", _F["achetes"] + _F["annules"], "#5cab7a"),
               ("achetés", _F["achetes"], GAIN)]
        fig = go.Figure(go.Bar(
            x=[v for _, v, _c in _et], y=[n for n, _v, _c in _et], orientation="h",
            marker_color=[cc for _n, _v, cc in _et],
            text=["%d" % v for _, v, _c in _et], textposition="outside",
            hovertemplate="%{y} : %{x}<extra></extra>"))
        fig.update_layout(height=200, margin=dict(l=0, r=40, t=6, b=0),
                          yaxis=dict(autorange="reversed"), xaxis_title=None,
                          paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, use_container_width=True)

        # PAR HEURE : empilees, parce que la question est « de quoi est faite cette heure »,
        # pas « combien y en a-t-il de chaque sorte ». Un 2px de fond separe les segments.
        if _F.get("par_heure"):
            h = pd.DataFrame(_F["par_heure"])
            h["quand"] = pd.to_datetime(h["t"], unit="s", utc=True).dt.tz_convert("Europe/Paris")
            fig = go.Figure()
            for cle, nom, coul in (("hors", "hors bande (le modèle refuse)", DOUX),
                                   ("pause", "bloqués (la pause refuse)", ACCENT),
                                   ("achat", "achetés", GAIN)):
                fig.add_trace(go.Bar(x=h["quand"], y=h[cle], name=nom, marker_color=coul,
                                     marker_line=dict(width=2, color="rgba(0,0,0,0)"),
                                     hovertemplate="%%{x|%%d/%%m %%Hh} — %%{y} %s<extra></extra>" % nom))
            fig.update_layout(barmode="stack", height=260, margin=dict(l=0, r=0, t=6, b=0),
                              yaxis_title="décisions", legend=dict(orientation="h", y=-.22),
                              paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig, use_container_width=True)
            st.caption("Une heure sans barre verte n'est pas une panne : c'est soit le modèle qui "
                       "ne trouve rien dans la bande (gris), soit la pause qui bloque (orange).")

        if _F.get("periodes"):
            with st.expander("L'historique des pauses (%d dernières)" % len(_F["periodes"])):
                pp = pd.DataFrame(_F["periodes"])
                pp["début"] = (pd.to_datetime(pp["debut"], unit="s", utc=True)
                               .dt.tz_convert("Europe/Paris").dt.strftime("%d/%m %H:%M"))
                pp["fin"] = (pd.to_datetime(pp["fin"], unit="s", utc=True)
                             .dt.tz_convert("Europe/Paris").dt.strftime("%d/%m %H:%M"))
                pp["durée (min)"] = pp["minutes"]
                pp["tickets refusés"] = pp["n"]
                pp["en cours"] = pp["ouverte"].map({True: "oui", False: ""})
                st.dataframe(pp[["début", "fin", "durée (min)", "tickets refusés", "en cours"]]
                             .iloc[::-1], use_container_width=True, hide_index=True)
        st.divider()

    # ------------------------------------------------------------- variantes
    # LES TROIS VARIANTES DE LA REGLE EN SERVICE, a depart commun.
    #
    # Mido, 22/09 : « t as une idee pour les presenter sur le meme graphique ? ». Le probleme
    # n etait pas l echelle mais le DEPART : la regle en service a 162 tickets d avance sur des
    # candidates qui en ont zero. Toutes repartent donc du gel des candidates -- memes tickets,
    # meme marche, memes instants, seule la regle differe.
    #
    # DEUX CHOIX QUI EVITENT DE SE MENTIR :
    #   - l axe Y est en EUR PAR TICKET, pas en euros cumules. Sur la page principale, une ligne
    #     a 357 tickets/jour ecrase une ligne a 33 en montrant son VOLUME et pas sa qualite.
    #   - une ligne a +0,38 EUR/ticket : ce qu une pause rapporte sur des rendements MELANGES,
    #     par pure mecanique (3.171). Au-dessus de zero mais sous cette ligne, une courbe ne
    #     gagne rien. Sans ce repere le graphique fait croire que « positif = ca marche ».
    _V = D.get("variantes") or {}
    if _V.get("lignes"):
        st.subheader("Les trois variantes de la règle")
        st.caption("Toutes partent du **%s**, le gel des candidates : elles voient donc les "
                   "**mêmes tickets**, et seule la règle diffère. L'axe est en **€ par ticket** — "
                   "en euros cumulés, une ligne qui trade beaucoup écraserait les autres sans être "
                   "meilleure." % _V.get("gel_lisible", "?"))
        st.caption("⚠️ Depuis le **26/09 à 12h38**, c'est **B · MODÈLE FRAIS** qui est en "
                   "production. `BANDE + PAUSE` continue de tourner en papier comme **témoin**, "
                   "pour qu'on puisse dire si la bascule valait le coup — voir l'onglet *Marché*.")
        _vides = [l["nom"] for l in _V["lignes"] if len(l.get("courbe") or []) < 1]
        _trac = [l for l in _V["lignes"] if len(l.get("courbe") or []) >= 1]
        if _vides:
            st.caption("Pas encore de ticket, donc rien à tracer : **%s**." % " · ".join(_vides))
        if _trac:
            fig = go.Figure()
            for i, l in enumerate(_trac):
                d = pd.DataFrame(l["courbe"], columns=["t", "moy", "bruit"])
                d["quand"] = pd.to_datetime(d["t"], unit="s", utc=True).dt.tz_convert("Europe/Paris")
                c = VARIANTES_T[i % len(VARIANTES_T)]
                # LA BANDE D INCERTITUDE D ABORD, pour qu elle passe SOUS les traits.
                fig.add_trace(go.Scatter(
                    x=list(d["quand"]) + list(d["quand"])[::-1],
                    y=list(d["moy"] + d["bruit"]) + list(d["moy"] - d["bruit"])[::-1],
                    fill="toself", fillcolor=_alpha(c, .13), line=dict(width=0),
                    hoverinfo="skip", showlegend=False))
            for i, l in enumerate(_trac):
                d = pd.DataFrame(l["courbe"], columns=["t", "moy", "bruit"])
                d["quand"] = pd.to_datetime(d["t"], unit="s", utc=True).dt.tz_convert("Europe/Paris")
                c = VARIANTES_T[i % len(VARIANTES_T)]
                fig.add_trace(go.Scatter(
                    x=d["quand"], y=d["moy"], mode="lines",
                    name="%s — %d tickets" % (l["nom"], len(d)),
                    line=dict(color=c, width=2),
                    hovertemplate="<b>%s</b><br>%%{x|%%d/%%m %%Hh%%M}"
                                  "<br>%%{y:+.2f} € / ticket<extra></extra>" % l["nom"]))
                # ETIQUETTE DIRECTE au bout : l identite ne repose jamais sur la seule couleur
                # (une paire de la palette est a 7,3 de separation daltonienne, sous la cible de 8).
                fig.add_annotation(x=d["quand"].iloc[-1], y=d["moy"].iloc[-1],
                                   text=" %s" % l["nom"].split(" · ")[0], showarrow=False,
                                   xanchor="left", font=dict(color=c, size=11))
            fig.add_hline(y=0, line=dict(color=DOUX, width=1, dash="dot"))
            fig.add_hline(y=_V.get("nul", 0.384), line=dict(color=DOUX, width=1, dash="dash"),
                          annotation_text="le hasard (+%.2f)" % _V.get("nul", 0.384),
                          annotation_position="right",
                          annotation_font=dict(color=DOUX, size=11))
            fig.update_layout(height=380, margin=dict(l=0, r=110, t=6, b=0),
                              yaxis_title="€ par ticket (moyenne courante)",
                              legend=dict(orientation="h", y=-.18),
                              paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig, use_container_width=True)
            st.dataframe(pd.DataFrame([
                {"variante": l["nom"], "tickets": len(l["courbe"]),
                 "€/ticket": l["courbe"][-1][1] if l["courbe"] else None,
                 "bruit": l["courbe"][-1][2] if l["courbe"] else None}
                for l in _trac]), use_container_width=True, hide_index=True)
        st.caption("La **bande grise** autour de chaque courbe est le bruit sur la moyenne. Tant "
                   "qu'elles se chevauchent, l'écart entre deux règles n'est pas lisible. "
                   "Échéance du gel : **200 tickets retenus ou 14 jours**.")
        st.divider()

    st.subheader("Gain cumulé")
    st.caption("Chaque courbe part de **zéro à son propre démarrage** — elles ne commencent pas "
               "toutes à la même date, donc deux courbes superposées ne couvrent pas les mêmes "
               "heures de marché. La date de début est rappelée dans la légende.")
    # TOUTES les strategies declarees sont dans le selecteur, y compris celles a zero ticket. Deux
    # fois de suite j ai exclu un gel tout neuf de l endroit ou on le cherche -- d abord en le
    # mettant dans un bloc a part, puis en exigeant qu il ait deja une courbe. Mido a du me le dire
    # deux fois. Une strategie qu on vient de geler DOIT etre visible la ou on regarde, meme vide :
    # c est justement le moment ou l on veut verifier qu elle existe.
    dispo = list(D["lignes"])
    noms = [l["nom"] + ("" if len(l.get("courbe") or []) >= 2 else "  (pas encore de ticket)")
            for l in dispo]
    par_nom = dict(zip(noms, dispo))
    defaut = [n for n in (["temoin sans filtre"] + [c["nom"] for c in D["contre_temoin"][:3]]) if n in noms]
    choix = st.multiselect("Lignes affichées", noms, default=defaut, key="courbes")
    # Une ligne cochee sans ticket ne se trace pas -- on le dit, au lieu de la faire disparaitre.
    retenues = [par_nom[n] for n in choix]
    vides = [l["nom"] for l in retenues if len(l.get("courbe") or []) < 2]
    if vides:
        st.caption("Sélectionnée%s mais pas encore de ticket, donc rien à tracer : **%s**. "
                   "Elle apparaîtra dès sa première coupe."
                   % ("s" if len(vides) > 1 else "", " · ".join(vides)))
    traçables = [l for l in retenues if len(l.get("courbe") or []) >= 2]
    if traçables:
        fig = go.Figure()
        for i, l in enumerate(traçables):
            d = pd.DataFrame(l["courbe"], columns=["t", "cum"])
            d["quand"] = pd.to_datetime(d["t"], unit="s", utc=True).dt.tz_convert("Europe/Paris")
            depuis = d["quand"].iloc[0].strftime("%d/%m")
            fig.add_trace(go.Scatter(
                x=d["quand"], y=d["cum"], mode="lines",
                name="%s — dep. %s, %d tickets" % (l["nom"], depuis, l["n"]),
                line=dict(color=TEINTES[i % len(TEINTES)], width=2),
                hovertemplate="<b>%s</b><br>%%{x|%%d/%%m %%Hh}<br>%%{y:+.0f} € cumulés<extra></extra>"
                              % l["nom"]))
        fig.add_hline(y=0, line=dict(color=DOUX, width=1, dash="dot"))
        fig.update_layout(height=400, margin=dict(l=0, r=0, t=6, b=0), yaxis_title="€ cumulés",
                          legend=dict(orientation="h", y=-.16),
                          paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, use_container_width=True)

        st.subheader("Gain par jour")
        st.caption("Le cumulé est écrasé par le témoin : une ligne à 60 tickets y est un trait "
                   "plat. Par jour, chacune se lit à son échelle — et on voit tout de suite si "
                   "une stratégie gagne **tous les jours** ou si elle tient sur une seule journée.")
        jours = sorted({d["jour"] for l in retenues for d in (l.get("par_jour") or [])})
        if jours:
            fig = go.Figure()
            for i, l in enumerate(retenues):
                m = {d["jour"]: d for d in (l.get("par_jour") or [])}
                fig.add_trace(go.Bar(
                    name=l["nom"], x=jours,
                    y=[(m.get(j) or {}).get("gain") for j in jours],
                    marker_color=TEINTES[i % len(TEINTES)],
                    customdata=[[(m.get(j) or {}).get("n") or 0] for j in jours],
                    hovertemplate="<b>%s</b><br>%%{x}<br>%%{y:+.0f} € sur %%{customdata[0]} tickets"
                                  "<extra></extra>" % l["nom"]))
            fig.add_hline(y=0, line=dict(color=DOUX, width=1))
            fig.update_layout(barmode="group", height=340, margin=dict(l=0, r=0, t=6, b=0),
                              yaxis_title="€ gagnés ce jour-là",
                              legend=dict(orientation="h", y=-.2),
                              paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig, use_container_width=True)

            t = pd.DataFrame([{"stratégie": l["nom"],
                               **{d["jour"][5:]: d["gain"] for d in (l.get("par_jour") or [])}}
                              for l in retenues])
            st.dataframe(t, use_container_width=True, hide_index=True)

    st.subheader("Registre complet")
    r = pd.DataFrame([{k: v for k, v in l.items() if k not in ("courbe", "par_jour")} for l in D["lignes"]])
    r["depuis"] = pd.to_datetime(r["debut"], unit="s", utc=True).dt.tz_convert("Europe/Paris").dt.strftime("%d/%m %H:%M")
    # LES SEPT CRITERES, et pas seulement les euros. Mido, 20/09 : « j'ai l'impression que le seul
    # élément qui te fait dire strat bonne ou mauvaise c'est ton sigma, t'es sûr de ça ? » — non :
    # la ligne la plus significative du projet est le TÉMOIN. Une stratégie se juge sur plusieurs
    # axes à la fois, donc ils doivent être ici, pas dans un script que je relance à la demande.
    for c_ in ("eur_jour", "gagnants_pct", "moitie_1", "moitie_2", "sans3_part"):
        if c_ not in r.columns:
            r[c_] = None
    # « GARDE SANS SES 3 » : la PART de l'avance qui survit quand on retire les trois meilleurs
    # tickets. `sans3 > 0` était trop laxiste — BANDE + PAUSE le passait à +0,204 après avoir perdu
    # 91 % de son avance, parce que 3 tickets sur 80 portaient tout (§3.163).
    # Une ligne sans ticket doit afficher « — », pas « nan % » : un gel tout neuf se lit d abord
    # dans ce tableau, et c est le moment ou l on veut verifier qu il existe, pas voir du bruit.
    def _ok(x):
        return x is not None and x == x        # x != x est vrai pour NaN

    r["moities"] = [("%+.2f / %+.2f" % (a, b)) if _ok(a) and _ok(b) else "—"
                    for a, b in zip(r["moitie_1"], r["moitie_2"])]
    r["survie3"] = [("%.0f %%" % (100 * x)) if _ok(x) else "—" for x in r["sans3_part"]]
    r["gagn"] = [("%.0f %%" % x) if _ok(x) else "—" for x in r["gagnants_pct"]]
    r = r[["nom", "n", "par_ticket", "eur_jour", "gagn", "moities", "survie3", "total", "depuis"]]
    r = r.sort_values("par_ticket", ascending=False)
    r.columns = ["stratégie", "tickets", "€/ticket", "€/jour", "gagnants", "2 moitiés",
                 "garde sans ses 3", "total €", "depuis"]
    st.dataframe(r, use_container_width=True, hide_index=True, height=min(760, 38 * len(r) + 40))
    st.caption("**Aucun de ces critères ne suffit seul.** *€/ticket* est ce qui paie ; *€/jour* "
               "corrige le volume (85 tickets à +2,5 n'est pas 600 à +0,3) ; *2 moitiés* dit si "
               "elle gagne tout le temps ou a eu un bon jour ; *garde sans ses 3* est la part de "
               "l'avance qui survit quand on retire ses trois meilleurs tickets — sous 50 %, "
               "l'avance tient à quelques coups ; *gagnants* sépare « beaucoup de petits gains » "
               "de « une pièce à peine biaisée ».")
    # DEUX SORTIES DIFFERENTES SUR LE MEME TABLEAU. Trouve le 20/09 parce que Mido a vu
    # « FORET REENTRAINEE 6h se degrade beaucoup plus que la figee » : elle ne se degrade pas, elle
    # vend 47 s plus tot. Le dire ici, sinon la comparaison est silencieusement fausse.
    st.warning("**Deux sorties différentes cohabitent dans ce tableau.** Les lignes `FORET 75s…` "
               "et `FORET REENTRAINEE 6h` sont mesurées sur une **sortie à 240 s** ; toutes les "
               "autres — témoin compris — sur une **sortie à 287 s**, celle du moteur. "
               "47 secondes de détention d'écart : +0,22 point en moyenne sur l'historique, mais "
               "**3,85 points le 20/09**. Comparer une ligne d'une famille à une ligne de l'autre "
               "n'est donc valable qu'à ce bruit près. À l'intérieur d'une famille, et pour "
               "l'écart au témoin, les chiffres sont propres. `FORET GAGNANT` a été regelée le "
               "20/09 à 15h56 sur la sortie à 287 s.", icon="⚠️")

    with st.expander("La table telle qu'elle sort du terminal"):
        st.code(D.get("texte") or "(texte non enregistré)", language=None)


# =============================================================== LES COUTS (registre continu)
F_COUT = os.path.join(RACINE, "cout_serie.json")
POSTES = [("pool", "commission du pool", "#6b9ec9"), ("impact", "impact de notre ordre", "#b98ac7"),
          ("frais_reseau", "frais de réseau", "#5cab7a"), ("caution", "caution du compte-jeton", "#d4a03c"),
          # PLUS « inexpliqué » : il l'était, il ne l'est plus. §3.156 a ouvert la transaction au
          # lamport — ce sont TROIS prélèvements de frais exécutés dans notre transaction, 1,21 %
          # par jambe, soit 2,42 % l'aller-retour ; le registre en mesure 2,44. Garder l'étiquette
          # « inexpliqué » m'a fait ré-enquêter dessus le 20/09 sur une chose résolue depuis 24 h.
          ("inexplique", "prélèvements de frais", "#c9564b")]


@st.fragment(run_every=60)
def couts():
    S = lire(F_COUT)
    if not S:
        st.info("Le registre des coûts n'est pas encore écrit.")
        return
    t = S["tout"]
    st.caption("Registre écrit ticket par ticket, jamais recalculé — %d tickets, %s. "
               "Le coût est l'écart entre ce que le **prix** du jeton a fait et ce que ton "
               "**portefeuille** a encaissé, divisé par les euros déployés."
               % (S["n"], age(S["genere"])))
    c = st.columns(4)
    c[0].metric("Coût mesuré", "%.2f pt" % t["total"], "%d tickets" % t["n"], delta_color="off")
    c[1].metric("Déployé", eur(t["deploye"]) + " €", "au total", delta_color="off")
    c[2].metric("Ce que ça a coûté", eur(-t["euros"]["total"], 2) + " €", "en euros", delta_color="off")
    av, ap = S.get("avant_bascule"), S.get("apres_bascule")
    if av and ap:
        c[3].metric("Depuis les économies", "%.2f pt" % ap["total"],
                    "contre %.2f avant · %d tickets" % (av["total"], ap["n"]), delta_color="off")

    st.subheader("Où part l'argent")
    unite = st.radio("Normalisation", ["€ par ticket", "points de mise"], horizontal=True,
                     key="unite_cout", label_visibility="collapsed")
    par_tick = unite.startswith("€")
    st.caption("**€ par ticket** : ce que chaque ticket coûte vraiment. C'est la seule vue qui "
               "montre l'effet d'un changement de mise — passer de 20 à 10 € divise le coût par "
               "deux. **Points de mise** : le coût en % de ce qu'on engage ; il compare des régimes "
               "de mise différents, mais masque justement le changement de mise."
               if par_tick else
               "**Points de mise** : coût en % de ce qu'on engage. Déjà divisé par la mise, donc "
               "il ne bouge pas quand la mise change. Bascule sur **€ par ticket** pour voir "
               "l'effet du passage de 20 à 10 €.")

    def val(d, cle):
        return (d["par_ticket"][cle] if par_tick else d[cle]) if d else None

    fig = go.Figure()
    blocs = [("tout", t)] + ([("avant", av)] if av else []) + ([("depuis", ap)] if ap else [])
    for cle, lib, col in POSTES:
        for i, (nom, d) in enumerate(blocs):
            fig.add_trace(go.Bar(
                name=lib, y=["%s (%d tickets, mise %.0f €)" % (nom, d["n"], d.get("mise_moy") or 0)],
                x=[val(d, cle)], orientation="h", marker_color=col, showlegend=(i == 0),
                hovertemplate="%s : %%{x:.4f}<extra></extra>" % lib))
    fig.update_layout(barmode="stack", height=230, margin=dict(l=0, r=0, t=6, b=0),
                      xaxis_title="€ par ticket" if par_tick else "points de coût (1 pt = 1 % de la mise)",
                      legend=dict(orientation="h", y=-.3),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig, use_container_width=True)

    u = "€/ticket" if par_tick else "pt"
    d = pd.DataFrame([{"poste": lib, "tout (%s)" % u: val(t, cle),
                       "avant (%s)" % u: val(av, cle), "depuis (%s)" % u: val(ap, cle),
                       "euros au total": t["euros"][cle]} for cle, lib, _ in POSTES]
                     + [{"poste": "TOTAL", "tout (%s)" % u: val(t, "total"),
                         "avant (%s)" % u: val(av, "total"), "depuis (%s)" % u: val(ap, "total"),
                         "euros au total": t["euros"]["total"]}])
    st.dataframe(d, use_container_width=True, hide_index=True)
    st.caption("La bascule du 19/09 10h53 : récupération de la caution activée, priorité d'achat "
               "divisée par 5. La colonne « depuis » dit si ça a marché — elle a besoin d'une "
               "soixantaine de tickets pour être crédible.")

    if S.get("glissant"):
        st.subheader("Le coût dans le temps")
        st.caption("Moyenne glissante sur les 30 derniers tickets. Un point apparaît dès le 5ᵉ. "
                   "La mise moyenne de la fenêtre est tracée en dessous : une baisse du coût qui "
                   "suit une baisse de mise n'est pas une amélioration de l'exécution.")
        g = pd.DataFrame(S["glissant"])
        g["quand"] = pd.to_datetime(g["t"], unit="s", utc=True).dt.tz_convert("Europe/Paris")
        col = "par_ticket" if (par_tick and "par_ticket" in g) else "total"
        fig = go.Figure(go.Scatter(x=g["quand"], y=g[col], mode="lines",
                                   line=dict(color=ACCENT, width=2), name="coût"))
        if "mise_moy" in g:
            fig.add_trace(go.Scatter(x=g["quand"], y=g["mise_moy"], mode="lines", name="mise moyenne",
                                     line=dict(color=DOUX, width=1, dash="dot"), yaxis="y2"))
        fig.add_hline(y=0, line=dict(color=DOUX, width=1, dash="dot"))
        fig.update_layout(height=280, margin=dict(l=0, r=0, t=6, b=0),
                          yaxis_title="€ par ticket" if col == "par_ticket" else "points de coût",
                          yaxis2=dict(title="mise €", overlaying="y", side="right", showgrid=False),
                          legend=dict(orientation="h", y=-.2),
                          paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, use_container_width=True)

    if S.get("par_jour"):
        st.subheader("Par jour")
        j = pd.DataFrame([{"jour": k, "tickets": v["n"], "mise moy €": v.get("mise_moy"),
                           "déployé €": v["deploye"], "coût pt": v["total"],
                           "coût €/ticket": (v.get("par_ticket") or {}).get("total"),
                           "coût € total": v["euros"]["total"],
                           **{lib: val(v, cle) for cle, lib, _ in POSTES}}
                          for k, v in S["par_jour"].items()])
        st.dataframe(j, use_container_width=True, hide_index=True)

    with st.expander("Les derniers tickets, un par un"):
        r = pd.DataFrame(S["derniers"])
        r["quand"] = pd.to_datetime(r["t"], unit="s", utc=True).dt.tz_convert("Europe/Paris").dt.strftime("%d/%m %H:%M")
        cols = ["quand", "mise", "q", "brut_pct", "gain", "frais_reseau", "caution", "impact",
                "pool", "inexplique", "total", "total_pct"]
        st.dataframe(r[[c for c in cols if c in r]].iloc[::-1],
                     use_container_width=True, hide_index=True, height=420)


def _queue_haute(q: dict):
    """LA QUEUE HAUTE SUR 3 JOURS — le seul indicateur de marché qui explique nos pertes.

    27/09 (§0.2 undecies du journal). La dégradation du flux brut du 24 au 27/09, −1,01 €/ticket,
    est **entièrement** l'amincissement de la queue haute : 17,5 % → 14,7 % de gros gains. Les deux
    autres composantes n'ont pas bougé — le taux d'effondrement (37,8 → 38,6) ni la taille du gros
    gain (+1,223 → +1,206). Vérification : 0,028 × 1,21 × 25 € = 0,85 € contre 1,01 mesuré.

    ET LA PAUSE NE PEUT RIEN CONTRE ÇA. Elle repère les *poches locales* à queue mince et les évite
    (15,7 % contre 22,3 %). Si le marché entier passe en queue mince, il n'y a plus de poche épaisse
    où se réfugier : elle n'est pas cassée, elle n'a plus rien à choisir.

    Pourquoi 3 jours et pas 1 : à ~280 pools/jour le bruit sur cette part est de ±2,2 pt, donc les
    −2,8 pt qui expliquent tout valent 1 σ sur une journée. **En dessous de 2 σ il n'y a rien à
    lire** — c'est écrit en clair pour que le chiffre ne se lise pas comme une tendance.
    """
    if not q.get("lisible"):
        return
    st.markdown("**La queue haute (part des pools ≥ +50 %) — 3 derniers jours contre les jours "
                "d'avant.** C'est la seule des trois composantes du marché qui bouge, et c'est "
                "elle qui paie. Sous 2 σ, rien à lire.")
    lignes = []
    for cle in ("marche", "bande", "sur"):
        t = q.get(cle)
        if not t:
            continue
        lignes.append({"population": t["nom"],
                       "3 derniers jours": "%.1f %% (n=%d)" % (t["pct_3j"], t["n_3j"]),
                       "avant": "%.1f %% (n=%d)" % (t["pct_ref"], t["n_ref"]),
                       "écart": "%+.1f pt ± %.1f" % (t["ecart_pt"], t["ic_pt"]),
                       "σ": "%.2f" % t["sigma"]})
    st.dataframe(lignes, use_container_width=True, hide_index=True)
    if q.get("conc_3j") is not None and q.get("conc_ref") is not None:
        st.caption("**Pouvoir de concentration de la bande** (queue de la bande ÷ queue du marché) : "
                   "×%.2f ces 3 jours contre ×%.2f avant. Le 24-27/09 il est passé de ×1,82 à "
                   "×1,58 pendant que le marché restait plat : la queue était sortie de la bande."
                   % (q["conc_3j"], q["conc_ref"]))
    m, b = q.get("marche") or {}, q.get("bande") or {}
    sm, sb = m.get("sigma", 0.0), b.get("sigma", 0.0)
    if sm <= -2.0:
        st.error("**C'est le marché** : sa queue a minci (%.2f σ). Aucune règle ne récupère ça — "
                 "la pause évite les poches locales à queue mince, pas un marché entier en queue "
                 "mince." % sm)
    elif b and sb <= -2.0 and abs(sm) < 2.0:
        st.error("**C'est nous, pas le marché** : le marché est plat (%.2f σ) mais la bande a "
                 "perdu sa queue (%.2f σ, %+.2f €/ticket). C'est une dérive du score — la "
                 "réponse est dans le modèle, pas dans la règle. Un challenger gelé sur données "
                 "récentes est le remède ; `challenger.py` le juge."
                 % (sm, sb, q.get("cout_eur_ticket", 0.0)))
    elif sm >= 2.0:
        st.success("**La queue du marché s'est épaissie** (%.2f σ). C'est le marché qui donne, "
                   "pas la règle qui s'améliore." % sm)
    else:
        st.caption("Rien au-dessus de 2 σ : les écarts sont dans le bruit.")


def marche():
    """« C'EST MOI OU C'EST LE MARCHÉ ? » — la question que la page ne savait pas trancher.

    Mido, 26/09 : *« ajoute des indicateurs marché, car quand moi je perds de l'argent je sais pas
    si c'est le marché ou mes strats »*. Elle montrait le résultat de la règle sans jamais dire ce
    que le marché offrait CE JOUR-LÀ — donc une perte était toujours ambiguë.

    LA COLONNE QUI RÉPOND EST L'ÉCART : ce que la règle a fait, moins ce qu'un pool éligible pris au
    hasard rapportait le même jour. Positif un jour de perte = la règle a bien travaillé dans un
    marché mauvais. Négatif = c'est la règle.
    """
    M = lire(F_MARCHE)
    if not M or not M.get("jours"):
        st.info("Pas encore de données de marché — `carnet_json` les écrit toutes les 5 minutes.")
        if M and M.get("erreur"):
            st.caption("erreur : %s" % M["erreur"])
        return
    jours = M["jours"]
    d = jours[-1]

    st.subheader("Aujourd'hui : le marché, et nous")
    c = st.columns(4)
    c[0].metric("Le marché (pool au hasard)", eur(d["marche_eur"], 2),
                help="Rendement net d'un pool éligible pris au hasard. C'est le tarif du jour : "
                     "s'il est négatif, perdre est normal.")
    c[1].metric("BANDE + PAUSE (papier)",
                eur(d["regle_eur"], 2) if d.get("regle_eur") is not None else "—",
                help="Sur les tickets que la règle aurait pris, pause comprise.")
    c[2].metric("ÉCART BANDE + PAUSE − marché", eur(d["ecart"], 2) if d.get("ecart") is not None else "—",
                delta=None,
                help="Règle moins marché. C'est la seule colonne qui dit si c'est vous ou le marché.")
    c[3].metric("Gros gains au marché", "%.1f %%" % d["gros_gains_pct"],
                help="Part des pools au-dessus de +50 %%. Tout l'argent vient de là : "
                     "un jour sans queue est un jour sans gain, quelle que soit la règle. "
                     "Bruit du jour : ±%.1f pt — ne pas lire ce chiffre seul, voir en dessous."
                     % d.get("gros_gains_ic", 0.0))

    _queue_haute(M.get("queue") or {})

    if d.get("ecart") is not None:
        if d["ecart"] > 0 and (d.get("regle_eur") or 0) < 0:
            st.warning("Journée perdante, mais **la règle a fait mieux que le marché** "
                       "(%+.2f €/ticket d'écart). Le marché était mauvais." % d["ecart"])
        elif d["ecart"] < 0:
            st.error("**La règle a fait moins bien que le marché** (%+.2f €/ticket). "
                     "Ce n'est pas le marché." % d["ecart"])

    st.subheader("Les dix derniers jours")
    lignes = []
    for j in jours:
        lignes.append({
            "jour": j["jour"], "pools": j["n"],
            "marché €/ticket (pool au hasard)": j["marche_eur"],
            "effondrements": "%.1f %%" % j["effondrement_pct"],
            "gros gains": ("%.1f %% ± %.1f" % (j["gros_gains_pct"], j["gros_gains_ic"])
                           if j.get("gros_gains_ic") is not None
                           else "%.1f %%" % j["gros_gains_pct"]),
            "×2": "%.1f %%" % j["x2_pct"],
            "BANDE + PAUSE €/ticket (papier)": j.get("regle_eur"),
            "écart": j.get("ecart"),
        })
    st.dataframe(lignes, use_container_width=True, hide_index=True)
    st.caption("`marché` = ce que rapporte un pool éligible au hasard, net du péage, à la mise de "
               "la page. `écart` = règle − marché : **c'est lui qui répond à « moi ou le marché »**.")



st.title("Carnet Tangier")


# HORLOGE DE VIE. Si elle cesse d'avancer, la page est décrochée et tout ce qui est en dessous est
# périmé. Sans elle, une session figée ressert son dernier rendu — âge des données compris.
@st.fragment(run_every=2)
def horloge():
    st.caption("⏱ page vivante · %s" % dt.datetime.now(TZ).strftime("%d/%m %H:%M:%S"))


horloge()

# TROIS ONGLETS, ET CHACUN DIT EN PREMIÈRE LIGNE CE QU'IL MONTRE. Mido, 27/09 : « trop bordélique,
# on voit des chiffres on sait pas quelle strat ». La frontière qui compte est ARGENT RÉEL contre
# PAPIER : un chiffre papier lu comme de l'argent a déjà coûté cher (−436 € le 15/09).
onglets = st.tabs(["💶 Argent réel", "📉 Marché : moi ou le marché ?", "🧪 Recherche (papier, 0 €)"])
with onglets[0]:
    st.success("**ARGENT RÉEL** — deux stratégies tournent : **BANDE + PAUSE** (25 €) et **G+D** "
               "(20 €). Chaque chiffre porte le nom de sa stratégie.")
    argent_reel()
with onglets[1]:
    st.info("**MARCHÉ** — ce que le marché offrait chaque jour, pour savoir si une perte vient de "
            "lui ou de **BANDE + PAUSE**. Tout est calculé sur le carnet papier, pas sur l'argent réel.")
    marche()
with onglets[2]:
    st.warning("**PAPIER, 0 €** — rien ici n'est de l'argent. Ce sont des règles et des modèles "
               "testés sans acheter. Seule la section « Coûts » vient des vrais tickets de "
               "BANDE + PAUSE.")
    with st.expander("Les stratégies testées sur papier", expanded=True):
        table_complete()
    with st.expander("Coûts réels d'exécution (BANDE + PAUSE)"):
        couts()
