"""LA TABLE UNIQUE : une ligne par ticket, TOUTES les variables de TOUTES les sources.

MIDO, 18/09 au soir : « je te dis tout tout tout tout. Il faut partir d un scope tres large et
reduire, affiner, reduire, affiner. » Et le trou qu il a vu : chaque variable de ce projet a ete
testee SEULE -- le prix, puis les detenteurs, puis l image, puis les liens -- et jamais croisee.

Ce module ne teste rien. Il ASSEMBLE. Une ligne par ticket du carnet papier de reference, et en
colonnes tout ce que le projet sait de ce jeton A L INSTANT DE LA DECISION (45 s) :

  A  prix a 45 s (papier_combo.decision.variables)   19 colonnes
  B  metadonnee (solana_social) : liens declares, nom, symbole, description
  C  liens relus (liens.sqlite) : verification IPFS, nombre de champs
  D  image (images.sqlite) : luminance, couleurs, empreinte -> « gabarit deja vu » AVANT ce jeton
  E  detenteurs a 45 s (papier_social) : sac1, n_sacs5
  F  stock a 15/25/35/45 s (papier_stock) : parts hors coffre et leurs variations
  G  createur (sol_createur) : nombre de lancements ANTERIEURS du meme createur
  H  canal Telegram (tg_lignes) : poste dans un canal AVANT 45 s
  I  source du lancement (solana_stream_launches)
  J  temps : heure, jour, debit de lancements
  K  regime : taux de gagnants et moyenne des 20 derniers tickets CLOTURES avant la decision
  L  transactions des 45 premieres secondes (v1_avant) : acheteurs, tailles, robots recurrents
     connus AVANT ce jeton, vendeurs sans achat
  M  offre (mint_offre)

CIBLES, calculees a part et jamais melangees aux variables :
  brut_120, brut_240 (papier_combo.issue) et ret_H pour H dans {60, 90, 120, 180, 240, 287},
  lus dans solana_prix_chaine : entree au DERNIER prix <= 47 s, sortie au PREMIER prix >= H.

REGLE ABSOLUE, verifiee par un test : aucune colonne de cible ne commence par le meme prefixe
qu une variable, et la liste des variables est ecrite en dur (`VARIABLES`) -- un commentaire
egare avait deja laisse entrer des brut_* dans un modele (faux GO +108 %, journal §3.87).

LE FUTUR NE PASSE PAS. Tout ce qui compte des occurrences (createur en serie, gabarit d image,
robot recurrent) ne compte que les jetons NES AVANT celui-ci. Un robot vu dans 1 615 lancements
n est « recurrent » pour un jeton donne que s il l etait deja a la naissance de ce jeton.

Sortie : /app/data/recherche/tout/table.pkl (pandas). Usage :
    python -m intel.research.tout_table
"""
from __future__ import annotations

import glob
import json
import os
import sqlite3
import statistics as st
import sys
from collections import defaultdict

import pandas as pd

DOSSIER = "/app/data/recherche/tout"
V1 = "/app/data/recherche/v1_avant"
COMBO = "/app/db/papier_combo.sqlite"
INTEL = "/app/db/intel.sqlite"
LIENS = "/app/db/liens.sqlite"
SOCIAL = "/app/db/papier_social.sqlite"
STOCK = "/app/db/papier_stock.sqlite"
IMAGES = os.path.join(DOSSIER, "images.sqlite")
ENTREE = 47
HORIZONS = (60, 90, 120, 180, 240, 287)
AGE_V1 = 45                       # les variables de transaction s arretent a l instant de decision
RECURRENT = 5
FENETRE_REGIME = 20

CIBLES = ["brut_120", "brut_240"] + ["ret_%d" % h for h in HORIZONS]


def ro(path: str) -> sqlite3.Connection:
    return sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=60)


