# Les pistes en cours — état au 18/09/2026, 19h45

Ce fichier existe pour une raison : plusieurs pistes tournent en parallèle, chacune avec son critère
écrit d'avance, et il est impossible de toutes les garder en tête. **Une ligne par piste, ce qu'elle
teste, où elle en est, et quand elle rendra son verdict.**

Tous les chiffres viennent d'une exécution réelle des scripts, pas de mémoire. Pour les remettre à
jour : `docker exec -w /app tangier-intel python -m intel.research.<nom>`.

---

## Les deux choses à savoir avant tout le reste

### 1. Le frein a été DÉBRANCHÉ le 18/09 à 19h30

Jugé sur les 82 tickets **postérieurs à son propre gel** :

| | n | net |
|---|---|---|
| tout prendre | 82 | **−1,47 %** |
| **avec le frein** | 49 | **−10,38 %** |

Ses trois critères sont NON : corrélation de rang négative (−0,086), Q1 n'est pas le pire, le frein
n'aide pas.

**Ce qui l'avait mis en prod n'était pas un test.** Le commit annonçait « hors échantillon **de la
bande** » — pas du frein, dont la fenêtre de 20 avait été choisie sur ces mêmes données. Coupé à son
propre gel : **+1,49 pt avant, −8,91 pt après**. Même motif que `BAS + BANDE`, la troisième fois.

Et l'argument décisif était faux : « il ne fait que s'abstenir, il ne peut pas créer de perte
nouvelle ». **S'abstenir n'est neutre que si c'est au hasard.**

**Débranché avec l'accord de Mido**, après P&L rejoué en deux moitiés (−23,50 pt puis −0,99 pt :
négatif des deux côtés). La production est revenue à `risque` seul. Le gel `frein_taux` continue
de le juger en papier, sans rien coûter.

### 2. Le coût réel est peut-être 4,87 points, pas 2,62

`calibration_live`, 73 tickets sur les mêmes jetons que le papier :

```
écart réel − papier : −2,25 pt   IC95 [−6,20 ; +1,24]  -> aucun écart démontrable
avec un coût plat recalé à 4,87 pts : écart +0,00 pt
```

Traduction : l'écart n'est **pas démontrable** à ce stade, et s'il existe il est entièrement une
question de **niveau de coût**, pas de biais sur les gagnants. Mais s'il se confirme, le coût réel
est 4,87 pts et **aucune règle testée ne passe ce seuil**. C'est la question n°1 du projet.

**Il faut ~100 tickets. Il en manque 27.** Ne rien corriger avant.

---

## Le carnet réel

`modele_rapide`, `mode: live`, mise 20 €.

- **76 tickets clôturés, −92,33 €, ~53 % de gagnants.** Budget d'arrêt : −150 €.
- Règle : décision à 45 s, acheter si `risque ≤ 0,2694`, vendre à 240 s sans stop ni prise de gain.
  **Aucun frein, aucun plafond en nombre d'ordres.**
- La seule raison de le laisser tourner : finir la calibration ci-dessus.

---

## Les gels — une piste par ligne

Chacun a son critère écrit **avant** d'avoir vu les données, et se juge sur les tickets
**postérieurs** au gel.

| piste | gelée le | avancement | où ça en est | verdict provisoire |
|---|---|---|---|---|
| **ensemble de 12 modèles** | 18/09 01h30 | 512 / 1000 | forêt aléatoire **+48 €**, ensemble +21 € contre le modèle en service | **le seul qui va dans le bon sens** |
| `piste_foule` (≥ 91 acheteurs) | 17/09 22h00 | 182 / 1568 | écart −17,84 %, moitiés −31,2 / −4,6 | mauvais |
| `frein_taux` | 18/09 17h00 | 82 / 1500 | −10,38 % avec, −1,47 % sans | échoue les 3 · **débranché de la prod** |
| `usine` (filtre IPFS) | 18/09 18h00 | 59 / 1200 | écart −3,01 pt, **inversé** depuis le gel | (b) échoue : pas sur les deux moitiés |
| `au_plus_bas` | 18/09 10h00 | 53 / 800 | +8,66 %, +115 € | (a) échoue : gros gains ×1,42 au lieu de ×1,5 |
| `bas_bande` | 18/09 11h30 | 30 / 1200 | +8,27 % mais **−10,09 % sans ses 3 meilleurs** | (b) et (c) échouent |
| `entree_75` (T+75 vs T+60) | 18/09 09h05 | 24 / 1000 | +1,24 pt apparié | (b) et (c) échouent |
| `frein_bande` | 18/09 18h30 | 13 / 800 | trop tôt | — |

