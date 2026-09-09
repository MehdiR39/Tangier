# Journal de recherche — Tangier Intel

**À lire au début de chaque séance, et à compléter à la fin.** Ce fichier est la mémoire du
projet : ce qui tourne, ce qui a été mesuré, ce qui a échoué et pourquoi. Sans lui on refait les
mêmes tests et on répète les mêmes erreurs.

Règle d'écriture : **un chiffre sans sa méthode ne vaut rien.** Chaque entrée dit la question, la
donnée, le résultat, et la conclusion qu'on en tire — y compris quand la conclusion est « on ne
sait pas ».

Dernière mise à jour : 2026-09-09.

---

## 1. Le système en une page

Deux carnets automatiques qui achètent des jetons dans leur première minute de vie et les revendent
quelques minutes plus tard.

| | Robinhood Chain | Solana |
|---|---|---|
| Découverte | logs `Initialize` d'Uniswap v4 | DexScreener **+ flux de migrations en direct** (§3.21) |
| Règle d'entrée | 27 à 60 échanges dans la 1re minute **puis ≥ 30 échanges dans la 2e** (§3.10) | ≥ 75 acheteurs distincts, **< 600 échanges**, ≤ 15 échanges/acheteur, capitalisation < 50 k$, hors pump.fun (§3.6, §3.13, §3.26) |
| Refus d'entrée | — | mesure de la 1re minute incomplète (§3.25) · prix tombé sous la moitié de celui vu sur le même jeton dans le quart d'heure (§3.26) |
| Sortie | ×2 ou T+5 min | **×1,5**, **stop à −30 %**, ou T+15 min (§3.23, §3.24) |
| Ticket | 5 € | 20 € |
| Portefeuille | `0x2a33086d2fce255f61ac1a3000bf944397c9c908` | `HY4wrwepxv3JCMox1LG7K46Bj6TnP1xMHSk42ojEZfyL` |
| État au 09/09 00h30 | actif, **aucune limite** : ni budget, ni plafond horaire, ni coupure de pertes | actif, 4 positions max (contrainte du portefeuille), **aucun plafond horaire**, coupure à 100 € de pertes **réelles** par jour |

**Expériences en cours** — chacune a un critère écrit d'avance :

- **Robinhood, 10 tickets de 5 €** : la confirmation en deuxième minute fait-elle tomber le taux
  d'invendables sous 40 % ? Référence : 100 % sur les cinq derniers tickets, 46 % sur les
  vingt-huit précédents. Bascule d'annulation : `t1.confirm_minute2: 0`.
- **Solana, série ouverte de tickets de 20 €** : l'objectif ramené à ×1,5 (§3.23) inverse-t-il la perte de 5,70 € par ticket constatée à ×2 ? Le plancher de 75 acheteurs tient-il ce que le backtest promet
  (+0,36 par euro, 69 % de gagnants) ? Référence : −18,16 € réels sur les cinq tickets sans
  plancher. Bascule d'annulation : `solana.min_buyers: 5`.
- **Solana, le refus « jeton effondré » coûte-t-il des occasions ?** Posé le 08/09 22h. Deux cas
  mesurés (NASFROG, WTW) achetaient le jeton 26× et 4,4× sous le prix auquel la règle venait de
  l'écarter. Le refus est posé du côté prudent, mais NASFROG est ressortie à ×1,41 : il se peut
  qu'entrer après une chute soit un bon point d'entrée. `solana_judgements` enregistre désormais
  chaque passage avec capitalisation, variation à 5 min et âge. **Critère** : d'ici 200 jugements,
  comparer le résultat des lignes achetées après une chute à celui des autres. Bascule
  d'annulation : `solana.collapse_memory_seconds: 0`.

Passer en réel demande **deux gestes séparés** sur chaque chaîne : une clé privée dans `.env`, et
`mode: live` dans `config/intel.yaml`. La clé ne sort jamais de `_keypair()` / `signer.py`.

### Adresses qui ont coûté cher à trouver

- Il existe **deux déploiements Uniswap v4** sur Robinhood Chain. Notre PoolManager est
  `0x8366a39cc670b4001a1121b8f6a443a643e40951`, et le seul routeur qui le sert est
  `0x8876789976decbfcbbbe364623c63652db8c0904`. Le routeur « par défaut » (`0xf8b30c1b…`) sert un
  autre PoolManager : cinq achats réels ont échoué en `PoolNotInitialized` avant qu'on le voie.
- ETH natif = `0x0000…0000`, WETH = `0x0bd7d308f8e1639fab988df18a8011f41eacad73`. Seul l'ETH natif
  est autorisé à l'achat réel (§3.2) ; les pools WETH partent au carnet à blanc.

---

## 2. Résultats réels, lus sur la chaîne

Jamais depuis le livre : depuis le solde des portefeuilles. Voir §5.1 pour pourquoi.

| Chaîne | Versé | Solde | Négoce |
|---|---|---|---|
| Robinhood | 0,186 ETH (0,003 le 04/09 + 0,183 le 07/09) | 0,1846 ETH | **−3,20 €** |
| Solana | 2,980 SOL | 2,789 SOL | **−18,16 €** |

Le livre Telegram annonce −19,77 € contre −21,37 € en vérité, soit **1,60 € d'écart** : c'est le
gaz des autorisations de dépense et des transactions rejetées, qui sort du portefeuille sans
appartenir à aucune ligne.

---

## 3. Journal des mesures

### 3.1 — Le compteur d'entrée T+1 (Robinhood), 2026-09-06
**Question** : quel signal, mesurable en une minute, prédit qu'un lancement va monter ?
**Donnée** : 5 491 lancements échantillonnés, paquet `intel/research/`.
**Résultat** : le seul signal qui survit hors échantillon est un **compteur d'échanges** : ≥ 27
échanges dans la minute suivant le premier trade. Les indicateurs techniques classiques n'ont
aucun pouvoir à 6 h sur les jetons établis.
**Conclusion** : c'est devenu la règle d'entrée. Voir §3.9 pour ce qu'elle vaut aujourd'hui.

### 3.2 — Les pools cotés en USDG perdent, 2026-09-07
**Donnée** : carnet réel, 42 lignes USDG contre 106 ETH.
**Résultat** : USDG −73 € avec 24 % de gagnants ; ETH +159 €.
**Conclusion** : `allowed_quotes` ne contient que l'ETH natif. Les pools USDG et WETH continuent
d'être mesurés en argent fictif.

### 3.3 — Le plafond de 60 échanges, 2026-09-07
**Question** : au-delà de combien d'échanges une première minute dense est-elle un bundle ?
**Donnée** : 84 pools ETH que le livre n'a **pas** achetés (donc sans effet de notre part).
**Résultat** : sous 60 échanges, 77 % vivaient encore 5 minutes après ; au-dessus, 11 %, durée de
vie médiane 1,1 minute. Nos propres achats du jour : 6 sous le plafond +57,82 €, 13 au-dessus
−59,22 €.
**Nuance importante** : l'historique des 45 jours précédents disait l'inverse (100-200 échanges
survivaient le mieux). C'est **une tactique qui a changé, pas une loi**. `t1.max_trades: 0` retire
le plafond.

### 3.4 — Pump and pull, 2026-09-07
**Résultat** : 81 % des pools passant la barre T+1 voient leur liquidité retirée **1 seconde**
après leur dernier échange.
**Conclusion** : sortie « ×2 sinon T+5 ». Tenir plus longtemps détruit le carnet sur cette chaîne.

### 3.5 — Calibration Solana, 2026-09-08
**Question** : quelle règle d'entrée sur Solana, où l'on peut compter les acheteurs distincts ?
**Donnée** : 254 lancements observés minute par minute sur 12 h (`intel/research/solana_backtest.py`).
**Résultat** : le rapport échanges/acheteur sépare (sous 15 on gagne, au-dessus on perd), et la
sortie ×2-ou-T+15 gagne sur les quatre critères à la fois.
**Conclusion** : règle de départ, ticket 5 € puis 20 €.

### 3.6 — Le plancher d'acheteurs distincts (Solana), 2026-09-08
**Question** : le nombre absolu d'acheteurs prédit-il mieux que leur ratio ?
**Donnée** : les mêmes 254 lancements.

| Plancher | n | Gagnants | Par euro |
|---|---|---|---|
| ≥ 5 (avant) | 91 | 65 % | +0,237 |
| ≥ 100 | 34 | 71 % | +0,359 |
| ≥ 125 (retenu) | 22 | 73 % | +0,447 |

**Trois vérifications** : il améliore les **sept** règles de sortie testées, donc il ne s'accroche
pas à un couple de paramètres ; au-dessus de 125 acheteurs aucun lancement ne dépasse 15
échanges/acheteur, donc il englobe le filtre anti-bundle ; il laisse 1,2 occasion/h en direct.
**Réserve assumée** : la tranche > 125 ne compte que 22 lancements et c'est elle qui porte
l'avantage. Sur les cinq achats réels du 08/09 il aurait gardé haMSTR et ANSEMCOIN, écarté Dukky
et CATECOIN : +3,55 € au lieu de −18,32 €.
**Appliqué** le 08/09 à 11h15 au seuil 125, **ramené à 100 à 12h30**, puis **à 75 à 14h00**.
Chaque descente a la même cause : le plancher, et non le marché, était le facteur limitant. À 125,
une heure sans occasion ; à 100, deux heures et demie et vingt-quatre lancements jugés pour zéro
ticket, toutes les rejections disant « acheteurs < 100 » avec un maximum observé à 82.

Le tableau qui a décidé du seuil 75, avec le plafond de densité du §3.13 :

| Règle | n | Gagnants | Par euro | Robustesse | Rythme réel |
|---|---|---|---|---|---|
| Plancher 100 et < 600 échanges | 28 | 75 % | +0,437 | +0,371 | 1,38/h → 20 tickets en 15 h |
| **Plancher 75 et < 600 échanges** | 39 | 69 % | +0,359 | +0,288 | **1,88/h → 20 tickets en 11 h** |
| Plancher 50 et < 600 échanges | 49 | 65 % | +0,296 | +0,218 | 2,13/h → 20 tickets en 9 h |

Le plancher 75 avec plafond rend exactement ce que rendait le plancher 100 sans plafond, pour 40 %
de tickets en plus. En dessous de 75 la robustesse décroche.

### 3.7 — Le biais du compteur d'acheteurs est volontaire, 2026-09-08
**Fait** : les acheteurs sont comptés sur les **300 premières transactions** de la minute, les
échanges sur la minute entière. Pour 46 % des lancements le rapport est donc gonflé.
**Test** : le rapport corrigé filtre **moins bien** (60 % de gagnants et +0,193 par euro, contre
62 % et +0,221 pour le biaisé à sélectivité égale), parce que le biaisé transporte aussi la
densité — et la densité a un optimum propre : 300 à 600 échanges rendent +0,390 par euro, au-delà
de 600 c'est négatif.
**Conclusion** : **ne pas « corriger » ce plafond.** Noté dans `solana_watcher.py` et
`research/solana_watch.py`, qui échantillonnent identiquement exprès.

