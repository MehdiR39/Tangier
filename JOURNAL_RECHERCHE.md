# Journal de recherche — Tangier Intel
- **Une sortie simulée se confirme sur deux relevés consécutifs.** 7 % des écarts entre deux points
  de prix dépassent 20 % ; un pic isolé crée un objectif atteint qui n'a jamais existé. C'est ce
  qui a fait annoncer +2,995 € par ticket pour un signal qui valait −0,292 (§3.54).

**À lire au début de chaque séance, et à compléter à la fin.** Ce fichier est la mémoire du
projet : ce qui tourne, ce qui a été mesuré, ce qui a échoué et pourquoi. Sans lui on refait les
mêmes tests et on répète les mêmes erreurs.

Règle d'écriture : **un chiffre sans sa méthode ne vaut rien.** Chaque entrée dit la question, la
donnée, le résultat, et la conclusion qu'on en tire — y compris quand la conclusion est « on ne
sait pas ».

Dernière mise à jour : 2026-09-14.

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
| État au 09/09 11h50 | **EN PAUSE** — critère d'arrêt atteint (50 % d'invendables contre 40 % écrits d'avance), −0,702 par euro sur 24 h. Carnet à blanc actif, ventes en cours poursuivies | actif, 4 positions max (contrainte du portefeuille), **aucun plafond horaire**, coupure à 100 € de pertes **réelles** par jour |

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

### 3.37 — La mémoire « déjà jugé » ne survivait pas au redémarrage, 2026-09-09 10h45
**Déclencheur** : PHOUSE, deux achats refusés à quatre minutes d'intervalle. En cherchant pourquoi
la chaîne refusait, j'ai trouvé bien pire — **pourquoi on essayait d'acheter.**

| | 10:37:38 | 10:41:45 |
|---|---|---|
| pool | `Bqux4KF1Mt…` | **le même** |
| prix | 3,953 × 10⁻⁵ | **1,107 × 10⁻⁵** (−72 %) |
| mesure | 317 échanges, 109 acheteurs | **exactement la même** |
| verdict | acheté | acheté |

Le moteur garde en mémoire les pools déjà jugés (`self.judged`), pour ne juger un lancement qu'une
fois. **Cette mémoire est en RAM.** J'avais redémarré le conteneur à 10:40 pour appliquer un
réglage : le redémarrage l'a vidée, et le même pool a été rejugé comme s'il était neuf, à 72 % de
son prix, avec la même mesure de première minute.

**C'est le troisième visage du même défaut.** NASFROG (§3.25) revenait par une mesure tronquée, WTW
(§3.26) par un second pool du même jeton, PHOUSE par un redémarrage. À chaque fois la règle « T+1 »
se transforme en « acheter ce qui vient de s'effondrer ». Et j'ai redémarré ce conteneur une
douzaine de fois en deux jours.

**Deux corrections** :
1. La mémoire est lue dans `solana_judgements`, qui est persistante : un pool jugé dans les six
   dernières heures n'est jamais rejugé, quel que soit le nombre de redémarrages.
2. Le garde-fou « jeton effondré » ne s'applique plus seulement aux **autres** pools du même jeton
   mais aussi au **même** pool. La première version excluait le pool courant en supposant qu'il ne
   pouvait pas être jugé deux fois — supposition fausse dès qu'on redémarre.

**Ce que ça change pour §3.36.** J'y avais attribué les refus de la chaîne à la latence et ouvert la
tolérance de dérive de 5 à 15 %. La mesure qui la justifiait tient toujours — cotation à 1,7-2 %,
transaction annulée, donc le prix bouge de plus de 3 % entre la cotation et l'atterrissage. Mais
l'**urgence** était mal attribuée : ces transactions portaient sur un jeton en train de s'effondrer,
qu'on n'aurait pas dû chercher à acheter. Le refus de la chaîne nous protégeait. Le réglage à 15 %
reste en place avec son critère écrit, mais il n'est plus le sujet.

**Leçon de méthode** : un état en mémoire qui garantit « une seule fois » n'en garantit rien dès que
le processus peut redémarrer — et sur un système qu'on corrige plusieurs fois par jour, il redémarre
souvent. Tout garde-fou d'unicité doit s'appuyer sur la base, pas sur la RAM.

### 3.38 — La règle achetait dans la pire tranche : ajout d'un plancher, 2026-09-09 11h
**Reproche de l'opérateur, justifié** : « hier c'était toi qui avais trouvé 50 k ». Exact. Le plafond
de capitalisation a été posé le 08/09 sur une mesure du **collecteur**, à l'ancienne échelle de
comptage et sur une autre période, avec la capitalisation lue dans `sol_obs`. La mesure d'aujourd'hui
part des données du **moteur**, à la bonne échelle, sur une fenêtre récente, avec la capitalisation
lue chez DexScreener. Deux sources, deux périodes, deux conclusions — **c'est un avertissement sur la
méthode autant qu'un résultat.**

**Mesure, 129 lancements comptés à la bonne échelle, croisés avec les courbes de prix** :

| tranche | n | gagnants | par euro | 1re moitié | 2e moitié |
|---|---|---|---|---|---|
| **< 25 k$** | **58** | **21 %** | **−0,134** | **−0,163** | **−0,112** |
| 25-50 k$ | 50 | 40 % | −0,018 | +0,019 | −0,091 |
| 50-150 k$ | 21 | 48 % | +0,043 | +0,055 | +0,037 |

La règle avait un plafond et **aucun plancher** : elle achetait donc en plein dans la tranche la plus
mauvaise. `min_market_cap_usd: 25000` ajouté.

**Pourquoi celui-ci et pas les autres** : c'est le seul résultat de la journée positif au test
hors-échantillon — mauvais dans **les deux** moitiés, sur le plus gros des trois échantillons, avec
un écart de taux de gagnants massif (21 % contre 40-48). Et il **retire une tranche mauvaise** au
lieu d'en choisir une bonne, ce qui demande beaucoup moins de foi dans l'échantillon.

**Ce qui a été testé et écarté le même jour, faute de tenir hors échantillon** :

| candidat | n | par euro | 1re moitié | 2e moitié |
|---|---|---|---|---|
| ratio ≤ 3 | 25 | +0,011 | −0,045 | +0,049 |
| ratio ≤ 3 et cap 25-150 k | 20 | +0,040 | **−0,100** | +0,132 |
| ratio ≤ 6 et cap 25-150 k | 24 | +0,008 | −0,078 | +0,070 |

Tous positifs en global, tous négatifs sur une moitié. **On n'y touche pas.** Le plancher d'acheteurs
va d'ailleurs dans le mauvais sens sur ces données (−0,061 sans plancher, −0,092 à 75, −0,113 à 100)
— autre raison de ne rien changer d'autre tant que l'échantillon est de cette taille.

**Le vrai enseignement, plus important que le réglage** : ce paramètre a changé deux fois en deux
jours, chaque fois sur quelques dizaines de lancements, chaque fois avec une mesure qui semblait
propre. **L'échantillon ne porte pas ces réglages.** La discipline pour la suite : plus aucun
changement de seuil tant que `sol_regime` n'a pas plusieurs jours, sauf pour retirer une tranche
mauvaise dans les deux moitiés — ce qui est le seul cas où l'on ne surajuste pas.

### 3.39 — Le rythme d'achat : 0,17/h contre 4-6 annoncés, 2026-09-09 11h30
**Reproche de l'opérateur** : « avec l'abonnement on achèterait 4 par heure, voire 6 ; je ne vois
rien de tout ça ». Vérifié, et il a raison — d'un facteur trente.

**Entonnoir mesuré sur 12 h** :

| étape | n | par heure |
|---|---|---|
| flux de migrations en direct | 526 | **43,8** |
| dont aussi visibles chez DexScreener | 38 | |
| lancements jugés | 696 | 58,0 |
| **écartés faute d'acheteurs** | **616** | **88,5 % du total** |
| écartés pour densité | 42 | |
| écartés pour capitalisation | 31 | |
| passent tous les filtres | 7 | 0,58 |
| ordres envoyés | 6 | dont **4 échouent** |
| **positions ouvertes** | **2** | **0,17** |

**L'abonnement n'est pas en cause** : 43,8 lancements par heure, dont 38 seulement sur 526 étaient
aussi visibles chez DexScreener. Sans lui on ne verrait presque rien. C'est mesuré, et ça règle la
question de savoir s'il valait ses 49 $.

**Le goulot est le plancher d'acheteurs**, qui écarte à lui seul 88,5 % de tout. Les échecs
d'exécution mangent ensuite la moitié du reste.

**Ce que le plancher coûte est mesuré ; ce qu'il rapporte ne l'est pas.** Sur les 134 lancements
comptés à la bonne échelle il va même dans le mauvais sens — aucun plancher −0,061 par euro, à 75
−0,092, à 100 −0,113, de façon monotone. Restreint aux lancements qui passent aussi densité et
capitalisation, il ne reste que **13 lignes**, 2 à 5 par tranche : impossible de trancher.

**Décision, avec l'opérateur : plancher ramené de 75 à 50.** Critère écrit d'avance, à vérifier sur
les 30 prochains tickets réels — le résultat par euro ne doit pas être pire que −0,10, et la part
des lignes perdant plus de la moitié du ticket ne doit pas dépasser 25 %. Si l'un des deux échoue,
retour à 75.

**Ce qui justifie de déroger à la règle « plus de changement de seuil » posée en §3.38** : là, le
coût est mesuré et énorme, et le bénéfice n'est pas démontré. Et il y a un second effet qui compte
autant : **à 0,17 ticket par heure il faut une semaine pour réunir 30 lignes, donc on ne peut rien
apprendre.** Multiplier le rythme est aussi ce qui rend les mesures suivantes possibles.

### 3.40 — Les ordres partaient sans frais de priorité, 2026-09-09 11h45
**Suite de §3.36.** Quatre ordres sur six échouaient en erreur Jupiter `0x1771`, avec des cotations
pourtant bonnes — impact entre 1,7 et 2 %, très loin du plafond. J'avais ouvert la tolérance de
dérive de 5 à 15 % : **PHOUSE a échoué à nouveau juste après**, donc l'explication était incomplète.

**Ce qui manquait** : `build_swap` envoyait la transaction **sans aucun frais de priorité**. Sur
Solana, une transaction sans priorité attend son tour d'inclusion — et pendant cette attente le prix
bouge. Jupiter compare alors le montant reçu au seuil calculé lors de la cotation, ne le trouve
plus, et annule. Ce n'est ni le prix ni la tolérance : c'est le **temps d'atterrissage**.

**Changement** : `priority_fee_lamports: 1000000`, soit 0,001 SOL ou environ 0,10 €, appliqué à
l'achat **et à la vente**. Payer pour atterrir vite coûte moins cher que de ne pas atterrir — 0,10 €
contre un ticket de 20 € qui ne se place pas.

**Et ça compte encore plus à la vente qu'à l'achat.** Un stop de perte ne sert à rien si l'ordre met
dix secondes à être inclus pendant que le jeton s'effondre. §3.34 montrait que tout le déficit du
carnet vient de sept effondrements quasi totaux, dont AMDuck sortie à ×0,06 avec un stop censé
couper à ×0,7 ; la boucle rapide à 5 secondes a réglé la moitié du problème — voir le prix plus tôt
— et les frais de priorité règlent l'autre — sortir avant que le prix ne bouge encore.

**Critère écrit d'avance** : sur les dix prochaines tentatives, le taux d'échec doit tomber sous
20 % (il est à 67 % sur les six dernières). Si les échecs persistent, la cause est ailleurs et il
faudra instrumenter le délai entre la cotation et le reçu, qui n'est mesuré nulle part aujourd'hui.

**Ce que ça dit du reste** : trois de mes diagnostics de la matinée sur ces échecs étaient
incomplets — d'abord la tolérance, puis le jeton qui s'effondre, enfin l'atterrissage. Les trois
sont réels et se cumulent ; aucun n'était suffisant seul. C'est un rappel qu'un symptôme unique
peut avoir plusieurs causes indépendantes, et qu'en corriger une ne prouve rien tant que le symptôme
n'a pas disparu.

### 3.41 — Ce que l'abonnement Helius apporte vraiment, 2026-09-09 11h30
**Question de l'opérateur** : « à quoi sert de payer 50 € par mois ». Mesuré sur 24 h.

| | |
|---|---|
| lancements déposés par le flux de migrations | **806** |
| dont aussi visibles chez DexScreener | 67 (**8 %**) |
| lancements jugés | 649 — dont **596 venus du flux**, 53 de DexScreener seul |
| **passages de la règle** | **10 — dont 9 du flux, et 6 que le flux SEUL a vus** |

**Sans l'abonnement : 53 lancements jugés au lieu de 649, et 1 passage au lieu de 10.** Il multiplie
les occasions par dix. Le rythme d'achat n'est donc pas limité par la découverte (§3.39) mais par ce
qu'il y a à acheter derrière.

**Et il paie une seconde chose, plus fondamentale** : le RPC indexé qui permet de compter les
échanges et les acheteurs distincts de la première minute. Toute la règle d'entrée repose là-dessus,
et ce comptage est hors de portée d'un nœud public à ce volume — sans lui il n'y a pas de stratégie,
seulement des achats à l'aveugle.

**Coût rapporté à l'usage** : 45 € par mois, soit 1,50 € par jour, contre environ 460 € engagés par
jour en tickets. **0,3 %.** Ce n'est pas là que l'argent part.

**Ce que la question a de juste malgré tout** : l'abonnement n'est pas le problème, mais il n'est
utile que si les occasions rapportent. Sur la fenêtre récente elles sont à l'équilibre au mieux
(§3.35). Si `sol_regime` confirme sur plusieurs jours que le marché ne paie plus, la décision n'est
pas d'annuler l'abonnement — c'est d'arrêter d'acheter, et l'abonnement suivra.

**Vérification du collecteur corrigé** (§3.35) : il produit désormais des mesures marquées `pages=12`
— 19 à ce stade, dont **2 refusées** parce que la première minute reste hors de portée même à
12 000 signatures, soit 10 %. Avant la correction, ces deux-là auraient rendu un compte trop petit
et seraient passées sous le plafond de densité.

### 3.42 — Robinhood mis en pause : son critère d'arrêt était atteint depuis des heures, 2026-09-09 11h50
**Ce que je n'avais pas regardé.** J'ai passé la matinée sur Solana pendant que l'autre carnet
perdait davantage. Mesure par tranches de 6 h :

| tranche | tickets | gagnants | invendables | résultat |
|---|---|---|---|---|
| 07/09 11h | 5 | 1 | 0 | **+67,51 €** |
| 07/09 17h | 10 | 3 | 0 | −0,81 |
| 07/09 23h | 2 | 0 | 2 | −10,16 |
| 08/09 05h | 6 | 0 | 5 | −27,98 |
| 08/09 11h | 5 | 2 | 2 | −10,99 |
| 08/09 17h | 12 | 1 | 10 | **−50,63** |
| 08/09 23h | 15 | 0 | 3 | **−47,52** |
| 09/09 05h | 2 | 0 | 2 | −10,21 |

**Sur 24 h : 34 tickets, −119,34 € sur 170 € engagés, soit −0,702 par euro.** Six tranches
consécutives négatives, 50 % d'invendables. Tout le résultat positif du carnet tient dans une seule
tranche du 07/09 au matin.

**Le critère d'arrêt était écrit d'avance**, dans la configuration : « si le taux d'invendables
tombe sous 15 %, la règle tient ; s'il reste au-dessus de 40 %, Robinhood s'arrête ». Il est à 50 %
depuis hier soir. **Le drapeau `t1_paused` est posé.**

**Ce que la pause fait exactement** : les décisions continuent d'être écrites, mais en carnet à
blanc (`shadow`) — aucun euro ne sort. Les ventes des positions déjà ouvertes continuent
normalement, ce qui est indispensable : il reste une ligne ouverte. Le carnet à blanc continue donc
d'accumuler des mesures sans risquer d'argent, ce qui est exactement ce dont on a besoin pour
savoir si la règle redevient bonne.

**Pourquoi je ne l'ai pas vu plus tôt, et ce que ça coûte** : depuis hier soir ce carnet n'avait
plus aucun garde-fou automatique — la limite de tickets, le plafond horaire et le plafond de pertes
ont tous été retirés à la demande de l'opérateur, et j'avais écrit à ce moment-là qu'il ne restait
« que la taille du ticket et le solde du portefeuille ». C'était exact et insuffisant : entre ce
constat et cette pause, le carnet a joué 34 tickets et perdu 119 €. **Un garde-fou retiré doit être
remplacé par une surveillance, pas par rien** — le bilan toutes les 30 minutes ne regardait que
Solana.

**À corriger dans la foulée** : le bilan périodique doit inclure le résultat par euro des DEUX
carnets et vérifier les critères d'arrêt écrits, pas seulement l'état des moteurs.

### 3.43 — Le collecteur ne suit pas le pool qu'on trade, 2026-09-09 12h
**Point de départ** : les cinq grosses pertes Solana portent tout le déficit. En traçant leur chemin
de prix, trois d'entre elles semblaient avoir été perdues **pendant que le marché montait** —
CATECOIN à ×2,34, Dukky à ×1,90, AMDuck à ×1,21. De quoi soupçonner un défaut grave de notre
exécution.

**Vérification sur la chaîne, qui tranche** :

| | acheté | vendu | rapport |
|---|---|---|---|
| AMDuck | 0,2091 SOL → 485,1 Md jetons | 485,0 Md → **0,0121 SOL** | **×0,058** |
| DLSS5 | 0,2077 SOL → 617,9 Md | 617,8 Md → 0,0222 SOL | ×0,107 |
| CATECOIN (matin) | 0,0278 SOL → 40,3 Md | 39,9 Md → 0,0009 SOL | ×0,033 |
| CATECOIN (soir) | 0,2090 SOL → 418,6 Md | 416,1 Md → **0,3185 SOL** | ×1,52 |

Les ventes ont bien eu lieu, sur la quasi-totalité des jetons détenus, à des prix catastrophiques.
**Il n'y a pas de défaut d'exécution.**

**L'erreur était dans ma lecture.** Le collecteur de recherche (`sol_pair`) enregistre **un** pool
par jeton, et ce n'est pas nécessairement celui que le moteur trade — un jeton gradué en a plusieurs.
Le signe qui aurait dû m'alerter : alignés sur le pool du collecteur, AMDuck et Dukky apparaissent
achetés à T+12,3 et T+19,1 minutes, alors que la fenêtre d'achat s'arrête à 10 minutes. Deux pools,
deux horloges.

**Ce que ça invalide** : la comparaison rejeu/réel de §3.31 appariait les lignes **par jeton**, pas
par pool. Sa conclusion — « le rejeu est fiable dès lors qu'il simule la règle qui tournait » —
repose donc sur des chemins de prix qui ne sont pas forcément ceux qu'on a subis. Les cinq lignes
d'après le stop restent cohérentes, mais **la démonstration est plus faible que je ne l'ai écrite**.

**Ce que ça ne change pas** : entre notre dernier relevé de prix (×1,11 pour AMDuck) et la vente, la
valeur a chuté de 94 %, en un seul intervalle de la boucle lente. La boucle à 5 secondes (§3.34) et
les frais de priorité (§3.40) visent précisément ce trou, et rien ici ne les remet en cause.

**À corriger dans la collecte** : `sol_pair` doit enregistrer le pool **par pair_id**, et
l'appariement avec nos positions doit se faire sur le pair_id que le moteur a réellement tradé —
il est déjà écrit dans les notes de chaque position (`pool:...`). Tant que ce n'est pas fait, aucune
comparaison entre les courbes du collecteur et nos résultats réels n'est fiable.

### 3.44 — Suivre les 58 lancements jugés par heure, pas seulement les 0,8 achetés, 2026-09-09 12h30
**Le vrai blocage, nommé.** Le carnet juge 58 lancements par heure et n'en achète que 0,8 : on
n'apprend donc que sur **1,4 %** de ce qu'on voit. C'est pour ça que chaque question de seuil reste
sans réponse — 13 lignes exploitables pour trancher un plancher d'acheteurs, 20 pour une
combinaison. Ce n'est pas le choix des seuils qui nous fait tourner en rond, c'est la taille de
l'échantillon.

**Ce qui est posé** : `solana_suivi` enregistre le prix, la liquidité et la capitalisation de **tout
lancement jugé**, acheté ou non, à chaque cycle pendant 30 minutes après le jugement. Sur le
**pool exact** qui a été jugé — l'appariement se fait sur `pairAddress`, et un autre pool du même
jeton est ignoré, ce qui règle le défaut de §3.43 à la source.

**Coût** : quelques appels DexScreener par cycle, l'API rendant 25 jetons à la fois. Rien de
nouveau, on l'interroge déjà.

**Ce que ça débloque** : d'ici quelques heures, plusieurs centaines de lancements avec leur courbe
de prix réelle. On pourra rejouer n'importe quelle règle d'entrée — plancher d'acheteurs, densité,
capitalisation, ratio, et leurs combinaisons — sur des centaines de lignes au lieu de vingt, **sans
engager un euro**. Les trois réglages changés aujourd'hui (plancher 50, capitalisation 25-50 k,
densité 600) pourront être jugés sur des données au lieu de l'être sur une intuition.

Premier passage vérifié : 21 relevés sur 21 pools.

### 3.45 — Recherche systématique : aucun avantage démontrable, 2026-09-09 13h
**Reproche de l'opérateur, fondé** : « tu récupères des données depuis trois jours et tu es toujours
incapable d'en profiter ». Exact. J'avais 745 lancements et 197 000 relevés de prix, et je m'en
servais pour répondre à des questions une par une au lieu de chercher une règle.

**Et ma méthode était fausse.** Je regardais les deux moitiés de la période **puis** je retenais ce
qui était positif dans les deux. C'est du peeking : en essayant assez de combinaisons on en trouve
toujours une qui passe les deux, et elle ne vaut rien. La bonne méthode — appliquée ici pour la
première fois — est de **chercher sur la première moitié uniquement**, puis de juger la gagnante sur
une seconde moitié jamais regardée.

**`intel/research/sol_recherche.py`** : 654 lancements exploitables, 328 dans la première moitié,
326 dans la seconde. **72 000 combinaisons** de plancher d'acheteurs, plafond de densité, ratio,
bande de capitalisation, objectif, stop et durée.

**Premier passage, sans contrainte de largeur** — la recherche choisit une règle ultra-sélective :

| | 1re moitié | 2e moitié |
|---|---|---|
| ≥75 ach, <600 éch, cap >50 k, ×2,0/stop 0,7/T+30 | 18 lignes, **+0,508** | 8 lignes, **−0,201** |

C'est la signature du surajustement dans sa forme la plus pure : +0,508 devient −0,201.

**Second passage, en exigeant au moins 40 lignes retenues** pour que le verdict ait un sens :

| | 1re moitié | **2e moitié (verdict)** |
|---|---|---|
| ≥75 ach, <450 éch, ×2,0/stop 0,7/T+30 | 43 lignes, **+0,314**, 63 % gagnants | 20 lignes, **+0,022**, 40 % gagnants |

**+0,022 par euro sur 20 lignes, c'est zéro.** Après une semaine, 745 lancements et 72 000
combinaisons : **aucun avantage démontrable.** Ce n'est pas un réglage qui manque.

**Ce que la recherche dit de mes changements du matin** : elle retient **≥ 75 acheteurs**. La
variante à 50 — que j'avais déployée trois heures plus tôt sur une tendance monotone observée sur
134 lancements, **sans validation hors échantillon** — est **négative hors échantillon** à −0,134
par euro. `min_buyers` remis à 75.

**Réserve honnête sur l'objectif ×2,0** que la recherche préfère : §3.23 et §3.34 montrent qu'en
réel **aucune** de nos 25 positions n'a atteint ×2. La recherche travaille sur des courbes
DexScreener échantillonnées à la minute, qui contiennent des sommets que notre propre relevé ne voit
pas et qu'un ordre réel n'atteint pas forcément. On ne change donc pas l'objectif sur cette base.

**La conclusion qui compte** : à 0,6 ticket par heure il faut deux semaines pour accumuler 20 lignes
de vérification, à 40 € de perte par jour. Le suivi posé une heure plus tôt (§3.44) mesure 58
lancements par heure **sans engager un euro**. Continuer à acheter, c'est payer pour apprendre vingt
fois moins vite.

### 3.46 — La sortie, elle, a un candidat — mais il repose sur un ×2 que notre carnet n'a jamais vu, 2026-09-09 13h30
**Après §3.45** (aucun avantage dans l'entrée sur 72 000 combinaisons), la piste restante était celle
que §3.34 désignait sans que je l'exploite : **21 tickets sur 28 rapportent +0,10 à +0,14 par euro,
7 effondrements emportent tout.** Le problème est la queue, donc la sortie.

**`intel/research/sol_sortie.py`**, même discipline qu'en §3.45 — 323 règles cherchées sur la
première moitié, jugées sur la seconde jamais regardée. Quatre formes, dont trois jamais testées :
sortie partielle, stop suiveur, stop qui se resserre.

| règle de sortie | moitié 1 | **moitié 2 (verdict)** | queue 2 |
|---|---|---|---|
| **30 % à ×1,5 puis ×2,0 / stop 0,7 / T+30** | +0,317 | **+0,126** | **0 %** |
| ×2,0 / stop 0,8 / T+15 | +0,332 | +0,108 | 0 % |
| ×2,0 / stop 0,7 / T+15 | +0,321 | +0,100 | 0 % |
| **production ×1,5 / stop 0,7 / T+15** | +0,151 | **+0,067** | 0 % |
| ×2,0 **sans stop** / T+10 | +0,350 | **−0,098** | 23 % |

**Deux enseignements solides** : toutes les règles avec stop tiennent hors échantillon, toutes celles
sans stop s'effondrent (−0,098, −0,114, avec 23 % de queue) — le stop est confirmé une troisième
fois. Et la sortie partielle rapporte presque le double de la production.

**Mais tout le tableau repose sur un objectif à ×2, et nos 25 positions réelles n'ont JAMAIS atteint
×2** (§3.34, sommet médian ×1,02). L'un des deux se trompe, et il faut le savoir avant de toucher à
quoi que ce soit.

**Première réponse du suivi posé une heure plus tôt** (§3.44), en 18 minutes : 726 relevés sur
43 pools, dont 33 assez suivis. **24 % atteignent ×1,5, 12 % atteignent ×2,0.** Donc ×2 arrive — au
prix DexScreener.

**L'explication que je retiens, et qui est testable** : DexScreener publie un prix moyen de marché ;
notre suivi de position interroge le routeur pour **notre taille réelle**. Sur un pool mince, ×2 au
prix moyen peut valoir ×1,3 à la vente. Si c'est le cas, **tout rejeu bâti sur des prix DexScreener
est optimiste**, y compris celui-ci, et la production a raison de rester à ×1,5.

**Rien n'est déployé sur cette base.** Le test : comparer, sur une position ouverte, notre cotation
routeur et le prix DexScreener au même instant. Quelques positions suffisent, et le suivi les
fournira aujourd'hui.

### 3.47 — Un pool sur cinq est invendable à notre taille : le filtre qui manquait, 2026-09-09 14h
**La question posée en §3.46** : les règles de sortie qui battent la production reposent toutes sur
un objectif à ×2 que nos 25 positions réelles n'ont jamais atteint. DexScreener publie un prix moyen
de marché ; notre carnet demande au routeur ce que la position vaut **à la vente, pour notre taille**.
Les deux sont-ils comparables ?

**Mesure, `intel/research/sol_aller_retour.py`** — pour 25 pools suivis, on cote un achat de 20 €
puis la revente immédiate de ce qu'on recevrait. Deux cotations, aucun ordre, aucun euro engagé.

| ce qui manque au retour | |
|---|---|
| médiane | **2,9 %** |
| 1er quartile | 1,1 % |
| 3e quartile | 4,5 % |
| **pire** | **98,7 %** |
| pools coûtant plus de 10 % | **6 sur 25** |
| pools coûtant plus de 25 % | **5 sur 25** |

**Première conclusion : les rejeux ne sont pas faussés d'un facteur deux.** Pour le pool médian,
l'aller-retour coûte 2,9 % — l'écart avec le rejeu ne vient donc pas d'un handicap général
d'exécution.

**Seconde conclusion, bien plus importante : un pool sur cinq est structurellement invendable à
notre taille.** On peut y entrer, on ne peut pas en sortir. Le pire rend 1,3 % de la mise.

**Et ce chiffre colle à ce qui détruit le carnet** : sept tickets sur vingt-huit anéantis (25 %),
contre cinq pools sur vingt-cinq invendables (20 %). Ce n'est donc pas le prix qui s'effondre après
notre achat — **c'est qu'on n'aurait jamais dû entrer.**

**Ce que ça change dans la hiérarchie des correctifs.** Aucune règle de SORTIE ne répare ça : ni le
stop, ni la boucle à 5 secondes (§3.34), ni les frais de priorité (§3.40). Tous supposent qu'il
existe une contrepartie à un prix. Quand elle n'existe pas, ils ne servent à rien. Les trois restent
utiles pour les pools normaux, mais **ils ne visaient pas la bonne cause.**

**Filtre déployé** : `max_aller_retour_pct: 8`. Avant chaque achat, on cote la revente de ce qu'on
recevrait ; au-dessus de 8 % on n'entre pas. Le seuil laisse passer les trois quarts des pools (3e
quartile à 4,5 %) et écarte toute la queue. Coût : une cotation supplémentaire par tentative.

**L'impact affiché à l'achat ne suffisait pas**, et c'est pour ça que ce défaut a survécu à
`max_impact_pct` : 1,11 % en médiane à l'achat contre 1,15 % à la vente, donc symétrique **en
moyenne** — et parfaitement muet sur les pools asymétriques, ceux qui coûtent 25 % ou 98 %. Il faut
coter le retour, pas déduire.

**Critère écrit d'avance** : sur les 20 prochains tickets, la part des lignes perdant plus de la
moitié de la mise doit tomber sous 10 % — elle est à 22 %. Si elle n'y tombe pas, l'invendabilité
n'était pas la cause et il faudra chercher ailleurs.

### 3.48 — Le rythme d'achat, chiffré étape par étape, 2026-09-09 14h30
**Question de l'opérateur** : « depuis hier 23 h on n'a pas acheté un seul jeton, le rythme devient
combien ? » Entonnoir rejoué sur 24 h de jugements réels :

| filtre | passages | par heure |
|---|---|---|
| lancements jugés | 908 | 37,8 |
| ≥ 75 acheteurs | 125 | 5,21 |
| et < 600 échanges | 66 | 2,75 |
| et ratio ≤ 15 | 66 | **2,75** — ce filtre n'écarte rien |
| **et capitalisation 25-50 k$** | **7** | **0,29** |

**La bande de capitalisation éliminait 59 des 66 passages à elle seule** — un facteur dix. Et le
filtre de ratio, hérité de la calibration d'origine, n'écarte plus rien du tout.

**Correction** : plafond relevé de 50 k$ à **150 k$**. Le 50 k datait du 08/09, mesuré sur le
collecteur à l'ancienne échelle, et **je ne l'avais jamais revalidé**. Les données du moteur, à la
bonne échelle, disent l'inverse : la tranche **50-150 k est la seule positive dans les deux moitiés**
(+0,043 par euro, 48 % de gagnants), quand 25-50 k fait −0,018 et < 25 k fait −0,134. Mon plafond
coupait exactement la meilleure tranche.

On ne va pas au-delà de 150 k : aucune mesure ne le justifie, et 34 des 59 lancements écartés sont
au-dessus de 500 k — la population « trop grosse pour bouger » que la mesure d'origine condamnait.

**Rythme attendu après correction** : 0,71 passage par heure, soit ~0,57 après le filtre
d'aller-retour, et une position toutes les deux heures environ si les frais de priorité portent le
taux d'exécution à 80 %. Contre une toutes les cinq à treize heures avant.

**Ce que cet épisode dit de ma méthode** : j'ai posé trois filtres en deux jours — plafond de
capitalisation, plancher de capitalisation, plancher d'acheteurs — sans jamais mesurer ce que leur
COMBINAISON laissait passer. Chacun paraissait raisonnable isolément ; ensemble ils ramenaient le
carnet à un ticket toutes les treize heures, c'est-à-dire à l'impossibilité d'apprendre quoi que ce
soit. **Un filtre doit être jugé sur l'entonnoir complet, pas sur sa propre justification.**

### 3.49 — Mes frais de priorité RÉDUISAIENT la priorité, 2026-09-09 15h
**Déclencheur** : BODEN, refusé en erreur `0x1771` alors que les frais de priorité de §3.40 étaient
déployés. Avant de conclure quoi que ce soit sur le taux d'échec, j'ai vérifié que le correctif
était réellement appliqué. Il ne l'était pas — il faisait l'inverse.

**Mesure directe contre l'API Jupiter**, même cotation, quatre formes de demande :

| forme envoyée | frais réellement appliqués |
|---|---|
| aucun paramètre (défaut de Jupiter) | **99 999 lamports** |
| `priorityLevelWithMaxLamports`, niveau « high », plafond 1 000 000 | **59 431** |
| niveau « veryHigh », plafond 1 000 000 | 128 218 |
| entier `300000` | 299 999 |
| entier `1000000` | 999 999 |

**Demander le niveau « high » plafonné à un million fait appliquer 59 431 lamports, soit 40 % de
MOINS que le défaut.** Le paramètre n'est pas un montant : c'est une estimation par niveau, et
l'estimation de Jupiter pour « high » était en dessous de son propre défaut. J'ai donc réduit la
priorité pendant deux heures en croyant l'avoir multipliée par dix.

**Corrigé** : un entier est appliqué tel quel. `priority_fee_lamports: 500000`, soit 0,048 € par
ordre — cinq fois le défaut, 0,24 % d'un ticket de 20 €.

**Ce que ça invalide** : la conclusion de §3.40 n'a jamais été testée. Le taux d'échec des ordres
depuis son déploiement (1 confirmé sur 2) ne dit rien, puisque la priorité était plus basse
qu'avant. Le compteur repart de zéro.

**Leçon, et c'est la deuxième fois aujourd'hui** : un réglage envoyé à une API tierce doit être
vérifié dans la RÉPONSE de l'API, pas supposé depuis la documentation. Deux appels de quinze
secondes auraient évité deux heures de fausse confiance — et je ne l'ai fait que parce qu'un ordre
a échoué. Sans cet échec, je serais resté persuadé d'avoir corrigé quelque chose.

**Vérifié aussi, et écarté** : BODEN et HAMSTERUNITE sont tous deux des jetons Token-2022 avec les
mêmes extensions (`metadataPointer`, `tokenMetadata`) et **aucune taxe de transfert**. L'hypothèse
d'un jeton taxé à la vente ne tient pas ; la différence entre les deux est le mouvement de prix
pendant l'atterrissage, pas la structure du jeton.

### 3.50 — « Tu as vendu trop tôt » : vrai sur ce ticket, faux comme règle, 2026-09-09 15h30
**Reproche de l'opérateur** devant une courbe. Vérifié, et il a raison sur le cas :

| jeton | notre sortie | prix ~40 min plus tard | écart |
|---|---|---|---|
| **HAMSTERUNITE** | ×1,14 (T+15) | **×1,71** | **+50 %** |
| AMDuck | ×0,06 (stop) | ×0,05 | −22 % — vendre était juste |

On a encaissé 2,73 € là où tenir en aurait donné ~14.

**Mais la règle se juge sur la distribution, pas sur un cas.** Le suivi posé trois heures plus tôt
(§3.44) permet de trancher : sur **51 pools** suivis de T+2 à T+30, prix maximum après T+15 rapporté
au prix à T+15 :

| | |
|---|---|
| médiane | **×1,01** |
| 3e quartile | ×1,05 |
| font mieux de plus de 20 % | 7 sur 51 (**14 %**) |
| font **pire** | 15 sur 51 (**29 %**) |

**Tenir au-delà de T+15 ne rapporte rien en moyenne, et deux fois plus de pools se dégradent qu'ils
ne progressent nettement.** HAMSTERUNITE appartient aux 14 % favorables. Tenir systématiquement
aurait gagné 50 % sur lui et perdu davantage sur quinze autres.

**On ne touche pas à la durée de détention.**

**Ce que cet épisode démontre surtout** : la question a été tranchée en deux minutes sur 51 pools,
là où il aurait fallu des semaines de tickets réels. C'est exactement ce que le suivi devait
apporter, et c'est la première fois qu'une intuition de l'opérateur est vérifiée le jour même sur un
échantillon suffisant.

**Sur le stop, en revanche, prudence.** ZDOG est sorti à ×0,62 pour un seuil à 0,70, soit 11 % de
dépassement, avec la boucle à 5 secondes. Tentant d'y voir la preuve que la boucle marche — sauf que
CALVIN faisait déjà 11 % **avant** elle, et qu'AMDuck en faisait 91 %. Un bon cas après un correctif
ne prouve rien quand un cas aussi bon existait avant. Il faut la série.

### 3.51 — Le stop coûte deux positions sur douze, et en épargne trente-cinq euros, 2026-09-09 16h
**Reproche de l'opérateur** : « ces deux positions m'ont fait perdre de l'argent ». Fondé — RSTR
sortie à ×1,00 vaut ×1,81 aujourd'hui, ZDOG sortie au stop vaut ×1,08. Environ **25 € manqués sur
ces deux lignes**.

**Ce que la règle coûte et rapporte, sur les 14 lignes perdantes encore cotables** :

| | |
|---|---|
| perdu réellement en vendant | **−144,97 €** |
| si on tenait encore aujourd'hui | **−180,09 €** |
| **épargné par le stop** | **+35,12 €** |

Neuf lignes sur onze valent **moins** cher aujourd'hui qu'à notre sortie, et pas de peu : NIKEY
×0,02, ZAPE ×0,04, AMDuck ×0,05, CALVIN ×0,06, Propaganda ×0,08, ETF ×0,11, BIPOLAR ×0,13. Le stop
a coupé à ×0,86, ×0,80, ×0,76 avant que ça tombe à deux ou quatre pour cent.

**Pouvait-on distinguer les deux qui remontent ?** Mesuré sur **30 pools** du suivi qui passent sous
×0,70 :

| après le passage sous le seuil | |
|---|---|
| remontent au-dessus de ×1,00 | 5 sur 30 (**17 %**) |
| remontent au-dessus de ×1,20 | 4 sur 30 (13 %) |
| **sommet médian atteint ensuite** | **×0,38** |
| 3e quartile | ×0,70 |

**Trois pools sur quatre ne repassent jamais au-dessus du seuil.** Retirer le stop ferait sortir à
×0,52 en moyenne au lieu de ×0,70 — soit **26 % de plus perdus sur chaque ligne stoppée**, pour en
récupérer une sur six.

**On garde le stop, et on ne cherche pas de discriminateur** : cinq cas de remontée, c'est trop peu
pour en tirer un signal. À revoir quand l'échantillon aura grossi.

**Le biais à nommer, parce qu'il revient sans cesse** : la ligne visible est toujours celle qui monte
après la vente. Les neuf qui se sont effondrées après notre sortie, personne ne les regarde — on n'y
pense plus. C'est vrai pour l'opérateur comme pour moi, et c'est pour ça que la seule réponse
acceptable à « on est sorti trop tôt » est une distribution, jamais un exemple.

### 3.52 — Le péage est fixe, et les deux pistes de l'après-midi sont mortes, 2026-09-09 17h
**Remarque de l'opérateur** : « moi je gagne en regardant la capitalisation, toi avec tout
l'algorithme tu n'y arrives pas, il y a un problème quelque part ». Fondée. Trois mesures en
réponse, dont deux tuent la piste qu'elles ouvraient.

**1. Les grosses capitalisations ne sont pas la réponse.** Sur 94 pools suivis, la tranche > 150 k$
affichait 91 % de gagnants — spectaculaire. Vérification : leur multiple de sortie médian est
**×1,029**, 34 sorties sur 35 se font à l'expiration, et leur capitalisation médiane est de
**5,9 millions** — ce ne sont pas des lancements. Net par ticket de 20 € : **+0,65 € avec les frais
de routage seuls, +0,048 € une fois le coût réel d'aller-retour déduit.** Les 3 % de dérive sont
entièrement mangés par le péage. Piste morte.

**2. Le péage est FIXE, pas de l'impact de marché.** Mesuré par cotation aller-retour à quatre
tailles :

| taille | coût réel |
|---|---|
| 2 € | 2,30 % |
| 5 € | 2,07 % |
| **20 €** | **1,55 %** |
| 50 € | 1,64 % |

Le coût ne dépend pas de la taille — il est même minimal à 20 €. C'est un prélèvement des places
d'échange, pas un problème de profondeur. **Il n'y a donc rien à optimiser côté exécution**, ce qui
ferme une piste sur laquelle j'allais passer l'après-midi. Et corollaire utile : **la taille du
ticket n'est pas contrainte par le marché** — à 50 € le coût par euro est identique. Le jour où la
stratégie sera positive par euro, la monter ne coûtera rien.

**3. Le stop suiveur : spectaculaire, puis nul.** Motivé par LEPTEP, monté à ×1,25 avant de
redescendre au stop. Sur 65 pools de moins de 150 k$, péage compris :

| règle | net/ticket |
|---|---|
| ×1,5 / stop 0,7 (production) | −0,111 € |
| ×1,25 / stop 0,7 | −0,971 |
| ×1,15 / stop 0,7 | −1,444 |
| **suiveur −15 % + stop 0,7** | **+7,573** |

Baisser l'objectif aggrave : plus de gagnants, trop petits pour payer le péage. Le suiveur semblait
magnifique. **Il tient à une seule ligne** :

| suiveur −15 %, seconde moitié, 33 lignes | |
|---|---|
| moyenne | +7,573 € |
| **sans la meilleure** | **−0,463** |
| sans les trois meilleures | −2,983 |
| **médiane** | **−4,318** |

Cinq meilleures : +5, +8, +19, +56, **+265 €**. Un pool a fait ×15 et porte tout. **Ce n'est pas une
règle, c'est un billet de loterie**, et la ligne médiane perd 4,32 €. Rien n'est déployé.

**Ce qui reste, et c'est l'énoncé le plus net du problème depuis le début du projet** : le péage de
2 % impose des mouvements très supérieurs à 2 %. Les grosses capitalisations ne bougent que de 3 % —
elles ne le paient pas. Les petites bougent assez, mais un quart s'effondre de 90 %. **Il n'existe
pas de zone confortable entre les deux**, et c'est pourquoi chaque réglage essayé retombe à
l'équilibre. Le seul levier restant est de **séparer les petites capitalisations qui montent de
celles qui s'effondrent** — ce que ni notre règle ni celle de l'opérateur ne fait.

### 3.53 — L'historique du créateur : le premier signal qui sépare vraiment, 2026-09-09 18h
**Point de départ, §3.52** : avec l'information disponible au moment du jugement, l'effondrement
d'une petite capitalisation n'est **pas** prévisible. Taux d'effondrement autour de 50 % dans toutes
les tranches d'acheteurs, de ratio, de liquidité, d'âge et de variation à 5 minutes. Il fallait donc
une information qu'on n'avait pas.

**Le créateur est récupérable, et pour rien.** Les autorités de frappe et de métadonnées sont
révoquées à la migration, mais remonter à la **première transaction du mint** et lire qui l'a payée
donne le créateur en **0,2 seconde par jeton** — 110 jetons résolus en 36 secondes.

**Sur 113 lancements suivis, avec la règle de production et le péage de 2 %** :

| | lignes | net par ticket de 20 € | gagnants | sans le meilleur dixième |
|---|---|---|---|---|
| créateur à **un seul** jeton | 90 | **−0,838 €** | 48 % | −1,976 |
| créateur **récidiviste** | 23 | **+2,995 €** | 52 % | **+2,386** |
| ensemble | 113 | −0,058 | | |

Et sur la forme des mouvements : les jetons de créateurs récidivistes montent au-dessus de ×1,3
**49 % du temps contre 17 %** pour les créateurs à jeton unique — trois fois plus.

**Ce qui distingue ce résultat de tous ceux de la journée** : il survit au retrait du meilleur
dixième (+2,386). C'est exactement le test qui a tué le stop suiveur, spectaculaire à +7,57 € mais
porté par une seule ligne à +265 €.

**Le mécanisme est plausible**, ce qui compte quand l'échantillon est mince : un portefeuille qui
lance plusieurs jetons est une opération organisée, avec une distribution et une communauté qui
survivent à la migration. Un créateur à coup unique n'a aucune raison de faire vivre son jeton après
avoir encaissé.

**Rien n'est déployé** — 23 lignes ne font pas une règle. Ce qui est posé : `SolanaWatcher._createurs`
résout le créateur de chaque lancement jugé **en tâche de fond**, quinze par cycle. Jamais dans le
chemin de décision : ajouter des allers-retours RPC entre la cotation et la signature est
précisément ce qui fait échouer les ordres (§3.40, §3.49).

**Critère écrit d'avance** : quand `sol_createur` couvrira 300 lancements suivis, refaire la mesure
en choisissant sur la première moitié et en jugeant sur la seconde. Si l'écart tient, c'est le
premier filtre d'entrée fondé de tout le projet — et il vise précisément ce qui détruit le carnet.

### 3.54 — Le signal du créateur ne survit pas au bruit de prix, 2026-09-09 18h30
**§3.53 annonçait** +2,995 € par ticket pour les créateurs récidivistes contre −0,838 pour les
créateurs à jeton unique, robuste au retrait du meilleur dixième. **C'était faux, et voici comment
je l'ai vu.**

**Le déclencheur** : le rejeu annonçait +9,40 € — exactement l'objectif ×1,5 — sur LEPTEP, un jeton
qu'on avait acheté **en réel** au même moment et sur le même pool, et qui nous a coûté **−6,29 €**
au stop. Même pool, deux résultats opposés : l'un des deux mentait.

**La courbe suivie de ce pool, relevés à 30 secondes** :
`1,64 · 1,36 · 1,81 · 1,81 · 2,07 · 1,59 · 1,38 · 1,83 · 1,36 · 1,90 · 1,23`
Le prix saute de ±40 % d'un relevé au suivant. Le rejeu normalisait sur 1,36, voyait 2,07 deux
minutes plus tard, et concluait « objectif atteint » pendant que le carnet sortait au stop.

**Ampleur du bruit, mesurée sur 120 pools et 4 772 écarts** — et elle nuance l'alarme :

| variation d'un relevé au suivant | |
|---|---|
| médiane | **0,1 %** |
| 3e quartile | 1,5 % |
| 9e décile | 14,7 % |
| au-dessus de 20 % | 7 % des écarts |
| pools au bruit médian > 15 % | **3 sur 120** |

La série est donc **propre pour l'immense majorité** des pools. Mais 7 % des écarts dépassent 20 %,
et sur une fenêtre de quinze minutes ça suffit à déclencher un faux objectif ou un faux stop.

**Correction de méthode** : une sortie n'est validée que si **deux relevés consécutifs** franchissent
le seuil. Résultat :

| | sans confirmation | avec confirmation |
|---|---|---|
| créateur à un seul jeton | −0,554 | −0,533 |
| créateur récidiviste | **+2,577** | **+0,617** |
| récidiviste, sans le meilleur dixième | +1,871 | **−0,292** |

**Le signal s'effondre.** Il reste un écart de ~1,2 € par ticket entre les deux groupes, et les
récidivistes restent les moins mauvais (−0,292 contre −1,527 au test robuste) — mais **plus rien
n'est positif**. Rien à déployer.

**Ce que ça impose pour toute mesure future** : une sortie simulée doit être confirmée par deux
relevés. Sans ça, un pic isolé de 40 % crée un gain qui n'a jamais existé, et 7 % des écarts sont
dans ce cas. Toutes les mesures du jour bâties sur `solana_suivi` — §3.50, §3.52, §3.53 — sont à
relire avec cette réserve ; celles qui portaient sur des taux (part qui s'effondre, part qui monte)
sont moins touchées que celles qui simulent un objectif.

**Bilan honnête de la journée sur la recherche** : quatre pistes ouvertes, quatre tuées par
vérification — grosses capitalisations, stop suiveur, historique du créateur, et l'optimisation de
l'exécution. Aucun avantage déployable trouvé. Le seul acquis solide est négatif et utile : le péage
de 2 % est fixe, et il n'y a rien à gagner côté exécution.

### 3.55 — Le stop à 5 secondes a empêché de vendre, 2026-09-09 19h
**L'incident.** USELESSLAPTOP, achetée à 13:57, monte à **×1,58**. La règle veut vendre à T+15. Elle
n'y arrive pas : **plus de trente refus consécutifs de Jupiter en erreur 429 « Rate limit
exceeded »**, de 14:12 à 14:17. La position est restée bloquée à son sommet pendant cinq minutes.

**La cause est un correctif que j'ai déployé ce midi.** `book_poll_seconds: 5` faisait coter chaque
position ouverte douze fois par minute ; s'y ajoutaient les deux cotations du filtre d'aller-retour à
chaque tentative d'achat, à un rythme de 2,8 achats par heure. Le quota de l'API gratuite a sauté, et
les VENTES ont été les premières victimes puisqu'elles passent par le même endpoint.

**Un garde-fou qui bloque la sortie est pire que pas de garde-fou.** J'avais construit un stop plus
réactif qui, dans les faits, empêchait de vendre.

**Ce qui a débloqué** : couper les achats (`min_buyers: 99999`) pour rendre le quota aux ventes. La
position est sortie dans les vingt secondes, à ×1,44, **+8,54 €**. Puis `book_poll_seconds` porté de
5 à 20.

**Comment je l'ai vu** : parce que l'opérateur a demandé pourquoi USELESSLAPTOP était encore ouverte.
**Pas** parce que la surveillance l'a détecté — le bilan des 30 minutes vérifie les positions Solana
bloquées au-delà de 20 minutes, et celle-ci en était à 17. Le seuil était trop lâche et la
vérification ne regardait pas les échecs d'exécution répétés.

**Bilan de la période où le rythme était élevé** (12h50 → 19h, plafond de capitalisation à 150 k) :
7 tickets, **−21,98 €**, −0,157 par euro, à 2,8 tickets/heure — soit **−233 € par jour** au même
régime. Le plafond a été remis à 50 k, puis les achats coupés entièrement.

**Acquis quand même** : **0 perte supérieure à la moitié de la mise sur ces 7 tickets**, contre 22 %
avant les correctifs. Les stops coupent désormais à ×0,62-0,69 au lieu de ×0,06. La limitation des
pertes fonctionne ; c'est le seul progrès mesurable de la journée.

**Part de responsabilité, demandée par l'opérateur et due** : sur ~290 € perdus depuis le début,
environ 200 € viennent de défauts de ma main — BIPOLAR payé deux fois (−20 €), stop absent les
premières heures (~−40 €), plafond relevé sur une mesure fausse (−24 €), Robinhood laissé sans
surveillance la nuit (−119 €). Le marché explique le reste.

### 3.56 — Recherche complète sur les courbes du suivi : un seul paramètre bouge, 2026-09-09 19h15
**Exigence de l'opérateur** : chercher une stratégie gagnante, pas arrêter. Recherche refaite sur
les **courbes du suivi** — que je n'avais jamais utilisées pour un balayage — avec **sorties
confirmées par deux relevés** (§3.54) et le péage de 2 %.

**504 combinaisons** de plancher d'acheteurs, ratio, bande de capitalisation, objectif, stop et
durée, cherchées sur la première moitié de 159 lancements, jugées sur la seconde :

| règle | moitié 1 | moitié 2 |
|---|---|---|
| ×2,0 / stop 0,8 / T+30 | +1,80 | **−2,42** |
| ×2,0 / stop 0,7 / T+30 | +1,64 | −1,44 |
| **×1,5 / stop 0,8 / T+30** | +0,52 | **+0,38** |
| **×1,5 / stop 0,7 / T+30** | +0,36 | **+0,78** |
| ×2,0 / stop 0,8 / T+15 | +1,16 | −2,72 |

**Toutes les variantes à ×2,0 s'effondrent hors échantillon ; les deux seules positives des deux
côtés sont à ×1,5 et T+30.** La seule différence avec la production est la durée.

**Le paramètre isolé**, sur les 24 lancements à ≥ 75 acheteurs avec courbe :

| durée | tout | moitié 1 | moitié 2 | sans le meilleur dixième |
|---|---|---|---|---|
| T+15 (production) | −0,20 | +0,22 | −0,63 | −1,08 |
| **T+30** | **+0,53** | **+1,07** | **0,00** | **−0,27** |

**T+30 fait mieux que T+15 sur les quatre colonnes.** Ce n'est pas une preuve — vingt-quatre lignes,
et rien n'est positif au test de robustesse. Mais c'est le **seul paramètre du projet qui pointe dans
la même direction sur toutes les mesures**, il ne coûte qu'un réglage, et il rejoint l'observation de
l'opérateur sur les ventes prématurées.

**Déployé** : `max_hold_seconds` 900 → 1800, achats rouverts (`min_buyers` 75), le reste inchangé —
capitalisation 25-50 k, carnet toutes les 20 s.

**Critère écrit d'avance** : sur les 20 prochains tickets, le résultat par euro doit être meilleur
que les **−0,157** mesurés à T+15 cet après-midi. Sinon retour à 900.

**Ce que la recherche dit aussi, et qu'il faut garder en tête** : sur 504 combinaisons testées avec
la méthode honnête, seules deux survivent, sur dix lignes hors échantillon. Ce n'est pas un avantage
démontré, c'est la moins mauvaise direction disponible. Le facteur limitant reste l'échantillon : le
suivi ne tourne que depuis sept heures, et il ne compte que 24 lancements passant la règle
d'entrée. Il en faudra dix fois plus pour trancher — et ils arrivent tout seuls, sans risquer un euro.

### 3.57 — Les trous ne venaient pas du service payant, mais de mon échantillon, 2026-09-09 20h
**Question de l'opérateur** : « les trous viennent d'où ? je pensais qu'on payait un service pour
avoir les données ». Vérifié, et la réponse est déplaisante.

**L'abonnement n'y est pour rien.** Appel direct à l'endpoint d'enrichissement Helius : HTTP 200,
transactions décodées, payeur présent sur chacune. Le service répond correctement.

**Le défaut est dans notre code, et il est précis.** `getSignaturesForAddress` rend les signatures
du plus **récent** au plus ancien. La fenêtre de la première minute héritait de cet ordre, et
l'échantillon de 300 transactions envoyé à l'enrichissement prenait donc les **300 dernières** de la
minute — jamais les premières — alors que le commentaire du code affirme le contraire depuis
l'origine.

**Preuve, sur 1 163 lancements ayant des échanges dans leurs trente premières secondes** :

| | échanges dans la minute (médiane) | moins de 300 échanges |
|---|---|---|
| lignes rendant **0 acheteur à 30 s** (impossible) | **1 788** | **0 sur 333** |
| lignes saines | 107 | 650 sur 830 (78 %) |

**Aucune** des 333 lignes cassées n'a moins de 300 échanges. Dès qu'un pool dépasse le seuil de
l'échantillon, ses trente premières secondes ne sont jamais décodées.

**Ce que ça touche au-delà de la mesure à 30 secondes** : le comptage des acheteurs à 60 secondes
utilise le même échantillon. Sur un pool à 1 788 échanges, `uniq_payers` compte les acheteurs des
300 **dernières** transactions de la minute. Le plancher de 75 acheteurs — le filtre central de
toute la stratégie — est donc appliqué à une quantité qui n'est pas celle que §3.7 décrit, et ce
depuis le début.

**Corrigé dans les deux programmes en même temps**, moteur et collecteur : la fenêtre est triée par
horodatage avant l'échantillonnage. Les deux doivent mesurer la même chose, faute de quoi la
calibration ne s'applique pas à la production (§3.35).

**Ce que ça oblige à reconsidérer** : toutes les mesures d'acheteurs antérieures au 09/09 20h portent
sur un échantillon biaisé vers la fin de la minute, et d'autant plus que le pool est dense. Le
plancher de 75 a été calibré là-dessus. Il faudra le remesurer sur les données propres — c'est
exactement la même erreur que §3.35, à un autre endroit du même code.

**Leçon, la troisième du même genre en deux jours** : un commentaire qui affirme ce que fait le code
n'est pas une preuve. « les 300 premières transactions », « 6 × 1 000 signatures dépassent largement
une minute », « frais de priorité élevés » — trois affirmations écrites en toute bonne foi, trois
faux. Ce qui coûte n'est pas l'erreur, c'est qu'elle se transmet ensuite dans chaque mesure qui s'y
appuie.
---

### 3.58 — Les deux dimensions balayees sur donnees propres : pas d'edge, 2026-09-09 17h

Premiere fois que sortie ET entree sont mesurees proprement sur le meme echantillon, avec moitie
tenue a l'ecart et test contre le hasard. `intel/research/sol_objectif.py` et `sol_entree.py`.

**Sortie** — 40 combinaisons objectif x stop, 292 courbes de `solana_suivi` :

    recherche : meilleur x1,40 / 0,80 a -0,111/euro
    jugement  : cette meme case donne -0,185 ; le meilleur y est x1,05 / 0,80

La grille **s'inverse** entre les deux moities : les objectifs hauts gagnent d'un cote, les bas de
l'autre. C'est la signature du bruit. Et les 40 cases sont negatives, de -0,111 a -0,213.

L'hypothese que je defendais -- « l'objectif x1,5 est trop haut, les tickets plafonnent a x1,1 » --
etait tiree des dix derniers tickets. Elle est fausse sur 292 courbes. **Dix tickets ne sont pas un
echantillon**, meme quand le motif y est frappant.

**Pourquoi aucune sortie ne marche**, en une distribution :

    touchent x1,15  41,8 %     tombent sous x0,70  51,4 %
    touchent x1,50  26,7 %     tombent sous x0,50  43,8 %
    touchent x2,00  14,7 %     tombent sous x0,10  20,5 %
    pic median x1,09 · creux median x0,66 · fin mediane x0,80

Ce sont **les memes lancements** qui montent a x1,15 et qui descendent sous x0,70 : les deux seuils
mordent sur la meme population. Il faut x1,0204 pour couvrir le peage et **36,6 % seulement**
finissent au-dessus. Un sur cinq finit sous x0,10.

**Entree** — ~200 regles sur 12 variables, sortie fixee a la production (x1,5 / 0,7) :

    reference (acheter tout)   recherche -0,128   jugement -0,178
    market_cap >= 204207       recherche -0,028   jugement -0,130   (meilleur en recherche)
    chg_m5 <= -56,9            recherche -0,041   jugement -0,079   (le seul correct des deux cotes)

Le test decisif est le tirage au sort : 2 000 echantillons de 50 tickets pris au hasard dans la
moitie de jugement donnent une mediane de -0,176 et un decile haut de -0,106. La meilleure regle
fait -0,130, et **19,4 % des tirages au hasard font aussi bien ou mieux**. Elle ne se distingue pas
du hasard.

**Conclusion : il n'y a pas d'edge dans cette famille de strategies.** Ni dans le choix du
lancement, ni dans le moment de la vente. Le balayage d'entree precedent (72 000 combinaisons,
+0,022 hors echantillon) tournait sur l'echantillon biaise par le bug d'ordre de tri (§3.57) ; sa
reprise sur donnees propres donne le meme verdict, ce qui au moins confirme que le biais n'avait
pas cache un signal.

**Seule piste non morte**, a ne pas confondre avec une solution : `chg_m5 <= -56,9`, acheter apres
une chute de plus de 57 %, est la seule regle correcte dans les deux moities. C'est un pari de
retour a la moyenne -- l'inverse exact de ce que fait le carnet, qui achete la hausse. Elle reste
perdante ; elle merite d'etre suivie a blanc, pas mise en production.

**Et le point qui decide de la depense :** `solana_suivi` enregistre la courbe de TOUS les
lancements juges -- 302 courbes pour 100 tickets reellement achetes sur 72 h. Acheter en reel
n'apporte aucune information que la collecte a blanc ne donne deja. Le carnet reel paie ~212 EUR
par jour pour apprendre ce qui s'apprend gratuitement.

### 3.59 — Un stop ne s'execute pas a son niveau : le simulateur gonflait les 20 strategies, 2026-09-09 17h30

`chute_rebond`, ajoutee a blanc une minute plus tot, affichait **+414 EUR sur 84 tickets, +0,247 par
euro**. Cinquieme resultat spectaculaire de la semaine ; comme les quatre precedents, un artefact --
mais empile a deux etages, ce qui vaut d'etre garde.

**Premier etage : le simulateur supposait une execution au seuil.** `_sortie` rendait `stop` quand
le stop se declenchait, c'est-a-dire 0,70 exactement. Or un stop dit **quand on donne l'ordre**, pas
**a combien il s'execute**. PONSZCAT, vingt minutes plus tot : stop a 0,70, execution reelle a
**x0,20** -- le pool s'etait vide entre deux releves espaces de vingt secondes.

Ecart mesure en rendant le prix reel au lieu du seuil :

    prod_t30       -0,053  ->  -0,426     ecart -0,373
    ta_calme       -0,053  ->  -0,365     ecart -0,313
    dense          -0,142  ->  -0,432     ecart -0,289
    stop_serre     -0,007  ->  -0,210     ecart -0,203
    sans_stop      -0,279  ->  -0,279     ecart  0,000   <-- la seule sans stop

**`sans_stop` a un ecart exactement nul.** C'est ce qui a isole la cause : le biais ne touche que
les strategies a stop, et d'autant plus qu'elles s'arretent souvent. `stop_serre` passait pour
quasi a l'equilibre (-0,007) alors qu'elle perd 0,210 par euro.

**Deuxieme etage : la moitie in-sample.** `chute_rebond` survivait a la correction (+0,172). Decoupee
en deux :

    peage  2 %   1re moitie +0,343   2e moitie (hors echantillon) +0,006
    peage  5 %              +0,301                                -0,025
    peage 10 %              +0,233                                -0,076

Tout le gain vient de la moitie deja regardee. Hors echantillon : **zero**. Et le peage de 2 % est
le plancher : sur des jetons qui viennent de chuter de 57 %, les pools sont minces et le vrai
aller-retour depasse souvent 10 % (§3.47). Le test contre le hasard passait a 2,5 % uniquement
parce qu'il incluait la moitie in-sample.

**Ce qu'il faut en retenir :**

- **Un simulateur de sortie doit rendre le prix, jamais le seuil.** Le seuil est une intention,
  le prix est un fait. La difference vaut jusqu'a 0,373 par euro, soit de quoi inverser le signe de
  n'importe quelle conclusion.
- **Une strategie a blanc calculee retroactivement sur tout l'historique est integralement
  in-sample.** Ses 84 tickets ne sont pas 84 observations : c'est un balayage deguise en carnet.
  Le decoupage en moities reste obligatoire.
- **Verifier la robustesse au peage, pas seulement au reglage.** Une strategie qui ne survit qu'a
  2 % de frais n'existe pas : c'est le plancher, atteint seulement sur les pools profonds -- et une
  strategie qui achete des effondrements ne travaille jamais sur des pools profonds.

Les 479 lignes de `sol_strat_resultat` calculees avec le biais ont ete effacees (sauvegarde CSV) et
sont recalculees par le moteur. Tout classement des strategies anterieur au 09/09 17h30 est faux.

### 3.60 — Le plancher de 75 acheteurs n'apporte rien, 2026-09-09 17h45

Reprise du critere central du carnet sur donnees propres -- il avait ete calibre sur l'echantillon
biaise par le bug d'ordre de tri (§3.57) et jamais revalide depuis. 364 lancements, moitie de
jugement tenue a l'ecart.

    par euro          >= 0        >= 25       >= 50       >= 75
    1re moitie      -0,124      -0,117      -0,141      -0,116     (182 -> 27 tickets)
    2e moitie       -0,182      -0,219      -0,316      -0,467     (182 -> 38 tickets)

La seconde moitie est parfaitement monotone : plus on exige d'acheteurs, pire c'est. Le test contre
le hasard y est spectaculaire -- sur 5 000 tirages de 38 tickets, **aucun** ne fait aussi mal que
`payers >= 75`, et aucun ne fait aussi bien que son complement.

**Mais la premiere moitie est plate** : -0,124 / -0,117 / -0,141 / -0,116, aucune tendance. Le taux
de gagnants, statistique bien moins sensible aux catastrophes isolees que la moyenne, le confirme :

    1re moitie   >=75 : 44 %   <75 : 47 %   ecart  +3 points   -- rien
    2e moitie    >=75 : 21 %   <75 : 51 %   ecart +30 points   -- enorme

**L'effet ne se reproduit pas. On ne conclut pas** que le plancher est nuisible : c'est exactement
la signature des quatre artefacts precedents, un resultat massif dans une moitie et rien dans
l'autre.

**Ce qui est en revanche cohérent des deux cotes : le plancher n'apporte AUCUN benefice.** En
premiere moitie -0,116 avec contre -0,125 sans -- indiscernable ; en seconde moitie il est trois
fois pire. Dans les deux cas, acheter ce qu'il rejette fait au moins aussi bien.

Et il coute 82 % du flux : **65 lancements sur 364 le passent**. Un filtre qui supprime quatre
cinquiemes des passages pour un benefice nul est un mauvais filtre quel que soit son signe (§3.48).

**Portee reelle de ce constat.** Le plancher d'acheteurs n'est pas un reglage parmi d'autres : c'est
le critere autour duquel toute la strategie est batie -- « une foule qui se presse annonce une
hausse ». Cette these n'a aucun support mesure. Combinee a §3.58 (ni l'entree ni la sortie n'ont
d'edge), la conclusion est que la famille de strategies elle-meme est sans fondement, pas qu'elle
est mal reglee.

### 3.61 — Le simulateur est deux fois trop pessimiste : la resolution, 2026-09-09 18h20

Test le plus utile de la journee, et il aurait du etre le PREMIER : rejouer la regle de production
sur les tickets reellement achetes, et comparer ticket par ticket au resultat encaisse.

                        REEL      SIMULE     ecart
    LAPJAK            +10,32     -19,29    +29,61
    LEPTEP             -6,29     -19,72    +13,42
    ZCAPY              -6,43     -19,11    +12,68
    Bigduck            -6,66     -15,74     +9,07
    ...
    TOTAL (13)        -78,44    -146,57    +68,12
    par euro          -0,302     -0,564

**Le carnet reel fait deux fois mieux que sa propre simulation.** LAPJAK est le cas d'ecole : la
courbe le voit toucher le stop (-19,29), le moteur a pris son objectif a x1,53 (+10,32). L'ecart
median par ticket n'est que de +1,53 EUR -- c'est une poignee de tickets qui portent tout l'ecart,
ceux ou la courbe a rate un mouvement.

**Cause : la resolution.** `solana_suivi` echantillonne toutes les **33 s** en mediane ; le moteur
interroge le routeur toutes les **20 s** et agit sur une vraie cotation. Avec la confirmation sur
deux releves, la rejoue exige ~66 s de condition soutenue la ou le moteur se contente de ~40 s. Sur
des jetons qui font x1,21 -> x0,20 en 66 secondes (PONSZCAT), l'ecart n'est pas un detail : la
rejoue sort systematiquement plus tard, donc plus bas en chute, et rate les pics en hausse.

**Ce que cela invalide, et ce que cela epargne :**

- **INVALIDE : toute conclusion sur les reglages de SORTIE.** Le balayage objectif x stop (§3.58)
  donnait au mieux -0,111/euro ; le biais mesure est d'environ +0,26/euro, soit plus que le
  resultat lui-meme. Et il ne frappe pas uniformement : un reglage qui negocie souvent (stop serre,
  objectif proche) est penalise davantage qu'un reglage passif. **La phrase « les 40 cases perdent »
  est retiree.**
- **EPARGNE : les comparaisons d'ENTREE.** La meme sortie est appliquee a toutes les regles, donc
  le biais se retranche dans la comparaison. Le classement des regles, le test contre le hasard et
  le constat sur le plancher d'acheteurs (§3.60) restent valides.
- **EPARGNE : le resultat du carnet reel.** -0,138/euro sur 24 h se lit sur la chaine, pas dans une
  simulation.

**Regle generale :** *avant d'utiliser un simulateur pour trancher, le confronter au reel sur les
memes evenements.* Treize tickets ont suffi. J'ai balaye 40 combinaisons de sortie et ~200 regles
d'entree avant de faire cette verification a treize lignes de code -- l'ordre etait inverse.

**Corollaire sur la resolution :** un simulateur ne peut pas trancher une question dont l'echelle de
temps est plus fine que son pas d'echantillonnage. Pour arbitrer des sorties a 20 s, il faut des
releves a 20 s ou moins.

**Et echantillonner plus vite ne suffirait pas -- mesure du 09/09 18h50.** Un pool actif interroge
toutes les 5 s pendant deux minutes : DexScreener n'a change son prix que **trois fois**, a t+10 s,
t+70 s et t+100 s. La source se rafraichit au rythme ou nous l'echantillonnons deja ; polling plus
souvent ne rendrait que la meme valeur perimee, en consommant du quota.

Le probleme n'est donc pas la cadence, c'est **la source**. Le moteur decide sur une cotation
Jupiter : instantanee, reelle, et c'est le prix auquel il sera effectivement servi. La recherche
rejoue sur DexScreener, qui retarde jusqu'a une minute. Sur un jeton qui fait x1,21 -> x0,20 en
66 secondes, une minute de retard n'est pas une imprecision, c'est l'evenement entier.

**Deux sorties possibles, aucune gratuite :**

  1. **Coter au routeur pour la recherche aussi.** Fidele par construction, mais limite en debit et
     partage avec le chemin de vente -- une boucle a 5 s avait deja provoque des 429 bloquant les
     ventes (§3.55). Il faudrait un quota separe.
  2. **Calculer le prix depuis les reserves du pool, en lisant le compte sur le RPC.** Aucune
     dependance a un agregateur, cadence libre, et le RPC indexe est deja paye. Le cout est le
     decodage du format de chaque DEX -- Meteora DAMM v2, PumpSwap, pump.fun -- et il faut le
     refaire a chaque nouveau lieu de negoce.

Tant que l'une des deux n'est pas faite, **aucune question de sortie ne peut etre tranchee par
rejoue**, et il faut le dire au lieu de produire des grilles qui ont l'air precises.

### 3.62 — L'effondrement se predit, mais l'eviter ne rapporte pas, 2026-09-09 19h15

Question choisie parce qu'elle est **insensible a la resolution** (§3.61) : un jeton qui tombe a
x0,04 et y reste est visible a n'importe quelle cadence, contrairement a un pic de trente secondes.
Etiquette : deux releves consecutifs sous x0,30 dans les trente minutes.

**Le signal existe, et il se reproduit dans les deux moities** -- le premier de la journee :

    taux d'effondrement de reference      33 % (recherche)   30 % (jugement)
    market_cap >= 5,6 M                    9 %                8 %      (n=36)
    market_cap >= 1,67 M                  10 %               12 %      (n=51)

1 tirage au hasard sur 3 000 fait aussi bien. Les grosses capitalisations ne s'effondrent pas : leur
creux median est x1,00, elles ne descendent pas du tout.

**Mais cela ne se convertit pas en argent, et le piege etait la mediane.**

                                  n    peage 2 %   5 %    10 %
    tout (jugement)              233     +0,009  -0,022  -0,074
    market_cap >= 1,67 M          51     -0,092  -0,120  -0,167
    market_cap >= 5,6 M           36     -0,066  -0,094  -0,142
    zone de production 25k-50k    29     -0,323  -0,343  -0,378

**70 % des tirages au hasard font mieux que la regle a 1,67 M.** Elle est moins bonne que le
hasard.

La mediane des grosses capitalisations est x1,03 -- au-dessus du peage -- mais leur MOYENNE par euro
est -0,07. La distribution est asymetrique : beaucoup de petits gains, quelques pertes lourdes, et
les quelques-unes l'emportent. **J'ai failli annoncer une decouverte sur une mediane.** Une mediane
decrit le ticket typique ; c'est la moyenne qui decrit le compte en banque, et sur des distributions
a queue lourde les deux disent le contraire.

**Ce qui survit, solide des deux cotes :** la zone ou le carnet achete, 25k-50k, est de tres loin la
pire matiere premiere mesuree -- -0,624 en recherche, -0,323 en jugement, en achat-conservation.
Issue mediane x0,17 : on perd 83 % de la mise sur le ticket median. Contre x1,03 pour les grosses
capitalisations.

**Nuance qui compte, et qui joue en faveur du moteur :** le carnet reel rend -0,138/euro la ou
l'achat-conservation dans la meme zone rend -0,323. **Les sorties recuperent plus de la moitie du
desastre.** Elles ne suffisent pas a passer positif, mais elles travaillent -- ce qui contredit
l'impression laissee par une journee de tickets sortis a x0,20.

**Etat de la question apres cette mesure :** les trois familles connues restent sans issue -- petites
capitalisations qui bougent mais s'effondrent une fois sur trois, grosses qui ne s'effondrent pas
mais ne paient pas le peage, et rien entre les deux. C'est le meme mur qu'au §3.44, mesure cette
fois sur 464 lancements au lieu de 25.

### 3.63 — Les sorties du moteur valent +0,14 a +0,25 par euro, 2026-09-09 19h20

Premier resultat positif de la journee, et le seul qui resiste a toutes les verifications. Il fallait
d'abord corriger une comparaison biaisee que j'avais moi-meme produite : j'avais oppose le carnet
reel (-0,138/euro) a l'achat-conservation de TOUS les lancements de la tranche 25k-50k (-0,323).
Ce ne sont pas les memes tickets -- l'ecart pouvait venir des autres filtres, pas des sorties.

Refait a entree identique, sur les **memes** tickets reellement achetes, contre « tenir trente
minutes sans rien faire ». La valeur de fin est insensible a la resolution (§3.61), donc la
comparaison est valide malgre le probleme de source.

    TOTAL (13)          reel -78,44   tenir -141,77   ecart +63,35
    par euro                 -0,302          -0,545         +0,244
    le moteur fait mieux sur 9 tickets sur 13

**Robustesse -- la regle du journal impose de retirer la meilleure ligne (§3.51) :**

    complet                    +0,244/euro   mediane +4,55 EUR par ticket
    sans la meilleure ligne    +0,140/euro   mediane +4,51
    sans la meilleure et la pire +0,247/euro mediane +4,55

**La mediane ne bouge pas d'un centime.** C'est exactement l'inverse du stop suiveur, qui valait
+7,573 par ticket et tombait a -0,463 des qu'on retirait une ligne. Ici l'effet est porte par la
masse des tickets, pas par un accident.

**Ce que cela dit du systeme.** Le probleme n'est pas la machinerie : elle recupere pres de la
moitie de ce que la matiere premiere detruit. Le probleme est **entierement l'entree** -- une
tranche dont l'issue mediane est x0,17 (§3.62) et dans laquelle aucune regle testee ne trie mieux
que le hasard (§3.58, §3.60).

Corollaire pratique : si une source de lancements moins toxique existait, l'infrastructure existante
vaudrait la peine d'etre rebranchee dessus. Ce n'est pas le moteur qu'il faudrait jeter.

**Reserve : 13 tickets.** L'effet est stable a la troncature mais l'echantillon est mince ; a
reprendre a 40 tickets avant d'en faire un argument.

### 3.64 — Le facteur on-chain ne survit pas a trois periodes, 2026-09-09 19h45

Reprise complete de la seule piste du projet qui avait montre un resultat hors echantillon. Le
script existant annoncait **2,62x sur 2022-2026** pour une selection par croissance des adresses
actives. Ce chiffre est une courbe de capital **long-only**, qui melange trois choses : le filtre de
regime (applique identiquement a toutes les strategies), le beta du marche, et la selection. Seule
la troisieme est un alpha.

**Etape 1 -- isoler la selection.** Ecart entre sextile haut et sextile bas a trente jours, plus
l'IC. Le temoin est instructif : le momentum de prix a un ecart NEGATIF dans les deux periodes
(-5,0 % et -1,2 %), donc le test ne valide pas n'importe quoi. L'adoption est positive des deux
cotes (+4,3 % et +3,1 %).

**Etape 2 -- neutraliser le marche.** Long le sextile haut, short le bas :

    AdrActCnt   2020-2021 -1,2 %/an (portage nul)   2022-2026 +12,4 %
    TxTfrCnt    2020-2021 -20,3 %                   2022-2026 +11,3 %
    TxCnt       2020-2021 +23,1 %                   2022-2026 +21,0 %

`TxCnt` -- la croissance du nombre de transactions -- passait le test qui tuait les deux autres, et
survivait a 10 %/an de portage du short (+13,6 % / +10,1 %).

**Etape 3 -- la robustesse aux reglages, qui l'a tue.** A fenetre 45 jours, passer de K=5 a K=6 fait
basculer de **+62 % a -31 %**. Un effet reel ne bouge pas de 90 points quand on change un actif dans
un panier. Seuls 7 reglages sur 26 tenaient des deux cotes.

**Etape 4 -- une troisieme periode, recuperee pour l'occasion.** 2020-2021 ne compte que douze
rebalancements, trop peu pour trancher. J'ai donc telecharge chez Binance les clotures journalieres
2017-2021 (`scripts/fetch_prices_2017.py`) pour ouvrir **2018-06 -> 2020-10** : bear 2018, reprise
2019, krach Covid, ~26 rebalancements, regimes absents des deux autres periodes.

**Le verdict, sur 36 reglages x 3 periodes independantes :**

    cases positives   2018-2020  72 %    2020-2021  25 %    2022-2026  64 %
    attendu par hasard, positif PARTOUT : 0,72 x 0,25 x 0,64 = 11,5 %  ->  4,2 / 36
    observe : 3

**Moins que le hasard.** Trois reglages tiennent partout (TxCnt, fenetre 90-120 j, K=5-6) la ou le
tirage au sort en donnerait quatre.

**Nuance a ne pas escamoter :** 2020-2021 est un bull vertical de quinze mois, et c'est la que tout
meurt (25 % de cases positives contre 72 % et 64 %). Un long-short y est structurellement penalise
puisque la jambe short se fait detruire. On peut donc soutenir que le test y est injuste. Mais on ne
peut pas avoir les deux : soit la periode hors echantillon compte, soit elle ne compte pas. Ce qui
est certain, c'est qu'on ne peut pas faire tourner ce facteur en aveugle.

**Ce qui reste vrai malgre le verdict**, et merite d'etre garde : dans les trois periodes, ce sont
les metriques d'ACTIVITE en CROISSANCE qui separent le mieux, jamais les NIVEAUX -- la croissance
d'usage prédit, la taille non. Et le momentum de prix est negatif partout. Ces deux faits sont
coherents sur 90 rebalancements ; ils ne suffisent pas a faire une strategie.

**Outils crees** : `onchain_selection_skill.py`, `onchain_longshort.py`, `onchain_all_metrics.py`,
`onchain_txcnt_robustesse.py`, `onchain_periode3.py`, `onchain_trois_periodes.py`,
`fetch_prices_2017.py`.

### 3.65 — Le prix lu dans les reserves du pool : la zone T+0 devient observable, 2026-09-09 20h

Trois mesures de la journee disaient la meme chose sous trois angles : **DexScreener ne peut pas
repondre aux questions qu on lui pose.**

  - il se rafraichit toutes les 30 a 60 s, alors que le moteur decide toutes les 20 s -- d ou un
    simulateur deux fois trop pessimiste (§3.61) ;
  - il n indexe pas les pools recents : **6 sur 74** en une heure ;
  - le premier releve des 530 courbes collectees tombait a T+1,28 min au plus tot, mediane T+1,72.
    **La zone T+0 a T+1,5 min n avait jamais ete observee** -- celle ou agissent le createur, les
    bundlers et les snipers du premier bloc.

Une tentative d elargir le suivi aux lancements non encore juges n a rien change (min T+1,52 apres,
contre T+1,28 avant) : le goulot n etait pas la requete, c etait la source.

**Solution : lire le prix la ou il se forme, dans les reserves du pool.**

    getProgramAccounts(PumpSwap, dataSize=301, memcmp offset 43 = mint de base)   -> le pool
    getMultipleAccounts([base_ta, quote_ta])                                      -> les reserves
    prix = reserve_quote / reserve_base

L offset 43 vaut 8 (discriminant) + 1 (bump) + 2 (index) + 32 (createur) ; les deux comptes de
reserve suivent base_mint, quote_mint et lp_mint, soit l offset 139.

**Valide contre DexScreener sur cinq pools** avant d etre branche : ecarts de -2,4 % a +4,2 %, dans
le sens et l ordre de grandeur attendus de son retard. Le lecteur est donc juste, et l ecart mesure
au passage combien l agregateur retarde.

**Resultat apres 90 secondes** : 314 releves sur 28 pools, **premier releve a T+17 s**. Un pool vide
(0,02 SOL de reserve) apparait dans la serie -- le retrait de liquidite devient visible en dix
secondes au lieu d etre constate apres coup.

**Ce que cela debloque :**

  1. la zone T+0 a T+1,5 min, jamais vue ;
  2. les rejouees de sortie, invalidees au §3.61 faute de resolution ;
  3. la detection de retrait de liquidite en direct, via la reserve SOL.

**Cout** : une resolution par lancement (~74/h) et un appel groupe toutes les dix secondes. Ce sont
des appels RPC indexes, pas des cotations de routeur : le chemin de vente n en depend pas, contrairement
a la boucle a 5 s qui avait provoque des 429 bloquant les ventes (§3.55).

**Limite connue** : seul PumpSwap est decode. Meteora DLMM (programme `LBUZKhRx...`, comptes de
904 octets, prix par bins) demande un decodage different et n est pas couvert.

`intel/engines/prix_chaine.py`, branche dans l ordonnanceur sous `solana_prix_chaine`, configure par
`solana.prix_chaine`. N achete rien, ne signe rien.

### 3.66 — Un lancement qui a l'air trop propre se fait vider cinq fois plus, 2026-09-09 21h39

Premiere mesure de la zone T+0 a T+90 s, rendue possible par la lecture des reserves en chaine
(§3.65). 109 courbes exploitables, premier releve median a T+22 s, un point toutes les dix secondes.

**Trois signes, mesures avant T+90 s, tous dans le sens « ca se passe bien » :**

    le prix est au-dessus de son point de depart (var >= +0,7 %)
    il n a JAMAIS baisse depuis le depart (creux >= 0)
    la liquidite a grossi (liq_var >= +0,35 %)

**Taux de vidage selon le nombre de signes reunis :**

    signes    recherche      jugement
      0        6 % (18)      7 % (28)
      1        0 % (8)       0 % (4)
      2       43 % (7)      20 % (10)
      3       43 % (21)     33 % (12)
    regroupe
      0-1      4 % (26)      6 % (32)
      2-3     43 % (28)     27 % (22)
    base globale 19 %

Coherent dans les deux moities, monotone dans les deux. Test du hasard sur la moitie de jugement :
sur 5 000 tirages de 22 pools, **3,9 % font aussi mal**.

**Le mecanisme, qui compte autant que le chiffre.** Un pool controle n a pas de pression vendeuse
reelle, donc pas de creux : l absence de degat est le signe qu il n y a personne en face. Un vrai
lancement a un flux a deux sens, donc desordonne. Le journal a assez d exemples de signaux sans
mecanisme pour qu on exige celui-ci.

**Et le filtre ne coupe pas les ailes en coupant les pertes** -- verification qui a change la lecture :

    groupe        n   vidages   x>=1,5   x>=2   x>=3   issue mediane
    0-1 signe    59      5 %     44 %    34 %   20 %      x0,75
    2-3 signes   50     38 %     32 %    22 %   10 %      x0,38

Le groupe propre a MOINS de vidages ET PLUS de gros gagnants. Sur 31 pools qui font au moins x2
apres la decision, 20 sont dans le groupe propre, qui ne represente que 54 % de l echantillon.

    esperance    tout        -0,109/euro (n=109)
                 0-1 signe   +0,006/euro (n=59)
                 2-3 signes  -0,244/euro (n=50)

**Ecarter la moitie des lancements fait passer la population de -0,109 a l equilibre.**

**Ce que ce resultat n est PAS.** +0,006 par euro est zero, pas un gain. Et c est de l in-sample :
decoupe en deux moities, le meme filtre donne -0,223 puis +0,189. La moyenne, sensible aux queues,
oscille enormement ; seules les statistiques de TAUX (vidages, x1,5, x3) sont stables des deux cotes.
On ne peut donc pas affirmer que ce filtre gagne de l argent -- seulement qu il ameliore la matiere
premiere sur quatre mesures independantes.

**Coupure posee.** Les 139 courbes existantes au 09/09 21h39 sont definitivement in-sample : la
regle en a ete tiree, les remesurer ne ferait que la retrouver. `COUPURE = 1788989940` est inscrit
dans `intel/research/premiere_minute.py`, et `--avant` ne garde que les courbes nees apres. C est le
seul echantillon qui puisse confirmer ou infirmer, et il fallait le declarer AVANT de le regarder.

**MIS EN PRODUCTION le 09/09 a 21h50**, avec deux precautions et une reserve.

`intel/engines/trop_propre.py`, branche dans le moteur juste avant les plafonds de position. Il
ecarte au seuil de deux signes sur trois.

  - *Ce qui justifie de le poser malgre l absence de preuve de gain* : le groupe ECARTE est negatif
    dans les DEUX moities (-0,338 et -0,277 a trois signes). Cesser d acheter un groupe perdant des
    deux cotes ne peut pas couter plus cher que de continuer. Le groupe retenu, lui, est a
    l equilibre : ce filtre retire une perte, il ne cree pas un profit.
  - *Cout en flux, mesure avant de poser* (§3.48) : il ecarte **46 %** des lancements suivis au
    seuil 2, 32 % au seuil 3. Il divise le flux par deux, loin des filtres qui l avaient etrangle a
    un ticket toutes les treize heures.
  - *Il monte en puissance* : sur les 44 lancements achetes cette semaine, 2 seulement ont une
    courbe en chaine -- le collecteur ne tourne que depuis deux heures. Le filtre ne juge que ce
    qu il a mesure et laisse passer le reste, sans quoi il echantillonnerait au hasard au lieu de
    filtrer.

**Le ticket passe de 20 EUR a 5 EUR** dans le meme mouvement. Le carnet rend -0,157 par euro :
a 20 EUR c est -65 EUR par jour pour 111 EUR en caisse, moins de deux jours ; a 5 EUR c est -16 EUR
par jour, sept jours. **La collecte est identique** -- meme flux juge, memes courbes, meme
apprentissage. C est la seule variable qui achete du temps sans couter d information. A remonter
quand le test en avant aura parle, pas avant.

**Premier passage en direct, honnetement** : BATON juge 0/3 (prix -25,8 %, creux -30,4 %, liquidite
-15,2 %), donc laisse passer, puis sorti au stop a x0,50. Le filtre a laisse passer un perdant des
son premier ticket. C est attendu -- le groupe retenu est a l equilibre, il contient donc encore des
perdants -- et cela vaut d etre note ici plutot que de ne consigner que les succes. La perte a fait
-2,5 EUR au lieu de -10 : la baisse de ticket, elle, agit immediatement.

**Prochaine etape, la seule qui vaille** : atteindre ~200 courbes post-coupure et rejouer la mesure
a l identique. Si le groupe propre tient a l equilibre et le suspect a -0,24, on aura le premier
filtre du projet qui repose sur autre chose que de la chance. Sinon ce sera le cinquieme artefact de
la semaine, et il aura coute zero euro.

### 3.67 — Le portage de funding : le seul trade gagnant du projet, et il est mort, 2026-09-09 22h

Les trois familles testees jusqu ici -- lancements memecoin, selection on-chain, fourniture de
liquidite -- consistent toutes a DEVINER. Elles echouent toutes, ce qui est coherent : deviner mieux
que le marche est le metier le plus dur qui existe. Restait a tester une famille qui ne devine rien.

Sur un perpetuel, quand le taux de funding est positif, les acheteurs a effet de levier PAIENT les
vendeurs, mecaniquement, toutes les huit heures. Long au comptant + short le perpetuel annule le
risque de prix et encaisse ce taux. On ne parie pas sur une direction : on facture un service a des
gens presses. Donnees deja sur le disque depuis juillet (`data_onchain/funding_rates.csv`,
82 245 lignes, 27 actifs, 2019-2026) et jamais ouvertes.

    PANIER EQUIPONDERE, 2 506 jours          brut +3,56 %/an   net de 2 % +1,56 %
    LES 3 TAUX LES PLUS HAUTS                brut +9,71 %/an   net       +7,71 %   99 % de mois positifs
    SEUIL taux >= 0,0005                     brut +24,72 %/an  net      +22,72 %   48 % de mois positifs

**Le premier resultat vraiment gagnant de tout le projet.** +7,71 % net par an avec 99 % de mois
positifs sur six ans, sans jamais rien prevoir. Le pire mois du panier fait -0,40 %, la pire annee
-0,90 %.

    par annee   2020 +6,47   2021 +12,74   2022 -0,73   2023 +1,94   2024 +3,82   2025 +0,21   2026 -0,90

**Et il est arbitre.** Sur 2025-2026 : le panier fait -0,45 % brut, la selection des trois plus hauts
+1,70 % brut soit **-0,30 % net**. Tout le monde connait ce trade ; des que le funding monte, les
arbitragistes l ecrasent. La variante a seuil eleve (+24,72 %) n a que 48 % de mois positifs : ce ne
sont pas des revenus reguliers, ce sont des aubaines de periode de mania.

**Ce que ce resultat apprend, au-dela du trade lui-meme :**

  1. **Le seul trade gagnant trouve en une semaine ne predit rien.** Il encaisse. C est coherent avec
     ce que montre §3.62 sur qui gagne reellement : teneurs de marche, arbitragistes, createurs --
     personne ne devine, chacun facture ou sait.
  2. **Un edge mecanique et public se fait arbitrer.** Six ans de +8 %, puis zero. Ce qui se mesure
     dans un fichier CSV se mesure aussi chez tous les autres.
  3. **Le capital est la contrainte, pas la strategie.** 8 % par an sur 200 EUR font 16 EUR. Pour que
     ce type de rendement compte il faut six chiffres. C est ce qui rend les memecoins attirants --
     le seul endroit ou 200 EUR peuvent devenir 2 000 -- et c est la meme volatilite qui produit le
     x10 et le /6. Les deux ne sont pas separables ; l issue mediane mesuree est x0,17.

**Ce que ce fichier NE mesure PAS** et qu il faut dire : le risque d execution -- liquidation du
short si la base diverge, defaillance de plateforme, retrait de cotation. Des chiffres historiques
ne les montrent pas.

`scripts/carry_funding.py`. Aucune position, aucun ordre.

### 3.68 — Ce que la litterature dit, et ce qui transfere, 2026-09-09 23h

L operateur a demande d elargir : lire ce qui est publie sur les DEX, et construire a partir de la
au lieu de tatonner. Trois familles de travaux, lues le soir meme.

**1. Detection de rug pull -- Yaremus et al. 2025, TON, arXiv 2509.01168.** 48 380 jetons sur
Ston.Fi et DeDust, gradient boosting, **AUC 0,885-0,891 dans les 5 premieres minutes** (approche
TVL : chute de plus de p % depuis le pic de liquidite dans la premiere heure). Variables de tete :
`max_tvl_5min`, `jetton_creation_trade_delta` (delai creation du jeton -> premier echange),
`first_buy_time` ; pour l approche Idle : `total_usd_volume_5min`, `buys_5min`, `is_pool_creator`.
Table 1 du papier : 33 variables, toutes lisibles a T+5 min.

**2. Graduation pump.fun -- Kamat 2026, arXiv 2607.02823.** 832 941 lancements, Cox
proportionnel, concordance 0,858. **Telegram : HR 5,40**, lift x8,94 ; les trois reseaux : x17,4 ;
log capitalisation initiale : HR 4,51. Seuls 0,2-0,6 % des lancements graduent. Nous ne voyons
donc deja que l elite -- ce qui explique en partie pourquoi les filtres d entree ne trient plus
rien apres migration : le gros du tri est fait avant.

**3. Momentum crypto -- Liu & Tsyvinski 2021, Liu, Tsyvinski & Wu 2022.** Momentum de serie
temporelle a 1-4 semaines ; les gagnants font 1,65 %/semaine (Sharpe 1,28) contre 0,62 % pour les
perdants ; modele a trois facteurs marche / taille / momentum ; pas de retour a la moyenne a court
terme. Fondement de « acheter la survie plutot que la naissance » (§3.69).

**Ce que personne n a publie** : les rendements APRES graduation. La litterature s arrete ou le
suivi long (§3.69) commence.

**Transfert a PumpSwap, mesure.** `intel/research/features_lancement.py` construit les variables du
papier TON sur nos lancements avec courbe en chaine, etiquette definie comme chez eux (reserve SOL
sous 20 % de son pic, p = 0,80) ; `scripts/modele_rug.py` refait leur modele. Sonde prealable :

  - le delai creation -> migration EST lisible (pagination obligatoire : sans elle un jeton a plus
    de mille signatures donne une date proche de la migration, d ou deux deltas de « 1 s » a la
    premiere sonde) ;
  - le createur du mint EST lisible, et la sonde a attrape un **lanceur en serie** : `7tb75Wsa…`
    a migre deux jetons a quinze secondes d intervalle ;
  - `is_pool_creator` vaut 0 sur 120 : sur PumpSwap le pool est cree par le programme. La variable
    ne transfere pas ;
  - les metadonnees sociales : pump.fun repond 530, le PDA Metaplex est absent sur les mints
    recents (Token-2022 ?). Champ laisse optionnel.

**Resultat, 120 lancements, 33 % de rugs, 5 plis stratifies :**

    gradient boosting (le modele du papier)   AUC 0,595 ± 0,076
    regression logistique                     AUC 0,544 ± 0,067
    signes_trop_propre seul (§3.66)           AUC 0,463 ± 0,104
    hasard                                    AUC 0,500
    papier de reference                       AUC 0,885-0,891
    cible « multiple a T+15 min »             IC +0,023

**Les variables du papier ne transferent pas a cet echantillon** -- ou l effet est trop faible pour
apparaitre sur 120 lignes la ou ils en avaient 48 000. L intervalle de l AUC va de 0,52 a 0,67.

**Et le filtre « trop propre » sort SOUS le hasard sur cette etiquette.** Avertissement serieux,
mais qui ne tranche pas seul : l etiquette du modele (chute depuis le pic, 90 premieres secondes
comprises) n est pas celle de §3.66 (chute depuis la reserve a T+90 s). Le test en avant, defini
AVANT de regarder, dit autre chose a 62 courbes post-coupure :

    0-1 signe    30 courbes   13 % vides   -0,194/euro
    2-3 signes   32 courbes   31 % vides   -0,402/euro

La direction tient, affaiblie (x2,4 au lieu de x4-7) -- ce qu on attend d un vrai effet hors
echantillon. **Verdict provisoire : le filtre tient en avant ; on ne conclut pas avant 100.**

**Ce que l exercice apprend :** un modele publie a 0,89 sur une chaine ne se transporte pas par
decret sur une autre. Les mecanismes (liquidite initiale, delai de creation, volume des premieres
minutes) sont plausibles partout ; les seuils et les poids ne le sont pas, et 120 lignes ne
suffisent pas a les reapprendre. La seule reponse est plus de donnees -- et le collecteur en
chaine en produit ~90 par heure.

### 3.69 — Acheter la survie ne marche pas non plus, 2026-09-10 matin

La derniere hypothese ouverte de la veille : ne pas acheter la naissance, acheter ce qui a tenu une
heure, et tenir des heures -- ce que l operateur a fait sur 2dDDte (x3,13 en quatre heures) et ce que
l ecran de DexScreener suggere (+400 % a dix-sept heures d age). Personne ne l avait mesure : toute
la recherche s arretait a T+30 min. `intel/engines/suivi_long.py` a collecte 13 h : 1 578 pools,
951 suivis au-dela de 12 h, 60 000 releves. `intel/research/survie.py` pose la question.

**Ce que devient un lancement qui a tenu une heure**, depuis son prix a T+1 h (286 lancements) :

    horizon   fin mediane   x>=1,5   x>=2   x>=3   perd la moitie   tenir, par euro
    T+2 h        x0,99       17 %    11 %    7 %        26 %            -0,152
    T+3 h        x0,95       16 %     9 %    7 %        32 %            -0,219
    T+6 h        x0,94       13 %     8 %    4 %        33 %            -0,270

La survie a une heure ne change pas la distribution : le jeton median ne bouge pas, un tiers perd la
moitie, 7 % triplent. Le x3,13 de l operateur est dans les 7 %.

**Aucune sortie ne sauve la mise** (recherche / jugement) : tenir 3 h -0,283 / -0,098 ; stop
suiveur 30 % sur 6 h -0,243 / -0,155 ; stop 50 % sur 12 h -0,330 / -0,171. Le stop suiveur, qui
faisait tout le gain du stop-suiveur fantome de §3.51, ne fait rien ici non plus.

**Aucune condition d entree a T+1 h ne tient** : 1 regle sur 36 est positive des deux cotes
(`cap <= 1 830 $`, +0,030 / +0,005 sur 43 / 43 -- des pools de poussiere), et 15 % des tirages au
hasard de meme taille font mieux. Liquidite, volume, flux acheteurs/vendeurs, variation horaire :
rien ne trie.

**Pourquoi l ecran trompe.** DexScreener « New / Trending » affiche les gagnants du moment. Les
26 a 33 % qui ont perdu la moitie dans le meme intervalle ne sont pas sur l ecran. C est un biais de
survivant en direct, et il est d autant plus fort que le classement est par performance.

**Reserves.** 13 h de collecte, 110 pools seulement a 6 h ; les deux moities different (-0,24 contre
-0,16), donc les niveaux bougent. Mais le SIGNE ne bouge pas : toutes les cases sont negatives, a
tous les horizons, dans les deux moities. Rejouer a 500 pools dans deux jours ; on ne s attend pas a
un renversement.

**Bilan des familles testees depuis le 08/09**, toutes sur moitie tenue a l ecart :

    acheter la naissance (T+2 min), 200 regles d entree, 40 sorties      aucun edge
    filtre « trop propre » (premiere minute)                               reduit les rugs, pas la perte
    facteur on-chain sur 3 periodes                                        moins que le hasard
    fournir la liquidite                                                   pire sur memecoin, ~3 %/an sur majeurs
    portage de funding                                                     +8 %/an 2019-2024, zero depuis
    acheter la survie (T+1 h), 36 regles, 7 sorties                        aucun edge

Le seul resultat positif mesure reste celui du 09/09 : le trading manuel de l operateur, +30 % sur
trois jours, un trade sur deux gagnant. Ce n est pas une strategie reproductible par une regle --
c est exactement ce que dit la distribution : 7 % de x3 et 26 % de moitie, et il a pris un des 7 %.

### 3.70 — Le flux en argent, et l'absorption : le premier signal stable, 2026-09-10

Deux questions de l operateur, en regardant l onglet Txns de DexScreener. La seconde a produit le
seul resultat de la semaine qui survive a tous les controles -- sans pour autant gagner de l argent.

#### Le flux en ARGENT, pas en nombre

Le nombre d echanges avait ete teste et rejete (§3.69) : cent achats d un dollar coutent un dollar
de frais et fabriquent une belle colonne verte. Le MONTANT coute ce qu il pese. DexScreener ne le
separe pas par sens ; on le calcule a la source, depuis les DEUX reserves lues toutes les dix
secondes : le SOL monte et le jeton baisse -> un achat de ce montant ; l inverse -> une vente ; les
deux dans le meme sens -> un depot ou un retrait de liquidite, qu il faut ecarter sous peine de
prendre un retrait pour une vente geante. Le flux NET est exact malgre la resolution (il se
telescope) ; le volume brut est une borne inferieure. `intel/research/flux.py`.

**Ce que ca donne, 477 pools, quartiles du desequilibre acheteur sur 90 s :**

    quartile           mediane   moy/euro   vides   x>=1,5   x>=3
    vend le plus        -33,4 %   -0,048     11 %    45 %     14 %
    2                   -73,8 %   -0,395     32 %    47 %     15 %
    3                    +1,5 %   -0,250     28 %    21 %      4 %
    achete le plus       +3,5 %   +0,111      3 %     4 %      2 %

Ca separe fortement, et **dans le sens inverse de l intuition** : les pools ou personne ne vend sont
surs et morts (3 % de vidages, 2 % atteignent x3) ; ceux ou ca vend fort sont dangereux et vivants
(jusqu a 32 % de vidages, 14-15 % atteignent x3). **35 des 42 gros gagnants sont dans les deux
quartiles vendeurs.**

Mais aucune regle n en sort : 0 sur 48 tient des deux cotes. « Achete le plus » fait -0,183 en
recherche et +0,157 en jugement -- signe oppose -- et sa moyenne positive tombe a -0,023 quand on
retire sa meilleure ligne. Seule la MEDIANE est stable (+2,9 / +3,5 / +3,4 % sur trois echantillons),
et +3 % contre un peage de 2 % ne fait pas une strategie.

#### L absorption : prix qui se stabilise PENDANT que ca achete

Question suivante de l operateur, plus fine : la CONJONCTION. Ni le prix seul (§3.66) ni le flux
seul, mais le prix qui cesse de bouger tandis que l argent continue d entrer. Fenetre
T+180 s a T+300 s, decision a T+300 s, resultat a T+900 s. `intel/research/absorption.py`.

    groupe                        n   moy/euro   sans best   mediane   x>=1,5
    plat + achete (absorption)  177    -0,086     -0,092      +1,1 %     2 %
    plat + vend (distribution)   55    -0,129     -0,181     -19,8 %    15 %
    bouge + achete              114    -0,319     -0,354     -51,3 %    28 %
    bouge + vend                117    -0,198     -0,267     -43,2 %    39 %

**C est le premier resultat de la semaine qui ne tienne pas sur une ligne** : « sans sa meilleure
ligne » ne bouge pratiquement pas (-0,086 -> -0,092), la ou six resultats precedents changeaient de
signe. Coherent dans les deux moities (-0,150 puis -0,038, le moins mauvais des quatre groupes des
deux cotes). Et **le test en avant, defini avant de regarder** : -0,062/euro sur 148 courbes nees
apres la coupure, contre -0,179 de reference, avec **0,1 % des tirages au hasard qui font aussi
bien**.

#### Mais l ingredient actif n est pas celui qu on croit

Test de monotonie, qui separe un mecanisme d une coincidence :

    A. par platitude, a flux acheteur constant     -0,037  -0,059  -0,363  -0,247
    B. par force du flux, a prix plat constant     -0,143  -0,037  -0,059  -0,146

La platitude ordonne (les deux quartiles les plus plats a ~-0,05, les deux plus agites a ~-0,30).
**La force du flux ne l ordonne pas : c est un U.** « Achete le plus » est aussi mauvais que « vend
le plus ». **Ce qui porte l effet, c est que le prix arrete de bouger -- pas que ca achete.** Un
achat massif est du bruit au meme titre qu une vente massive ; c est l absence de mouvement qui
distingue.

Cela recoupe §3.66 : les pools « trop propres » (achat pur, aucun creux) etaient mauvais. Les
extremes des deux cotes le sont.

#### Ce que ca vaut, honnetement

    acheter tout            -0,179/euro   -3,57 EUR par ticket de 20
    acheter l absorption    -0,062/euro   -1,24 EUR par ticket de 20
    ecart                   +0,117/euro   +2,33 EUR par ticket · 42 % du flux garde

**Ca ne gagne pas.** Ca divise la perte par trois. Et le groupe retenu est celui ou il ne se passe
rien : **2 % atteignent x1,5**, contre 28-39 % dans les groupes agites. C est un signal DEFENSIF --
il designe l endroit ou on ne perd presque pas et ou on ne gagne pas.

**Reserves :** 463 pools, 13 h de collecte, horizon de dix minutes seulement (T+300 s a T+900 s). Le
seuil de platitude est la mediane de l echantillon, donc relatif -- a refixer en absolu avant tout
usage. A rejouer a 1 000 pools et sur un horizon d une heure via `solana_suivi_long`.

### 3.71 — Le filtre « trop propre » confirme en avant : le premier edge du projet, 2026-09-12

La coupure posee le 09/09 a 21h39 avait brule 139 courbes et declare a l avance ce qui pourrait
confirmer ou infirmer. Deux jours de collecte plus tard, **2 582 courbes nees apres la coupure**,
jamais regardees, contre 364 au premier essai. Le verdict :

    groupe            n     vides   x>=1,5   x>=3   par euro
    0-1 signe      1 280      16 %    31 %    11 %   +0,188
    2-3 signes     1 302      28 %    23 %     4 %   -0,257
    reference      2 582      22 %    27 %     8 %   -0,036

Sur 3 000 tirages au hasard de 1 302 courbes, **aucun** n atteint le taux de vidage du groupe
ecarte. Le filtre separe sur les quatre mesures a la fois, dans le meme sens, et l ecart de
rendement est de 0,44 par euro entre les deux groupes.

**Ce qui tient au controle :**

    moities du test en avant   0-1 signe +0,232 puis +0,154 · 2-3 signes -0,256 puis -0,259
    peage 2 %  +0,189      5 %  +0,152      10 %  +0,091      15 %  +0,031

Coherent dans les deux sous-moities, et survit a des frais bien au-dela des 2 % de reference.

**Ce qui NE tient PAS, et qui change tout :**

    complet +0,189 · sans la meilleure ligne +0,067 · sans les cinq meilleures -0,130
    gagnants 31 % · ticket median -26,2 % · le meilleur ticket +15 507 % (x156)

Cinq courbes sur 1 280 portent 169 % du gain total. Ce n est pas une strategie qui gagne
regulierement : c est une loterie a esperance positive. Le ticket TYPIQUE perd un quart de la mise.

**Combien de tickets pour que l esperance se realise** (4 000 simulations par ligne) :

    tickets    chance de gain    mediane (en mises)    pire decile
        20          31 %              -3,2               -7,9
       100          42 %              -5,9              -23,7
       250          61 %             +23,1              -44,2
       500          74 %             +74,0              -56,1
     1 000          85 %            +172,8              -30,4
     2 000          94 %            +359,1              +64,1

**Sous 250 tickets on perd plus souvent qu on ne gagne.** C est exactement ce que le carnet reel a
vecu : 44 tickets sur sept jours, -129 EUR. Le carnet n a jamais eu tort sur la methode, il n a
jamais eu assez de tickets -- et il n avait pas le filtre.

**Le plan chiffre**, avec 1 500 EUR et des tickets de 5 EUR, 500 tickets en ~25 jours au rythme
actuel : mediane +378 EUR, gain dans 73 % des cas, pire decile -292 EUR.

**Ce que ce resultat corrige dans le journal.** §3.66 concluait « reduit les rugs, pas la perte » et
§3.58 « aucun edge a l entree ». Les deux etaient justes SUR LEUR ECHANTILLON -- 109 et 302 courbes.
A 2 582 courbes le meme filtre, non modifie, sort a +0,188. La difference n est pas la regle, c est
la taille. **Une loterie a queue lourde ne se juge pas sur des centaines de tirages ; il en faut des
milliers**, et tout ce que ce journal a declare mort avant le 12/09 l a ete sur des echantillons
trop petits pour trancher.

**Ce qui reste a faire avant d y engager de l argent :**
  1. rejouer a 5 000 courbes -- l edge doit survivre a un doublement de l echantillon ;
  2. verifier sur le CARNET REEL : le simulateur reste DexScreener, deux fois trop pessimiste
     (S3.61), donc le chiffre reel devrait etre MEILLEUR, mais cela se mesure et ne se suppose pas ;
  3. verifier que le filtre laisse passer assez de flux -- il garde 50 %, soit ~10 tickets par jour
     au rythme actuel, donc 500 tickets demandent 50 jours et non 25.

### 3.72 — Les reseaux sociaux, a l'envers du papier : le meilleur signal du projet, 2026-09-12

L operateur, apres que j ai dit ne pas savoir detecter les bonnes fenetres : « ton role c est pas
d analyser cette periode et de detecter ce qu elle a de particulier ? » -- puis, quand j ai propose
d aller chercher le social : « pourquoi tu me demandes que maintenant ». Il avait raison : le papier
pump.fun etait lu depuis mardi (S3.68) et je n avais pas collecte sa variable de tete.

**Pourquoi la collecte avait echoue le 09/09, et ce n etait pas une absence de donnee.** Deux
erreurs empilees, toutes deux silencieuses :

  1. je cherchais les metadonnees dans un compte Metaplex separe. Ces jetons sont en **Token-2022**
     et les portent DANS le compte du mint (extension `tokenMetadata`) -- d ou un PDA vide et la
     conclusion erronee que la donnee n existait pas ;
  2. la passerelle IPFS par defaut (`ipfs.io`) repond 429 des qu on enchaine. Tous les champs
     revenaient vides **sans qu aucune erreur ne le signale**. Avec la passerelle dediee de pump.fun
     (`pump.mypinata.cloud`) : **81 % de reussite contre 8 %**.

Deuxieme fois cette semaine qu une source muette passe pour une source vide (S5.30 pour le prix
aberrant de HYPE). Une lecture qui echoue doit le DIRE.

**Le resultat, sur 404 lancements ayant courbe et fiche :**

    groupe               n    vides   x>=1,5   x>=3    par euro
    tous               404     25 %    32 %     9 %    +0,320
    aucun reseau       200      8 %    30 %    13 %    +0,981
    les trois reseaux   31     61 %    52 %     6 %    -0,550
    avec Telegram       43     47 %    47 %     7 %    -0,392
    sans Telegram      361     22 %    31 %     9 %    +0,405

**C est l inverse exact du papier**, et ce n est pas une contradiction : Kamat mesure la
GRADUATION, moi ce qui se passe APRES. Les reseaux aident a graduer ; parmi les jetons qui ont
gradue, en avoir signifie que la graduation a ete **fabriquee**. Un jeton qui gradue sans aucune
promotion l a fait sur de la demande reelle. Le meme fait vu des deux cotes de la migration.

**Et le croisement avec le filtre de forme (S3.71) montre deux effets INDEPENDANTS :**

    reseaux         forme         n    vides    par euro
    aucun           0-1 signe   146      4 %    +1,456
    aucun           2-3 signes   78     14 %    -0,316
    au moins un     0-1 signe    75     40 %    -0,339
    au moins un     2-3 signes  151     42 %    -0,323

**4 % de vidages contre 42 %** -- six morts sur 146. Le taux de vidage est une proportion, donc
insensible aux valeurs extremes, et il est **stable entre les deux moities** : 8 % puis 7 % sans
reseaux, 32 % puis 50 % avec. Sur 3 000 tirages au hasard, aucun n atteint le taux du groupe ecarte.

**Ce que ca donne en pratique** -- groupe « aucun reseau ET 0-1 signe », 34 % du flux, n=201 :

    tickets   chance de gain   mediane (en mises)   pire decile
        50          71 %             +9,8             -7,7
       100          83 %            +66,3             -6,3
       250          96 %           +247,3            +42,9
       500         100 %           +513,8           +212,8

A comparer au filtre de forme seul (S3.71) : 42 % de chance de gain a 100 tickets, contre 83 % ici.

**RESERVES, et elles sont serieuses :**
  - 201 lancements, 2,6 jours, UNE seule fenetre de marche -- exactement la critique que l operateur
    a portee sur S3.71 et qui reste valable ici ;
  - la moyenne reste portee par la queue : +107,9 % de moyenne pour un ticket median a -25,7 % ;
  - la collecte sociale ne couvre que 432 des 2 831 jetons ; le remplissage complet tourne.

**Le seul chiffre vraiment robuste est le taux de vidage** : 4 % contre 42 %, sur des proportions,
stable entre moities. Meme si le rendement ne se confirmait pas, diviser la mortalite par dix change
la nature du jeu.
### 3.73 — Telegram : ce n'est pas le signal qui était faux, c'est la durée de détention, 2026-09-12

L'opérateur, après que je lui ai dit ne rien trouver de concluant : « Non mec je veux chercher un
truc qui gagne de l'argent putain cherche problème **Telegram fonctionne sur une durée de vie
limitée** ou un truc comme ça croise tout stp ».

Son intuition était juste et **la mienne était fausse**. §3.72 annonçait « avec Telegram, −0,392 par
euro », donc Telegram comme signal NÉGATIF. Ce chiffre était mesuré sur une seule règle de sortie :
tenir quinze minutes. Or tenir n'est pas une stratégie, c'est l'absence de stratégie.

**Le profil temporel, mesuré sur 2 560 courbes** (`intel/research/croise.py`, nées du 09/09 20 h au
12/09 13 h, coupées en deux par date de naissance) :

    durée de détention   1 min   2 min   3 min   4 min   5 min   6 min   8 min   10 min   15 min
    telegram, jugement   +0,07   +0,07   +0,14   +0,17   +0,21   +0,15   +0,07    −0,03    −0,34

Le même groupe passe de **+0,17 à −0,34** selon qu'on sort à quatre minutes ou à quinze. §3.72 ne
mesurait pas Telegram, il mesurait l'effondrement qui suit le pic.

**Le résultat, moitié de JUGEMENT seule** (n=95, jamais regardée pendant la recherche) :

    groupe             n      gagnants   médiane   par euro
    population      1 280       48 %      −0,3 %    +0,061
    avec Telegram      95       69 %      +4,3 %    +0,174

Sur **20 000 tirages au hasard** de 95 jetons pris dans la même population, **zéro** fait aussi bien,
ni sur le taux de gagnants ni sur la médiane. Sur la moyenne, 11,6 % font mieux — et c'est normal :
la moyenne de la population est portée par sa queue, la moyenne est donc le mauvais test ici.

**Pourquoi ce résultat n'est pas comme les six familles enterrées cette semaine.**

  1. **Il ne tient pas sur une loterie.** Le meilleur ticket du groupe Telegram fait **x3,4** — celui
     du groupe « 0-1 signe » fait x286. Retirer la meilleure ligne fait passer le gain de +0,174 à
     +0,154 : il reste. Toutes les trouvailles précédentes s'effondraient à ce test.
  2. **Il n'est pas concentré sur trois fenêtres.** Huit tranches de 6 h sur onze sont positives.
     C'était exactement la critique que l'opérateur avait portée sur §3.71, et elle tombe ici.
  3. **Il survit au retard d'entrée.** Entrer 30 s après la décision : +0,173. 60 s : +0,151.
  4. **Il survit au péage.** À 10 % de frais aller-retour, retard de 30 s compris : +0,077.
  5. **Le témoin est plat.** Les mêmes jetons SANS Telegram, même retard, même péage : +0,022.

**Le mécanisme, qui compte autant que le chiffre.** Kamat 2026 mesure que le Telegram multiplie par
8,9 le taux de graduation. Le canal n'est pas magique : il donne au lancement une audience réelle,
donc un flux d'achat qui dure quelques minutes — puis cette audience s'épuise. §3.72 et §3.73 ne se
contredisent pas : la promotion fabrique une montée, et une montée fabriquée retombe. Il faut être
dedans pendant, et dehors après.

**Twitter ne fait pas le travail.** Twitter sans Telegram : n=1 010, 54 % de gagnants, jugement
−0,019. C'est bien Telegram qui discrimine, et 165 des 171 jetons Telegram ont aussi Twitter.

**Le filtre `trop_propre` (§3.71) ne doit PAS s'appliquer ici**, et c'est important :

    groupe                          n    gagnants   médiane   recherche   jugement
    telegram + 0-1 signe (gardé)    64      50 %     +0,0 %     +0,190     +0,177
    telegram + 2-3 signes (rejeté) 107      76 %     +4,3 %     +0,134     +0,173
    sans tg + 0-1 signe (gardé)  1 236      32 %     −2,0 %     +0,494     +0,137
    sans tg + 2-3 signes (rejeté)1 153      61 %     +0,6 %     −0,031     −0,048

Le filtre écarterait **107 des 171 jetons Telegram**, qui rapportent +0,156 par euro. Il a été
mesuré sur la population générale, où le groupe 2-3 signes perd ; sur les jetons Telegram il gagne.
**Le Telegram passe devant.** Leçon générale : un filtre mesuré sur une population ne se transporte
pas dans un sous-groupe sans être remesuré dedans.

**Ce qui est en place**, `intel/engines/telegram_rapide.py`, à blanc depuis le 12/09 14 h 30 :
entrée à T+90 s si la métadonnée du mint porte un Telegram, sortie quatre minutes plus tard. Quatre
minutes et non cinq : à 4 min les deux moitiés disent la même chose (+0,156 et +0,174), à 5 min la
moitié de recherche tombe à +0,055. On prend le point stable, pas le sommet du balayage.

La lecture bout en bout prend **0,17 s en médiane et 0,64 s au pire** sur 40 jetons lus en direct :
la fenêtre de 90 s n'est pas une contrainte. Le flux donne **environ 2 jetons avec Telegram par
heure**, soit 55 par jour — cent tickets en moins de deux jours.

**RÉSERVES.** 2,7 jours, une seule fenêtre de marché.

**PASSAGE EN RÉEL, 12/09 15 h 10.** Mis devant cette réserve, l'opérateur a répondu « Ok va passer
en prod juste dis moi le rythme d'achat il sera de combien ». Le moteur tourne donc en réel sur le
portefeuille du robot (71,60 € au basculement), mise de 10 €, six lignes simultanées au plus.

**Rythme mesuré au basculement**, et c'est la réponse à sa question :

    43 à 51 lancements par heure (1 217 sur 24 h)
    × 92 % couverts par le collecteur de courbes, sans redémarrage
    × 6,6 % portant un Telegram (181 sur 2 744 fiches lues)
    = 2,5 à 3 achats par heure, soit 60 à 70 par jour

À 10 € le ticket : 600 à 700 € de volume par jour pour **60 € immobilisés au pire**, puisque chaque
ligne ne dure que quatre minutes. La couverture tombe à 59 % quand on redémarre le moteur : trois
reconstructions dans l'heure ont coûté 41 % du flux.

**Premier aller-retour réel, FOMOBRAIN, 15 h 13 → 15 h 17.** Acheté 4,43e-07, vendu 8,79e-07, soit
**x1,98 sur le prix des réserves**. Le portefeuille, lui, a encaissé **+0,08148 SOL soit +7,69 €**
sur 10 € — donc **x1,77 réellement**. L'écart est le péage réel : **10,7 % sur l'aller-retour**, et
non les 2 % du calcul à blanc. Un seul ticket ne fixe pas un péage, mais s'il se confirme il ramène
l'espérance de +0,174 à environ **+0,077 par euro** (ligne « 10 % » du tableau de sensibilité).
C'est le chiffre à surveiller en premier, avant même le taux de gagnants.

**Ce qui protège l'argent et ne vient pas de la mesure :** la cotation de la REVENTE avant l'achat
(refus au-delà de 15 % d'aller-retour), parce que cinq pools sur vingt-cinq sont invendables à notre
taille (§3.36) et que la mesure ci-dessus lit des réserves, qui ne disent rien de la contrepartie.
Et le résultat d'une ligne réelle se lit sur le solde du portefeuille, jamais sur une cotation.

**DEUX PISTES TESTÉES ET MORTES, 12/09 16 h.** Toutes deux nées de l'observation des trois premiers
tickets. Notées ici pour ne pas être retestées.

*Le stop suiveur ne marche pas.* TRUMPBRAIN était monté à x2,10 à 108 s puis redescendu à x0,98 à la
sortie : un stop suiveur semblait évident. Sur les 174 jetons Telegram il dégrade à TOUS les
réglages, et de façon monotone.

    recul toléré    aucun    −15 %   −20 %   −25 %   −30 %   −40 %   −50 %
    jugement       +0,171   +0,034  +0,042  +0,114  +0,118  +0,121  +0,146

Plus le stop est lâche, plus on se rapproche de ne rien faire : c'est la signature d'un coût pur.

*Le vidage de liquidité n'est pas prévisible avant l'achat.* batonfly a perdu 64 % de son pool entre
deux relevés espacés de dix secondes (81,9 → 29,5 SOL, x1,06 → x0,18), après être monté à x1,51.
**11 % des jetons Telegram sont vidés pendant les quatre minutes de détention et coûtent −0,72 par
euro** ; les enlever ferait passer la règle de +0,171 à +0,270. Les vidés montent effectivement plus
vite avant l'entrée (hausse médiane +9,0 % contre +1,2 %, liquidité +5,3 % contre +0,6 %) — mais
l'écart des médianes ne sépare pas les populations :

    on garde si            vides (jugement)   recherche   jugement
    tout                        12 %            +0,143     +0,181
    hausse ≤ 10 %               10 %            +0,135     +0,162
    liquidité ≤ +5 %             9 %            +0,118     +0,176

Aucun filtre ne bat « ne rien filtrer », et aucun n'enlève les vidages : 12 % deviennent 9 ou 10 %
pour 30 % de flux perdu. **Un écart de médianes n'est pas un pouvoir de séparation**, et c'est la
troisième fois cette semaine que je manque de le vérifier avant d'y croire.

**PAS DE FUITE DU FUTUR : LA MÉTADONNÉE EST GELÉE, 12/09 18 h.** Question de l'opérateur, et elle
visait juste : « une chaîne Telegram peut être créée après l'existence de la crypto ». Si le lien
Telegram pouvait être ajouté après une hausse, la mesure serait une illusion — j'ai lu le 12/09 des
fiches de jetons nés le 09/09, donc j'aurais cru prédire ce qui était déjà arrivé.

Vérifié sur 40 jetons portant un Telegram, tirés au hasard : **`updateAuthority` vaut `None` pour
les 40**. Personne ne peut modifier la métadonnée, pas même le créateur. Et 39 sur 40 pointent vers
un contenu IPFS adressé par son empreinte, donc changer un caractère change l'adresse. Ce que j'ai
lu après coup est exactement ce qui était lisible à T+90 s.

Conséquence sur ce qu'est vraiment le signal : ce n'est pas « ce jeton a une communauté », c'est
**« le créateur avait prévu une communauté avant de lancer »** — une intention déclarée publiquement
et irrévocablement au moment zéro. Un canal ouvert plus tard est invisible au moteur, qui ne
l'achètera jamais. Ça reste cohérent avec le mécanisme : celui qui prépare son canal avant de lancer
amène une audience réelle dans les premières minutes, et c'est elle qui achète pendant qu'on tient.

**Méthode.** Avant de croire une variable lue après coup, vérifier qu'elle ne pouvait pas être
écrite après coup. Ici la chaîne le garantit ; ailleurs il faudra l'horodater à la lecture.

**L'HEURE D'ENTRÉE ÉTAIT UN RÉGLAGE HÉRITÉ, PAS UNE MESURE, 12/09 18 h 30.** Question de
l'opérateur : « on achète à T+60 ou même avant ? ». T+90 ne venait d'aucune mesure — il venait de ce
que le filtre `trop_propre` avait besoin de quatre relevés avant de juger. Or le Telegram est dans
la métadonnée, lisible dès la première seconde.

    entrée      T+15    T+30    T+45    T+60    T+75    T+90    T+120
    recherche  +0,378  +0,168  +0,158  +0,197  +0,162  +0,268  +0,104
    JUGEMENT   +0,090  +0,107  +0,255  +0,194  +0,206  +0,151  +0,147
    sans best  +0,065  +0,090  +0,158  +0,174  +0,169  +0,130  +0,122

**T+60 retenu** : les deux moitiés s'y accordent et « sans best » y est le plus haut. Le balayage
CONJOINT entrée × tenue (30 cases) confirme sans l'avoir cherché : T+60 / 4 min est la case au plus
petit écart entre moitiés de toute la grille (0,002), et ses voisines tiennent — un plateau, pas un
pic. Coût : 3 % du flux, 91 % des jetons ont un prix lisible dès T+60 contre 94 % à T+90.

Et « ou même avant » est **non** : T+15 et T+30 tombent à +0,090 et +0,107 en jugement. Le signal
Telegram annonce une audience qui va arriver, pas une qui est déjà là.

**LE MÊME BALAYAGE, REFAIT PROPREMENT, 13/09.** L'opérateur redemande : « le choix de 60 a été
étudié ? t'avais vérifié qu'acheter avant était pas bon ? ». En lui répondant j'ai vu le défaut du
premier balayage : il prenait « le premier relevé à *t* secondes ou plus », si bien qu'un jeton dont
le premier relevé arrive à 40 s entrait dans la tranche T+15. **Les tranches précoces étaient
contaminées par des entrées tardives.** Refait en exigeant un relevé à ±10 s de la cible :

    cible      n    couvert   recherche   JUGEMENT   sans best
    T+15     168      88 %     +0,415     +0,101      +0,072
    T+20     176      92 %     +0,385     +0,087      +0,060
    T+30     184      96 %     +0,173     +0,102      +0,082
    T+40     185      97 %     +0,220     +0,111      +0,094
    T+50     187      98 %     +0,194     +0,218      +0,122
    T+60     187      98 %     +0,255     +0,181      +0,157
    T+75     187      98 %     +0,364     +0,187      +0,157
    T+90     187      98 %     +0,264     +0,139      +0,117

La conclusion ne bouge pas et se durcit : **acheter tôt est mesurablement moins bon**, pas neutre.
T+15 à T+40 donnent +0,087 à +0,111 en jugement et +0,060 à +0,094 sans leur meilleure ligne, contre
+0,157 à T+60. Les écarts énormes entre moitiés dans ces tranches (+0,415 contre +0,101) sont la
signature du bruit. T+60 et T+75 sont à égalité sur le critère le plus dur, « sans best ».

Entrer tôt coûte aussi du flux : à T+15, 88 % des jetons ont un relevé, contre 98 % à partir de
T+50. On paierait deux fois pour être en avance.

**Méthode.** Une tranche horaire définie par « à partir de *t* » n'est pas une tranche : c'est un
fourre-tout qui aspire tout ce qui vient après. Exiger un point DANS la fenêtre, pas après elle.

**RIEN NE MARCHE SUR LES 93 % SANS TELEGRAM, 12/09 19 h.** La stratégie ignore 2 546 des 2 729
lancements. Testé, entrée T+60, tenue 4 min, deux moitiés :

    règle                       n    recherche   jugement   sans best
    aucun réseau             1 339     -0,066     +0,164      +0,054
    description vide         1 092     -0,042     +0,224      +0,090
    twitter seul               331     +2,102     +0,017      -0,026
    pool >= 100 SOL          1 031     +0,009     +0,035      +0,018
    pool < 70 SOL            1 158     +0,529     +0,179      +0,060

Tout change de signe entre les deux moitiés, ou vaut zéro. `twitter seul` à +2,102 contre +0,017 et
`pool < 70 SOL` à +0,529 contre +0,179 sont des queues, pas des règles. Le seul stable
(`pool >= 100 SOL`, +0,009 / +0,035) est trop petit pour survivre au péage réel de 7 %.

**En revanche une famille est nettement NÉGATIVE, et proprement.** Acheter ce qui monte déjà perd,
de façon monotone et cohérente entre les moitiés :

    hausse à T+60 >= 0 %   -0,048        liquidité +2 % ou plus   -0,116
    hausse à T+60 >= 5 %   -0,119        liquidité +5 % ou plus   -0,129
    hausse à T+60 >= 10 %  -0,127        liquidité +10 % ou plus  -0,204

C'est le miroir du filtre « trop propre » (§3.71) et ça confirme son mécanisme : la montée visible
avant T+60 est fabriquée, et on paie pour entrer dedans. **Ne jamais poursuivre le prix.**

**LES FAMILLES ENTERRÉES, REJOUÉES À 4 MINUTES, 12/09 19 h 30.** §3.73 disait qu'elles avaient
toutes été jugées sur « tenir quinze minutes » et méritaient d'être rejouées. Fait, entrée T+60,
sortie 4 min, 2 891 jetons ayant densité et courbe :

    règle                              n    recherche   jugement   sans best
    acheteurs distincts >= 70        887      +0,066     +0,045     +0,028
    échanges 1re min <= 600        1 919      +0,029     +0,034     +0,023
    échanges par acheteur <= 8     1 618      +0,038     +0,025     +0,013
    100 acheteurs ET < 600 éch.      246      +0,025     +0,021     +0,004
    TELEGRAM (témoin)                177      +0,211     +0,198     +0,178

La sortie courte les fait effectivement passer de NÉGATIVES à positives des deux côtés — la leçon de
§3.73 tient. Mais elles valent +0,01 à +0,045 en jugement, **donc zéro une fois le péage réel de 7 %
appliqué**. Telegram fait dix fois plus sur la même mesure. Conclusion : la durée de détention était
bien une erreur de méthode, mais la corriger ne ressuscite aucune de ces familles.

**LES AUTRES RAMPES DE LANCEMENT NE VALENT PAS LE DÉTOUR.** J'avais annoncé qu'elles pourraient
doubler le flux ; la donnée dit 5 %. Jetons distincts vus sur 7 jours : pumpswap 4 275, pumpfun
1 226 (avant graduation), meteora 123, raydium 122, meteoradbc 3. Chiffrer le gisement AVANT de
construire le collecteur a évité deux à trois jours de travail pour 6 % de flux en plus.

Ce qui reste réellement inexploité est la phase AVANT graduation (pumpfun, 1 226 jetons) : c'est là
que l'effet publié s'applique dans le bon sens (Telegram multiplie par 8,9 la probabilité de
graduer, Kamat 2026), alors que nous n'observons que des diplômés. Piste ouverte, non mesurée.

**LA RÈGLE NE SE TRANSPORTE PAS SUR ROBINHOOD CHAIN, 13/09.** Question de l'opérateur : « ce truc là
avec Telegram et tout fonctionne pour Robinhood chain aussi ? ». Non, et pour une raison de fond.

Sur Solana le lien Telegram est écrit DANS le jeton à sa création et gelé (`updateAuthority: None`,
40 sur 40). Sur Robinhood Chain il n'existe aucune métadonnée équivalente : aucune des 30 tables EVM
ne porte de champ social. La seule source est la fiche DexScreener, que le créateur remplit quand il
veut. Mesuré le 13/09 :

    âge du jeton      n    avec réseaux   dont Telegram
    moins de 2 h     12        58 %            17 %
    2 à 24 h         15        53 %             7 %
    1 à 7 jours      13        77 %            23 %
    plus de 7 jours  23        83 %            30 %

**La part monte avec l'âge**, donc l'information est ajoutée après coup. Un test historique y
lirait le futur : un jeton qui a monté aurait eu son Telegram renseigné ensuite. C'est exactement la
fuite que §3.73 avait écartée côté Solana, et elle est bien réelle ici.

S'ajoute le flux : 211 jetons par jour sur Robinhood contre 1 122 sur Solana.

**Le seul chemin honnête** serait de collecter les réseaux À LA PREMIÈRE VUE, horodatés, pendant
plusieurs semaines, puis de tester sur cette donnée propre. Rien d'autre ne vaut.

**QUELLE AUTRE CHAÎNE ? 13/09.** Question de l'opérateur : « il y a pas une autre chaîne où c'est
bien fait comme Solana, avec beaucoup de génération et Telegram ? ». Deux critères : du volume, et
une métadonnée **gelée à la création** qui porte le lien.

    chaîne / rampe        créations/jour   métadonnée sociale         verdict
    Solana / pump.fun         ~1 100       dans le jeton, gelée       la référence
    BNB / four.meme         >20 000        exposée par leur API       À VÉRIFIER
    Robinhood Chain             211        fiche DexScreener, tardive mort (voir ci-dessus)
    Base / Clanker                ?        créé depuis Farcaster      non mesuré
    TON                           ?        Jetton TEP-64, possible    non mesuré

**four.meme est le seul candidat sérieux sur le volume** : plus de 20 000 jetons par jour, davantage
que pump.fun, et un revenu quotidien supérieur (1,4 M$ contre 885 k$). Son API expose bien Telegram
et Twitter.

**Ce que je n'ai PAS pu établir**, et c'est tout ce qui compte : ces liens vivent-ils dans
l'événement de création (donc gelés et horodatés) ou dans leur base de données (donc modifiables,
comme Robinhood) ? L'adresse de contrat citée par la documentation Bitquery ne renvoie aucun
événement sur un nœud public, et les nœuds BSC publics plafonnent la portée des requêtes.

**LE TEST EST FAIT, ET IL TRANCHE : NON.** 68 événements du contrat four.meme
(`0x5c952063c7fc8610ffdb798152d69f0b9550762b`, 20,7 M de transactions) lus sur 60 blocs BNB, soit
45 secondes de chaîne. **Zéro porte un lien social.** Les seules chaînes lisibles sont le nom et le
symbole du jeton. Les liens Telegram et Twitter vivent donc dans leur base de données, modifiables,
exactement comme sur Robinhood Chain. La règle ne s'y transporte pas.

**Et ça n'a rien coûté.** J'avais annoncé qu'il fallait un nœud BNB payant : c'était faux, et
l'erreur venait de moi. `bsc-dataseed.binance.org` refuse `eth_getLogs` avec
`{'code': -32005, 'message': 'limit exceeded'}`, et mon script écrivait `.get('result') or []`, ce
qui transforme une erreur en liste vide. J'ai donc conclu « ce contrat n'émet rien » alors que le
nœud disait « je refuse ». `bsc.publicnode.com` répond correctement, gratuitement.

**Méthode, pour la troisième fois cette semaine.** `réponse.get('result') or []` est un piège :
il efface la différence entre « rien » et « refusé ». Vérifier la présence d'une erreur AVANT de
lire un résultat. Même famille que l'IPFS à 429 (§3.72) et que le prix aberrant de HYPE (§5.30).

**LES REPRISES DE NOM, 13/09.** L'opérateur voit deux achats CATGIRL à seize minutes d'écart et
demande si c'est une erreur. Ce sont **deux jetons différents portant le même nom** — le moteur ne
raisonne que sur l'adresse, jamais sur le symbole, donc rien de cassé. Mais l'observation vaut une
mesure : un jeton qui reprend un nom récent est probablement une copie qui surfe sur l'attention du
premier. 43 % des lancements reprennent un nom vu dans les 24 h.

    groupe                        n     gagnants   médiane   recherche   JUGEMENT
    nom inédit (24 h)          1 892      45 %      -2,0 %     +0,012     +0,089
    reprise de nom             1 439      54 %      +0,3 %     -0,045     -0,028
    TELEGRAM, nom inédit         166      58 %      +3,9 %     +0,242     +0,154
    TELEGRAM, reprise de nom      40      78 %      +0,8 %     +0,099     +0,208

Sur la population générale, **la reprise de nom est négative des deux côtés** : c'est un signal
faible mais cohérent. Chez les jetons Telegram, l'effet DISPARAÎT — les deux groupes sont positifs,
et le groupe « copie » est même légèrement meilleur en jugement. Le filtre Telegram écarte donc déjà
les mauvaises copies. Rien à changer.

Troisième fois que ce schéma se répète : un signal réel sur la population générale (forme, heure,
reprise de nom) s'évapore dans le sous-groupe Telegram. C'est ce qui rend ce filtre différent des
autres — il absorbe les autres.

**LES AUTRES CHAÎNES, REVUE COMPLÈTE, 13/09.** Quatre candidates passées au même crible : du volume,
et un lien Telegram **gelé à la création et lisible à T+60**.

    chaîne / rampe     volume        lien social             verdict
    Solana pump.fun   ~1 100 grad/j  gravé dans le jeton     LA SEULE QUI MARCHE
    BNB four.meme    >20 000 créa/j  base de four.meme       absent à T+60
    Robinhood Chain      211 /j      fiche DexScreener       ajouté après coup
    TON                  faible      hors standard TEP-64    pas de champ social
    Base / Clanker       moyen       Farcaster, pas Telegram autre réseau

**BNB, le meilleur candidat, échoue sur un point plus grave que la contamination.** Le collecteur
monté le 13/09 (`intel/engines/bnb_collecte.py`) capte bien les créations — 27 en trois minutes,
noms décodés depuis l'événement — mais sur **118 relevés à T+55 à T+202 s, zéro lien social**.
DexScreener indexe pourtant ces jetons (`dexId: fourmeme`) : il rend `socials: []`. L'information
n'existe donc pas encore au moment où il faudrait décider. Ce n'est plus seulement qu'on ne peut pas
VALIDER la stratégie, c'est qu'on ne pourrait pas l'EXÉCUTER. L'API de four.meme, qui affiche bien
ces liens sur leur site, rend 404 depuis notre serveur.

**TON, la candidate intuitive, n'a pas de champ social.** C'est la chaîne de Telegram, mais TEP-64
ne définit que `name`, `description`, `image`, `symbol`, `decimals`, `amount_style`, `render_type`.
Un projet peut mettre ses liens dans le JSON externe pointé par `uri`, donc hors chaîne et
modifiable sauf adressage par empreinte. Et le volume est sans commune mesure.

**Base / Clanker est natif FARCASTER, pas Telegram.** Le signal mesuré porte sur Telegram
précisément — Twitter seul ne marche pas (1 070 jetons, jugement −0,019). Rien ne dit qu'un autre
réseau porterait le même effet, et il faudrait tout remesurer.

**Conclusion.** Solana n'est pas la meilleure chaîne par hasard ni par volume : elle est la seule où
l'intention du créateur est inscrite publiquement, irrévocablement, à la seconde zéro. C'est une
propriété de structure, pas de marché. Le collecteur BNB reste en marche : il dira à quel âge les
liens apparaissent là-bas, ce qui fermera ou rouvrira la porte.

**BNB EST CLOS, MAIS UNE PORTE S'OUVRE SUR SOLANA MÊME, 13/09 nuit.**

Le collecteur BNB a tourné une heure : **663 créations captées, soit 649 par heure**, ce qui confirme
le volume annoncé. Et **4 853 relevés sociaux, zéro Telegram, zéro liquidité**, à tous les âges
jusqu'à quinze minutes. DexScreener indexe pourtant ces jetons (`dexId: fourmeme`). L'information
n'existe pas au moment de décider : la piste est fermée, pas entrouverte.

**En revanche je m'étais trompé sur les autres rampes SOLANA.** J'avais écrit qu'elles pesaient 5 %
du flux, mesuré sur `solana_observations` — une source biaisée, puisque notre flux écoute
spécifiquement les migrations pump.fun. Notre collecte est d'ailleurs **à 97 % pump.fun** (3 328
mints sur 3 440 finissent par `pump`), donc elle ne peut rien dire des autres.

La vraie question n'est pas le volume mais la métadonnée. Testé sur 14 jetons Solana NON-pump.fun :

    aucun ne porte de metadonnee Token-2022 dans le mint          14 / 14
    mais leur fiche METAPLEX separee est IMMUABLE                 10 / 14
    modifiable                                                     4 / 14

**L'immuabilité n'est donc pas une propriété de pump.fun, c'est une propriété courante de Solana.**
Le lien Telegram de ces jetons vit dans le JSON pointé par la fiche Metaplex, exactement comme chez
pump.fun — seul l'endroit où lire change. Et la mutabilité se vérifie jeton par jeton AVANT
d'acheter (`isMutable`), donc les 4 sur 14 modifiables s'écartent d'eux-mêmes.

**Ce qui reste à mesurer, et c'est bon marché :** combien de graduations non-pump.fun par jour, et
quelle part porte un Telegram dans son JSON. Si le volume suit, la règle s'étend sans changer de
chaîne, de portefeuille, ni de chemin d'exécution — le risque marginal est nul.

**DEUX QUESTIONS DE L'OPÉRATEUR, 13/09 : SORTIR PLUS TÔT, ET MISER PLUS FORT.** Posées comme
questions, avec la consigne explicite de tester avant de changer quoi que ce soit.

**1. Sortir sur une anomalie avant les 4 minutes : NON, et pour une raison physique.**

    seuil de chute de liquidité   aucun   -10 %   -20 %   -30 %   -40 %   -50 %
    JUGEMENT                     +0,169  +0,063  +0,080  +0,109  +0,148  +0,160
    pire décile                    -76 %   —       -72 %   -77 %   -78 %    —

Dégrade à tous les seuils, monotone, et **ne protège même pas les gros perdants** : le pire décile
reste à -72/-78 % quoi qu'on fasse. La cause est observationnelle -- la chute de liquidité et
l'effondrement du prix tombent dans le MÊME relevé de dix secondes (batonfly : 82 → 29,5 SOL et
x1,06 → x0,18 en un pas). On ne peut pas réagir plus vite qu'on n'observe. La seule voie serait
d'écouter le flux de swaps en direct au lieu de sonder les réserves toutes les dix secondes.

**2. Une probabilité de réussite pour miser plus : le signal existe, mais ce n'est PAS une
probabilité.** Ce qui varie n'est pas la chance de gagner, c'est la TAILLE du gain :

    gros pools    68 % de gagnants · gain moyen quand ça gagne +30 % · perte moyenne -47 %
    petits pools  57 % de gagnants · gain moyen quand ça gagne +85 % · perte moyenne -42 %

Les jetons qui gagnent le plus SOUVENT sont ceux qui rapportent le MOINS. Miser sur la probabilité
reviendrait à miser sur ce qui ne paie pas.

**En revanche la taille du pool à l'entrée sépare très nettement**, et les deux moitiés sont
d'accord :

    pool à l'entrée      n   gagnants   médiane   recherche   JUGEMENT   sans best
    0-60 SOL            38     37 %     -10,0 %    -0,124     +0,141      +0,041
    60-75 SOL           55     67 %     +49,0 %    +0,575     +0,377      +0,298
    75-85 SOL           52     63 %     +33,5 %    +0,236     +0,193      +0,146
    100 SOL et plus     57     74 %      +0,6 %    -0,023     +0,020      +0,000

Les deux extrêmes sont mauvais pour des raisons opposées. Sous 60 SOL, le pool médian ne fait que
**1,5 SOL** : un ordre de 20 € y vaut 14,5 % du pool, soit ~29 % d'impact — le garde-fou les refuse
déjà. Au-dessus de 100 SOL, on gagne trois fois sur quatre et on ne gagne rien.

**La bande 60-85 SOL comme filtre**, avec toute la discipline :

    filtre           part du flux   recherche   JUGEMENT   sans best   hasard
    tout                  100 %      +0,176     +0,179     +0,157     100,0 %
    60-85 SOL              52 %      +0,441     +0,274     +0,238       0,0 %
    >= 60 SOL              81 %      +0,254     +0,186     +0,161       3,7 %

Au péage réel de 6,5 % : **+0,216 par euro contre +0,125** pour tout prendre.

**MAIS l'arithmétique du débit change la conclusion.** Le filtre double le gain par euro et divise
les tickets par deux : 1,3 ticket/h × 20 € × 0,216 = 5,6 €/h, contre 2,5 × 20 × 0,125 = 6,3 €/h
aujourd'hui. **Filtrer seul fait perdre de l'argent.** Il ne vaut que combiné à une mise plus forte :
1,3 × 40 € × 0,216 = 11,2 €/h, pour le même capital immobilisé, puisque les lignes durent 4 minutes.

C'est donc la réponse à la question telle qu'elle était posée : oui, on peut miser plus fort sur un
sous-ensemble, mais le critère est la TAILLE DU POOL et non une probabilité, et filtrer sans
augmenter la mise serait un recul. n = 107 jetons dans la bande. Rien n'est changé.

**LE PÉAGE RÉEL, deux tickets.** C'est désormais le chiffre à surveiller avant tous les autres.

    ticket        prix     encaissé   péage
    FOMOBRAIN    x1,98      x1,77     10,8 %
    IF           x1,03      x0,99      3,6 %

Il dépend de la taille du pool et de la vitesse du prix au passage, donc il varie. À 2 % la règle
donne +0,171 par euro et 66 % de gagnants ; **à 10 % elle donne +0,085 et 43 %** — elle cesse d'être
« la plupart des tickets gagnent » pour devenir « portée par la queue », exactement la forme fragile
reprochée aux six familles enterrées. Deux tickets ne fixent rien ; cinquante le diront.

**Et une correction à ma propre méthode.** §3.72 a conclu « Telegram = signal négatif » en ne
balayant qu'une seule règle de sortie. Un signal ne se juge pas sous une seule sortie : la durée de
détention fait partie de la stratégie, pas du décor. Six familles ont été enterrées cette semaine
en tenant quinze minutes. Elles méritent d'être rejouées sur le profil temporel.



### 3.74 — Une découverte qui n'était qu'une colonne fausse, et la confirmation qu'elle a permise, 2026-09-14

**La règle morte.** Le 13/09 au soir, un balayage de 1 866 combinaisons a sorti une seule
survivante au seuil corrigé pour le test multiple : « petite capitalisation ET gros pool »
(`mcap < 166 k$` et `pool >= 468 SOL`), 0 sur 100 000 tirages, quatre quarts de période positifs,
indépendante de Telegram. Mise en observation à blanc plutôt qu'activée — c'est la seule décision
de cette histoire qui s'est révélée juste.

**Elle n'a jamais tiré. Zéro ticket en 9 heures.** C'est ce silence qui a mis sur la piste.

**La cause : `reserve_sol` comptait des unités d'autre chose que du SOL.** Le collecteur
(`prix_chaine.py`) lisait les deux comptes de réserve d'un pool PumpSwap et supposait que le second
était du WSOL. Il ne l'est pas toujours. Étiquetage sur la chaîne des 4 587 pools de l'historique,
en lisant leur `quote_mint` à l'offset 43+32 du compte de pool : **456 pools, soit 9,9 %, ne sont
pas adossés au SOL.**

    reserve_sol          médiane      p90              max
    avant correction     69,85 SOL    2 493 SOL    3 648 691 SOL
    après correction     75,53 SOL      966 SOL        3 029 SOL

La médiane était juste — ~75 SOL est simplement la liquidité qu'un jeton pump.fun reçoit à sa
migration. **C'est la queue haute qui était polluée**, et « gros pool » n'allait chercher que là.
Un pool annoncé à 2 060 964 SOL, soit 200 M€ pour un jeton à 43 000 $.

**Rejugement sur donnée assainie**, avec l'offre réelle de chaque jeton (voir plus bas) et la
contrainte d'exécution appliquée avant mesure — 2 656 tickets exécutables, coupure sur la date de
naissance :

    règle                              n     recherche   JUGEMENT   sans best
    tout prendre                    1 328      +0,004      -0,012     -0,015
    mcap<166k$ ET pool>=468 SOL         0          --          --         --
    mcap < 166 k$ (seule)             557          --      -0,012     -0,020
    pool >= 468 SOL (seule)           707          --      -0,008     -0,009

**Aucun ticket, dans les deux moitiés, à 4, 5 et 6 minutes.** Les deux conditions sont réellement
incompatibles, et l'arithmétique dit pourquoi : sur un pool à produit constant,
`mcap / pool_sol = offre / reserve_base`. « Petite capitalisation ET gros pool » ne sont pas deux
signaux, c'est une seule variable structurelle déguisée — la part de l'offre détenue par le pool.
Prise seule, `mcap < 166 k$` est **négative**, soit l'inverse du sens annoncé par la découverte.

**L'offre pump.fun n'est pas constante.** Contrôle sur 60 jetons tirés au hasard : médiane 9,99e8
mais étendue de 7,55e8 à 2,00e9, et **38 % seulement à 1 % d'un milliard**. Toute reconstruction
hors-ligne qui la suppose constante se trompe jusqu'à un facteur 2. Le moteur live, lui, la lit à
chaque décision (`getTokenSupply`) — il était juste. Lecture en lot possible par
`getMultipleAccounts` sur les comptes de mint, offset 36..44 en u64 petit-boutiste, décimales en
44 : 40 appels au lieu de 4 000, vérifié **exact** contre `getTokenSupply` sur 15 jetons.

**CE QUE CE NETTOYAGE A RENDU POSSIBLE.** La correction laisse un jeu de prix lus aux réserves du
pool, indépendant de DexScreener d'où vient toute la règle Telegram. Autre capteur, autre cadence,
autre zone temporelle. Aucun seuil n'y a jamais été choisi : il est jugement en entier. 911 tickets
exécutables, sortie à 4 min, péage 2,4 % :

    groupe             n      par euro   médiane   sans best   gagnants   >= x1,9
    TELEGRAM          51       +0,116     +0,004     +0,061       53 %      16 %
    pas de Telegram  860       -0,039     +0,013     -0,045       60 %       2 %
    twitter seul     499       -0,067     +0,019     -0,077       59 %       2 %
    site seul        382       -0,063     +0,016     -0,075       58 %       3 %

Twitter et le site restent négatifs : l'effet est spécifique à Telegram, comme sur DexScreener.

**Et le test du hasard porté par la bonne statistique.** Sur la moyenne il donne 1,93 %, mais
8,32 % une fois retiré le meilleur ticket — faiblesse normale d'une queue épaisse sur 51
observations. La fréquence des gros tickets, elle, ne peut pas être portée par un seul coup :

    seuil      Telegram      sans Telegram    rapport    hasard
    >= x1,5    14/51  27 %    42/860   5 %     x5,6      0,000 %
    >= x1,9     8/51  16 %    18/860   2 %     x7,5      0,000 %

**0 sur 20 000 dans les deux cas.** C'est la deuxième confirmation indépendante de la semaine,
après le multiplicateur 4,5 entre le taux de Telegram chez les créations (1,46 %) et chez les
gradués (6,5 %) mesuré la même nuit. La règle en production ne repose plus sur une seule source de
prix.

**Ce qu'on en retient sur la méthode.** Le silence d'une règle est une donnée. Une règle qui sort
d'un balayage géant et ne tire jamais n'est pas « en attente d'occasion » : il faut aller vérifier
que ses conditions sont seulement compatibles, et sur quelle colonne elle s'appuie. Ici, neuf
heures de silence valaient mieux que n'importe quel test statistique — et la mise en observation à
blanc, décidée après l'activation trop rapide de la règle de hausse, a évité que la découverte
coûte un euro.

### 3.75 — Deux pistes creusées à fond : la courbe ne paie pas, et le « zéro social » BNB était une erreur de source, 2026-09-14

L'opérateur, le 14/09 : *« t'as vu qu'on peut se retrouver du jour au lendemain avec un truc qui
fonctionne plus… ne décourage abandonne pas une piste car t'as essayé 2/3 remonté de données et ça
renvoyait vide creuse cherche et note »*. Les deux pistes ci-dessous étaient exactement dans ce cas.

#### A. Acheter AVANT la graduation : le signal est énorme, le rendement est nul

**Pourquoi c'était la meilleure piste disponible.** La stratégie en production n'agit qu'après la
migration — ~40 occasions par heure. Les créations sont douze fois plus nombreuses (~470/h). Le
même avantage par euro y rapporterait douze fois plus.

**Le signal brut est spectaculaire.** Le SOL réel accumulé dans la courbe sépare massivement :

    âge      futures graduées (médiane)   les autres    rapport
    T+1 min        0,23 SOL                0,01 SOL       21x
    T+3 min        0,19 SOL                0,00 SOL      165x
    T+5 min        0,14 SOL                0,00 SOL      364x

**Et l'exécution y est FAVORABLE**, contrairement à PumpSwap : la courbe pump.fun a des réserves
virtuelles (~30 SOL), donc un ordre de 0,53 SOL vaut ~1,8 % d'impact même quand la courbe ne
contient que 0,2 SOL réel. C'est l'inverse du problème qui avait tué la règle de hausse.

**Le majorant est même très beau.** En supposant qu'on sache d'avance qui graduera — donc en
trichant — acheter à T+300 s et vendre à la graduation donne **+1,499 par euro, 81 % de gagnants**.

**Et pourtant la règle honnête ne paie pas.** Filtre sur le seul `sol_reel` disponible à l'instant
d'entrée, sortie à la graduation ou à la fin du suivi, coupure sur la date de naissance :

    entrée T+300 s        n     recherche   JUGEMENT   sans best   gagnants   graduent
    SOL >= 0           1 602      -0,034     -0,039      -0,043        3 %      0,6 %
    SOL >= 3              96      -0,070     -0,038      -0,069       23 %      4,1 %
    SOL >= 8              61      -0,038     -0,033      -0,080       27 %      6,5 %
    SOL >= 20             41      +0,003     +0,016      -0,056       24 %      9,8 %
    SOL >= 40             29      +0,081     +0,112      +0,013       34 %     13,8 %

Le seuil fait bien monter le taux de graduation (0,6 % → 13,8 %, soit 23×). **Mais le rendement
reste négatif partout sauf une case**, et cette case a une **médiane négative** (−0,069) et tombe à
+0,013 dès qu'on retire son meilleur ticket. Sur 29 tickets, un seul coup porte tout — la forme
exacte des deux fausses découvertes de la semaine. Testé aussi à T+180 s et T+480 s, à 4 et 10 min
de tenue : **28 cellules, aucune ne survit à « sans best »**.

**Pourquoi ça ne marche pas, mécaniquement.** Le prix à T+15 s vaut en médiane **1,96 fois** le prix
de graduation : la poussée est déjà passée quand on arrive. Acheter à T+60 s sur un jeton qui
graduera donne un multiple médian de **x0,65**. L'argent de la courbe est capté dans les quinze
premières secondes, par des acteurs plus rapides que nous.

**Ce qui reste ouvert** : le suivi s'arrêtait à 15 min alors que 33 % des graduations arrivent après
(médiane 8 min, p75 25 min, p90 119 min). Ces lignes étaient soldées au prix de la 15e minute au
lieu de leur graduation — mesure pessimiste d'une ampleur inconnue. `suivi_minutes` passe de 15 à
45 (couvre ~82 %), et `part_lue` de 0,35 à 0,60.

**Et une mesure à refaire, pas un résultat.** Le test direct « une création avec Telegram
gradue-t-elle plus ? » donne 3,70 % (2 sur 54) contre 3,82 % sans — soit aucun effet. Mais
l'intervalle sur 2 graduations va de 0,5 % à 13 % : il ne distingue ni le taux de base ni le x4,5
annoncé ce matin. **Ce n'est pas une réfutation, c'est un manque de puissance**, et c'est pour ça
que la part de fiches lues augmente.

#### B. BNB : « zéro lien social » était faux, il y en a 40 %

**Ce que j'avais écrit le 13/09**, en arrêtant le collecteur : *« 6 766 créations, 53 928 relevés,
ZERO lien social à tous les âges. L'information n'existe pas au moment de décider. »*

**C'était une limite de la source prise pour un fait sur la chaîne.** Le collecteur interrogeait
DexScreener. Pour un jeton four.meme encore sur sa courbe, DexScreener renvoie bien une paire — les
54 228 relevés en ont une — mais sa réponse ne contient **aucun bloc `info`**. Clés vérifiées une
par une le 14/09 : `baseToken, chainId, dexId, pairAddress, pairCreatedAt, priceChange, priceNative,
quoteToken, txns, url, volume`. Ni prix, ni liquidité, ni réseaux. Jamais. D'où le zéro.

**La bonne source est l'API de four.meme :**
`https://four.meme/meme-api/v1/private/token/get?address=<adresse>` → `telegramUrl`, `twitterUrl`,
`webUrl`, `tokenPrice.price`, `tokenPrice.marketCap`. Sondage sur 90 jetons :

    âge du jeton      n     Telegram   twitter    site
    8 à 24 h         45      40,0 %    88,9 %    64,4 %
    plus de 24 h     45      44,4 %    86,7 %    71,1 %
    (Solana)                  3,7 %    42 %      20 %

**Ce qui ne veut PAS dire que la règle y marchera — au contraire.** Sur Solana, la force du signal
tient en partie à sa **rareté** : 3,7 % des jetons le portent, et c'est ce qui en fait un filtre. Un
lien présent sur 40 % des jetons ne trie presque rien. La question est ouverte et ne se tranchera
qu'avec la collecte horodatée.

**Et l'horodatage reste vital** : ces liens sont dans la base de four.meme, modifiables après coup.
L'écart entre 8-24 h (40,0 %) et plus de 24 h (44,4 %) est faible mais non nul, et la tranche qui
compte — moins de 2 h — manquait faute de collecte. Le collecteur est relancé avec la bonne source.

#### Ce que ces deux pistes ont en commun

Dans les deux cas j'avais conclu trop tôt sur une mesure vide. Sur BNB, un zéro que je n'ai pas
interrogé. Sur la courbe, j'aurais pu m'arrêter au premier sondage (« multiple médian 1,000, part
au-dessus de x1,5 : 0 % » sur 67 jetons en 0,54 h) — et j'aurais raté le signal à 21×, qui est réel
même s'il n'est pas monnayable. **Un chiffre nul ou plat doit d'abord être suspecté d'être un
défaut d'instrument.** Ce n'est qu'après l'avoir disculpé qu'il devient un résultat.

### 3.76 — BNB chiffré : 94 % des jetons ne sont jamais échangés, et Telegram y est anti-prédictif, 2026-09-14

L'opérateur, le 14/09 : *« ne me dis pas ce qui est difficile, tes intuitions foirent tout le temps,
je veux les chiffres — simule un portefeuille blanc qui trade BNB et teste toutes les combinaisons
de stratégie possibles »*. Réponse chiffrée, sans commentaire d'intuition.

**Données.** 617 jetons four.meme dont nous possédons un historique de prix **horodaté par nous**
(`bnb_releves`, 13/09), croisé avec leurs liens sociaux lus chez four.meme (`bnb_social`, module
`intel.research.bnb_fiches`). Taux sur cet échantillon : Telegram 74,1 %, twitter 93,7 %, site
85,3 % — plus élevés que le sondage général (40-44 %) parce que ce sous-ensemble est celui que
DexScreener avait indexé, donc déjà biaisé vers les jetons vivants.

**Le balayage.** 4 entrées (T+60/120/240/420 s) × 4 tenues (2/5/10/20 min) × 9 filtres sociaux =
**144 cellules**, dont 34 avec assez de tickets. Coupure recherche/jugement sur la date de
naissance, résultat privé de son meilleur ticket, seuil corrigé pour le test multiple à 0,0347 %.

    CE QUI SURVIT (positif dans les deux moitiés ET sans son meilleur ticket) : AUCUNE sur 34.

**Et le motif du résultat était l'information.** Presque toutes les cellules affichaient exactement
−0,030, soit précisément le péage, avec **0 % de gagnants**. Un chiffre plat se suspecte d'abord
comme un défaut d'instrument (§6) — vérification faite, ce n'en était pas un :

    644 jetons · 37 bougent (5,7 %) · 607 au prix INCHANGÉ
    et ce prix est le même d'un jeton à l'autre : 4,111e-06, 5,740e-09...

Ce n'est donc pas la source qui fige : c'est **le prix de départ de la courbe**, jamais modifié
parce que **le jeton n'a reçu aucune transaction**. 94,3 % des four.meme sont morts à la naissance
dans la fenêtre observée (jusqu'à T+491 s).

**Telegram y est ANTI-prédictif**, exactement l'inverse de Solana :

    filtre            n jetons   échangés   taux
    avec Telegram         457        14     3,1 %
    sans Telegram         160        23    14,4 %
    avec twitter          578        29     5,0 %
    les trois             454        13     2,9 %

Un jeton SANS Telegram a **4,6 fois plus de chances** d'être échangé qu'un jeton avec. Et ce sens
résiste au biais de la mesure : les liens ayant été lus après coup, la fuite du futur devrait
FAVORISER Telegram, pas le pénaliser. Le résultat négatif est donc robuste à sa propre limite.

**Même les 37 qui bougent ne paient pas** : −0,038 par euro, médiane −0,030, **5 % de gagnants**,
meilleur ticket +0,71, aucun au-dessus de +100 %.

**Ce que ça ferme, et ce que ça n'exclut pas.** La fenêtre d'observation s'arrêtait à T+491 s :
on ne peut pas distinguer « mort » de « lent ». `AGE_LIMITE` passe de 900 s à 3 600 s et la collecte
horodatée continue avec la bonne source. Mais sur la question posée — un portefeuille à blanc qui
trade BNB dans les minutes suivant la création — la réponse mesurée est : **aucune combinaison ne
gagne, et la meilleure piste théorique y est inversée.**

### 3.77 — Autopsie des 59 tickets réels : rien ne sépare à l'entrée, la sortie est déjà optimale, reste la mise, 2026-09-14

L'opérateur : *« analyse sérieuse des différents achats, pourquoi certains ont marché d'autres non,
est-ce qu'il y a une cause qui peut nous éviter de perdre ou de gagner plus — n'oublie pas
reinforcement learning et learning by doing »*.

**Précaution de méthode, écrite avant de regarder.** Sur 59 tickets, chercher parmi quinze variables
laquelle sépare le mieux *garantit* de trouver quelque chose. Le carnet réel sert à FORMULER des
hypothèses ; la validation se fait sur le jeu indépendant des prix lus aux réserves.

#### 1. À l'entrée, gagnants et perdants sont indiscernables

31 gagnants (+457,42 €) contre 28 perdants (−436,14 €). Médiane des uns contre médiane des autres :

    variable              gagnants   perdants   rapport
    pool à l'entrée       78,6 SOL   77,6 SOL     1,01x
    capitalisation         42 525 $   38 917 $    1,09x
    part de l'offre          0,188      0,199     0,94x
    âge à l'achat             59 s       60 s     0,98x
    fraîcheur du prix         50 s       52 s     0,97x
    hausse avant l'achat    +0,049     +0,043     1,16x
    heure UTC                  8 h        9 h     0,89x

**Dix variables, aucun rapport qui s'éloigne de 1.** Et les 59 tickets portent TOUS twitter et site :
zéro variation à exploiter de ce côté. Ce n'est pas un échec de mesure, c'est un résultat — à
l'instant d'acheter, l'information disponible ne distingue pas l'issue.

#### 2. La sortie à 4 minutes est confirmée par notre propre argent

Chaque ticket ne donne pas un chiffre mais une TRAJECTOIRE : 29 de nos achats ont un chemin de prix
complet, soit des centaines d'observations pour la question « quand vendre ». Rejeu avec le péage
RÉEL de chaque ticket (médiane 2,2 %) :

    sortie fixe à 120 s    -0,036      sortie à 360 s   +0,093
    sortie fixe à 180 s    +0,042      sortie à 480 s   +0,091
    sortie fixe à 240 s    +0,135  <-- en place
    sortie fixe à 300 s    +0,155      sortie à 600 s   -0,125

Un vrai sommet autour de 240-300 s. 300 s donne +0,155 contre +0,135, mais **sans best il tombe à
+0,077 contre +0,086** : l'écart est porté par un ticket. On ne bouge pas.

#### 3. L'amélioration candidate n'a pas résisté

Sur le carnet réel, « prendre le gain à x2, sinon sortir à 240 s » battait la règle en place sur les
deux mesures : **+0,200 contre +0,135, et sans best +0,152 contre +0,086**. Testée sur 55 chemins
indépendants (jetons Telegram, prix aux réserves, pools vérifiés) :

    groupe Telegram, 55 chemins    sortie 240 s    objectif x2
    tout                              +0,061         +0,064
    moitié de recherche               +0,206         +0,198
    moitié de JUGEMENT                -0,078         -0,065

**+0,003 d'écart. Rien.** Les +0,065 du carnet réel étaient du bruit sur 29 tickets et 18 règles
essayées. Stops (−15 à −60 %) et suiveurs (−15 à −40 %) : aucun n'apporte rien non plus, troisième
confirmation de §3.23 et §3.59.

#### 4. Ce qui reste améliorable : la taille de la mise

Elle n'a besoin d'aucun signal — seulement de l'avantage et de sa dispersion, tous deux mesurables
sur ce qui a déjà été joué.

    59 tickets · avantage +0,0724 par euro · écart-type 0,621
    intervalle à 90 % : -0,058 à +0,208
    Kelly sur l'avantage mesuré        18,7 % du capital
    demi-Kelly                          9,4 %
    Kelly sur la BORNE BASSE          -15,1 %   <-- négative

**La borne basse est négative, donc le calcul ne justifie aucune taille.** Kelly ne mise pas sur un
avantage qui peut être nul. Ce qui ne veut pas dire s'arrêter — il faut jouer pour apprendre — mais
que la mise actuelle est celle qu'on accepte de PERDRE pour acheter l'information, pas celle qu'un
avantage prouvé justifierait. Ce que chaque taille aurait donné sur nos 59 tickets :

    mise      résultat    pire série    pire ticket
    10 EUR     +42,69       -29,96         -8,41
    20 EUR     +85,38       -59,91        -16,82
    50 EUR    +213,46      -149,78        -42,05
    80 EUR    +341,53      -239,65        -67,27

**Et le point décisif : on apprend au nombre de TICKETS, pas au nombre d'euros.** Diviser la mise
par deux divise le risque par deux et ne ralentit l'apprentissage d'aucun jour. Les 200 tickets qui
trancheront arrivent à la même date à 25 € qu'à 50 €.

#### 5. Sur l'apprentissage par renforcement

Un agent par renforcement apprend une politique *état → action → récompense*. La mesure du §1 dit
qu'il n'existe, pour l'instant, aucun état observable qui prédise la récompense : dix variables,
aucune séparation. Il n'y a donc rien à apprendre — un agent entraîné là-dessus apprendrait le bruit
de 59 tickets, exactement ce que le rejeu du §3 vient de démontrer sur dix-huit règles.

Ce qui EST de l'apprentissage par l'expérience, et qui tourne déjà : `intel.research.usure` remet à
jour l'estimation de l'avantage et son intervalle à chaque ticket, et dit combien il en faut encore.
C'est la boucle adaptée au volume de données dont on dispose. Un bandit contextuel deviendra
justifié le jour où l'on aura **et** 200 tickets **et** une variable qui sépare — aujourd'hui il
manque les deux.

### 3.78 — Ce qui fait une bonne journée : rien de mesurable, 2026-09-14

L'opérateur : *« pour une journée meilleure qu'une autre c'est quoi le driver ? le marché crypto ?
le BTC ? le ETH ? les créateurs ? »*

Le carnet réel ne compte que trois jours — on ne corrèle rien avec trois points. Mais les cinq jours
de prix sur **tous** les jetons gradués permettent une série HORAIRE : 2 734 tickets simulés,
108 heures avec au moins 8 tickets. Corrélation de rangs (Spearman), et surtout **son seuil de
bruit affiché à côté**, `1,96/racine(n)` — sans quoi +0,10 sur 108 heures se lit comme un résultat.

    cause candidate              corrélation   seuil   verdict
    BTC variation -> marché         +0,101     0,189   bruit
    SOL variation -> marché         +0,059     0,189   bruit
    BTC niveau -> marché            -0,182     0,189   bruit
    flux (tickets/h) -> marché      -0,103     0,189   bruit
    marché -> notre groupe          +0,076     0,370   bruit
    BTC -> notre groupe             -0,020     0,370   bruit
    flux -> notre groupe            +0,208     0,370   bruit

**Aucune ne passe son seuil.** Notre groupe Telegram ne suit même pas le marché memecoin.

**Les créateurs**, quatrième hypothèse, devenue testable : 562 des 4 625 créateurs ont lancé
plusieurs jetons (12,2 %, contre une vingtaine trois jours plus tôt). Historique construit dans
l'ordre du temps — pour juger le jeton k on n'utilise que les jetons 1..k−1 :

    premier jeton du créateur   2 442   -0,007   sans best -0,009
    il en a déjà fait 1           119   +0,027   sans best -0,010
    il en a déjà fait 2+          103   -0,024   sans best -0,051
    précédent gagnant             107   -0,009   sans best -0,036
    précédent perdant             115   +0,016   sans best -0,022

Rien ne tient : tous les « sans best » sont négatifs. Et le point qui ferme la porte : **sur nos
jetons Telegram, 3 seulement ont un prédécesseur**. Sur 119 créateurs récidivistes, **0 mettent
toujours un Telegram, 116 n'en mettent jamais**. Les créateurs qui recommencent et les créateurs qui
mettent un Telegram sont deux populations disjointes — le filtre par historique ne peut pas se
combiner à la stratégie, faute de recouvrement.

**Conclusion.** Sur cinq jours, une bonne journée ne se distingue d'une mauvaise par aucune cause
observable. C'est cohérent avec §3.77, où dix variables mesurées à l'instant d'acheter ne séparaient
pas les gagnants des perdants. La distribution porte 13 % de tickets sous −70 % et 13 % au-dessus de
+90 % : **la journée est faite par ceux qui tombent dedans**, et rien de ce qu'on sait mesurer ne le
prédit. Il n'y a donc pas de « n'acheter que les bons jours » à construire.

**La limite honnête** : cinq jours. Une influence de BTC se jouerait sur des semaines, et un
changement de régime (effondrement du marché) ne serait pas visible ici. Ce résultat dit qu'il n'y a
rien à exploiter au jour le jour, pas qu'aucun régime n'existe.

### 3.79 — Le filtre « 3 signes » chez les jetons Telegram : le premier vrai candidat, et mon erreur de lecture, 2026-09-14

#### La question de l'opérateur, et sa cause

*« On rentre au moment où ça se crashe. »* Mesuré : notre prix d'entrée se situe au **80ᵉ centile**
de tout ce qui précède, et dans **45 % des cas c'est le plus haut vu jusque-là**. On achète donc
systématiquement haut, et c'est structurel — le signal Telegram désigne des jetons que quelqu'un
vient d'acheter.

Mais ce n'est pas un crash : le prix médian après l'entrée reste à 1,00 tout du long. Ce qui explose
est la **dispersion** — p25 de 0,998 à T+80 s à **0,011** à T+600 s, pendant que le p75 monte à
1,452. Bifurcation, pas effondrement. Entrer plus tard ne répare rien (T+90 +0,042 · T+120 +0,014 ·
T+180 −0,007 · T+300 −0,208).

#### Le filtre, et l'inversion qui le rend intéressant

Trois signes, tous mesurés **avant T+90 s** sur les réserves qu'on lit déjà (§3.66) :
le prix est au-dessus de son premier relevé (≥ +0,7 %) · il n'est jamais descendu en dessous ·
la liquidité a grossi (≥ +0,35 %). On n'achète que si les **trois** sont vrais.

**Sur la population générale ces signes désignent les jetons qui se font vider cinq fois plus** — un
jeton qui monte tout droit sans jamais reculer ressemble à une mise en scène. **Chez les jetons
Telegram, le même profil désigne les bons.** Deux populations, deux sens opposés.

#### MON ERREUR, qui vaut plus que le résultat

Premier passage : j'ai présenté le filtre comme positif sur nos 35 tickets réels, puis je l'ai
écarté parce que 13 tickets **simulés** de la moitié de jugement donnaient −0,015. L'opérateur :
*« tu me sors un truc, tu dis c'est le seul truc positif, et après tu dis non c'est un piège »*.

Il a raison. J'ai laissé **13 observations simulées annuler 35 observations de vrai argent**, et
j'avais en plus lu la mauvaise tranche (13 tickets au lieu de 15, découpage différent). À force de
me méfier des fausses découvertes après trois cette semaine, j'ai appliqué le scepticisme à
l'envers. **La méfiance n'est utile que si elle pèse les preuves dans le bon sens.**

Et un filtre ne se juge pas sur le niveau du groupe gardé — qui bouge avec la période — mais sur le
**contraste** entre ce qu'il garde et ce qu'il jette.

#### Le test correct

    échantillon                garde            jette            CONTRASTE
    nos tickets RÉELS          35 à +0,128      25 à -0,079        +0,206
    simulés (Telegram)         26 à +0,202      36 à -0,082        +0,285
      dont recherche           11 à +0,227      20 à -0,163        +0,389
      dont JUGEMENT            15 à +0,184      16 à +0,018        +0,166
    TOUT RÉUNI                 61 à +0,159      61 à -0,081        +0,240

Le contraste est du même signe dans les quatre échantillons, **jugement compris**. Test du hasard
porté sur le contraste : 9,0 % sur les seuls tickets réels, **1,8 % sur tout réuni**.

#### Ce que ça vaut, jour par jour

    jour     achats  gardés  part   sans filtre   AVEC filtre   différence
    12/09       12      6    50 %      +17,34       +32,40        +15,06
    13/09       35     19    54 %     +125,86      +128,50         +2,64
    14/09       19     10    53 %     -345,79      -143,68       +202,10
    TOTAL       66     35    53 %     -202,59       +17,22       +219,80

**Il ne change presque rien les bons jours et coupe les deux tiers de la perte le mauvais.** Il ne
rogne pas les ailes, il coupe la traîne — l'inverse de tous les filtres enterrés cette semaine.

**Le coût** : 53 % des achats conservés, soit 11,7 par jour au lieu de 22. Les tickets qui manquent
pour trancher l'avantage mettront donc **deux fois plus longtemps** à arriver. On échange de la
vitesse d'apprentissage contre de la protection.

Aucun signe ne trie seul (65 à 73 % des achats passent chacun) : c'est leur combinaison qui décide.
En attente de décision de l'opérateur, rien n'est active.

### 3.80 — NFT : la rareté ne se paie pas là où elle n'est pas pricée, 2026-09-14

L'opérateur, après un premier examen que j'avais bâclé en jugeant le NFT à l'aune d'une stratégie à
4 minutes : *« pas forcément pour notre méthode, c'est sûr qu'un NFT ne se trade pas sur 4 min, sois
un peu intelligent »*. Reprise dans le bon ordre : sur un marché lent, l'inefficacité n'est pas dans
le flux mais dans le **prix de chaque objet**.

**Le plancher est efficace** : le 2ᵉ listing est à 0-2,7 % du 1ᵉʳ sur cinq collections. Pas de
bonnes affaires sous le plancher.

**Mais la rareté n'est pas toujours dans le prix demandé** : pricée sur 5 collections
(famous_fox −0,637 · cets_on_creck −0,302 · mad_lads −0,299 · okay_bears −0,267 · SMB −0,255),
**pas du tout** sur claynosaurz (+0,015) et smb_gen3 (+0,076). Anomalie apparente : des pièces rares
listées au prix des communes.

**Elle n'en est pas une.** 1 377 ventes réelles sur 40 à 90 jours, rareté calculée par nous à partir
des traits de chaque pièce (score statistique, somme des −log des fréquences) plutôt qu'un rang
tiers dont on ignore la formule :

    collection      corrélation rareté/prix de VENTE   écart quart rare vs commun
    claynosaurz        +0,057 (seuil 0,088)  non              +1 %
    smb_gen3           +0,096 (seuil 0,101)  non              +5 %
    mad_lads           +0,370 (seuil 0,088)  OUI             +11 %

**Les deux collections où la rareté n'est pas pricée sont exactement celles où elle ne se paie
pas.** Le marché a raison de l'ignorer. Et là où elle se paie, elle est déjà dans le prix demandé.

Le péage achève l'affaire : **7 %** à la revente (2 % Magic Eden + 5 % de royalties, relevés dans
les métadonnées). L'écart est de +1 % et +5 % là où il n'est pas pricé, +11 % là où il l'est déjà.

**Deux obstacles de collecte, instructifs tous les deux** : l'historique d'activité est à **99,7 %
des offres et listings** — 0,3 % de ventes, d'où un premier passage qui n'a rien ramené ; et le
paramètre `type=buyNow` fonctionne alors que `activityType` et `kind` sont **acceptés sans effet**,
renvoyant le flux non filtré. Un garde-fou vérifie désormais que le filtre a bien été applique.

Piste fermée sur un résultat, pas sur un manque de données.

### 3.81 — Aucun carnet n'a jamais eu d'espérance positive : j'ai mis de l'argent sur un contraste, 2026-09-15

**Le réel est arrêté** le 15/09 à 07h42 à la demande de l'opérateur (`telegram_rapide.mode` et
`execution.mode` en `paper`). Carnet réel du 12 au 15/09 : **−436,06 EUR sur 229 tickets** ; les deux
derniers jours −604,42 EUR. Portefeuille de l'opérateur : ~800 EUR devenus ~185.

#### 1. L'erreur de fond, trouvée en confrontant le simulateur au réel

Simulation complète, 1 180 jetons du 12 au 14/09 (base ancienne), coût d'exécution MESURÉ en chaîne
sur nos 227 tickets (prix payé et encaissé contre prix du pool) :

    groupe             simulé, avant coût   coût réel   espérance        à 30 EUR/ticket
    propre (516)          +0,004 / euro       −0,010     −0,006 / euro      −0,17 EUR
    telegram (66)         +0,010 / euro       −0,079     −0,069 / euro      −2,07 EUR
    autre (596)           −0,075 / euro

**Le filtre propre a été validé sur son CONTRASTE (+0,080 contre le reste), jamais sur son niveau,
qui est nul.** J'ai mis de l'argent sur « perd moins que les autres », pas sur « gagne ». La règle
§6 « un filtre se juge sur le contraste » est vraie pour JUGER UN FILTRE ; elle est fausse pour
décider d'ENGAGER DE L'ARGENT, qui ne dépend que du niveau après coûts réels. Telegram : les chiffres
positifs venaient du 12/09 (+0,121) et du 13/09 (+0,179), le 14/09 fait −0,281 ; et le simulateur
comptait 2,4 % de péage quand le réel en coûte 8 points de plus.

Hypothèse vérifiée et FAUSSE : le simulateur n'écarte pas les vidages (2 exclusions sur 1 180
candidats ; 10,1 % de vidés simulés côté propre contre 15,2 % réels).

#### 2. La perte, c'est la traîne : 15 % de vidages à −81 %

Carnet propre, 145 tickets réels : 22 vidages (r ≤ −0,5) = 86 % de la perte de la nuit. Non-vidés
+11 % en moyenne, vidés −81 % : **point mort à 11,9 % de vidages**, mesuré 15,2 % (IC 95 % 10,2-21,9).
Gain moyen du 15/09 +3,76 EUR contre perte moyenne −18,75 : il fallait 83 % de gagnants, on en a 67.

- **Rien ne les sépare à l'entrée** : 18 variables (pool, hausse, hausse 30 s, écart au plus haut,
  volatilité, k, part de l'offre dans le pool, âge, fraîcheur, twitter, site, description, créateur
  récidiviste, symbole/nom déjà vus, refus du garde-fou, heure). AUC par permutation + BH q=0,10 : la
  meilleure à 13 % de hasard. Puissance : avec 22 événements seule une AUC > 0,63 est détectable.
- **Les « 3 signes » n'en font que 2** : prix +0,7 % et réserve SOL +0,35 % sont en désaccord sur 1
  ticket sur 223 — à produit constant, prix ∝ réserve².
- **Un vidage est une cascade** : juste avant, le jeton est AU-DESSUS de notre prix (+1,2 % médiane) ;
  puis −84 % entre deux lectures de 10 s. Première grosse vente −24 % (médiane), 4 à 22 vendeurs
  distincts ensuite. Pas un retrait de liquidité (k −12 % au creux). La première vente fait souvent
  5 à 37 % de l'offre en UNE transaction (HIKKO 37,5 %, cashcaton 20,3 %, SharkCAT 16,5 %).
- **Ce n'est pas l'exécution** côté propre : au prix du pool −0,021/euro, réel −0,030. Côté Telegram
  l'exécution coûte −0,079/euro.

#### 3. Pourquoi « ça monte puis ça crashe »

- **Telegram : vraie dégradation** (permutation de l'ordre : 0,8 %). Le taux de vidage ne bouge pas ;
  ce sont les GAGNANTS qui fondent (hausse médiane des non-vidés +71 % au premier bloc, +1 à +5 %
  ensuite). Et la mise a été montée à 113 EUR pile à ce moment : à 30 EUR constants le carnet
  Telegram ferait +65,90 EUR au lieu de −248,29. Les hausses de mise ont coûté 314 EUR.
- **Propre : compatible avec le hasard** (11,7 %) — même prime, mêmes hausses du début à la fin. Le pic
  à +115,68 EUR après 23 tickets survient dans 16 % des permutations : c'est la forme d'une
  distribution à petits gains et traîne à −90 %.
- Point commun : on lance une stratégie à la fin d'une bonne série, puis on monte la mise.

#### 4. Tout ce qui a été testé pour limiter la perte, et fermé

- **15 règles de stop** rejouées sur les 227 chemins avec le coût réel de chaque ticket (rejeu calé :
  règle en place −131,74 contre −132,60 réel) : aucune positive, même en vente instantanée. Couper au
  premier changement de signe −200 EUR, sous le prix d'achat −265, tenir 30 s −74.
- **Vente sur cascade** (lecture du pool à la seconde, `intel/engines/vente_cascade.py`, 17 tests) :
  au seuil 30 % on sort à −57 % (propre) / −78 % (Telegram) en vendant 2 s après le signal. P&L
  rejoué +43 EUR sur 227 tickets, mais **+123,52 sur la première moitié et −80,50 sur la seconde**,
  probabilité d'être positif 65 %. Seuils plus bas pires (20 % : −611 EUR). Déployée en live à 07h09
  AVANT ce test — faute signalée par l'opérateur. Nos ventes réelles s'inscrivent en chaîne ≤ 2 s
  après la décision dans 97 % des cas.
- **Acheter après un crash** : 927 crashs ≥ 50 % en une lecture, achat à la lecture suivante —
  médiane −4,6 % à 30 s, −45 % à 240 s, avant coûts. Le prix continue de tomber.
- **Entrer plus tôt ou plus tard** (première lecture, 30, 60, 90, 120 s × sorties 30-480 s × 4
  groupes, coûts 3 % / 8 %) : 7 combinaisons positives sur 100, la meilleure (+0,232) portée par UN
  ticket à ×316 sur un pool de 2,5 SOL ; sans lui −0,054. Tout négatif.

#### 5. Ce qui reste

Une seule variable jamais mesurée et qui a une raison mécanique d'exister : **qui détient le stock à
l'instant d'acheter**. Non testable sur l'historique (les vendeurs ont vendu, les soldes actuels ne
disent plus rien) : enregistrement vers l'avant sur chaque candidat, acheté ou non.

**Vérifié sur l'historique le 15/09 (`vendeurs.py`)** : dans 22 vidages lisibles, le premier gros
vendeur détenait DÉJÀ au moins 80 % de ce qu'il a vendu au moment de notre achat dans **15 cas sur
22** (médiane 100 %). Son stock à notre achat : médiane 7,3 % de l'offre, ≥ 5 % dans 13 cas. Son
compte de jetons est né entre T−1 s et T+25 s après la migration : il a acheté dans les toutes
premières secondes. Telegram : 9 vidages sur 11 portaient un vendeur à 7-41 % visible à l'entrée.
Propre : plus éclaté — 3 sur 11 à ≥ 5 %, et 6 vendeurs sur 11 ont acheté APRÈS nous (T+72 à T+297 s),
donc invisibles à l'entrée. Ce qui manque pour conclure : la fréquence de tels détenteurs chez les
jetons qui ne se vident PAS. C'est ce que mesure `detenteurs.py`, verdict figé dans
`detenteurs_verdict.py` (200 tickets papier, deux moitiés, niveau après coût réel).

Note de méthode : `pool_quote` n'est remplie par AUCUN moteur — c'est `pools_propres.py` lancé à la
main (§3.74). Le 15/09 j'ai annoncé à tort qu'elle avait « cessé d'être remplie » après l'échange de
base. Relancée : 412 pools étiquetés.

### 3.82 — Qui détient le stock, et ce que ça rapporte : rien d'assez gros, 2026-09-15 après-midi

Objectif fixé par l'opérateur : **50 EUR par jour**, soit ~150 tickets à 30 EUR et **+1,1 % net par
ticket**. Tous les tests ci-dessous ont leurs règles écrites AVANT le calcul, coupure recherche /
jugement par date de naissance, niveau après coût réel.

**D'où vient le stock des vidages** (relu transaction par transaction sur 6 vidages) : achat du dernier
morceau de courbe pump.fun à T−1 s (HIKKO 52 %, GOLDGOOSE 51 %), ou TRANSFERT vers un portefeuille neuf
entre T+0 et T+12 s (cashcaton 20 %, BBRAIN 11 %, CHILLGPT 11 %, TROLLGPT 48 %). Rien n'est acheté dans
le pool : relire les transactions du POOL ne montre rien, relire celles du JETON sur [T−5, T+30 s] montre
le vendeur avec le bon montant (`premieres_secondes.py`, 1 885 jetons reconstruits via Helius
`getTransactionsForAddress`, ordre chronologique, ~1 s par jeton).

**Le sac ne prédit pas le vidage** (`sacs_verdict.py`) : le carnet propre est fait de lancements où UN
portefeuille détient 79,3 % de l'offre (toute la courbe) — médiane 79,3 % chez les vidés comme chez les
autres sur nos tickets réels. Simulé propre, 581 jetons : AUC 0,441 (légèrement inverse). NON.

**Récidive** : 908 jetons à détenteur ≥ 5 %, **811 portefeuilles distincts** — les orchestrateurs
prennent un portefeuille neuf à chaque fois. Au niveau du **financeur** (`financeurs.py`, 604 financeurs,
plateformes > 25 détenteurs écartées) le signal existe sur les deux moitiés : financeur qui a déjà vidé →
31,0 % / 40,6 % de vidages contre ~11 %. Mais il ne touche que 7 % du carnet propre : +1 centime par euro.

**Combinaison** (`combinaison_verdict.py`) : filtre détenteur/financeur + vente sur cascade. Simulé propre
−2,5 → +0,8 % (recherche), +2,4 → +3,8 % (jugement) : chaque effet ajoute sur les deux moitiés. MAIS
**la simulation surestime le réel de 3,7 points par euro sur les mêmes jetons** (123 tickets : réel −1,9 %,
simulé +1,7 %), et 37 tickets réels hors de la population simulée perdent −18 %. Rejouée sur l'argent réel :
−271 → −210 EUR. NON.

**Acheter la hausse confirmée** (`hausse_confirmee.py`) : née de 15 tickets réels achetés > +10 % au-dessus
de la lecture à 60 s (+26 % par euro sur les deux moitiés). Sur 105 jetons propres simulés : recherche
−12,6 %, jugement +2,9 % à coût prudent (sans best −0,6 %), **vidages 23-29 % au lieu de ~11 %**. Sur tous
les jetons, négatif partout. Les 15 tickets étaient de la chance. NON.

**Bilan du 15/09** : sur ce marché, à notre vitesse et sans position d'initié, aucune règle testée
n'atteint +1,1 % par ticket après coûts sur les deux moitiés — 18 variables d'entrée, 15 stops, vente sur
cascade, achat après crash, fin de cascade, 100 combinaisons d'entrée/sortie, sac, récidive portefeuille
et financeur, combinaison, hausse confirmée. Reste en cours, sur données neuves : `detenteurs.py` (soldes
réels à T+60 s), déjà affaibli par le résultat historique sur le sac.

### 3.83 — Audit du code : les prix du projet étaient faux, et la correction ne crée aucun avantage, 2026-09-15 soir

Audit demandé par l'opérateur (« creuse bien le code, tout le code, il y a d'autres problèmes »), après
qu'il a fallu son insistance pour trouver les comptes de jetons jamais fermés. Chaque point vérifié
sur la chaîne avant d'être retenu.

**DÉFAUT 1 — LA RÉSERVE VIRTUELLE (majeur, données).** Un pool PumpSwap issu d'une migration pump.fun
porte à l'octet 245 de son compte (301 octets) un u64 de **17,5845 SOL**, et échange au prix
**(SOL du coffre + 17,5845) / jetons**. Réserve implicite recalculée sur nos trades : 17,94 SOL en
médiane sur 239 achats, 17,27 sur 239 ventes (l'écart = les frais) ; une formule à 0,25 % de frais colle
aux jetons reçus à 1 % près. 3 423 pools à 17,5845, 1 883 à 0 (vérifié : ils échangent bien au prix du
coffre), 351 à d'autres valeurs non vérifiables (écartés). `prix_chaine.py` calculait SOL du coffre /
jetons : **prix trop bas de 17,6/(q+17,6), soit −18 % sur un pool frais de 80 SOL, −1 % à 1 400 SOL.**
Conséquences : la « prime à l'entrée » (+5,5 % propre, +24 % Telegram, §3.81) était ce biais, pas un
coût ; le garde-fou `max_ecart_pool_pct` refusait les pools frais en croyant la cotation trop chère ;
toutes les simulations exagéraient les gains (pool qui grossit) et les pertes (pool qui se vide).

**DÉFAUT 2 — LE RETARD (données).** `getMultipleAccounts` sans `commitment` = « finalized » :
**31 slots, 12,4 s** derrière la chaîne, horodaté à l'heure de lecture. `processed` : 0 slot.

**DÉFAUT 3 — LES COMPTES DE JETONS JAMAIS FERMÉS (argent).** 291 comptes vides, **0,4579 SOL récupérés**
le 15/09 (291 fermetures confirmées). Coût : 0,15 EUR par trade, 0,50 % à 30 EUR, compté en perte.

**COÛT RÉGLABLE.** Frais de priorité 0,0005 SOL par transaction : 0,00101 SOL par aller-retour mesuré,
0,32 % à 30 EUR.

**VÉRIFIÉ ET SANS PROBLÈME** : aucun sandwich (0 sur 221 achats et 222 ventes lus bloc par bloc ; 137
achats sont la première transaction du pool dans leur bloc, 55 suivent un autre robot qui achète le même
jeton) ; aucun achat hors carnet ni rachat en double sur 568 transactions ; une seule transaction en
échec ; ventes complètes (aucun jeton resté) ; migrations détectées en 1 s (p90 2 s) ; cycles réguliers
(10 s, p99 12 s) ; 98,6 % du SOL payé entre dans le pool.

**LE SIMULATEUR CORRIGÉ COLLE AU RÉEL** (`calibration_corrigee.py`, 236 tickets) :

    groupe      simulation d'avant   simulation corrigée   réel      écart restant
    propre            −2,3 %               −3,3 %          −5,8 %      −2,5 pts
    telegram         +10,7 %               +4,1 %          +1,3 %      −2,8 pts
    tous              +2,0 %               −0,8 %          −3,5 %      −2,6 pts

Écart réel − corrigé ticket par ticket : médiane −2,4 points, p25 −3,1, p75 −1,3 — un coût fixe (dépôt
0,5 + priorité 0,3 + frais de pool ~1,7). Sur Telegram, les deux tiers de l'optimisme venaient des prix.

**REFAIT AVEC LES PRIX CORRIGÉS** (`refaire_corrige.py` : prix échangeable, lectures décalées de 12 s,
exécution à +2 s, coût 2,0 et 2,5 points, 3 groupes × entrée 30/60/90 s × détention 60-480 s) : **aucune
combinaison positive sur les deux moitiés.** Règle en place (60 s / 240 s, coût 2,0) : propre −4,0 % /
−2,5 % ; telegram +11,6 % / −14,1 % ; autres −4,9 % / −6,9 %. La correction ne révèle aucun avantage
caché : elle retire un avantage illusoire.

**Corrigé dans le code** (non déployé au moment d'écrire) : `prix_chaine.py` lit la réserve virtuelle
(`reserve_virtuelle()`, octet 245, ignorée au-delà de 50 SOL), écrit `prix_sol` = prix échangeable et une
colonne `reserve_virtuelle`, lit en `processed` ; même correction dans `vente_cascade.py` et
`detenteurs.py`. Tests : `test_reserve_virtuelle.py`. **Tout `prix_sol` antérieur au déploiement est le
rapport des coffres** : le corriger avec `data/recherche/reserve_virtuelle.json` et décaler de 12 s.

### 3.84 — Grand balayage sur prix corrigés : rien ne survit à trois tranches, 2026-09-15 soir

Demande de l'opérateur : « trouve une stratégie avec ce nouveau simulateur, tente tout ». Protocole
unique pour tout : tranches chronologiques par naissance du pool (RECHERCHE 60 %, TRI 20 %, TEST FINAL
20 % lu une fois), rendement net de coût réel, plafonné à +300 % pour les moyennes, contrôle par
rendements mélangés. Scripts : `grand_balayage_table.py`, `grand_balayage.py`, `grand_balayage_ml.py`,
`grand_balayage_sorties.py`, `grand_balayage_long.py`, `verif_long_ml.py`.

**Table** : 27 135 décisions (3 157 pools × âges 20-600 s × durées 30-900 s), coût 1,7 % + impact.
Sans filtre (60 s / 240 s) : niveau +2,9 % (10/09), −0,4 % (12/09), −3,2 % (13/09), −3,3 % (14/09),
−11,8 % (15/09) ; **médiane positive tous les jours (+0,8 à +1,9 %)** ; vidages 11-14 %, puis 22,5 % le 15/09
avec des pools cinq fois plus petits (93 SOL médians). Le régime a changé dans la tranche finale.

- **Règles simples** (une et deux variables) : strict, 64 candidats contre 4 au hasard, 1 survivant au tri,
  −10,6 % au test. Large : 1 177 candidats, 73 survivants au tri (28 au hasard) ; **les 25 meilleurs sont
  TOUS négatifs au test** (−4 à −24 %). De la structure qui ne dure pas.
- **LightGBM, court terme** : le VIDAGE est prévisible hors échantillon (AUC 0,79 tri, 0,82 test, contre
  0,56 variable par variable) — mais n'acheter que les plus faibles risques rend −1,9 % / −2,2 à −2,9 % :
  les jetons qui ne se vident pas ne bougent pas assez pour couvrir 1,9 % de coût. Le gain du marché est
  dans les rares gros mouvements, qui sont aussi les plus risqués. Régression du rendement : corrélation
  +0,19 à +0,28 hors échantillon, stratégies toutes négatives au test.
- **Sorties dynamiques** (TP 5-100 %, SL −10 à −50 %, exécution à la lecture suivante) : un premier passage
  a donné 20 « GO » à +112 %… par BIAIS DE SURVIE (un chemin trop court rendait NaN sauf si le TP était
  touché). Corrigé : **0 règle ne survit** à recherche + tri.
- **Horizons longs** (DexScreener, 7 449 pools suivis 24 h ; son prix inclut la réserve virtuelle, SOL/USD
  implicite constant à 100-102 $) : tenir des heures rend −8 à −43 % en moyenne ; règles : 0 candidat.
  LightGBM 8 h top 10 % : tri +5,6 %, test +14,0 %, corrélation +0,55 — **effondré à la vérification** :
  sortie au dernier prix connu → +0,5 % ; un trade par jeton → −10,3 % ; 27 modèles sur 50 entraînés sur du
  bruit font aussi bien ; 0 réglage sur 9 positif au test.

**Conclusion** : sur ces cinq jours, avec des prix justes et le coût réel, aucune stratégie — règle, modèle,
sortie ou horizon — ne tient sur la tranche jamais vue. Deux pièges de simulation ont été attrapés AVANT
d'être annoncés (survie des chemins courts, doublons de jetons) ; ils auraient produit deux faux « GO ».
Limite honnête : cinq jours et un changement de régime le dernier jour. Le collecteur corrigé accumule
maintenant des données justes ; toute la chaîne est scriptée et se relance à l'identique.

### 3.85 — Les séries existent (régime de quelques heures), et les effets s'additionnent sans devenir positifs, 2026-09-15 nuit

L'opérateur : « je constate plusieurs bons coups qui se suivent et plusieurs mauvais qui se suivent, il y a
pas une cause ? » (`series.py`, `combinaison_finale.py`, prix corrigés, coût réduit 1,25 % + impact/2).

**Carnet réel** (244 tickets) : test des séries z = −0,57, compatible avec le hasard ; mais P(gagne) 63 %
contre 71 % après 2 gagnants et **78 % après 3 gagnants terminés** (n = 65).

**Population** (2 965 décisions) : corrélation résultat passé / suivant +0,04 (hasard global p = 0,026,
intra-jour p = 0,06 à 0,26 — surtout un effet de période). **Coupe-circuit à seuil fixe** (moyenne des 50
derniers résultats connus > 0) : on trade +2,8 % / −1,6 % / −1,1 %, à l'arrêt −2,8 % / −4,9 % / −7,4 %
(recherche / tri / test) : **écart +5,6 / +3,3 / +6,3 points, même signe sur les trois tranches.**

**Combinaison régime + classifieur de vidage + durée** (81 combinaisons figées) : les effets s'additionnent —
entrée 45 s, sortie 120 s : rien −1,1 / −2,6 / −5,2 % ; régime seul +1,8 / −0,6 / −4,5 ; risque seul
+1,5 / −2,0 / −3,7 ; **les deux +5,0 / +0,7 / −2,0 %, vidages 13 → 4 %, 12 → 5 %, 18 → 8 %**. Meilleure au test :
45 s / 240 s ≈ 0,0 %. Retenue (meilleur min recherche/tri) : test −2,0 %, NON ; 10 tirages sur 50 avec un
régime sans information temporelle font aussi bien au test.

**Taille des pools récents comme régime** (connue immédiatement) : le lien par jour (11/09 148 SOL −4,6 % ;
15/09 93 SOL −11,1 % ; 10/09 518 SOL +4,5 %) ne tient pas décision par décision. NON. Les pools « sans
réserve virtuelle » sont marginaux (3 à 22 décisions par tranche) : la dégradation du 15/09 est dans le
type standard.

**Conclusion** : on sait rendre la stratégie beaucoup moins mauvaise (+3 à +6 points, vidages divisés par deux
hors échantillon), pas gagnante sur la tranche jamais vue, dont le marché part de −5 %. Deux questions que
seules des données neuves trancheront : le régime du 15/09 est-il la nouvelle norme ? et la combinaison
tient-elle en papier, en temps réel ?

### 3.86 — TEST PAPIER VERS L'AVANT, pré-enregistré : départ le 15/09 à 12h24 UTC, verdict le 29/09

Accord de l'opérateur (« ok ») pour brancher la combinaison §3.85 en papier. `intel/research/papier_combo.py`,
processus séparé du moteur (lecture seule de sa base, écrit dans `/app/db/papier_combo.sqlite`), aucun ordre.

- **Population** : tout pool suivi par le collecteur corrigé (réserve virtuelle, lecture `processed`), première
  lecture ≤ 32 s (équivalent en temps réel du « ≤ 20 s d'âge vrai » de l'historique retardé de 12 s — ajusté
  avant toute issue jugée), ordre de 0,31 SOL ≤ 15 % du pool.
- **Décision à 45 s**, variables de prix identiques à la table (écart 1e-16 sur 400 pools). **Risque** :
  `modele_vidage.json`, LightGBM variables de prix seulement (AUC hors échantillon 0,78 / 0,82, même que le
  modèle complet), évalué en Python pur (`arbres.py`, écart 7e-16 avec LightGBM), seuil p80 = 0,2694.
  **Régime** : moyenne des 50 derniers résultats connus (décision 60 s, sortie 240 s, coût réduit) > 0.
- **Entrée** lecture ≈ 47 s ; **sorties** 167 s et 287 s. **Coûts** : réduit 1,25 % + impact/2 ; réel actuel
  1,7 % + impact + 0,5 %.
- **CRITÈRE ESSENTIEL** (régime ET risque, H = 120 s, coût réduit), jugé le **29/09** : moyenne ≥ +1,1 %, sans
  son meilleur ticket > 0, positive sur les deux moitiés. Sinon : on arrête ce marché. Secondaire : H = 240 s.
  Attente honnête écrite au départ : autour de −1 % à 0 % (historique du modèle allégé : tri −0,5 %, test −2,3 %).
- Rapport : `python -m intel.research.papier_combo --rapport`. Le processus s'arrête si le conteneur redémarre.

### 3.87 — Copier les portefeuilles gagnants : protocole pré-enregistré, 2026-09-15 après-midi

Recherche internet demandée par l'opérateur (sources dans la conversation) : aucune stratégie documentée ne
fait 50 €/jour sur ~1 000 € — l'arbitrage de financement rapporte 3-12 %/an net sur BTC/ETH (20-60 % sur les
petites), la tendance intraday BTC un Sharpe ~1,6 brut (≈ 32 %/an à 20 % de volatilité, ~0,9 €/jour), l'heure
22h UTC +0,07 % contre 0,10 % de frais taker. Sur pump.fun, trois papiers confirment ce qu'on a mesuré : un
modèle de graduation passe d'AUROC 0,86 à **0,46** sur la période suivante (arXiv 2607.02823) ; les réseaux de
snipers (1 012 groupes) n'apportent **aucun SOL entrant mesurable** une fois leurs propres achats retirés
(+6,3 %, IC [−0,5 ; +15,1], arXiv 2607.02795). La seule idée du marché jamais testée ici : **copier des
portefeuilles**. L'opérateur écarte les marchés liquides (« 1 € par jour autant faire du buy and hold »).

- **Données** : `copie_collecte.py` relit chaque échange réussi des 900 premières secondes des 3 157 pools du
  balayage (Helius `getTransactionsForAddress` sur le pool, filtre `status: succeeded` — sans ce filtre, 60
  pages de 100 transactions ne dépassaient pas 101 à 432 s sur 5 pools de la sonde ; avec, les mêmes pools
  sont lus jusqu'à 900 s). Volume machine : jusqu'à 16 144 transactions réussies en 15 min sur un pool, dont
  2 508 changent les coffres. Prix à la transaction vérifiés : écart médian **0,0000** avec
  `solana_prix_chaine` sur 15 pools. Coût ≈ 390 crédits par pool (10 par 100 transactions), ~1,2 M au total.
- **Piège trouvé à la sonde** : la création du pool et les mouvements de liquidité (les deux coffres bougent
  dans le même sens) passaient pour des échanges — une « vente » de 4 948 SOL. Corrigé avant la collecte.
  Reste ~30 achats par pool sans acheteur visible (compte créé et fermé dans la transaction) : non copiables,
  ignorés. Le rendement d'une copie vient du PRIX, pas du SOL attribué.
- **Protocole figé** dans la docstring de `copie_verdict.py` : retard 3 s, sortie à la première vente du
  meneur + 3 s ou à 900 s, coût du balayage, grille de 12 combinaisons (score propre/copie × k {3,5,10} ×
  seuil {0, +10 %}), sélection sur TRI, test lu une fois avec meneurs ré-appris sur RECHERCHE + TRI ; GO si
  moyenne ≥ +1,1 %, sans le meilleur > 0, n ≥ 30, positive sur chaque moitié ; témoins « tous les
  portefeuilles » et 50 tirages de meneurs au hasard.
- Attente honnête écrite avant : négative — le copieur achète toujours après son meneur, et des bots piègent
  les copieurs (arXiv 2601.08641).

**RÉSULTAT (15/09 ~18h, `data/recherche/copie/verdict.txt`) : NON.** 2 979 pools lus (169 tronqués à plus de
20 000 transactions, 9 en erreur), 736 449 portefeuilles, ~1,69 M crédits.
- Sélection sur TRI : 11 combinaisons sur 12 négatives (−2,2 à −8,0 %) ; retenue score propre, k ≥ 10, > +10 % :
  TRI +1,2 % (n = 213, sans le meilleur +0,4 %). Témoin « tous » : −3,1 à −3,5 %.
- **TEST FINAL** (411 meneurs ré-appris) : **−6,25 %** (n = 218), sans le meilleur −7,1 %, médiane −2,3 %, moitiés
  −3,4 / −9,1 %. Retard 1 s −7,1 %, 6 s −4,7 % : la vitesse n'est pas la cause. Témoin « tous » −7,1 % ; 10
  tirages au hasard sur 50 font aussi bien.
- **Mais la PERSISTANCE est réelle, hors échantillon** (rendement propre sur TRI) : gagnants de RECHERCHE
  (≥ 10 pools, > +10 %) **+8,8 %** par pool (166 actifs, n = 826) contre **−13,5 %** pour tous et −19,6 % pour les
  perdants ; ordre identique à k ≥ 5 (+4,0 / −16,3 / −21,5 %). Même ordre dans l'essai préliminaire interne à
  RECHERCHE (+8,3 / −4,8 / −8,4 %), où un « +15,7 % » par tranche d'âge d'achat s'est révélé être le même jeton
  compté plusieurs fois (−0,3 % à un trade par jeton) — attrapé avant d'être annoncé.
- Conclusion : un savoir-faire existe chez quelques centaines de portefeuilles, et il ne se transmet pas par la
  copie. Étape suivante demandée par l'opérateur : trouver POURQUOI ils gagnent (jetons choisis, moments, sorties,
  ventes fractionnées), croisé avec le technique et le fondamental, pour en faire une règle à nous. La tranche
  TEST a servi une fois ici : le test ultime d'une telle règle devra inclure des données neuves (vers l'avant).

### 3.88 — Pourquoi les bons gagnent : ni leurs signaux, ni un modèle de 56 variables ne passent le TEST, 2026-09-15 soir

Demande de l'opérateur : « fais tout ce que tu proposes » (analyse technique et fondamentale croisée).

- **Formule de prix confirmée** sur 364 000 échanges réels (un pool sur dix) : aucun prix payé meilleur que le prix
  du pool avant l'échange (0,0 %) ; sans réserve virtuelle, le prix payé tombe hors de l'intervalle avant/après
  (position médiane 51,6 à l'achat, −36,5 à la vente, contre 0,99 et 0,68 avec).
- **Décomposition des +8,8 %** des bons sur TRI (positions à un seul achat = 68,5 %, +10,0 %) : les renforts ne sont
  PAS la source (une première lecture l'affirmait, calcul faux, corrigé avant de conclure). L'écart rendement en SOL
  / rendement au prix du pool est à l'ENTRÉE (leur prix moyen payé sous le prix de fin de seconde) ; un copieur
  n'y a pas accès. Copie parfaite à la transaction suivante +3,8 %, à 3 s +1,5 %, après coût réel −1,1 %.
- **Leur rachat sur repli** (260 cas, médianes) : 32 s après l'achat, −13,8 % sous le plus haut, 4 s après une vente
  de 3,6 SOL (3,8 % du pool). Rendement −1,3 % (54 % gagnants) contre −17,1 % (39 %) pour les autres.
- **Historique complet des 325 bons** (`bons_historique.py`, 461 759 transactions, ~49 000 crédits) : 159
  transactions et 17 jetons par jour (médianes), 79 % signées par eux-mêmes ; **courbe pump.fun 37 % des
  transactions contre PumpSwap 30 %** ; 223 sur 325 achètent au moins un de nos jetons AVANT sa migration.
- **Étude croisée** (`bons_etude.py` → `etude.pkl`, 23 612 décisions × 56 variables visibles à l'instant : flux
  transaction par transaction, qualité des portefeuilles tirée des pools terminés avant, fondamental, régime ;
  `bons_verdict.py`, protocole figé) — TEST FINAL, coût réel : **F1 modèle du rendement −4,3 %** (TRI +11,2 %),
  **F2 imitation −7,7 %**, **F3 règles des bons −12,0 %** (TRI +6,9 %, 16 hasards sur 20 font aussi bien). NON ×3.
  Marché sans filtre (45 s / 120 s) : −3,3 / −5,6 / −7,1 %.
- **Incident** : un premier passage a donné « GO à +108 % » — un commentaire inséré dans la ligne `NON_VARS` avait
  fait entrer les colonnes de RÉSULTAT dans les variables. Vu dans le diagnostic avant toute annonce ; assertion
  ajoutée. Une variable de liquidité lue à A + 2 s (fuite de 2 s) avait aussi été remplacée avant le calcul.
- **Diagnostic stable R et T** : la frénésie perd — quintile le plus actif à 45 s (achats 30 s, acheteurs, volume,
  volatilité, plus gros achat) −6 à −18 % contre ≈ 0 % pour les plus calmes ; un acheteur dominant perd moins
  (−1 à −2 % contre −7 à −13 %). Aucun groupe au-dessus de +1,1 % après coût.
- Le TEST FINAL a maintenant servi deux fois (§3.87, §3.88). Toute règle future devra se valider sur des pools nés
  après le 15/09.
- **Où les bons gagnent en ARGENT RÉEL** (historique complet, SOL du portefeuille frais compris, 49 213 positions
  fermées, transactions à un seul jeton) : total +1 375 SOL / 80 471 engagés (+1,7 %) ; 197 portefeuilles sur 316
  gagnants, 10 % des portefeuilles font 76 % du gain. **Hors période de sélection** (achats après le 12/09 21h) :
  courbe → courbe +2,5 % (13 439 SOL), courbe → pool +10,7 % (2 662 SOL, conditionné à la graduation), **total
  courbe +3,9 %** ; **pool → pool −3,3 %** (8 501 SOL) ; autres DEX −2,2 %. Pendant la sélection : pool +8,0 %,
  courbe +0,4 %. **Leurs « +8,8 % par pool » (moyenne à poids égal, sans frais, 15 min) ne sont pas de l'argent : en
  SOL pondéré et frais compris, ils perdent dans les pools après la sélection.** Leur gain réel est sur la courbe
  pump.fun, avant la migration — une phase que notre moteur n'a jamais tradée.

### 3.89 — La courbe pump.fun : collecte, coûts, réglages, et les injections géantes dans les pools, 2026-09-15 nuit

Accord de l'opérateur (« vas-y ») pour ~500 000 crédits : `courbe_collecte.py` relit chaque échange réussi du
programme pump.fun, 13/09 00h → 15/09 00h UTC (mesure : 1 266 à 1 727 transactions par minute, ~115 000 par heure).
- **Formule** : prix = (30 + SOL de la courbe) / (jetons de la courbe + 73 M), exacte (erreur médiane 0,0) pour 1 099
  jetons sur 1 722 ; fin de courbe à 85,01 SOL. 621 jetons à autres réglages (ajustement impossible, erreur médiane
  80 %) ne dépassent quasi jamais 10 SOL (15) ni 30 SOL (1) : exclus au moment de la décision.
- **Coût mesuré** sur 207 échanges ≥ 0,05 SOL : l'acheteur paie 3,06 % de plus que ce qui entre dans la courbe, le
  vendeur touche 2,15 % de moins (médianes). Parts récurrentes : 0,48 % + 0,47 % (pump.fun) et ~0,30 %
  (créateur) par côté ; le reste = pourboires variables. Coût retenu : 2,5 % + 0,32 % + impact ; prudent +1 point.
- **Premier essai de la table** : créations presque jamais reconnues (357 au lieu de ~3 450 en 3 h) et créateur
  invisible — collecteur corrigé et relancé (3 heures relues, <1 % du forfait).
- **INJECTIONS GÉANTES** (vu en comparant fin de courbe et ouverture du pool) : exemple 12RaVJ, la migration
  dépose 67,4 SOL et 206,9 M jetons ; dans le MÊME bloc, EfeYMnNK… met 2 970 SOL et prend 201,1 M jetons (97 %) ;
  le prix du pool vaut alors ×1 289 la fin de courbe et y reste 600 s. **51,5 % des 3 148 pools** de la collecte
  dépassent 300 SOL de coffre dans les 10 premières secondes (coffre médian au 1er échange : 380 SOL) ; injecteurs
  récurrents (Bf6z1Tr4 108 pools, DFHkArJt 99, 5zWxvqhr 74, EwujkMx5 65, 98TQeKbR 60). C'est l'origine du « pool
  médian de 370 SOL » du carnet propre. Prix réels (notre bot y a tradé) ; pourquoi personne n'y revend les
  jetons de courbe à ×k² reste NON EXPLIQUÉ. Conséquence : l'étude de la courbe sort SUR la courbe (H ou 80 SOL),
  jamais au prix d'un pool.
- Vérifié sur la transaction : EfeYMnNK avait 3 100 SOL et en dépense 2 999,58 (2 969,93 dans le coffre, 28,15 de
  frais, 2 × 0,74 à deux comptes) en deux instructions d'achat PumpSwap. Sur 1 617 pools à injection : 759
  injecteurs distincts, 812 SOL médians ; **dans 92 % des pools l'injecteur ne revend rien du pool en 15 min** ;
  les autres achètent 22 SOL et vendent 12 SOL (médianes) pendant ce temps. Hypothèse NON prouvée : les jetons
  achetés sont redistribués vers d'autres adresses et vendus plus tard (cohérent avec les transferts vers des
  portefeuilles neufs à T+0-12 s de l'autopsie §3.81).

**Comment les bons gagnent sur la courbe** (demande de l'opérateur : « on essaie de comprendre comment les traders
gagnent », pas de les copier). Positions achetées sur la courbe après le 12/09 21h et fermées, SOL réel : 10 237
positions, 168 portefeuilles, +622 SOL / 16 099 (+3,87 %).
- 38 % de positions gagnantes, médiane −6,1 % ; les 10 % meilleures +1 847 SOL, les 90 % autres −1 225 SOL.
- Durée : 0-5 s −14,5 %, 5-30 s −6,7 %, 30-120 s −0,8 %, 2-10 min +5,7 %, 10-60 min +6,4 %, > 1 h +26,1 % (durée
  en partie conditionnée par l'issue : ils coupent vite, laissent courir).
- Sortie sur la courbe −0,65 % (9 199) ; sortie dans le pool +8,8 % (1 038, 65 % gagnantes) = plus que tout le gain.
- 3 portefeuilles font 89 % du gain (+270, +169, +117 SOL ; mises médianes 1,8-3,8 SOL).
- **Aucune de ces sorties dans un pool gonflé** : pools normaux 753 positions +5,3 % ; pools absents de la collecte
  285 positions +42,5 %. Les jetons à injection sont vraisemblablement des lancements d'opérateur où l'extérieur
  n'a pas de stock.

### 3.90 — La courbe : verdict NON ; l'après-midi du 15/09 est réel, et porté par les transactions « version 1 », 2026-09-15 soir

- **Collecte courbe terminée** : 6 429 818 transactions, ~643 000 crédits (plus que les ~500 000 annoncés). 55 709
  jetons créés en 2 jours, 1 259 complets (2,3 %). **Correction** : les « 621 jetons à autres réglages » ne sont pas
  petits — sur ce 2e type de courbe, le SOL ne passe pas par le compte lu (lamports figés à 0,001 SOL pendant que
  des millions de jetons sortent) ; 487 des 826 jetons tradés par les 3 meilleurs portefeuilles sont de ce type.
  Le « +25 % à moins de 1 SOL » était cet artefact.
- **Verdict courbe** (`courbe_verdict.py`, coût 2,5 % + 0,32 % + impact) : témoin négatif à tous les niveaux (ex.
  10 SOL / 5 min −20 / −23 / −22 %) ; F1 règles TRI +3,8 % → TEST −11,6 % NON ; F2 LightGBM TRI +7,9 % → TEST +6,8 %
  (n = 40, sans le meilleur −0,8 %, moitiés −0,4 / +13,9 %, 0 hasard sur 10) NON — seul signal au-dessus du hasard,
  à revoir sur jours neufs.
- **Frais — erreur de présentation corrigée** : `calibration_corrigee.py` compare le réel à la variation de prix
  BRUTE ; −2,62 pts (moyenne, 236 tickets ; médiane −2,41) = coût total réel, déjà reproduit par 1,7 % + impact
  (2,65 % à 30 €). Appliquer −2,4 en plus = double comptage (« −239 € » retiré). Tendance 240 s, 13-15/09, coût
  réel mesuré : **+47 €** ; sans l'après-midi du 15 : −290 € (30 €), −466 € (50 €).
- **Taille du ticket** (modèle 1,2 % + 0,001/s + dépôt 0,00204/s + 2s/(q+V), contrôle 2,65 % à 30 €) : optimum
  ~50 € ; au-delà de 100 € l'impact détruit tout. Ne change pas la conclusion.
- **Reconstruction de l'historique non biaisée** : même règle (45 → 287 s) sur 2 794 pools, prix reconstruits
  (décalage 12 s + V) contre transactions réelles : écart moyen +0,0001, corrélation 0,986, ≤ 0,8 pt par jour.
- **Historique en tranches de 6 h** (sans filtre, 240 s, coût réel) : 0 tranche sur 23 ≥ +10 %, 7 positives, meilleure
  +7,2 % (10/09 18h), pire −14,3 % (15/09 0h).
- **L'après-midi du 15/09 (14h24-20h30) vérifié transaction par transaction** (120 pools, ~50 000 crédits) :
  collecteur +15,3 %, transactions +13,9 % (corr. 0,987) ; net réel +407 € sans filtre, +314 € tendance à 30 €.
  **57 pools contiennent des transactions VERSION 1** (Helius refuse `maxSupportedTransactionVersion: 0`) : +26,7 %
  brut, +411 € nets ; les 63 autres +2,4 % brut, −4 € nets. Part des pools concernés : 9 / 2 979 (0,3 %) du 09/09 au
  15/09 7h47, 57 / 120 (48 %) l'après-midi du 15. Présence détectée sur 15 min ENTIÈRES (après l'entrée compris) :
  pas un signal tant que la présence avant 45 s n'est pas mesurée. Le moteur lit en version 0 (`solana_stream.py`,
  `prix_chaine.py`, `execution/solana.py`) : possible perte de lancements, à vérifier.
- **Ce qu'est la version 1** : mise à jour réseau SIMD-0385, activée le 15/09 à ~01h04 UTC (epoch 1035) ; taille max
  des transactions 1 232 → 4 096 octets, limites de calcul et frais de priorité dans l'en-tête ; tout appel RPC
  doit passer `maxSupportedTransactionVersion: 1`, sinon erreur −32015 (sources : Solana Compass, QuickNode,
  solana.com). Les 9 erreurs de la collecte de copie sont des pools nés après l'activation.
- **Le moteur n'est pas aveugle** : lancements vus par heure 35-47 avant 03h (Paris), 32-53 après ; pools suivis dès
  la naissance stables (26-43/h). Il lit des comptes, pas les transactions des autres. Reste à passer
  `maxSupportedTransactionVersion: 1` dans `execution/solana.py` (lecture de nos propres transactions) avant tout
  retour au réel, et dans les scripts de recherche qui lisent des transactions.
- **La version 1 AVANT l'achat est-elle un signal ?** (accord de l'opérateur ; `copie/v1_lecture.py`, 50 premières
  secondes de 377 pools nés après l'activation, 248 710 transactions, ~25 000 crédits ; rendement collecteur 47 →
  287 s, coût réel 2,62 pts, 30 €) : v1 avant 45 s 69 pools +8,9 % (+185 €, sans le meilleur +4,7 %) ; sans 308
  pools −4,3 % (−397 €). **Ne tient pas** : l'après-midi les deux groupes font pareil (+10,8 / +11,5 %) — l'écart
  « +411 / −4 € » de la fenêtre de 15 min venait surtout de transactions APRÈS l'entrée ; le matin 7h47-14h24 +9,4 %
  mais −4,2 % sans le meilleur ; avec la tendance +5,1 % (43) contre +6,6 % (77). Seule piste : tiers le plus actif
  (≥ 257 échanges avant 45 s) avec v1 +8,2 % (42) contre −18,2 % (84) — découpe après coup, une journée. À refaire
  sur des jours neufs avant toute conclusion.
- **PRÉ-ENREGISTRÉ le 15/09 à ~23h, avant toute donnée du 16/09** (l'opérateur : « t'es pas biaisé ? ») : sur les
  pools nés APRÈS le 16/09 00h (Paris), lecture des 50 premières secondes avec `maxSupportedTransactionVersion: 1`
  (même script `v1_lecture.py`), rendement collecteur entrée 47 s → sortie 287 s, coût réel 2,62 pts, 30 €.
  Règle A : ≥ 1 transaction version 1 réussie sur le pool avant 45 s. Règle B : A ET ≥ 257 échanges avant 45 s.
  Règle C (ajoutée le même soir, toujours avant les données du 16/09) : A ET tendance > 0 (moyenne des 50 derniers
  résultats connus), comparée à « tendance seule ». Le 15/09 : C 43 pools +5,1 % (+65 €), tendance sans v1 77
  pools +6,6 % (+152 €).
  **Règle D, ajoutée le 16/09 à 10h30** (après la découverte des injections, §3.90) : tendance N=50 ET coffre SOL à
  la naissance (1re lecture, âge ≤ 20 s) < 100 SOL, c'est-à-dire un pool NON gonflé par une injection ; variante de
  contrôle < 150 SOL ; témoins : tendance seule et sans filtre. Mesure rétrospective 13→16/09 (coût réel 2,62 pts,
  30 €) : **+210 € sur 264 tickets** (+2,65 %/ticket, sans le meilleur +1,53 %, **sans les 3 meilleurs −0,65 %**,
  moitiés +128 / +82 €, jours +1 / +32 / +236 / −60 €) ; par taille de coffre : < 100 SOL +210 €, 100-300 −234 €,
  300-1 000 −49 €, > 1 000 −19 € ; seuils voisins < 80 SOL −153 € (28 tickets), < 150 +145 €, < 200 +61 €. Seuil
  choisi APRÈS avoir vu les chiffres : à juger uniquement sur les jours neufs. Mécanisme connu avant le chiffre
  (pools d'opérateur où les bons traders ne vont jamais, et où l'ancien carnet propre allait toujours).

### 3.91 — Durée de détention et SORTIE : la prise de gain à +20/+30 % gagne partout, 2026-09-16

Exploration demandée par l'opérateur (« continue d'explorer »), sur les données déjà collectées, sans crédit.

- **Balayage entrée × sortie dans le sous-ensemble** (tendance N=50 + coffre naissance < 100 SOL, 13→16/09, coût
  réel, 30 €) : sortie 240 s la seule bonne à toutes les entrées (+110 / +210 / +230 / +124 / −448 € pour 30 / 45 /
  60 / 90 / 120 s d'entrée) ; **sortie 480 s catastrophique** (−1 636 à −2 390 €) : les effondrements tombent entre
  4 et 8 min, ce qui valide la sortie à 4 min de l'ancien bot.
- **Sorties sur le flux** (`sorties_flux.py`, transactions des 2 979 pools 09→15/09, sous-ensemble 524 tickets) :
  heure fixe 287 s +2,36 % (+371 €) ; **prise de gain +20 % +3,63 % (+570 €, sans le meilleur +3,07 %)**, +30 %
  identique (plateau), +50 % +2,93 % ; sortie sur grosse vente ≥ 3 % du coffre +0,85 % ; décrochage −15 % +0,38 %,
  −25 % −1,87 % : **couper sur la baisse vend dans le trou, prendre le gain paie.**
- **Généralité** (même période) : la prise de gain améliore les QUATRE populations — tous les pools −2,41 → −1,14 %,
  tendance seule +0,09 → +0,27 %, coffre < 100 seul −1,53 → +1,86 % (+704 €), tendance + coffre < 100 +2,36 →
  +3,63 %. Ce n'est donc pas un artefact de découpe.
- **Jours récents 13→16/09** (prix collecteur, 1 821 décisions) : tout reste négatif — tous −2 432 → −1 398 € ;
  tendance −613 → −410 € ; coffre < 100 −1 176 → **−172 €** ; tendance + coffre < 100 −270 → −98 € (+20 %) et
  −46 € (+30 %). Jour par jour du meilleur sous-ensemble : −142 / −73 / **+201** / −84 €.
- **Règle E, pré-enregistrée le 16/09 à 11h** (jours neufs uniquement) : entrée 45 s, **sortie à +25 % de gain
  sinon 240 s**, sur tendance N=50 et coffre naissance < 100 SOL ; témoins : la même sans prise de gain, et sans
  filtre. Seuil +25 % = milieu du plateau +20/+30 mesuré, choisi pour ne pas coller à un point.
- Acquis méthodologique : la prise de gain est le premier effet qui va dans le même sens sur 4 populations et 2
  périodes. Le niveau, lui, dépend du marché : il ne suffit pas à rendre la stratégie gagnante depuis le 13/09.
- **Délai d'exécution de la vente** (09→15/09, pool < 100 SOL, +25 %) : instantané +1 024 € (irréaliste), 1 s
  +591 €, 2 s +669 €, 5 s +708 €. Seule la vente au prix de la transaction déclenchante est flattée (+2,5 pts par
  ticket) ; au-delà d'une seconde le niveau est stable. **Toujours simuler la vente au moins une transaction après
  le déclenchement** — piège attrapé le 16/09 avant publication du chiffre.
- **Moment d'achat** (même population, sortie +25 % sinon 240 s, vente 2 s après) : 20 s −195 / +381 €, 30 s −5 /
  +503 €, **45 s +669 / +555 €**, 60 s +334 / +218 €, 90 s +232 / +117 €, 120 s −169 / −83 € (sans / avec
  tendance). 45 s reste le meilleur réglage.
- **VERDICT EN TROIS TRANCHES AVEC LA NOUVELLE SORTIE** (`balayage_tp.py`, 2 956 pools, cible = prise de gain
  +25 % sinon 240 s, vente 2 s après, coût réel) : **la découverte ne survit pas.** tous R −0,6 / T −3,6 /
  F −5,7 % ; coffre < 100 SOL R +2,6 (+521 €) / T −2,4 / F −7,8 % ; tendance R +1,2 / T −3,4 / F −3,2 % ;
  **tendance + coffre < 100 R +5,3 % (+449 €) / T −5,2 % / F −2,6 %**. Modèle LightGBM : TRI +2,4 % → TEST −1,6 %.
  Règles à une variable : 6 candidates en RECHERCHE, **0 survivante** au TRI (hasard : 0,0 par tirage). Les
  « +570 € » du sous-ensemble venaient donc de la période d'apprentissage (09→12/09). La prise de gain reste un
  vrai gain relatif (elle fait perdre moins partout), pas un avantage absolu.
- **POURQUOI ÇA SE DÉGRADE : c'est le marché, et c'est significatif** (bootstrap 10 000 + test de permutation,
  cible prise de gain +25 %) : tous les pools R −0,60 % / T −3,55 % / F −5,66 %, écart R − (T+F) = +3,99 points,
  **le hasard fait aussi bien dans 0,0 % des cas** ; coffre < 100 SOL +7,92 points (0,1 %) ; tendance + coffre
  < 100 +9,60 points (2,0 %). **Pente sur tous les pools : −1,50 point par jour, t = −4,2.** Conséquence chiffrée :
  sur la dernière tranche le ticket moyen part de −5,7 %, nos meilleurs filtres apportent +3 à +6 points, il en
  manque 2 à 4 pour revenir à zéro et 7 pour atteindre +1,1 %. C'est l'explication mesurée du « ça marche puis ça
  s'arrête » observé par l'opérateur depuis le début : ce n'est pas le filtre qui s'use, c'est le rendement de base
  du marché qui baisse. Reste à savoir si la pente dure (l'après-midi du 15/09 a été très positif : pas monotone).
- **NATURE DE LA RUPTURE** (3 premiers jours 09-11/09, 1 277 tickets, contre 3 derniers 13-15/09, 1 227 ; sortie
  heure fixe, coût réel) : Kolmogorov-Smirnov D = 0,148 p = 1,8e-12 ; moyennes −0,35 % → −5,67 % (t = 2,89,
  p = 0,004) ; **Mann-Whitney p = 0,15 : les rangs et la médiane n'ont pas bougé** — le changement est dans les
  queues. Décomposition : gagnants 48,5 → 55,8 % (+7,3), médiane −0,07 → +0,86 %, montées ≥ +25 % 31,3 → 27,1 %,
  effondrements ≤ −50 % 13,8 → 16,0 %, **gain moyen d'un gagnant +27,8 → +17,7 % (−10,1)**, **perte moyenne
  −26,8 → −35,1 % (−8,3)**. On gagne plus souvent, beaucoup moins gros, et on perd plus gros.
- **Oaxaca-Blinder** (LightGBM appris sur les 3 premiers jours, variables visibles à 45 s) : prévu sur la fin
  −2,27 % contre −5,67 % réalisé ; **écart total −5,32 points = −1,93 dû aux caractéristiques des jetons et −3,40
  à la réponse du marché**. Caractéristiques qui changent : coffre médian 282 → 389 SOL, échanges dans les 45
  premières secondes 78 → 168, acheteurs 53 → 96, SOL achetés 200 → 296. **Marché deux fois plus encombré à
  l'entrée, hausses plus petites, chutes plus profondes.**
- **COUPE-CIRCUIT RÉACTIF** (idée de l'opérateur : « dès qu'un jeton fait une grosse perte on se calme et on revient
  plus tard » ; `coupe_circuit.py`, rejeu chronologique, un résultat n'est connu qu'à naissance + 289 s) : avec la
  prise de gain +25 %, **pause de 30 min après tout ticket ≤ −30 %** donne +2,54 % (328 tickets, +249 €) sur les 3
  premiers jours et **−2,02 % (263 tickets, −160 €)** sur les 3 derniers, contre +0,76 % (+292 €) et −3,40 %
  (−1 251 €) sans coupe-circuit : **+1,8 et +1,4 point, même sens sur les deux périodes**, et la perte des mauvais
  jours divisée par 8 (4 fois moins de tickets). Pauses de 60 min moins bonnes (−4,79 %) : on rate les reprises.
  « 3 pertes de suite » (+1,75 % puis −3,75 %) est moins bon que « une grosse perte » : ce sont les grosses pertes
  qui annoncent les séries. Ne rend pas positif quand le marché est à −5,7 %.
  **Règle F pré-enregistrée (16/09)** : prise de gain +25 % sinon 240 s, ET pause 30 min après tout ticket ≤ −30 %.
### 3.92 — Règles G et H, et trois idées enterrées, 2026-09-16

**Règle G (pré-enregistrée le 16/09 à 10h30, jugée sur jours neufs)** : achat à 45 s (+2 s), **jetons peu
encombrés** (≤ 74 acheteurs dans les 45 premières secondes), **pool non gonflé** (coffre < 100 SOL à la naissance),
**vente à +25 % sinon 240 s**, **pause 30 min après tout ticket ≤ −30 %**. Comparatif sur 3 670 tickets (coût réel
2,62 pts, 30 EUR, ordre ≤ 15 % du pool) : sans filtre −2 655 €, + prise de gain −1 256 €, + tendance −197 €,
**règle G +553 €** (297 tickets, une entrée sur douze). Par période : 09→14/09 +545 €, 15/09 nuit −56 €,
15/09 matin −15 € (trou comblé par relecture, 10 700 crédits), 15/09 après-midi +93 €, 16/09 −14 €.
**Hors échantillon strict : +64 € sur 73 tickets (+0,9 %/ticket).**

**Ce qui limite G, mesuré** : dans sa propre famille de 144 réglages (foule × coffre × gain × pause), optimisés sur
09→12/09 et jugés sur 13→16/09, **68 sur 144 sont positifs au test, médiane −0,09 %** ; le meilleur réglage de
l'apprentissage donne +1,26 % au test contre +3,47 % pour G telle quelle. **Optimiser ne sert à rien**, et un vote
d'experts (10 meilleurs réglages) ne fait pas mieux (+1,15 % à 5 voix sur 10).
**Pourquoi aucune méthode adaptative ne peut trancher ici** : écart-type 45 points par ticket → il faut 8 170
tickets par règle (136 jours) pour distinguer deux règles qui diffèrent d'un point ; la borne de regret d'un
algorithme en ligne sur 144 règles et 150 tickets vaut 8,2 points par ticket, contre 1,1 point d'avantage cherché.

**Trois idées testées et enterrées le 16/09** :
- vendre en deux fois (moitié à +25 %, moitié à 240 s) : +257 € contre +553 € pour G ; le bruit baisse à peine
  (47,4 → 45,9 pts) et le gain se coupe de moitié ;
- écarter les jetons où un **vendeur massif** déjà repéré achète avant 45 s : le sens s'inverse selon le seuil
  (1 repérage : écarter coûte 419 € ; 3 repérages : écarter rapporte 170 €) — bruit ;
- **apport de liquidité** (teneur de marché) de 45 s à 287 s sur 3 268 pools : **−2,09 %** en moyenne, et surtout
  **les frais encaissés par les apporteurs valent +0,006 % en médiane** : sur PumpSwap les frais vont au protocole
  et au créateur. Ça enterre toute la famille market making / grid trading sur ce marché.

**Règle H, pré-enregistrée le 16/09 à 14h** (idée venue des guides internet, mesurée à l'envers de ce qu'ils
disent) : règle G **plus** la condition qu'au moins un détenteur pèse ≥ 5 % de l'offre à +30 s. Sur les 95 tickets
de G avec relevé disponible : au moins un détenteur ≥ 5 % → +7,66 % (36 tickets, +83 €) ; aucun → −2,29 %
(48 tickets, −33 €) ; plus gros détenteur > 10 % → +3,74 % contre ≤ 5 % → −2,29 %. Les guides recommandent
l'inverse (« aucun gros détenteur »). À juger sur les jours neufs avec `detenteurs.py`, qui tourne depuis le 15/09.

### 3.93 — Méthodes venues de marchés voisins : trois règles ajoutées, et la correction qui va avec, 2026-09-16

Recherche internet demandée par l'opérateur. Les guides de sniping ne donnent rien d'exploitable (course à la
vitesse, achat en bloc 0 depuis plusieurs portefeuilles). Trois idées transposables ont été testées sur nos 852 à
1 486 tickets (sortie +25 % sinon 240 s, coût réel, ordre ≤ 15 % du pool) :

- **Petites capitalisations, « first red day »** ([TradeZero]) → I : monté ≥ +30 % depuis la naissance et ≥ 15 %
  sous son plus haut à 45 s. 56 tickets +2,02 % (+34 €) mais **−3,35 % sans son meilleur** ; variante stricte
  +27,37 % sur 18 tickets, moitié due à un seul. Non concluant.
- **NFT, « volume maintenu »** → J : SOL acheté 30-45 s ≥ SOL acheté 0-15 s. Seule : **−1,53 %** (670 tickets) ;
  l'inverse (flux qui s'essouffle) +0,42 % (1 018). Avec G : +8,39 % (87) contre +6,59 % pour G seule.
- **IPO, « ouverture sous le prix d'offre »** → K : prix à 45 s SOUS le premier prix du pool → **+0,82 %** (402),
  contre **−1,50 %** (1 086) pour ceux déjà montés. L'analogie tient à l'envers de ce que disent les guides.

**Convergence utile** : flux qui accélère, prix qui monte, foule d'acheteurs — trois mesures indépendantes disent
que l'agitation des 45 premières secondes annonce une perte. C'est le mécanisme derrière la règle G.

**Règles I, J, K pré-enregistrées le 16/09 à 14h30** (l'opérateur : « ça ne coûte rien de l'ajouter »), **avec
correction pour test multiple** : onze règles sont désormais en lice (A-H plus I, J, K). Une règle ne sera déclarée
découverte que si elle réunit : moyenne ≥ +1,1 %, positive sans son meilleur ticket, positive sur les deux moitiés,
**et** supérieure au témoin « sans filtre » sur la même période, **et** encore positive après retrait de sa
meilleure journée. Sinon : observation, pas découverte.

### 3.94 — DEUXIÈME MARCHÉ : les courbes pump.fun libellées en jeton PUMP, invisibles depuis le début, 2026-09-16

En cherchant où passe le SOL des « courbes à autres réglages » (§3.90), la réponse est qu'il n'y en a pas : ces
jetons se tradent **contre le jeton de la plateforme**, mint `pumpCmXqMfrsAkQ5r49WcJnRayYRqmXz6ae8H7H9Dfn`. Vérifié
sur transaction : un portefeuille donne 52 380 PUMP et reçoit 39,4 M de jetons ; les seuls lamports qui bougent sont
les 0,0015 SOL de création d'un compte. Notre lecture cherchait des lamports : elle ne voyait donc rien.

- **Taille** : 621 jetons sur 1 722 actifs (36 %) dans l'échantillon de 3 heures du 13/09.
- **Enjeu** : **487 des 826 jetons** tradés par les trois portefeuilles qui font 89 % du gain réel des « bons »
  (§3.88) sont sur ce marché. C'est le seul endroit où on a la preuve mesurée que quelqu'un gagne, et le seul qu'on
  n'a jamais regardé. Le « +25 % à moins de 1 SOL » de §3.88 était cet artefact.
- **Collecte lancée le 16/09 à 15h** : `courbe_pump.py`, 13/09 12h → 14/09 12h UTC, les deux côtés (jetons et PUMP)
  lus pour chaque transaction, version 1 acceptée. Sonde : 54 lignes PUMP par minute (minorant, page tronquée),
  prix de l'ordre de 2,5e-3 PUMP par jeton. Coût attendu ~280 000 crédits.
- À mesurer ensuite : rendements par niveau de remplissage, coûts réels de ce marché, et ce que font les trois
  portefeuilles dedans. Rien n'est conclu tant que ce n'est pas mesuré.

- **Heure de la journée : RIEN de concluant.** 12h +12,4 % (5 jours positifs sur 5), 13h +9,1 %, 2h +7,0 %, contre
  4h −10,2 %, 8h −9,4 %, 15h −4,9 %. Avec 24 heures testées sur 5-6 jours, une heure à 5/5 sort du hasard environ
  une fois sur trois : pas de filtre horaire, à revoir quand on aura deux semaines.
  Verdict quand la règle A a ≥ 150 pools : GO si moyenne ≥ +1,1 %, sans le meilleur > 0, deux moitiés (par date)
  > 0 ; résultat donné en euros tout compris, avec le témoin « sans version 1 » à côté. Rien ne change d'ici là.

### 3.95 — G+D, et la découverte qui compte : la prise de gain vaut ce que valent nos YEUX, 2026-09-16

**Le mélange G+D** (foule ≤ 74, coffre < 100 SOL, tendance > 0, sortie +25 %, pause 30 min) donne le meilleur
rendement PAR TICKET de toutes les règles testées — +9,71 % sur 126 tickets, +10,28 % hors échantillon sur 33 —
mais 2,5 fois moins de tickets que G seule, donc moins d'euros au total (+367 € contre +607 €). Témoin
indispensable : aux **mêmes instants**, un jeton tiré au hasard dans la demi-heure rend déjà **+4,49 %** (le filtre
de tendance choisit des heures favorables) ; G+D est au 80ᵉ centile de ce témoin, soit p ≈ 0,20. Non significatif.

**Test papier vers l'avant monté et gelé** : `intel/research/papier_gd.py`, gel 16/09 15h40 UTC, critère écrit
avant les données (300 tickets ou 21 jours ; moyenne ≥ +4,5 %, deux moitiés > 0, positive sans son meilleur, et
au-dessus du 95ᵉ centile du témoin). Il ne lance aucun processus : il relit `v1_avant` (acheteurs), les prix du
moteur et la table `ref` de `papier_combo` (tendance). Zéro risque pour la production.

**Et c'est en le branchant que le vrai résultat est sorti.** Rejoué sur les 24 h déjà passées, il donne −15,24 %
là où le backtest donnait +10,28 % sur les mêmes jours. Diagnostic, une cause à la fois :

- **Ce n'est pas la définition de l'entrée** : dernière lecture ≤ 47 s (backtest) +5,93 %, première lecture ≥ 47 s
  (ce qu'on peut vraiment payer) +6,10 %. Aucun biais.
- **C'est la FINESSE DES PRIX.** Les tickets construits sur les transactions (écart médian 0 s) rendent +16,91 % ;
  les mêmes règles sur des lectures toutes les 10 s rendent +3,23 %.

**Mesure propre, appariée** (mêmes 3 245 pools, même règle, seule la cadence d'observation change ; le délai
d'exécution de 2 s reste partout) :

| vision du marché | tous les pools | coffre < 100 | foule ≤ 74 et coffre < 100 |
|---|---|---|---|
| chaque transaction | −1,09 % | | +5,23 % |
| une lecture / 2 s | −1,09 % | | +5,48 % |
| une lecture / 5 s | −1,18 % | | +4,12 % |
| une lecture / 10 s | −2,05 % | | +1,69 % |
| une lecture / 20 s (**cadence actuelle du carnet**) | −2,23 % | | +2,46 % |
| sortie à 287 s, sans prise de gain | −1,90 % | | — |

Écart apparié **2 s − 20 s** : **+1,14 pt par ticket [+0,27 ; +2,04]** sur 3 245 pools, **+2,64 pts
[+0,50 ; +4,65]** sur les 1 346 pools à coffre < 100 SOL. Les deux intervalles excluent zéro. Sur la période
c'est +159 € et +152 €, soit ≈ +21 €/jour à 30 € le ticket.

- **29 % des pools touchent +25 % entre 47 et 287 s, âge médian du déclenchement 93 s.** À 20 s de cadence on rate
  le sommet une fois sur deux ; c'est là que part l'argent.
- **Le coût est nul** : on n'a besoin d'yeux rapides que sur les positions TENUES, une ou deux à la fois. 120
  lectures par ticket, ~4 800 lectures par jour. `book_poll_seconds: 20` dans `config/intel.yaml`.
- **Ce que ça ne fait pas** : ça ne rend pas gagnante une sélection perdante. Tous pools confondus on reste à
  −1,09 % même en voyant chaque transaction. C'est un multiplicateur, pas un avantage.

**Conséquence sur tout ce qui a été annoncé avec une prise de gain.** Les chiffres des règles E, F, G, H, I, J, K
et D reposent en partie sur des prix par transaction : ils sont **optimistes de 1 à 4 points par ticket** tant que
le carnet lit à 20 s. Le chiffre exécutable de G est +2,46 %, pas +5,23 %. Toute mesure de sortie réactive doit
désormais être annoncée AVEC la cadence d'observation supposée.

**Déployé le 16/09 à 15h46** : `intel/engines/veille_rapide.py`, branché dans l'ordonnanceur à 2 s, 10 tests,
suite complète verte (243). Le moteur est en `mode: paper` — rien n'est signé. Ce que le déploiement a appris :

- **Un plancher de 5 s ralentissait EN SILENCE toutes les boucles.** `scheduler._loop` faisait
  `delay = max(5.0, interval)` : la veille réglée sur 2 s tournait à 5 s (vu sur les horodatages du journal,
  exactement 5,000 s d'écart). Le plancher devient un paramètre, à 1 s pour la veille seule. **`t1.poll_seconds: 2`
  est dans le même cas depuis toujours** — la boucle d'entrée T+1, censée tourner à 2 s, tourne à 5 s. Laissée
  telle quelle faute de mesure : à corriger seulement après avoir mesuré ce que la cadence vaut à l'ENTRÉE, comme
  on vient de le faire pour la sortie.
- **La veille a réveillé le carnet dès son premier passage** et les positions concernées se sont fermées.
- **Quatre positions papier traînaient ouvertes depuis 40 heures** (BIFROST, Deg, Cuck, MIKEANSON), bien au-delà de
  `max_hold_seconds: 900`. Deux d'entre elles n'ont aucune série de prix (leur pool n'a jamais été suivi), donc la
  veille ne peut pas les juger et s'abstient — c'est le comportement voulu : sans prix d'entrée dans la MÊME unité,
  on ne compare pas. Mais des positions papier bloquées faussent le carnet à blanc, à joindre au correctif du
  garde-fou d'impact en attente.
- **Deux modules de tests étaient déjà cassés avant cette séance**, tous deux sur `intel/execution/solana.py` :
  `test_prix_reels.py` importe `echange_reel`, supprimée du fichier (44 lignes retirées, plus aucun appelant) alors
  que le commit 7cabc4c l'avait ajoutée pour enregistrer le prix RÉELLEMENT payé ; `test_ecart_pool.py` attend une
  clé `ecart_pool_pct` qui n'est pas produite sur le chemin testé. Signalé, non corrigé : ce n'est pas à moi de
  décider si la suppression était voulue.

### 3.96 — Trois passes de vérification sur G et D, et la convention de vente qui gonflait tout, 2026-09-16

Mido : « si t'es sûr de toi tu peux refaire 3 passes ». Trois vérifications indépendantes, et elles ont trouvé.

**Passe 1 — une implémentation écrite à part.** Elle retombe EXACTEMENT sur l'original (D +610 € sur 621 tickets,
G+D +367 € sur 126) : pas de bug de calcul. Mais en changeant une convention à la fois, elle isole deux choix
arbitraires que je n'avais jamais justifiés :

- **La vente après déclenchement.** `toutes_regles.py` prenait la DERNIÈRE lecture ≤ déclenchement + 2 s —
  c'est-à-dire, sur une série à 10 s, le prix du déclenchement lui-même, donc **une vente sans délai**. En prenant
  la première lecture ≥ +2 s (ce qu'on peut vraiment exécuter) : **D +610 → +377 €, G +607 → +391 €, G+D +367 →
  +300 €.** Tous mes chiffres de la journée étaient gonflés de 20 à 40 %.
- **La série de référence de la tendance.** Sortie à heure fixe (le choix d'origine, et celui qu'implémente
  `papier_combo`) ou sortie avec prise de gain : D passe de +377 € à +151 €. Très sensible ; on garde la sortie à
  heure fixe, qui est celle qui tourne en direct.

**Passe 2 — tous les seuils bougent, un à la fois** (convention exécutable) :

| | foule | coffre | pause | fenêtre tendance | objectif | coût |
|---|---|---|---|---|---|---|
| **G+D** | +97 à +305 € (50→150) | +232 à +300 € (100→250) | +286 à +316 € (0→60 min) | +252 à +359 € (25/50/100) | +256 à +300 € (+15→+25 %) | +268 € à 3,5 pts |
| D | — | **+14 € à coffre 75** | +162 à +377 € | **+51 € à fenêtre 25** | — | — |
| G | +138 à +516 € | +100 à +391 € | +289 à +476 € | — | — | — |

**G+D est positif dans TOUTES les variantes testées.** D s'effondre sur deux réglages. Le seuil de 74 acheteurs
n'est pas un pic choisi après coup : 60 à 150 donnent tous du positif, l'optimum est plutôt vers 90.

**Passe 3 — contre le hasard** (2 000 tirages, mêmes instants, jeton tiré au hasard dans la demi-heure) :

| règle | vrai | hasard au même instant | centile |
|---|---|---|---|
| D | +2,85 % | +2,78 % | **50** |
| G | +4,19 % | +0,03 % | **99** |
| G+D | +8,14 % | +1,86 % | **98** |

**D ne choisit pas les jetons, il choisit les moments** : à instant égal, un tirage au hasard fait aussi bien.
C'est G qui sélectionne. Ça renverse ce que j'avais annoncé une heure plus tôt (« hors 10/09, D bat G+D »).

**Taille de mise.** Le coût ne dépend de la taille que par l'impact : ancré sur la calibration réelle
(2,62 pts à 30 €), il passe seulement à 3,47 % à 60 €, et le rendement par ticket reste à ~8,5 %. Les euros
montent donc presque proportionnellement : +46 €/jour à 30 €, +93 €/jour à 60 €. **Mais** sur 185 € de capital,
19 tickets/jour, 30 jours, 20 000 vies simulées, en rejouant la même distribution RECENTRÉE À ZÉRO (le scénario
« je me trompe ») : ruine 21 % à 10 €, 45 % à 20 €, 63 % à 30 €, 75 % à 50 €, **80 % à 60 €**. Conseillé : 20 €
tant que le test papier n'a pas parlé.

**Test papier G+D en direct** : `intel/research/papier_gd_direct.py`, gelé le 16/09 à 16h10 Paris. Il décide à
45 s en direct (le compte des acheteurs vient d'une lecture de chaîne payée seulement pour les pools qui ont
passé les deux filtres gratuits), suit jusqu'à 25 positions en parallèle dans UNE seule lecture, et la logique de
sortie est isolée dans `avancer()` avec 9 tests. Trois bugs à moi corrigés le soir même : deux `commit()`
manquants (la base paraissait vide, j'en ai conclu à tort que le test ne voyait aucun pool), un format d'affichage,
et un suivi séquentiel qui rendait le test aveugle 4 minutes par ticket alors que le moteur, lui, tient 4 lignes
en parallèle — Mido : « mais un truc ça veut dire que le bot parallélisé et pas le test ? ».

**Le test papier « régime + risque » est mort** : 187 tickets depuis le 15/09, **−3,26 % par ticket**, les deux
moitiés négatives, −165 €/jour. Son critère était ≥ +1,1 %. Verdict acquis avant l'échéance du 29/09.

### 3.97 — Le marché PUMP : pas un trésor, le contraire, 2026-09-16

24 h collectées (13/09 12h → 14/09 12h UTC) : **119 196 échanges réels, 1 072 jetons**. Le PUMP vaut 0,0036 $,
donc ce marché fait **4,8 M$ par jour** — réel, mais l'échange médian n'y fait que **9,74 $** et la réserve
médiane d'une courbe à l'entrée ~700 €.

**Notre règle appliquée telle quelle (entrée 45 s, sortie +25 % ou 287 s), 250 tickets exécutables :
−12,38 % par ticket**, intervalle 95 % [−15,83 ; −8,86], 28 % de gagnants, −928 € sur 24 h. Six à dix fois pire
que le marché SOL sur la même période.

Contrôles faits AVANT d'annoncer, cette fois :
- cohérence des prix : 77 % des échanges successifs montent — normal sur une courbe dominée par les achats ;
- **achat au tout premier échange : +27,28 %** (36 % de gagnants) ; à 45 s : −12,92 % ; à un instant au
  hasard : −14,85 % ;
- forme de la courbe, base 100 à 45 s : **99 à 60 s, 97 à 120 s, 90 à 180 s, 84 à 287 s, 76 après 10 min.**

**Ce que c'est** : un marché où les tout premiers acheteurs prennent l'argent des suivants, plus brutalement que
sur PumpSwap. Toute notre famille de stratégies entre à 45 s, c'est-à-dire du mauvais côté. Et c'est
l'explication la plus simple de la présence des « bons » portefeuilles là-bas (§3.94) : ils y sont tôt.
La piste est fermée pour nous, sauf à faire du sniping dans le bloc de création — autre métier, autres
concurrents.

**Correction, le soir même : j'avais fermé ce marché sur le TÉMOIN, pas sur notre règle.** Mido : « mais G+D ne
tourne pas sur PUMP ? ». Refait avec les filtres :

| règle | tickets | par ticket | intervalle 95 % |
|---|---|---|---|
| témoin | 250 | −12,38 % | −15,88 ; −8,83 |
| foule ≤ 74 | 212 | −12,65 % | −16,14 ; −9,19 |
| foule ≤ 30 | 146 | −13,35 % | −16,71 ; −9,80 |
| foule ≤ 15 | 84 | −10,87 % | −14,31 ; −7,30 |
| réserve > médiane + foule ≤ 74 | 88 | −15,05 % | −22,16 ; −7,84 |
| **tendance > 0, et donc G+D** | **0** | — | — |

Le filtre de foule n'y sert à rien (85 % des jetons PUMP ont déjà moins de 74 acheteurs à 45 s) et le resserrer
ne renverse rien. **Et G+D n'aurait pris AUCUN ticket** : la tendance — moyenne des 50 derniers résultats connus —
n'est jamais positive sur un marché où chaque ticket perd 12 %. Le filtre de tendance nous aurait tenus dehors
tout seul, sans qu'on ait rien su de ce marché. C'est le meilleur argument en sa faveur qu'on ait.

**Et la taille réelle de ce marché, pour ne pas la surestimer une seconde fois** : 36 % des JETONS mais **3,9 % des
TRANSACTIONS** (119 873 lignes PUMP trouvées en balayant 3 085 256 transactions du programme pump.fun sur 24 h).
C'est une longue traîne de petits jetons presque morts — médiane **6 échanges par jeton** sur toute leur vie.

**Leçon de méthode** : fermer une famille sur le témoin sans filtre, c'est fermer sur le mauvais test. Le témoin
dit si le marché est porteur ; il ne dit pas si NOTRE règle y gagne. Les deux mesures sont nécessaires.

### 3.98 — Le collecteur large : une collecte, toutes les règles, et la mesure iso-prod, 2026-09-17 nuit

Mido : *« l'important c'est d'avoir toutes ces règles qui tournent la nuit pour avoir plus de données »*, puis
*« il faut que ça soit simulé dans les mêmes conditions que la prod »*, puis *« on peut ajouter les deux méthodes
implémentées en prod aussi ? je veux être sûr que les autres font mieux »*. Les trois demandes sont justes et
corrigent un défaut de méthode que j'avais depuis le début.

**Un collecteur, pas cinq.** `papier_gd_direct.py --regle large` prend **tout ce qui a un coffre < 100 SOL** et
enregistre, à l'instant de la décision, les acheteurs et la tendance. On évalue ensuite n'importe quelle règle
— coffre seul, D, G, D+F, G+D — **sur exactement les mêmes tickets**. Un test par règle aurait vu des pools
différents : on aurait comparé des périodes de marché, pas des règles. L'inverse est impossible, un ticket refusé
ne revient jamais.

**Iso-prod sur le prix.** Jusqu'ici la sortie était calculée sur le prix du pool moins 2,62 points forfaitaires,
calibrés sur 236 tickets passés à un tout autre rythme. Le collecteur demande maintenant au **routeur**
(`lite-api.jup.ag`) la vraie cotation à l'entrée et à la sortie : l'aller-retour coté contient le glissement,
l'impact et les frais de route, sans aucune hypothèse. Les deux chiffres sont gardés côte à côte.

**Le coût du retard, mesuré et non supposé.** Entre la décision et le remplissage il y a la file du moteur, et je
supposais 2 s. Chaque entrée est recotée à **+2, +5 et +10 s** : l'écart avec la cotation initiale est le prix de
la lenteur, obtenu sans toucher à la production.

**Les deux carnets en service sont dans la comparaison.** Mon témoin était « acheter n'importe quoi » — la bonne
référence est ce qui tourne déjà. Le suivi va donc jusqu'à **1800 s** et note des jalons (prix à 167/287/600/900/
1200/1500/1800 s, premier franchissement de ×1,25, ×1,5, ×2 et du stop 0,7 avec le prix obtenable 2 s plus tard),
ce qui permet de rejouer la sortie de `telegram_rapide` (`TENUE_S = 240`, quatre minutes — Mido m'a repris, je la
croyais à 30 min) et celle du carnet `solana` (×1,5, stop 0,7, échéance 1800 s). **Réserve écrite dans le rapport
lui-même** : on rejoue leur SORTIE, pas leur entrée — `solana` entre à T+1 min sur des critères DexScreener qu'on
n'enregistre pas, `telegram_rapide` sur un signal Telegram qui ne se rejoue pas.

**Sept défauts trouvés en relisant le code, tous réels** (Mido : *« refais 2 lectures de code pour voir si t'as pas
loupé un truc »*) :

1. la cotation de sortie était prise en fin de suivi (30 min) et comparée à un calcul à 4 min — **deux durées de
   détention différentes**, donc un écart qui ne veut rien dire ; on cote désormais aussi à 287 s ;
2. `MAX_OUVERTS` restait à 25 alors que les positions durent six fois plus longtemps ;
3. le plafond de positions était en réalité **dicté par une limite d'API** (`getMultipleAccounts` accepte 100
   comptes, deux par position) ; la lecture se fait par lots de 100 et le plafond passe à 120 — la nuit donne 14
   positions simultanées (0,5 ticket/minute mesuré) mais le flux de journée est trois à quatre fois plus dense ;
4. **les positions perdues à chaque redémarrage restaient « prises » sans issue** : l'analyse les aurait comptées
   comme des tickets dont on ignore la sortie. Elles sont marquées `interrompu` et écartées ;
5. les `INSERT` de `decision` utilisaient l'ordre implicite des colonnes : ajouter une colonne les cassait tous, et
   un redémarrage des deux tests gelés par le chien de garde aurait planté ;
6. `--rapport` posait un gel dans une base vierge — un rapport lit, il n'écrit jamais ;
7. **le gel du collecteur large était faux** : au premier démarrage il avait repris par défaut celui du test à 45 s
   (14h10 UTC) au lieu de son propre lancement (22h41 UTC). Le gel s'écrit maintenant dans la base (table `meta`)
   et se relit tout seul, donc aucune relance ne peut plus remettre un test à zéro ni lui faire juger des pools
   nés avant sa propre décision.

**Chien de garde.** Deux coupures d'internet dans la soirée ont montré que l'écoute des créations de pool ne se
reconnecte pas au retour du réseau : les boucles tournaient, le conteneur résolvait les noms, et plus un seul
lancement n'arrivait pendant une heure. `surveillance.sh` détecte l'absence de lancement depuis 15 min, vérifie
que le réseau répond — sinon il attend, redémarrer pendant une coupure ne sert à rien — et relance le moteur et
les six processus, au plus une fois par demi-heure.

### 3.99 — Le modèle ne mesure pas le danger, il mesure la VIE, 2026-09-17

Depuis le 15/09 le carnet `papier_combo` écarte les jetons dont le modèle d'arbres prédit une
probabilité de vidage supérieure à 0,2694 (le 80e centile d'apprentissage). Ce seuil gagnait, et je
n'avais jamais vérifié POURQUOI. En découpant les 1 356 tickets terminés en cinq groupes de risque
prédit croissant, le résultat n'a rien d'un filtre de sécurité :

| groupe | risque moyen | chute < −50 % | gain > +50 % | rendement |
|---|---|---|---|---|
| Q1, le plus « sûr » | 0,031 | 4,1 % | **0,0 %** (0 sur 271) | +1,03 % |
| Q2 | 0,112 | 18,1 % | 1,1 % | −6,49 % |
| Q3 | 0,225 | 23,2 % | 16,6 % | +2,28 % |
| **Q4** | 0,270 | 25,1 % | **18,8 %** | **+5,57 %** |
| Q5, le plus risqué | 0,355 | 33,1 % | 18,0 % | −5,70 % |

**Un jeton incapable de s'effondrer est un jeton où il ne se passe rien.** Le modèle sépare le mort
du vivant, pas le sain du pourri ; la probabilité de vidage et la probabilité de gros gain montent
ensemble. Deux choses s'expliquent d'un coup : pourquoi toutes les pondérations continues par le
score perdent de l'argent — elles concentrent la mise sur Q1 et Q2, c'est-à-dire sur le néant et sur
le pire groupe ; et pourquoi 0,2694 « marchait » — il tombe par accident au milieu de Q4, le seul
groupe rentable. Le seuil gagnait pour une raison qui n'était pas la sienne.

**La bande du milieu.** Viser `0,20 ≤ risque < 0,35` plutôt qu'éviter le risque, sur ces mêmes
1 356 tickets (H=240, coût réduit, mise 30 EUR) :

| bande | tickets | par ticket | total | sans ses 3 meilleurs | 15/09 | 16/09 | 17/09 |
|---|---|---|---|---|---|---|---|
| tout | 1 356 | −0,67 % | −272 € | −1,33 % | +205 | −195 | −282 |
| 0,00–0,2694, le filtre en service | 958 | +0,68 % | +197 € | −0,26 % | +54 | +75 | +67 |
| **0,20–0,35** | **683** | **+3,90 %** | **+799 €** | **+2,59 %** | **+339** | **+156** | **+304** |
| 0,24–0,30 | 326 | +7,64 % | +747 € | +4,92 % | +249 | +73 | +425 |
| 0,25–0,45 | 523 | −0,18 % | −28 € | −1,91 % | +226 | −73 | −182 |

99,9e centile contre 4 000 tirages de même taille (le hasard donne −0,70 %). C'est un plateau et non
un pic — 0,22–0,32 donne +3,81 %, 0,20–0,30 +4,34 % — mais déborder vers le haut le détruit.

**La réserve, et elle est décisive : ces 1 356 tickets ont servi à TROUVER la bande, ils ne peuvent
donc pas la valider.** D'où le gel, écrit dans `papier_combo.py` le 17/09 à 16h30 UTC (18h30 Paris),
avant l'arrivée du premier ticket concerné : bornes [0,20 ; 0,35[, critère ≥ +2,00 % par ticket,
positif sur les deux moitiés et positif sans ses trois meilleurs, au premier atteint de 300 tickets
postérieurs au gel ou de 21 jours. Sinon la bande est abandonnée. Le +2 % est ce qui la sépare du
reste : le hasard donne −0,70 %, le filtre en service +0,68 %. La décision du carnet en service n'a
PAS été touchée — il garde son seuil 0,2694, sinon son propre test gelé ne voudrait plus rien dire ;
la bande se rejoue sur les scores déjà enregistrés, comme le collecteur large rejoue ses règles.

### 3.100 — 12,3 % du modèle tire à blanc, et le NaN qui fabrique de fausses découvertes, 2026-09-17 soir

Question de Mido : faut-il finetuner LightGBM, essayer d'autres architectures, empiler des modèles,
et peut-on améliorer la prévision des CHUTES ? Réponse mesurée, et deux trouvailles au passage.

**Ce que le score prédit vraiment.** Sur 1 369 tickets, AUC du score pour prédire la chute > 50 % :
**0,672** ; pour le gros gain > +50 % : **0,724** ; pour > +100 % : **0,740**. Le modèle a été
entraîné à détecter le vidage et il est MEILLEUR à détecter l'inverse. Ce n'est pas un détecteur de
danger, c'est un détecteur de mouvement, plus fort du côté haussier (§3.99). Le finetuner sur la
chute optimiserait donc la moins bonne de ses deux capacités : l'effort utile est sur la CIBLE
(entraîner sur le gain attendu) et sur des variables NON-PRIX, pas sur l'architecture.

**Le piège du NaN, qui m'a fabriqué une fausse découverte en une minute.** En cherchant si
l'information « ça chute » est séparable de « ça monte » à l'intérieur de la bande, j'ai obtenu
AUC 0,221 pour `ret_30` — spectaculaire. C'était faux. Les variables contiennent des NaN, **et en
Python toute comparaison avec NaN est fausse : `sorted()` rend alors un ordre arbitraire sans lever
la moindre erreur**, ce qui corrompt silencieusement tri et AUC. Corrigé et recoupé
chronologiquement en deux moitiés, avec une barre de bruit tirée d'une variable continue aléatoire
(0,063 au 99e centile, pour 17 variables testées) : **aucune variable ne tient sur les deux
moitiés**. `ret_30` fait 0,488/0,469 puis 0,442/0,417 ; seul `dd_max` frôle la barre, ce que le
hasard produit sur 17 essais. **Conclusion : avec les variables de prix actuelles, la prévision des
chutes n'est pas améliorable — l'information n'y est pas.** La leçon de méthode :
*nettoyer les NaN AVANT tout tri ou toute AUC ; un NaN ne lève pas d'erreur, il fabrique un résultat.*

**Le défaut trouvé grâce au bug : le modèle appris n'est pas le modèle exécuté.** En comptant les
NaN, trois variables sortent à **100 % manquantes sur les 1 376 tickets** : `ret_60`, `ret_120`,
`q_croiss_60`. C'est mécanique — on décide à **45 s**, un rendement à 60 ou 120 s n'existe pas
encore. Or le modèle **coupe 518 fois sur elles, soit 12,3 % de ses 4 200 coupes** ; et s'il a
construit ces coupes, c'est qu'à l'entraînement ces variables avaient des valeurs, sinon l'algorithme
n'aurait eu aucun gain à les choisir. Le modèle a donc appris sur des jetons observés à 120 s ou plus
et on l'applique à 45 s : à chaque coupe concernée il part du côté « par défaut », à l'aveugle.
**C'est la première raison SOLIDE de réentraîner** — pas la dérive du marché, un défaut de
construction. La réparation est mesurable : même recette, mêmes données, seulement les variables
disponibles à 45 s, puis comparaison des AUC sur les mêmes tickets. Réserve : le défaut est prouvé,
le gain de sa réparation ne l'est pas. Le test gelé de la bande reste valide — elle est définie sur
le score réellement produit en production, défaut compris.

### 3.101 — La foule dans la bande : pré-enregistrée faute de pouvoir la trancher, 2026-09-17 soir

Puisque l'information de PRIX est épuisée à l'intérieur de la bande (§3.100), la suite logique est
d'y apporter une variable **non-prix**. Le collecteur large en enregistre une qui ne doit rien au
prix : le nombre d'**acheteurs uniques** avant la décision — la variable de la règle G, que le
modèle n'a jamais vue.

**Résultat : le test ne peut pas répondre aujourd'hui, et c'est ça le résultat.** Sur les 251
tickets de la bande joignables avec le collecteur large, couper à la médiane donne +10,8 % puis
+6,7 % en faveur du groupe « beaucoup d'acheteurs », **même signe sur les deux moitiés**. Mais la
barre de bruit — mêmes données, valeurs mélangées 400 fois — est de **±20 %**. L'écart observé est
donc plus petit que ce que le hasard produit couramment. Aucune des six variables non-prix testées
(acheteurs, coffre, impact d'entrée, jetons à 2/5/10 s) ne franchit sa barre.

La raison est arithmétique : **un ticket de la bande varie de 70 points d'écart-type** (la bande
contient les jetons qui bougent, c'est sa définition), donc 125 tickets par moitié ne laissent
rien voir sous ~25 points. Le calcul de puissance donne la suite du calendrier :

| tickets | écart détectable | date à 335/jour |
|---|---|---|
| 253 (17/09) | 25 pts | — |
| 696 | 15 pts | 19/09 |
| 1 088 | 12 pts | 20/09 |
| 1 568 | 10 pts | 21/09 |

**Ne pas confondre « rien ne tient » avec « la variable est inutile ».** L'instrument est trop
grossier, comme un pèse-personne sous une lettre. D'où le pré-enregistrement, écrit dans
`intel/research/piste_foule.py` et gelé le 17/09 à 20h00 UTC (22h00 Paris) : seuil **91 acheteurs**
(la médiane observée AVANT le gel, jamais réajustée), direction annoncée (le groupe haut rend plus),
critère **≥ +10 points de même signe sur les deux moitiés**, échéance **1 568 tickets postérieurs au
gel ou 21 jours**. Le 1 568 n'est pas un chiffre rond : c'est 32 × (0,70/0,10)², la taille qu'il faut
pour distinguer 10 points — un test verrouille cette égalité pour qu'on ne s'autorise pas à conclure
plus tôt sur du bruit.

**Bloqueur noté au passage** : le conteneur n'a ni `lightgbm`, ni `numpy`, ni `scikit-learn` — la
réparation du modèle (§3.100, réentraîner sur les 16 variables réellement disponibles à 45 s) n'est
donc pas faisable là où tournent les données. Il faudra exporter le jeu d'entraînement vers un
environnement qui les possède.

### 3.102 — La bande passe tous les contrôles de fragilité, et sa sortie n'est pas optimisable, 2026-09-17 nuit

**Deux instruments indépendants mesurent les mêmes tickets.** `papier_combo` (donc la bande) évalue
ses sorties sur la table du moteur, **cadencée à 10 s**, en tenue sèche de 240 s. `papier_large` suit
les MÊMES pools en lisant la chaîne lui-même **toutes les 1 s**, avec une autre sortie. Sur les 282
tickets communs — c'est le contrôle de fragilité le plus sévère qu'on puisse faire sans attendre :

| | grille 10 s, tenue 240 s | grille 1 s, TP +25 %/287 s |
|---|---|---|
| dans la bande | +3,11 % | −1,18 % |
| hors bande | −22,01 % | −13,29 % |
| **écart** | **+25,1 pts** | **+12,1 pts** |

**Le NIVEAU dépend de l'instrument, l'AVANTAGE non.** C'est exactement la distinction de §3.81 : un
contraste juge une sélection, seul le niveau fait de l'argent. Ici la sélection tient.

**Cinq sorties, données identiques à 1 s, seule la règle change** (223 tickets dans la bande) :

| sortie | dans la bande | hors bande | écart |
|---|---|---|---|
| tenue sèche 167 s | −0,91 % | −16,53 % | +15,6 pts |
| tenue sèche 287 s | +0,86 % | −24,63 % | +25,5 pts |
| TP +25 % sinon 287 s | −1,18 % | −13,29 % | +12,1 pts |
| TP +25 % + stop 0,7 | +0,99 % | −5,69 % | +6,7 pts |
| TP +50 % sinon 287 s | +2,90 % | −18,19 % | +21,1 pts |

**L'avantage de la bande survit aux cinq** (+6,7 à +25,5 points). C'est le résultat solide.

**Et la sortie n'est PAS optimisable sur ces données — je m'en suis abstenu.** Le tableau ci-dessus
crie « prends TP +50 % » (+2,90 % contre −1,18 %). Comparaison APPARIÉE, chaque ticket étant son
propre témoin, ce qui divise fortement le bruit :

| contre la tenue sèche 287 s | différence/ticket | intervalle 95 % | verdict |
|---|---|---|---|
| TP +25 % | −2,03 pts | [−9,66 ; +5,29] | indiscernable |
| TP +50 % | +2,05 pts | [−4,62 ; +8,18] | indiscernable |
| TP +25 % + stop | +0,13 pts | [−7,72 ; +7,26] | indiscernable |

Et les deux moitiés chronologiques changent de signe : TP +25 % fait **+8,28** puis **−12,25**.
Avec 223 tickets à 70 points d'écart-type, une différence de 2 points est invisible même appariée.
**Choisir TP +50 % ici, ce serait optimiser du bruit** — la faute exacte qui a coûté 800 EUR.

### 3.103 — Audit iso-prod du 17/09 au soir : sain, et deux précisions de fonctionnement

Quatre collecteurs écrivent, dernière décision il y a moins d'une minute, **zéro position prise sans
issue** après une heure (les « 907 sans issue » du premier passage étaient les pools REJETÉS,
`pris=0` — vérifié avant d'alerter). Un seul trou historique, 16/09 21h23→23h42, celui des coupures
d'internet déjà traitées par le chien de garde.

Deux précisions qui comptent pour lire les chiffres, et qui ne sont PAS des défauts :
- **`solana_prix_chaine` est cadencée à 10 s** et n'est écrite que par `prix_chaine.py`. La veille à
  1 s ne remplit pas cette table — elle réveille le carnet et met à jour `positions.peak_price`.
  La cadence observée (médiane 10,0 s, min 9, max 11) est donc conforme au réglage.
- **Les tests papier n'ont pas la même source** : `papier_combo` lit cette table (10 s),
  `papier_gd_direct` lit la chaîne lui-même à 1 s. Toutes les règles comparées à l'intérieur d'un
  même collecteur restent comparables ; entre collecteurs, la granularité diffère.

### 3.104 — Réparer le modèle et l'enrichir : les deux pistes se ferment, la découverte de fond tient, 2026-09-17 nuit

L'environnement conda `qrt` de l'hôte possède `lightgbm 4.7`, `pandas`, `numpy`, `scikit-learn` — la
réparation du §3.100 est donc faisable hors ligne, et `data/recherche/balayage/table.pkl` (27 135
lignes, 47 colonnes) est toujours là. **Rien n'a été déployé : le modèle en service alimente le test
gelé de la bande, le remplacer l'annulerait.**

**Le défaut est entièrement expliqué.** La table contient **dix âges de décision** (20 à 600 s) et le
modèle a été entraîné « tous âges confondus » (`grand_balayage_ml.py`). À A=45 — le seul âge où on
s'en sert — `ret_120` est manquante à 100 %, `ret_60` et `q_croiss_60` à 98,4 %, alors qu'elles ne
manquent qu'à 49,6 % et 27,9 % sur l'ensemble. Le modèle a donc appris ces variables sur les autres
âges. Seules **3 010 lignes sur 27 135 sont à A=45**.

**La réparation marche, et ne rapporte presque rien.** Apprentissage sur la tranche R (60 % les plus
anciens), mesure sur la tranche F (20 % les plus récents, jamais vue), restreinte à A=45 :

| modèle | AUC hors éch. à A=45 | coupes à blanc |
|---|---|---|
| en service : 19 var, tous âges | 0,757 | **12,3 %** |
| sans les mortes : 16 var, tous âges | **0,763** | 0 % |
| sans les mortes : 16 var, A=45 seul | 0,757 | 0 % |
| 16 var + non-prix, tous âges | **0,765** | 0 % |
| 16 var + non-prix, A=45 seul | 0,755 | 0 % |

Retirer les variables mortes supprime bien les 12,3 % de coupes à l'aveugle mais ne gagne que
**+0,006 d'AUC** — LightGBM absorbait déjà presque tout par ses directions par défaut. N'entraîner
que sur A=45 **ne vaut rien** (0,757) : perdre 90 % des lignes annule le bénéfice de conditions
identiques. Et les **variables non-prix n'ajoutent que +0,002** (`createur_prec`, `det_a_vide`,
`fin_a_vide`, `marche_*`, `sac1`, `n_sacs5`, `n_descr`, `telegram`, `twitter`, `site`). Vérifié
avant usage : elles **ne fuitent pas** — `grand_balayage_table.py` ne retient que ce qui était
CONNU avant la décision (`connu = naissance + 302 s`, `bisect_right`, le jeton lui-même exclu).
Réserve : elles sont très lacunaires (`sac1` 60 % manquante, `telegram` 58 %), donc « n'ajoutent
rien » vaut pour cette collecte-ci, pas pour l'idée en général.

**En euros, aucun des cinq ne se distingue** : bande en centiles sur la tranche F à A=45, les cinq
modèles rendent entre −10,59 % et −11,74 % par ticket, pour une erreur-type de 2,5 points. Un écart
sous ~5 points n'est pas interprétable — donc il n'y a rien à choisir.

**Ce qui tient, et c'est le point important : la découverte de fond se reproduit sur une période
indépendante.** Sur le 12→15/09, avec un modèle entraîné uniquement sur le 09→12/09 (1 198 tickets
hors échantillon) :

| quintile | risque | chute < −50 % | gain > +50 % | rendement |
|---|---|---|---|---|
| Q1 | 0,007 | 2,9 % | **0,0 %** | −1,32 % |
| Q2 | 0,020 | 5,9 % | **0,0 %** | −2,06 % |
| Q3 | 0,062 | 10,4 % | 1,2 % | −8,16 % |
| Q4 | 0,218 | 25,1 % | **13,8 %** | −3,25 % |
| Q5 | 0,319 | 32,9 % | 14,6 % | −11,65 % |

**Zéro gros gain dans les deux quintiles les plus « sûrs », sur 479 tickets, période indépendante,
modèle indépendant.** Le modèle mesure la VIE : confirmé deux fois.

**Ce qui NE tient pas, et que je retire.** J'ai d'abord conclu que « la bande perd sur l'historique »
(−6,27 % contre −5,29 % sans filtre). **Cette comparaison est confondue** : le modèle déployé a été
entraîné SUR ces lignes, et un modèle est systématiquement plus tranché sur ce qu'il a vu — sa
médiane de score y est de 0,085 contre 0,227 en vivant, ce qui déplace complètement les bornes. Le
modèle réentraîné, lui, a une autre calibration encore. **Il n'existe aucun moyen propre de juger la
bande sur l'historique** ; le seul test valable est celui gelé le 17/09 à 18h30. De plus la période
12→15/09 était négative pour tout (−5,29 % sans filtre) : elle ne pouvait ni valider ni réfuter.

### 3.105 — La durée de tenue : ce qui sauve une tenue longue, c'est la prise de gain, 2026-09-17 nuit

On décide à 45 s et on tient 240 s sans l'avoir jamais comparé à autre chose. La table historique a
**dix âges de décision** (20 à 600 s) et six horizons : de quoi poser la question. Protocole imposé
par les tranches du fichier — apprentissage sur R, **choix sur T**, vérification sur F une seule
fois. Sur les 50 cases, tout est négatif (la période 12→15/09 l'était pour tout), mais **un motif
énorme survit aux deux tranches** : sur F, H=30 s donne −2,8 à −5,3 %, H=240 s donne −6,1 à −17,3 %,
**H=480 s donne −23,5 à −29,7 %**. Vingt points d'écart, pour un bruit de 5.

**Confirmé sur le vivant, et avec un optimum.** Tenue sèche, sans prise de gain, sur les tickets du
collecteur à 1 s :

| horizon | dans la bande | hors bande |
|---|---|---|
| 167 s | −1,99 % | −16,83 % |
| **287 s** | **+0,70 %** | −23,02 % |
| 600 s | −18,02 % | −46,70 % |
| 900 s | −36,52 % | −63,05 % |
| 1800 s | **−60,25 %** | −69,29 % |

**J'ai failli en tirer une alerte fausse.** Le carnet de production `solana` tient **1 800 s** : à
lire ce tableau, il serait catastrophique. Mais il a une prise de gain ×1,5 ET un stop à 0,7, donc
il ne tient jamais 1 800 s en réalité. En rejouant sa VRAIE règle sur 300 tickets :

| échéance | tenue seule | règle du carnet (TP ×1,5 + stop 0,7) |
|---|---|---|
| 287 s | +0,70 % | −3,21 % |
| 900 s | −36,52 % | −1,97 % |
| 1 800 s | **−60,25 %** | **−1,83 %** |

**Le critère pré-enregistré du 09/09, resté dans `config/intel.yaml` sans jamais être évalué, est
TENU** : il exigeait « mieux que −0,157 par euro sinon retour à 900 s » ; on mesure **−0,0183**.
`max_hold_seconds: 1800` reste justifié. Leçon de méthode : ne jamais extrapoler d'une tenue sèche
vers une règle qui a des sorties conditionnelles — il faut rejouer la règle entière.

**Le mécanisme, décomposé** (tickets de la bande, comparaison appariée, chaque ticket son témoin) :

| à 1 800 s | rendement | ce que ça ajoute |
|---|---|---|
| tenue sèche | −60,25 % | — |
| + stop 0,7 | −39,73 % | **+20 pts** |
| + stop **et** prise de gain ×1,5 | +1,37 % | **+41 pts** |

**C'est la prise de gain qui sauve une tenue longue, pas le stop.** Ces jetons montent puis
redescendent : sans plafond on rend tout. Et tenue courte (287 s, +0,70 %) ≈ tenue longue avec
TP+stop (+1,37 %) — les deux chemins arrivent au même endroit.

**Pour la bande précisément, aucune sortie n'est départageable** : les différences appariées ont
toutes leur intervalle contenant zéro et des moitiés de signes opposés (TP ×1,5 + stop à 1 800 s :
+0,67 pt, [−7,89 ; +9,05], +11,1 / −9,8). Seule exception nette, le stop **seul** à long horizon,
franchement négatif et cohérent sur les deux moitiés (−24,9 pts à 900 s, −40,4 pts à 1 800 s) — mais
c'est l'effet de l'horizon, pas du stop. À horizon égal (287 s) le stop **coûte** 3 points à la
bande (−3,2 / −2,8 sur les deux moitiés) : logique, la bande sélectionne des jetons qui bougent, et
un stop y coupe des positions qui seraient remontées.

### 3.106 — La bande pourrait-elle tourner ? Oui, et voici ce qui manque exactement, 2026-09-17 nuit

Un rendement par ticket ne devient de l'argent que si le moteur peut PRENDRE ces tickets. Trois
contraintes existent dans `config/intel.yaml` et aucune n'avait été confrontée à la bande.

**La file de 4 positions n'est PAS bloquante — j'ai failli l'annoncer comme telle.** Le calcul de
capital donnait un pic de 7 positions simultanées contre `max_open_positions: 4`, ce qui laissait
craindre des tickets perdus en masse. En rejouant les arrivées dans l'ordre avec une file de taille
limitée — ce que fait réellement le moteur — le pic n'est qu'un pic :

| contrainte | tickets pris | par ticket | à 5 EUR/jour | à 30 EUR/jour |
|---|---|---|---|---|
| aucune | 713 | +3,70 % | +59 € | +353 € |
| **file de 4** | **704 (98,7 %)** | **+3,60 %** | **+57 €** | **+339 €** |
| file de 8 | 713 | +3,70 % | +59 € | +353 € |

Neuf tickets perdus sur 713, soit 4 % du gain. Même à la mise de production de **5 EUR**, la bande
dépasserait l'objectif de 50 EUR/jour — en échantillon, donc sans valeur probante tant que le test
gelé n'a pas parlé.

**Ce qui manque vraiment : le moteur ne sait pas calculer le score.** Vérifié — `modele_vidage.json`
n'est chargé que par `intel/research/papier_combo.py` ; **aucun moteur ne l'utilise**, et le carnet
`solana` décide sur `min_buyers` seul (`solana_watcher.py:487`). Déployer la bande demanderait donc
de porter dans le chemin de décision du moteur : le chargement du modèle, le calcul des 19 variables
à 45 s, le score, puis les bornes.

**Et le piège de ce portage est déjà documenté** : le 17/09 au matin, le filtre de tendance calculé
par le backtest sur sa propre population laissait passer 41 % des pools, contre 28 % pour le moteur
qui lisait `papier_combo.ref` — même jour, même règle, +74 EUR contre −6 EUR. Une réimplémentation
des variables dans le moteur reproduirait exactement ce genre d'écart. **Le portage doit donc appeler
LE MÊME code** (`variables()` extrait dans un module partagé), jamais une seconde version.

Pré-requis, dans l'ordre : (1) le verdict de la bande ; (2) l'extraction de `variables()` en module
partagé, avec un test qui compare moteur et recherche sur les mêmes pools ; (3) le rejeu du P&L en
deux moitiés exigé avant toute mise en production.

### 3.107 — Décider plus tard n'est pas exécuter plus tard : la contradiction n'existait pas, 2026-09-17 nuit

La grille du §3.105 suggérait que décider à 60 s bat 45 s sur les deux tranches, ce qui semblait
contredire une mesure du matin — « entrer à 65 s au lieu de 47 s coûte 3,65 points ». La table
contenant **le même pool à dix âges**, la comparaison peut se faire pool par pool, ce qui élimine
la variabilité entre pools, de loin la plus grosse. Tranche F seulement, horizon 240 s :

| âges comparés | pools | le plus jeune | le plus vieux | différence | erreur-type |
|---|---|---|---|---|---|
| 30 → 45 s | 470 | −7,45 % | −7,77 % | −0,33 pt | ±0,78 |
| **45 → 60 s** | 566 | −7,43 % | −6,22 % | **+1,22 pt** | ±0,79 |
| 45 → 90 s | 570 | −7,40 % | −6,60 % | +0,80 pt | ±1,50 |
| 60 → 90 s | 566 | −6,08 % | −6,12 % | −0,03 pt | ±1,32 |
| **45 → 180 s** | 571 | −7,18 % | −13,20 % | **−6,01 pts** | ±2,41 |

Dans la bande seule (246 pools présents aux deux âges) : 45 → 60 s donne **+2,38 pts ± 1,45**.

**La contradiction n'existait pas, je confondais deux choses opposées.** *Décider* à 60 s, c'est
disposer de 15 secondes d'information en plus avant de choisir — légèrement bon. *Exécuter* à 65 s
une décision prise à 45 s, c'est subir 18 secondes de dérive sans aucune information en échange —
franchement mauvais. Les deux mesures disent la même chose : **l'information aide, le retard nuit.**

La forme d'ensemble est 30 ≈ 45 < 60 ≈ 90 > 120 > 180, soit un optimum plat vers 60-90 s. L'effet
vaudrait +1,2 à +2,4 points par ticket, c'est-à-dire de l'ordre de 190 EUR/jour à 30 EUR la mise —
**mais il ne fait que 1,5 erreur-type, il n'est donc pas établi.** Et il est hors de question de
toucher à l'âge maintenant : le test gelé de la bande décide à 45 s, le déplacer l'annulerait.
À pré-enregistrer après le verdict, pas avant.

### 3.108 — Changer la cible : fermé. Et la raison de fond : le SENS n'est pas dans les données, 2026-09-17 nuit

Le modèle est entraîné à prédire la CHUTE (AUC 0,672) alors qu'il prédit spontanément mieux le GROS
GAIN (0,724, et 0,740 au-delà de +100 %). L'entraîner sur la bonne cible semblait la piste la plus
prometteuse. Elle est fermée, et ce qu'on a trouvé en la fermant vaut plus que la piste.

**Quatre cibles, même recette, protocole R apprend / T choisit / F vérifie** (rendement de la bande
en centiles, A=45) :

| cible d'apprentissage | AUC chute | bande sur T | bande sur F |
|---|---|---|---|
| chute < −50 % *(en service)* | 0,757 | −3,30 % | −10,59 % |
| gros gain > +50 % | 0,747 | −1,31 % | **−14,45 %** |
| gros gain > +100 % | 0,744 | −4,38 % | −11,86 % |
| le gain lui-même (régression) | 0,551 | **−1,17 %** | −8,48 % |

Ce qui brillait sur T ne survit pas sur F : `gros gain > +50 %` était deuxième sur T et devient le
**pire** sur F. Sans le protocole, j'annonçais une amélioration qui empirait les choses de 4 points.

**J'avais d'abord conclu « les deux cibles sont la même fonction ». C'est faux, et je le retire.**
Mesuré : corrélation de rang **0,772** entre les deux scores, et **46 % de recouvrement seulement**
sur leurs 20 % les mieux notés. Ce sont deux fonctions différentes — mais leur différence ne porte
pas sur la direction, donc elle n'achète rien.

**J'ai aussi jugé la nouvelle cible dans l'ANCIENNE forme de stratégie** (la bande du milieu), ce qui
était une faute : un modèle-gain monotone appellerait de prendre le HAUT. Balayage par décile,
choix sur T puis vérification sur F : **aucune forme ne se reproduit**, pour aucune cible — le
modèle en service lui-même passe de +17,7 (D8 sur T) à −8,9 (D8 sur F).

**La raison de fond, et c'est le vrai résultat.** Parmi les jetons qui BOUGENT vraiment
(|brut_240| ≥ 50 %, 5 434 cas), qu'est-ce qui prédit le SENS ?

| population | AUC hors échantillon |
|---|---|
| tous âges, avec `A` | 0,683 |
| tous âges, sans `A` ni `n_lect` | 0,675 |
| **A=45 seul — la condition de service** | **0,509** |

Le 0,68 était un **artefact** : le modèle devinait l'âge de décision, et dans cette table un jeton
jugé à 600 s a déjà fait une partie de son mouvement. L'âge fuit même après retrait de `A` et
`n_lect`, par le **motif des variables manquantes** (`ret_120` n'existe qu'aux âges élevés). À âge
constant, **0,509 : rien**. (Réserve : 256 jetons seulement, ce qui exclut un effet fort, pas un
effet faible.)

**Conséquence sur la stratégie.** On ne peut pas choisir les gagnants : l'information directionnelle
n'est pas dans les 45 premières secondes de prix. La seule stratégie possible est **sélectionner les
jetons qui bougent et encaisser l'asymétrie** — la perte est bornée à −100 %, le gain ne l'est pas.
C'est exactement ce que fait la bande ; ce n'était pas le raisonnement qui l'avait produite, c'est
celui qui la justifie.

### 3.109 — La faute de la journée : j'ai soustrait un coût qui décrit un bot qu'on n'a pas construit, 2026-09-17 nuit

**Tous les chiffres que j'ai donnés le 17/09 utilisaient `cout_reduit` (1,57 pt médian) alors que le
coût total réel, mesuré de bout en bout, vaut 2,62 pts.** L'écart, environ un point par ticket,
retourne le signe de trois lignes sur quatre.

Ce n'est pas une erreur de recopie. `papier_combo.py` documente lui-même les deux lignes :

```
couts   reduit = 1,25 % + impact/2   (depot recupere, priorite baissee)
        reel actuel = 1,7 % + impact + 0,5 %   (depot)
```

Le coût réduit est donc **le coût qu'on aurait SI on faisait deux optimisations qui ne sont pas
faites** — récupérer le dépôt de compte-jeton et baisser les frais de priorité — plus une hypothèse
de diviser l'impact par deux. Mes tableaux décrivaient un bot qui n'existe pas, et je les ai
présentés comme « iso-prod » toute la journée, en répondant « oui, c'est vérifié » chaque fois que
Mido posait la question.

**Le pire : c'est la DEUXIÈME fois en deux jours que je me trompe sur le même chiffre, dans l'autre
sens.** Le 16/09 j'avais construit un coût de 5,04 % en ajoutant 2,4 pts par-dessus le 2,62 déjà
end-to-end (double comptage, « −239 € » retiré). Cause identique : **je ne pars jamais de la mesure
vérifiée, je recalcule à partir de ce que je trouve sous la main.**

**La mesure, re-vérifiée ce soir en relançant `calibration_corrigee.py`** — 236 tickets `mode='live'`,
gain réel du portefeuille contre prix simulé corrigé : **moyenne −0,0262, médiane −0,0241, quartiles
−0,0312 et −0,0126**. C'est la seule référence.

**La table corrigée (mise 30 €, coût 2,62 pts, collecteurs uniquement) :** douze lignes, **douze
totaux négatifs**. `RISQUE seul` passe de +174 € à **−139 €** ; les « moins pires » (G+D 45 s −6 €,
G+D les trois −21 €, D+F −37 €) ne le sont que parce qu'elles prennent 24 à 34 tickets — c'est de
l'abstention, pas de la performance. Les lignes du collecteur G+D étaient déjà correctes : ce
collecteur utilise 2,62 depuis sa création. **Seules les cinq lignes de `papier_combo` étaient
fausses, toutes dans le même sens.**

**RÈGLE, à appliquer sans exception : le coût de référence est 2,62 pts.** Tout chiffre publié dit
quel coût il contient. Ne jamais reprendre une variante « optimisée » sans dire, dans la même
phrase, ce qu'elle suppose et si c'est implémenté.

**Ce que la correction révèle, et qui est la vraie information de la journée.** En rendement BRUT,
avant tout coût : bande **+4,73 %**, RISQUE seul **+2,15 %**, régime+risque +1,65 %, témoin +0,84 %.
Le coût réel étant de 2,62 pts, **seule la bande a un brut qui le dépasse** — et `RISQUE seul` rate
de 0,33 point seulement. La question décisive de ce projet n'est donc pas « quelle règle » mais
**« de combien peut-on baisser le coût »**. Deux leviers mesurés : récupérer le dépôt de
compte-jeton vaut **0,39 pt à 50 €** (il est récupérable en fermant le compte, ce n'est pas
implémenté) ; et surtout la **taille du ticket**, parce que les frais fixes (priorité 0,048 € par
ordre, soit 0,096 € l'aller-retour, plus le dépôt) ne dépendent pas de la mise :

| mise | 5 € | 15 € | 30 € | 50 € | 75 € | 100 € |
|---|---|---|---|---|---|---|
| coût moyen (bande) | **6,91 pts** | — | 2,78 | 2,86 | 3,24 | 3,72 |
| bande, EUR/jour | −37 | +57 | +172 | +274 | **+320** | +276 |
| RISQUE seul, EUR/jour | −107 | −76 | −55 | −76 | −179 | −368 |

**À la mise de production (5 €), le coût est de 6,91 pts et AUCUNE règle ne peut gagner**, avant même
de parler de stratégie. Monter la mise ne sauve que ce qui est déjà positif : pour une ligne
négative, une mise plus grosse multiplie la perte. Réserve : la colonne 75 € repose sur le modèle
d'impact, pas sur une mesure.

### 3.110 — La nuit du 17 au 18/09 : un seul modèle est un TIRAGE, et le premier expert décorrélé

**LA MESURE QUI EXPLIQUE TOUTE LA NUIT.** 96 entraînements **identiques** — mêmes données, même
recette, seule la graine aléatoire change — appliqués aux mêmes 1 568 tickets vivants :

| | étendue | écart-type | tirages perdants |
|---|---|---|---|
| un seul LightGBM | **−252 à +348 €** | **117 €** | **30 %** |
| ensemble de 12 | +38 à +190 € | 54 € | 0 sur 8 |
| forêt aléatoire | −63 à +92 € | 54 € | — |

LightGBM tire au sort 80 % des lignes et 70 % des variables à chaque arbre. **Le modèle en service
est donc un tirage, et il se trouve être au-dessus de la moyenne** (+140 € contre +66 €). Ce n'est
pas une qualité de la stratégie.

Cela **explique les sept pistes mortes de la nuit** : déplacer le seuil, filtrer sur la taille du
pool, découper les ordres, réentraîner sur des données fraîches, changer la cible, construire des
variables (`qualite_30`, `souffle`, `taille_vol`…), corriger `cout` et l'heure. Toutes se jouaient
entre 20 et 160 €, c'est-à-dire **sous le bruit du tirage**, que je ne mesurais pas. Je comparais
des coups de dés en croyant comparer des méthodes.

**DEUX CORRECTIONS QUE MIDO A IMPOSÉES, ET QUI ÉTAIENT JUSTES.**
- Le **découpage des ordres ne réduit rien** : sur un AMM à produit constant, vendre en n morceaux
  donne le même résultat **à la 8e décimale** (vérifié numériquement), parce que le second morceau
  repart du prix où le premier s'est arrêté. Il ne gagne que si le pool se reconstitue entre les
  tranches — mesuré sur 12 pools lus à 0,35 s pendant 210 s : après une baisse de 0,6-1,2 % (notre
  ordre à 60 €), le rebond médian est de **−0,143 %** et le prix remonte 50 % du temps. Aucune
  reconstitution. Et chaque tranche paie 0,16 % de frais de priorité en plus.
- **Ma « fuite » d'entrée n'en était pas une.** J'avais durci la règle (première lecture ≥ 47 s au
  lieu de la plus proche), ce qui dégradait tout de 0,47 pt. Mido a objecté que la décision ne
  dépend pas du prix : vrai. La lecture retenue est avant 47 s dans 51 % des cas et après dans 49 %
  — c'est du bruit symétrique, pas un biais. Correction **retirée**.

**LE RÉSULTAT POSITIF DE LA NUIT : un expert qui se trompe DIFFÉREMMENT.** L'agrégation d'experts
ne vaut que si les experts divergent. Notre ensemble et notre forêt sont corrélés à **0,939** et se
recouvrent à **91 %** : rien à échanger. Un expert entraîné **uniquement** sur la concentration des
détenteurs, sans voir un seul prix, atteint **AUC 0,682** avec une corrélation au prix de **0,682**.

Mesure faite **avant** d'écrire la moindre ligne de collecte, pour savoir quoi collecter :

| expert | n var | AUC | corrélation au prix |
|---|---|---|---|
| PRIX (référence) | 19 | 0,747 | — |
| les 11 variables non-prix | 11 | 0,678 | 0,649 |
| les 5 « utiles » | 5 | 0,699 | 0,680 |
| **`sac1` + `n_sacs5` seules** | **2** | **0,682** | **0,682** |

Les variables **gratuites** (Telegram, Twitter, site, description, régime de marché) ne valent
**rien** : 0,563 à elles seules, et les retirer améliore le reste. Le créateur n'est **pas**
récupérable à bas coût — ces jetons sont en Token-2022 avec métadonnées intégrées et
`updateAuthority` à `null`. Le financeur demande la même pagination lourde. Ni l'un ni l'autre ne
justifie son coût quand deux parts de détention donnent déjà 0,682.

Et exiger les **deux** experts améliore à chaque étape : sans filtre −9,95 %, prix seul −8,66 %,
détenteurs seuls −7,56 %, **les deux d'accord −6,43 %**.

**PIÈGE DE MESURE, À NE JAMAIS REFAIRE.** J'ai chronométré `getSignaturesForAddress` avec
`limit: 1` (57 ms) puis l'ai implémenté avec `limit: 1000`. **Ce n'est pas le même appel** : il
bloque des minutes sur un jeton actif ET ne remonte même pas jusqu'à la création. Le collecteur est
resté bloqué **sans lever d'erreur** et n'a rien écrit pendant deux minutes. *Toujours chronométrer
l'appel EXACT qu'on va écrire.* Le coût réel retenu : un `getTokenLargestAccounts` + un
`getTokenSupply`, **82 ms en médiane, 186 au pire**, sur une fenêtre de 45 s.

**QUATRE TESTS GELÉS AJOUTÉS CETTE NUIT**, tous notés en parallèle, aucun collecteur en marche
modifié : bande + pause (23h30), ensemble de 12 et forêt aléatoire (01h30), expert détenteurs
(03h00). Le modèle en service continue de décider seul.

**Sur les jetons vivants, la concentration est extrême** : le plus gros détenteur tient **58 %** en
médiane, les cinq premiers **92 %**.

### 3.111 — Pourquoi le régime ne nous sauve pas, et pourquoi la pause non plus, 2026-09-18 matin

La nuit du 18/09 a été franchement mauvaise : rendement **brut**, avant tout coût, **−3,50 %** par
ticket sur 269 tickets, contre +4,33 % le 15/09, +0,41 % le 16 et +0,13 % le 17. Heure par heure :
02h +11,4 %, puis 05h **−9,2 %**, 06h **−10,9 %**, 07h **−8,1 %**. Question posée : s'il y a un
régime aussi net, pourquoi ni le régime ni la pause ne nous en sortent ?

**LE RÉGIME EST RÉEL APRÈS COUP, ILLISIBLE AVANT.** Piège de mesure central : un ticket décidé à *t*
ne rend son résultat qu'à *t*+242 s. L'état du marché connu **à l'instant de la décision** est donc
la moyenne des seuls tickets **déjà clôturés** dans les 30 min précédentes — pas de ceux encore
ouverts, qui seraient de la lecture d'avenir. Sur les 1 436 tickets où cet état est lisible :

| état des 30 min (connu AVANT) | n | état moyen | ticket suivant |
|---|---|---|---|
| Q1 | 287 | −22,18 % | **+0,89 %** |
| Q2 | 287 | −10,31 % | −7,26 % |
| Q3 | 287 | −0,63 % | −2,37 % |
| Q4 | 287 | +7,44 % | −8,94 % |
| Q5 | 288 | +24,41 % | **−0,97 %** |

Non monotone, et dans le mauvais sens aux extrêmes. Corrélation de rang état → ticket suivant :
**+0,014**, quand deux écarts-types du hasard valent ±0,053. **Il n'y a pas de persistance du
marché à 30 minutes.** Chaque jeton est sa propre loterie. Ceci confirme indépendamment l'échec déjà
enregistré de *régime + risque* : ce n'était pas la formulation du régime qui était mauvaise, c'est
qu'il n'y a rien à lire.

**LA PAUSE, VERSION « TOUT LE MARCHÉ » : UN INTERRUPTEUR, PAS UN FILTRE.** Si les déclencheurs
viennent de l'ensemble des tickets, la nuit a passé **100 % du temps en pause** (454 min sur 454).
Arithmétique simple : 70 clôtures sous −30 % en 452 min, soit **une chute toutes les 6 min**, pour
une pause qui dure 30 min. Elle ne se relève jamais. Le code applique la pause au flux de la
stratégie, pas au marché, ce qui l'évite — mais la marge est mince : la BANDE produit une chute
toutes les 9 min, RISQUE seul une toutes les 15 min.

**LA PAUSE, VERSION DU CODE : SPECTACULAIRE, ET INDISTINGUABLE DU HASARD.** Depuis le gel de la
bande, au coût mesuré de 2,62 pts et à 25 EUR :

| | sans pause | avec pause |
|---|---|---|
| RISQUE seul | n=320 · −1,07 % · −86 EUR | n=**42** · +8,24 % · **+87 EUR** |
| BANDE | n=215 · −8,31 % · −447 EUR | n=**14** · +17,83 % · **+62 EUR** |

Tentant, et faux. La pause ne garde que 13 % (resp. 7 %) des tickets, donc sa variance est énorme.
Deux contrôles la démolissent :

- **D'où vient l'argent.** Les trois meilleurs tickets gardés font +229 %, +154 %, +36 %. **Sans
  eux, RISQUE + pause vaut −18 EUR sur 39 tickets.** Le ticket à +229 % porte à lui seul les *deux*
  lignes du tableau : c'est le même.
- **Le hasard fait pareil.** 10 000 sélections aléatoires de la *même taille* dans le *même* vivier :
  médiane −13 EUR, intervalle 5 %–95 % de −117 à +95 EUR. **662 tirages sur 10 000 font aussi bien
  ou mieux → p = 0,066.** Pour la bande, p = 0,070.

**CE QU'ON EN RETIENT.** p = 0,066 n'est pas zéro : ce n'est pas réfuté, c'est *non démontré*. Et
c'est précisément la situation pour laquelle la pause a été **gelée le 17/09 à 23h30** avec son
critère écrit d'avance. On attend les 300 tickets ; on ne la promeut pas sur un ticket à +229 %.

**LA BANDE EST MORTE.** 214 tickets sur 300, **−8,38 % par ticket**. Pour atteindre son critère gelé
de +2 % il lui faudrait faire +27,8 % par ticket sur les 86 restants. Premier verdict
pré-enregistré du projet, et c'est un **échec** — à écrire comme tel.

**MÉTHODE À GARDER.** Toute règle qui *réduit fortement le nombre de tickets* doit être comparée à
une sélection aléatoire de la même taille avant qu'on y croie. Une moyenne sur 14 ou 42 tickets à
traîne épaisse ne veut rien dire toute seule.

### 3.112 — Les trois leviers structurels sont fermés : caution, taille de pool, durée, 2026-09-18

Trois questions posées dans la foulée, toutes les trois tranchées **contre** l'espoir. À garder
ensemble parce qu'elles épuisent la dimension « exécution » du problème.

**1. LA CAUTION N'EXISTE PAS.** J'avais annoncé 0,66 pt récupérable en fermant les comptes-jetons,
ramenant le coût de 2,62 à 1,96 — soit exactement le seuil qui rendait `RISQUE seul` (brut +2,15 %)
gagnante. Lecture de la chaîne avant d'activer le module : **0 compte vide, 1 compte au total,
après 244 tickets réels**. Un compte abandonné persiste indéfiniment ; 244 seraient encore là. La
route d'échange ferme l'ATA elle-même et le remboursement entre dans le `sol_delta` de la vente —
or c'est précisément ce que `telegram_rapide._compter_sur_la_chaine` additionne pour produire
`gain_eur`, la base des 2,62. **La caution est donc déjà comptée, à zéro, dans la mesure.**
`intel/engines/recuperation.py` ne récupérerait rien ; le commentaire de `config/intel.yaml` qui
affirmait le contraire a été corrigé.

**2. LA TAILLE DU POOL NE RÉDUIT PAS LE COÛT DE FAÇON DÉMONTRABLE.** Le découpage des 237 tickets
réels par coffre semblait pourtant clair — Q1 (74 SOL) **2,91 pts**, Q2 (93 SOL) **2,98**, Q3 (470)
2,57, Q4 (677) **2,04** — et c'est de là que venait le « 2,9 » que Mido avait en tête. Ajustement
`coût = a + b·mise/(coffre+17,58)` sur ces mêmes tickets :

| | valeur | IC95 |
|---|---|---|
| part fixe `a` | **1,72 pts** | 0,73 .. 2,68 |
| pente `b` (impact) | 0,0398 | **−0,0029 .. +0,0906** |

**La pente contient zéro.** Le dégradé tient dans le bruit de 59 tickets par case. Et sur les
tickets papier, filtrer sur la taille du pool ne produit aucun net significatif (IC de `RISQUE
seul` : petits pools +1,04 % [−6,24..+8,43], gros pools −0,94 % [−2,94..+0,97]). La part fixe de
1,72 pt est **proportionnelle à la mise** (frais de pool + spread), donc grossir la mise ne la
dilue pas — contrairement aux frais de priorité (~0,33 pt à 30 €), qui eux ne peuvent pas baisser
sans faire échouer des ordres (§3.40, quatre sur six).

**3. LA DURÉE DE DÉTENTION : AUCUN HORIZON N'EST POSITIF.** Le péage est identique quelle que soit
la durée — un seul aller-retour — donc si le brut montait avec le temps, le net monterait. Testé en
apparié (mêmes 1 836 tickets, même entrée à 47 s, seule la sortie change ; séries tronquées comptées
au dernier prix connu, 2 à 10 selon l'horizon, jamais jetées) :

| sortie | brut (RISQUE seul) | net après 2,62 | écart au 240 s (IC95) |
|---|---|---|---|
| 30 s | −0,31 % | −2,93 % | −2,15 [−4,72..+0,37] |
| 90 s | −0,73 % | −3,35 % | −2,56 [−4,73..−0,33] |
| 180 s | **+2,02 %** | **−0,60 %** | +0,19 [−1,26..+1,72] |
| **240 s (actuel)** | +1,84 % | −0,78 % | — |
| 360 s | −6,99 % | −9,61 % | **−8,79** [−11,47..−6,00] |
| 600 s | −23,32 % | −25,94 % | −25,12 [−28,62..−21,65] |
| 840 s | −29,81 % | −32,43 % | −31,61 [−35,67..−27,47] |

Tenir plus longtemps est **catastrophique et monotone** : ~9 points perdus par tranche de deux
minutes, confirmé sur les deux moitiés chronologiques. Tenir moins longtemps ne rapporte rien :
180 s est nominalement le meilleur mais son avantage sur 240 s est indistinguable de zéro. **Les
242 s en service sont déjà à l'optimum, et l'optimum est négatif.**

**CE QUE CES TROIS RÉSULTATS DISENT ENSEMBLE.** Le coût d'exécution de 2,62 pts n'est pas une
inefficacité qu'on peut corriger : c'est un péage, majoritairement proportionnel, payé au pool. Il
n'existe aucun réglage d'exécution — caution, choix du pool, mise, durée — qui le réduise de façon
démontrée. **La seule variable qui reste est le rendement brut**, qui doit dépasser 2,62 % par
ticket hors échantillon. Aucune règle n'y parvient à ce jour ; la seule qui y parvenait en
échantillon (la bande, +4,73 % brut) vient d'échouer en conditions réelles (§3.111).

### 3.113 — La perte tient dans 10 tickets, et ils ne sont pas arrêtables, 2026-09-18

Mido, de mémoire de sa mise en production : « on gagne souvent de petites sommes, on perd rarement
de grosses ». **C'est exact, et c'est la structure du problème.** Sur ses 244 tickets réels
(−544 EUR au total) :

| | n | moyenne | total |
|---|---|---|---|
| gagnants | **153 (63 %)** | **+8,02 EUR** | +1 228 EUR |
| perdants | 91 (37 %) | **−19,47 EUR** | −1 772 EUR |

Ticket médian **+2,4 %** : le ticket typique gagne. Le gain moyen vaut 0,41 fois la perte moyenne.
Et la perte est ultra-concentrée : **les 10 pires tickets font −561 EUR, soit 103 % de la perte
totale.** Sans eux, le livre était positif. (Symétriquement les 10 meilleurs font +531 EUR : la
distribution est à queues épaisses des deux côtés, mais la queue gauche gagne.)

**UN STOP NE PEUT PAS LES COUPER — deux raisons indépendantes, mesurées.**

*(a) Le prix saute.* Les lectures tombent toutes les **10 s** (p90 : 11 s). Parmi les 213 tickets
papier qui finissent sous −70 %, le niveau **déjà atteint à la première lecture sous −30 %** est de
**−69 % en médiane** ; **49 % étaient déjà sous −70 %** et 20 % sous −80 %. Le stop n'a rien à
vendre : entre deux lectures le prix a traversé toute la zone.

*(b) Les creux remontent.* Sur 668 jetons qui touchent −30 %, **13 % finissent au-dessus de −10 %**.
Couper à −30 % sacrifie ces reprises — cohérent avec le résultat central du projet : *le modèle
mesure la VIE, pas le danger*, et un jeton capable de chuter est un jeton capable de monter.

Résultat, simulé avec réalisme d'exécution (vente à la lecture **suivant** le franchissement, jamais
au prix du seuil — erreur du 16/09) sur 1 295 tickets `RISQUE seul` :

| règle | net | écart au sans-stop (IC95) |
|---|---|---|
| sans stop | −0,63 % | — |
| stop −15 % | −1,60 % | −0,98 [−2,36..+0,41] |
| stop −30 % | −1,00 % | −0,38 [−1,21..+0,45] |
| stop −50 % | −0,54 % | +0,08 [−0,34..+0,52] |

**Aucun stop n'améliore quoi que ce soit**, et les plus serrés dégradent nettement — confirmé sur
les deux moitiés chronologiques (stop −20 % : −0,04 % puis **−3,05 %**).

**CE QUE ÇA IMPLIQUE.** La perte n'arrive pas progressivement : elle arrive **en un saut**, entre
deux lectures espacées de 10 s. C'est donc d'abord un problème d'**ENTRÉE** : il faut ne pas être
dans ces jetons-là. C'est précisément ce que vise l'expert détenteurs gelé le 18/09 (§3.110) — qui
regarde *qui détient le jeton* et non son prix. Son verdict tombe à 1 000 tickets.

**RÉSERVE MAJEURE, soulevée par Mido et vérifiée — cette conclusion N'EST PAS établie à la
résolution du moteur.** J'ai écrit « le prix saute entre deux lectures de 10 s » en décrivant le
collecteur d'ARCHIVE (`solana_prix_chaine` : médiane 10,0 s, p90 11 s, **tous les jours depuis le
09/09**, dans les deux bases). Mais le moteur ne regarde pas à 10 s : `veille_rapide` lit les
comptes de réserve du pool **toutes les 1 s** depuis le 17/09 (2 s avant), par notre propre RPC,
justement pour réveiller le carnet quand un seuil est franchi.

**Et ces lectures à 1 s ne sont enregistrées nulle part** — `veille_rapide` ne fait qu'un
`UPDATE positions SET peak_price`. Il n'existe donc AUCUN historique de prix sous 10 s : ni
`solana_suivi` (DexScreener), ni `trades`/`swap_events` (EVM, arrêtés le 17/09 à 14 h), ni
`pump_prix`. Le test du stop ci-dessus est donc nécessairement fait à 10 s.

Or §3.95 a déjà montré que la cadence vaut très cher du côté de la PRISE DE GAIN : passer de 20 s à
2 s vaut **+1,14 pt par ticket [+0,27 ; +2,04]**, et le tableau des cadences y était monotone. Rien
ne permet de supposer que le côté STOP y serait insensible. **Je retire donc la force de la
conclusion « aucun stop ne peut marcher » : elle est démontrée à 10 s, pas à 1 s.**

**CE QU'IL FAUT POUR TRANCHER.** Enregistrer un flux de prix à 1 s sur la fenêtre 47–287 s. Coût
mesuré : **3 pools simultanés en médiane dans cette fenêtre, 13 au pire** — donc ~3 lectures RPC par
seconde, quand le collecteur actuel en fait déjà ~1/s. C'est un processus séparé avec sa propre
base, sur le modèle de `social_collecte`, qui ne touche aucun collecteur en marche.

### 3.114 — Le moteur voit à 1 s, je mesurais à 10 s : le collecteur rapide, 2026-09-18

**Mido : « ce marché est un marché de vitesse, je te l'ai dit 343 fois, et tu dis toujours 10 s ».**
Il a raison, et le problème est plus grave qu'une erreur de chiffre.

**LE MOTEUR EST RAPIDE. C'ÉTAIT LA MESURE QUI ÉTAIT LENTE.** En production, `veille_rapide` lit les
réserves du pool **toutes les 1 s** (2 s avant le 17/09) pour déclencher `take_profit_multiple: 1.5`
et `stop_loss_multiple: 0.7`. Mais **il ne garde rien** : un `UPDATE positions SET peak_price`, et
la lecture est perdue. Le seul historique de prix qui existe est `solana_prix_chaine`, à **10,0 s de
médiane, p90 11 s, tous les jours depuis le 09/09**, dans les deux bases — vérifié. Aucune autre
source ne descend en dessous (`solana_suivi` = DexScreener ; `trades`/`swap_events` = EVM, arrêtés
le 17/09 à 14 h ; `pump_prix` = la courbe, pas le pool).

**CONSÉQUENCE SUR TOUT CE QUI A ÉTÉ MESURÉ ICI.** `papier_combo`, la bande, `RISQUE seul`,
l'ensemble, la forêt, l'expert détenteurs, le test de durée et le test de stop de §3.113 décrivent
**un bot à sortie fixe (287 s) observant à 10 s**. Le moteur réel sort sur **seuils**, à 1 s. Ce ne
sont pas les mêmes machines, et §3.95 avait déjà chiffré l'écart sur la prise de gain : même règle,
mêmes 3 245 pools, seule la cadence d'observation change — transactions +5,23 %, 2 s +5,48 %,
5 s +4,12 %, **10 s +1,69 %**. Un facteur 3.

**`intel/research/prix_rapide.py`, écrit et lancé le 18/09.** Processus séparé, base
`/app/db/prix_rapide.sqlite`, lit `intel.sqlite` en lecture seule, n'écrit que chez lui. Fenêtre
35–310 s (la position tenue), cadence 1 s tenue en dur (on dort le reste du tour, jamais `PAS` de
plus, sinon la cadence dérive avec le RPC). Les réserves se lisent en **un seul lot**
(`getMultipleAccounts`, ≤ 100 comptes, `commitment: processed`) : **un appel par seconde quel que
soit le nombre de pools**. Coût mesuré avant écriture : 3 pools simultanés en médiane, 13 au pire.
Mesuré après : **0,10 s par tour, cadence réelle 1,00 s médiane / 1,02 p90**. 8 tests
(`tests/intel_tests/test_prix_rapide.py`).

**VALIDATION DU DÉCODAGE.** Comparé au collecteur d'archive sur les mêmes pools : la réserve
virtuelle est **identique** (17,585 = 17,585 ; 0 = 0) et un pool dormant donne exactement le même
coffre (0,364 = 0,364). L'écart de +2,2 % sur les pools actifs n'est donc pas un bug de décodage —
c'est le prix qui a bougé entre les deux horodatages. *Ne jamais conclure à une découverte sur un
écart avant d'avoir comparé les données BRUTES, pas la grandeur dérivée.*

**PREMIER RÉSULTAT ANNONCÉ, PUIS CORRIGÉ DANS L'HEURE — à garder comme exemple.** J'ai d'abord
annoncé à Mido **2,25 %/s de variation médiane** sur 245 intervalles issus de **2 pools**, dont un
très frais et très agité. Vingt minutes plus tard, sur 987 intervalles et 6 pools, la médiane est
de **0,146 %/s** — quatorze fois moins. *Une médiane sur deux pools n'est pas une médiane ; c'est
un pool.* Le chiffre publié était un artefact de petit échantillon, exactement ce que Mido
redoutait (« c'est pas un truc que tu vas me dire dans deux jours que c'était trop beau ? »).

**LA VRAIE STRUCTURE : DES MARCHES D'ESCALIER, PAS UNE DIFFUSION.** Sur 987 intervalles d'une
seconde :

| | valeur |
|---|---|
| médiane | **0,146 %** |
| moyenne | 2,566 % |
| p90 / p99 / max | 6,97 % / 21,26 % / **160,9 %** |

**35 % des secondes le prix ne bouge pas du tout.** Et le mouvement est massivement concentré :
**1 % des secondes portent 25 % du mouvement, 5 % en portent 47 %, 25 % en portent 90 %.** Contrôle
de cohérence avec le collecteur à 10 s sur les mêmes pools et la même période : observé 1,14 %
contre 0,51 % attendu d'une marche aléatoire (rapport 2,24) — le mouvement est bien réel et bien
concentré. Contrôle complémentaire : sur 355 mouvements de prix > 0,5 %, **zéro** avec un coffre
figé — aucun mouvement fantôme, tout changement vient d'un vrai échange.

**CE QUE ÇA IMPLIQUE, ET ÇA COUPE DANS LES DEUX SENS.** *Pour* : 5 % des secondes portent la moitié
du mouvement, et un échantillonnage à 10 s les rate ou les date mal — voir un sommet 9 s plus tôt
vaut quelque chose, c'est ce que §3.95 avait mesuré sur la prise de gain (+1,14 pt de 20 s à 2 s).
*Contre* : le mouvement est un SAUT. On ne peut jamais vendre PENDANT un saut, seulement après.
Un stop ne sortira donc pas à −30 % si un seul échange fait passer le prix de −30 % à −70 % — ce
qui est exactement le mécanisme décrit en §3.113 à 10 s. **L'attente raisonnable est donc que la
vitesse aide sur la PRISE DE GAIN plus que sur le STOP, et qu'elle ne referme pas à elle seule
l'écart de 2,62 pts.** À vérifier sur données, pas à supposer.

**CE QU'ON POURRA TRANCHER DANS QUELQUES JOURS**, et pas avant : le stop à −30 % et la prise de gain
à +50 % que le moteur applique déjà, rejoués à la cadence à laquelle il les voit vraiment.

### 3.115 — T+75 gelé, et le rappel que je ne mesurais pas la production, 2026-09-18 09h05

**Mido, après une journée de conclusions négatives : « je pense que t'es vraiment biaisé à sortir
que des trucs négatifs ».** Le reproche est fondé : sept résultats négatifs dans la journée, et
quand un résultat positif est apparu (l'heure d'entrée), je l'ai présenté comme un « problème » au
lieu d'un levier. Ce qui suit vient de sa question, pas de la mienne.

**MA RECHERCHE N'ENTRE PAS OÙ LA PRODUCTION ENTRE.** `papier_combo` décide à **T+45** ; la
production Telegram entre à **T+60**, choisi le 12/09 sur 183 jetons parce que c'était le point où
les deux moitiés s'accordaient. J'avais d'abord traité l'écart comme un défaut de la production
(« 14 s de retard ») — faux : mesurés contre leur propre cible, les achats réels tombent à **61 s de
médiane**, soit à la seconde près. Le bot fait exactement ce qu'on lui demande. *Avant de qualifier
un écart de retard, lire la cible que le code vise réellement.*

**LA MESURE, SUR LA POPULATION QUE LA PRODUCTION TRADE** (jetons portant un Telegram), appariée,
même détention de 240 s, seul l'âge d'entrée change :

| entrée | T+30 | T+45 | T+47 | **T+60** | **T+75** | T+90 |
|---|---|---|---|---|---|---|
| brut | +1,73 % | +5,62 % | +3,53 % | **+6,01 %** | **+10,97 %** | +9,81 % |
| écart à T+60 | −4,27 | −0,39 | −2,48 | ref | **+4,97** | +3,80 |
| IC95 | [−8,4;−0,1] | [−3,4;+2,4] | [−5,6;+0,4] | — | **[+1,3;+9,2]** | [−1,0;+8,7] |

Deux enseignements. **(1) Ne PAS passer à T+45** : sur cette population il est indiscernable de
T+60 (−0,39, intervalle à cheval sur zéro). Le −0,87 pt que j'avais annoncé venait de ma population
de recherche et ne se transfère pas — troisième fois dans la journée qu'un chiffre est cité hors de
la population où il a été mesuré. **(2) T+75 est le premier résultat positif ET significatif de la
journée**, deux moitiés positives (+15,94 / +6,01).

**TROIS RAISONS DE NE PAS Y CROIRE, écrites avant de voir la suite.** C'est le **meilleur de six**
âges testés (un « significatif » par hasard sur cinq comparaisons : ~1 fois sur 4). L'effet **fond
déjà** quand l'échantillon s'élargit : +4,97 pt sur les 364 jetons disponibles aux six âges, **+3,08
pt** sur les 430 disponibles aux deux âges utiles — signature d'une surestimation par sélection. Et
c'est le profil exact de la bande : +3,90 % en échantillon, morte dehors.

**`intel/research/entree_75.py`, gelé à 07h05 UTC.** Puissance calculée AVANT de figer : écart-type
apparié 36,37 pts par ticket, donc 1 000 tickets détectent un effet de 3,2 pts à 80 % — on
dimensionne sur un effet **plus petit** que l'observé, jamais sur l'observé. Flux mesuré : 57 jetons
Telegram par jour, soit ~18 jours. **Critère, figé** : au premier atteint de 1 000 tickets ou 21
jours, (a) T+75 bat T+60 en apparié, (b) l'écart tient sur les deux moitiés, (c) T+75 est positif
après les 2,62 pts. Les trois, sinon abandon. La production reste à T+60 ; le fichier ne lance rien
et lit tout en lecture seule.

**#2 ET #3 SONT CLOS.** Retard d'entrée : n'existe pas (cible T+60, réalisé 61 s). Latence
d'exécution : appel RPC 41 ms contre un slot Solana de ~270 ms — le plancher est la chaîne, pas le
réseau, il n'y a rien à y gagner. Reste ouvert le **#1**, la cadence d'observation (20 s en
production contre 1 s dans le code d'aujourd'hui), que `prix_rapide` permettra de trancher.

### 3.116 — On ne peut pas éviter les grosses pertes, mais on peut DOUBLER les gros gains, 2026-09-18 10h00

**Question de Mido : « le problème vient des grosses pertes, peut-on les éviter, les prévoir ? »**
La réponse mesurée retourne la question.

**PRÉVOIR LA CATASTROPHE : NON.** Cible `brut_240 <= -70 %` (219 tickets sur 1 872, 11,7 %), toutes
les variables disponibles à 45 s testées, coupe chronologique, barre de bruit tirée d'une variable
aléatoire **continue** (|AUC−0,5| = 0,005). La meilleure, `risque`, tient hors échantillon
(AUC 0,642 puis **0,674**) — mais son AUC sur les **gros gains** vaut **0,730**, *du même côté*.
Idem pour `vol` (0,643 / 0,686) et `q` (0,371 / 0,271). **Écarter le danger écarte le gain**, pour
la énième fois.

**UNE SEULE EXCEPTION, ET ELLE N'EST PAS UN SEUIL TAILLÉ DANS LES DONNÉES.** `depuis_min` =
prix à 45 s rapporté à son minimum depuis la naissance. AUC catastrophe 0,563 contre AUC gros-gain
0,481 : les deux partent de **côtés opposés**, seule variable dans ce cas. Et son premier quintile
est la valeur **exactement zéro** — c'est-à-dire *le prix à 45 s EST son plus bas depuis la
naissance*. Le jeton n'a fait que descendre, il n'a pas rebondi. Pas de seuil à optimiser : la
frontière est naturelle.

**CE QUE ÇA DÉPLACE** (418 tickets contre 1 454 ; tests de PERMUTATION, 5 000 mélanges) :

| | au plus bas | le reste | rapport | p |
|---|---|---|---|---|
| gros gains ≥ +50 % | **19,6 %** | 8,5 % | **×2,32** | **< 0,0001** |
| très gros ≥ +100 % | **8,6 %** | 3,0 % | **×2,87** | **< 0,0001** |
| catastrophes ≤ −70 % | 13,4 % | 11,2 % | ×1,20 | **0,232 — non significatif** |
| chutes ≤ −50 % | 25,8 % | 19,0 % | ×1,36 | 0,0018 |
| gagnants | 46,4 % | 64,9 % | ×0,72 | < 0,0001 |

**On ne supprime pas la queue gauche : on épaissit la queue droite.** On gagne nettement moins
souvent et beaucoup plus gros. C'est la première fois dans ce projet qu'une variable sépare la vie
du danger.

**CE QU'IL NE FAUT PAS SE RACONTER.** Le NET n'est pas démontré : +1,07 % contre −2,45 % pour le
témoin, mais **p = 0,098** contre un tirage au hasard de même taille, deuxième moitié chronologique
négative (−0,69 %), et **négatif en retirant ses trois meilleurs tickets** (−1,07 %). Par jour :
+274 / −77 / +201 / **−287 EUR**. Ce qui est solide, c'est le déplacement des TAUX ; l'argent ne
l'est pas.

**`intel/research/au_plus_bas.py`, gelé à 08h00 UTC.** Choix de conception à retenir : **le critère
porte d'abord sur le taux, pas sur l'argent**, parce que l'écart-type du net est de **74 points par
ticket** — détecter +3,5 pt demanderait **3 503 tickets**, là où un rapport de gros gains de 1,8 se
tranche en **352**. On juge d'abord ce qui est mesurable, et on exige quand même que l'argent suive.
Critère figé, à 800 tickets ou 21 jours (flux : 151/jour) : (a) gros gains ≥ 1,5× les autres,
(b) catastrophes ≤ 1,5× les autres, (c) net positif après 2,62 pts **sur les deux moitiés**.

**LE COÛT N'A PAS ÉTÉ TOUCHÉ, et voici pourquoi.** Mido a demandé si 2,62 avait bougé depuis hier.
Il ne peut pas être remesuré sans trading — c'est une mesure sur des exécutions réelles. Ses
ingrédients, eux, sont observables : coffre médian à 40–60 s **74 SOL pendant les tickets réels,
74 SOL aujourd'hui** (identique ; seule la queue bouge, p25 de 0 à 33), frais de priorité inchangés,
SOL à 92,11 EUR contre ~100 supposés en config. Le modèle d'impact donnerait −0,22 pt, mais c'est un
MODÈLE — celui-là même qui s'était déjà trompé de 0,14 pt face à la calibration — et l'écart vient
entièrement de la queue des petits coffres. **On reste à 2,62.** À la reprise du trading, relancer
`calibration_corrigee.py` sur les premiers tickets avant de publier le moindre chiffre.

### 3.117 — Le régime est mort, et la conjonction qui passe enfin les trois contrôles, 2026-09-18 11h30

**LE RÉGIME NE MARCHE PAS, et il ne marchait déjà pas.** Mido a demandé pourquoi le régime
n'améliore rien un mauvais jour. Réponse mesurée sur 1 850 tickets — il n'améliore rien, **aucun
jour** :

| quintile de `regime` | −0,126 | −0,080 | −0,040 | +0,015 | +0,103 |
|---|---|---|---|---|---|
| net du ticket | −3,87 % | **+1,01 %** | **−8,56 %** | −1,42 % | −0,72 % |

Zigzag, aucune monotonie. Corrélation de rang **+0,026** pour un bruit de ±0,046. Et la règle telle
qu'utilisée (`regime > 0`) : +1,07 pt sur le témoin, **IC95 [−3,23 ; +5,42]** sur 633 tickets —
non distinguable de zéro. Le +4,85 pt affiché le 18/09 portait sur **39 tickets d'une journée** et
s'évapore sur la période. Cohérent avec §3.111 par une voie indépendante : il n'y a pas de
persistance du marché à cette échelle. **`regime` est clos.**

**PIÈGE DE PRÉSENTATION, à ne pas refaire.** J'ai donné le +4,85 pt d'une seule journée dans un
tableau à côté de chiffres de période, sans dire que son n valait 39. Mido : « t'as donné un truc
sur au plus bas + bande alors que je te posais une question sur le régime ». Deux fautes dans le
même échange : un effectif tu, et un changement de sujet non annoncé. *Un chiffre sur moins de 100
tickets ne se met pas dans le même tableau qu'un chiffre de période.*

**BANDE ET RÉGIME N'ONT AUCUN RAPPORT**, ce que la conversation avait confondu : la BANDE filtre le
JETON (probabilité de vidage prédite, 0,20–0,35), le RÉGIME filtre le MARCHÉ. Vérifié : 35 % de la
bande tombe aussi en régime, contre **34 % attendu si indépendants**. Recouvrement exactement au
hasard.

**LA CONJONCTION `AU PLUS BAS + BANDE`, gelée à 09h30 UTC** (`intel/research/bas_bande.py`). Elle
vient de l'objection de Mido — « limiter une perte est un élément indispensable d'une stratégie
gagnante » — et elle assemble les deux moitiés mesurées séparément : la BANDE limite la casse,
`AU PLUS BAS` grossit le gain (§3.116).

| | n | net | moitiés | sans ses 3 meilleurs | p contre le hasard |
|---|---|---|---|---|---|
| témoin | 1 892 | −2,35 % | −1,93 / −2,77 | −2,83 | 0,498 |
| RISQUE seul | 1 320 | −0,58 % | −0,73 / −0,43 | −1,26 | 0,121 |
| AU PLUS BAS | 421 | +0,89 % | +2,61 / −0,82 | −1,25 | 0,129 |
| au plus bas + RISQUE | 205 | +3,42 % | −1,98 / +8,77 | −0,98 | 0,074 |
| **au plus bas + BANDE** | **268** | **+5,10 %** | **+5,98 / +4,22** | **+1,76** | **0,017** |

**C'est la première règle du projet à cocher les trois contrôles à la fois** : deux moitiés
positives, positive sans ses trois meilleurs tickets, et au-delà du hasard. Gros gains : 21,6 %.

**Réserves écrites d'avance** : combinaison choisie APRÈS avoir regardé (le p ne tient pas compte de
la multiplicité) ; elle repose sur la BANDE, qui vient d'échouer seule hors échantillon (−8,38 %,
§3.111) ; 2,8 jours de données, quand la bande affichait +3,90 % sur une fenêtre comparable avant de
mourir. **Critère figé**, à 1 200 tickets (flux 96/jour, ~13 j) ou 21 jours : net positif, positif
sur les deux moitiés, **et** positif sans ses trois meilleurs. Écart-type du net : 79,3 pts, donc
1 200 tickets ne tranchent PAS le net seul — d'où les deux conditions de robustesse, qui elles se
lisent à cet effectif.

### 3.118 — Réduire le coût d'exécution nous appauvrirait, 2026-09-18

**Mido : « il y a des astuces discutées sur internet pour réduire le coût ? le 2,62 me casse la
tête. »** Les conseils courants (glissement serré à 3 %, RPC privé anti-sandwich, limiter les
transactions brûlées) ont été confrontés à nos 237 tickets réels. Deux sont sans objet, et le
troisième **coûte de l'argent**.

**SANDWICH : marginal.** Notre configuration est large (20 % achat, 25 % vente, 40 % en cascade),
donc théoriquement une invitation. Mais l'écart d'exécution est resserré — médiane 2,4 pts,
quartiles 1,3 / 3,1 — alors qu'un sandwich systématique collerait l'écart à nos limites. Tickets
au-delà de 15 pts : **4 %**. On n'est pas sandwiché de façon systématique.

**TRANSACTIONS BRÛLÉES : négligeable.** Sur 188 échecs, **15** seulement ont été envoyées puis
rejetées (≈0,75 EUR au total). Les 173 autres — impact supérieur au plafond, construction refusée,
cotation trop au-dessus du pool — sont écartées **avant** l'envoi et ne coûtent rien.

**GLISSEMENT SERRÉ : LE PIÈGE.** Refuser les mauvaises exécutions fait mécaniquement baisser le coût
affiché, et fait baisser le résultat encore plus :

| seuil de refus | refusés | coût moyen | **total réel** |
|---|---|---|---|
| aucun (situation actuelle) | 0 | **2,62 pts** | **−586 EUR** |
| écart ≥ 20 pts | 7 | 1,76 | −614 |
| écart ≥ 10 pts | 16 | 1,27 | −763 |
| écart ≥ 5 pts | 38 | **0,62** | **−847 EUR** |

**Le coût tombe de 2,62 à 0,62 pt et on perd 261 EUR de plus.** Parce que les tickets mal exécutés
sont les BONS : un grand écart d'exécution se produit quand le prix bouge vite, et un prix qui bouge
vite est un jeton qui monte. Les pires exécutions sont sur les meilleurs jetons.

**CE QU'IL FAUT EN RETENIR.** Les 2,62 pts ne sont pas des frais payés bêtement : c'est en grande
partie **le prix d'entrer dans les jetons qui bougent**. « Réduire le coût » n'est donc pas un
objectif — c'est une métrique qu'on peut améliorer en s'appauvrissant. *Le seul objectif est le net
en euros.* Ajouter ce cas à la liste des métriques qu'il ne faut jamais optimiser seules.

### 3.119 — Retour en RÉEL, et deux artefacts arithmétiques démasqués, 2026-09-18

**LA REPRISE.** Mido : « une proposition — le fait d'être sur papier nous fait rater pas mal
d'informations qu'on peut avoir en prod ; peut-on lancer une strat en prod, quitte à sacrifier un
peu d'argent pour comprendre ? » Puis, après vérifications : « fais-le, le .env contient déjà les
clés et t'as l'autorisation ». Objectif **assumé** : mesurer, pas gagner. Budget accepté : ~150 EUR.
Trading relancé le 18/09 à 11h30 Paris, portefeuille 1,8886 SOL (~174 EUR), mise 20 EUR, plafonds
40 ordres/jour et −150 EUR sur 24 h.

**LE MOTEUR NE SAVAIT JOUER QU'UNE RÈGLE.** `telegram_rapide` achète les jetons à Telegram à T+60
avec stop −30 % et prise de gain +50 %. Rejouée sur la période où elle a vraiment tourné : **−7,73 %
par ticket**, contre **−6,44 %** pour le carnet réel — les deux concordent. Mido : « le bot contient
deux règles et on a une dizaine de strats qui tournent en papier, pourquoi tu veux y aller avec la
règle Telegram ? » D'où `intel/engines/modele_rapide.py`, qui joue une règle de la recherche.
**Vérifié contre `papier_combo` sur 2 297 pools : 0 différence d'éligibilité, 2 297/2 297 variables
identiques, écart maximal sur la probabilité du modèle 0,00e+00, mêmes 311 jetons retenus.** Deux
pièges corrigés : `cout` est une VARIABLE DU MODÈLE et doit utiliser la mise d'entraînement
(0,31 SOL) — sinon 19 % des pools basculaient d'éligibilité ; et il manquait l'exigence d'une
lecture près de 47 s.

**QUATRE DÉFAUTS TROUVÉS EN RELISANT LE CODE APRÈS L'AVOIR ÉCRIT**, dont trois avant le premier
ordre : (a) le plafond bloquait la VENTE, donc atteindre 40 ordres aurait laissé les positions
ouvertes indéfiniment — *un plafond arrête les achats, jamais les ventes* ; (b) `gain_eur` n'était
jamais calculé, donc le plafond de perte ne se serait jamais déclenché et on n'aurait **rien
mesuré** ; (c) le taux SOL/EUR était figé à 92 dans la config au lieu d'être lu sur le marché ;
(d) une vente qui échoue retentait toutes les 5 s en silence — une position invendable est de
l'argent bloqué et doit réveiller l'opérateur.

**L'ERREUR DE RÈGLE.** J'ai branché `AU PLUS BAS + BANDE` sur la foi de +5,30 % par ticket, mesurés
sur TOUTE la période — alors que la BANDE qu'elle contient était morte hors échantillon depuis son
gel du 17/09. Coupé à cette date : **−7,10 %** par ticket, **−16,91 %** sans ses trois meilleurs,
soit pire que le témoin (−3,57 %). Trois tickets réels perdus avant que la question de Mido ne le
révèle. Bascule sur `risque` (−0,11 % hors échantillon sur 408 tickets), et la règle est désormais
**configurable**, une valeur inconnue n'achetant rien.

**PREMIERS FAITS RÉELS.** La machinerie fonctionne de bout en bout : décision 45 s, achat confirmé,
vente à 240 s, P&L lu sur le portefeuille. **Le coût d'exécution n'a pas dérivé** : médiane ~2,8 pts
contre 2,41 de référence. À 11 tickets : −17,75 EUR, **5 gagnants (45 %)**, conforme aux 46 %
attendus.

**DEUX ARTEFACTS ARITHMÉTIQUES, tous deux spectaculaires et tous deux faux.**

*(1) Un tri qui classait par le résultat.* En cherchant un régime de marché, `pa.sort()` sur des
couples `(état du marché, résultat)` a donné un Q3 à **+30,64 %**, robuste au retrait de ses trois
meilleurs, p = 0,000. Python trie par le second élément sur les ex æquo — et **36 % des tickets
avaient un état de marché exactement égal à 0,00 %**. Pour un tiers des données, le tri se faisait
donc sur le résultat lui-même. Ex æquo remélangés : le +30 % disparaît, tout tient entre −5 % et
−1 %. *Trier par une clé qui ne nomme que le prédicteur, et chercher les points de masse avant de
faire confiance à des quantiles.*

*(2) Une soustraction qui comprime.* Le coût d'exécution, calculé `simulé − réel`, montait
monotonement avec le rendement du pool (1,36 → 2,29 → 2,72 → 3,04 pts, ρ = +0,333). J'en ai conclu
devant Mido que le coût mange la queue droite — celle qui porte tout le résultat — et j'ai proposé
de refaire toutes les estimations du projet. Artefact : sur un jeton qui tombe à −72 %, les deux
termes sont écrasés contre −100 % et leur différence est mécaniquement petite, alors que rien ne la
borne sur un jeton qui monte. Recalculé en **multiplicatif**, `1 − (1+réel)/(1+simulé)`, la
corrélation **s'inverse à −0,246** : le coût est pire sur les jetons qui s'effondrent (4,57 % contre
2,42 %), ce qui est exactement ce que vendre dans un pool qui se vide doit produire. **Le coût plat
de 2,62 pts reste valide et aucune reprise n'était nécessaire.**

**RÈGLE À GARDER : tout motif monotone découvert sur une grandeur DÉRIVÉE doit être refait avec une
autre formulation de la même grandeur avant d'être annoncé.**

### 3.120 — Le coût n'est pas un frais, c'est le prix de la volatilité qu'on vient chercher, 2026-09-18

**Mido : « tu dis qu'on paye beaucoup car les pools sont petits — on a essayé de miser sur des pools
plus gros ? »** J'avais répondu ce matin que la taille du pool ne réduisait pas le coût de façon
démontrable (pente contenant zéro, §3.118). **C'était avec la mesure ADDITIVE, démasquée depuis
comme biaisée (§3.119).** Refaite en multiplicatif sur les 237 tickets réels, l'effet est net :

| coffre médian | n | coût multiplicatif |
|---|---|---|
| 74 SOL | 59 | **3,51 %** |
| 93 SOL | 59 | 3,33 % |
| 470 SOL | 59 | 2,83 % |
| 677 SOL | 60 | **2,25 %** |

Monotone, sans exception. **1,26 point d'économie** en passant aux gros pools.

**MAIS LE RENDEMENT BRUT BAISSE D'EXACTEMENT AUTANT.** Sur les tickets papier de `RISQUE seul` :

| | n | rendement brut |
|---|---|---|
| pools < 100 SOL | 629 | **+4,07 %** |
| pools ≥ 300 SOL | 466 | **+2,81 %** |
| écart | | **−1,26 pt** (IC95 [−6,72 ; +3,86]) |

**Le même chiffre au centième près.** Ce n'est pas une coïncidence : un gros pool bouge moins *dans
les deux sens*. Notre ordre le pousse moins — donc le coût tombe — et le marché le pousse moins —
donc le gain tombe. **C'est la même propriété physique qui produit les deux effets.** Le net par
quintile de coffre zigzague (+0,81 / +0,10 / −4,04 / +3,74 / −1,20 %) sans aucune monotonie.

**FORMULATION À RETENIR : le coût d'exécution n'est pas un frais qu'on subit, c'est le prix de la
volatilité qu'on vient chercher.** Choisir des pools où l'exécution coûte moins, c'est choisir des
pools où il ne se passe rien. Cela clôt définitivement la piste « viser des pools plus gros », et
explique pourquoi aucun réglage d'exécution n'a jamais rien donné.

**DÉCOUPER L'ORDRE, RETESTÉ AVEC LA BONNE DONNÉE.** Même question de Mido, reposée. Ma réponse
d'hier tenait sur 12 pools lus à 10 s ; le collecteur `prix_rapide` donne maintenant 223 pools à
1 s. Autocorrélation des variations : 1 s **−0,018**, 2 s +0,006, 5 s **−0,029**, 10 s **+0,036**,
30 s +0,026 — les signes alternent, tout est sous 0,04, c'est du bruit. Simulation directe de la
vente étalée sur les chemins réels : 2 morceaux à 5 s **+0,036 %** [−0,718 ; +0,746], 4 morceaux
**−0,355 %** [−1,615 ; +0,844]. Même en prenant le meilleur chiffre au pied de la lettre, il
faudrait qu'il rapporte 3,17 points pour rembourser le coût — il en rapporte 0,036. Rappel du
mécanisme : dans un AMM à produit constant, le prix final ne dépend que du volume TOTAL, pas du
nombre de morceaux (vérifié à la 8ᵉ décimale) ; le seul gain possible viendrait de ce que
**d'autres** repoussent le prix pendant qu'on attend — et à 4 minutes de vie, il n'y a personne en
face.

**LE COÛT EN EUROS, sur les 25 premiers tickets réels** : le marché a donné +43,84 EUR, l'exécution
a pris **−16,12 EUR**, il reste +27,71 EUR. **L'exécution mange 37 % de ce que le marché donne**,
soit 0,64 EUR par ticket de 20 EUR pour 4 minutes. À 40 tickets/jour, c'est **26 EUR/jour** de coût
pur ; pour dégager 50 EUR/jour net il faudrait que le marché en donne 76.

### 3.121 — Le régime EXISTE : je le cherchais sur la mauvaise grandeur, 2026-09-18 17h00

**Mido, après une journée où j'avais déclaré le régime de marché mort (§3.111, §3.117) :**
*« j'arrive pas à croire qu'on rate pas un truc — là on a un taux de +64 %, peu de positions
perdantes, et on arrive pas à trouver un switch de régime ou un frein quand le marché va
changer ».* Il avait raison, et l'erreur était de conception.

**J'AVAIS TESTÉ 45 FORMULATIONS DU RÉGIME, ET AUCUNE N'ÉTAIT UN TAUX.** Toutes portaient sur le
rendement **moyen** — 5 fenêtres × 3 durées × 6 statistiques, plus trois indicateurs sans délai.
Or la moyenne de ces tickets est écrasée par quelques valeurs à +200 % : elle est structurellement
trop bruitée pour révéler quoi que ce soit. **Le taux de gagnants est borné entre 0 et 1, insensible
aux queues.** C'est là que le signal était.

**LA MESURE**, sur `RISQUE seul` (1 373 tickets), causalité stricte — seuls les tickets déjà
**clôturés** à l'instant de la décision (t+242 s), jamais ceux encore ouverts :

| quartile du taux récent (20 derniers) | 45 % | 55 % | 65 % | 75 % |
|---|---|---|---|---|
| **NET du ticket suivant** | **−3,84 %** | −0,92 % | +1,55 % | **+2,83 %** |

**Monotone sur les quatre quartiles.** Et la fenêtre de 50 tickets, indépendante, donne la même
forme : −3,30 / −0,99 / +1,18 / +3,09 %. **C'est la première fois dans ce projet qu'une variable de
marché ordonne le net sans zigzaguer** — toutes les tentatives précédentes alternaient les signes.

**CE QUI N'EST PAS DÉMONTRÉ.** S'abstenir sous 50 % donne +1,47 % par ticket contre −0,09 % pour le
témoin, mais **p = 0,152** contre un tirage au hasard de même taille, et trois fenêtres ont été
essayées — il faudrait donc nettement mieux que 0,05. La monotonie sur 4 quartiles × 2 fenêtres est
un fait d'une autre nature, structurellement bien plus dur à obtenir par hasard qu'un seul p, mais
elle a été constatée **après** coup.

**`intel/research/frein_taux.py`, gelé à 15h00 UTC.** Règle : ne pas acheter quand le taux de
gagnants des 20 derniers tickets clôturés est ≤ 50 %. **Le seuil n'est pas ajusté** — 50 % est la
frontière naturelle (plus de perdants que de gagnants), et un seuil optimisé sur les données serait
invalide d'avance. Critère figé à 1 500 tickets ou 21 jours : (a) corrélation de rang positive,
(b) Q1 le pire et Q4 le meilleur, (c) le frein bat « tout prendre » sur les mêmes tickets. Les
trois, sinon abandon. **Dimensionné sur la monotonie et non sur l'argent** : détecter +1,5 pt en
euros demanderait ~19 000 tickets, l'ordre des quartiles se lit en 1 700.

**LEÇON DE MÉTHODE, la plus importante de la journée.** Un balayage large sur une grandeur mal
choisie ne remplace pas le choix de la grandeur. 45 formulations d'une moyenne bruitée disent
« rien » avec assurance ; une seule formulation d'un taux borné montre le signal. *Avant de balayer,
demander quelle grandeur a le meilleur rapport signal/bruit pour la question posée* — et se méfier
des moyennes sur des distributions à queues épaisses, qui sont le pire estimateur possible.

### 3.122 — Anatomie des perdants à la seconde : la chute est une FALAISE, 2026-09-18 soir

**Mido : « analyse ces tickets perdants — le profil, le nom, les détenteurs, la vitesse de crash,
analyse tout ça, on trouvera probablement un filtre ».** Fait en deux temps, et le second clôt une
question que j'avais dû laisser ouverte le matin même.

**AVANT L'ACHAT : RIEN.** Balayage de toutes les variables disponibles contre le NET, y compris
celles jamais testées — longueur du nom, longueur du symbole, taille de la description,
concentration des détenteurs. Coupe chronologique, et **barre de bruit tirée d'une variable
aléatoire** : celle-ci obtient **9,15 %** d'écart entre ses quintiles. Aucune vraie variable ne fait
significativement mieux, et aucune ne garde le même quintile gagnant avec un écart au-dessus du
bruit. Ce que Mido avait vu sur ses 31 tickets réels — description à 1 caractère chez les perdants
contre 28,5 chez les gagnants — donne 6,28 puis 8,07 % sur 1 399 tickets, **sous la barre du
hasard**. C'était 10 tickets contre 6.

**PIÈGE REFAIT LE JOUR MÊME OÙ JE L'AI DOCUMENTÉ.** Le premier balayage donnait des écarts de
**126 %** sur `A`, `V`, `twitter`, `site`, monotones et stables sur les deux moitiés. Tous faux :
`A` vaut toujours 45 (**100 % d'ex æquo**), les autres sont binaires (69 à 74 %), et mon `s.sort()`
sur des couples `(valeur, résultat)` triait les ex æquo **par le résultat**. C'est exactement le
§3.119, point 1, écrit six heures plus tôt. *Documenter un piège ne suffit pas : il faut que le code
le rende impossible.* Correction retenue : trier par une clé qui ne nomme que le prédicteur, avec
les ex æquo mélangés au hasard, et **afficher la part d'ex æquo** à côté de chaque variable.

**APRÈS L'ACHAT : LA CHUTE EST UNE FALAISE.** 49 perdants (≤ −30 % à 240 s) suivis à **1 seconde**
par `prix_rapide` — mesure impossible avant ce matin :

| | médiane | p25 | p75 |
|---|---|---|---|
| moitié de la chute atteinte | **56 s** | 18 s | 130 s |
| 90 % de la chute | **86 s** | 22 s | 144 s |
| **pire variation en UNE seconde** | **−55,2 %** | −74,6 % | −35,0 % |

**92 % des perdants ont au moins une seconde à −20 % ou pire**, et 51 % ont perdu la moitié dans
les 60 premières secondes après l'achat.

**LE STOP EST DÉFINITIVEMENT CLOS, et pour deux raisons contradictoires.** *(1) Trop rapide pour
être coupé* : quand la chute est visible, elle est faite — médiane −55 % en une seconde, et notre
ordre de vente arrive un slot Solana plus tard dans un pool déjà vidé. *(2) Couper serait souvent
une erreur* : **43 % des perdants passent PLUS BAS que leur prix de sortie** et remontent de
+8,7 points en médiane. Le stop vendrait au pire moment. Le 18/09 au matin j'avais retiré la force
de cette conclusion faute de données sous 10 s (§3.114) ; les données à 1 s la rétablissent, et plus
fermement qu'avant.

**CE QUE TOUT CECI CONFIRME.** Les perdants meurent tous de la même façon — d'un coup, tôt, sans
prévenir — mais mourir de la même façon ne donne aucun filtre : il faudrait que les survivants
meurent *différemment*, or ils ne meurent pas. **La seule information exploitable existe avant
l'achat, et elle n'y est pas.** C'est pourquoi le seul signal trouvé aujourd'hui porte sur le
MARCHÉ (§3.121, le taux de gagnants récent) et non sur le jeton.

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
5. **Réentraîner le modèle : à quelle fréquence, et faut-il seulement le faire ?** Question posée par
   Mido le 17/09, ouverte volontairement — rien à décider avant le verdict de la bande. Ce qui est
   déjà mesuré ce jour-là, sur les tickets du 15 au 17/09 (le modèle a été entraîné le 15/09 sur le
   09→15/09, donc le 16 et le 17 sont hors échantillon) :
   - **Le pouvoir de discrimination ne se dégrade pas.** AUC sur « chute > 50 % à 240 s » : 0,652 le
     15, **0,678** le 16, **0,670** le 17. Aucune décroissance en deux jours hors échantillon. (Cette
     AUC n'est PAS comparable au 0,74 d'entraînement — l'étiquette diffère ; seule la comparaison
     entre les trois jours est valide, elle utilise la même définition.)
   - **C'est l'ÉCHELLE du score qui bouge, pas sa qualité.** Médiane 0,218 → 0,227 → 0,229 ; la part
     de la population sous le seuil fixe 0,2694 passe de **75,2 % à 68,7 % en deux jours**. Le modèle
     est intact et la règle change toute seule. C'est la dérive dangereuse, parce qu'elle est
     invisible : aucune métrique de modèle ne l'attrape.
   - **Une bande à deux bords y résiste, un seuil à un bord non.** [0,20 ; 0,35[ vaut « centile 40 à
     centile 91 » les trois jours (44,7→92,3 / 39,0→90,8 / 40,5→90,2) et sa part de population tient
     à ±2 points, là où le seuil en perd 6,5. Quand la distribution monte, la bande perd en bas mais
     regagne en haut.
   - **Réserve : trois jours ne font pas une tendance.** Le 75 → 71 → 69 est monotone mais tient sur
     trois points. À re-mesurer avant d'en conclure quoi que ce soit.

   Les trois pistes qui en découlent, dans cet ordre : (a) **exprimer les bornes en centiles du
   jour** plutôt qu'en valeurs absolues — ça supprime la dérive d'échelle sans réentraîner ;
   (b) si on réentraîne un jour, **geler la RECETTE et non les poids** (mêmes variables, même
   fenêtre, même périodicité, bornes en centiles) pour qu'un test en avant valide la procédure,
   réentraînement compris ; (c) ne jamais réentraîner pendant qu'un test gelé tourne — un modèle qui
   change en cours de route ramène à « ça a l'air bien sur les données passées », l'état exact qui a
   coûté 800 EUR.
6. **Sonde de vente avant achat** : le nœud Robinhood **honore les overrides d'état de `eth_call`**
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
### 5.12 — Un paramètre jamais déclaré a tué toutes les ventes pendant 35 minutes

`prepare_sell` référençait `proprietaire` sans l'avoir dans sa signature. J'avais ajouté ce
paramètre à `prepare_buy` et écrit la ligne correspondante dans `prepare_sell` sans toucher à sa
déclaration. Le fichier s'importe très bien : un `NameError` ne se déclenche qu'à l'exécution de la
ligne, et cette ligne n'est atteinte **que lorsqu'une position doit être vendue**.

Conséquence : le moteur a tourné normalement pendant 35 minutes, achetant sans problème, jusqu'à ce
qu'une position ait besoin de sortir. Là le cycle entier s'est écrasé — `run_cycle` → `run_carnet`
→ `_positions` → `prepare_sell` — et il s'est réécrasé à chaque cycle suivant.

Le coût, mesuré sur HTZ SOL (§ courbe `solana_suivi`, paire `FtE3k1FS…`) :

    16:33:14  x1.01
    16:34:24  x0.66   sous le stop, un seul relevé : la double confirmation tient
    16:35:01  x0.78   rebond -- la règle avait raison
    16:36:35  x0.82
       trou : le stop se confirme, la vente s'écrase à 16:37:08
    16:38:38  x0.27   vente réelle, 90 s plus tard
    16:41:27  x0.04   rug complet

Réalisé −14,57 € sur 20 €. Sorti au stop comme prévu (~x0,68 après glissement), la perte aurait été
d'environ −6,5 €. **Le défaut a coûté ~8 € sur ce seul ticket.**

Ce qu'il faut en retenir, et qui vaut au-delà de ce bug :

- **Un chemin de code qui ne s'exécute qu'en cas de perte n'est jamais testé par le trafic normal.**
  Les achats fonctionnaient, les logs étaient verts, le tableau de bord paraissait sain. Seul un
  ticket perdant révélait la panne — c'est-à-dire le pire moment possible pour la découvrir.
- **Une exception dans la boucle de position tue AUSSI la boucle de position suivante.** Le cycle
  n'est pas cloisonné par position : une seule ligne en échec bloque la sortie de toutes les autres.
- **Après toute modification de signature, appeler la fonction une fois à blanc.** Trente secondes
  auraient suffi ; huit euros ont payé l'omission.

### 5.13 — Vendre là où le jeton est, et signer avec la bonne clé

En corrigeant 5.12 j'ai trouvé deux défauts dormants dans la vente manuelle, tous deux muets :

1. `vendre()` ne cherchait le solde que sur le portefeuille manuel. Une position ouverte avant la
   création de ce portefeuille dort sur celui du robot : la commande répondait « le portefeuille ne
   détient pas ce jeton » sur une ligne parfaitement vivante — donc **impossible à vendre depuis
   Telegram**. C'est le cas de RIKA. `_valeur()` cherchait déjà sur les deux ; la vente non.
2. La transaction était assemblée pour `signer_address()` (robot) puis signée avec la clé manuelle.
   Un propriétaire et une signature qui ne correspondent pas donnent une transaction invalide, et
   l'échec n'apparaît qu'au rejet du réseau — position toujours ouverte, opérateur convaincu
   d'avoir vendu.

Règle : **le portefeuille qui détient décide, et la clé suit le portefeuille.** On cherche le solde
sur tous les portefeuilles connus, on retient lequel a répondu, et on passe ce propriétaire ET sa
clé au reste de la chaîne.

### 5.14 — « $0.00 » dans un portefeuille veut dire « prix inconnu », pas « sans valeur »

Phantom affichait `$0.00` sur une position de 34 $, tout en indiquant `−$15.50` sur la même ligne —
une contradiction qui est le signe même du défaut : le **solde** est juste, la **cotation** manque.

Cause : le jeton se négocie sur *Meteora DAMM v2*, un type de pool que Phantom n'indexe pas. Jupiter
non plus — son `priceImpactPct` renvoyait la valeur plafonnée (1 = 100 %), identique pour 1 % et
pour 100 % de la position, ce qui est un aveu d'absence de prix de référence et non une mesure.

La preuve de valeur ne vient d'aucun afficheur, mais d'une **cotation de revente réelle** :

    vendre 100 % -> 0.329920 SOL
    vendre   1 % -> 0.003305 SOL   (x100 = 0.3305, soit 0,2 % d'écart)

Une sortie linéaire sur deux ordres de grandeur prouve la profondeur du pool bien mieux qu'un champ
d'impact. **Ne jamais conclure « ça vaut zéro » depuis une interface : demander au routeur.**

### 5.15 — Le lien du graphique se construit sur la paire, jamais sur le jeton

`dexscreener.com/solana/<mint>` n'est pas la forme canonique et ne dit pas **quelle** paire s'ouvre.
Un jeton en a souvent plusieurs, dont des mortes : RIKA garde sa courbe pump.fun abandonnée à
0,00004229 $ à côté de son vrai marché PumpSwap à 0,0001718 $ ; Rock traîne trois paires Meteora
dont une à 17 $ de liquidité. Ouvrir la mauvaise donne un graphique qui s'effondre à zéro et fait
croire à une position morte.

On résout donc la paire la plus profonde via `/latest/dex/tokens/<mint>` et on lie sur son adresse.
Bénéfice secondaire : la réponse porte le symbole, ce qui permet d'afficher « Rock » plutôt qu'une
adresse tronquée — et de vérifier d'un coup d'œil qu'on regarde le bon jeton.

### 5.16 — Un journal qui annonce des achats qui n'ont pas eu lieu

`solana ACHAT Sydney · 193 echanges, 91 acheteurs · 20 EUR` etait ecrit au moment ou la DECISION
est enregistree, pas au moment de l'execution. L'ordre a ete refuse une seconde plus tard
(« aller-retour 8,9 % > plafond 8,0 % »), et aucune position n'a jamais existe. Le journal
affirmait pourtant une depense de 20 EUR.

Deux consequences, toutes deux rencontrees le meme jour :

- **on cherche une position qui n'existe pas.** J'ai passe plusieurs minutes a tracer un ticket
  fantome, en soupconnant de l'argent depense hors du livre ;
- **le compte des tickets est faux si on le lit dans les logs.** Les refus y ressemblent aux achats.

La ligne dit desormais `RETENU ... EUR demandes`. L'achat reel se lit sur `position ouverte`, ecrit
apres l'execution, et le refus a sa propre ligne avec son motif.

Meme famille que le defaut inverse trouve une heure plus tot : une alerte de palier partait sans
ecrire quoi que ce soit dans le journal, et j'ai cherche une alerte deja recue par l'operateur.
**Regle : ce qui se produit s'ecrit, ce qui s'ecrit s'est produit.** Un journal qui ne respecte pas
les deux sens ne sert a rien pour diagnostiquer.

Au passage, ce refus etait la bonne decision : le filtre d'aller-retour a empeche une entree dans un
pool dont on ne serait pas ressorti. C'est le seul filtre a ce jour dont l'utilite se voit
directement.

### 5.17 — `chain_id` ne separe pas les deux carnets : seul `model_version` le fait

J'ai annonce a l'operateur « Solana perd 218 EUR sur 24 h, -0,277 par euro » et bati sur ce chiffre
un raisonnement sur l'autonomie du portefeuille. **Le vrai chiffre est -62,70 EUR, -0,116 par
euro.** Trois fois moins.

La cause est une variante de §5.11. Je filtrais sur `kind='PORTFOLIO'` -- correct -- et sur
`model_version NOT LIKE 'manuel%'` en croyant isoler le carnet du robot. Mais **les deux chaines
partagent `chain_id = 4663`**, et « pas manuel » laisse passer Robinhood :

    t1-watcher-v0.1     Robinhood   30 tickets  -113,44 EUR sur 150 EUR   -0,756/euro
    sol-t1-v0.1         Solana      28 tickets   -67,93 EUR sur 560 EUR   -0,121/euro

Le carnet Robinhood, arrete depuis 11h24, tenait encore dans la fenetre de 24 h par ses tickets
anterieurs. J'additionnais donc les pertes d'un carnet mort a celles du carnet vivant, et le
resultat par euro etait doublement faux : les numerateurs s'additionnaient alors que les mises,
150 EUR contre 560, ne sont pas comparables.

Pire : j'ai ensuite alerte l'operateur en annoncant « Robinhood tourne encore » sur la foi de ces
memes 30 tickets. Fausse alerte -- dernier achat a 11h24, `enabled: false`, zero position ouverte.

**Regles :**

- **Le carnet se designe par `model_version`, jamais par `chain_id`.** Les deux carnets vivent sur
  le meme identifiant de chaine ; c'est le moteur qui les separe, pas le reseau.
- **Une exclusion (`NOT LIKE`) n'isole rien.** Elle laisse passer tout ce qu'on n'a pas prevu.
  Nommer ce qu'on veut (`model_version = 'sol-t1-v0.1'`) plutot qu'enumerer ce qu'on refuse.
- **Un resultat par euro n'a de sens qu'a mise homogene.** Additionner des tickets de 5 EUR et de
  20 EUR et diviser par la somme melange deux experiences.
- **Une fenetre glissante contient les morts.** Un carnet arrete pese encore sur les 24 h suivant
  son arret ; toute lecture doit verifier la date du dernier achat avant de conclure qu'il tourne.

Consequence pratique : la pente reelle du carnet Solana est bien moins raide que ce que j'ai
annonce, et la decision de l'operateur doit se prendre sur -63 EUR par jour, pas sur -218.

### 5.18 — Un plafond de positions reelles qui comptait le papier

`decisions.py` et `fastlane.py` limitaient les achats a `max_open` (15 par defaut) avec :

    SELECT COUNT(*) FROM positions WHERE chain_id=? AND status IN ('OPEN','HALF')

Sans filtre sur `kind`, ce compte inclut les positions a blanc. Etat reel au moment de la
decouverte : 12 lignes VIRTUAL de `intel-scoring-v0.3.0` ouvertes depuis cinq jours, 1 de
`intel-scoring-v0.2.0` depuis six jours, 1 VIRTUAL de `t1-watcher-v0.1`, et 2 lignes PORTFOLIO sans
mise (des observations : « entrée = premier prix observé, coût réel inconnu »). Soit **16 pour un
plafond de 15**.

**Consequence : le carnet Robinhood etait sature par des simulations.** Il est arrete, donc l'effet
etait invisible -- mais a sa reactivation il n'aurait rien achete du tout, et le seul indice aurait
ete une ligne de log `voie rapide, ecarte : 18 positions deja ouvertes`, qu'il faut deja soupconner
pour aller la lire.

C'est la troisieme fois en deux jours que le melange reel/papier fausse quelque chose : §5.11 sur
les resultats annonces, §5.17 sur la separation des carnets, et maintenant un garde-fou de trading.

**Regle : toute requete qui pilote une decision d'argent reel filtre `kind='PORTFOLIO'`, au meme
titre qu'une requete de resultat.** La table `positions` sert quatre usages -- carnet reel, carnet a
blanc, observations sans mise, positions manuelles -- et rien dans son nom ne le dit.

**Garde-fou qui manquait** : un plafond atteint devrait dire ce qu'il compte. `18 positions deja
ouvertes` ne permet pas de voir que 16 d'entre elles sont fictives ; `18 dont 2 reelles` l'aurait
montre du premier coup d'oeil.

### 5.19 — Une transaction refusee pour un octet de trop

`solana ordre non envoye Caviar : decoded VersionedTransaction too large: 1233 bytes (max: 1232)`.
Jupiter avait compose une route a plusieurs sauts dont la transaction depassait d UN octet la limite
absolue de Solana. Deux ordres sur 747 (0,27 %). L argent n etait pas en jeu -- le refus arrive
avant l envoi -- mais l occasion l etait, pour une raison purement technique.

**Ce qu il ne fallait PAS faire** : brider les routes par defaut avec `maxAccounts`. Cela degraderait
la route des 99,7 % d ordres qui passent, pour en sauver 0,3 -- et une route plus courte veut dire
un moins bon prix.

**Fait** : mesurer la transaction REELLEMENT construite (`len(base64.b64decode(tx))`) et ne recoter
que si elle depasse 1 180 octets, en resserrant `maxAccounts` a 40, puis 32, puis 24 jusqu a passer.
Un ordre normal ne paie rien ; un ordre au bord est sauve.

**Branche sur l achat ET sur la vente.** La vente compte davantage : un achat rate coute une
occasion, une sortie bloquee coute la position -- ce que §5.12 a demontre le meme jour, pour 8 EUR
sur un seul ticket.

Verifie a blanc sur une position reelle : vente 881 octets, achat 1 092 octets, aucune recotation
declenchee, aucune transaction envoyee.

**Regle generale :** *une limite technique se traite au bord, pas au centre.* Un garde-fou qui
s applique a tous les cas pour proteger les cas extremes est un cout permanent contre un risque
rare ; mesurer puis corriger ne coute que sur les cas concernes.

### 5.20 — Une colonne absente sur 2 % des lignes, et c'etait le meilleur ticket

`PURR` a rapporte +18,02 EUR en 141 secondes, sorti a x1,90 -- le plus gros gagnant de la journee.
Sa ligne n a **ni `entry_price` ni `peak_price`**. Le multiple annonce dans le motif de sortie est
calcule ailleurs, sur les montants reellement echanges, donc le resultat encaisse est juste ; c est
la colonne de prix qui manque.

Frequence : **1 ticket sur 44 (2,3 %)**. Avec n=1 il n y a aucune correlation a etablir -- que le cas
manquant soit le meilleur ticket est une coincidence, pas un motif, et il faut le dire ainsi.

**Mais la consequence, elle, est structurelle** : toute analyse indexee sur `entry_price` --
distribution des sommets, multiples atteints, calibration d un objectif -- ecarte ces lignes en
silence. Aujourd hui cela revenait a supprimer le seul ticket a x1,90 d un echantillon de 44, dont
la moyenne passe de -3,42 a -2,94 EUR selon qu on l inclut ou non.

**Regle : une analyse annonce combien de lignes elle a ecartees, et pourquoi.** Un filtre implicite
`WHERE entry_price IS NOT NULL` est un echantillonnage non declare -- meme famille que le zero de
`uniq_payers_30s` confondu avec une absence d acheteurs (§3.57) et que la liquidite absente lue
comme nulle, qui avait produit la fausse « meilleure regle » `liquidity_usd < 8,83`.

### 5.21 — Corriger un bug peut retirer un frein : le scanner debloque par accident

Troisieme occurrence en deux jours du meme melange reel/papier, et la plus consequente. Apres
`decisions.py` et `fastlane.py` (§5.18), `intel/execution/safety.py` -- **le portail qui autorise
reellement les ordres** -- comptait lui aussi toutes les lignes sans filtrer `kind` :

    avant   20 positions comptees (14 VIRTUAL + 2 observations sans mise + 2 reelles + 2 autres)
    apres    2 positions comptees
    plafond 15

Consequence mesuree : **91 refus** « 20 positions ouvertes >= plafond 15 » entre le 07/09 02h11 et
le 09/09 21h05. Le carnet du scanner refusait TOUS ses achats depuis trois jours, non par jugement
de marche mais par erreur de comptage.

**Et voila le vrai enseignement.** En corrigeant ce compte j ai retire, sans le vouloir, le SEUL
frein d un carnet en `mode: live` sur Robinhood Chain -- celui dont le resultat mesure est de
**-0,72 par euro**, avec 12 lignes invendables sur 21, et dont l operateur avait arrete le jumeau le
matin meme. Ce carnet a 57 achats reels a son historique, le dernier le 09/09 a 11h24.

Un bug tenait lieu de garde-fou. Le reparer etait juste ; l effet de bord ne l etait pas.

**Fait** : `execution.kill_switch: true`, qui retablit l etat EFFECTIF -- aucun achat EVM -- avec du
code juste plutot qu avec une erreur de comptage. Le drapeau ne touche pas Solana :
`solana_watcher` n emprunte pas ce chemin. Le retirer appartient a l operateur.

**Regles :**

- **Avant de reparer un garde-fou, verifier ce qu il retenait.** Un compteur faux qui bloque un
  carnet perdant produit le bon resultat pour la mauvaise raison ; le corriger sans regarder
  transforme une reparation en autorisation de depenser.
- **Un etat obtenu par accident se re-etablit deliberement, jamais en laissant le bug.** Sinon la
  prochaine correction le retire a nouveau, et personne ne saura pourquoi le carnet s est reveille.
- **Chercher les autres occurrences du meme motif AVANT de conclure.** J ai corrige deux sites en
  croyant avoir fini ; le troisieme etait celui qui comptait. `grep "COUNT(*) FROM positions"` en
  entier, pas le premier resultat.

### 5.22 — L'arret d'urgence bloquait les sorties ; vente automatique des lignes manuelles EVM

L operateur, avant de dormir le 09/09 : « sur les positions manuelles tu vends cette pose si elle
fait un gros gain cette nuit » -- DOGSHIT, 95,36 EUR, sur Robinhood Chain.

**Premier obstacle, trouve en verifiant le chemin : `kill_switch` refusait TOUT ordre**, ventes
comprises (« arret d urgence actif » ajoute quel que soit `kind`). Pose a 21h10 pour empecher le
scanner de racheter (§5.21), il aurait aussi empeche de solder DOGSHIT sur un pic nocturne. Le
fichier faisait pourtant lui-meme l argument inverse trois lignes plus bas pour la liste blanche
(« applying it to a sell traps the book »). Corrige : l arret d urgence ne bloque que `BUY`.
Verifie : SELL_HALF et SELL_ALL autorises, BUY refuse.

**Deuxieme obstacle, evite de justesse.** A 23h09 un achat manuel de DOGSHIT via Telegram avait ete
refuse pour « dernier echange il y a 551 min (> 15 min) » alors que le pool echange toutes les dix
secondes -- l horodatage du dernier echange que lit le chemin EVM est perime pour un jeton que le
scanner n ingere pas. Si ce controle s appliquait aux ventes, la sortie nocturne aurait ete refusee
pour la meme fausse raison. Il ne s applique qu aux achats (`if is_buy:` dans `prepare()`, avec un
commentaire du 07/09 qui dit exactement pourquoi). La fraicheur perimee reste un defaut a traiter :
elle refuse des achats manuels legitimes sur des jetons hors scanner.

**Mecanisme pose.** `surveiller()` couvrait seulement `manuel-sol-v1` ; il couvre desormais toutes
les lignes `manuel-%`, valorise les EVM par `_valeur_evm`, et -- si `manuel.vente_auto.enabled` --
ecrit une DECISION que l executeur EVM ramasse a son cycle de 5 s et dimensionne sur le solde reel :
SELL_HALF a `moitie_a` (x2), SELL_ALL a `tout_a` (x4), chaque tranche une seule fois (notes
`vendu:`), avec un message Telegram a chaque emission. Deux tranches parce que c est ainsi que
l operateur trade lui-meme (2dDDte sorti en trois fois pour x3,13).

Verifie de bout en bout sans rien envoyer : valorisation DOGSHIT x0,88 ; garde-fou ; filtre de
`pending_decisions` (accepte `manuel-evm-v1`) ; `surveiller()` execute en direct sans erreur et sans
emission (0,88 < 2) ; les deux decisions `manuel-evm-v1` presentes en base sont d anciens achats
deja journalises REFUSED, donc hors file.

**Regles :**
- **Un arret d urgence arrete ce qui depense, jamais ce qui sort.** Sinon il transforme une
  protection en piege, et c est au pire moment qu on s en apercoit.
- **Avant de promettre une action nocturne, parcourir le chemin complet a la main** : ce soir deux
  murs sur quatre maillons, dont un que le code documentait deja.
- **Un incident du heredoc** : un `
` de source est devenu un vrai retour a la ligne dans une
  f-string et a casse `manuel.py` sur le disque AVANT la verification `ast.parse`. Ecrire le fichier
  apres la verification, pas avant ; et passer par un script ecrit directement plutot que par un
  heredoc quand le contenu porte des sequences d echappement.

### 5.23 — `/manuel` montrait le registre, pas la chaine

« Manuel affiche pas ce que tu montres. » L operateur venait de recevoir une carte de ses six
portefeuilles lue sur la chaine (653 EUR) et `/manuel` lui repondait trois lignes et un latent de
-77 EUR. Les deux etaient justes ; ils ne repondaient pas a la meme question. `/manuel` lisait la
table `positions` -- ce que le systeme avait ENREGISTRE -- et ses PURR sur Trust, son SOL, son ETH
n y figuraient pas parce que personne ne les avait saisis.

Meme lecon que §5.1, prise a l envers : la regle « le P&L se lit sur le solde du portefeuille,
jamais sur une cotation » avait ete appliquee a la valorisation des lignes connues, pas a la liste
des lignes elle-meme. Un registre dit ce qu on croit avoir ; la chaine dit ce qu on a.

**Fait.** `manuel.portefeuilles` declare les six adresses publiques (nom, chaine, qui detient la
cle). `Manuel._inventaire()` les lit toutes a chaque `/manuel` : SOL et comptes de jetons par
`getTokenAccountsByOwner` ; ETH par `eth_getBalance` et, faute d index de jetons sur Robinhood
Chain, les jetons connus du registre par `balanceOf`. Valorisation par la paire la plus profonde de
DexScreener -- un ordre de grandeur, pas un prix de sortie, contrairement aux lignes du registre
qui sont cotees au routeur.

**Un defaut attrape a la premiere sortie** : les jetons EVM etaient lus dans un ensemble tronque a
40 dans un ordre arbitraire ; les dizaines de vieilles lignes Robinhood ont fait disparaitre
DOGSHIT (84 EUR) de son propre portefeuille. Corrige : positions ouvertes en tete, puis les plus
recentes. Total lu : 648,73 EUR, coherent avec la carte de minuit (653,20 aux prix d alors).

**Ce qui reste a faire, et qui n est pas du code** : six portefeuilles pour deux usages, dont un
partage entre le moteur et le MetaMask de l operateur. La structure saine est deux portefeuilles --
un a lui, un au moteur -- et c est un virement entre ses poches, a faire eveille.

### 5.24 — La vente demandee n'est pas partie, et le scanner a ferme la ligne : deux bugs a moi

L operateur, avant de dormir : « tu vends cette pose si elle fait un gros gain cette nuit ». DOGSHIT
a fait x2,98 a 03h05, x3,27 au pic. Rien n a ete vendu. Chaine exacte :

    03:05:04  x2,98 -> le suivi manuel emet SELL_HALF, alerte Telegram partie     (correct)
              ... et ecrit le multiple 3,27 dans `peak_price`, une colonne de PRIX (bug 1)
    03:05     `build_and_sign` refuse : « arret d urgence actif »                   (bug 3)
    03:06:08  le scanner Robinhood ramasse la ligne manuelle                       (bug 2)
              lit peak_price = 3,27, prix reel 0,00055 -> « -100 % depuis le plus haut »
              emet SELL_ALL et FERME la ligne dans le registre -> plus de surveillance
    03:06     ce SELL_ALL est refuse a son tour (« impact 81 % », etat de pool perime)

**Bug 1, a moi.** Le code des paliers ecrivait `peak_price = MAX(peak_price, mult)`. Un multiple
dans une colonne de prix. Corrige : le pic va dans les notes (`pic:`), en multiple, et
`peak_price` n est plus touche par le suivi manuel.

**Bug 2, a moi, pour la cinquieme fois.** `open_position` excluait les lignes `t1-%` et rien
d autre. Le scanner a adopte la ligne manuelle. Meme classe que §5.11, §5.17, §5.18, §5.21 -- un
`model_version` non filtre -- que j avais corrigee site par site en ratant celui-ci. Corrige a la
racine : `intel/engines/carnet.py` definit les quatre carnets et le fragment SQL de chacun ; le
scanner (`decisions.py` x3, `fastlane.py` x2, `digest.py`) ne voit plus que `intel-%` ; l executeur
dimensionne une vente sur la ligne du carnet DE LA DECISION (`held_units`). Regle : une requete sur
`positions` qui filtre `token_address` sans filtrer `model_version` est un defaut, pas un style.

**Bug 3, a moi, promis la veille.** J avais retire l arret d urgence de la porte de securite pour
qu il ne bloque que les achats (§5.22), verifie a cet endroit, et promis la chaine. Il existait un
SECOND controle dans le signataire, aveugle au sens de l ordre. Corrige : `verifier_arret(ctx,
sortie=...)` ; `build_and_sign` recoit `sortie=(kind != BUY)` des deux appels de l executeur.

**Cout.** La moitie qui devait partir a x2,98 (~142 EUR) n est pas partie ; la ligne a cesse d etre
surveillee pendant que le prix redescendait de x3,27 a x3,13. Rien n est perdu tant que les 786 244
DOGSHIT sont la, mais le gain fond.

**Reparation.** Ligne #460 rouverte, `peak_price` vide, marque `vendu:moitie` retiree (rien n a
ete vendu). `manuel.vente_auto.enabled: false` : l operateur a dit de ne pas vendre, rien ne
vendra sans son mot.

**La lecon de methode, celle qui coute.** Verifier un maillon et promettre la chaine. Trois fois
cette semaine : `prepare_sell` (§5.12), la porte de securite (§5.22), le signataire (ici). Regle
desormais inscrite : *aucun chemin qui touche l argent n est annonce avant un passage a blanc de
bout en bout, du seuil jusqu a la signature.*

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
- **Un garde-fou d'unicité en mémoire n'en est pas un.** `self.judged` garantissait qu'un pool
  n'est jugé qu'une fois — jusqu'au redémarrage suivant, qui le rouvrait au prix effondré du
  moment (§3.37). Sur un système corrigé plusieurs fois par jour, l'unicité doit s'appuyer sur la
  base de données.
- **Comparer rejeu et réel se fait par époque de règle.** Les lignes jouées avant l'ajout du stop
  ne se comparent pas à un rejeu qui l'applique : l'écart apparent était de +0,412 par euro, il
  devient −0,090 une fois les époques séparées (§3.31). Les dates de changement de règle sont
  consignées ici exactement pour ça.
- **Apparier par POOL, jamais par jeton.** Un jeton gradué a plusieurs pools ; le collecteur en
  suit un, le moteur en trade un autre. Trois grosses pertes ont semblé se produire « pendant que
  le marché montait » à cause de cet appariement, et deux positions apparaissaient achetées hors
  de la fenêtre d'achat (§3.43). Le pair_id réellement tradé est dans les notes de la position.
- **Un filtre se juge sur l'entonnoir complet, pas sur sa propre justification.** Trois filtres
  posés en deux jours, chacun raisonnable isolément, ramenaient ensemble le carnet à un ticket
  toutes les treize heures — donc à l'impossibilité d'apprendre (§3.48). Après chaque ajout,
  mesurer combien de passages il reste par heure.
- **Un réglage envoyé à une API tierce se vérifie dans sa RÉPONSE, jamais dans sa documentation.**
  Les frais de priorité demandés au niveau « high » faisaient appliquer 40 % de moins que le défaut
  de Jupiter (§3.49). Deux appels de quinze secondes l'auraient montré ; je ne l'ai découvert que
  parce qu'un ordre a échoué.
- **Toute requête de résultat filtre sur `kind='PORTFOLIO'`.** La table `positions` mélange carnet
  réel et carnet à blanc ; sans le filtre on annonce −339 € au lieu de −115 € (§5.11).
- **Un chiffre s'annonce avec la taille de son échantillon**, et quand elle est mince la conclusion
  s'écrit « on ne conclut pas ». Une chute mesurée sur 14 lancements n'est pas une tendance.
- **Un signal ne se juge jamais sous une seule règle de sortie.** La durée de détention fait partie
  de la stratégie, pas du décor. Le même groupe Telegram vaut +0,174 par euro à quatre minutes et
  −0,34 à quinze : §3.72 l'avait déclaré signal négatif en ne testant que quinze minutes, §3.73 en
  a fait le meilleur résultat du projet. Avant d'enterrer une famille, balayer la sortie.
- **Le test du hasard porte sur la statistique qui porte l'effet.** Sur une population à queue
  épaisse, la moyenne d'un tirage aléatoire varie tellement qu'aucun effet réel ne s'en distingue :
  le groupe Telegram donne 11,6 % sur la moyenne et 0,00 % sur le taux de gagnants et la médiane,
  pour le même échantillon. Choisir la statistique AVANT de voir le résultat.
- **`reponse.get("result") or []` efface la différence entre « rien » et « refusé ».** Le 13/09 j'en
  ai conclu qu'un contrat BNB n'émettait aucun événement, alors que le nœud répondait
  `limit exceeded` — et j'ai annoncé à l'opérateur qu'il fallait un accès payant. Vérifier la
  présence d'une erreur AVANT de lire un résultat. Troisième occurrence de cette famille cette
  semaine, après l'IPFS à 429 (§3.72) et le prix aberrant de HYPE (§5.30).
- **Une variable lue après coup doit être prouvée non modifiable après coup.** Sinon la mesure lit
  le futur sans le dire. Pour les métadonnées de jetons Solana la chaîne le garantit
  (`updateAuthority: None` sur 40 sur 40, §3.73) ; partout ailleurs, horodater à la lecture.
- **Regarder ce qui est déjà configuré avant de demander quoi que ce soit.** Le 12/09 j'ai demandé
  à l'opérateur de me fournir un jeton de robot Telegram qui était dans son `.env` depuis un mois
  (`TELEGRAM_BOT_TOKEN_BIS`), et je lui avais avant ça fait chercher un canal public qui n'était pas
  le sien, faute d'avoir listé les robots branchés.
- **Un filtre mesuré sur une population ne se transporte pas dans un sous-groupe.** Le filtre
  « trop propre » écarte un groupe perdant partout — sauf chez les jetons Telegram, où le même
  groupe gagne (+0,156 par euro, 76 % de gagnants). Remesurer le filtre dans le sous-groupe.
- **Le silence d'une règle est une donnée, pas une attente.** La règle « petite capitalisation ET
  gros pool », seule survivante d'un balayage de 1 866 combinaisons, n'a tiré aucun ticket en neuf
  heures d'observation. Ce n'était pas faute d'occasion : ses deux conditions étaient
  arithmétiquement incompatibles, et la colonne qui les portait comptait des unités d'un jeton qui
  n'était pas du SOL (§3.74). Une règle qui ne tire jamais se dissèque immédiatement — compatibilité
  de ses conditions, et provenance de chaque colonne qu'elle lit.
- **Deux conditions sur un pool à produit constant ne sont pas deux signaux.** `mcap / pool_sol`
  vaut identiquement `offre / reserve_base` : croiser une capitalisation et une taille de pool ne
  produit qu'une variable structurelle déguisée. Avant de croiser deux mesures d'un même pool,
  écrire leur rapport.
- **Un effet mesuré sur une seule source de prix reste une propriété possible de ce capteur.** La
  règle Telegram venait entièrement de DexScreener. Rejouée sur les prix lus aux réserves — autre
  capteur, autre cadence — elle donne +0,116 par euro contre −0,039, et 0 sur 20 000 au test du
  hasard sur la fréquence des gros tickets (§3.74). Tant que ce contrôle n'est pas fait, un edge
  n'est pas confirmé, il est seulement reproductible chez le même fournisseur.
- **Un zéro se suspecte d'abord comme un défaut d'instrument.** « Zéro lien social sur 6 766
  créations BNB » n'était pas un fait sur la chaîne : DexScreener ne porte simplement aucun bloc
  `info` pour un jeton four.meme sur courbe. La vraie valeur est 40 % (§3.75). Avant de conclure
  d'une mesure nulle ou plate, la disculper : interroger une seconde source, ou vérifier champ par
  champ que l'information cherchée est bien censée s'y trouver.
- **Un signal énorme n'est pas un rendement.** Le SOL accumulé dans la courbe sépare les futures
  graduées d'un facteur 21 à T+1 min et 165 à T+3 min, et le seuil multiplie par 23 le taux de
  graduation — sans qu'aucune règle exécutable ne gagne d'argent, parce que la hausse est déjà
  passée quand on arrive (le prix à T+15 s vaut 1,96 fois le prix de graduation). Mesurer la
  séparation d'un signal et mesurer ce qu'il rapporte sont deux questions différentes ; seule la
  seconde décide.
- **Un majorant qui brille ne prouve rien.** « Acheter à T+300 s et vendre à la graduation » donne
  +1,499 par euro — en supposant connu d'avance qui graduera. La même entrée, filtrée sur la seule
  information disponible à l'instant, donne entre −0,11 et +0,11 selon le seuil, et rien ne survit
  à « sans best ». Toujours écrire la version qui ne sait rien du futur AVANT de se réjouir.
- **Le scepticisme doit peser les preuves dans le bon sens.** Le 14/09 j'ai écarté un filtre positif
  sur 35 tickets de vrai argent parce que 13 tickets SIMULÉS ne le confirmaient pas (§3.79). Après
  trois fausses découvertes dans la semaine, la méfiance était devenue un réflexe au lieu d'un
  calcul. Avant d'enterrer un résultat sur un échantillon contradictoire : comparer les tailles, et
  se demander lequel des deux est le plus proche de la décision réelle.
- **Un filtre se juge sur le CONTRASTE, pas sur le niveau du groupe gardé.** Le niveau bouge avec la
  période — le même groupe donne +0,227 sur une moitié et +0,184 sur l'autre. L'écart entre ce qu'on
  garde et ce qu'on jette, lui, reste du même signe : +0,206 / +0,285 / +0,389 / +0,166 sur quatre
  échantillons (§3.79). Le test du hasard porte sur le contraste.
- **Un filtre utile coupe la traîne sans rogner les ailes.** Le filtre « 3 signes » change de +15 €
  et +3 € les deux bons jours, et de +202 € le mauvais (§3.79). Un filtre qui améliore surtout les
  bons jours ne fait que sélectionner du passé ; celui qui coupe les pires jours protège.
- **Le silence d'un paramètre d'API vaut refus.** `type=buyNow` filtre bien les ventes Magic Eden,
  mais `activityType` et `kind` sont ACCEPTÉS sans effet et renvoient le flux non filtré (§3.80).
  Une collecte bâtie dessus aurait tourné des heures pour rien. Vérifier dans la RÉPONSE que le
  filtre demandé a été appliqué, jamais dans le fait que l'appel n'a pas échoué.
- **Juger une nouvelle famille à l'aune de la stratégie en place est une paresse.** J'ai d'abord
  écarté le NFT parce qu'il ne se trade pas en 4 minutes — vrai et hors sujet. La bonne question
  était : où est l'inefficacité sur un marché LENT ? (§3.80) La réponse était mesurable et a fermé
  la piste pour une bonne raison au lieu d'une mauvaise.
- **Un contraste positif n'est pas une stratégie gagnante.** Le contraste juge un filtre ; l'argent ne
  dépend que du NIVEAU du groupe gardé, après coûts d'exécution MESURÉS en chaîne, sur toute la
  période. Le filtre propre battait le reste de +0,080 et rapportait lui-même +0,004 avant coûts,
  −0,006 après : 229 tickets réels et −436 EUR plus tard (§3.81). Avant d'engager un euro : écrire
  l'espérance par ticket en EUR, coûts réels inclus.
- **Rien ne part en production sans son P&L rejoué, coupé en deux moitiés.** Le 15/09 la vente sur
  cascade a été mise en live avant d'avoir le P&L ; rejouée ensuite : +123 EUR sur une moitié, −81
  sur l'autre (§3.81). Des tests unitaires qui passent prouvent que le code fait ce qu'on veut, pas
  que ce qu'on veut rapporte.
- **Une moyenne sur une traîne épaisse se lit avec et sans ses meilleurs tickets.** +0,232 par euro
  sur 1 103 tickets devenait −0,054 en retirant UN ticket à ×316 (§3.81).
- **Avant d'attribuer une cause, la chercher dans le code.** « `pool_quote` a cessé d'être remplie
  après l'échange de base » : faux, aucun moteur ne l'a jamais remplie (§3.81). Une recherche d'une
  seconde l'aurait montré.


---

### 3.123 — La trajectoire du STOCK : le collecteur, et les deux pièges trouvés en le construisant, 2026-09-18 16h30

**L'hypothèse est de Mido, et elle ne ressemble à rien de ce qu'on a testé.** « Une partie des
effondrements vient de groupes entrés très tôt, disposant encore d'un stock énorme par rapport aux
acheteurs présents. Le signal d'achat serait une transition : les premiers détenteurs ont largement
distribué, des acheteurs extérieurs continuent d'arriver, et leurs achats absorbent les ventes
restantes. »

Ce qui la distingue : **toutes** nos variables sont des mesures de PRIX, et elles disent toutes la
même chose — ce qui prédit la chute prédit la montée (§3.107, « le modèle mesure la VIE »). Ici on
ne mesure pas le prix, on mesure un ÉTAT : combien de munitions restent au-dessus du marché.

Et elle explique un échec qu'on n'avait pas su expliquer. `expert_detenteurs` (§3.110) regarde
`sac1` à UN seul instant, 45 s, et fait −169 € sur 269 tickets. L'objection le démolit exactement :
deux jetons peuvent avoir la même concentration alors que dans l'un le groupe initial a déjà vendu
et dans l'autre il tient encore de quoi vider le pool. **Une photo ne distingue pas les deux.**

#### Le collecteur : `intel/research/stock_collecte.py`

Quatre photos de `getTokenLargestAccounts` aux âges 15, 25, 35, 45 s, dans sa propre base
`papier_stock.sqlite`. Il stocke des FAITS BRUTS — parts cumulées, portefeuilles, offre, coffre — et
aucune variable dérivée : « a-t-il vendu ? » se calcule à l'analyse, ce qui permet de la reformuler
quand elle montrera un motif monotone (règle 3 de la discipline).

Coût mesuré : **270 ms en médiane, 2,8 s au pire**, trois appels RPC par photo. Un tour est borné à
la fois en nombre (12) et **en temps (6 s)**, et les photos sont classées par fenêtre la plus proche
de se fermer : sans ça une photo lente en faisait rater trois autres.

#### Piège n°1 — le plus gros détenteur est TANTÔT le coffre du pool, TANTÔT un portefeuille

Le premier essai donnait `s1 = 79,3 %` sur deux jetons et `s5 = s20 = 100 %`. Vérification sur six
pools, en comparant le plus gros compte au compte de réserve du pool :

| jeton | s1 | est-ce le coffre ? |
|---|---|---|
| `RCLi3Q5gRpqf` | 79,3 % | non — un vrai portefeuille |
| `qDPBddfjjcZk` | 79,4 % | non — un vrai portefeuille |
| `6TcJ4MJsxyo1` | 54,8 % | **oui, le coffre** |
| `GmJAEGGte1y6` | 50,1 % | **oui, le coffre** |

**Ce sont les deux situations les plus opposées qui soient** : dans l'une l'offre est enfermée dans
le pool et personne ne peut la déverser, dans l'autre un seul acteur tient de quoi vider le pool
plusieurs fois. Non corrigé, `s1` leur donnait exactement le même chiffre. C'est le piège qui avait
déjà rendu `sac_wallet` inutilisable (654 jetons, 654 portefeuilles distincts : c'était le coffre,
unique par construction).

La correction ne coûte rien : **`pair_id` EST l'adresse du pool**, donc le coffre est le compte dont
le propriétaire est le pool. Aucun `getProgramAccounts` — l'appel à 15 s de timeout — n'est
nécessaire. Vérifié : le coffre est reconnu sur 5 pools sur 6.

#### Piège n°2 — `getTokenLargestAccounts` rend des comptes-jetons, pas des portefeuilles

Un portefeuille a un compte-jeton **différent par jeton**. Garder l'adresse technique interdisait de
reconnaître un même acteur d'un lancement au suivant — c'est-à-dire précisément la suite de
l'hypothèse (financement commun, achats synchronisés, transferts entre eux). `getMultipleAccounts`
donne le propriétaire (octets 32-64 d'un compte SPL) pour les vingt comptes **en un seul appel**.

#### Premier échantillon, et le risque qu'il montre déjà

Deux jetons complets, quatre photos chacun. Ils illustrent parfaitement les deux états :

| jeton | plus gros **portefeuille** | top-20 hors pool |
|---|---|---|
| `2ZQmqyyrtP2T` | 3,8 % — le stock est dans le pool | 53,0 % |
| `DeBEtV2ycUcZ` | **44,0 %** — un seul acteur | 82,7 % |

**Mais aucun des deux n'a bougé d'un point entre 15 et 45 s.** Si c'est général, le « film »
n'apporte rien sur la « photo », et la photo est déjà mesurée perdante (−169 €). **C'est la première
chose à mesurer, avant toute variable de décision** : quelle est la dispersion de `s1_hp` entre 15 et
45 s ? Si elle est nulle, la piste est close, et c'est un résultat utile — Mido l'avait prévu :
« on pourrait aussi découvrir que cette transition n'arrive presque jamais ».

#### Ce que ça ne donnera pas, et il faut le savoir AVANT de mesurer

Le lien entre portefeuilles. Si le gros détenteur transfère à trois complices au lieu de vendre, la
concentration baisse et on croira à une distribution alors que le stock est intact. **Ce biais va
dans le mauvais sens : il fait paraître bons des cas qui ne le sont pas.** Le reconstruire
demanderait les transactions du pool — `getSignaturesForAddress` bloque plusieurs minutes sur un
jeton actif, et 98 % des sorties passent par un routeur (§3.42) — donc hors de portée en 45 s.

#### Le critère du verdict, écrit AVANT les données

Reformulation du test décisif de Mido : *à âge, mouvement récent et liquidité comparables, cet état
du stock prédit-il un meilleur rendement réellement exécutable ?* Donc :

1. **Au moins 300 jetons complets** (4 photos, sans erreur), sinon rien n'est conclu.
2. Le verdict se juge **après le coût mesuré de 2,62 pts**, sur des lancements **postérieurs** à ce
   gel, et **sans les 3 meilleurs tickets**.
3. Comparaison à âge/liquidité comparables, et à un **tirage aléatoire de même taille** — une règle
   qui garde peu de tickets doit battre le hasard, pas la moyenne générale.
4. La part d'ex æquo est affichée à côté de chaque variable (règle 2).

Surveillé par le gardien. 14 tests le protègent (`tests/intel_tests/test_stock_collecte.py`), dont
un qui interdit au collecteur de contenir le moindre mot de décision.


---

### 3.124 — `sac1` empilait deux états opposés : `expert_detenteurs` ne ferme pas la concentration, 2026-09-18 17h00

En corrigeant le collecteur de stock, une question s'est imposée : **`social_collecte` exclut-il le
coffre du pool ?** Non. Donc `sac1` — la variable sur laquelle `expert_detenteurs` a fait −169 € et
sur laquelle j'ai fermé la piste de la concentration — mesurait tantôt le coffre, tantôt un
portefeuille.

Diagnostic sur 571 jetons ayant à la fois une mesure de détenteurs et un résultat, en résolvant le
propriétaire de chaque compte-jeton (octets 32-64) et en le comparant à l'adresse du pool :

| le plus gros détenteur était | n | `sac1` médian |
|---|---|---|
| le **coffre du pool** | 209 | 20,3 % |
| un **vrai portefeuille** | 106 | 78,6 % |
| compte fermé, non classable | 256 | — |

**20,3 % contre 78,6 % : ce ne sont pas des mesures bruitées autour d'une même grandeur, ce sont
deux variables empilées**, et elles décrivent les situations les plus opposées qui soient.

#### Mais l'écart de rendement ne peut PAS être cru, et la raison est instructive

| groupe | n | moyenne | médiane |
|---|---|---|---|
| coffre | 209 | −9,94 % | −16,96 % |
| vrai portefeuille | 106 | −2,77 % | −1,49 % |
| **compte fermé, écarté** | **256** | **−2,49 %** | **+13,98 %** |

Sept points d'écart entre les deux premiers, même signe sur les deux moitiés, 86,4 % contre le
hasard. Tentant. **Et faux.**

Pour classer un jeton d'hier il faut résoudre le propriétaire de son compte **aujourd'hui**. Un
compte fermé ne se relit plus — vérifié un par un avec `getAccountInfo`, ce ne sont pas des échecs
d'appel groupé. Donc **« le compte est-il encore lisible ? » est une information du FUTUR par rapport
à la décision à 45 s**, et elle est massive : +13,98 % de médiane pour les non-classables contre
−2,60 % pour les classables, seize points.

Classer là-dessus, c'est trier avec le résultat — **la même famille d'erreur que le `sort()` sur
`(prédicteur, résultat)`** qui avait produit un faux Q3 à +30,64 % (règle 2). Je l'ai évitée
uniquement parce que j'avais écrit « mesurer le groupe écarté » dans le critère avant de regarder.

#### Ce que ça change vraiment

1. **Le verdict −169 € d'`expert_detenteurs` ne ferme pas la question de la concentration.** Il
   condamne `sac1` tel qu'il était mesuré. La grandeur qu'il prétendait mesurer n'a jamais été testée.
2. **L'histoire ne peut pas répondre.** Toute reconstruction rétrospective de « qui détenait quoi »
   passe par des comptes dont la survie dépend du résultat. Seule une collecte **en avant** le peut.
3. **C'est précisément ce que fait `stock_collecte.py`** (§3.123), qui résout le propriétaire à
   15–45 s, quand le compte existe forcément. Construire le collecteur était donc le bon choix, pour
   une raison que je n'avais pas vue en le construisant.
4. Le sous-découpage lourd/léger parmi les portefeuilles **échoue** : signe opposé entre les deux
   moitiés, 76,9 % contre le hasard (il en faut 95). Rien là, et de toute façon il hérite du biais.

**Nouvelle règle de discipline, la 11 :** *avant de classer des données passées avec une lecture
faite maintenant, se demander si la lecture aurait pu échouer pour une raison liée au résultat.* Un
compte fermé, un jeton disparu, une page supprimée : l'absence est rarement au hasard.

Script : `intel/research/sac_diagnostic.py`.


---

### 3.125 — Le frein débranché : « hors échantillon de la BANDE » n'était pas hors échantillon du frein, 2026-09-18 19h30

Mido, en lisant le tableau des pistes : **« mec c'est toi qui a dit le frein fonctionne »**. Il avait
raison de le demander, et la vérification lui donne raison sur le fond.

#### Ce qui m'avait convaincu n'était pas un test

Le commit qui branche le frein en production annonce :

> HORS ECHANTILLON de la bande (458 tickets) : sans frein +0,54 %, **AVEC frein +2,27 %**

Hors échantillon **de la bande** — pas du frein. Et le même commit écrit, deux lignes plus bas,
« la fenêtre de 20, **choisie sur les données** ». J'ai donc jugé le frein sur les tickets qui
l'avaient fait choisir. Coupé à la date de son propre gel (18/09 15h00 UTC) :

| | tickets | sans frein | avec frein | écart |
|---|---|---|---|---|
| **avant** son gel | 1 383 | −0,25 % | +1,25 % | **+1,49 pt** |
| **après** son gel | 82 | −1,47 % | −10,38 % | **−8,91 pt** |

**C'est le même motif que `BAS + BANDE`** (+9,02 % avant / −7,10 % après). Troisième fois dans ce
projet, et les trois fois c'est Mido qui l'a vu, pas moi.

En deux moitiés chronologiques, le frein coûte **−23,50 pt** puis **−0,99 pt** : négatif des deux
côtés, il n'aide jamais. Un tirage au hasard de même taille fait aussi mal dans 2,7 % des cas — donc
juste au-delà du bruit, sur 82 tickets seulement.

#### Et l'argument qui le tenait en production était faux

J'avais écrit, et c'est ce qui a emporté la décision :

> RISQUE ASYMÉTRIQUE […] le frein ne fait que S'ABSTENIR. Au pire il réduit le volume sans rien
> améliorer ; **il ne peut pas créer de perte nouvelle**.

**C'est faux, et l'erreur est générale.** S'abstenir n'est neutre que si l'on s'abstient au hasard.
Un filtre écarte par construction un sous-ensemble ; s'il contient préférentiellement des gagnants,
il crée bien une perte par rapport à ne pas l'avoir. **Aucune abstention sélective n'est gratuite** —
c'est vrai de tous les filtres du projet, pas seulement de celui-ci.

#### Ce qui a été fait

`frein_enabled: false`. La production revient à **`risque` seul**. Le gel `frein_taux.py` continue
de le juger en papier jusqu'à 1 500 tickets, sans rien coûter. 82 tickets ne tranchent pas une
question ; ils suffisent à ne pas laisser un pari sur l'argent réel quand la seule raison de l'avoir
pris s'est révélée fausse.

**Règle de discipline 13 :** *« hors échantillon » n'a de sens que rapporté à UNE règle précise.*
Un chiffre hors échantillon de A ne dit rien de B si B a été choisi sur ces mêmes données. Écrire
systématiquement **de quoi** le hors-échantillon est hors.

**Règle 14 :** *un garde-fou qui « ne fait que s'abstenir » n'est pas sans risque.* Écarter n'est
gratuit que si l'on écarte au hasard.


---

### 3.126 — La COURBE pump.fun rejouée : témoin négatif partout, et deux règles qui tombent sur le contrôle, 2026-09-18 20h30

Mido, après qu'on a montré que les acheteurs du pool perdent : **« tu dis que ceux qui gagnent
achètent sur la courbe, pourquoi on le fait pas ? »**

La question était juste, et le dossier existait déjà : 1,2 Go de transactions de courbe (13–14/09),
`courbe_verdict.py`, protocole **figé avant** de regarder la table le 15/09 au soir. Il n'avait
jamais tourné faute de `lightgbm` dans le conteneur. Installé (+ `libgomp1`, `pandas`,
`scikit-learn`), en revérifiant après chaque étape que le moteur réel et les quatre collecteurs
réimportent — c'est un conteneur qui manipule de l'argent réel.

#### Le témoin : aucune case positive

Acheter sur la courbe à un niveau S de SOL levé, garder H secondes :

| | H=60 | H=300 | H=1800 |
|---|---|---|---|
| S=5 SOL | −0,091 | −0,167 | −0,259 |
| S=10 | −0,124 | −0,200 | −0,308 |
| S=20 | −0,108 | −0,186 | −0,274 |
| S=40 | −0,047 | −0,030 | −0,088 |
| S=50 | −0,043 | −0,010 | −0,069 |
| S=70 | −0,050 | −0,064 | −0,082 |

**Vingt-et-une combinaisons, vingt-et-une négatives.** Et le motif est monotone en H : plus on
garde, plus on perd — le même fait que dans le pool.

#### Les deux familles, et ce qui les tue

**Famille 1** (règles) : S=50, filtre « flux calme », H=300 s. TRI +0,0377 → **TEST −0,1160**,
moitiés −0,1835 / −0,0521, et **le hasard fait aussi bien 14 fois sur 20**. NON.

**Famille 2** (LightGBM du rendement net) : S=10, H=300 s, haut 10 %. TRI +0,0791 → **TEST +0,0677
sur 40 tickets, et 0 tirage au hasard sur 10 ne fait aussi bien**. Sur ces deux chiffres seuls,
c'est un GO éclatant.

**Il échoue sur les deux contrôles qui ne regardent pas le p :**
- **sans son meilleur ticket : −0,0075.** Un seul ticket porte +6,77 % de moyenne sur 40.
- **première moitié −0,0037**, seconde +0,1391.

VERDICT NON, et il est mérité. C'est la démonstration la plus nette de la journée que **le p-value
ne protège de rien** : 0 tirage sur 10, et un seul ticket derrière.

#### Ce que ça ferme, et ce que ça corrige

1. **La courbe est close comme lieu d'achat.** Le pool perd, la courbe perd, copier ceux qui gagnent
   perd (−6,25 %), et les trois familles bâties sur leur comportement perdent (−4,3 / −7,7 / −12,0).
2. **Correction d'une formulation à moi, du même soir** : j'avais dit que la courbe était « le seul
   endroit où un signal d'argent réel a été mesuré positif ». Le +3,9 % décrit la performance de
   **325 portefeuilles déjà sélectionnés pour être bons** — pas une règle achetable. Le second ne se
   déduit pas du premier, et le test dit le contraire.
3. **Une note de mémoire affirmait que Mido avait « refusé » la collecte de courbe le 15/09.** C'est
   faux : `courbe_collecte.py` porte en en-tête « accord de l'opérateur : vas-y ». Il l'a dit lui-même
   — *« j'ai jamais rien refusé c'est toi qui décide avec les chiffres »*. **Règle 15 : ne jamais
   attribuer à l'opérateur une décision dont je n'ai pas la trace ; si une piste n'a pas été
   explorée, la raison par défaut est la mienne.**


---

### 3.127 — Site, Twitter, Telegram déclarés : le meilleur contraste du projet, et il ne vaut rien, 2026-09-18 21h15

Mido : **« on a testé pour Telegram mais ça n'a pas fonctionné, le fait d'avoir un site web ça ajoute
plus sérieux ? »**

**La question n'avait jamais été testée.** Ce que le projet appelait « le test Telegram », c'étaient
des **signaux de chaînes** — quelqu'un poste un jeton, on l'achète. Ici il s'agit de la
**métadonnée** : le créateur a-t-il déclaré un lien ? `features_lancement.py` annonce `a_site`,
`a_twitter`, `a_telegram` dans sa documentation **depuis le 09/09** sans qu'aucun ait jamais été
implémenté. Neuf jours.

Collecte : `liens_collecte.py`, **2 115 jetons lus sur 2 138**. Les métadonnées pump.fun sont des
fichiers IPFS **immuables** : les relire aujourd'hui rend exactement ce qui existait à la décision.
C'est l'opposé du piège des comptes fermés (§3.124).

#### Le résultat

| | n | moyenne | médiane | sans 3 meil. |
|---|---|---|---|---|
| **avec** site | 1 561 | −0,53 % | +2,79 % | −1,39 % |
| **sans** site | 554 | −4,49 % | +0,11 % | −6,33 % |

Écart **+3,96 pt**, moitiés **+7,13 / +0,59** (même signe), et **il tient sans les 3 meilleurs**.
Twitter donne +3,66 pt, Telegram +4,52 pt, tous deux de même signe sur les deux moitiés.

**Trois critères sur cinq passent — c'est le meilleur score de toute la journée.**

#### Pourquoi c'est quand même NON

**(4) Ça ne bat pas le hasard.** Permutation sur l'écart : 7,6 % pour le site, 11,2 % Twitter,
17,0 % Telegram. Et **28,4 %** pour la loi du maximum sur trois variables essayées.

**(5) Le groupe AVEC perd quand même : −0,53 %.** C'est le critère décisif, et c'est la règle qui a
coûté 436 € le 15/09 : **l'argent se décide sur le NIVEAU, jamais sur un contraste.** Avoir un site
rend le jeton moins catastrophique, pas rentable.

Et le filtre serait faible : **73,8 % des jetons déclarent un site**, donc l'écarter ne retire qu'un
quart du flux — un flux dont on a mesuré qu'il perd.

#### Deux erreurs à moi, dans la même heure

1. **12 fils sur les passerelles IPFS → 1 505 erreurs 403 sur 1 511 échecs.** Je martelais `ipfs.io`
   parce que l'ordre des passerelles était fixe. Corrigé : 8 passerelles **tirées au hasard** à
   chaque appel, 4 fils → 2 115 lus. Les 6 seuls vrais 404 montrent que les échecs étaient
   mécaniques, pas liés au contenu — sans cette vérification, 71 % de données manquantes auraient pu
   être une sélection.
2. **Mon test de la loi du maximum comparait un ÉCART ENTRE DEUX GROUPES à des écarts de MOYENNE
   D'ÉCHANTILLON.** Deux grandeurs d'échelle différente : il annonçait **0,0 %** là où le test
   correct (permutation des étiquettes) donne **28,4 %**. Un test qui rend 0,0 % doit être suspecté
   avant d'être cru. **Règle 16 : un test de significativité se valide en vérifiant qu'il compare
   bien la MÊME grandeur des deux côtés.**


---

### 3.128 — Le scope large : 19 494 tests croisés, et rien que le hasard ne produise, 2026-09-18 21h33

Mido : *« je te dis tout tout tout tout. Il faut partir d'un scope très large et réduire, affiner. »*
Et son diagnostic : chaque variable avait été testée **seule**, jamais croisée.

**La table unique** (`tout_table.py`) : 2 208 tickets × **107 variables de 13 familles** — prix à
45 s, métadonnée, liens relus, image, détenteurs, stock, créateur en série, canal Telegram, source,
temps, régime causal, transactions des 45 premières secondes (acheteurs, tailles, robots récurrents
connus **avant** ce jeton, vendeurs sans achat), offre — × 8 cibles (6 horizons de sortie). Tout
compteur historique ne compte que les jetons nés avant. `tg_poste` exclu : 891 postés, **0 avant
45 s** — une fuite.

**Le balayage** (`tout_balayage.py`) : 56 variables × 5 coupes × 6 horizons = 1 668 tests seuls,
puis les paires des 20 meilleures = 17 826 tests. **19 494 au total.** Trois tranches
chronologiques (RECHERCHE 40 / TRI 30 / TEST 30), coût 6,55 pt, et la **loi du maximum sur le
balayage entier** : cibles mélangées, tout refait 20 fois.

#### Le témoin, au coût réel, sur TEST

| H | moy | méd | gagnants | catastrophes |
|---|---|---|---|---|
| 240 s | **−7,96 %** | −4,07 % | 44,5 % | **21,3 %** |

#### Ce que le hasard produit sur 19 494 tests

Meilleur TEST des 20 balayages sur cibles mélangées : +8,10, +5,76, … **+26,67, +41,67 %**.
**Barre (95ᵉ centile) : +27,42 %.**

#### Le vrai meilleur

`px_q_croiss bas20 ET tps_heure haut50`, H=287 : TEST **+7,54 %** sur 53 tickets — **sans ses 3
meilleurs −2,00 %, moitiés +30 / −15**. Les 25 meilleures ont toutes `sans3 < 0` et des moitiés de
signes opposés.

**VERDICT : +7,54 % contre une barre à +27,42 %. Le balayage n'a rien trouvé que 19 494 essais au
hasard ne produisent tout seuls.**

#### L'idée de la distribution — la seule ligne qui approche zéro

`v1_sol_ventes bas50 ET v1_sol_sans_achat bas20` (peu de ventes, et peu de SOL sorti par des vendeurs
qui n'ont pas acheté) : **catastrophes 1,7 % contre 21,3 %**, moyenne **−0,65 %** contre −7,96 %,
n=121. C'est la seule règle des 19 494 dont la moyenne approche zéro, et elle le fait en supprimant
les catastrophes — exactement le mécanisme que Mido décrivait. **Mais elle reste négative, elle est
une parmi 19 494, et elle n'a pas été sélectionnée par la barre du hasard.** Notée, pas retenue.

Le motif `q haut20` (gros coffres) : catastrophes 1,9 % mais moyenne −6 % — un gros pool évite la
falaise et ne rapporte rien, ce qu'on avait déjà mesuré (§3.113).

#### Ce que ça ferme

Le scope large était la bonne demande, et il est fait : **toutes** les sources, croisées, sur
**toutes** les cibles, avec le seul contrôle qui compte pour un balayage. Le résultat est le même
que pour chaque variable prise seule. Ce n'est plus « on n'a pas assez cherché ».


---

### 3.129 — Trois idées à moi, testées le soir même : être le pool, les survivants, un autre marché. Trois morts, 2026-09-18 22h05

Mido : *« si je dois fournir l'idée autant la tester moi-même, à quoi sers-tu ? »* Juste. Toutes les
pistes du jour venaient de lui. Voilà les miennes, et ce que la machine en a fait.

**Le fait qui les motive**, sorti du balayage large : **le problème n'est pas la queue, c'est le
corps.** Les règles qui suppriment les catastrophes (1,9 % au lieu de 21 %) font quand même −6 %,
parce que le péage de 6,55 mange les tickets normaux. Filtrer l'achat, sous toutes ses formes, est
donc mort. Il faut changer de **côté** ou de **péage**.

#### 1. Être le pool (changer de côté) — mort
L'argent va aux vendeurs et aux frais. Déposer de la liquidité PumpSwap de 25 s à 60 s, 1 661 pools,
20 € : **−3,12 %** en moyenne (médiane +0,37 %, 58 % gagnants), **avant** frais de dépôt/retrait et
impact d'achat de la moitié en jetons. Frais LP gagnés : **0,0001 SOL** sur 0,19 déposé — notre part
du pool est trop petite pour que les frais comptent, et la réserve SOL se vide quand les vendeurs
sortent. `intel/research` (calcul inline, journal).

#### 2. Les survivants (changer de péage) — mort
À une heure d'âge les pools sont gros et l'impact tombe à quelques dixièmes de point. Grille sur
`solana_suivi_long` (4 261 jetons, 24 h, un relevé/min) : retour à la moyenne **et** momentum,
chute/hausse de 20–50 % depuis l'extrême de l'heure, cible +10/+20 % ou horizon 30–240 min, entrée au
relevé suivant, vente au relevé suivant la cible, coût 0,5 pt + 2×20 €/liquidité. **96 règles, 96
négatives.** Meilleure : réversion 20 %, H=240 min, **−3,36 %**, médiane **−41,84 %**, 22 % de
gagnants. Acheter une chute sur un survivant, c'est acheter la suite de la chute. Le momentum ne
figure même pas dans les 15 premières. `survivants.py`.

#### 3. Un autre marché : BNB / four.meme — mort
`bnb_balayage.py` rejoué sur l'ancienne base (617 jetons du 13/09) : 35 cellules, presque toutes à
**exactement −0,030** — le péage de 3 % et rien d'autre. **Les prix ne bougeaient pas.** Un marché
sans mouvement ne paie même pas ses frais. Une journée de données : un ordre de grandeur, suffisant
dans ce sens-là.

#### Ce que ça dit, mis bout à bout
Pool à 47 s, courbe, copie des gagnants, liquidité, survivants à 1 h, autre chaîne, 19 494 croisements
de 107 variables : **tout ce qui est accessible à un acheteur de 20 € est négatif après le péage
réel.** Ce n'est plus une question de piste. Ce qui reste d'inconnu : (a) `stock_collecte` (les 300
vers 4 h), (b) **quatre jours ne distinguent pas « pas d'edge » de « mauvaise semaine »** — la
machine est automatique maintenant, la rejouer chaque semaine sans un euro en jeu est la seule chose
qui ait encore une valeur d'information.


---

### 3.130 — Réentraîner `risque` jusqu'à 18h : pire après 18h, 2026-09-18 22h19

Mido : *« si tu réentraînes risque seul jusqu'à aujourd'hui 18h, améliore-t-il les données après 18h ? »*

Même modèle (19 variables lues dans `modele_vidage.json`, cible `brut_240 ≤ −0,50`, mêmes
hyperparamètres), seule la date de fin d'entraînement change. Comparaison à effectif égal sur la
fenêtre de jugement, coût 6,55, tirage au hasard de k tickets en témoin. `reentrainer.py`.

| coupe 18h → après 18h (126 tickets) | en service | réentraîné | hasard |
|---|---|---|---|
| AUC vidage | **0,651** | 0,550 | — |
| k = 79 (la règle) | −13,81 % | **−17,02 %** | −14,75 % |
| 50 % gardés | −8,26 % | −15,99 % | −14,67 % |
| 30 % gardés | −5,41 % | −11,68 % | −14,59 % |

Le modèle frais fait moins bien que le vieux **et** que le hasard. Le vieux classe encore (bat
91–93 % des tirages à 30–50 % gardés) mais son niveau reste à −5 / −8 % : classer n'est pas gagner.

Coupe de midi (156 tickets, jugés midi→18h) : le frais fait +0,20 % contre −3,44 % au k de la règle
(AUC 0,614 contre 0,563), puis **s'inverse à 30 % gardés** (−6,21 contre −3,04), et son sans-3 est
négatif partout. Deux coupes, deux réponses contraires : **réentraîner ne produit rien de stable.**
L'information ne dérive pas ; elle est faible, et le péage la mange, frais ou vieux.


---

### 3.131 — Réentraîner l'ensemble de 12 et la forêt jusqu'à 18h : rien de stable non plus, 2026-09-18 22h23

Mido : *« entraîne 12 modèles »*. Même test que §3.130, même recette que les fichiers en service,
sur **grande table (26 566 lignes, 09→15/09) + carnet papier jusqu'à la coupe** — strictement plus
de données et plus récentes, pour que « frais » ne veuille pas dire « dix fois moins ».
`reentrainer_ensemble.py`.

**Coupe 18h → après 18h (126 tickets, témoin −14,7 %, hasard −15 %)**

| gardés | ENS service | ENS frais | FORÊT service | FORÊT fraîche |
|---|---|---|---|---|
| k=81 | −12,91 % | −8,00 % | −8,72 % | −12,61 % |
| 50 % | −8,29 % | −8,32 % | −10,13 % | **−4,21 %** |
| 30 % | −5,27 % | −4,89 % | −5,02 % | **−0,71 %** (sans3 −8,13) |

Tous battent le hasard (−15 %) : le classement contient de l'information sur cette fenêtre. Aucun
niveau n'est positif ; le meilleur, −0,71 % sur 38 tickets, fait −8,13 % sans ses 3 meilleurs.
L'ensemble frais est **identique** à l'ensemble en service (−8,32 contre −8,29 ; −4,89 contre −5,27).

**Coupe midi → 12h–18h (156 tickets, témoin −1,32 %)** : forêt fraîche +2,14 % à k=104 (bat le
hasard 88 %) puis **−5,08 % à 50 % gardés** (19 %) ; à 30 % tout le monde est à −2,7/−3,3 % et
personne ne bat le hasard.

**Verdict, identique à §3.130 :** réentraîner ne produit rien de stable. L'ensemble frais copie
l'ancien ; la forêt fraîche oscille entre meilleure et pire selon la coupe et l'effectif. Le
classement existe faiblement, le niveau est négatif, et le péage de 6,55 tient tout sous zéro.


---

### 3.132 — Marche avant : réentraîner toutes les 6 h et trier à 30 %, sur toute la période — non, 2026-09-18 22h26

Mido : *« si on fait −0,71 % sur une journée compliquée c'est pas mal non ? »* La bonne question
n'est pas une fenêtre mais toutes : `marche_avant.py`, 11 coupes de 6 h du 16/09 00h au 18/09 18h,
à chaque coupe forêt (300 arbres) et ensemble (6 boostings) réentraînés sur grande table + carnet
avant la coupe, jugés sur les 6 h suivantes, 30 % et 50 % gardés, tout additionné. Coût 6,55.

| fenêtre | n | témoin | forêt 30 % | forêt 50 % | ens 30 % |
|---|---|---|---|---|---|
| 16/09 00h | 200 | −12,45 % | −5,91 % | −9,16 % | −8,41 % |
| 16/09 06h | 137 | −1,99 % | −3,35 % | +5,11 % | −3,49 % |
| 16/09 12h | 155 | −2,03 % | **+0,15 %** | +0,36 % | −2,05 % |
| 16/09 18h | 95 | −4,28 % | −7,25 % | −5,30 % | −9,79 % |
| 17/09 00h | 185 | −11,05 % | −8,10 % | −10,05 % | −8,75 % |
| 17/09 06h | 164 | −8,36 % | −11,12 % | −9,51 % | −7,31 % |
| 17/09 12h | 164 | +4,71 % | −7,73 % | −5,93 % | −6,62 % |
| 17/09 18h | 215 | −6,24 % | −3,92 % | −5,21 % | −1,79 % |
| 18/09 00h | 214 | −8,28 % | −3,25 % | −1,58 % | −1,88 % |
| 18/09 06h | 168 | −8,84 % | −5,30 % | −4,34 % | −5,53 % |
| 18/09 12h | 156 | −1,32 % | −2,30 % | −3,66 % | −3,33 % |

**Toute la période, additionnée :**

| | n | net/ticket | € à 20 € | sans 3 meil. | gagnants | catastrophes |
|---|---|---|---|---|---|---|
| témoin | 1 853 | −5,90 % | −2 186 € | −6,67 % | 43 % | 22 % |
| **forêt 30 %** | 552 | **−5,23 %** | **−577 €** | −5,71 % | 34 % | **7 %** |
| forêt 50 % | 924 | −4,72 % | −872 € | −5,62 % | 42 % | 13 % |
| ensemble 30 % | 552 | −5,15 % | −569 € | −5,68 % | 35 % | 8 % |

**Une fenêtre positive sur onze** (16/09 12h, +0,15 %). Sur la fenêtre où le témoin gagne
(17/09 12h, +4,71 %), la forêt triée fait −7,73 % : elle écarte précisément les tickets qui montent.
Le −0,71 % de la soirée était **une fenêtre, pas une règle**.

**Le fait qui compte, une troisième fois :** trier à 30 % fait passer les catastrophes de 22 % à
**7 %** — et le net ne bouge que de 0,67 point (−5,90 → −5,23). La perte n'est pas dans la queue,
elle est dans le corps. Le péage de 6,55 sur les tickets ordinaires reste au-dessus de ce qu'ils
rapportent, catastrophes ou pas.


---

### 3.133 — Une forêt sur TOUT (107 variables) : premier total positif d'une marche avant, +0,41 % — et pourquoi ça ne suffit pas, 2026-09-18 22h30

Mido : *« on a construit une forêt en croisant toutes nos variables, réseau, prix, image ? »*
**Non** — les modèles en service n'utilisent que 19 variables de prix. Fait ce soir :
`marche_avant_tout.py`, 11 coupes de 6 h, forêt (300 arbres) sur les 107 variables de la table
unique, deux cibles : **vidage** (celle des modèles actuels) et **gain** (P(net > 0)), 30 % et 50 %
gardés, coût 6,55.

| toute la période | n | net/ticket | € | sans 3 meil. | gagnants | catastrophes |
|---|---|---|---|---|---|---|
| témoin | 1 853 | −5,04 % | −1 868 € | −6,39 % | 44 % | 20 % |
| vidage, forêt 30 % | 552 | −3,19 % | −352 € | −3,83 % | 38 % | 6 % |
| vidage, forêt 50 % | 924 | −1,10 % | −203 € | −3,54 % | 46 % | 10 % |
| **gain, forêt 30 %** | 552 | **+0,41 %** | **+45 €** | **−3,65 %** | **66 %** | 16 % |
| gain, forêt 50 % | 924 | −1,41 % | −260 € | −3,93 % | 60 % | 19 % |
| gain, boosting 30 % | 552 | −2,69 % | −297 € | −4,45 % | 64 % | 16 % |

**Ce qui est nouveau.** C'est la première fois qu'une marche avant du projet rend un total **au-dessus
de zéro** : +0,41 % par ticket, +45 € sur 552 tickets, **66 % de gagnants** contre 44 % au témoin.
Et la cible **gain** fait ce que la cible vidage ne faisait pas — elle ne coupe pas seulement la
queue (16 % de catastrophes, pas 6 %), elle choisit des tickets qui montent.

**Ce qui l'empêche d'être une règle.**
- **Sans ses 3 meilleurs tickets : −3,65 %.** Trois tickets sur 552 portent tout le positif.
- L'écart-type du net par ticket est de **59 points** (mesuré) ; l'erreur standard sur 552 tickets
  est de **±2,5 pt**. +0,41 % est à 0,16 écart-type de zéro : **indistinguable de zéro**. (Une
  première version de ce paragraphe disait « ~35 points » de tête — corrigé sur la mesure.)
- 5 fenêtres positives sur 11 ; la version 50 % est à −1,41 %.

**Où est l'information — le résultat qui compte.** Importance des variables dans la forêt de gain :

| famille | poids |
|---|---|
| **v1 — transactions des 45 premières secondes** (gini des achats, SOL acheté, plus gros achat, vendeurs, ventes, vendeurs sans achat…) | **43 %** |
| prix à 45 s | 17 % |
| taille du coffre `q` | 10 % |
| `risque` (le modèle en service) | 8 % |
| image | 8 % |
| temps, liens, régime, métadonnée, nom, détenteurs, créateur | ≤ 3 % chacune |

**Le flux d'ordres des 45 premières secondes porte plus d'information que le prix** — deux fois
et demie plus. C'est la seule famille du projet qui n'ait jamais été mise dans un modèle avant ce
soir, et c'est celle que la forêt choisit. Ce n'est pas un edge : c'est une direction, la première
qui ne soit pas une mesure de prix, avec des données à 1 409 tickets sur 2 208 seulement (le
collecteur v1 s'est arrêté le 18/09 09h13, quota Helius).


---

### 3.134 — La même forêt, restreinte aux tickets qui ont des données de transactions : +1,05 %, 72 % de gagnants, v1 à 60 %, 2026-09-18 22h35

Vérification de §3.133 : la forêt ne voit plus jamais de trou comblé à la médiane sur la famille
qu'elle préfère. Couverture réelle du collecteur v1 : **16/09 et 17/09 à toutes les heures**
(20–40 pools/h), 18/09 jusqu'à 9h seulement (quota Helius : 150 000 crédits/jour pour ~250 000
nécessaires, par construction). Donc 1 409 tickets sur 2 208, 9 fenêtres au lieu de 11.
`marche_avant_tout.py`, `V1_SEUL=1`.

| toute la période | n | net/ticket | € | sans 3 meil. | gagnants | catastrophes |
|---|---|---|---|---|---|---|
| témoin | 1 242 | −4,72 % | −1 173 € | −5,81 % | 45 % | 20 % |
| **gain, forêt 30 %** | 370 | **+1,05 %** | **+78 €** | **−1,30 %** | **72 %** | 15 % |
| gain, boosting 50 % | 619 | +0,13 % | +16 € | −1,96 % | 63 % | 19 % |
| vidage, forêt 50 % | 619 | −1,66 % | −205 € | −3,42 % | 47 % | 11 % |

**Tout s'est amélioré en retirant les trous** : +0,41 → **+1,05 %**, 66 → **72 %** de gagnants,
sans-3 −3,65 → **−1,30 %**. Et la famille v1 passe de 43 % à **60 %** du poids de la forêt (prix
11 %). Le poids de 43 % n'était donc pas un artefact du remplissage — retirer le remplissage l'a
augmenté.

**Ce qui reste vrai :** sans ses 3 meilleurs, −1,30 % ; 3 fenêtres positives sur 9, le total porté
par le 17/09 12h (+19,68 %) ; erreur standard sur 370 tickets ≈ ±3,1 pt, donc +1,05 % est à 0,34
écart-type de zéro. **Pas un edge.** Une direction qui se renforce quand on la mesure mieux, ce
qui est exactement l'inverse de tout ce qui a été testé ces quatre jours.

Loi du maximum lancée dans la foulée : 12 marches avant complètes avec les résultats permutés
(variables intactes), forêt de gain seule, pour savoir ce que cette machine « trouve » toute seule.


---

### 3.135 — Loi du maximum sur la marche avant : +1,05 % est au 83ᵉ centile du hasard, pas au 95ᵉ, 2026-09-18 22h37

12 marches avant complètes (9 fenêtres, forêt de gain 30 %, `V1_SEUL=1`) avec les **résultats
permutés entre tickets**, variables intactes :

```
+0,12  -5,44  -9,04  +2,39  -4,13  -2,35  -10,15  -1,96  -9,28  -3,83  -6,94  -6,54   (%/ticket)
```

2 tirages sur 12 sont positifs ; le meilleur fait **+2,39 %**. Le vrai +1,05 % est au-dessus de
10 tirages sur 12 — **83ᵉ centile**, en dessous de la barre des 95 %. **Il ne passe pas.**

Une observation secondaire, notée sans en faire plus : sur la statistique robuste (**sans les 3
meilleurs**), le vrai résultat (−1,30 %) est au-dessus des **12 tirages sur 12** (le meilleur des
hasards fait −2,97 %) — p ≈ 1/13 ≈ 0,08 à un côté. Cohérent avec « une direction, pas un edge ».

**Verdict :** non tradeable en l'état. Ce qui le distinguerait du bruit est mécanique, pas
intellectuel : **des tickets**. À 370 tickets l'erreur standard est de ±3,1 pt ; à 1 500 elle
serait de ±1,5. Le collecteur de transactions ne couvre que ~60 % des heures (quota Helius
150 000/jour pour ~250 000 nécessaires). Couvrir 100 % des heures pendant une semaine donnerait
~3 000 tickets avec données de transactions, sans un euro en jeu — c'est la seule dépense qui ait
encore une valeur d'information dans ce projet, et elle se chiffre en crédits RPC, pas en SOL.


---

### 3.136 — Pousser la modélisation à l'intérieur de la marche avant : sept variantes, 2026-09-18 22h44

Mido : *« avant de geler, peut-on pousser la modélisation ? feature selection avec RF, toute autre
idée »*. Fait, avec la seule discipline qui tienne : **chaque choix se fait sur les données
antérieures à la coupe** (sélection de variables, taille de feuille hors-sac, poids), jamais sur la
fenêtre jugée. `marche_avant_plus.py`, 1 409 tickets avec transactions, 9 fenêtres, 30 % gardés,
coût 6,55.

| variante | net/ticket | € | sans 3 meil. | gagnants |
|---|---|---|---|---|
| témoin (tout prendre, 1 242) | −4,72 % | −1 173 € | −5,81 % | 45 % |
| base (§3.134) | +1,05 % | +78 € | −1,30 % | 72 % |
| + 12 variables de transactions | +0,24 % | +18 € | −2,11 % | 71 % |
| **sélection des 25 plus utiles à chaque coupe** | **+1,89 %** | **+140 €** | **−0,54 %** | 72 % |
| feuilles réglées hors-sac | +0,85 % | +63 € | −1,58 % | 71 % |
| espérance (régression du net) | **−3,58 %** | −265 € | −6,56 % | 52 % |
| poids décroissant (½ à 24 h) | +1,77 % | +131 € | −0,71 % | 71 % |
| rang forêt + boosting | +0,57 % | +42 € | −1,69 % | 71 % |

**Ce qui aide :** enlever des variables (sélection : +1,89 %, sans-3 −0,54 %) et pondérer le
récent (+1,77 %). Les deux réduisent le **bruit** — 72 variables pour ~1 000 lignes, c'est trop.
**Ce qui nuit :** en ajouter (+12 variables → +0,24 %) et prédire le montant au lieu du sens
(régression : −3,58 % — les queues à +300 % rendent la régression folle ; classer par P(gain)
est plus robuste). Cohérent : le signal est faible, tout ce qui ajoute de la variance le noie.

**Toujours vrai :** aucune variante n'est positive sans ses 3 meilleurs ; le 17/09 12h porte
+19 à +30 % dans toutes ; 3–4 fenêtres positives sur 9. Et **+1,89 % est déjà sous la barre du
hasard mesurée pour UNE variante (§3.135 : +2,39 %)** — la barre du choix de la meilleure des sept
sera plus haute encore. Lancée : 8 marches avant complètes, résultats permutés, meilleure des sept
retenue à chaque fois (`NULLS=8`, ~80 min).


---

### 3.137 — Barre du hasard sur le choix de la meilleure des sept variantes : un tirage sur huit fait mieux, 2026-09-18 22h53

8 marches avant complètes, résultats permutés, **meilleure des sept variantes retenue à chaque
fois** — le maximum sous permutation de la procédure entière :

```
+3,59  -1,91  -4,32  -2,32  -2,39  -2,74  -1,89  -1,83    (%/ticket)
vrai (sélection) : +1,89 %
```

**Le script a imprimé « AU-DESSUS » et il a tort.** Avec 8 tirages, `np.quantile(·, 0,95)` interpole
entre le 7ᵉ (−1,83) et le 8ᵉ (+3,59) et sort une « barre » à +1,70 % — un artefact : **un tirage
sur huit dépasse le vrai résultat**, p ≈ (1+1)/(8+1) ≈ 0,22. Corrigé dans le script : à petit N on
compte « k tirages sur N font aussi bien », pas un centile interpolé. C'est le même piège que le
test de la loi du maximum des liens (§3.127, 0,0 % faux) : **un test qui rend le verdict qu'on
espère se vérifie avant d'être cru.**

**Lecture correcte, avec §3.135 (12 tirages, une variante : 2 sur 12 au-dessus) :** le vrai
résultat bat 6 tirages sur 7 et 10 sur 12 — **au 80–88ᵉ centile du hasard, jamais au-delà du
maximum.** Meilleur que la plupart des hasards, pas distinguable du meilleur des hasards. C'est la
définition d'une direction, pas d'un edge, et elle est stable d'un test à l'autre.

**Ce qui la ferait passer :** pas une huitième variante — des tickets. ±3,1 pt de marge à 370 ; ±1,5
à 1 500. Une semaine de collecte de transactions à couverture complète.


---

### 3.138 — « T'es sûr ? » : le 60 % des transactions était gonflé par le biais d'impureté, la vraie part est 44 %, 2026-09-18 22h57

Mido : *« mec t'es sûr de ce que tu racontes ? »* Non, pas de tout — et le point le moins sûr était
celui qui portait la « direction ». L'importance d'impureté des forêts **favorise mécaniquement
les variables continues** (beaucoup de valeurs distinctes) contre les binaires ; les 16 variables
de transactions sont toutes continues. Refait avec l'importance par **permutation** (AUC perdu
quand on brouille chaque variable sur la fenêtre jugée, 20 répétitions), dernière coupe, 1 083
tickets d'entraînement, 326 jugés :

| famille | impureté (biaisée) | permutation |
|---|---|---|
| transactions (v1) | 60 % | **44 %** |
| prix | 11 % | 14 % |
| image | 8 % | 12 % |
| coffre `q` | 6 % | 9 % |
| `risque` | 5 % | 8 % |

Les transactions restent la première famille, **mais à 44 %, pas 60 %** — et l'image remonte à
12 % (`img_l`, la largeur, est parmi les 8 variables les plus utiles : cohérent avec l'idée de
Mido sur les gabarits produits en série). Somme des importances par permutation : +0,031 AUC
seulement — les variables sont très **redondantes** (brouiller l'une ne coûte presque rien tant que
les autres restent).

Un chiffre nouveau, à ne pas surinterpréter : **AUC gagnant/perdant de 0,787** sur cette fenêtre
(0,5 = rien), contre 0,55–0,65 pour les modèles de vidage. Une seule fenêtre, et classer n'est pas
gagner (sur ces mêmes heures la marche avant faisait +2,30 % puis −2,18 %). Vérification lancée :
le même AUC sur les 9 fenêtres, chacun contre 20 permutations de ses propres résultats.

**Seconde réserve, non levée :** « ça s'améliore quand on nettoie » (§3.134) a aussi changé la
période (16–17/09 surtout). L'amélioration peut être le marché de ces jours-là.

**Règle 17 :** *une importance de variables se lit par permutation, jamais par impureté, dès que les
familles mélangent continues et binaires.*


---

### 3.139 — Le classement gagnant/perdant EST réel : AUC 0,65–0,82 sur 9 fenêtres sur 9, chacune au-dessus du max de 20 permutations, 2026-09-18 22h58

Vérification du 0,787 de §3.138 sur toutes les fenêtres. Forêt de gain (P(net_240 > 0), 300 arbres,
toutes les variables, `V1_SEUL`), entraînée sur tout ce qui précède chaque coupe, jugée sur les 6 h
suivantes ; à chaque fenêtre, 20 permutations des résultats de la fenêtre donnent l'AUC que le
hasard produit.

| fenêtre | n | AUC | max de 20 permutations |
|---|---|---|---|
| 16/09 06h | 112 | 0,711 | 0,650 |
| 16/09 12h | 120 | 0,730 | 0,584 |
| 16/09 18h | 87 | 0,797 | 0,599 |
| 17/09 00h | 155 | 0,731 | 0,546 |
| 17/09 06h | 137 | 0,654 | 0,617 |
| 17/09 12h | 145 | 0,822 | 0,657 |
| 17/09 18h | 160 | 0,747 | 0,591 |
| 18/09 00h | 192 | 0,805 | 0,532 |
| 18/09 06h | 134 | 0,783 | 0,562 |

**AUC moyen 0,753, min 0,654, max 0,822 — 9 fenêtres sur 9 au-dessus du maximum de leurs 20
permutations.** Ce n'est plus « une direction » : **le modèle sait, hors échantillon et à chaque
fenêtre, quels tickets finiront au-dessus de zéro après le coût réel.** La probabilité que neuf
fenêtres indépendantes dépassent chacune le max de 20 tirages par hasard est de l'ordre de
(1/21)⁹.

**Pourquoi l'argent ne suit pas (encore).** L'AUC mesure le SENS, pas la TAILLE. À 30 % gardés on a
72 % de gagnants et seulement +1,05 % : les gagnants sont petits, les perdants sont grands, et le
péage de 6,55 est dedans. Les deux tests précédents ne se contredisent pas : le classement est réel
(AUC), et l'argent qu'on en tire à 30 % est dans le bruit (écart-type 59 pts par ticket).

**La question devient donc mécanique :** à quelle sélectivité le classement réel devient-il de
l'argent réel ? Courbe lancée : 5, 10, 15, 20, 30, 50 % gardés, calibration par tranche de
probabilité (gain moyen des gagnants, perte moyenne des perdants), et barre du hasard à 200
permutations sur le choix de la meilleure coupe.


---

### 3.140 — Pourquoi un classement réel ne fait pas d'argent : le modèle trouve des survivants modestes, pas des fusées, 2026-09-18 22h59

Courbe de sélectivité de la forêt de gain, 9 fenêtres additionnées, coût 6,55 :

| gardés | n | net/ticket | € | sans 3 meil. | gagnants | catastrophes | fenêtres > 0 |
|---|---|---|---|---|---|---|---|
| **5 %** | 58 | **+4,40 %** | +51 € | **+3,50 %** | **91 %** | 5 % | 5/9 |
| 10 % | 121 | −0,25 % | −6 € | −1,11 % | 82 % | 7 % | 5/9 |
| 20 % | 246 | −0,16 % | −8 € | −1,05 % | 79 % | 11 % | 4/9 |
| 30 % | 370 | +1,05 % | +78 € | −1,30 % | 72 % | 15 % | 3/9 |
| 50 % | 619 | −1,89 % | −234 € | −3,72 % | 63 % | 20 % | 1/9 |
| 100 % | 1 242 | −4,72 % | −1 173 € | −5,81 % | 45 % | 20 % | 2/9 |

**La calibration explique tout** (probabilité prédite contre réalité, toutes fenêtres) :

| p prédite | n | gagnants réels | net | gain moyen des gagnants | perte moyenne des perdants |
|---|---|---|---|---|---|
| < 0,4 | 528 | 26 % | −9,03 % | **+45,0 %** | −28,1 % |
| 0,4–0,5 | 362 | 48 % | −3,57 % | +42,9 % | −46,1 % |
| 0,5–0,6 | 155 | 58 % | −0,73 % | +37,6 % | −53,8 % |
| 0,6–0,7 | 46 | 72 % | +2,07 % | +13,8 % | −27,6 % |
| 0,7–0,8 | 107 | **86 %** | +1,45 % | **+9,7 %** | −49,4 % |
| ≥ 0,8 | 44 | 82 % | +1,41 % | +12,9 % | −50,4 % |

**Le modèle est calibré sur le SENS** — à p ≥ 0,7 il a raison 86 % du temps, hors échantillon. Mais
ce qu'il reconnaît, ce sont des **survivants modestes** : leurs gains moyens font +10 %, contre +45 %
pour les tickets qu'il juge risqués. Et les 14 % de ratés à p ≥ 0,7 perdent −49 %. Arithmétique :
0,86 × 9,7 − 0,14 × 49,4 = **+1,4 %**. Exactement le net observé. **Un classement réel qui
identifie les jetons qui montent peu.** Les fusées sont dans le tas des « risqués », avec les
catastrophes — le modèle mesure la vie, pas la taille, une fois de plus.

**La seule cellule positive sans ses 3 meilleurs de tout le projet** : 5 % gardés, +4,40 %, sans-3
+3,50 %, 91 % de gagnants, 5 % de catastrophes. 58 tickets. Barre du hasard (200 permutations des
résultats dans chaque fenêtre, meilleure des 6 coupes retenue) : 95ᵉ centile **+8,56 %**, max
+17,82 %, **23 tirages sur 200 font aussi bien, p ≈ 0,12**. Non significatif — à 58 tickets la barre
est très haute. Et la courbe n'est pas monotone (5 % bon, 10–20 % ≈ 0, 30 % +1) : à 58 tickets, ça
peut être la forme du bruit.

**Ce que ça vaudrait si c'était vrai** (et rien ne le dit encore) : 5 % de ~470 tickets/jour ≈ 24
tickets × 20 € × 4,4 % ≈ **+21 €/jour** ; à 40 € de mise ≈ +42 €/jour. C'est la première cellule du
projet où l'arithmétique de l'objectif n'est pas absurde. Ce qui la sépare d'un résultat : environ
**quatre fois plus de tickets** — la même conclusion que §3.135 et §3.137, avec maintenant une cible
précise à surveiller (le top 5 % et sa calibration).


---

### 3.141 — Changer la cible (> +5, +10, +20 %) : le modèle reconnaît la survie, pas la taille, 2026-09-18 23h04

Suite directe de §3.140. Si le modèle « > 0 » choisit des survivants modestes, l'entraîner à
reconnaître « > +10 % » devrait choisir des gagnants plus gros. `selectivite.py`, 9 fenêtres.

| cible | gardés | n | net/ticket | sans 3 meil. | gagnants | catastrophes |
|---|---|---|---|---|---|---|
| > 0 | 5 % | 58 | **+4,40 %** | **+3,50 %** | 91 % | 5 % |
| > +5 % | 5 % | 58 | +2,79 % | +1,81 % | 88 % | 9 % |
| > +10 % | 5 % | 58 | −0,67 % | −4,25 % | 67 % | 17 % |
| > +10 % | 10 % | 121 | +5,72 % | −2,54 % | 66 % | 19 % |
| > +20 % | 5 % | 58 | **−9,04 %** | −15,81 % | 47 % | **31 %** |
| > +20 % | 30 % | 370 | −3,26 % | −6,34 % | 47 % | 27 % |

**Plus on demande au modèle de reconnaître de gros gains, plus il choisit des catastrophes** : à
« > +20 % », 31 % de catastrophes et 47 % de gagnants — pire que le témoin. Les fusées et les
falaises sont les mêmes jetons vus à 45 s ; aucune variable ne les sépare. C'est la démonstration
la plus directe du fait central du projet : **le modèle mesure la vie, pas la taille.**

Meilleure des 16 cellules : +5,72 % (> +10 %, 10 % gardés), sans-3 −2,54 %, et **64 tirages sur
200 font aussi bien (p ≈ 0,32)**. Rien ne passe.

**Ce qui reste, et c'est net :** une seule cellule positive sans ses 3 meilleurs dans tout le
projet, la cible « > 0 » à 5 % gardés (+4,40 %, 91 % de gagnants, 58 tickets, p ≈ 0,12 seule).
Changer de cible ne l'améliore pas ; changer de modèle non plus (§3.136). **Seuls des tickets
peuvent la confirmer ou la tuer.**


---

### 3.142 — GEL : forêt de gain, top 5 %, papier, 2026-09-18 23h08

Mido : *« on fait quoi, on gèle et on reste en condition opérationnelle ? »* Oui. Comme chaque gel
de la semaine : le critère écrit avant, le test en papier, jugé sur les tickets postérieurs,
puis plus rien ne bouge. `foret_gel.py`, base propre `papier_foret.sqlite`, sous le gardien.

**La règle, causale et exécutable.** Toutes les 6 h : reconstruire la table unique ; **noter les
tickets nés depuis le passage précédent avec le modèle sauvé à ce passage-là** — donc entraîné
avant leur naissance, la marche avant faite en avant ; renseigner les résultats ; réentraîner sur
tout ce qui précède ; sauver les seuils (quantiles 0,95 et 0,90 des scores d'entraînement). Un
ticket est **retenu** si sa probabilité ≥ seuil des 5 % les plus sûrs. Tickets avec données de
transactions seulement.

**Le critère, au premier atteint de 250 tickets retenus ou de 21 jours** (9 octobre) :
(a) net > 0 au coût 6,55 · (b) positif sans ses 3 meilleurs · (c) positif sur les deux moitiés ·
(d) ≥ 80 % de gagnants · (e) au-dessus de 200 permutations des résultats. **Les cinq, sinon abandon.**

**Ce qui le distingue des cinq gels morts cette semaine :** il repose sur un classement démontré
(§3.139), pas sur un contraste. **Ce qui ne le distingue pas :** 58 tickets, p ≈ 0,12, et cinq
règles avant lui qui avaient l'air aussi bonnes à 58 tickets.

**Limite connue :** le collecteur de transactions s'arrête au quota (150 000 crédits/jour pour
~250 000). À ~60 % de couverture et 5 % retenus, 250 tickets demandent ~15 jours — le critère de
21 jours tombera probablement d'abord. Couvrir 100 % des heures est une décision de quota, pas de
recherche.

**État opérationnel à 23h08 :** carnet réel arrêté (−158,85 €, plafond) · 6 processus sous le
gardien (papier_combo, social_collecte, prix_rapide, stock_collecte, foret_gel, + v1_enregistreur
lancé à part) · stock : les 300 dans la matinée · 9 gels en cours. **Plus rien ne se construit.**


---

### 3.143 — Deux questions de Mido : quoi d'autre pour le modèle, et d'autres familles (réseaux, XGBoost, CatBoost) ?, 2026-09-18 23h10

**Améliorer le modèle, par rendement mesuré cette nuit :**
1. **Des tickets.** Marge ±3,1 pt à 370 tickets (écart-type 59 pts) ; aucun réglage n'a déplacé un
   résultat de plus d'un point. Couvrir 100 % des heures de transactions (quota Helius) pèse plus
   que tout algorithme.
2. **Moins de variables.** Seule modification qui ait aidé : sélection à 25 → +1,89 % contre +1,05
   (§3.136). En ajouter 12 → +0,24. Somme des importances par permutation : +0,031 AUC — forte
   redondance (§3.138).
3. **Pondérer le récent** : +1,77 % (§3.136).
4. **La sortie** : le modèle reconnaît des survivants ; 270 s > 240 s sur tous les tickets (§3.126 :
   +1,91 contre +0,98). Lisible sur les 5 % retenus dans `ret_287` sans toucher au gel.
5. **À ne pas faire** : cibler la taille (−9,04 % à « > +20 % », §3.141), régresser le montant
   (−3,58 %, §3.136), grossir le modèle.

**D'autres familles — pas maintenant, et voici pourquoi c'est mesuré et non une opinion :**
- XGBoost et CatBoost sont la même famille que LightGBM (arbres boostés). Le boosting a été mesuré
  **moins bon que la forêt** sur ces données : 6 boostings, 30 % gardés, **−2,69 %** contre
  **+1,05 %** pour la forêt sur les mêmes tickets (§3.133) ; la moyenne de rang forêt+boosting fait
  +0,57 (§3.136). Sur ~1 400 lignes bruitées le boosting sur-apprend, la forêt moyenne. CatBoost
  (boosting ordonné) est un peu plus robuste : une marche avant de contrôle, pas un chantier.
- Réseaux de neurones : 1 400 lignes tabulaires, 30 % de trous, queues à +300 % — les arbres
  dominent dans les comparaisons publiées à cette taille (Grinsztajn et al. 2022). Question de
  taille d'échantillon, pas de goût.
- Chaque famille essayée est un tirage de plus sous la loi du maximum. À ±3 pt de bruit, deux
  modèles sont indiscernables, et chercher « le meilleur » fabrique le résultat. Séquence : **4×
  plus de données d'abord, comparaison des familles ensuite**, quand une différence pourrait se voir.

Le gel (§3.142) reste tel quel.


**Amendement de §3.142, 23h13 — avant le premier ticket noté.** Mido : *« go 1 »* (moins de
variables). Le gel de 04h00 n'avait encore noté aucun ticket (son premier passage ne fait
qu'entraîner). Règle amendée : à chaque réentraînement, **une première forêt classe les variables
par utilité sur le passé, on garde les 25 premières, on réentraîne dessus** — la variante mesurée à
+1,89 % (sans-3 −0,54) en §3.136. Gel re-daté à 23h13, base et modèle repartis de zéro. Aucune
donnée postérieure au gel n'a été regardée. Le critère ne change pas.


---

### 3.144 — Heures inventées, encore : les en-têtes de §3.128 à §3.143 sont corrigés d'après git, 2026-09-18 23h15

Je n'ai pas relu l'horloge après 22h14 et j'ai daté quinze sections de tête — jusqu'à « 04h30 du
19/09 » alors qu'il était **23h13 le 18/09**. La même faute que ce matin (§3.125, « 20h15 » pour
19h03). Les heures ci-dessus sont maintenant celles des commits (`git log --date`), à la minute.
La date du gel de la forêt, écrite « 04h30 » et donc **dans le futur**, est ramenée à l'heure
réelle du lancement. **Règle 18 : une heure ne s'écrit qu'après avoir été lue — `date`, ou l'heure
du commit — jamais estimée.**