# ----------------------------------------------------------------------------- A. le socle
def socle() -> pd.DataFrame:
    c = ro(COMBO)
    rows = []
    for pair, mint, naiss, t, elig, q, V, risque, regime, n_reg, p0, cr, cre, var, b120, b240 in c.execute(
            "SELECT d.pair, d.mint, d.naissance, d.t_dec, d.eligible, d.q, d.V, d.risque, d.regime,"
            " d.n_regime, d.p_entree, d.cout_reduit, d.cout_reel, d.variables, i.brut_120, i.brut_240"
            " FROM decision d JOIN issue i ON i.pair = d.pair WHERE i.brut_240 IS NOT NULL"):
        r = {"pair": pair, "mint": mint, "naissance": naiss, "t_dec": t, "eligible": elig,
             "q": q, "V": V, "risque": risque, "regime_modele": regime, "n_regime": n_reg,
             "p_entree": p0, "brut_120": b120, "brut_240": b240}
        try:
            d = json.loads(var or "{}")
        except Exception:  # noqa: BLE001
            d = {}
        for k, v in d.items():
            if k in ("q", "V", "cout"):
                continue
            try:
                r["px_" + k] = float(v) if v is not None else None
            except Exception:  # noqa: BLE001
                r["px_" + k] = None
        rows.append(r)
    df = pd.DataFrame(rows).sort_values("t_dec").reset_index(drop=True)
    print("A  socle : %d tickets" % len(df), flush=True)
    return df


# ----------------------------------------------------------------------------- B. metadonnee
def metadonnee(df: pd.DataFrame) -> pd.DataFrame:
    c = ro(INTEL)
    m = {}
    for mint, nom, sym, tw, tg, site, nd in c.execute(
            "SELECT mint, nom, symbole, twitter, telegram, site, n_descr FROM solana_social"):
        nom, sym = nom or "", sym or ""
        m[mint] = {"meta_twitter": tw, "meta_telegram": tg, "meta_site": site, "meta_n_descr": nd,
                   "nom_len": len(nom), "nom_mots": len(nom.split()),
                   "nom_maj": int(bool(nom) and nom.isupper()),
                   "nom_non_ascii": int(any(ord(ch) > 127 for ch in nom)),
                   "nom_chiffre": int(any(ch.isdigit() for ch in nom)),
                   "nom_ai": int("ai" in nom.lower().split() or nom.lower().endswith("ai")),
                   "sym_len": len(sym), "sym_egal_nom": int(sym.lower() == nom.lower())}
    x = pd.DataFrame.from_dict(m, orient="index")
    out = df.merge(x, left_on="mint", right_index=True, how="left")
    print("B  metadonnee : %d/%d" % (out["meta_site"].notna().sum(), len(out)), flush=True)
    return out


# ----------------------------------------------------------------------------- C. liens relus
def liens(df: pd.DataFrame) -> pd.DataFrame:
    if not os.path.exists(LIENS):
        return df
    c = ro(LIENS)
    x = pd.read_sql("SELECT mint, a_site AS lien_site, a_twitter AS lien_twitter,"
                    " a_telegram AS lien_telegram, n_description AS lien_n_descr,"
                    " n_champs AS lien_n_champs, domaine AS lien_domaine FROM lien"
                    " WHERE erreur IS NULL", c)
    x["lien_dom_fun"] = x["lien_domaine"].fillna("").str.endswith(".fun").astype(int)
    x["lien_dom_len"] = x["lien_domaine"].fillna("").str.len()
    x = x.drop(columns=["lien_domaine"])
    out = df.merge(x, on="mint", how="left")
    print("C  liens relus : %d/%d" % (out["lien_site"].notna().sum(), len(out)), flush=True)
    return out


# ----------------------------------------------------------------------------- D. image
def image(df: pd.DataFrame) -> pd.DataFrame:
    if not os.path.exists(IMAGES):
        return df
    c = ro(IMAGES)
    x = pd.read_sql("SELECT mint, luminance AS img_luminance, part_sombre AS img_sombre,"
                    " part_claire AS img_claire, n_couleurs AS img_couleurs, bimodalite AS img_bimod,"
                    " centre_moins_bord AS img_centre, largeur AS img_l, hauteur AS img_h,"
                    " domaine AS img_dom, empreinte AS img_emp FROM image WHERE erreur IS NULL", c)
    x["img_ipfs"] = x["img_dom"].fillna("").str.contains("ipfs|pinata|nftstorage", regex=True).astype(int)
    x["img_carre"] = (x["img_l"] == x["img_h"]).astype(int)
    out = df.merge(x.drop(columns=["img_dom"]), on="mint", how="left")
    # « gabarit deja vu » : combien de jetons NES AVANT ont la meme empreinte (Hamming <= 10)
    vus: list[tuple[int, int]] = []          # (naissance, empreinte en entier)
    deja = []
    for _, r in out.iterrows():
        e = r.get("img_emp")
        if isinstance(e, str) and e:
            try:
                ei = int(e, 16)
            except ValueError:
                ei = None
        else:
            ei = None
        n = 0
        if ei is not None:
            for nb, ej in vus:
                if nb < r["naissance"] and bin(ei ^ ej).count("1") <= 10:
                    n += 1
            vus.append((r["naissance"], ei))
        deja.append(n if ei is not None else None)
    out["img_gabarit_deja_vu"] = deja
    out = out.drop(columns=["img_emp"])
    print("D  image : %d/%d" % (out["img_luminance"].notna().sum(), len(out)), flush=True)
    return out


