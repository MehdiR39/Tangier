"""« Acheter la hausse confirmee » -- test fige le 15/09 avant calcul.

ORIGINE. Sur notre argent reel, les 15 tickets propres achetes plus de 10 % au-dessus de la lecture a
60 s ont gagne +26,3 % par euro (+19 % puis +40 % sur les deux moitiees) quand les 108 achetes au prix
de cette lecture perdaient -11,5 %. 15 tickets ne font pas une regle : on la teste sur tout le coffre.

REGLE. Le jeton passe le filtre propre (3 signes) a la lecture la plus proche de T+60 s (45-90 s).
Si, entre cette lecture et T+180 s, une lecture atteint +SEUIL au-dessus d elle, on achete a la
lecture SUIVANTE, et on vend a +240 s de cet achat (+/- 45 s).
COUTS. 1,0 point (execution mesuree en chaine) et 4,7 points (execution + optimisme de la simulation
mesure sur les memes jetons le 15/09). DECISION sur 4,7 points.
DECISION. SEUIL = 10 % seulement. GO si sur la moitie de JUGEMENT (par date de naissance) : niveau
>= +0,011, sans son meilleur ticket > 0, vidages < 11,9 %, ET niveau > 0 sur la RECHERCHE.
5 % et 20 % sont affiches pour information et ne decident rien.
"""
import statistics as st
import intel.research.combinaison_verdict as cv

COUTS = (0.010, 0.047)


def tickets(courbes, marque, seuil, groupe):
    out = []
    for pair, pts in courbes.items():
        mint = pts[0]["mint"]
        if mint not in marque or not pts or pts[0]["age"] > 20:
            continue
        av = [x for x in pts if x["age"] <= 90]
        e = min((x for x in pts if 45 <= x["age"] <= 90), key=lambda x: abs(x["age"] - 60), default=None)
        if len(av) < 3 or not e or not e["x"] or 0.31 / e["x"] > 0.15:
            continue
        p0, l0 = av[0]["p"], av[0]["x"] or 0
        signes = (int(e["p"] / p0 - 1 >= 0.007) + int(min(x["p"] for x in av) / p0 - 1 >= 0)
                  + int(((e["x"] / l0 - 1) if l0 > 0 else 0) >= 0.0035))
        g = "telegram" if marque[mint] else ("propre" if signes == 3 else "autre")
        if groupe != "tous" and g != groupe:
            continue
        suite = [x for x in pts if e["age"] < x["age"] <= 180]
        i = next((k for k, x in enumerate(suite) if x["p"] >= e["p"] * (1 + seuil)), None)
        if i is None or i + 1 >= len(suite) + 0:
            if i is None:
                continue
        apres = [x for x in pts if x["age"] > suite[i]["age"]]
        if not apres:
            continue
        a = apres[0]                                   # achat a la lecture suivant le signal
        s = min((x for x in pts if x["age"] > a["age"]), key=lambda x: abs(x["age"] - (a["age"] + 240)), default=None)
        if not s or abs(s["age"] - (a["age"] + 240)) > 45:
            continue
        out.append({"nais": pts[0]["ts"] - pts[0]["age"], "r": s["p"] / a["p"] - 1, "attente": a["age"] - e["age"]})
    return sorted(out, key=lambda t: t["nais"])


def stats(v):
    s = sorted(v, reverse=True)
    return st.mean(s), (st.mean(s[1:]) if len(s) > 1 else float("nan")), sum(1 for x in s if x <= -0.5) / len(s)


def main():
    c, marque, sac, fin, courbes = cv.charger()
    for groupe in ("propre", "tous"):
        for seuil in (0.10, 0.05, 0.20):
            T = tickets(courbes, marque, seuil, groupe)
            if len(T) < 40:
                print("%-6s seuil %2d %% : %d tickets, trop peu" % (groupe, 100 * seuil, len(T)))
                continue
            h = len(T) // 2
            jours = max((T[-1]["nais"] - T[0]["nais"]) / 86400, 1e-9)
            print("\n%s · seuil +%d %% · %d tickets (%.0f par jour) · attente mediane %.0f s%s"
                  % (groupe.upper(), 100 * seuil, len(T), len(T) / jours, st.median(t["attente"] for t in T),
                     "   <- LA SEULE QUI DECIDE" if (seuil == 0.10 and groupe == "propre") else ""))
            res = {}
            for cout in COUTS:
                for nom, part in (("recherche", T[:h]), ("JUGEMENT", T[h:])):
                    m, sb, vid = stats([t["r"] - cout for t in part])
                    res[(cout, nom)] = (m, sb, vid)
                    print("   cout %.1f pt  %-9s n=%4d  niveau %+.4f  sans best %+.4f  vides %4.1f %%  -> %+5.0f EUR/jour"
                          % (100 * cout, nom, len(part), m, sb, 100 * vid, (len(T) / jours) * m * 30))
            if seuil == 0.10 and groupe == "propre":
                mj, sbj, vj = res[(0.047, "JUGEMENT")]
                mr = res[(0.047, "recherche")][0]
                go = mj >= 0.011 and sbj > 0 and vj < 0.119 and mr > 0
                print("   VERDICT : %s" % ("GO -> test EN PAPIER" if go else "NON"))


if __name__ == "__main__":
    main()