### 3.8 — Entrer plus tard sur Solana tue l'avantage, 2026-09-08
**Question** : peut-on ouvrir la fenêtre d'achat (75 s – 10 min) pour capter plus de lancements ?

| Entrée | Gagnants | Par euro |
|---|---|---|
| T+1 min | 70 % | +0,427 |
| T+5 min | 57 % | +0,131 |
| T+10 min | 35 % | **−0,107** |
| T+30 min | 32 % | −0,073 |

**Conclusion** : non. Tout l'avantage vit dans les premières minutes. La fenêtre n'est pas un
réglage, c'est la stratégie.

### 3.9 — Pourquoi Robinhood a été mis en pause, 2026-09-08 12h02
**Fait** : l'expérience s'est soldée à **5 tickets sur 5 invendables, −25,32 €**. Aucune vente n'a
abouti. Historiquement 46 % d'invendables sur les 28 lignes précédentes. La règle d'arrêt convenue
avec l'opérateur (« au-dessus de 40 %, Robinhood s'arrête ») est franchie deux fois plutôt qu'une.

    #318 −5,06 €   #321 −5,06 €   #323 −5,07 €   #324 −5,07 €   #325 −5,06 €

Toutes fermées au même motif : « invendable après 8 essais ». Les achats ont été coupés après le
troisième ; les deux derniers étaient déjà engagés.
**La pause a été levée à 12h30**, mais sous une règle différente : voir §3.10.
**Diagnostic, en trois tests** :
1. Le transfert ERC-20 passe depuis notre adresse **et** depuis une adresse témoin à qui on
   invente un solde → aucune liste noire, le contrat n'est pas en cause.
2. D'autres ont vendu 15 à 19 fois dans la première minute → le jeton n'est pas bloqué.
3. L'état des pools : liquidité **zéro** sur l'un, prix effondré sur les deux autres au point que
   637 000 jetons valent quelques milliers de wei.

**La mesure qui explique tout**, sur 16 lignes réelles :

| | Échanges après notre achat (médiane) |
|---|---|
| Lignes vendues | **296** |
| Lignes invendables | **12** |

On n'achète pas des pièges, on achète **des pools dont la vie est déjà finie**. Et à T+1 minute
rien de ce qu'on mesure ne sépare les deux : 52 échanges en première minute donne un pool mort
comme un pool vivant.

### 3.10 — La deuxième minute comme confirmation (Robinhood), 2026-09-08
**Question** : attendre T+2 et exiger que l'activité continue sauve-t-il le carnet ?
**Donnée** : 1 365 pools suivis à t+1, t+2, t+5… ; 321 passent la barre 27-60.
**Ce qui est solide** (fait observable, pas un prix simulé) :

| Seuil en minute 2 | Pools gardés | dont morts | Pools écartés | dont morts |
|---|---|---|---|---|
| ≥ 10 échanges | 281 | 5 % | 40 | **80 %** |
| ≥ 20 échanges | 271 | 2 % | 50 | **80 %** |
| ≥ 30 échanges | 257 | **0 %** | 64 | **72 %** |

**Ce qui n'est pas tranché** : le simulateur donne T+1 gagnant (+0,479 par euro même en comptant
les pools morts comme perte totale, contre +0,387 à T+2). Mais il annonce aussi 82 % de gagnants
à T+1 là où le carnet réel perd avec 46 % d'invendables. **Un simulateur déjà faux sur la règle
en place ne peut pas départager l'alternative.**
**Conclusion** : le filtre identifie très bien les pools mourants. Savoir si la minute d'attente
coûte plus qu'elle ne rapporte demande une expérience réelle bornée, pas une simulation.
**Implémenté et lancé le 08/09 à 12h30** : `t1.confirm_minute2: 30`. Le verdict d'un pool est
différé à T+2 ; s'il fait moins de 30 échanges pendant sa deuxième minute, il est écarté comme
mourant. Expérience bornée à 10 tickets de 5 €, soit 50 € de risque. **Critère de réussite :** le
taux d'invendables doit tomber sous 40 %, contre 100 % sur les cinq derniers tickets et 46 % sur
les vingt-huit précédents. `t1.confirm_minute2: 0` revient à l'achat immédiat.

### 3.13 — La densité dit autre chose que le plancher d'acheteurs (Solana), 2026-09-08
**Question** : à plancher d'acheteurs égal, la densité de la première minute sépare-t-elle encore ?
Deux filtres qui disent la même chose ne valent pas mieux qu'un.
**Donnée** : les 254 lancements observés, plancher fixé à 100 acheteurs.

| | n | Gagnants | Par euro | Médiane | Sans 10 % haut |
|---|---|---|---|---|---|
| Plancher 100 seul | 35 | 69 % | +0,348 | +0,459 | +0,266 |
| **Plancher 100 et moins de 600 échanges** | 28 | **75 %** | **+0,437** | **+0,630** | **+0,371** |

**Résultat** : les quatre mesures montent ensemble, y compris la robustesse (+39 % une fois le
meilleur dixième retiré), donc l'effet n'est pas porté par quelques lignes chanceuses. Un
**plancher** d'échanges, lui, n'apporte rien : au-dessus de 300 le résultat baisse.
**Coût** : 12 % des occasions, 1,50 par heure au lieu de 1,70.
**Appliqué** le 08/09 à 12h40 : `solana.max_trades_first_minute: 600`. Mettre 0 pour le retirer.

### 3.14 — Le signe achat/vente était inversé dans `features.py`, 2026-09-08
**Question** : les deltas d'un swap v4 sont-ils du côté du pool ou du côté de l'appelant ?
**Donnée** : nos cinq achats confirmés, retrouvés dans les événements de swap.
**Résultat** : sur chacun, la jambe du jeton vaut **+5,7 × 10²³** et celle de la cotation
**−2,18 × 10¹⁵**. Les deltas sont donc du côté de l'appelant : `tok > 0` est un achat.
`features.py` testait `tok < 0`, donc **appelait vente tout achat et achat toute vente**.
**Portée** : le compteur d'entrée T+1 n'est pas touché, il compte des échanges sans regarder le
sens. Tout indicateur d'achat/vente bâti sur `window()` l'était. `book_sim`, `book_sim2`,
`replay_paper` et `tax_ceiling` avaient déjà la bonne convention.
**Corrigé** le 08/09.

### 3.15 — Le scanner de notation n'a pas d'avantage, 2026-09-08
**Question** : après une mauvaise journée sur T+1, le scanner de notation du dépôt vaut-il mieux ?
Horizon de quelques heures, jetons liquides, pas de déployeur en face.
**Donnée** : 12 021 évaluations sur six jours croisées avec 314 000 relevés de prix.

| Horizon 6 h (79 % de couverture) | n | Médiane | % qui doublent |
|---|---|---|---|
| Taux de base | 8 783 | −3,8 % | **1,9 %** |
| Score 65 à 75 | 4 038 | +0,5 % | 1,6 % |
| Score 75 et plus | 2 728 | −5,5 % | **0,3 %** |

À 24 h : base −21,4 % et 3,0 % de doublements ; score 75+ à −20,9 % et **0,4 %**.

**Résultat** : les jetons les mieux notés doublent six à sept fois **moins** souvent que la moyenne.
Le score est inversement lié à ce qu'on cherche. La couverture manquante joue contre lui : les
jetons absents des relevés sont les morts.
**Attention** : les moyennes affichées sont aberrantes (+5 978 %, +3 149 097 %), signe de prix
faux dans certains relevés. Seules les médianes sont exploitables ici, et il y a une dette de
qualité de données à traiter dans `token_snapshots`.
**Contredit** la note de calibration du 04/09 (« quartile haut : 11,7 % de doublements contre
3,8 % de base »). Six jours de données réelles disent l'inverse.
**Conclusion** : porte fermée. **T+1 reste le seul signal qui ait survécu hors échantillon**
(§3.1), et il ne faut pas l'abandonner sur une mauvaise journée.
**Effet de bord utile** : à 24 h la médiane est de −21 % quelle que soit la note. Tenir un de ces
jetons une journée coûte un cinquième — ce qui confirme que seuls les horizons courts sont
jouables, et donc les sorties à T+5 et T+15.

### 3.24 — Il manquait un stop de perte, 2026-09-08 19h30
**Le défaut** : le carnet avait un objectif de gain et une limite de temps, **rien pour couper une
position qui tombe**. Trois lignes ont été tenues jusqu'à l'échéance pendant qu'elles mouraient —
DLSS5 à ×0,11, ZAPE à ×0,04, FTFS à ×0,01 après **−99 % en cinq minutes**. L'effondrement de FTFS
a été vérifié par deux sources indépendantes : le routeur ne payait plus 0,01 € pour le sac, et
DexScreener affichait 1 786 ventes contre 513 achats sur la période. Ce n'est pas un pool vidé,
c'est tout le monde qui sort en même temps.

| Règle (objectif ×1,5) | Gagnants | Par euro | Médiane | Robustesse |
|---|---|---|---|---|
| Sans stop | 68 % | +0,123 | +0,487 | +0,079 |
| **Stop à −30 %** | 66 % | **+0,183** | +0,487 | **+0,147** |
| Stop à −50 % | 66 % | +0,134 | +0,487 | +0,092 |

**Appliqué** : `solana.stop_loss_multiple: 0.7`. Aurait limité les trois lignes ci-dessus à 6 €
chacune au lieu de 18 à 20, soit **environ 40 € sur une seule journée**.
**Ce qui distingue ce réglage de tous les autres du jour** : le backtest et le réel disent la même
chose. Sur l'objectif de sortie ils se contredisaient et il a fallu trancher pour le réel ; ici ils
convergent. Le stop **suiveur** depuis le sommet, lui, avait été écarté au §3.22 parce qu'il sortait
sur du bruit — un stop sec depuis l'entrée est une règle différente, il ne coupe jamais une gagnante.
**Outil** : `intel/research/sol_stoploss.py`.

