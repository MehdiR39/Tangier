"""ECARTER LES JETONS FABRIQUES PAR UNE USINE, PRE-ENREGISTRE le 18/09/2026 a 16h00 UTC (18h00 Paris).

D OU ÇA VIENT. Mido, capture d ecran a l appui : « j ai constate que la majorite des crashs vient
des memes avec comme photo un fond noir et l ecriture au milieu ». En allant chercher les images, je
suis tombe sur autre chose : **un quart des jetons ne servent pas leurs metadonnees depuis IPFS mais
depuis une API de plateforme** -- `metadata.j7tracker.io`, `meta.uxento.io`, `usepaid.app`,
`api.vortexdeployer.com`. Ce sont des USINES A JETONS. Le domaine de l URI les trahit gratuitement,
sans telecharger une seule image.

Et Mido a precise son idee, qui est plus profonde que le critere visuel : « c est pas un critere fixe
fond noir ecriture milieu, l idee c est que des cons arnaqueurs s inspirent et les memes cons
refont la meme sorte de crypto ; le marche contient beaucoup d escrocs et on peut gagner si on evite
ces escrocs ». L usine est le cas le plus grossier d acteur recurrent -- le detecter est le premier
pas, pas le dernier.

LA MESURE, sur 1 382 tickets `RISQUE seul` :

| | n | net | deux moities | sans ses 3 meilleurs |
|---|---|---|---|---|
| tout prendre | 1 382 | -0,36 % | -1,41 / +0,70 | -1,01 % |
| **IPFS brut (fait main)** | 1 041 | **+1,06 %** | -0,26 / +2,39 | **+0,20 %** |
| **les USINES seules** | 341 | **-4,70 %** | **-5,73 / -3,67** | **-7,39 %** |

**Ecart de 5,76 points par ticket**, negatif sur les deux moities et pire encore sans ses meilleurs.

CE QUE L USINE N EST PAS : un simple proxy du modele. A `risque` constant, l ecart tient sur trois
quintiles sur quatre -- -5,35, -6,46, -17,74 -- mais **PAS sur le cinquieme (+0,83)**. L information
n est donc pas entierement nouvelle : les jetons d usine ont un `risque` median de 0,205 contre
0,106, un coffre de 76 SOL contre 266, une volatilite de 0,026 contre 0,003. Le modele en voit une
partie. C est la reserve principale de cette piste, et elle est ecrite avant de voir la suite.

CE QUI N EST PAS DEMONTRE NON PLUS : p = 0,167 pour « IPFS seul » contre un tirage au hasard de meme
taille. Quatre categories ont ete regardees et la structure retenue apres coup. Le filtre n ecarte
que 14 % des tickets (25 % si l on retire toutes les usines), donc son effet sur le total reste
modeste meme s il est reel.

LA REGLE FIGEE : n acheter que si l URI des metadonnees est de l IPFS -- c est-a-dire pas servie par
une plateforme. Aucune liste d usines a maintenir : on ne nomme pas les mauvaises, on exige la
bonne. Une usine nouvelle est donc ecartee d office, ce qu une liste noire n aurait pas fait.

CRITERE, FIGE, au premier atteint de 1 200 tickets posterieurs au gel ou de 21 jours :
  (a) les jetons d USINE doivent faire MOINS BIEN que les autres, sur exactement les memes tickets ;
  (b) l ecart doit tenir sur les DEUX moities chronologiques ;
  (c) « IPFS seul » doit etre positif APRES les 2,62 pts de cout.
Les trois, sinon la piste est abandonnee et ecrite comme telle.

Lecture seule. La production ne lit pas ce fichier.
"""
from __future__ import annotations

import os
import sqlite3
import statistics as st
from urllib.parse import urlparse

GEL_USINE = 1789740000.0          # 18/09/2026 16h00 UTC = 18h00 Paris
SEUIL_RISQUE = 0.2694
COUT, PLAFOND = 0.0262, 3.0
N_CRITERE, JOURS_CRITERE = 1200, 21
BASE = os.environ.get("COMBO_DB", "/app/db/papier_combo.sqlite")
BASE_MOTEUR = os.environ.get("INTEL_DB", "/app/db/intel.sqlite")


