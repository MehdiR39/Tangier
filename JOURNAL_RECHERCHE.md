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