### 3.23 — L'objectif de ×2 ne se déclenchait jamais, 2026-09-08 18h
**Ce que le suivi du sommet a révélé** (fonction ajoutée le jour même sur la remarque de
l'opérateur) : sur huit tickets, **l'objectif de ×2 ne s'est pas déclenché une seule fois**. Les
sommets plafonnent à ×1,82. Trois lignes sont montées au-dessus de ×1,4 puis ont tout rendu — ZAPE
de +57 % à −96 %, NIKEY de +50 % à −14 %, BIPOLAR de +82 % à +44 %.

Part du gain potentiel réellement captée, médiane sur les lignes montées : **−14 %**. On ne rate
pas le sommet, on finit sous le prix d'entrée après avoir été à +50 %.

**Simulation sur nos propres relevés** (valeur vendable réelle, toutes les 30 s) :

| Objectif | Déclenché sur | Résultat de la série |
|---|---|---|
| ×1,3 | 3 lignes | +5,54 € |
| ×1,4 | 3 lignes | +11,50 € |
| **×1,5** | 3 lignes | **+17,47 €** |
| ×1,8 | 1 ligne | −18,91 € |
| ×2,0 *(en place)* | **0** | **−46,23 €** |

Le plateau de ×1,3 à ×1,5 repose sur les mêmes trois lignes : ce n'est pas un maximum fragile.
**Appliqué** : `solana.take_profit_multiple: 1.5`.
**Contredit le §3.22**, qui donnait ×2 gagnant sur les quatre critères — mais ce backtest porte sur
une autre journée et n'a jamais envisagé qu'un objectif puisse ne jamais se déclencher. Quand le
backtest et le réel se contredisent, **le réel gagne**.
**Réserve** : huit lignes, dont deux sans sommet mesuré (MEWZ et CPU, antérieures à la fonction) —
et ce sont les deux gagnantes, donc la simulation les pénalise plutôt qu'elle ne les flatte.

### 3.22 — Le stop suiveur est moins bon que l'objectif fixe, 2026-09-08
**Ce qui a ouvert la question** : le suivi du sommet, ajouté sur la remarque de l'opérateur, a
montré des positions qui montent puis retombent avant l'échéance — BIPOLAR sommet ×1,82 vendue
×1,44, NIKEY ×1,50 vendue ×0,86, CPU ×1,80 vendue ×1,18.
**Outil** : `intel/research/sol_trailing.py`, 47 lancements sous la règle en place.

| Sortie | Gagnants | Par euro | Médiane | Robustesse |
|---|---|---|---|---|
| **Objectif ×2** *(en place)* | **66 %** | +0,271 | **+0,309** | **+0,186** |
| Objectif ×3 | 62 % | +0,288 | +0,108 | +0,098 |
| Suiveur −15 % | 57 % | +0,282 | +0,046 | +0,044 |
| Suiveur −30 % | 47 % | +0,247 | −0,011 | +0,005 |
| Suiveur −20 % et objectif ×2 | 55 % | +0,179 | +0,034 | +0,083 |

**Résultat** : non. La moyenne se tient mais la médiane s'effondre de +0,309 à +0,046 et la
robustesse de +0,186 à +0,044. Ces jetons bougent de 20 % en permanence : un stop suiveur sort sur
du bruit avant le vrai mouvement, échangeant quelques sorties bien placées contre beaucoup de
sorties prématurées.
**Conclusion** : rien ne change. Trois observations réelles ont suggéré une piste, la mesure l'a
écartée. Voir un sommet passer fait mal, mais la règle qui l'aurait capté aurait coupé les
gagnantes trop tôt.

### 3.21 — Le flux de lancements en direct, 2026-09-08
**Problème** : la découverte Solana lit deux flux **promotionnels** de DexScreener. Mesuré : 4,3
lancements PumpSwap par heure y apparaissent dans la fenêtre achetable, alors que la chaîne en
gradue **une vingtaine**. On en ratait plus des trois quarts, et le rythme est ce qui empêchait de
savoir si la stratégie gagne.
**Décision** : abonnement Helius Developer, 49 $/mois, pris par l'opérateur le 08/09. L'argument
qui a emporté la décision : le budget de tickets est plafonné, donc l'abonnement **n'amplifie aucun
risque** — il divise seulement par deux le temps pour obtenir la réponse.

**Trois filtres essayés, mesurés au débit réel :**

| Abonnement à | Débit | Coût mensuel | Verdict |
|---|---|---|---|
| PumpSwap entier | 26 544/min | 448 M crédits | exclu (forfait 10 M) |
| pump.fun entier | 3 780/min | 45,6 M | hors forfait, mais `Migrate` y est visible |
| pump.fun × PumpSwap | 55/min | 0,6 M | bon marché, **aucun lancement** — que de la plomberie de frais |
| **pump.fun × `39azUYFW…`** | **0,8/min** | **0,02 M** | retenu |

Le bon compte a été trouvé en capturant quatre migrations et en croisant leurs listes de comptes :
six sont communs, un seul donne un flux étroit.

**Deux erreurs commises en chemin, notées pour ne pas les refaire :**
1. Le premier filtre (croisement avec PumpSwap) semblait évident et ne portait aucun lancement.
   Toujours vérifier qu'un flux contient ce qu'on croit, avant de le brancher.
2. L'extraction cherchait un jeton **apparaissant** dans la transaction, en croyant qu'une migration
   en crée un. Elle n'en crée pas : le jeton vit depuis sa courbe de bonding, c'est le **pool** qui
   est neuf. Quatre migrations sont passées sans rien déposer avant que ça se voie.

**Résultat à 16h55** : premier lancement déposé, récupéré par la découverte vingt-sept secondes plus
tard, et **inconnu de DexScreener**. Le coût réel mesuré est de 0,2 % du forfait.
**Précaution de conception** : la source vient **en plus** de DexScreener, jamais à sa place, et
chaque jeton garde la trace de savoir si l'autre source l'avait aussi. Sans ça, impossible de dire
ce que l'abonnement apporte. La boucle se coupe seule au-delà de 30 Mo par cycle.

### 3.20 — La confirmation en 2e minute ne transfère pas sur Solana, et on sait pourquoi, 2026-09-08
**Question** : la meilleure trouvaille du jour (§3.19) marche-t-elle aussi sur le carnet où les
sorties aboutissent ? **Outil** : `intel/research/sol_confirm.py`.

| Règle Solana | n | Gagnants | Par euro | Sans 10 % haut |
|---|---|---|---|---|
| **Achat à T+1, sans confirmation** *(en place)* | 22 | **64 %** | **+0,357** | **+0,259** |
| Achat à T+2, sans condition | 22 | 59 % | +0,307 | +0,201 |
| T+2, confirmation ≥ 30 | 21 | 57 % | +0,275 | +0,157 |
| T+2, confirmation ≥ 60 | 19 | 63 % | +0,364 | +0,291 |

**Résultat** : non. L'activité médiane en deuxième minute vaut **159 échanges** sur les lancements
que le filtre retient — un seul sur vingt-deux tombe sous les seuils. Il n'y a rien à écarter, et
la minute d'attente coûte l'entrée plus chère.

**L'explication, qui vaut plus que le résultat** : la confirmation en deuxième minute est un
**substitut au comptage des acheteurs**, pas un signal indépendant. Sur Robinhood, 98 % des
échanges passent par un routeur, donc tous les achats semblent venir de la même adresse et compter
les acheteurs est impossible : la deuxième minute est le seul moyen d'y distinguer une foule d'un
bundle. Sur Solana on voit chaque payeur, donc le travail est fait dès T+1.
**Conséquence** : deux chaînes, deux règles, et c'est justifié — pas une incohérence.
**Réserve** : 22 lancements. Le sens est cohérent sur les quatre mesures et le mécanisme tient,
mais ce n'est pas une preuve.

### 3.19 — Le balayage de variantes hors ligne, 2026-09-08
**Outil** : `intel/research/t1_variants.py`. Rejoue toutes les variantes de la règle T+1 sur les
mêmes pools, à partir de ce que le moteur a déjà observé (`t1_observations` + `swap_events`). Ne
touche ni au réseau ni au chemin d'exécution. Créé pour ne plus jamais régler un seuil en
production sur cinq tickets (§3.16).

**Ce qui le rend crédible, contrairement aux simulateurs précédents** : un pool qui fait moins de
30 échanges après l'entrée compte pour une **mise entièrement perdue**, pas pour une sortie au
dernier prix. C'est le modèle validé par le réel (médiane de 12 échanges après achat sur les lignes
invendables, 296 sur les vendues). Résultat : le simulateur reproduit enfin la perte réelle.

Sur 1 659 pools observés en direct, 344 passant la barre :

| Variante | n | Gagnants | Par euro | Médiane | Sans 10 % haut | Pools morts |
|---|---|---|---|---|---|---|
| 27-60, achat à T+1 *(ancienne règle)* | 344 | 40 % | **−0,213** | −0,288 | −0,348 | **39 %** |
| 27-60, confirmation 10 en 2e min | 220 | 48 % | −0,055 | −0,028 | −0,171 | 23 % |
| 27-60, confirmation 20 en 2e min | 156 | 54 % | +0,056 | +0,046 | −0,050 | 16 % |
| **27-60, confirmation 30 en 2e min** | 99 | **61 %** | **+0,137** | **+0,197** | +0,042 | **10 %** |
| 27-60, confirmation 50 en 2e min | 29 | 48 % | +0,078 | −0,016 | −0,027 | 17 % |
| 27-100, confirmation 30 | 167 | 46 % | −0,109 | −0,042 | −0,233 | 26 % |
| 27 et plus, confirmation 30 | 395 | 52 % | +0,037 | +0,015 | −0,070 | 16 % |

**Trois conclusions** :
1. L'ancienne règle perdait **−0,21 par euro** avec 39 % de pools morts. Le simulateur le dit enfin,
   là où les précédents annonçaient +0,479 et 82 % de gagnants (§3.10) parce qu'ils supposaient
   qu'on peut toujours revendre.
2. La confirmation en deuxième minute est l'effet dominant, et 30 est bien l'optimum : monotone
   jusque-là, et 50 fait retomber (n=29).
3. Le plafond de 60 gagne sa place : l'ouvrir à 100 fait replonger à −0,109.

**Règles de sortie, à confirmation 30** : ×1,5 donne la meilleure médiane (+0,469) et 66 % de
gagnants ; ×3 la meilleure moyenne (+0,238) mais uniquement via le décile haut — la robustesse est
identique partout (+0,042 à +0,053). La sortie sans objectif affiche +1,087 de moyenne et **−0,025**
hors décile haut : elle parie entièrement sur ses valeurs extrêmes. Le ×2 en place est un
compromis défendable ; il n'y a pas de gain net à en changer.

**La configuration réelle déployée le 08/09 est donc celle que ce balayage recommande.**

