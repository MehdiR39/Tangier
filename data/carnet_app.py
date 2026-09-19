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
TZ = dt.timezone(dt.timedelta(hours=2))

GAIN, PERTE, ACCENT, DOUX = "#3f9c6d", "#c9564b", "#d4a03c", "#8b9098"
TEINTES = ["#d4a03c", "#5cab7a", "#d4695e", "#6b9ec9", "#b98ac7", "#c9a06b", "#7fb3a3", "#c78fa0"]

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


# =========================================================== LE CARNET RÉEL (rythme rapide)
@st.fragment(run_every=5)
def bandeau_reel():
    L = lire(F_LIVE)
    if not L:
        st.info("Le carnet réel n'est pas encore écrit — `carnet_json.py` tourne-t-il dans le conteneur ?")
        return
    f = L["fenetre_24h"]
    bloque = f["bloque"]
    st.markdown(
        '<div class="bandeau %s"><b>%s</b> — budget de perte sur 24 h glissantes : '
        '<span class="mono">%s €</span> sur un plafond de <span class="mono">%s €</span>. '
        'Marge restante <span class="mono">%s €</span>.</div>'
        % ("bloque" if bloque else "ouvert",
           "ACHATS BLOQUÉS" if bloque else "achats ouverts",
           eur(f["gain"]), eur(f["plafond"]), eur(f["marge"])),
        unsafe_allow_html=True)

    c = st.columns(5)
    c[0].metric("Aujourd'hui", eur(L["jour"]["gain"]) + " €", "%d ordres" % L["jour"]["n"],
                delta_color="off")
    c[1].metric("Depuis le début", eur(L["total"]["gain"]) + " €",
                "%d tickets fermés" % L["total"]["n"], delta_color="off")
    c[2].metric("Positions ouvertes", str(L["ouvertes"]))
    st_ = L.get("statuts") or {}
    c[3].metric("Achetés aujourd'hui", str(st_.get("FERMEE", 0) + L["ouvertes"]))
    c[4].metric("Refusés aujourd'hui", str(sum(v for k, v in st_.items() if k != "FERMEE")))
    st.caption("carnet réel · %s" % age(L["genere"]))

    if st_:
        with st.expander("Pourquoi des tickets ont été refusés aujourd'hui"):
            for k, v in sorted(st_.items(), key=lambda x: -x[1]):
                st.write("**%s** — %d" % (k, v))
            for k, v in (L.get("motifs") or {}).items():
                st.caption("« %s » — %d" % (str(k)[:110], v))

    if L.get("courbe"):
        d = pd.DataFrame(L["courbe"], columns=["t", "cum"])
        d["quand"] = pd.to_datetime(d["t"], unit="s", utc=True).dt.tz_convert("Europe/Paris")
        fig = go.Figure(go.Scatter(x=d["quand"], y=d["cum"], mode="lines",
                                   line=dict(color=ACCENT, width=2), name="réel"))
        fig.add_hline(y=0, line=dict(color=DOUX, width=1, dash="dot"))
        fig.update_layout(height=230, margin=dict(l=0, r=0, t=6, b=0),
                          yaxis_title="€ cumulés", showlegend=False,
                          paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, use_container_width=True)

    G = L.get("gains") or []
    if len(G) >= 5:
        # LE REGIME REGARDE. Melanger les periodes avant et apres une bascule, c est moyenner deux
        # bots differents : avant le 19/09 15h30 c est un autre modele ET une mise double.
        reg = L.get("regimes") or [{"cle": "tout", "nom": "Tout le carnet réel", "depuis": None}]
        noms = [r["nom"] for r in reg]
        defaut = len(noms) - 1 if len(noms) > 1 else 0        # par defaut : le regime EN COURS
        choisi = reg[noms.index(st.radio("Période", noms, index=defaut, horizontal=True,
                                         key="regime_reel", label_visibility="collapsed"))]
        g = pd.DataFrame(G)
        if choisi["depuis"]:
            g = g[g["t"] >= choisi["depuis"]]
        if g.empty:
            st.info("Aucun ticket fermé sur cette période pour l'instant.")
            return
        g["quand"] = pd.to_datetime(g["t"], unit="s", utc=True).dt.tz_convert("Europe/Paris")
        st.caption("%d tickets fermés · %s € au total · mise %s €"
                   % (len(g), eur(g["gain"].sum(), 2), eur(g["mise"].mean(), 0).lstrip("+")))

        st.subheader("Chaque ticket, un par un")
        st.caption("Vert = fermé en gain, rouge = fermé en perte. La hauteur est le résultat "
                   "réel du ticket, pas une estimation.")
        fig = go.Figure(go.Bar(
            x=g["quand"], y=g["gain"],
            marker_color=[GAIN if v >= 0 else PERTE for v in g["gain"]],
            hovertemplate="%{x|%d/%m %H:%M}<br><b>%{y:+.2f} €</b><extra></extra>"))
        fig.add_hline(y=0, line=dict(color=DOUX, width=1))
        fig.update_layout(height=280, margin=dict(l=0, r=0, t=6, b=0), yaxis_title="gain du ticket €",
                          showlegend=False, bargap=.1,
                          paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, use_container_width=True)

        st.subheader("Comment les gains se répartissent")
        gag, per = g[g["gain"] >= 0]["gain"], g[g["gain"] < 0]["gain"]
        st.caption("Ce marché est **asymétrique** : un gagnant peut rapporter plusieurs fois ce "
                   "qu'un perdant coûte, mais les perdants sont plus nombreux. C'est la forme de "
                   "cette distribution qui décide si une stratégie peut gagner, pas sa moyenne.")
        c = st.columns(4)
        c[0].metric("Gagnants", "%d (%.0f %%)" % (len(gag), 100 * len(gag) / len(g)))
        c[1].metric("Gain moyen", eur(gag.mean(), 2) + " €" if len(gag) else "—")
        c[2].metric("Perte moyenne", eur(per.mean(), 2) + " €" if len(per) else "—")
        c[3].metric("Médiane", eur(g["gain"].median(), 2) + " €")
        fig = go.Figure()
        fig.add_trace(go.Histogram(x=per, marker_color=PERTE, name="pertes", nbinsx=30))
        fig.add_trace(go.Histogram(x=gag, marker_color=GAIN, name="gains", nbinsx=30))
        fig.add_vline(x=0, line=dict(color=DOUX, width=1))
        fig.add_vline(x=g["gain"].mean(), line=dict(color=ACCENT, width=2, dash="dash"),
                      annotation_text="moyenne %s €" % eur(g["gain"].mean(), 2))
        fig.update_layout(height=300, margin=dict(l=0, r=0, t=26, b=0), barmode="overlay",
                          xaxis_title="gain du ticket €", yaxis_title="nombre de tickets",
                          legend=dict(orientation="h", y=-.22),
                          paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, use_container_width=True)

    # ---- CE QU ON A ECARTE : la foret a-t-elle jete des mauvais ou des bons ? -------------------
    E = L.get("evites") or []
    if E and len(G) >= 5:
        e = pd.DataFrame(E)
        if choisi["depuis"]:
            e = e[e["t"] >= choisi["depuis"]]
        pris = pd.DataFrame(G)
        if choisi["depuis"]:
            pris = pris[pris["t"] >= choisi["depuis"]]
        pris = pris[pris["brut_pct"].notna()]
        if len(e) and len(pris):
            st.subheader("Ce qu'on a écarté")
            st.caption("On n'a pas acheté ces jetons, mais le carnet papier sait ce que leur prix "
                       "a fait. C'est la seule façon de savoir si nos refus **protègent** ou "
                       "**coûtent** — et si la forêt écarte bien les mauvais.")
            LIB = {"ECARTEE": "écartés par la forêt", "BLOQUEE": "bloqués par le budget de perte",
                   "FREIN": "bloqués par le frein", "ANNULEE": "annulés (échec technique)"}
            lignes = [{"groupe": "ACHETÉS", "n": len(pris),
                       "rendement brut moyen %": round(pris["brut_pct"].mean(), 2),
                       "gagnants %": round(100 * (pris["brut_pct"] > 0).mean())}]
            for s_, sous in e.groupby("statut"):
                lignes.append({"groupe": LIB.get(s_, s_), "n": len(sous),
                               "rendement brut moyen %": round(sous["brut_pct"].mean(), 2),
                               "gagnants %": round(100 * (sous["brut_pct"] > 0).mean())})
            t = pd.DataFrame(lignes)
            fig = go.Figure(go.Bar(
                x=t["rendement brut moyen %"], y=t["groupe"], orientation="h",
                marker_color=[ACCENT if g_ == "ACHETÉS" else
                              (GAIN if v >= 0 else PERTE)
                              for g_, v in zip(t["groupe"], t["rendement brut moyen %"])],
                customdata=t[["n", "gagnants %"]].values,
                hovertemplate="<b>%{y}</b><br>%{x:+.2f} %% en moyenne<br>"
                              "%{customdata[0]} tickets · %{customdata[1]} %% gagnants<extra></extra>"))
            fig.add_vline(x=0, line=dict(color=DOUX, width=1))
            fig.update_layout(height=230, margin=dict(l=0, r=10, t=6, b=0),
                              xaxis_title="rendement brut du jeton, avant coût (%)",
                              yaxis=dict(autorange="reversed"), showlegend=False,
                              paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig, use_container_width=True)
            st.dataframe(t, use_container_width=True, hide_index=True)

            # PAR TRANCHE, pas seulement en moyenne. Une moyenne favorable peut cacher qu on jette
            # autant de gros gains que de grosses pertes -- et dans un marche aussi asymetrique,
            # perdre un jeton a +240 % coute plus cher qu eviter un a -80 %. Mido, 19/09 : « pas
            # que le rendement, il va falloir voir si la RF retire que des grosses pertes ou des
            # gros gains aussi, et dans quelle proportion ».
            ec = e[e["statut"] == "ECARTEE"]
            if len(ec) >= 5:
                st.caption("**Dans chaque tranche, combien de jetons ont été gardés et combien "
                           "écartés.** La question est simple : la forêt jette-t-elle surtout les "
                           "catastrophes (à gauche), ou jette-t-elle aussi les fusées (à droite) ? "
                           "Dans ce marché un jeton monte à +240 % quand une perte s'arrête à "
                           "−100 % — en jeter un gros coûte plus cher qu'en éviter un mauvais.")
                B = [-1e9, -50, -20, 0, 20, 50, 1e9]
                NB = ["catastrophe<br>< −50 %", "grosse perte<br>−50 à −20", "petite perte<br>−20 à 0",
                      "petit gain<br>0 à +20", "bon gain<br>+20 à +50", "gros gain<br>> +50 %"]
                cg = pd.cut(pris["brut_pct"], B, labels=NB).value_counts().reindex(NB).fillna(0)
                ce = pd.cut(ec["brut_pct"], B, labels=NB).value_counts().reindex(NB).fillna(0)
                tot = (cg + ce).replace(0, np.nan)
                fig = go.Figure()
                fig.add_trace(go.Bar(name="gardés", x=NB, y=cg.values, marker_color=ACCENT,
                                     text=[int(v) if v else "" for v in cg.values],
                                     textposition="inside",
                                     hovertemplate="<b>%{x}</b><br>%{y} jetons gardés<extra></extra>"))
                fig.add_trace(go.Bar(name="écartés", x=NB, y=ce.values, marker_color=PERTE,
                                     text=[int(v) if v else "" for v in ce.values],
                                     textposition="inside",
                                     customdata=(100 * ce / tot).round(0).values,
                                     hovertemplate="<b>%{x}</b><br>%{y} jetons écartés — "
                                                   "soit %{customdata:.0f} %% de cette tranche"
                                                   "<extra></extra>"))
                fig.update_layout(height=340, margin=dict(l=0, r=0, t=6, b=0), barmode="stack",
                                  yaxis_title="nombre de jetons",
                                  legend=dict(orientation="h", y=-.22),
                                  paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
                st.plotly_chart(fig, use_container_width=True)
                st.caption("La part rouge de chaque barre est ce que la forêt a refusé dans cette "
                           "tranche. **Elle trie bien si le rouge domine à gauche et disparaît à "
                           "droite.**")
                lig = pd.DataFrame({"tranche": [n.replace("<br>", " ") for n in NB],
                                    "jetons vus": (cg + ce).astype(int).values,
                                    "gardés": cg.astype(int).values,
                                    "écartés": ce.astype(int).values,
                                    "% écarté": (100 * ce / tot).round(0).values})
                st.dataframe(lig, use_container_width=True, hide_index=True)
            if len(ec) >= 5:
                d_ = ec["brut_pct"].mean() - pris["brut_pct"].mean()
                if d_ < 0:
                    st.success("**La forêt écarte bien les mauvais** : les %d jetons qu'elle a "
                               "refusés font %s %% en moyenne, contre %s %% pour ceux qu'elle a "
                               "gardés — %s points d'écart en sa faveur."
                               % (len(ec), eur(ec["brut_pct"].mean(), 2),
                                  eur(pris["brut_pct"].mean(), 2), eur(-d_, 2)))
                else:
                    st.warning("**Attention** : les %d jetons écartés par la forêt font %s %% en "
                               "moyenne, soit %s points de MIEUX que ceux qu'elle a gardés. Sur un "
                               "petit nombre c'est du hasard ; si ça tient, elle trie à l'envers."
                               % (len(ec), eur(ec["brut_pct"].mean(), 2), eur(d_, 2)))

    if L.get("derniers"):
        d = pd.DataFrame(L["derniers"])
        d["quand"] = pd.to_datetime(d["t"], unit="s", utc=True).dt.tz_convert("Europe/Paris").dt.strftime("%d/%m %H:%M")
        d = d[["quand", "symbole", "risque", "mise", "gain", "statut"]]
        d.columns = ["quand", "jeton", "risque", "mise €", "gain €", "statut"]
        st.dataframe(d, use_container_width=True, hide_index=True, height=260)


# =============================================================== LA TABLE (rythme lent)
@st.fragment(run_every=60)
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
    r = r[["nom", "n", "total", "par_ticket", "jour", "n_jour", "depuis"]].sort_values("total", ascending=False)
    r.columns = ["stratégie", "tickets", "total €", "€/ticket", "aujourd'hui €", "tickets du jour", "depuis"]
    st.dataframe(r, use_container_width=True, hide_index=True, height=min(760, 38 * len(r) + 40))

    with st.expander("La table telle qu'elle sort du terminal"):
        st.code(D.get("texte") or "(texte non enregistré)", language=None)


# =============================================================== LES COUTS (registre continu)
F_COUT = os.path.join(RACINE, "cout_serie.json")
POSTES = [("pool", "commission du pool", "#6b9ec9"), ("impact", "impact de notre ordre", "#b98ac7"),
          ("frais_reseau", "frais de réseau", "#5cab7a"), ("caution", "caution du compte-jeton", "#d4a03c"),
          ("inexplique", "inexpliqué", "#c9564b")]


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


st.title("Carnet Tangier")
st.caption("Tout ce qui a réellement tourné, au coût d'exécution mesuré sur la chaîne. "
           "Les chiffres viennent de `data/table_std2.py` — cette page ne recalcule rien.")


# HORLOGE DE VIE, en haut et bien visible. Elle ne sert qu'à une chose : si elle cesse d'avancer,
# la page est décrochée et tout ce qui est affiché en dessous est périmé. Sans elle, une session
# figée ressert indéfiniment son dernier rendu — âge des données compris, donc rassurant à tort.
@st.fragment(run_every=2)
def horloge():
    st.caption("⏱ page vivante · %s" % dt.datetime.now(TZ).strftime("%d/%m %H:%M:%S"))


horloge()

onglets = st.tabs(["Carnet réel", "Coûts", "Stratégies"])
with onglets[0]:
    bandeau_reel()
with onglets[1]:
    couts()
with onglets[2]:
    table_complete()
