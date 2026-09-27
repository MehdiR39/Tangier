> **DOCUMENT HISTORIQUE — plus a jour.** Archive le 27/09/2026 lors du rangement du projet.
> Il decrit le projet tel qu il etait a sa date. Etat actuel : `README.md`, `docs/ARCHITECTURE.md`,
> et la section 0 de `JOURNAL_RECHERCHE.md`.

# Tangier — prompt de reprise

À lire au début de chaque séance, avec `JOURNAL_RECHERCHE.md` (le journal complet, §3.1 à §3.122).

---

## 1. L'objectif et les règles non négociables

**Objectif de Mido : générer en moyenne 50 €/jour.** Il écrit en français, on lui répond en français.

**Contraintes de sécurité, jamais assouplies :**

- La clé privée vit **uniquement** dans `C:\Users\Osiris\Documents\Tangier\.env`. Jamais collée en
  conversation, jamais journalisée, jamais affichée. On ne dérive que l'**adresse publique**.
- Le passage en réel demande **deux actes délibérés** : la clé présente **et** `mode: live`.
- **Ne jamais arrêter ni modifier le carnet réel sans l'accord explicite de Mido.** Instruction du
  18/09 : *« laisse tourner, n'arrête rien sans que je te dise »*.
- Refuser de construire quoi que ce soit qui escroque d'autres acheteurs.
- Les portefeuilles Trust de Mido sont à lui : le moteur n'en a aucune clé, il alerte, il ne signe
  jamais.
- **Aucun changement de production sans approbation explicite et sans P&L rejoué en deux moitiés.**

---

## 2. Comment ça tourne

Un conteneur Docker `tangier-intel`. `intel/` et `config/intel.yaml` sont montés **en lecture
seule** depuis l'hôte — un correctif arrive avec un redémarrage, sans reconstruction.

```
docker restart tangier-intel                       # applique un changement de code ou de config
docker exec -w /app tangier-intel python -m intel.research.<module>
docker exec -e MISE=25 -w /app tangier-intel python data/table_std2.py    # LA table
```

