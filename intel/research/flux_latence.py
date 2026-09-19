"""PEUT-ON aller chercher le flux d ordres A 45 s ? Deux questions, pas une.

CE QUI AMENE ICI (§3.155 et la suite du 19/09) :
  - la foret nourrie au flux d ordres bat le temoin de +0,430 EUR/ticket, 1 tirage sur 100 fait
    aussi bien ;
  - le collecteur de prix lit le pool toutes les **10 s** (mediane sur 763 intervalles, 5 lectures
    avant 60 s), donc on ne peut PAS compter les ventes depuis la suite des soldes du coffre ;
  - en argent, la moitie PAR TRANSACTION vaut a elle seule le jeu complet (+0,438 contre +0,430)
    tandis que la moitie coffre tombe a un niveau de +0,034, c est-a-dire rien.
Le signal exige donc l appel par transaction au moment de decider. Deux choses peuvent le tuer, et
elles sont independantes :

  LATENCE    l appel prend du temps, et la decision est prise a 45 s. Le moteur entre deja a ~54 s
             (§3.152) ; tout retard deplace l entree, donc le prix paye, donc le cout qu on a mis
             150 EUR a mesurer.
  FRAICHEUR  meme instantane, l appel peut ne pas TOUT voir : rien ne garantit que l index des
             transactions soit a jour a la seconde. Si interroger a 50 s rend moins d echanges que
             la meme fenetre relue a 140 s, alors les variables calculees en direct ne sont pas
             celles sur lesquelles la foret a ete entrainee -- un decalage entrainement/service
             invisible a toute mesure de modele (regle 10).

PROTOCOLE. On prend des pools VIVANTS ages de 40 a 70 s. Pour chacun : on lit la fenetre
[naissance - 5 s, naissance + 45 s] tout de suite (c est ce que ferait le moteur), on chronometre,
puis on relit EXACTEMENT la meme fenetre une fois le pool a plus de 140 s, et on compare. La fenetre
est identique, donc toute difference est de la fraicheur d index, pas du trafic en plus.
Lecture seule, aucune signature, aucune cle touchee.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import time

import numpy as np

sys.path.insert(0, "/app/intel/research")
import copie_collecte as cc  # noqa: E402

cc.VERSION_MAX = 1        # les transactions « version 1 » existent depuis le 15/09 (§3.90)
BASE = os.environ.get("INTEL_DB", "/app/db/intel.sqlite")
FENETRE = 45
RELECTURE_AGE = 140
N_POOLS = int(os.environ.get("N_POOLS", "10"))
ATTENTE_MAX = int(os.environ.get("ATTENTE_MAX", "900"))


def jeunes(age_min=40, age_max=70):
    """Pools vivants dont la naissance est connue et qui ont l age voulu MAINTENANT."""
    c = sqlite3.connect("file:%s?mode=ro" % BASE, uri=True, timeout=60)
    try:
        rows = c.execute(
            "SELECT pair_id, MAX(mint), MIN(ts - age_s), MAX(reserve_virtuelle)"
            " FROM solana_prix_chaine WHERE ts >= ? GROUP BY pair_id HAVING MIN(age_s) <= 20",
            (time.time() - 3600,)).fetchall()
    finally:
        c.close()
    out, now = [], time.time()
    for p, m, t0, v in rows:
        age = now - float(t0)
        if age_min <= age <= age_max:
            out.append({"pair": p, "mint": m, "naissance": float(t0), "V": float(v or 17.5845)})
    return out


def lire(p):
    t = time.time()
    r = cc.lire_pool(p)
    return time.time() - t, r


def main() -> None:
    cc.FENETRE_S = FENETRE
    print("LATENCE ET FRAICHEUR DE L APPEL PAR TRANSACTION")
    print("fenetre [naissance-5 s, naissance+%d s] · relue a %d s · lecture seule" % (FENETRE, RELECTURE_AGE))
    print()
    vus, debut = {}, time.time()
    while len(vus) < N_POOLS and time.time() - debut < ATTENTE_MAX:
        for p in jeunes():
            if p["pair"] in vus or len(vus) >= N_POOLS:
                continue
            age = time.time() - p["naissance"]
            try:
                d, r = lire(p)
            except Exception as e:
                print("   %s... ECHEC %s" % (p["pair"][:8], str(e)[:80]), flush=True)
                vus[p["pair"]] = None
                continue
            vus[p["pair"]] = {"p": p, "age": age, "duree": d, "tot": r["n_tx"],
                              "ech": len(r["echanges"]), "pages": r["pages"]}
            print("   %s... age %3.0f s · lu en %.2f s · %d tx · %d echanges"
                  % (p["pair"][:8], age, d, r["n_tx"], len(r["echanges"])), flush=True)
        time.sleep(5)

    faits = {k: v for k, v in vus.items() if v}
    if not faits:
        print("\n   aucun pool lu -- rien a conclure")
        return
    print()
    print("   on attend que chacun ait %d s pour relire LA MEME fenetre..." % RELECTURE_AGE, flush=True)
    for v in faits.values():
        reste = RELECTURE_AGE - (time.time() - v["p"]["naissance"])
        if reste > 0:
            time.sleep(min(reste, 300))
        try:
            d2, r2 = lire(v["p"])
            v["tot2"], v["ech2"], v["duree2"] = r2["n_tx"], len(r2["echanges"]), d2
        except Exception as e:
            print("   relecture %s... ECHEC %s" % (v["p"]["pair"][:8], str(e)[:60]), flush=True)

    print()
    print("   %-10s %6s %8s %9s %9s %9s" % ("pool", "age", "duree", "tx a 45s", "tx relu", "manquant"))
    durees, manques = [], []
    for v in faits.values():
        if "tot2" not in v:
            continue
        m = v["tot2"] - v["tot"]
        durees.append(v["duree"])
        manques.append(m)
        print("   %-10s %5.0fs %7.2fs %9d %9d %9d%s"
              % (v["p"]["pair"][:8] + "..", v["age"], v["duree"], v["tot"], v["tot2"], m,
                 "   <- INCOMPLET" if m > 0 else ""))
    if not durees:
        print("   aucune relecture aboutie")
        return
    a, mq = np.array(durees), np.array(manques)
    print()
    print("LATENCE   mediane %.2f s · p90 %.2f s · pire %.2f s"
          % (np.median(a), np.percentile(a, 90), a.max()))
    print("          -> entree deplacee de ~54 s a ~%.0f s en median" % (54 + np.median(a)))
    print()
    print("FRAICHEUR %d pools sur %d incomplets a 45 s · transactions manquantes : median %.0f, pire %d"
          % (int((mq > 0).sum()), len(mq), np.median(mq), mq.max()))
    if (mq > 0).sum() == 0:
        print("          -> l index est a jour : ce qu on lit a 45 s est ce que la foret a appris")
    else:
        print("          -> ATTENTION : les variables en direct ne seront pas celles de l entrainement.")
        print("             Il faudrait reentrainer sur ce que l appel rend VRAIMENT a 45 s, pas sur")
        print("             la relecture a 70 s de v1_enregistreur (regle 10 : decalage entrainement/service).")


if __name__ == "__main__":
    main()
