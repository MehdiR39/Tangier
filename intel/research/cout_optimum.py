"""QUELLE MISE, ET QUELLE REGLE, pour rester en prod en perdant le moins possible ?

MIDO, 19/09 : « on a un objectif : continuer a etre en prod pour apprendre, recueillir assez de
donnees, mais sans perdre trop d argent. Donc il faut choisir la strategie adaptee parmi ce qu on a,
et le montant a investir optimal. »

CE N EST PAS « quelle strategie gagne » -- aucune ne gagne au cout actuel. C est : POUR CHAQUE EURO
PERDU, combien de tickets apprend-on ? Le vrai critere devient le prix de l information.

LE COUT N EST PAS PROPORTIONNEL A LA MISE, et c est ce qui cree un optimum. Mesure sur le registre
(`cout_tickets.jsonl`, 107 tickets reels decomposes au centime) :

    FIXE en euros      les frais de reseau : ~0,09 EUR par ticket quelle que soit la mise.
                       Leur POIDS en points s effondre quand la mise monte.
    FIXE en points     la commission du pool (0,25 %/jambe) et l « inexplique ». Indifferents.
    CROISSANT          l impact de notre propre ordre : 2 x mise_SOL / (coffre + V). Il double
                       quand la mise double, donc son poids en POINTS croit lineairement.

    cout(m) = F/m + p + k.m      ->  perte(m) = F + (p - brut).m + k.m²
    minimum en m* = (brut - p) / (2k), quand brut > p.

CE QU ON NE SAIT PAS, et qui est ecrit ici plutot que cache : on ignore comment l « inexplique »
(le premier poste, 1,98 pt sur 4,18) se comporte quand la mise change. On le suppose constant en
POURCENTAGE, l hypothese la plus neutre. S il s agit en fait de glissement, il croit avec la mise et
le vrai optimum est PLUS BAS que celui calcule ici. On ne le saura qu en faisant varier la mise et
en mesurant -- c est justement ce que la prod peut apprendre.

SORTIE : `data/cout_optimum.json`, relu par la page. Rien n est recalcule cote page.
"""
from __future__ import annotations

import datetime as dt
import json
import os

DATA = os.environ.get("CARNET_DIR", "/app/data")
REGISTRE = os.path.join(DATA, "cout_tickets.jsonl")
CARNET = os.path.join(DATA, "carnet.json")
SORTIE = os.path.join(DATA, "cout_optimum.json")
MISES = [5, 10, 15, 20, 25, 30, 40, 50, 75, 100]
TZ = dt.timezone(dt.timedelta(hours=2))


def lignes():
    out = []
    if not os.path.exists(REGISTRE):
        return out
    with open(REGISTRE, encoding="utf-8") as f:
        for l in f:
            try:
                out.append(json.loads(l))
            except Exception:  # noqa: BLE001
                continue
    return out


