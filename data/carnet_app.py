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
    """Depuis combien de temps ce fichier a-t-il été écrit ? Une page figée doit se dénoncer."""
    try:
        d = dt.datetime.fromisoformat(iso)
        s = (dt.datetime.now(dt.timezone.utc) - d).total_seconds()
        return ("il y a %.0f s" % s) if s < 90 else ("il y a %.0f min" % (s / 60))
    except Exception:
        return "?"


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
    dispo = [l for l in D["lignes"] if len(l.get("courbe") or []) > 2]
    noms = [l["nom"] for l in dispo]
    defaut = [n for n in (["temoin sans filtre"] + [c["nom"] for c in D["contre_temoin"][:3]]) if n in noms]
    choix = st.multiselect("Lignes affichées", noms, default=defaut, key="courbes")
    if choix:
        fig = go.Figure()
        for i, l in enumerate([x for x in dispo if x["nom"] in choix]):
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

    st.subheader("Registre complet")
    r = pd.DataFrame([{k: v for k, v in l.items() if k != "courbe"} for l in D["lignes"]])
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

onglets = st.tabs(["Carnet réel", "Coûts", "Stratégies"])
with onglets[0]:
    bandeau_reel()
with onglets[1]:
    couts()
with onglets[2]:
    table_complete()
