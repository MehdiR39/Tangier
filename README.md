# Tangier

Trading automatique de jetons fraîchement lancés sur **Solana (PumpSwap)**, en argent réel, avec
un moteur qui décide en 45 secondes, un carnet papier qui mesure chaque règle sans acheter, et une
page de suivi.

| | |
|---|---|
| **En production** | deux stratégies à 20 € : **BANDE + PAUSE** et **G+D** |
| **Objectif** | ~50 € par jour |
| **État courant** | `JOURNAL_RECHERCHE.md`, section 0 — à lire avant toute action |
| **Branches git** | `solana` = ce projet (prod Solana) · `main` = le scanner d actions, qui tourne depuis `C:	angier_L` |
| **Suivi** | page Streamlit : http://192.168.1.191:8502 (maison) · http://100.116.248.62:8502 (Tailscale) |

## Où lire quoi

| je veux… | lire |
|---|---|
| comprendre comment ça marche | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — schémas du flux, des carnets papier, de la mise à jour du modèle, carte des dossiers |
| démarrer, vérifier, redémarrer, dépanner | [`docs/EXPLOITATION.md`](docs/EXPLOITATION.md) |
| savoir ce qui est mesuré, décidé, en cours | [`JOURNAL_RECHERCHE.md`](JOURNAL_RECHERCHE.md), section 0 |
| trouver un script de recherche | [`docs/RECHERCHE_INDEX.md`](docs/RECHERCHE_INDEX.md) — 194 scripts classés par rôle |
| les règles de travail | [`CLAUDE.md`](CLAUDE.md) |
| les anciens projets | `archive/` — bot ML Binance (février), étude d'allocation (août) |

## Démarrage rapide

```bash
docker compose up -d intel                      # le moteur
docker inspect -f '{{.State.Health.Status}}' tangier-intel
scripts\lancer_carnet.cmd                       # la page (normalement lancée par une tâche planifiée)
```

Secrets et points d'accès : `.env` (modèle : `.env.example`). La clé privée n'en sort jamais.

## Organisation

```text
config/intel.yaml   tous les réglages          intel/        le code du moteur
data/               page, modèles, recherche   logs/         journaux
tests/              tests du moteur            docs/         documentation
scripts/            lanceurs Windows           archive/      anciens projets
```