# ----------------------------------------------------------------------------- E. detenteurs 45 s
def detenteurs(df: pd.DataFrame) -> pd.DataFrame:
    if not os.path.exists(SOCIAL):
        return df
    c = ro(SOCIAL)
    x = pd.read_sql("SELECT pair, sac1 AS det_sac1, n_sacs5 AS det_n_sacs5 FROM jeton"
                    " WHERE erreur IS NULL", c)
    out = df.merge(x, on="pair", how="left")
    print("E  detenteurs : %d/%d" % (out["det_sac1"].notna().sum(), len(out)), flush=True)
    return out


# ----------------------------------------------------------------------------- F. stock 15..45 s
def stock(df: pd.DataFrame) -> pd.DataFrame:
    if not os.path.exists(STOCK):
        return df
    c = ro(STOCK)
    x = pd.read_sql("SELECT pair, age, s1_hp, s5_hp, hors_pool, w1_est_coffre, n_comptes, coffre_vu"
                    " FROM photo WHERE erreur IS NULL", c)
    if x.empty:
        return df
    w = x.pivot_table(index="pair", columns="age",
                      values=["s1_hp", "s5_hp", "hors_pool", "w1_est_coffre", "n_comptes"])
    w.columns = ["stk_%s_%d" % (a, b) for a, b in w.columns]
    for k in ("s1_hp", "s5_hp", "hors_pool"):
        a, b = "stk_%s_15" % k, "stk_%s_45" % k
        if a in w and b in w:
            w["stk_d_%s" % k] = w[b] - w[a]
    out = df.merge(w, left_on="pair", right_index=True, how="left")
    print("F  stock : %d/%d" % (out.filter(like="stk_s1_hp_45").notna().any(axis=1).sum(), len(out)),
          flush=True)
    return out


# ----------------------------------------------------------------------------- G. createur en serie
def createur(df: pd.DataFrame) -> pd.DataFrame:
    c = ro(INTEL)
    par_createur: defaultdict[str, list] = defaultdict(list)
    de = {}
    for mint, cr, ts in c.execute("SELECT mint, createur, ts FROM sol_createur WHERE createur IS NOT NULL"):
        par_createur[cr].append(ts or 0)
        de[mint] = (cr, ts or 0)
    for cr in par_createur:
        par_createur[cr].sort()
    import bisect
    vals = []
    for m in df["mint"]:
        if m in de:
            cr, ts = de[m]
            vals.append(bisect.bisect_left(par_createur[cr], ts))    # lancements ANTERIEURS
        else:
            vals.append(None)
    df["cre_lancements_avant"] = vals
    df["cre_connu"] = df["cre_lancements_avant"].notna().astype(int)
    print("G  createur : %d/%d" % (df["cre_lancements_avant"].notna().sum(), len(df)), flush=True)
    return df


# ----------------------------------------------------------------------------- H. canal Telegram
def telegram_canal(df: pd.DataFrame) -> pd.DataFrame:
    c = ro(INTEL)
    x = {m: a for m, a in c.execute("SELECT mint, age_entree FROM tg_lignes")}
    df["tg_poste"] = df["mint"].map(lambda m: int(m in x))
    # connu AVANT la decision seulement : le canal a poste avant que l ancien carnet n entre a T+60
    df["tg_poste_avant_45"] = df["mint"].map(lambda m: int(m in x and (x[m] or 999) <= 45))
    print("H  telegram canal : %d postes, %d avant 45 s" % (df["tg_poste"].sum(), df["tg_poste_avant_45"].sum()),
          flush=True)
    return df