**Tous ont aussi une date butoir : 21 jours.** Passé ce délai sans critère atteint, la piste est
abandonnée, même si le nombre de tickets n'est pas atteint.

---

## Les collectes en cours

Quatre collecteurs détachés, relancés par `gardien.py` toutes les 60 s s'ils meurent — vérifié
après le redémarrage de 19h30 : ils sont tous revenus seuls.

| collecteur | ce qu'il enregistre |
|---|---|
| `papier_combo` | **le carnet papier de référence** — décision 45 s, sortie 287 s |
| `prix_rapide` | le prix à **1 s**, fenêtre 35–310 s |
| `social_collecte` | concentration des détenteurs (`sac1`) — **mesure contaminée, voir plus bas** |
| `stock_collecte` | **NOUVEAU** — la trajectoire du stock, 4 photos à 15/25/35/45 s |
| `gardien` | relance les quatre autres toutes les 60 s |

⚠️ `intel/` **et** `config/intel.yaml` sont montés en lecture seule, et la config n'est lue qu'au
**démarrage** : tout changement de règle demande `docker restart tangier-intel`. Un redémarrage est
sûr pour une position ouverte (`_sortir` relit les lignes `OUVERTE` en base), mais attendre sa
clôture évite de décaler une vente de 240 s.

---

## La nouvelle piste : la trajectoire du stock

**Ton hypothèse** : une partie des effondrements vient de groupes entrés très tôt qui tiennent encore
de quoi vider le pool ; le signal d'achat serait le moment où ils ont distribué et où des acheteurs
extérieurs continuent d'arriver.

Ce qui la distingue : **toutes nos autres variables sont des mesures de prix**, et elles disent
toutes la même chose — ce qui prédit la chute prédit la montée. Celle-ci mesure un **état** : combien
de munitions restent au-dessus du marché.

- Collecte depuis le **18/09 16h24**. 12 jetons complets, 0 erreur. ~300 attendus en 9 h.
- **Critère écrit d'avance** : 300 jetons complets, après le coût mesuré, sur des lancements
  postérieurs au gel, sans les 3 meilleurs tickets, contre un tirage aléatoire de même taille.
- **Risque connu dès le premier échantillon** : sur les premiers jetons, le stock **n'a pas bougé**
  entre 15 et 45 s. Si c'est général, le film ne dira rien de plus que la photo — et la piste est
  close. Ce serait un résultat utile.

---

## Ce qui a changé aujourd'hui : un test que je croyais fermé ne l'est pas

`expert_detenteurs` avait fait **−169 €** et j'avais fermé la piste de la concentration des
détenteurs. **C'était faux.** La variable `sac1` mesurait, sur 571 jetons :

| ce qu'était « le plus gros détenteur » | n | `sac1` médian |
|---|---|---|
| le **coffre du pool** | 209 | 20,3 % |
| un **vrai portefeuille** | 106 | 78,6 % |

Deux variables empilées, décrivant les situations les plus opposées qui soient. **Le verdict −169 €
condamne la mesure, pas la concentration.**

Et j'ai failli me tromper une deuxième fois en reclassant l'historique : il faut lire les comptes
**aujourd'hui**, or 256 sur 571 sont fermés, et ce groupe écarté a une médiane de **+13,98 %** contre
−2,60 % pour les autres. « Le compte est-il encore lisible ? » est une **information du futur**.
Seule une collecte en avant peut répondre — c'est `stock_collecte`.

---

## Ce qui est définitivement clos

Stop-loss · prise de gain · durée de détention · découpage de l'ordre · taille de pool · récupération
des cautions · régime de marché sur le rendement moyen · gabarits d'image (fond noir, écriture au
milieu) · portefeuille créateur · copie des bons traders.

**Faits à ne jamais recalculer de tête** : le coût d'exécution mesuré est 2,62 pts sur 244 tickets
réels (mais voir l'alerte n°2) · la chute est une falaise, −55 % en une seconde, aucun stop possible
· garder un jeton effondré aggrave toujours (−80,5 % à 4 min, −97,1 % à 20 h).

---

## Ce qui attend une décision de ta part

1. ~~Le frein~~ — **réglé le 18/09 à 19h30 : débranché, retour à `risque` seul.**
2. **La forêt aléatoire est le seul gel positif** (+48 € contre le modèle en service, 354 tickets).
   Faut-il la tester en production quand elle atteindra ses 1 000 tickets ?
3. ~~Redémarrer le conteneur~~ — **fait au passage : `stock_collecte` est maintenant surveillé par
   le gardien**, et les quatre collecteurs sont revenus seuls.
