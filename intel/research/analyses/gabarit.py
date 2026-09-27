"""LES MEMES ESCROCS REFONT LES MEMES JETONS : detecter le GABARIT et l eviter.

L IDEE, DE MIDO, mot pour mot : « c'est pas un critère fixe fond noir écriture milieu, l'idée que
j'ai c'est que des cons arnaqueurs s'inspirent et les mêmes cons refont la même sorte de crypto ;
le marché contient beaucoup d'escrocs et nous on peut gagner si on évite ces escrocs ».

CE QUE ÇA CHANGE PAR RAPPORT A TOUT LE RESTE DU PROJET. Toutes les variables testees jusqu ici sont
des MESURES INSTANTANEES : le prix, le coffre, la volatilite, la concentration des detenteurs. Elles
decrivent le jeton tel qu il est a 45 secondes, et elles disent toutes la meme chose -- ce qui
predit la chute predit aussi la montee. Ici on ne mesure pas le jeton : on se DEMANDE SI ON L A DEJA
VU. C est de la memoire, pas un seuil.

COMMENT ON RECONNAIT UN CREATEUR SANS LE CONNAITRE. Deux jetons batis sur le meme gabarit -- meme
fond, meme mise en page, seul le nom change -- ont des FICHIERS differents (un hash classique ne
verrait rien) mais des empreintes perceptuelles voisines. Le dHash encode la STRUCTURE de l image et
non ses couleurs : il resiste au changement de teinte, de compression et de taille. Deux empreintes
a moins de N bits l une de l autre viennent du meme gabarit, donc tres probablement de la meme main.

LA CAUSALITE EST LE POINT CRITIQUE, et c est ce qui rend la piste honnete : quand un jeton nait, les
jetons du MEME GABARIT nes avant lui sont deja morts ou vivants -- leur sort est CONNU. On peut donc
juger un nouveau jeton sur le passe de ses freres sans rien lire de son avenir. Aucun autre filtre du
projet n a cette propriete.

LA REGLE TESTEE : quand un gabarit a deja produit des jetons dont le resultat est connu, et que ces
jetons ont mal fini, ecarter le suivant.

CE QU IL FAUT VERIFIER AVANT D Y CROIRE, et qui est teste ici :
  1. les gabarits se REPETENT-ILS assez pour que la question se pose ?
  2. le passe d un gabarit predit-il l avenir du suivant, ou est-ce du bruit ?
  3. l effet survit-il a une barre tiree d une variable ALEATOIRE de meme structure ?

Lecture seule sur `images.sqlite` et sur le conteneur. N ecrit rien.
"""
from __future__ import annotations

import os
import random
import sqlite3
import statistics as st
import subprocess
from collections import defaultdict

BASE_IMG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "..",
                        "data", "recherche", "images.sqlite")
COUT, PLAFOND = 0.0262, 3.0
DISTANCE = 10          # bits de difference en deça desquels on parle du MEME gabarit


def _resultats() -> dict[str, tuple[float, float]]:
    """mint -> (instant de decision, net). Lu dans le conteneur, en lecture seule."""
    code = (
        "import sqlite3;"
        "c=sqlite3.connect('file:/app/db/papier_combo.sqlite?mode=ro',uri=True,timeout=30);"
        "rows=c.execute('''SELECT d.mint, d.t_dec, i.brut_240 FROM decision d"
        " JOIN issue i ON i.pair=d.pair WHERE d.eligible=1 AND i.brut_240 IS NOT NULL"
        " AND d.risque IS NOT NULL AND d.risque<=0.2694''').fetchall();"
        "print('\\n'.join('%s\\t%s\\t%s'%r for r in rows))"
    )
    out = subprocess.run(["docker", "exec", "-i", "tangier-intel", "python", "-c", code],
                         capture_output=True, text=True, timeout=180)
    d = {}
    for ligne in out.stdout.splitlines():
        p = ligne.split("\t")
        if len(p) == 3:
            try:
                d[p[0].strip()] = (float(p[1]), min(float(p[2]) - COUT, PLAFOND))
            except ValueError:
                continue
    return d