### 3.17 — La sortie : différence de structure entre les deux chaînes, 2026-09-08
**Question** : pourquoi 53 % des lignes Robinhood ne ressortent jamais et 0 % sur Solana ?
**Hypothèse testée puis écartée** : un autre pool paierait et on ne l'utilise pas. La cotation
brute donnait 99 € récupérables sur dix-neuf sacs — mais les états de pool utilisés ont un **âge
médian de 19 heures**. Ce sont des photos prises au moment de la mort du pool. Il n'y a rien à
récupérer et pas de défaut de routage.
**Ce qui reste, et qui est structurel** : sur Robinhood le fournisseur de liquidité peut tout
retirer, et 81 % le font une seconde après le dernier échange (§3.4). Il ne reste alors aucune
contrepartie à aucun prix. Sur Solana, même un effondrement de 95 % laisse un acheteur : Dukky a
rendu 1 € sur 20, ce qui est une perte de marché et non un sac mort.
**Nuance ajoutée le même jour** : le filtre de deuxième minute (§3.10) vise exactement ce risque,
et son premier ticket réel est sorti gagnant à **+3,19 €**. Conclure « Robinhood est structurellement
injouable » était donc prématuré — le filtre écarte précisément les pools qui se referment.
**Attention méthodologique** : la première version de cette mesure appelait la cotation avec la
mauvaise signature et avalait l'exception. Tout ressortait à « rien », ce qui ressemblait à une
réponse alors que c'était une panne. Ne jamais avaler une exception dans une mesure.

### 3.18 — Un jeton, une seule ligne — sur Robinhood aussi, 2026-09-08
**Fait** : le 08/09 à 14h21 et 14h25, le jeton 0x3761600a a été acheté **deux fois, dans deux
pools différents**. Les deux ont passé la barre puisque la garde portait sur le pool et non sur le
jeton.
**Conséquence** : la vente de la première ligne vide le portefeuille des DEUX mises. Une ligne est
créditée du produit de deux, l'autre se retrouve sans jetons et sera déclarée invendable. Le
+3,19 € de la ligne #334 est donc surévalué.
**Corrigé** : garde sur le jeton, comme sur Solana (§5.2). Même défaut, deux chaînes, corrigé le
matin d'un côté et l'après-midi de l'autre — signe qu'un correctif doit être cherché sur les deux
carnets par principe.

### 3.16 — Faute de méthode, 2026-09-08
**Ce qui s'est passé** : le seuil Solana a été changé trois fois en trois heures — 125, 100, 75 —
chaque fois sur un échantillon trop petit pour justifier quoi que ce soit, et chaque changement a
remis le compteur d'expérience à zéro. C'est de l'ajustement au bruit, en production, avec de
l'argent réel.
**Diagnostic manqué en parallèle** : la journée est passée sur la règle d'ENTRÉE alors que le
défaut mesuré est la SORTIE — 53 % des lignes Robinhood ne sont jamais ressorties. Aucun seuil
d'entrée ne répare une vente qui ne passe pas.
**Règle qui en découle** : la configuration réelle ne change qu'après une mesure qui l'exige, et
les variantes se testent dans le carnet à blanc, en parallèle, sur les mêmes lancements. Voir §4.

### 3.11 — Le compte d'acheteurs ne transfère pas sur Robinhood, 2026-09-08
**Donnée** : 321 lancements, sauts de routeur résolus (`intel/research/real_buyers.py`).
**Résultat** : toutes les tranches d'acheteurs donnent entre +1,85 et +3,65 par ticket, et la
tranche haute est **moins** bonne que la médiane. Seuls signaux faibles : moins de 10 détenteurs à
T+1, et plus de 95 % détenus par le top 10.
**Conclusion** : ce qui marche sur Solana ne marche pas ici.

### 3.12 — La découverte Solana regarde la mauvaise liste, 2026-09-08
**Fait** : `token-profiles/latest` et `token-boosts/latest` sont des flux **promotionnels**. À un
instant donné : 0 % des paires rendues ont moins de 10 minutes, 61 % ont entre 1 h et 24 h.
**Voies fermées, testées** :
- 4 autres points d'entrée DexScreener → aucune paire fraîche.
- Énumérer les créations de pool sur la chaîne → PumpSwap fait **30 000 transactions/minute**.
- Surveiller une autorité de migration → chaque créateur signe son propre pool, pas d'autorité
  unique.
**Ce qui passe quand même** : 12,6 lancements/h dans la fenêtre achetable, dont PumpSwap fournit
l'essentiel (0,99/h au plancher 125). Meteora : 29 lancements observés, **zéro** éligible.
**Conclusion** : sans flux payant ni adresse publique pour des webhooks, le seul levier de rythme
est le seuil.


### 3.25 — La mesure de la première minute se dégrade avec l'âge du pool, 2026-09-08
**Déclencheur** : l'opérateur montre le graphique de NASFROG à 22h02 locale — une flambée puis un
effondrement, capitalisation retombée à 2,39 k$ — et demande ce qui s'est passé.

**Donnée, lue dans `solana_observations` et `positions`** :

| moment | prix | échanges 1re min | acheteurs | décision |
|---|---|---|---|---|
| 20:54:27 | 6,194 × 10⁻⁵ | 1 387 | 99 | **écarté** (≥ 600, trop dense) |
| 21:00:15 | — | 258 | 87 | **acheté**, 20 € |
| 21:00:18 | 2,374 × 10⁻⁶ | | | entrée, soit **−96 %** en six minutes |

**Mécanisme** : `_first_minute` remonte l'historique de la paire à l'envers, du plus récent au plus
ancien, par pages de 1 000 signatures, six pages au maximum. Elle s'arrête quand elle franchit
l'instant de création. Si le pool a accumulé plus de 6 000 transactions depuis sa création, la
remontée n'atteint jamais la première minute — et le code comptait alors ce qu'il avait sous la
main **comme si c'était la première minute**, sans pouvoir distinguer « peu d'échanges » de « je ne
les ai pas vus ».

L'effet est pervers dans le sens exact qui coûte de l'argent : plus le lancement est violent, plus
vite la remontée cesse de l'atteindre, donc plus il a de chances de passer sous le plafond
anti-pompe. **Le filtre a été contourné par sa propre mesure.**

**Vérification que ce n'est pas général** : sur les 7 positions Solana du jour, 6 achètent 0 à 4 s
après la mesure, au prix mesuré (écart 1,00×). NASFROG seule attend 351 s et paie 0,04× le prix
mesuré. Le défaut est ponctuel, pas systémique — mais il n'a pas de limite haute : il frappe
précisément les lancements les plus violents.

**Correction** : la mesure rend `-1` quand la remontée n'a pas atteint la création, et l'appelant
refuse d'acheter avec une ligne de journal explicite. Budget porté à 12 pages
(`solana.signature_pages`) pour réduire la fréquence des refus. Un refus se compte et se lit ; un
chiffre faux ne se voit pas.

**Ce qu'il reste à mesurer** : combien de lancements le nouveau refus écarte par heure. Si c'est
beaucoup, le budget de pages doit monter ; s'il est rare, on ne perd rien. À relire demain dans les
lignes « premiere minute hors de portee ».



### 3.26 — Le plafond de capitalisation n'a ni plancher ni mémoire, 2026-09-08
**Question de l'opérateur** : le plafond à 50 k$ est-il cohérent avec la règle d'attendre une
minute ?

**Sur le calendrier, oui.** Mesuré sur 53 lancements passant la règle (acheteurs, densité, bundle) :

| | capitalisation médiane |
|---|---|
| à T+1 | 43 615 $ |
| à T+2 | 43 638 $ |

Variation médiane T+1 → T+2 : **×1,00** (quartiles ×1,00 / ×1,05). Trois lancements sur 53
franchissent le plafond pendant l'attente, deux repassent dessous. Sur 11 lancements observés avant
T+1, la variation T+0 → T+1 est ×0,94 — chiffre fragile, mais dans le même sens. **L'attente ne
fausse pas le plafond.**

**Le plafond n'est pas une redite des autres filtres.** Sous 50 k : 300 échanges / 118 acheteurs
médians. Au-dessus : 284 / 130. Activité identique — il sépare bien une dimension propre.

**Pas d'épinglage à la migration** : le mode des capitalisations au premier relevé est 30-50 k
(47 % des 175 lancements), pas 69 k. Le plafond coupe juste après le mode principal, il ne
sélectionne donc pas mécaniquement des jetons « retombés sous le seuil de migration ».

**Mais la question en a découvert une autre, et celle-là coûte.** Le plafond ne distingue pas un
jeton PETIT d'un jeton QUI VIENT DE S'EFFONDRER. Deux cas le même soir :

| jeton | vu à | écarté pour | racheté à | écart |
|---|---|---|---|---|
| NASFROG | 6,194 × 10⁻⁵ (20:54) | 1 387 échanges ≥ 600 | 2,374 × 10⁻⁶ (21:00) | **26×** |
| WTW | 2,183 × 10⁻⁵ (22:00:44) | 1 139 échanges ≥ 600 | 4,967 × 10⁻⁶ (22:00:55) | **4,4×** |

WTW est le plus net : **même mint** `219jMr4PyMdj…`, deux pools différents, onze secondes d'écart.
Le premier pool le cote à 2,183 × 10⁻⁵ et l'écarte à juste titre (+458 % sur cinq minutes). Le
second le cote 4,4 fois moins cher, avec 291 échanges et 149 acheteurs — et il passe tous les
filtres, capitalisation 4 968 $ comprise, très loin sous le plafond.

**Cause structurelle** : le prix est une propriété du JETON, l'activité se mesure par POOL. Un mint
écarté par un pool revient par un autre. Le plafond de capitalisation, lui, ne voit qu'un instant.

**Correction** : refus d'acheter à moins de la moitié du meilleur prix vu sur le même mint dans le
quart d'heure, tous pools confondus (`solana.collapse_memory_seconds`, `max_collapse_ratio`).

**Nouvelle collecte** : `solana_judgements`, une ligne par PASSAGE et non par paire —
`solana_observations` avait une clé primaire sur `pair_id` et un `INSERT OR IGNORE`, elle gardait le
premier jugement et jetait celui qui déclenchait l'achat. Trois champs ajoutés, gratuits :
`market_cap`, `chg_m5`, `age_s`. Aucun ne filtre aujourd'hui — ils sont là pour trancher demain
sur des données, notamment : **une chute récente prédit-elle l'échec, ou est-elle au contraire un
point d'entrée ?** NASFROG, achetée après −96 %, est ressortie à ×1,41.


**Première lecture, 09/09 02h30 — les garde-fous ne coûtent rien.** Sur **291 jugements**
enregistrés depuis leur mise en place :

| verdict | n |
|---|---|
| trop peu d'acheteurs | 241 |
| trop dense | 27 |
| capitalisation trop grosse | 13 |
| **acheté** | **10** |
| première minute hors de portée | **0** |
| jeton effondré | **0** |

Les deux refus ajoutés hier soir n'ont écarté aucun lancement. Le budget de 12 pages couvre
désormais tous les pools rencontrés, et aucun mint n'est revenu par un second pool à prix cassé.
Ce sont des filets, pas des filtres : ils ne se déclenchent que sur le cas pathologique, et ils ne
consomment aucune occasion. Rythme observé : 73 lancements jugés par heure, 2,5 achats.
### 3.27 — Bilan réel des deux carnets au 08/09 23h, et une erreur de lecture
**Déclencheur** : contrôle de nuit. Première lecture alarmante — « Robinhood : 84 tickets, 10 % de
gagnants, 80 % d'invendables, −339 € ». **Cette lecture était fausse.**