# ----------------------------------------------------------------------------- I. source + M. offre
def source_offre(df: pd.DataFrame) -> pd.DataFrame:
    c = ro(INTEL)
    src = {m: (s or "", i or "") for m, s, i in c.execute("SELECT mint, source, instruction FROM solana_stream_launches")}
    df["src_stream"] = df["mint"].map(lambda m: int(src.get(m, ("", ""))[0] == "stream"))
    off = {m: (o, d) for m, o, d in c.execute("SELECT mint, offre, decimales FROM mint_offre")}
    df["offre"] = df["mint"].map(lambda m: off.get(m, (None, None))[0])
    df["decimales"] = df["mint"].map(lambda m: off.get(m, (None, None))[1])
    df["mint_pump"] = df["mint"].str.endswith("pump").astype(int)
    print("I/M source + offre : %d/%d" % (df["offre"].notna().sum(), len(df)), flush=True)
    return df


# ----------------------------------------------------------------------------- J. temps
def temps(df: pd.DataFrame) -> pd.DataFrame:
    t = pd.to_datetime(df["t_dec"], unit="s", utc=True).dt.tz_convert("Europe/Paris")
    df["tps_heure"] = t.dt.hour + t.dt.minute / 60.0
    df["tps_jour_sem"] = t.dt.dayofweek
    df["tps_age_dec"] = df["t_dec"] - df["naissance"]
    # debit : lancements dans les 10 et 60 minutes AVANT la decision (le futur exclu)
    n = df["naissance"].values
    import numpy as np
    for fen, nom in ((600, "tps_lanc_10m"), (3600, "tps_lanc_60m")):
        df[nom] = [int(((n < x) & (n >= x - fen)).sum()) for x in df["t_dec"].values]
    print("J  temps : ok", flush=True)
    return df


# ----------------------------------------------------------------------------- K. regime causal
def regime(df: pd.DataFrame) -> pd.DataFrame:
    """Les 20 derniers tickets CLOTURES (t_dec + 242 s <= maintenant) avant chaque decision."""
    t = df["t_dec"].values
    fin = t + 242
    r = df["brut_240"].values
    import numpy as np
    ordre = np.argsort(fin)
    fin_s, r_s = fin[ordre], r[ordre]
    taux, moy = [], []
    for x in t:
        k = np.searchsorted(fin_s, x, side="right")
        w = r_s[max(0, k - FENETRE_REGIME):k]
        w = w[~np.isnan(w)]
        if len(w) >= 5:
            taux.append(float((w > 0).mean()))
            moy.append(float(w.mean()))
        else:
            taux.append(None)
            moy.append(None)
    df["reg_taux_20"] = taux
    df["reg_moy_20"] = moy
    print("K  regime causal : ok", flush=True)
    return df