Tests : sur l'**hôte**, avec l'env conda `qrt` (le conteneur n'a ni pytest ni PIL) :
`C:/Users/Osiris/miniconda3/envs/qrt/python.exe -m pytest tests/intel_tests/ -q`

### Les collecteurs détachés

Trois processus lancés à la main dans le conteneur, **qui ne survivent pas à un redémarrage** :
`papier_combo`, `social_collecte`, `prix_rapide`, `stock_collecte`. `intel/research/gardien.py`,
lancé par le scheduler, les relance seul — validé trois fois en conditions réelles le 18/09.
**Attention :** `intel/` est monté en lecture seule, donc le gardien déjà en marche garde la liste
qu'il avait à son import. Un collecteur ajouté à `COLLECTEURS` n'est surveillé qu'après le
**prochain redémarrage du conteneur**.

---

## 3. Les scripts qui comptent

### Moteurs (`intel/engines/`)

| fichier | rôle |
|---|---|
| `scheduler.py` | orchestre tout ; lance aussi le gardien |
| `prix_chaine.py` | lit le prix dans les réserves du pool, **toutes les 10 s** — la source de tout |
| `veille_rapide.py` | lit à **1 s** pour déclencher les seuils, mais **ne garde rien** |
| `modele_rapide.py` | **le moteur qui trade en réel** (voir §5) |
| `telegram_rapide.py` | l'ancien carnet, **en papier** — règle Telegram T+60, mesurée perdante |
| `solana_stream.py` | détecte les migrations pump.fun → PumpSwap |
| `suivi_long.py` | suit 24 h par jeton (DexScreener) |
| `recuperation.py` | **inutile**, désactivé : les cautions sont déjà récupérées par le routeur |

### Recherche (`intel/research/`)

| fichier | rôle |
|---|---|
| `papier_combo.py` | **le carnet papier de référence** : décide à 45 s, sortie 287 s |
| `arbres.py` | charge le modèle LightGBM exporté (`modele_vidage.json`) |
| `calibration_corrigee.py` | **le coût d'exécution réel** — à relancer avant tout chiffre après une reprise |
| `calibration_live.py` | **réel contre papier, sur les mêmes jetons** — la question ouverte n°1 |
| `prix_rapide.py` | collecteur de prix à **1 s** sur la fenêtre 35–310 s |
| `social_collecte.py` | concentration des détenteurs (`sac1`, `n_sacs5`) |
| `image_collecte.py` | images et empreintes perceptuelles (tourne sur l'**hôte**, PIL absent du conteneur) |
| `stock_collecte.py` | **trajectoire du stock** : 4 photos des détenteurs à 15/25/35/45 s, coffre du pool exclu |
| `sac_diagnostic.py` | montre que `sac1` empilait coffre et portefeuille — et pourquoi l'histoire ne peut pas trancher |
| `gardien.py` | relance les collecteurs morts |
| `table_std2.py` | **LA table** (dans le scratchpad, copiée dans `/app/data/`) |

### Les gels (règles pré-enregistrées, chacune avec son critère écrit AVANT)

`au_plus_bas.py` · `bas_bande.py` · `entree_75.py` · `ensemble.py` · `expert_detenteurs.py` ·
`frein_taux.py` · `frein_bande.py` · `usine.py` · `piste_foule.py`

---

## 4. Les faits mesurés — à ne jamais recalculer de tête

- **Le coût d'exécution est de 2,62 points** (moyenne) / 2,41 (médiane), mesuré sur 244 tickets
  réels, mise médiane 30 €. **Partir de ce nombre, jamais le recalculer.**
- **Il n'est pas réductible** : la caution est déjà récupérée (0 compte vide sur la chaîne), baisser
  la priorité fait échouer 4 ordres sur 6, découper l'ordre ne rapporte rien (AMM à produit
  constant), et les gros pools coûtent 1,26 pt de moins mais rapportent 1,26 pt de moins.
  **Le coût n'est pas un frais : c'est le prix de la volatilité qu'on vient chercher.**
- **Le modèle mesure la VIE, pas le danger** : ce qui prédit la chute prédit aussi la montée.
- **La chute est une falaise** : −55 % en une seconde en médiane, 92 % des perdants ont au moins une
  seconde à −20 % ou pire. **Aucun stop n'est possible**, ni avant ni après.
- **Stop et prise de gain coûtent 6,6 points/ticket.** La sortie est à 240 s, sans seuil.
- **Garder un jeton effondré aggrave toujours** : −80,5 % à 4 min, −97,1 % à 20 h, monotone, et
  20 % disparaissent complètement.
- **Le régime de marché n'est pas lisible** sur le rendement moyen (45 formulations testées) —
  **mais il l'est sur le TAUX de gagnants**. C'est la seule chose qui ait marché.

---

## 5. La production, au 18/09 au soir

`modele_rapide` en `mode: live`, mise **20 €** :

1. décision à **45 s**, achat à 47 s ;
2. acheter si `risque ≤ 0,2694` (seuil p80 du modèle) ;
3. **sauf si le frein est fermé** — moins de 11 gagnants parmi les **20 derniers tickets clôturés
   du carnet PAPIER** (jamais du carnet réel : il se bloquerait en boucle) ;
4. vendre à **240 s**, sans stop ni prise de gain ;
5. **arrêt total à −150 €** sur 24 h glissantes. **Aucun plafond en nombre d'ordres** — Mido n'en a
   jamais demandé, et celui que j'avais ajouté a bloqué le carnet en pleine journée.

---

## 6. La discipline — c'est elle qui vaut le plus

Chaque point vient d'une erreur réelle, la plupart commises le 18/09.

1. **Vérifier avant d'annoncer, et publier le `n` avec chaque chiffre.** Ne rien dire de ce qu'un
   résultat *implique* tant que la vérification qui le falsifierait n'a pas tourné.
2. **Ne jamais trier une structure qui contient le résultat.** `sort()` sur `(prédicteur, résultat)`
   trie les ex æquo par le résultat : un Q3 à +30,64 %, p = 0,000, entièrement faux. **Afficher la
   part d'ex æquo** à côté de chaque variable.
3. **Tout motif monotone sur une grandeur DÉRIVÉE doit être refait avec une autre formulation.**
   Le coût « additif » montait avec le rendement (ρ = +0,333) ; en multiplicatif il s'inverse
   (−0,246). C'était la soustraction qui produisait le motif.
4. **Juger une règle sur des tickets POSTÉRIEURS à son gel**, jamais sur ceux qui l'ont fait
   choisir. `BAS + BANDE` : +9,02 % avant, **−7,10 %** après.
5. **Se méfier des moyennes sur des queues épaisses** — c'est le pire estimateur. Un TAUX borné
   révèle ce qu'une moyenne bruitée cache : 45 formulations du régime ont échoué faute de ça.
6. **Une règle qui réduit fortement le nombre de tickets se compare à un tirage ALÉATOIRE de même
   taille**, et un balayage se compare à la loi du MEILLEUR sous permutation.
7. **Toujours regarder le résultat sans ses 3 meilleurs tickets.** C'est ce contrôle, pas le p, qui
   a démasqué toutes les fausses pistes.
8. **Un garde-fou ne doit jamais s'auto-alimenter.** Le plafond comptait ses propres refus ; le
   frein lisait ses propres décisions. Les deux se verrouillaient tout seuls, en silence.
9. **En cas de doute, un garde-fou LAISSE PASSER.** Un filtre qui bloque quand il ne sait pas finit
   par tout bloquer sans bruit.
10. **Les objections de Mido ont produit tous les vrais résultats de la journée.** Quand il dit
    « c'est pas possible » ou « pourquoi tu tiens à ça », **remesurer** — ne pas défendre.
11. **Avant de classer des données PASSÉES avec une lecture faite MAINTENANT, se demander si la
    lecture aurait pu échouer pour une raison liée au résultat.** 256 comptes-jetons sur 571 sont
    fermés, donc illisibles, et ce groupe a une médiane de **+13,98 %** contre −2,60 % pour les
    lisibles. « Le compte est-il encore lisible ? » est une information du futur.
12. **Un verdict négatif sur une variable CONTAMINÉE ne ferme pas la grandeur qu'elle prétendait
    mesurer.** `expert_detenteurs` (−169 €) condamne `sac1`, pas la concentration.

---

## 7. Les questions ouvertes

1. **Le papier surestime-t-il les GAGNANTS ?** Écart réel−papier de −3,74 pt à 27 tickets, dont
   seulement −0,55 imputable au niveau du coût ; le reste se concentre sur les gros gagnants
   (−6,81 pt). **Non démontré**, il faut ~100 tickets. `calibration_live.py`. **C'est la seule
   raison de laisser le réel tourner.**
2. **L'usine tient-elle ?** Hors échantillon, IPFS +2,92 % contre usine −10,16 %, écart de 13 pts,
   stable sur les deux moitiés. p = 0,098. Gelé, critère à 1 200 tickets.
3. **Le frein tient-il ?** Hors échantillon +2,27 % contre +0,54 %, positif sans ses 3 meilleurs.
   Gelé à 1 500 tickets. Défaut de conception connu : la fenêtre est en NOMBRE, donc elle dépend du
   débit — une fenêtre en temps serait plus propre mais fait moins bien (mesuré).
4. **La trajectoire du stock.** Le seul axe qui ne soit pas une mesure de prix : combien de
   munitions restent au-dessus du marché, et ont-elles déjà été déversées. `stock_collecte.py`
   collecte depuis le 18/09 16h25. Critère écrit d'avance : 300 jetons complets, après le coût de
   2,62 pts, sur des lancements postérieurs, sans les 3 meilleurs, contre un tirage aléatoire de même
   taille. **Risque connu dès le premier échantillon : le stock n'avait bougé sur aucun des deux
   premiers jetons entre 15 et 45 s.** Si c'est général, la piste est close — et c'est utile.
5. **Ce qui est clos** : stop, prise de gain, durée de détention, découpage d'ordre, taille de pool,
   récupération des cautions, régime sur le rendement moyen, gabarits d'image, portefeuille
   créateur. **La concentration des détenteurs n'est PLUS close** (§3.124) : elle n'a jamais été
   testée, seulement `sac1`, qui empilait deux états opposés.