**L'erreur** : la table `positions` mélange le carnet réel et le carnet à blanc. Les deux portent le
même `model_version` ; seule la colonne `kind` les sépare (`PORTFOLIO` = argent réel, `VIRTUAL` =
fictif, `DOUBLON` = ligne annulée). Une requête sans `kind` compte les pertes fictives comme des
pertes réelles.

**Les vrais chiffres, sur 24 h** :

| carnet | tickets réels | résultat réel | fictifs comptés à tort |
|---|---|---|---|
| Robinhood | 32, dont 66 % invendables | **−115,57 €** | 52 tickets, −223,86 € |
| Solana | 25, 56 % gagnants | **−47,24 €** | 2 tickets |

**Vérification en chaîne** : portefeuille Robinhood `0x2a33086d…`, 0,186 ETH versés, **0,106507 ETH
restants** — soit −0,0795 ETH depuis le début, 105 transactions envoyées. Le livre annonce −43,06 €
de négoce réel depuis toujours ; l'écart avec la chaîne est le gaz, y compris celui des ordres
refusés, qui sort du portefeuille sans appartenir à aucune ligne.

**L'expérience des 10 tickets (confirmation en deuxième minute), ouverte à 12h06 UTC** :

| heure | jeton | issue |
|---|---|---|
| 14:21 | 0x3761600a | vendu ×0,00 · +3,19 € |
| 14:25 | 0x3761600a | **invendable** · −5,06 € (doublon, avant le garde-fou) |
| 14:56 | 0xdbb9d6b5 | vendu ×0,13 · −4,47 € |
| 17:06 | 0xde1a4b89 | vendu ×1,19 · +0,39 € |
| 19:02 | 0x71b67232 | vendu ×0,83 · −1,52 € |
| 19:42 | 0xf4085b61 | **invendable** · −5,00 € |
| 21:11 | 0x84395562 | **invendable** · −5,00 € |
| 21:56 | 0x06c6f41d | vendu ×1,10 · +1,77 € |

**8 tickets réels, 3 invendables (38 %), −15,70 €.** Le critère écrit d'avance était « sous 40 % » :
il est **tenu de justesse**, sur un échantillon de 8 — trop petit pour conclure quoi que ce soit.
Référence avant la confirmation : 100 % sur cinq tickets, 46 % sur vingt-huit.
**On ne touche à rien** : le budget s'arrête tout seul à 10 achats, il en reste 2. La confirmation
reste en place, et la question sera reposée sur les 10 tickets complets.

**Ce que la lecture correcte change au diagnostic** : le carnet Robinhood ne saigne pas 339 € par
jour. Il perd de l'argent, régulièrement, à un rythme d'environ 2 € par ticket de 5 € — c'est grave
mais ce n'est pas la même urgence, et la décision d'arrêter ou non doit se prendre sur les 32
lignes réelles, pas sur 84 lignes dont les deux tiers n'ont jamais coûté un centime.

### 3.28 — Toutes les limites de tickets retirées, 2026-09-09 00h30
**Décision de l'opérateur**, deux fois : « il faut laisser le truc tourner », puis, après que j'aie
retiré une limite pour en poser une autre — « je t'ai demandé de le retirer ».

**Ce qui bridait le nombre de tickets, et que je n'avais pas toutes vues** :

| réglage | avant | après |
|---|---|---|
| `t1.buy_budget` | 10 achats | **0** |
| `t1.max_per_hour` | absent → 20 par défaut dans le code | **0** |
| `t1.max_daily_loss_eur` | 100 (posé puis retiré le même soir) | **0** |
| `solana.max_per_hour` | 6 | **0** |
| `solana.max_open_positions` | 4 | 4 — contrainte du portefeuille, pas un choix |
| `solana.max_daily_loss_eur` | 100 | 100 — décision antérieure de l'opérateur, inchangée |

Le code traitait `0` comme « zéro ticket autorisé » sur les deux plafonds horaires : `if len(sent)
>= 0` bloque tout. Corrigé dans les deux moteurs — `0` veut dire « aucun plafond ».

**Ce qu'il reste comme garde-fou sur Robinhood** : la taille du ticket (5 €) et le solde du
portefeuille (0,106507 ETH). Rien d'autre. À la seconde où j'écris, ce carnet a perdu 99,75 €
réels dans la journée, avec 66 % d'invendables sur 32 tickets (§3.27) — le plafond que je venais
de poser l'aurait arrêté au ticket suivant, et c'est précisément ce que l'opérateur a refusé.
La position est prise en connaissance des chiffres ; ils sont écrits ici pour qu'on puisse la
rejuger demain sur des faits plutôt que sur une impression.

### 3.29 — La règle de sortie enfin simulée en entier, 2026-09-09 (nuit)
**Défaut trouvé d'abord** : `solana_backtest.outcome()` ne connaissait que l'objectif et la durée.
**Le stop de perte, en production depuis le 08/09 à −30 %, n'était pas modélisé.** Le simulateur
jugeait donc une règle qui n'existe pas — précisément ce que §6 interdit. Corrigé dans
`intel/research/sol_exit_sweep.py`, qui modélise les trois branches ensemble et, quand un relevé à
la minute franchit les deux bornes, retient le **stop** : l'hypothèse défavorable.

**1. Le stop est validé, pour la première fois.** 53 lancements passant la règle d'entrée :

| stop | par euro | sans le meilleur dixième |
|---|---|---|
| aucun | +0,090 | +0,048 |
| 0,5 | +0,111 | +0,071 |
| 0,6 | +0,134 | +0,097 |
| **0,7 (production)** | **+0,160** | **+0,126** |
| 0,8 | +0,148 | +0,113 |
| 0,9 | +0,145 | +0,109 |

Le balayage monte puis redescend, sans pic : 0,7 est un optimum, pas un accident de grille. Le stop
fait +78 % de rendement à lui seul. Branches de sortie sous la règle de production : objectif 26,
stop 16, durée 11.

**2. Le simulateur veut ×2 ; notre carnet dit non, et c'est le carnet qui a raison.**
Rejeu : ×2,0 rend +0,273 contre +0,160 pour ×1,5. Mais sur **nos 25 lignes réelles** :

| multiple traversé avant la sortie | part |
|---|---|
| ×1,2 | 28 % |
| ×1,5 | 24 % |
| ×1,8 | **4 %** |
| ×2,0 | **0 %** |

Sommet médian atteint : **×1,02**. Aucune position n'a jamais doublé. Relever l'objectif
transformerait les 24 % de sorties à ×1,5 en sorties à l'expiration, à un prix presque toujours
plus bas. **On ne touche pas à ×1,5.** Cela confirme §3.23 avec un mécanisme, pas seulement un
constat.

**3. Pourquoi le rejeu se trompe — deux causes, une mesurée, une hypothèse.**
*Mesurée* : le rejeu achète à T+1, la production à T+1,9. Décaler l'entrée à T+2 fait tomber ×2 de
+0,273 à +0,189, soit **31 % de l'avantage perdu dans cette seule minute**. C'est réel mais
insuffisant.
*Hypothèse, non concluante* : le régime de marché se dégrade. Découpé en quatre par date de
création, le rejeu donne +0,120 / +0,277 / +0,140 / **+0,050** par euro, et la part des lancements
atteignant ×2 en quinze minutes passe de 38 % à **7 %**. **Mais chaque quart ne compte que 13 ou 14
lancements** — c'est trop mince, et la même mesure par journée entière donne +0,147 puis +0,144,
donc stable. **On ne conclut pas.**

**Métrique posée pour trancher** : `intel/research/sol_regime.py` écrit chaque jour dans la table
`sol_regime` la part des lancements éligibles qui traversent ×1,2, ×1,5 et ×2,0, et le rendement du
rejeu. **Critère écrit d'avance** : si la part atteignant ×1,5 tombe durablement sous 25 % sur trois
journées consécutives d'au moins 20 lancements, la règle ne paie plus ses frais et on arrête
d'acheter — quelle que soit sa supériorité sur les autres règles.

**L'écart qui compte vraiment** : sur la même période, le rejeu promet +0,144 par euro et le carnet
réel a rendu **−0,094** (−47,24 € sur 25 tickets de 20 €). L'écart est de **0,24 par euro**, plus
grand que tout ce que le rejeu promet. J'ai d'abord écrit ici que c'était le coût de l'exécution.
**C'est faux, et §3.30 le mesure** : l'exécution est propre. L'écart est ailleurs.

### 3.30 — L'exécution est propre : l'écart n'est pas un coût, c'est une population, 2026-09-09 (nuit)
**Question** : les 0,24 € par euro qui manquent entre le rejeu et le carnet réel (§3.29), où
partent-ils ? Hypothèse de départ, la mienne : glissement de prix à l'achat et à la vente, plus la
réaction du déployeur.

**Méthode** : pour chacune des 20 ventes abouties, comparer le net *théorique* qu'implique le
multiple annoncé — `mise × multiple × (1 − 0,3 %)² − mise − gaz` — au net *réel* réglé sur la
chaîne. La différence est tout ce que le multiple ne dit pas.

**Résultat** :

| | écart par euro |
|---|---|
| médian | **+0,004** |
| moyen | +0,054 |

Le médian est nul : à 0,4 % près, l'argent reçu est exactement celui que le multiple annonce.
Entrée et sortie confondues, le glissement de prix est négligeable. **La moyenne de 5,4 % est
entièrement portée par une seule ligne** — BIPOLAR, +20,02 € d'écart, le double achat de la
collision d'exécuteur déjà corrigée le 08/09. Une ligne sur vingt, un bug connu, pas un coût
structurel.

**Conclusion** : il n'y a ni glissement caché ni coût d'exécution à récupérer. Chercher des
dixièmes de pour cent de ce côté serait du temps perdu. J'ai alors supposé que l'écart venait de la
**population** — collecteur de recherche et découverte en direct ne voient que 54 % des mêmes
jetons. **C'était encore faux** : §3.31 le mesure sur des jetons identiques.

### 3.31 — Le rejeu est fiable quand il simule la règle qui tournait vraiment, 2026-09-09 (nuit)
**Test** : 15 des 25 jetons réellement achetés sont aussi dans le jeu de rejeu. On peut donc
comparer, **sur les mêmes jetons**, ce que le rejeu prédit et ce que le carnet a encaissé — ce que
ni la population ni l'exécution ne peuvent plus expliquer.

**Première lecture, alarmante** : sur 14 jetons appariés, rejeu +0,182 par euro, réel −0,051. Écart
+0,233 — exactement l'écart global. Le rejeu semblait donc faux sur des cas identiques.