# ----------------------------------------------------------------------------- L. transactions <= 45 s
def transactions(df: pd.DataFrame) -> pd.DataFrame:
    if not os.path.isdir(V1):
        return df
    vus: defaultdict[str, set] = defaultdict(set)   # portefeuille -> pools deja vus (NES AVANT)
    feats: dict[str, dict] = {}
    pools = []
    for f in sorted(glob.glob(os.path.join(V1, "*.jsonl"))):
        with open(f, encoding="utf-8") as fh:
            for ligne in fh:
                try:
                    d = json.loads(ligne)
                except Exception:  # noqa: BLE001
                    continue
                pools.append((float(d.get("naissance") or 0), d))
    pools.sort(key=lambda x: x[0])
    for naiss, d in pools:
        pair = d.get("pair")
        achats, ventes = [], []
        acheteurs, vendeurs = set(), set()
        premier = None
        robots, sol_robots = 0, 0.0
        sol_par_wallet: defaultdict[str, float] = defaultdict(float)
        jet_par_wallet: defaultdict[str, float] = defaultdict(float)
        for tx in d.get("tx") or []:
            try:
                age, parts = int(tx[0]), tx[2]
            except Exception:  # noqa: BLE001
                continue
            if age > AGE_V1:
                continue
            for p in parts or []:
                try:
                    q, dj, ds = str(p[0]), float(p[1]), float(p[2])
                except Exception:  # noqa: BLE001
                    continue
                sol_par_wallet[q] += ds
                jet_par_wallet[q] += dj
                if dj > 0 and ds < 0:
                    achats.append(-ds)
                    acheteurs.add(q)
                    if premier is None:
                        premier = age
                    if len(vus[q]) >= RECURRENT:          # recurrent AVANT ce jeton
                        robots += 1
                        sol_robots += -ds
                elif dj < 0 and ds > 0:
                    ventes.append(ds)
                    vendeurs.add(q)
        sans_achat = [v for q, v in sol_par_wallet.items() if v > 0 and q not in acheteurs]
        sa, sv = sum(achats), sum(ventes)
        gini = None
        if len(achats) >= 2:
            a = sorted(achats)
            n = len(a)
            gini = (2 * sum((i + 1) * x for i, x in enumerate(a)) / (n * sum(a)) - (n + 1) / n) if sum(a) > 0 else None
        feats[pair] = {
            "v1_n_achats": len(achats), "v1_n_ventes": len(ventes),
            "v1_acheteurs": len(acheteurs), "v1_vendeurs": len(vendeurs),
            "v1_sol_achats": sa, "v1_sol_ventes": sv,
            "v1_ratio_ventes": (sv / sa) if sa > 0 else None,
            "v1_premier_achat": premier,
            "v1_achat_median": st.median(achats) if achats else None,
            "v1_achat_max": max(achats) if achats else None,
            "v1_gini_achats": gini,
            "v1_robots": robots,
            "v1_part_robots": (sol_robots / sa) if sa > 0 else None,
            "v1_vendeurs_sans_achat": len(sans_achat),
            "v1_sol_sans_achat": sum(sans_achat),
            "v1_part_sans_achat": (sum(sans_achat) / sv) if sv > 0 else None,
        }
        for q in acheteurs:
            vus[q].add(pair)
    x = pd.DataFrame.from_dict(feats, orient="index")
    out = df.merge(x, left_on="pair", right_index=True, how="left")
    print("L  transactions <= %d s : %d/%d" % (AGE_V1, out["v1_n_achats"].notna().sum(), len(out)), flush=True)
    return out


# ----------------------------------------------------------------------------- N. cibles multi-H
def cibles(df: pd.DataFrame) -> pd.DataFrame:
    c = ro(INTEL)
    cols = {h: [] for h in HORIZONS}
    for _, r in df.iterrows():
        pts = c.execute("SELECT age_s, prix_sol FROM solana_prix_chaine WHERE pair_id = ? AND prix_sol > 0"
                        " ORDER BY age_s", (r["pair"],)).fetchall()
        avant = [p for a, p in pts if a is not None and a <= ENTREE]
        p0 = avant[-1] if avant else None
        for h in HORIZONS:
            apres = [p for a, p in pts if a is not None and a >= h]
            cols[h].append((apres[0] / p0 - 1.0) if (p0 and apres) else None)
    for h in HORIZONS:
        df["ret_%d" % h] = cols[h]
    print("N  cibles : ret_240 sur %d/%d" % (df["ret_240"].notna().sum(), len(df)), flush=True)
    return df


VARIABLES_EXCLUES = {"pair", "mint", "naissance", "t_dec", "eligible", "p_entree"}


def main() -> None:
    os.makedirs(DOSSIER, exist_ok=True)
    df = socle()
    for etape in (metadonnee, liens, image, detenteurs, stock, createur, telegram_canal,
                  source_offre, temps, regime, transactions, cibles):
        try:
            df = etape(df)
        except Exception as exc:  # noqa: BLE001
            print("   %s RATE : %s" % (etape.__name__, str(exc)[:160]), flush=True)
    variables = [c for c in df.columns if c not in CIBLES and c not in VARIABLES_EXCLUES]
    # la separation variables / cibles est ECRITE dans le fichier, pas deduite a l analyse
    df.attrs["VARIABLES"] = variables
    df.attrs["CIBLES"] = CIBLES
    df.to_pickle(os.path.join(DOSSIER, "table.pkl"))
    print()
    print("TABLE : %d lignes · %d variables · %d cibles" % (len(df), len(variables), len(CIBLES)))
    fam = defaultdict(int)
    for v in variables:
        fam[v.split("_")[0]] += 1
    print("familles :", dict(sorted(fam.items())))


if __name__ == "__main__":
    main()
