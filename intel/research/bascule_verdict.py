"""A-T-ON BIEN FAIT DE BASCULER ? L ancien modele contre le nouveau, depuis la bascule.

Mido, 26/09 : « il faut continuer a suivre l ancien modele pour savoir si on a bien fait de changer,
tu vois ? ». Oui, et sans bras temoin la question serait indecidable pour toujours.

LE BRAS TEMOIN EXISTE DEJA ET N A RIEN COUTE : `papier_combo` continue de scorer l ANCIEN modele en
continu, comme il le fait depuis le 15/09. On rejoue donc simplement sa regle -- bande [0,20 ; 0,35]
plus la pause, lue sur SON flux -- sur les tickets POSTERIEURS A LA BASCULE, et on la compare au
nouveau bras, `papier_challenger` avec la bande [0,1776 ; 0,3920] et la pause lue sur SON flux.

CHAQUE BRAS LIT SA PROPRE PAUSE, et c est le point delicat. La pause doit voir le flux entier de SA
bande : croiser les deux (la bande de l un, le flux de l autre) donnerait un troisieme objet qui n a
jamais tourne nulle part. C est la meme raison qui a impose `papier_challenger` avant de basculer.

CE QUI EST AUSSI AFFICHE : le carnet REEL depuis la bascule. Le papier dit ce que les deux regles
auraient fait ; seul le reel porte les couts d execution. Les deux ne se confondent pas.

ON NE CONCLUT PAS AVANT D EN AVOIR LES MOYENS. La mesure du 26/09 est nette : distinguer un ecart
de +2,1 EUR/ticket demande **411 tickets par bras** a 50 % de puissance, **838** a 80 %. A ~22
tickets/jour, c est 19 jours pour une chance sur deux. Ce script affiche donc toujours ou l on en
est sur ce chemin, et refuse de trancher avant.

Lecture seule. Usage : python -m intel.research.bascule_verdict
"""
from __future__ import annotations

import datetime as dt
import sqlite3
import statistics as st

TZ = dt.timezone(dt.timedelta(hours=2))

# L INSTANT DE LA BASCULE, en epoch : 26/09/2026 12h38'30 Paris, l instant du redemarrage qui a mis
# le modele frais en service. Ecrit ici une fois pour toutes -- une date approximative ferait entrer
# dans un bras des tickets decides par l autre.
BASCULE = 1790419110.0

ANCIEN = ("ANCIEN modele (temoin)", "/app/db/papier_combo.sqlite", (0.20, 0.35))
NOUVEAU = ("NOUVEAU modele (en prod)", "/app/db/papier_challenger.sqlite",
           (0.17763490200673798, 0.3920447192432126))

V, MISE, FIXE = 17.5845, 20.0, 0.03524
TENUE, SEUIL, PAUSE_S = 242.0, -0.30, 1800.0
# ce qu il faut pour trancher, mesure le 26/09 (sigma 15,41 par ticket, ecart vise +2,1)
POUR_TRANCHER = 411


def cout(q: float) -> float:
    return FIXE + 2.0 * (MISE * 0.31 / 30.0) / ((q or 0) + V)


def rejoue(tickets):
    pris, att, bl = [], [], 0.0
    for x in sorted(tickets, key=lambda z: z["t"]):
        att.sort(key=lambda z: z["fin"])
        while att and att[0]["fin"] <= x["t"]:
            f = att.pop(0)
            if f["r"] <= SEUIL:
                bl = max(bl, f["fin"] + PAUSE_S)
        if x["t"] >= bl:
            pris.append(x)
        att.append(x)
    return pris


def bras(chemin: str, bande: tuple[float, float]):
    """Les tickets qu une regle aurait pris depuis la bascule, SA pause lue sur SON flux."""
    c = sqlite3.connect("file:%s?mode=ro" % chemin, uri=True, timeout=30)
    tk = []
    for t, r, q, b in c.execute(
            "SELECT d.t_dec, d.risque, d.q, i.brut_240 FROM decision d JOIN issue i"
            " ON i.pair = d.pair WHERE d.eligible = 1 AND i.brut_240 IS NOT NULL"
            " AND d.q IS NOT NULL AND d.risque IS NOT NULL AND d.t_dec >= ? ORDER BY d.t_dec",
            (BASCULE,)):
        if bande[0] <= float(r) < bande[1]:
            tk.append({"t": float(t), "fin": float(t) + TENUE, "r": min(float(b) - cout(q), 3.0)})
    return tk, rejoue(tk)