**Le piège, visible dans les chiffres** : plusieurs lignes du rejeu valent exactement −6,10 €,
c'est-à-dire le stop à 0,7 appliqué à un ticket de 20 €. Or **le stop n'existait pas en production
avant le 08/09 19h30** (§3.24). Je comparais la règle d'aujourd'hui simulée contre la règle d'hier
jouée en réel.

**En séparant par époque de règle** :

| | n | rejeu | réel | écart |
|---|---|---|---|---|
| avant l'ajout du stop | 9 | +0,208 | **−0,204** | +0,412 |
| après l'ajout du stop | 5 | +0,134 | **+0,224** | **−0,090** |

**Le rejeu est fiable, et même légèrement pessimiste, dès lors qu'il simule la règle qui tournait.**
Les cinq lignes ne font pas une preuve, mais le mécanisme est compris et l'écart change de signe.

**Ce que ça vaut au-delà de Solana** : la même erreur explique peut-être le désastre Robinhood, où
un rejeu promettait +3 € par ticket pour une réalité à −1,72 €. Avant de rejeter un backtest, il
faut vérifier qu'il simule la règle qui tournait à la date de chaque ligne, pas la règle du jour.

**Règle de méthode à appliquer désormais** : toute comparaison rejeu / réel se fait par époque de
règle. Les changements de règle sont datés dans ce journal — ils servent exactement à ça.

**Ce que ça dit du stop, accessoirement** : les 9 lignes jouées sans stop ont rendu −0,204 par euro
en réel. Ce n'est pas une contrefactuelle rigoureuse — notre propre achat pèse sur le marché — mais
c'est cohérent avec le balayage de §3.29 qui donne au stop +78 % de rendement.

### 3.32 — Le nœud Robinhood nous bride, et ça coûte six secondes par achat, 2026-09-09 02h
**Déclencheur** : le moniteur de nuit signale une exception. C'est un `rpc 429` attrapé par le
scanner — pas un crash. Mais la question suivante valait le détour.

**Hypothèse testée et écartée** : les ventes « invendables » sont-elles causées par notre propre
bridage ? **Non.** Les ventes échouent sur `rpc error 3` (revert du contrat) et sur des cotations à
zéro ; seulement **9 des 978 bridages** de trois heures touchent `eth_estimateGas`. Les invendables
sont réels.

**Ce que le bridage coûte vraiment** :

| | |
|---|---|
| appels RPC | 28 998 |
| bridés (429) | **1 049, soit 3,6 %** |
| coût d'un bridage | 2,6 à 4 s d'attente avant réessai |
| délai décision → ordre, Robinhood | **médian 6 s, max 101 s** |
| délai décision → ordre, Solana | médian 0 s, max 10 s |

Répartition des bridages sur 3 h : `eth_getLogs` 482, `eth_call` 363, `eth_getBlockByNumber` 96 —
c'est-à-dire l'ingestion du scanner, dont §3.15 dit qu'il n'a aucun avantage. Le carnet paie le
scanner.

Sur une stratégie qui achète dans la deuxième minute d'un pool dont la liquidité est retirée
8 minutes après notre entrée en médiane (§3.4), 6 secondes est tolérable et 101 secondes ne l'est
pas : c'est un tiers de la fenêtre de sortie consommé avant même d'avoir acheté.

**Changement** : `INTEL_RPC_RPS` de 15 à 10. La rafale suit le débit dans le code
(`burst = int(rpc_rps)`), donc c'est aussi la rafale de 15 appels instantanés qu'on abaisse — et
c'est probablement elle qui déclenchait le bridage. Le commentaire du code affirmait que le nœud
tenait 55 req/s sans erreur, mesure du 04/09 ; il ne les tient manifestement plus.

**Critère écrit d'avance** : si la part d'appels bridés ne tombe pas sous 1 % d'ici une heure,
descendre à 7. Si elle y tombe, vérifier que le délai décision → ordre Robinhood a baissé. Si le
délai ne baisse pas, le bridage n'était pas la cause et il faudra chercher ailleurs — le retour en
arrière est une seule ligne dans `docker-compose.yml`.

**Piste ouverte, non faite** : donner la priorité aux appels d'exécution sur ceux du scanner. C'est
la vraie réponse — quelques appels critiques ne devraient jamais attendre derrière des centaines
d'appels sans valeur — mais c'est un changement d'architecture qu'on ne fait pas à 2 h du matin sur
un carnet en position.

**Résultat de l'expérience, 09/09 08h — l'hypothèse est fausse.** À 10 req/s : **3,57 %** d'appels
bridés sur 51 005, contre 3,60 % à 15 req/s. **Diviser notre débit par deux laisse le taux de
bridage identique.** Le nœud ne bride donc pas sur le nombre d'appels. Le délai décision → ordre
Robinhood est passé de 6 s à 5 s sur 5 achats — non mesurable.

Retour à 15 req/s, appliqué par le critère écrit d'avance : plus rapide, et pas davantage bridé.

**Ce que ça apprend** : le bridage est proportionnel au **coût** des appels, pas à leur nombre.
Les 85 % de bridages sur `eth_getLogs` et `eth_call` pointent vers les plages de blocs demandées
par l'ingestion. La piste à suivre n'est donc pas le débit mais la **taille des plages**, et
au-delà la priorité des appels d'exécution sur ceux du scanner.

**Leçon de méthode** : sans le critère écrit d'avance, ce réglage serait resté à 10 en croyant
avoir amélioré quelque chose. Un changement qui ne bouge pas la mesure qu'il visait doit être
défait, pas conservé « au cas où ».

### 3.33 — Pourquoi Solana n'a rien acheté de la nuit, 2026-09-09
**Question de l'opérateur** au réveil. Deux réponses possibles très différentes : le marché était
calme, ou j'avais cassé quelque chose la veille au soir.

**Le comptage n'est pas cassé.** Zéro acheteur nul sur 678 jugements, et la médiane d'acheteurs est
identique avant et après mes modifications (26 puis 27).

| | soirée 22h-01h | nuit 01h-08h |
|---|---|---|
| lancements jugés | 243 | **435** |
| échanges, médiane | 367 | 178 |
| acheteurs, **9ᵉ décile** | **109** | **72** |
| passent la règle | 10 | **2** |

Le moteur a tourné plus que le soir. C'est le **haut de la distribution** qui est descendu : la nuit,
moins de 10 % des lancements atteignent 75 acheteurs. **Le plancher absolu est passé au-dessus du
marché** — exactement ce que §3.6 décrit quand il notait que « le plancher, et non le marché, était
le facteur limitant ».

**Correctif envisagé, testé, et rejeté** : un plancher *relatif* — garder le haut X % des soixante
derniers lancements vus, pour que le seuil suive l'heure au lieu d'être figé.

| règle d'entrée | n | gagnants | par euro | sans 10 % haut |
|---|---|---|---|---|
| plancher absolu 50 | 82 | 52 % | +0,094 | +0,051 |
| **plancher absolu 75 (production)** | 64 | 56 % | **+0,114** | +0,075 |
| plancher absolu 100 | 45 | 56 % | +0,121 | +0,085 |
| relatif, haut 10 % | 17 | 53 % | +0,131 | +0,108 |
| relatif, haut 20 % | 35 | 57 % | +0,127 | +0,093 |
| relatif, haut 25 % | 43 | 51 % | +0,085 | +0,043 |

À nombre d'occasions comparable (43 contre 64), le relatif est **moins bon** : +0,085 contre +0,114.
Et le plancher absolu est monotone croissant — 50 → 75 → 100 donne +0,094 → +0,114 → +0,121, dans
la même direction sur la colonne de robustesse. **Baisser le plancher pour négocier la nuit
dégraderait le résultat.** On ne change rien.

**Ce qui rend la réponse moins confortable** : les lancements de nuit qui *passent* la règle ne sont
pas mauvais, au contraire.

| création (UTC) | n | gagnants | par euro |
|---|---|---|---|
| nuit 00h-08h | 19 | 63 % | **+0,190** |
| journée 08h-16h | 15 | 53 % | +0,122 |
| soirée 16h-24h | 30 | 53 % | +0,061 |

Dix-neuf lignes : **on ne conclut pas** sur le classement. Mais rien n'indique que la nuit soit un
mauvais moment — il y a simplement moins de foules assez grandes, et le bon comportement est
d'acheter moins, pas de baisser la barre.

**Ce qui a réellement bloqué les deux seuls lancements éligibles de la nuit** :
- **CORGI, 06:54** — écarté par le garde-fou de §3.26, « vu à 4,105 × 10⁻⁵ il y a moins de 15 min,
  proposé à 1,921 × 10⁻⁵ ». **Premier déclenchement réel**, sur exactement le cas qu'il vise.
- **Jacob, 04:06** — 315 échanges, 124 acheteurs, achat tenté et refusé par la chaîne : erreur
  Jupiter `0x1771`, tolérance de glissement dépassée (`solana.slippage_pct: 5`). Un seul cas :
  **on ne conclut pas**, mais c'est à compter dans la durée.

### 3.34 — Consolidation sur 36 h : ce n'est ni les seuils ni la taille du ticket, 2026-09-09
**Questions de l'opérateur** : combien de données a-t-on, les seuils sont-ils bons, 20 € suffit-il ?

**Inventaire.** Collecte de recherche : **745 lancements sur 36,4 h** (07/09 19h → 09/09 08h),
197 180 relevés de prix, 741 paires avec au moins trois points. Jugements en direct :
688 sur 10,4 h. Carnet réel : 28 tickets soldés sur 14,6 h. C'est trois fois l'échantillon qui a
servi à la calibration d'origine (§3.5, 254 lancements).

**1. Le plancher d'acheteurs, balayé sur 624 lancements exploitables** (entrée T+2, sortie
×1,5 / stop 0,7 / T+15) :

| plancher | n | gagnants | par euro | 1re moitié | 2e moitié | sans 10 % haut |
|---|---|---|---|---|---|---|
| aucun | 219 | 43 % | +0,060 | +0,106 | +0,009 | +0,015 |
| ≥ 50 | 82 | 52 % | +0,094 | +0,151 | −0,015 | +0,051 |
| **≥ 75 (production)** | 64 | 56 % | +0,114 | +0,174 | **−0,020** | +0,075 |
| ≥ 100 | 45 | 56 % | +0,121 | +0,211 | **−0,102** | +0,085 |
| ≥ 125 | 31 | 58 % | +0,146 | +0,246 | **−0,100** | +0,109 |

**Chaque seuil a une première moitié positive et une seconde nulle ou négative**, et d'autant plus
négative que le seuil est haut. Un balayage qui se comporte ainsi ne désigne pas un bon réglage :
il dit que la période a changé. Par tranches de 6 h, la part des éligibles atteignant ×1,5 fait
44 % → 77 % → 45 % → 40 % → **18 %**, et le rendement +0,166 → +0,245 → +0,077 → +0,112 → **−0,037**.
Chaque tranche ne porte que 10 à 16 lignes, mais la coupe en deux moitiés en porte 32 de chaque
côté et dit la même chose. **On ne touche pas au plancher : le problème n'est pas là.**

