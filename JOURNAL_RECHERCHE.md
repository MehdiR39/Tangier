# Journal de recherche — Tangier Intel

**À lire au début de chaque séance, et à compléter à la fin.** Ce fichier est la mémoire du
projet : ce qui tourne, ce qui a été mesuré, ce qui a échoué et pourquoi. Sans lui on refait les
mêmes tests et on répète les mêmes erreurs.

Règle d'écriture : **un chiffre sans sa méthode ne vaut rien.** Chaque entrée dit la question, la
donnée, le résultat, et la conclusion qu'on en tire — y compris quand la conclusion est « on ne
sait pas ».

Dernière mise à jour : 2026-09-08.

---

## 1. Le système en une page

Deux carnets automatiques qui achètent des jetons dans leur première minute de vie et les revendent
quelques minutes plus tard.

| | Robinhood Chain | Solana |
|---|---|---|
| Découverte | logs `Initialize` d'Uniswap v4 | DexScreener **+ flux de migrations en direct** (§3.21) |
| Règle d'entrée | 27 à 60 échanges dans la 1re minute **puis ≥ 30 échanges dans la 2e** (§3.10) | ≥ 75 acheteurs distincts, **< 600 échanges**, ≤ 15 échanges/acheteur, hors pump.fun (§3.6, §3.13) |
| Sortie | ×2 ou T+5 min | **×1,5** ou T+15 min (§3.23) |
| Ticket | 5 € | 20 € |
| Portefeuille | `0x2a33086d2fce255f61ac1a3000bf944397c9c908` | `HY4wrwepxv3JCMox1LG7K46Bj6TnP1xMHSk42ojEZfyL` |
| État au 08/09 18h00 | actif, expérience bornée à 10 tickets | actif, 4 positions max, budget 20 tickets |

**Expériences en cours** — chacune a un critère écrit d'avance :

- **Robinhood, 10 tickets de 5 €** : la confirmation en deuxième minute fait-elle tomber le taux
  d'invendables sous 40 % ? Référence : 100 % sur les cinq derniers tickets, 46 % sur les
  vingt-huit précédents. Bascule d'annulation : `t1.confirm_minute2: 0`.
- **Solana, 20 tickets de 20 €** : le plancher de 75 acheteurs tient-il ce que le backtest promet
  (+0,36 par euro, 69 % de gagnants) ? Référence : −18,16 € réels sur les cinq tickets sans
  plancher. Bascule d'annulation : `solana.min_buyers: 5`.

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
3. **Dette de qualité sur `token_snapshots`** : des prix aberrants y produisent des moyennes à
   +3 000 000 % (§3.15). À nettoyer avant toute étude qui utilise ces relevés.
4. **Sonde de vente avant achat** : le nœud Robinhood **honore les overrides d'état de `eth_call`**
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
