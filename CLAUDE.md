# Tangier — à lire avant toute action

Ce fichier est chargé automatiquement au début de chaque session. Il existe pour une raison
précise, énoncée par Mido le 20/09/2026 :

> *« Ma consigne était claire : on fait beaucoup de choses, tu dois donc tout écrire — les pistes,
> les analyses, les résultats, ce qui est en train d'être fait et ce qui est fait — et tu dois lire
> ce doc avant de faire quoi que ce soit. Toute demande de ma part, toute initiative de ta part doit
> être précédée de la lecture de ce doc. C'est la dernière fois que je dis ça. »*

Il l'avait déjà dit. Ce qui a échoué n'est pas la bonne volonté, c'est le format : `JOURNAL_RECHERCHE.md`
fait 8 000 lignes en ordre chronologique, donc « le lire avant chaque action » était impraticable,
donc ça ne se faisait pas. Résultat le 20/09 : j'ai **refait §3.156 de la veille**, moins bien, et
annoncé comme une découverte un « coût inexpliqué de 2,44 % » qui était décomposé au lamport depuis
24 heures. Et le calcul des 50 €/jour de §3.120 était resté à 40 tickets/jour pendant deux jours.

## La règle, en deux lignes

1. **AVANT toute action** — toute question de Mido, toute initiative de ma part, tout test, tout
   script : lire **`JOURNAL_RECHERCHE.md`, section 0 « ÉTAT COURANT »**. Elle tient en une page.
2. **APRÈS tout résultat** — mettre à jour la section 0 *dans le même geste* que l'analyse.
   Une mesure qui n'y est pas n'existera pas la prochaine fois.

La section 0 contient : ce qui est établi et ne se remesure pas · la piste ouverte qui vaut le plus ·
ce qui tourne et son échéance · ce qui est mort · les erreurs de méthode qui ont coûté le plus.

## Les trois questions à se poser avant d'écrire une ligne de code

1. **Est-ce que c'est déjà mesuré ?** → section 0.1, puis chercher dans le journal.
2. **Est-ce que la réponse est déjà dans les données produites ?** `data/carnet.json` contient
   déjà les 30 stratégies avec leur niveau, leur écart au témoin et leur bruit. Ce qui manque est
   presque toujours de la **lecture**, pas de la collecte.
3. **Est-ce que ça fait avancer la piste de la section 0.2 ?** Si non, c'est probablement un
   détour.

## Ce qui ne se fait jamais sans l'accord explicite de Mido

- Arrêter, mettre en pause ou brider le moteur en production. *« Laisse tourner, n'arrête rien sans
  que je te dise »* (18/09). Et : **proposer d'améliorer, jamais d'arrêter** (20/09).
- Changer le modèle en production, la mise, ou un seuil d'entrée.
- Toucher à un gel en cours : son critère est écrit d'avance, le laisser aller au bout est ce qui
  lui donne sa valeur.

Un carnet papier à zéro euro, en revanche, est un **arbitrage de recherche** : c'est à moi de
trancher, pas à lui. Ne pas lui demander une permission pour quelque chose de gratuit et réversible.

## Comment rendre compte

- **Le NIVEAU en euros d'abord**, le contraste au témoin ensuite. Un contraste ne paie rien :
  `VIDAGE 80 %` a le meilleur σ du projet (+3,06) et perd 0,204 € du ticket.
- **P&L par jour calendaire**, jamais en 24 h glissantes.
- **Tout chiffre avec son n et son bruit.** Un chiffre qui va bouger se donne avec l'amplitude
  dans laquelle il bougera, ou pas du tout.
- Un compte rendu **par conclusion vérifiée**, pas par étape.