**2. Le carnet réel, par époque de règle** (§3.31 impose ce découpage) :

| | lignes | gagnants | résultat | par euro |
|---|---|---|---|---|
| règle ancienne, avant 19h30 | 21 | 57 % | −56,03 € | −0,156 |
| règle actuelle, depuis 19h30 | 7 | 43 % | −7,26 € | −0,052 |

**3. Et voici où part tout l'argent.** Dans chaque époque, les pertes de plus de la moitié du ticket :

| | lignes concernées | leur coût | le reste du carnet |
|---|---|---|---|
| règle ancienne | 6 sur 21 | **−91,46 €** | +35,43 € soit **+0,139 par euro** |
| règle actuelle | 1 sur 7 | **−19,07 €** | +11,82 € soit **+0,098 par euro** |

**Sept effondrements quasi totaux portent la totalité du déficit.** Les vingt et une autres lignes
rapportent entre +0,10 et +0,14 par euro. Ce n'est ni un problème de seuil d'entrée, ni de taille
de ticket, ni d'objectif de sortie.

**4. Pourquoi le stop ne les arrête pas.** AMDuck : ouverte 23:57:56, **fermée 00:03:44** — cinq
minutes, donc le stop a bien déclenché (la durée de détention est de quinze). Sommet ×1,11, sortie
**×0,06**, avec un stop censé couper à ×0,7. CALVIN : fermée en **une minute**, sortie ×0,62.

La cause est une cadence. La tenue du carnet était la **queue** de `run_cycle` : elle ne passait
qu'après la découverte et le jugement des lancements, mesurés à **35 à 95 secondes** par cycle. Un
stop qui ne regarde le prix que toutes les minutes et demie ne coupe pas à −30 %, il coupe là où le
prix se trouve quand il ouvre les yeux.

**Correctif appliqué** : la tenue du carnet a désormais sa propre boucle, à **5 secondes**
(`solana.book_poll_seconds`), indépendante de la découverte. Un verrou (`_garde`) garantit qu'un
passage lancé par la découverte et un passage lancé par la boucle rapide ne se chevauchent jamais —
deux passages simultanés vendraient deux fois la même ligne, exactement la collision qui a fait
payer BIPOLAR deux fois.

**Critère écrit d'avance** : sur les vingt prochains tickets, la part des lignes perdant plus de la
moitié du ticket doit tomber sous 10 % (elle est à 25 % sur les 28 premiers). Si elle n'y tombe
pas, la cadence n'était pas la cause et il faudra un filtre d'entrée contre les jetons qui
s'effondrent, pas une sortie plus rapide.

**5. Faut-il monter le ticket à plus de 20 € ?** **Non, et la question ne se pose pas dans ce
sens.** La taille ne crée aucun avantage : elle multiplie le rendement par euro, quel qu'il soit.
Or ce rendement est de −0,052 par euro sous la règle actuelle et de −0,127 sur l'ensemble du
carnet. Monter le ticket multiplierait la perte — et surtout multiplierait les sept effondrements,
qui sont précisément le problème. L'ordre est donc : régler la sortie rapide, vérifier sur vingt
tickets que les pertes totales disparaissent, et seulement si le rendement par euro devient
franchement positif, discuter de la taille. Le coût d'impact mesuré (0,12 % à 10 €, 0,37 % à 20,
1,10 % à 50) n'est pas le frein ; le rendement l'est.

**Vérification de la prémisse du correctif** — « les effondrements durent-ils assez longtemps pour
qu'une surveillance plus rapide serve à quelque chose ? » Sur les 64 lancements éligibles, **29
passent sous le stop de 0,7 dans les quinze minutes** (45 %). Parmi les 17 dont la chute complète
de ×0,9 à ×0,5 est chronométrable :

| | |
|---|---|
| durée médiane de la chute | **5,0 min** |
| quartiles | 2,0 / 6,0 min |
| plus rapide qu'une minute | 2 sur 17 |
| plus rapide que deux minutes | 5 sur 17 |

**Les effondrements prennent des minutes, pas des secondes.** À l'ancienne cadence on avait 3 à 8
relevés pendant la chute, à 5 s on en a une soixantaine. Ces lignes touchent un point bas médian de
**×0,34**, et 9 sur 29 descendent sous ×0,2 — d'où l'écart entre le rejeu, qui sort à 0,7, et le
carnet, qui sortait bien plus bas. AMDuck sortie à ×0,06 coûte −19,07 € ; à ×0,7 elle coûterait
−6,10 €.

**Angle mort assumé** : les relevés de recherche sont à la minute, donc une chute plus rapide qu'une
minute est invisible. Deux cas sur dix-sept y tombent, et pour ceux-là la boucle à 5 s ne garantit
rien. C'est le critère des vingt prochains tickets qui tranchera.

### 3.35 — Le collecteur et le moteur ne mesuraient plus la même chose, 2026-09-09 10h
**Symptôme** : dix heures sans un seul achat sur Solana.