def criteres(pris):
    v = sorted(pris, key=lambda z: z["t"])
    n = len(v)
    if n < 6:
        return None
    nets = [MISE * x["r"] for x in v]
    tot, jours, mi = sum(nets), max((v[-1]["t"] - v[0]["t"]) / 86400.0, 1e-9), n // 2
    s = sorted(nets)
    sig = st.pstdev(nets) if n > 1 else 0.0
    return {"n": n, "niveau": tot / n, "eur_jour": tot / jours if jours >= 0.5 else float("nan"),
            "moitie_1": sum(nets[:mi]) / mi, "moitie_2": sum(nets[mi:]) / (n - mi),
            "part_top3": 100.0 * sum(s[-3:]) / tot if tot else float("inf"),
            "gagnants": 100.0 * sum(1 for x in nets if x > 0) / n,
            "gros_gains": 100.0 * sum(1 for x in nets if x >= MISE * 0.50) / n,
            "sigma": sig,
            "niveau_sigma": (tot / n) / (sig / n ** 0.5) if sig > 0 else float("nan")}


def main() -> None:
    quand = dt.datetime.fromtimestamp(BASCULE, TZ).strftime("%d/%m/%Y %H:%M")
    ecoule = (dt.datetime.now(TZ).timestamp() - BASCULE) / 86400.0
    print("=" * 88)
    print("A-T-ON BIEN FAIT DE BASCULER ? — bascule le %s · %.2f jour(s) ecoule(s)" % (quand, ecoule))
    print("=" * 88)

    res = []
    for nom, chemin, bande in (ANCIEN, NOUVEAU):
        try:
            offerts, pris = bras(chemin, bande)
        except Exception as exc:  # noqa: BLE001
            print("   %-26s illisible (%s)" % (nom, str(exc)[:50]))
            continue
        res.append((nom, bande, offerts, pris, criteres(pris)))

    if len(res) < 2:
        print("\n   un bras manque — rien a comparer.")
        return

    print("\n   %-26s %14s %14s" % ("", res[0][0][:14], res[1][0][:14]))
    print("   %-26s %14s %14s"
          % ("bande", "[%.3f;%.3f]" % res[0][1], "[%.3f;%.3f]" % res[1][1]))
    print("   %-26s %14d %14d" % ("candidats offerts", len(res[0][2]), len(res[1][2])))
    print("   %-26s %14d %14d" % ("tickets pris apres pause", len(res[0][3]), len(res[1][3])))

    if any(c is None for _, _, _, _, c in res):
        n = min(len(p) for _, _, _, p, _ in res)
        print("\n   TROP TOT : %d ticket(s) pris du cote le moins fourni, il en faut 6 pour"
              " afficher\n   quoi que ce soit. Revenir plus tard." % n)
        return

    AXES = [("niveau", "EUR/ticket", True), ("eur_jour", "EUR/jour", True),
            ("moitie_1", "1re moitie", True), ("moitie_2", "2e moitie", True),
            ("part_top3", "part portee par le top 3", False),
            ("gros_gains", "% de gros gains (>= +50 %)", True),
            ("gagnants", "% de gagnants", True),
            ("niveau_sigma", "sigma du niveau", True)]
    gagne_nouveau = 0
    for cle, lab, plus_grand in AXES:
        a, b = res[0][4][cle], res[1][4][cle]
        mieux = (b > a) if plus_grand else (b < a)
        gagne_nouveau += 1 if mieux else 0
        print("   %-26s %14.3f %14.3f %s" % (lab, a, b, "<" if mieux else ""))

    print("\n   -> le NOUVEAU modele gagne %d axes sur %d depuis la bascule"
          % (gagne_nouveau, len(AXES)))

    # ---- LE CARNET REEL, qui seul porte les couts d execution ----------------
    try:
        d = sqlite3.connect("file:/app/db/intel.sqlite?mode=ro", uri=True, timeout=20)
        n, g = d.execute(
            "SELECT COUNT(*), COALESCE(SUM(gain_eur), 0) FROM mr_lignes WHERE mode='live'"
            " AND gain_eur IS NOT NULL AND ts_entree >= ?", (BASCULE,)).fetchone()
        print("\n   LE CARNET REEL depuis la bascule : %d ticket(s) comptes, %+.2f EUR" % (n, g))
        print("      (le papier dit ce que les regles auraient fait ; seul le reel porte les couts)")
    except Exception:  # noqa: BLE001
        pass

    # ---- ce qu il faudrait pour trancher -------------------------------------
    n = min(len(res[0][3]), len(res[1][3]))
    print("\n   OU EN EST-ON DU CHEMIN POUR TRANCHER ?")
    print("      %d tickets par bras sur les %d qu il faut pour une chance sur deux" % (n, POUR_TRANCHER))
    if n < POUR_TRANCHER:
        jours = (POUR_TRANCHER - n) / max(len(res[1][3]) / max(ecoule, 1e-9), 1e-9)
        print("      il en manque %d, soit ~%.0f jour(s) au rythme observe." % (POUR_TRANCHER - n, jours))
        print("      **AUCUNE CONCLUSION AVANT.** Ce qui s affiche au-dessus est une observation,")
        print("      pas un verdict : sur peu de tickets, l ecart est domine par quelques tirages.")
    else:
        print("      de quoi trancher : lancer le test apparie complet.")


if __name__ == "__main__":
    main()