def main() -> None:
    L = lignes()
    if len(L) < 20:
        print("cout_optimum: %d tickets seulement, on ne calcule rien" % len(L))
        return

    # --- les trois natures de cout, mesurees sur le registre -------------------------------------
    n = len(L)
    dep = sum(x["mise"] for x in L)
    # LE REGIME ACTUEL, pas la moyenne de l histoire. La caution est recuperee depuis le 19/09
    # 10h53 : la compter encore reviendrait a facturer une depense qui n existe plus, et a
    # surestimer la part FIXE -- donc a pousser l optimum vers des mises trop grosses.
    F = sum(x["frais_reseau"] for x in L) / n                 # EUR par ticket, fixe
    caution_auj = 0.0                                          # module `recuperation` actif
    p = (sum(x["pool"] for x in L) + sum(x["inexplique"] for x in L)) / dep   # fraction, constante
    # impact : mesure a la mise pratiquee, ramene a « par euro de mise »
    k = (sum(x["impact"] for x in L) / dep) / (dep / n)       # fraction par EUR de mise
    # DEUX hypotheses de rendement brut, et elles ne disent pas la meme chose :
    #   traded : les tickets REELLEMENT achetes -- petit echantillon, et le budget de perte en a
    #            ecarte les meilleurs, donc il est pessimiste.
    #   voulu  : tous ceux que la regle demandait, bloques compris -- plus nombreux, plus juste
    #            sur ce que la strategie vaut, mais on ne les a pas tous joues.
    brut_traded = sum(x["mise"] * x["brut_pct"] / 100.0 for x in L) / dep
    brut_voulu = float(os.environ.get("BRUT_VOULU", "0.0284"))

    def cout_pct(m):
        return (F + caution_auj) / m + p + k * m

    def perte(m, brut):
        return m * (cout_pct(m) - brut)

    def optimum(brut):
        return (brut - p) / (2 * k) if (brut - p) > 0 and k > 0 else None

    courbe = [{"mise": m, "cout_pt": round(100 * cout_pct(m), 3),
               "perte_traded": round(perte(m, brut_traded), 4),
               "perte_voulu": round(perte(m, brut_voulu), 4)} for m in MISES]
    meilleur = min(courbe, key=lambda c: c["perte_voulu"])
    brut = brut_voulu
    m_etoile = optimum(brut_voulu)
    m_etoile_traded = optimum(brut_traded)

    # --- combien coute un jour de prod, par regle -------------------------------------------------
    regles = []
    C = None
    if os.path.exists(CARNET):
        with open(CARNET, encoding="utf-8") as f:
            C = json.load(f)
    if C:
        fin = dt.datetime.fromisoformat(C["genere"]).timestamp()
        # CHAQUE regle porte SON propre rendement brut, sinon elles coutent toutes pareil et le
        # tableau ne sert a rien. La table donne le net APRES le cout qu elle applique ; on le
        # remet pour retrouver le brut, puis on lui applique le cout de la mise etudiee.
        cout_table = C["cout_pt"] / 100.0
        mise_table = C["mise"]
        for l in C["lignes"]:
            if not l.get("debut") or not l["n"]:
                continue
            h = (fin - l["debut"]) / 3600.0
            if h < 6:
                continue
            tj = l["n"] * 24.0 / h
            brut_regle = l["par_ticket"] / mise_table + cout_table
            for m in (5, 10, 15, 20):
                pt_ = perte(m, brut_regle)
                regles.append({"regle": l["nom"], "mise": m, "tickets_jour": round(tj),
                               "brut_pct": round(100 * brut_regle, 3),
                               "perte_jour": round(tj * pt_, 1),
                               "par_ticket": round(pt_, 4)})

    d = {
        "genere": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "n_tickets": n, "deploye": round(dep, 2),
        "mesure": {
            "fixe_eur_par_ticket": round(F + caution_auj, 4),
            "constant_pct": round(100 * p, 3),
            "impact_pct_par_eur": round(100 * k, 5),
            "brut_traded_pct": round(100 * brut_traded, 3),
            "brut_voulu_pct": round(100 * brut_voulu, 3),
        },
        "courbe": courbe,
        "meilleure_mise": meilleur,
        "optimum_analytique": round(m_etoile, 1) if m_etoile else None,
        "optimum_traded": round(m_etoile_traded, 1) if m_etoile_traded else None,
        "regles": sorted(regles, key=lambda r: (r["mise"], r["perte_jour"]))[:200],
        "reserve": "L « inexplique » (le premier poste) est suppose constant en POURCENTAGE. "
                   "Si c est du glissement, il croit avec la mise et l optimum est PLUS BAS.",
    }
    with open(SORTIE + ".tmp", "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    os.replace(SORTIE + ".tmp", SORTIE)

    print("MESURE sur %d tickets reels (%.0f EUR deployes), REGIME ACTUEL (caution recuperee)" % (n, dep))
    print("   fixe        %.4f EUR par ticket (frais de reseau)" % (F + caution_auj))
    print("   constant    %.3f %% (pool + inexplique)" % (100 * p))
    print("   impact      %.5f %% par EUR de mise" % (100 * k))
    print("   brut : %+.3f %% sur les tickets JOUES · %+.3f %% sur ceux que la regle VOULAIT"
          % (100 * brut_traded, 100 * brut_voulu))
    print()
    print("   %6s %10s %16s %16s" % ("mise", "cout", "perte/ticket", "perte/ticket"))
    print("   %6s %10s %16s %16s" % ("", "", "(brut joue)", "(brut voulu)"))
    for c in courbe:
        etoile = "   <--" if c is meilleur else ""
        print("   %5d E %9.2f pt %+15.4f E %+15.4f E%s"
              % (c["mise"], c["cout_pt"], c["perte_traded"], c["perte_voulu"], etoile))
    print()
    print("   optimum : %s EUR (brut voulu) · %s (brut joue)"
          % (("%.1f" % m_etoile) if m_etoile else "aucun, prendre la plus petite mise",
             ("%.1f" % m_etoile_traded) if m_etoile_traded else "aucun, prendre la plus petite mise"))
    print()
    print("   RESERVE : %s" % d["reserve"])


if __name__ == "__main__":
    main()
