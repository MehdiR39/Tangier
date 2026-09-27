# Index des scripts de recherche — `intel/research/`

Genere automatiquement le 27/09/2026 a partir du code : ce que lance le gardien (`gardien.COLLECTEURS`), ce qu importent le moteur (`intel/engines/`), la page (`data/carnet_app.py`) et la table (`data/table_std2.py`), et leurs dependances.

**Pourquoi les scripts ne sont pas deplaces dans des sous-dossiers** : le gardien les lance par leur nom de module (`python -m intel.research.<nom>`) et beaucoup s importent entre eux par ce nom. Les deplacer casserait la prod. On les classe ici a la place.

## 1. Tourne en continu (lance par le gardien) — 10 scripts

| script | dernier commit | ce qu il fait |
|---|---|---|
| `carnet_json` | 2026-09-27 | Alimente la page de suivi locale : deux fichiers JSON dans `data/`, relus par Streamlit. |
| `papier_challenger` | 2026-09-27 | LE FLUX SCORE DU CHALLENGER, en direct — la piece qui manque pour pouvoir adopter un modele. |
| `papier_combo` | 2026-09-27 | Test PAPIER vers l avant de la combinaison regime + risque de vidage (§3.85). Lance le 15/09. |
| `papier_gd45` | 2026-09-19 | Instance papier_gd45 de papier_gd_direct (PAPIER_GD_AGE=45, PAPIER_GD_DB=/app/db/papier_gd.sqlite). Module a p… |
| `papier_large` | 2026-09-19 | Instance papier_large de papier_gd_direct (PAPIER_GD_REGLE=large, PAPIER_GD_DB=/app/db/papier_large.sqlite). M… |
| `prix_rapide` | 2026-09-18 | COLLECTE DU PRIX A 1 SECONDE, sur la fenetre ou la position est tenue (35-310 s). |
| `social_collecte` | 2026-09-18 | Collecte de la CONCENTRATION DES DETENTEURS, a l age ou la decision se prendrait (45 s). |
| `stock_collecte` | 2026-09-18 | LA TRAJECTOIRE DU STOCK : qui tient encore de quoi vider le pool, et qui a deja distribue. |
| `v1_enregistreur` | 2026-09-18 | Enregistreur vers l avant : les 60 premieres secondes de chaque nouveau pool, transaction par transaction (15/… |
| `veille_table` | 2026-09-27 | VEILLE DE LA TABLE : chaque ligne a une source, chaque source est surveillee, ou on le sait. |

## 2. Utilise par la prod, la page ou un collecteur (bibliotheque) — 17 scripts

| script | dernier commit | ce qu il fait |
|---|---|---|
| `arbres` | 2026-09-18 | Evaluer un modele LightGBM exporte en JSON, sans LightGBM (le conteneur ne l a pas). |
| `au_plus_bas` | 2026-09-18 | ACHETER AU PLUS BAS, PRE-ENREGISTRE le 18/09/2026 a 08h00 UTC (10h00 Paris). |
| `bas_bande` | 2026-09-18 | AU PLUS BAS + BANDE, PRE-ENREGISTRE le 18/09/2026 a 09h30 UTC (11h30 Paris). |
| `challenger` | 2026-09-27 | LE PROCESS DE MISE A JOUR DU MODELE : quand on reentraine, et comment on decide d adopter. |
| `copie_collecte` | 2026-09-19 | Copier les portefeuilles gagnants : etape 1, relire chaque echange des 15 premieres minutes du pool. |
| `ensemble` | 2026-09-18 | ENSEMBLE DE MODELES, PRE-ENREGISTRE le 17/09 a 23h30 UTC (18/09 01h30 Paris). |
| `entree_75` | 2026-09-18 | ENTREE A T+75 CONTRE T+60, PRE-ENREGISTRE le 18/09/2026 a 07h05 UTC (09h05 Paris). |
| `features` | 2026-09-08 | Event-time features, computed strictly from what was visible at each instant. |
| `frein_taux` | 2026-09-18 | FREIN SUR LE TAUX DE GAGNANTS RECENT, PRE-ENREGISTRE le 18/09/2026 a 15h00 UTC (17h00 Paris). |
| `gardien` | 2026-09-27 | GARDIEN DES COLLECTEURS DE RECHERCHE : les relancer s ils meurent, sans intervention humaine. |
| `labels` | 2026-09-07 | Forward outcomes for each observation. Nothing here may read a price at or before the entry. |
| `papier_gd_direct` | 2026-09-26 | G+D joue en PAPIER, en direct, avec les yeux du bot d aujourd hui (2 s). Gele le 16/09 a 16h20 UTC. |
| `piste_foule` | 2026-09-17 | PISTE PRE-ENREGISTREE : la foule ajoute-t-elle de l information DANS la bande de risque ? |
| `regime` | 2026-09-07 | Is the market's temperature observable BEFORE we bet, and does gating on it help? |
| `social` | 2026-09-12 | Les metadonnees sociales d un lancement : le predicteur le plus fort de la litterature. |
| `usine` | 2026-09-18 | ECARTER LES JETONS FABRIQUES PAR UNE USINE, PRE-ENREGISTRE le 18/09/2026 a 16h00 UTC (18h00 Paris). |
| `v1_traits` | 2026-09-20 | LES VARIABLES DE FLUX D ORDRES, calculees UNE SEULE FOIS ET AU MEME ENDROIT. |

## 3. Analyse ponctuelle (se lance a la main, rien n en depend) — 158 scripts

| script | dernier commit | ce qu il fait |
|---|---|---|
| `absorption` | 2026-09-12 | Un prix qui se stabilise PENDANT que les achats continuent : signal ou pas ? |
| `accord_75` | 2026-09-20 | LE MOTEUR PREND-IL LES MEMES TICKETS QUE LE CARNET ? La derniere verification avant l argent. |
| `accord_bande` | 2026-09-22 | LE `risque` DU MOTEUR EST-IL LE MEME QUE CELUI DU CARNET ? La bande en depend entierement. |
| `analyse` | 2026-09-07 | Descriptive analysis and threshold discovery. No threshold is chosen by hand anywhere here. |
| `arbitre_prod` | 2026-09-20 | CHAQUE CANDIDATE CONTRE LE MOTEUR, SUR LES MEMES TICKETS ET EN EUROS REELS. |
| `backtest` | 2026-09-07 | The 400 EUR book, with costs that can actually be paid. |
| `balayage_tp` | 2026-09-18 | Rejouer le balayage d ENTREE avec la nouvelle SORTIE (prise de gain +25 %), 16/09. |
| `bande_refaite` | 2026-09-20 | OU EST VRAIMENT L ARGENT DANS LE SCORE DE RISQUE ? La bande, redeterminee proprement. |
| `bascule_verdict` | 2026-09-26 | A-T-ON BIEN FAIT DE BASCULER ? L ancien modele contre le nouveau, depuis la bascule. |
| `bitquery` | 2026-09-07 | Continuous launch collection through Bitquery: every pool born in a window, and its trades. |
| `bnb_balayage` | 2026-09-14 | Portefeuille a blanc sur BNB : toutes les combinaisons, jugees avec la meme discipline. |
| `bnb_fiches` | 2026-09-14 | Recuperer les liens sociaux des jetons BNB dont on possede un historique de prix horodate. |
| `bons_etude` | 2026-09-18 | Pourquoi les bons portefeuilles gagnent : etape 1, la table. PROTOCOLE FIGE AVANT TOUT CALCUL (15/09 soir). |
| `bons_historique` | 2026-09-18 | Historique complet des bons portefeuilles (15/09, demande de l operateur : « analyser quand ils rentrent, |
| `bons_verdict` | 2026-09-18 | Pourquoi les bons portefeuilles gagnent : etape 2, le verdict. PROTOCOLE FIGE AVANT DE LIRE LA TABLE (15/09 so… |
| `book_sim` | 2026-09-07 | A whole 400 EUR book replayed over the 45-day history: which exit rules, per position and for the book? |
| `book_sim2` | 2026-09-07 | A whole 400 EUR book replayed over the history, with the exit priced the way this chain really works. |
| `bq_adapter` | 2026-09-07 | Turn the Bitquery collection into the research package's own tables, so nothing downstream changes. |
| `build` | 2026-09-07 | Turn the raw events into observations and outcomes. |
| `bundle_signal` | 2026-09-07 | Can a bundle be told apart from a real launch, one minute in, before any money is spent? |
| `calibration_corrigee` | 2026-09-18 | Le simulateur corrige colle-t-il enfin a l argent reel ? (15/09) |
| `calibration_live` | 2026-09-18 | LE CARNET REEL CONTRE SON EQUIVALENT PAPIER, SUR LES MEMES JETONS. |
| `candidates_verdict` | 2026-09-26 | LES DEUX CANDIDATES GELEES LE 22/09 22h13 — ou en sont-elles ? |
| `carnet_autopsie` | 2026-09-14 | Autopsie des 59 tickets reels : qu est-ce qui separe ceux qui ont gagne de ceux qui ont perdu ? |
| `carnet_sortie` | 2026-09-14 | Apprendre par l experience, sur la seule chose dont on ait assez de donnees : LA SORTIE. |
| `carnet_taille` | 2026-09-14 | Combien miser : la seule decision qu on puisse encore ameliorer avec 59 tickets. |
| `carnet_valider_sortie` | 2026-09-14 | Valider « prendre le gain a x2, sinon sortir a 240 s » sur un jeu qui ne l a pas suggeree. |
| `clean` | 2026-09-07 | Cleaning rules for price series, explicit and counted. Nothing is silently dropped. |
| `coffre` | 2026-09-18 | Le coffre : TOUTES les donnees de recherche, en un seul fichier, sur le disque de l operateur. |
| `collect` | 2026-09-07 | Build the unbiased launch dataset: sample pools, then fetch their raw events. |
| `collect_transfers` | 2026-09-07 | Second pass: ERC20 transfers for every launch that traded, on the unbiased sample. |
| `combinaison_finale` | 2026-09-18 | Combiner les trois effets vrais : regime + risque de vidage + duree (15/09, demande de l operateur). |
| `combinaison_verdict` | 2026-09-18 | Test combine : les petits effets vrais s additionnent-ils jusqu a 50 EUR par jour ? |
| `copie_verdict` | 2026-09-18 | Copier les portefeuilles gagnants : etape 2, le verdict. PROTOCOLE FIGE AVANT DE VOIR UN RESULTAT (15/09). |
| `coupe_circuit` | 2026-09-18 | Coupe-circuit reactif : apres une grosse perte, on s arrete un moment, puis on revient (idee de l operateur, 1… |
| `courbe_collecte` | 2026-09-18 | Relire TOUTE la phase courbe pump.fun sur deux jours (15/09 soir, accord de l operateur : « vas-y »). |
| `courbe_pump` | 2026-09-18 | Le DEUXIEME marche de pump.fun : les courbes libellees en jeton PUMP, pas en SOL (16/09). |
| `courbe_table` | 2026-09-18 | Etude de la COURBE pump.fun, etape 1 : la table des decisions. PROTOCOLE FIGE AVANT TOUT RESULTAT (15/09 soir)… |
| `courbe_verdict` | 2026-09-18 | Etude de la COURBE pump.fun, etape 2 : le verdict. PROTOCOLE FIGE AVANT DE LIRE LA TABLE (15/09 soir). |
| `cout_glissement` | 2026-09-19 | D OU VIENNENT LES 2,38 POINTS « INEXPLIQUES » ? Le taux reellement preleve, jambe par jambe. |
| `cout_optimum` | 2026-09-19 | QUELLE MISE, ET QUELLE REGLE, pour rester en prod en perdant le moins possible ? |
| `cout_registre` | 2026-09-19 | LE REGISTRE DES COUTS : chaque ticket reel decompose au centime, ecrit une fois, jamais refait. |
| `cout_reserve` | 2026-09-19 | LA RESERVE VIRTUELLE EST-ELLE VRAIMENT 17,5845 SOL ? Resolue sur nos propres echanges. |
| `cout_routeur` | 2026-09-19 | PAYONS-NOUS PLUS CHER QUE LES AUTRES ? La commission des tiers contre la notre. |
| `croise` | 2026-09-12 | Croiser TOUT : reseaux sociaux x forme du prix x sortie. Chercher ce qui gagne, pas ce qui survit. |
| `croise_chaine` | 2026-09-14 | Juger un signal sur les prix lus AUX RESERVES, pas chez DexScreener. |
| `decision_75` | 2026-09-18 | DECIDER A 75 s AVEC TOUTE LA PREMIERE MINUTE, contre decider a 45 s avec la moitie. |
| `detenteurs` | 2026-09-18 | Qui detient le stock a l instant ou le moteur achete ? Enregistrement VERS L AVANT. |
| `detenteurs_verdict` | 2026-09-18 | Verdict du filtre « detenteurs » -- regles FIGEES le 15/09 avant d avoir les donnees. |
| `drivers` | 2026-09-14 | Qu est-ce qui fait qu une journee est bonne ou mauvaise ? Mesure, pas intuition. |
| `entree_pic` | 2026-09-14 | Entrons-nous au sommet ? La forme moyenne du prix autour de notre achat. |
| `established` | 2026-09-07 | Technical signals on tokens that already HAVE a market -- the population the user trades. |
| `expert_detenteurs` | 2026-09-18 | EXPERT DETENTEURS, PRE-ENREGISTRE le 18/09 a 01h00 UTC (03h00 Paris). |
| `export_75` | 2026-09-20 | EXPORTE LA FORET 75s AU FORMAT DU MOTEUR -- inversee, verifiee, prete a brancher. |
| `export_etude` | non suivi | SORT LES DONNEES DE L ETUDE hors du conteneur, pour qu un notebook puisse les lire. |
| `features_lancement` | 2026-09-12 | La table de variables d un lancement, batie sur la litterature et non sur l intuition. |
| `filtre_jour` | 2026-09-14 | Le filtre « 3 signes », explique et chiffre jour par jour. |
| `final` | 2026-09-07 | One command, one consistent build, one file: the complete study from the raw events. |
| `final_bq` | 2026-09-07 | One command for the continuous (Bitquery) dataset: snapshot → adapter → build → layered test → file. |
| `financeurs` | 2026-09-18 | Qui a finance le portefeuille qui detient le sac ? (recidive au niveau du FINANCEUR) |
| `flux` | 2026-09-12 | Le flux acheteur/vendeur est-il un signal ? La version en ARGENT, pas en nombre. |
| `flux_fraicheur` | 2026-09-19 | A PARTIR DE QUAND l index des transactions est-il complet ? Le retard, mesure. |
| `flux_latence` | 2026-09-19 | PEUT-ON aller chercher le flux d ordres A 45 s ? Deux questions, pas une. |
| `flux_lesquelles` | 2026-09-19 | QUELLES variables de flux portent le signal -- et lesquelles le moteur peut-il voir a 45 s ? |
| `flux_severite` | 2026-09-19 | COMBIEN faut-il en garder ? La severite du tri, du plus laxiste au plus severe. |
| `flux_severite_t` | 2026-09-19 | La severite, jugee correctement : en ECARTS-TYPES, pas en euros bruts. |
| `flux_tronque` | 2026-09-19 | LE SIGNAL TIENT-IL SUR LA VUE TRONQUEE, celle qu on aura vraiment a 45 s ? |
| `foret75_analyse` | 2026-09-19 | ANALYSE DU MODELE « FORET 75s top 5 % » : ce qu il est, ce qu il prevoit, sur quoi il s appuie. |
| `foret75_marche` | 2026-09-19 | REENTRAINER LA FORET 75s AMELIORE-T-IL, COMME POUR CELLE A 45 s ? |
| `foret_avec_cout` | 2026-09-19 | LA METHODE REENTRAINEE FAIT-ELLE MIEUX AVEC LA VARIABLE DE COUT ? Et avec le VRAI cout ? |
| `foret_cible` | 2026-09-20 | LA CIBLE EST-ELLE LE DEFAUT ? « ne pas s effondrer » contre « etre gagnant », toutes choses egales. |
| `foret_sans_coffre` | 2026-09-19 | LA FORET TRIE-T-ELLE MIEUX SANS LA TAILLE DU COFFRE ? Le test que le carnet reel a impose. |
| `foret_vidage_plus` | 2026-09-19 | AMELIORER LA FORET DE VIDAGE : lui donner le FLUX D ORDRES, pas plus de variables de prix. |
| `frein_bande` | 2026-09-18 | FREIN x BANDE, PRE-ENREGISTRE le 18/09/2026 a 16h30 UTC (18h30 Paris). |
| `gabarit` | 2026-09-18 | LES MEMES ESCROCS REFONT LES MEMES JETONS : detecter le GABARIT et l eviter. |
| `grand_balayage` | 2026-09-18 | Grand balayage, etape 2 : chercher partout, ne croire que ce qui survit a trois tranches. |
| `grand_balayage_long` | 2026-09-18 | Grand balayage, etape 5 : les horizons LONGS (minutes a heures), sur le suivi DexScreener. |
| `grand_balayage_ml` | 2026-09-18 | Grand balayage, etape 3 : l apprentissage automatique combine toutes les variables a la fois. |
| `grand_balayage_sorties` | 2026-09-18 | Grand balayage, etape 4 : les sorties dynamiques (prise de gain, stop, detention max). |
| `grand_balayage_table` | 2026-09-18 | Grand balayage, etape 1 : la table (pool x moment de decision), prix CORRIGES, couts reels. |
| `hausse_confirmee` | 2026-09-18 | « Acheter la hausse confirmee » -- test fige le 15/09 avant calcul. |
| `image_collecte` | 2026-09-18 | L IMAGE DU JETON DIT-ELLE QUELQUE CHOSE ? Collecte et mesure, sur l HOTE. |
| `journee` | 2026-09-18 | Ou en est la journee ? Une commande, les chiffres du jour, convention EXECUTABLE. |
| `latence_75` | 2026-09-20 | PEUT-ON DECIDER A 75 s ? La seule question qui commande tout le reste : la LATENCE. |
| `layers` | 2026-09-07 | The layered test: A all → B security → C + momentum → D + organic flow. Judged on future data. |
| `liens_collecte` | 2026-09-18 | UN SITE WEB REND-IL UN JETON PLUS SERIEUX ? La question de Mido, 18/09 au soir. |
| `liens_verdict` | 2026-09-18 | UN SITE DECLARE REND-IL UN JETON MEILLEUR A ACHETER ? Critere ECRIT AVANT de lire la table. |
| `macro` | 2026-09-07 | Does the wider market's mood predict how generous launches are? ETH and BTC as the regime gauge. |
| `manque_75` | 2026-09-22 | DE QUELLES VARIABLES LE MOTEUR PEUT-IL SE PASSER ? On mesure avant de coder. |
| `marche_avant` | 2026-09-18 | MARCHE AVANT : reentrainer toutes les 6 heures, trier fort, additionner TOUTES les fenetres. |
| `marche_avant_plus` | 2026-09-18 | POUSSER LA MODELISATION -- a l interieur de la marche avant, jamais a cote. |
| `marche_avant_tout` | 2026-09-18 | UNE FORET SUR TOUT : les 107 variables de toutes les sources, en marche avant. |
| `nft_collecte` | 2026-09-14 | Collecter les VENTES NFT avec leur rang de rarete. N ACHETE RIEN. |
| `nft_traits` | 2026-09-14 | Recuperer les TRAITS de chaque piece vendue, pour calculer la rarete nous-memes. |
| `nft_verdict` | 2026-09-14 | La rarete se paie-t-elle a la revente ? Verdict NFT. |
| `ou_va_l_argent` | 2026-09-18 | OU VA L ARGENT ? Le seul acteur qu on n avait pas compte : celui qui RETIRE la liquidite. |
| `paperbook` | 2026-09-07 | Mark the paper book to market: what every dry-run T+1 entry is worth now, honestly. |
| `papier_gd` | 2026-09-16 | Test PAPIER vers l avant de la regle G+D (§3.95). Gele le 16/09 a 15h40 UTC. |
| `pause_partout` | 2026-09-20 | LA PAUSE, APPLIQUEE AU CARNET REEL — et ensuite a toutes les pistes prometteuses. |
| `pause_verdict` | 2026-09-20 | LA PAUSE FAIT-ELLE MIEUX QUE LE HASARD, AVEC LES DONNEES D AUJOURD HUI ? |
| `pools_propres` | 2026-09-14 | Assainir les donnees de pool AVANT toute mesure : quel jeton en face, et quelle offre. |
| `premiere_minute` | 2026-09-12 | Que se passe-t-il pendant la premiere minute, et est-ce que ca annonce la suite ? |
| `premieres_secondes` | 2026-09-18 | Qui a achete gros dans les premieres secondes du pool ? Reconstruction sur l historique. |
| `propre_verdict` | 2026-09-14 | Le filtre « 3 signes » : verdict unique, en pesant toutes les preuves ensemble. |
| `propre_x_tg` | 2026-09-14 | Le filtre « trop propre » croise avec Telegram, sur donnees assainies. |
| `queue_lourde` | 2026-09-22 | ATTRAPE-T-ELLE LES GROS COUPS PLUS SOUVENT QUE LE HASARD ? Le bon test sur un marche a queue lourde. |
| `qui_achete` | 2026-09-18 | QUI SE FAIT PIEGER ? La question de Mido, posee le 18/09 au soir. |
| `qui_gagne` | 2026-09-18 | QUI PIEGE QUI ? Le SOLDE de chaque acteur, pas sa presence. |
| `qui_gagne_vraiment` | 2026-09-18 | QUI GAGNE VRAIMENT ? Le solde COMPLET, ce qui reste sur les bras inclus. |
| `real_buyers` | 2026-09-08 | Does counting the real buyers separate the rugs on Robinhood Chain, as it does on Solana? |
| `recidive` | 2026-09-14 | Le passe d un createur predit-il son prochain jeton ? |
| `reentrainer` | 2026-09-18 | REENTRAINER `risque` JUSQU A UNE HEURE DONNEE, ET JUGER APRES : le modele en service vieillit-il ? |
| `reentrainer_ensemble` | 2026-09-18 | REENTRAINER L ENSEMBLE DE 12 ET LA FORET JUSQU A UNE HEURE DONNEE, ET JUGER APRES. |
| `refaire_corrige` | 2026-09-18 | Refaire les tests qui comptent, avec les prix CORRIGES (15/09). |
| `regime_live` | 2026-09-07 | Can the market's temperature be read from the chain's own launch activity, ahead of time? |
| `replay_paper` | 2026-09-07 | Recompute the paper book from the recorded prices, so it measures the rule and not the engine. |
| `report` | 2026-09-07 | The whole study, end to end, answering the fourteen questions and ending on a verdict. |
| `rug_signal` | 2026-09-08 | Le retrait de liquidite se voit-il venir dans les echanges qui le precedent ? |
| `sac_diagnostic` | 2026-09-18 | `sac1` MELANGE DEUX ETATS OPPOSES : ce que ca fait au verdict d `expert_detenteurs`. |
| `sacs_verdict` | 2026-09-18 | Verdict historique : ecarter les jetons ou un portefeuille a recu un gros « sac » a la migration. |
| `schema` | 2026-09-07 | Tables for the research dataset. Own file, so the live pipeline cannot be affected. |
| `selectivite` | 2026-09-18 | SELECTIVITE, CALIBRATION, CIBLE : ce que vaut un classement REEL en argent. |
| `sequences` | 2026-09-14 | Y a-t-il vraiment des SEQUENCES, ou notre oeil en fabrique-t-il ? |
| `series` | 2026-09-18 | Les bons et les mauvais trades arrivent-ils par SERIES ? (question de l operateur, 15/09) |
| `size_ladder` | 2026-09-07 | What does a bigger ticket actually cost? Ask the chain, on the pools the book is buying now. |
| `sol_aller_retour` | 2026-09-09 | Ce qu on peut VRAIMENT vendre, a notre taille, contre ce que le marche affiche. |
| `sol_confirm` | 2026-09-08 | La confirmation en deuxieme minute marche-t-elle aussi sur Solana ? |
| `sol_entree` | 2026-09-12 | Quels lancements acheter ? Balayage des regles d entree sur donnees propres. |
| `sol_exit_sweep` | 2026-09-09 | La regle de sortie en production n a jamais ete simulee telle qu elle est. |
| `sol_mcap` | 2026-09-08 | La capitalisation a l entree predit-elle le resultat ? |
| `sol_ml` | 2026-09-09 | Le jeu d apprentissage, et le garde-fou qui empeche de s en servir trop tot. |
| `sol_objectif` | 2026-09-12 | L objectif de sortie est-il regle trop haut ? |
| `sol_recherche` | 2026-09-09 | Chercher une regle gagnante honnetement : choisir sur la premiere moitie, juger sur la seconde. |
| `sol_regime` | 2026-09-09 | Le marche donne-t-il encore ce que la regle suppose ? Mesure suivie dans le temps. |
| `sol_sortie` | 2026-09-09 | Chercher l avantage du cote de la SORTIE, la ou les mesures disent qu il se trouve. |
| `sol_stoploss` | 2026-09-08 | Un stop de perte sauverait-il les lignes qui s effondrent ? |
| `sol_trailing` | 2026-09-08 | Un stop suiveur ferait-il mieux que l objectif fixe a x2 ? |
| `solana_backtest` | 2026-09-08 | Backtest the Solana T+1 book on what was actually observed, and choose its thresholds. |
| `solana_retro` | 2026-09-07 | Answer tonight instead of tomorrow: take Solana launches already hours old and read both ends. |
| `solana_watch` | 2026-09-09 | Watch Solana launches and record what becomes of them. Observation only: it never trades. |
| `sortie_age` | 2026-09-20 | A QUEL AGE FAUT-IL VENDRE ? Le meme ticket, mesure a six sorties. |
| `sortie_fine` | 2026-09-12 | Le balayage des sorties, refait sur des donnees qui ne mentent pas. |
| `sorties_flux` | 2026-09-18 | Sortir sur le FLUX plutot qu a l heure fixe, dans le sous-ensemble « tendance + pool non gonfle » (16/09). |
| `sortir_quand` | 2026-09-18 | SORTIR PLUS TOT PAIE-T-IL ? La seule facon de le savoir sans se mentir. |
| `survie` | 2026-09-12 | Acheter la survie, pas la naissance : que vaut un lancement qui a tenu une heure ? |
| `survivants` | 2026-09-18 | LES SURVIVANTS : trader les jetons qui ont passe une heure, la ou le peage est petit. |
| `t1_variants` | 2026-09-08 | Rejoue toutes les variantes de la regle T+1 sur les mêmes lancements, hors ligne. |
| `tax_ceiling` | 2026-09-07 | Where should the buy-tax ceiling sit? Replay the buys it refused and see what they were worth. |
| `tendance_en_ligne` | 2026-09-18 | Choisir la fenetre de tendance EN LIGNE, sans que je la regle a la main (16/09, idee de l operateur). |
| `tout_balayage` | 2026-09-18 | LE BALAYAGE LARGE : toutes les variables, seules puis par paires, sur toutes les cibles. |
| `tout_table` | 2026-09-20 | LA TABLE UNIQUE : une ligne par ticket, TOUTES les variables de TOUTES les sources. |
| `usure` | 2026-09-13 | L usure : savoir que la strategie meurt AVANT qu elle coute cher. |
| `v1_retard` | 2026-09-20 | A QUEL AGE `v1_enregistreur` A-T-IL ECRIT CHAQUE POOL ? Le moteur pourra-t-il le LIRE a 75 s ? |
| `v1_verdict` | 2026-09-18 | Verdict de la piste « transactions version 1 », PRE-ENREGISTRE le 15/09 a 23h (journal §3.90), avant toute don… |
| `variance` | 2026-09-14 | Pourquoi 53 % de gagnants ne donne PAS 53 % de bonnes journees. |
| `veille_derive` | 2026-09-23 | SURVEILLE LA DERIVE, ET NE RE-OPTIMISE QU A DES CONDITIONS ECRITES D AVANCE. |
| `verdict_ensemble` | 2026-09-19 | VERDICT DU GEL DU 18/09 01h30 : la loterie des tirages coutait-elle de l argent ? |
| `verif_long_ml` | 2026-09-18 | Verification du SEUL candidat qui a passe tri et test : LightGBM, detention 8 h, top 10 % (15/09). |

## 4. Arrete le 27/09 (menage) — base conservee — 9 scripts

| script | dernier commit | ce qu il fait |
|---|---|---|
| `foret75_carnet` | 2026-09-20 | FORET 75s REENTRAINEE : la recette du gel 75s, mais les poids ET LE SEUIL se refont toutes les 6 h. |
| `foret75_iso` | 2026-09-20 | FORET 75s ISO-MOTEUR : le meme modele gele, prive de ce que le moteur ne saura pas produire. |
| `foret_flux` | 2026-09-19 | FORET DE VIDAGE NOURRIE AU FLUX D ORDRES, gelee -- papier, zero euro. |
| `foret_gagnant` | 2026-09-20 | FORET GAGNANT 20 % : la bonne question, posee au meme instant que le moteur. |
| `foret_gel` | 2026-09-18 | FORET DE GAIN, 25 VARIABLES, TOP 5 % -- GELEE le 18/09/2026 a 23h10 Paris. Papier, zero euro. |
| `foret_gel75` | 2026-09-18 | Le gel de la foret a 75 s : meme regle, meme critere que foret_gel, decision avec toute la premiere |
| `foret_marche` | 2026-09-19 | FORET REENTRAINEE 6h : une RECETTE gelee, des poids qui se remettent a jour. |
| `papier_gd30` | 2026-09-19 | Instance papier_gd30 de papier_gd_direct (PAPIER_GD_AGE=30, PAPIER_GD_DB=/app/db/papier_gd30.sqlite). Module a… |
| `prod_reentraine` | 2026-09-20 | REENTRAINE LE MODELE DE PRODUCTION, toutes les 6 h, au format que le moteur sait lire. |
