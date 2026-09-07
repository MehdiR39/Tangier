# Tangier

Deux systèmes vivent dans ce dépôt. Ils ne partagent ni données ni exécution.

## `intel/` — moteur Robinhood Chain (en production)

Achète des lancements de memecoins sur Robinhood Chain (chain 4663) et les revend en
quelques minutes. Règle d'entrée : au moins 27 échanges dans la minute qui suit le premier
échange d'un pool. Règle de sortie : ×2 ou T+5 minutes, la première des deux.

```bash
docker compose up -d intel          # démarrer
docker compose logs -f intel        # suivre
```

Piloté depuis Telegram : `/pnl`, `/positions`, `/closed`, `/orders`, `/solde`,
`/pause`, `/resume`, `/restart`.

- architecture : [docs/INTEL_ARCHITECTURE.md](docs/INTEL_ARCHITECTURE.md)
- installation et variables : [docs/README_INTEL.md](docs/README_INTEL.md)
- la clé privée vit dans `.env`, jamais dans le dépôt ; le passage en réel demande
  deux gestes séparés (clé présente **et** `execution.mode: live`).

## `src/`, `scripts/`, `*.py` à la racine — bot Binance (hérité)

Le bot d'origine : backtests, optimisation, signaux quotidiens sur Telegram. Le conteneur
`tangier_watcher` fait encore tourner `bot_watcher.py`. Ses guides sont dans
[docs/legacy/](docs/legacy/).

## Données

`data/` n'est pas dans le dépôt et contient le jeu de recherche (`research.sqlite`,
5 491 lancements échantillonnés sans biais de survie) et les sauvegardes de la base du
moteur. La base vivante, elle, reste dans un volume Docker : une base SQLite en WAL sur un
montage Windows se corrompt.

## Tests

```bash
docker run --rm -v "$PWD/intel:/app/intel" -v "$PWD/tests:/app/tests" \
  -w /app -e PYTHONPATH=/app tangier-intel:latest python -m pytest -q tests
```