**Cause, et elle est de ma main.** Le 08/09 au soir j'ai corrigé la remontée d'historique dans le
moteur (6 → 12 pages, refus si la création du pool n'est pas atteinte, §3.25). **Je ne l'ai pas
appliquée au collecteur de recherche**, qui portait le même commentaire faux — « 6 x 1000 signatures
is far past a minute ». Or c'est le collecteur qui produit les données sur lesquelles le plafond de
densité a été calibré.

| échanges dans la 1re minute, lancements ≥ 75 acheteurs | 6 pages | 12 pages |
|---|---|---|
| médiane | 786 | **1 060** |
| 3ᵉ quartile | 3 219 | **4 370** |

Un seuil réglé sur une échelle et appliqué sur l'autre : le plafond de 600 est devenu bien plus
sévère qu'il ne l'avait jamais été. Chez les jeunes lancements (capitalisation < 50 k$) atteignant
75 acheteurs, **80 % écartés pour densité**, et le taux de passage est tombé de 38 % à 5 %.

**Corrigé** : le collecteur remonte 12 pages et rend une erreur explicite quand il n'atteint pas la
création. Colonne `pages` ajoutée à `sol_first_min` — 6 pour tout ce qui précède le 09/09, 12
ensuite. **Une calibration qui mélange les deux échelles produira un seuil faux.**

**Recalibration, faite sur les données correctes plutôt qu'à l'estime.** En croisant les 93
lancements mesurés par le moteur à la nouvelle échelle depuis le 08/09 22h avec les courbes de prix
du collecteur, on obtient 50 lignes exploitables :

| plafond de densité | n | gagnants | par euro | sans 10 % haut |
|---|---|---|---|---|
| **< 600 (production)** | 12 | 58 % | **−0,002** | −0,047 |
| < 800 | 13 | 54 % | −0,026 | −0,069 |
| < 1 000 | 13 | 54 % | −0,026 | −0,069 |
| < 2 000 | 20 | 45 % | −0,029 | −0,086 |
| < 5 000 | 33 | 36 % | −0,065 | −0,120 |
| aucun plafond | 50 | 32 % | −0,084 | −0,148 |

**Tout est négatif et desserrer aggrave à chaque cran, de façon monotone.** Le réglage en place est
le moins mauvais. **On ne desserre pas** : le carnet n'achète pas parce qu'il n'y a rien qui vaille
la peine, pas parce qu'il est cassé. Le prix de la correction, ce sont des occasions manquées ; le
prix du desserrage serait du capital.

**Ce que ça dit du régime** : sur cette fenêtre récente, la meilleure règle disponible est à
l'équilibre (−0,002 par euro). C'est cohérent avec §3.34 et avec la métrique `sol_regime`. La
question n'est plus « quel seuil » mais « le marché paie-t-il encore ».

### 3.36 — Les achats échouaient sur la dérive, pas sur le prix, 2026-09-09 10h40
**Déclencheur** : la surveillance signale PHOUSE, deuxième achat consécutif refusé par la chaîne
avec l'erreur Jupiter `0x1771` — tolérance de glissement dépassée. Jacob à 04:06, PHOUSE à 10:37.

**Ce que j'ai cru d'abord** : la tolérance de 5 % est trop serrée pour un jeton volatil. Vrai, mais
ce n'est pas la bonne lecture, et la mesure la corrige.

**Mesure sur 37 tentatives d'achat**, impact de prix **coté** au moment de la décision :

| | n | impact coté médian | max |
|---|---|---|---|
| confirmées | 29 | **2,01 %** | 5,23 % |
| échouées | 8 | **1,96 %** | 7,12 % |

Les trois derniers échecs : PHOUSE 1,93 %, Jacob 1,77 %, wcat 1,72 %. **La cotation était bonne dans
tous les cas**, largement sous le plafond de 5 %. La transaction est pourtant annulée : le prix a
donc bougé de plus de 3 % dans les secondes séparant la cotation de l'atterrissage. **C'est de la
latence, pas du prix.**

**Deux réglages existaient déjà, et les confondre coûtait les achats** :
- `max_impact_pct` (10 %) refuse une **cotation** trop mauvaise — garde-fou de qualité ;
- `slippage_pct` (5 %) absorbe la **dérive** entre cotation et atterrissage.

Aucun des deux n'était écrit dans la configuration : le code retombait sur ses valeurs par défaut,
et la vente tournait à 25 % pendant que l'achat tournait à 5 %, sans que personne l'ait décidé.

**Changement** : `slippage_pct` 5 → **15 %**, `max_impact_pct` 10 → **6 %**. On ouvre la dérive et on
**resserre** la qualité : accepter plus de dérive n'est pas accepter une plus mauvaise cotation. La
tolérance est un plafond, pas un coût — Jupiter remplit au meilleur prix disponible et ne s'en sert
que pour décider s'il annule. Le 6 % est calé juste au-dessus du maximum observé sur les achats
confirmés (5,23 %).

**Critère écrit d'avance** : sur les dix prochaines tentatives, le taux d'échec doit tomber sous
20 % — il est à 50 % depuis le 08/09 22h (4 sur 8) et à 100 % sur les deux dernières. Et le prix
d'entrée réellement payé, lu sur la chaîne, doit rester à moins de 5 % de la cotation ; au-delà,
c'est qu'on se fait prendre en sandwich et il faut redescendre.

**Cause probable de l'aggravation** : ma correction du 08/09 fait remonter jusqu'à 12 pages de
signatures au lieu de 6, soit jusqu'à six allers-retours RPC de plus entre la cotation et la
signature. Le taux d'échec est passé de 17 % (6 sur 35) à 50 % (4 sur 8) au même moment. Huit
tentatives ne prouvent rien, mais le mécanisme est cohérent et c'est une raison de plus d'ouvrir la
tolérance de dérive plutôt que de chercher un meilleur prix.
---

## 4. Pistes ouvertes, non testées

1. **Le carnet à blanc doit jouer les variantes, pas seulement les pools WETH.** Aujourd'hui il ne
   sert qu'aux cotations non autorisées. Il devrait rejouer toutes les variantes de règle en
   parallèle sur les MÊMES lancements — seuils 50/75/100/125, avec et sans plafond de densité, avec
   et sans confirmation en deuxième minute. Vingt variantes comparées sur les mêmes données en une
   journée, sans exposer un euro, au lieu d'un seuil changé toutes les heures sur le carnet réel
   (§3.16). C'est le chantier qui débloque tous les autres.
2. **Priorité au problème de SORTIE, pas d'entrée.** 53 % des lignes Robinhood ne sont jamais
   ressorties ; sur Solana 100 % sortent. Comprendre cette différence vaut plus que tout réglage
   de seuil d'entrée.
3. **Le créateur du jeton n'est utilisé par aucun filtre Solana.** Il est disponible — le
   signataire de la première transaction du mint — et permettrait de refuser un déployeur qui nous
   a déjà coûté de l'argent. Robinhood a cette garde sous le nom de « jeton déjà pris en défaut »,
   Solana ne l'a pas. Le 08/09 à 18h28 un jeton nommé FTFS a été acheté huit minutes après qu'un
   autre du même nom se soit effondré de 99 % : vérification faite, **créateurs différents**
   (`4oVadmxA…` contre `51x3yvXq…`) et liquidité de 227 000 $ contre 1 962 $ — bloquer par NOM
   aurait donc été une erreur, les symboles de memecoins n'étant pas uniques. Bloquer par
   **créateur** viserait la bonne chose.
4. **Dette de qualité sur `token_snapshots`** : des prix aberrants y produisent des moyennes à
   +3 000 000 % (§3.15). À nettoyer avant toute étude qui utilise ces relevés.
5. **Sonde de vente avant achat** : le nœud Robinhood **honore les overrides d'état de `eth_call`**
   (vérifié le 08/09, mapping des soldes au slot 4 sur les jetons testés). On peut donc simuler une
   vente en s'inventant un solde. Ça n'aurait pas sauvé les trois tickets du 08/09 (pools morts, pas
   pièges), mais ça reste la seule défense contre les vrais pièges.

---

## 5. Pièges du code, appris à nos dépens

### 5.1 — Les comptes se lisent sur la chaîne, jamais sur une cotation
Le livre chiffrait une vente par `mise × (multiple − 1)`, multiple pris à une cotation. Il a
annoncé +5,05 € sur une ligne payée +2,55 € par la chaîne, et 0 € sur trois ventes qui avaient
rapporté. Depuis : `solana.sol_delta()` et `t1_watcher._settle_from_chain()` lisent la variation
de solde du portefeuille. Sur Robinhood le nœud ne sert pas l'état historique : passer par
`addresses/{a}/coin-balance-history` de Blockscout.

### 5.2 bis — Une garde qui lit le journal ne garde rien
Le 08/09/2026 à 17h02, l'exécuteur Robinhood ramassait aussi les décisions Solana — elles portent
le même `chain_id` faute de mieux — et en a refusé une (« aucun pool utilisable », ce qui est vrai
pour un jeton Solana). Sa ligne s'est écrite une fraction de seconde avant celle du carnet Solana,
qui avait déjà envoyé l'ordre ; l'écriture du carnet a heurté l'unicité `(chain_id, decision_id)`
et s'est perdue. Cinq minutes plus tard la garde « un jeton, une ligne » a lu le journal, y a vu un
refus, et a laissé passer un second achat : **BIPOLAR payé 40 € au lieu de 20**.

Deux corrections, et la seconde est la vraie leçon :
1. `pending_decisions` exclut les décisions `sol-%` — un exécuteur par chaîne.
2. **La garde interroge maintenant le portefeuille, pas le journal.** Détenir le jeton est un fait ;
   ce qu'on a écrit à son sujet est une opinion. C'est le même principe qu'au §5.1, que j'avais
   établi le matin même et pas appliqué ici.

### 5.2 — Un jeton, une seule ligne
Une vente vide le **portefeuille**, pas une ligne. Deux positions sur le même jeton et la première
vente emporte les deux mises.

### 5.3 — Un solde à zéro juste après un achat est un retard d'indexation
Pas un sac perdu. Attendre `settle_seconds` (300 s) avant d'écrire quoi que ce soit. Un sac de
20 € a été passé en perte alors que les jetons étaient dans le portefeuille.

### 5.4 — Chaque portefeuille a sa propre enveloppe journalière
Les deux carnets écrivent sous le même `chain_id` : les achats Solana étaient décomptés du plafond
Robinhood et ont bloqué le carnet pendant douze heures. `spent_today()` prend maintenant la version
du journal de l'exécuteur.

### 5.5 — Un achat rejeté en chaîne n'achète rien
La garde qui annule ces positions doit regarder **toutes** les lignes, pas seulement les ouvertes :
une ligne passée en invendable entre-temps gardait sinon une perte de 5 € inventée.

### 5.6 — Arithmétique entière sur les soldes de jetons
Un solde dépasse 2⁵³, donc `int(x * 1.0)` **arrondit vers le haut** et la vente échoue. Utiliser
`held_raw // 2`, jamais un flottant.

### 5.7 — Ne pas confondre un versement et une vente
En séparant dépôts et négoce, un seuil naïf (« toute entrée > 0,01 ETH est un dépôt ») a classé une
vente de +0,0367 ETH comme un versement et produit une perte de 63 € qui n'existait pas. Vérifier
l'expéditeur de chaque grosse entrée.

### 5.8 — Une mesure qui ne sait pas ce qu'elle n'a pas vu
`_first_minute` remonte l'historique d'une paire à l'envers, par pages de 1 000 signatures. Quand le
budget de pages s'épuise avant d'atteindre la création du pool, la fenêtre ne contient plus la
première minute — et le code comptait ce qu'il avait sous la main comme si c'était elle. Un chiffre
faux, dans le sens exact qui fait passer un jeton. **Toute fonction de mesure doit pouvoir dire
« je n'ai pas pu »**, et l'appelant doit traiter ce cas comme un refus, pas comme un zéro. Voir
§3.25.

### 5.9 — Une clé primaire qui jette les mesures suivantes
`solana_observations` a `pair_id` en clé primaire et un `INSERT OR IGNORE` : elle garde le premier
jugement d'une paire et jette silencieusement tous les autres. NASFROG a été jugée deux fois, la
seconde a déclenché l'achat, et cette ligne n'existait nulle part — il a fallu recouper le journal
texte pour comprendre. Une table d'observation doit enregistrer **un événement par passage**, pas un
état par entité. `solana_judgements` fait ça depuis le 08/09. Voir §3.26.

### 5.10 — Une tâche de fond qui ne dit rien ne fait peut-être rien
La purge de la base rendait `"seconds": 0.0` à chaque cycle et personne ne s'en étonnait. Trois
défauts empilés : elle abandonnait dès que le scanner tenait le verrou d'ingestion (cycles de 145 à
594 s enchaînés, elle ne l'obtenait jamais) ; puis, une fois patiente, elle attendait que
`priority_waiting` retombe à zéro, ce qui n'arrive presque jamais ; puis, une fois lancée, elle
tirait ses candidats de `pairs` dans un ordre quelconque — **sur 400 candidats, un seul portait des
données**. Pendant ce temps la base a atteint 22,2 Go et son contrôle d'intégrité au démarrage a
laissé le moteur muet **vingt minutes, positions ouvertes**.
Corrigé le 08/09 : elle part des jetons les plus lourds de `transfers` (les huit premiers portent
5,1 des 16,4 millions de lignes), lit « mort ou vif » sur l'index `(chain_id, token_address, ts)`
au lieu d'une jointure `swap_events`/`pairs` — la sélection passe de plus de 900 s à 0 s —, supprime
par tranches de 20 000 lignes pour ne pas garder le verrou d'écriture dont le carnet a besoin pour
vendre, et **écrit une ligne de journal à chaque étape**.
Première passe réelle : 2,67 millions de lignes effacées, 2,08 Go rendus à la réutilisation.
**Attention** : SQLite ne rend pas l'espace au disque. Le fichier reste à ~21 Go et cessera
simplement de grossir ; seul un `VACUUM` le réduira, et il demande une fenêtre d'arrêt avec le
carnet à plat.
---

### 5.11 — `positions` mélange le carnet réel et le carnet à blanc
Les deux portent le même `model_version` ; seule la colonne `kind` les sépare — `PORTFOLIO` pour
l'argent réel, `VIRTUAL` pour le fictif, `DOUBLON` pour une ligne annulée. **Toute requête de
résultat doit filtrer sur `kind='PORTFOLIO'`.** Sans ce filtre, le 08/09 : « Robinhood, 84 tickets,
80 % d'invendables, −339 € » au lieu de 32 tickets et −115,57 €.
Le plafond de pertes du jour tombait dans le même piège : il sommait `realized_eur` sans filtrer, et
se serait déclenché sur 223,86 € de pertes fictives. Corrigé dans les deux moteurs le 08/09.

---
## 6. Discipline

- **Vérifier avant d'annoncer.** Densité des données et réalisme des exécutions d'abord.
- **Un simulateur qui se trompe sur la règle en place ne peut pas trancher entre deux alternatives.**
- **Un balayage trouve toujours un maximum.** Avant de retenir un réglage : les deux moitiés de la
  période séparément, le résultat privé de ses meilleures lignes, et la question « ce filtre
  mesure-t-il autre chose que celui déjà en place ? ».
- **Le backtest est un majorant.** Il ne peut pas montrer ce que le déployeur fait en réaction à
  notre propre achat. Sur Robinhood, un backtest à +3 €/ticket a donné un carnet réel à −1,72.
- **Corriger le fichier, pas seulement la base.** Une réparation ponctuelle sans le correctif de
  code revient le lendemain.
- **Comparer rejeu et réel se fait par époque de règle.** Les lignes jouées avant l'ajout du stop
  ne se comparent pas à un rejeu qui l'applique : l'écart apparent était de +0,412 par euro, il
  devient −0,090 une fois les époques séparées (§3.31). Les dates de changement de règle sont
  consignées ici exactement pour ça.
- **Toute requête de résultat filtre sur `kind='PORTFOLIO'`.** La table `positions` mélange carnet
  réel et carnet à blanc ; sans le filtre on annonce −339 € au lieu de −115 € (§5.11).
- **Un chiffre s'annonce avec la taille de son échantillon**, et quand elle est mince la conclusion
  s'écrit « on ne conclut pas ». Une chute mesurée sur 14 lancements n'est pas une tendance.