def _bits(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def groupes(emp: dict[str, str], distance: int = DISTANCE) -> dict[str, int]:
    """mint -> numero de gabarit. Regroupement glouton : chaque jeton rejoint le premier gabarit
    dont un membre est a moins de `distance` bits, sinon il en ouvre un nouveau."""
    chefs: list[tuple[int, str]] = []          # (numero, empreinte du chef de file)
    out: dict[str, int] = {}
    for m, e in emp.items():
        trouve = None
        for num, chef in chefs:
            if _bits(e, chef) <= distance:
                trouve = num
                break
        if trouve is None:
            trouve = len(chefs)
            chefs.append((trouve, e))
        out[m] = trouve
    return out


def rapport() -> None:
    chemin = os.path.abspath(BASE_IMG)
    if not os.path.exists(chemin):
        print("pas encore de base d images"); return
    c = sqlite3.connect("file:%s?mode=ro" % chemin, uri=True, timeout=30)
    emp = {m: e for m, e in c.execute(
        "SELECT mint, empreinte FROM image WHERE empreinte IS NOT NULL AND erreur IS NULL")}
    res = _resultats()
    emp = {m: e for m, e in emp.items() if m in res}
    print("\nGABARITS D IMAGE · %d jetons avec empreinte ET resultat" % len(emp))
    if len(emp) < 100:
        print("   trop peu pour conclure (la collecte est-elle finie ?)")
        return
    g = groupes(emp)
    tailles = defaultdict(list)
    for m, num in g.items():
        tailles[num].append(m)
    multi = {k: v for k, v in tailles.items() if len(v) >= 2}
    print("   %d gabarits distincts · %d comptent au moins 2 jetons (%d jetons concernes)"
          % (len(tailles), len(multi), sum(len(v) for v in multi.values())))
    if not multi:
        print("   aucun gabarit ne se repete : l idee ne s applique pas a cet echantillon")
        return
    gros = sorted(multi.values(), key=len, reverse=True)[:5]
    print("   les plus repetes : %s" % ", ".join(str(len(v)) for v in gros))

    # LE TEST QUI COMPTE, avec une causalite stricte : pour chaque jeton, on ne regarde que les
    # freres nes AVANT lui, dont le sort est donc deja connu au moment ou il faudrait decider.
    paires = []
    for num, membres in multi.items():
        ordre = sorted(membres, key=lambda m: res[m][0])
        for i in range(1, len(ordre)):
            passe = [res[x][1] for x in ordre[:i]]
            paires.append((st.mean(passe), res[ordre[i]][1], len(passe)))
    if len(paires) < 30:
        print("\n   %d paires seulement : trop peu pour trancher" % len(paires))
        return
    print("\n   %d jetons ont au moins un FRERE plus ancien dans leur gabarit" % len(paires))
    paires.sort(key=lambda x: (x[0], random.random()))
    q = len(paires) // 3
    print("   %-28s %6s %14s" % ("passe du gabarit", "n", "net du SUIVANT"))
    for k, nom in enumerate(("le pire tiers", "le tiers du milieu", "le meilleur tiers")):
        s = paires[k*q:(k+1)*q] if k < 2 else paires[2*q:]
        print("   %-28s %6d %+13.2f %%" % (nom, len(s), 100 * st.mean(x[1] for x in s)))
    a = [x for x in paires if x[0] < 0]
    b = [x for x in paires if x[0] >= 0]
    if a and b:
        print("\n   gabarit dont le passe est PERDANT  : n=%4d · le suivant fait %+.2f %%"
              % (len(a), 100 * st.mean(x[1] for x in a)))
        print("   gabarit dont le passe est GAGNANT  : n=%4d · le suivant fait %+.2f %%"
              % (len(b), 100 * st.mean(x[1] for x in b)))
        # BARRE DU HASARD : on melange les gabarits et on refait le meme calcul. Si l ecart
        # observe tombe dans ce nuage, le gabarit n explique rien.
        random.seed(20260918)
        tous = [res[m][1] for m in emp]
        tir = sorted(st.mean(random.choice(tous) for _ in a) for _ in range(5000))
        obs = st.mean(x[1] for x in a)
        p = sum(1 for x in tir if x <= obs) / 5000
        print("   -> ecart %+.2f pt · p = %.3f contre un tirage au hasard  %s"
              % (100 * (st.mean(x[1] for x in a) - st.mean(x[1] for x in b)), p,
                 "AU-DELA DU HASARD" if p < 0.05 else "pas distinguable du hasard"))

    # LA MEME QUESTION, MAIS SUR UN TAUX plutot qu une moyenne. Lecon du 18/09 (§3.121) : la
    # moyenne de ces tickets est ecrasee par quelques valeurs a +200 %, donc structurellement
    # incapable de reveler un signal. Un TAUX est borne, insensible aux queues -- c est ainsi que
    # le frein sur le marche a ete trouve apres que 45 formulations en moyenne eurent echoue.
    # Ici : un gabarit qui a DEJA produit une catastrophe en produit-il une autre ?
    print("\n   VARIANTE PAR TAUX : le gabarit a-t-il deja produit une CATASTROPHE (<= -70 %) ?")
    paires2 = []
    for num, membres in multi.items():
        ordre = sorted(membres, key=lambda m: res[m][0])
        for i in range(1, len(ordre)):
            passe = [res[x][1] for x in ordre[:i]]
            taux = sum(1 for y in passe if y <= -0.70) / len(passe)
            paires2.append((taux, res[ordre[i]][1], 1 if res[ordre[i]][1] <= -0.70 else 0))
    if len(paires2) >= 30:
        avec = [x for x in paires2 if x[0] > 0]
        sans = [x for x in paires2 if x[0] == 0]
        print("   %-34s %6s %14s %14s" % ("passe du gabarit", "n", "net du suivant", "catastrophes"))
        for nom, s in (("a DEJA produit une catastrophe", avec), ("n en a jamais produit", sans)):
            if len(s) < 5:
                print("   %-34s %6d  trop peu" % (nom, len(s)))
                continue
            print("   %-34s %6d %+13.2f %% %13.0f %%"
                  % (nom, len(s), 100 * st.mean(x[1] for x in s), 100 * st.mean(x[2] for x in s)))
        if len(avec) >= 5 and len(sans) >= 5:
            # barre du hasard sur le TAUX de catastrophes, pas sur la moyenne
            base = st.mean(x[2] for x in paires2)
            tir2 = sorted(st.mean(1 if random.random() < base else 0 for _ in avec)
                          for _ in range(5000))
            obs2 = st.mean(x[2] for x in avec)
            p2 = sum(1 for x in tir2 if x >= obs2) / 5000
            print("   -> taux de catastrophes %+.1f pt · p = %.3f  %s"
                  % (100 * (st.mean(x[2] for x in avec) - st.mean(x[2] for x in sans)), p2,
                     "AU-DELA DU HASARD" if p2 < 0.05 else "pas distinguable du hasard"))


if __name__ == "__main__":
    rapport()