def est_usine(uri: str | None) -> bool | None:
    """L URI est-elle servie par une plateforme plutot que par IPFS ? None si illisible.

    On ne nomme PAS les usines connues : on exige la bonne reponse (IPFS) et tout le reste est
    ecarte. Une liste noire laisserait passer chaque nouvelle plateforme le jour de son ouverture,
    ce qui est precisement le moment ou elle produit le plus de jetons.
    """
    if not uri:
        return None
    h = (urlparse(uri).netloc or "").lower()
    if not h:
        return None
    return "ipfs" not in h


def tickets(ici: sqlite3.Connection, depuis: float = GEL_USINE):
    ici.execute("ATTACH DATABASE 'file:%s?mode=ro' AS M" % BASE_MOTEUR)
    out = []
    for t, uri, b in ici.execute(
            "SELECT d.t_dec, o.uri, i.brut_240 FROM decision d JOIN issue i ON i.pair = d.pair"
            " JOIN M.solana_social o ON o.mint = d.mint"
            " WHERE d.eligible = 1 AND i.brut_240 IS NOT NULL AND d.risque IS NOT NULL"
            " AND d.risque <= ? AND d.t_dec >= ? ORDER BY d.t_dec", (SEUIL_RISQUE, depuis)):
        u = est_usine(uri)
        if u is None:
            continue
        out.append((t, u, min(b - COUT, PLAFOND)))
    return out


def rapport(ici: sqlite3.Connection, mise: float = 25.0) -> None:
    D = tickets(ici)
    print("\nECARTER LES USINES · PRE-ENREGISTRE le 18/09 a 18h00 Paris")
    print("   %d ticket(s) depuis le gel, sur les %d du critere" % (len(D), N_CRITERE))
    if len(D) < 40:
        print("   CRITERE : les usines doivent faire moins bien, sur les deux moities,")
        print("             et « IPFS seul » doit etre positif apres les 2,62 pts.")
        return
    U = [r for _, u, r in D if u]
    I = [r for _, u, r in D if not u]
    if not U or not I:
        print("   une seule categorie presente pour l instant")
        return
    m = len(D) // 2
    ua = [r for _, u, r in D[:m] if u]
    ub = [r for _, u, r in D[m:] if u]
    ia = [r for _, u, r in D[:m] if not u]
    ib = [r for _, u, r in D[m:] if not u]
    print("   %-16s %6s %12s %14s" % ("", "n", "net", "1re / 2e moitie"))
    print("   %-16s %6d %+11.2f %% %+6.2f / %+6.2f"
          % ("USINE", len(U), 100 * st.mean(U),
             100 * st.mean(ua) if ua else 0, 100 * st.mean(ub) if ub else 0))
    print("   %-16s %6d %+11.2f %% %+6.2f / %+6.2f"
          % ("IPFS brut", len(I), 100 * st.mean(I),
             100 * st.mean(ia) if ia else 0, 100 * st.mean(ib) if ib else 0))
    print("   ecart : %+.2f pt · l IPFS seul rapporterait %+.0f EUR"
          % (100 * (st.mean(U) - st.mean(I)), mise * sum(I)))
    a = st.mean(U) < st.mean(I)
    b = bool(ua and ub and ia and ib) and st.mean(ua) < st.mean(ia) and st.mean(ub) < st.mean(ib)
    d = st.mean(I) > 0
    print("   (a) usines moins bonnes : %s · (b) sur les deux moities : %s · (c) IPFS positif : %s"
          % ("oui" if a else "NON", "oui" if b else "NON", "oui" if d else "NON"))
    print("   -> %s" % ("CRITERE TENU" if (a and b and d) else "critere non atteint a ce stade"))
    print("   CRITERE, a %d tickets ou %d jours : les trois, sinon abandon." % (N_CRITERE, JOURS_CRITERE))


if __name__ == "__main__":
    rapport(sqlite3.connect("file:%s?mode=ro" % BASE, uri=True, timeout=60))
