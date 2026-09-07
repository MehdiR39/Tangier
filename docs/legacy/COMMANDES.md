# Tangier Trading Bot - Guide Complet des Commandes

## Table des matières

1. [Configuration initiale](#configuration-initiale)
2. [Ordre d'exécution recommandé](#ordre-dexécution-recommandé)
3. [Commandes détaillées](#commandes-détaillées)
4. [Fichiers de sortie](#fichiers-de-sortie)
5. [Dépannage](#dépannage)

---

## Configuration initiale

### Prérequis

```bash
# Installer les dépendances
pip install lightgbm xgboost scikit-learn imbalanced-learn python-binance python-dotenv optuna

# Créer un fichier .env avec vos clés Binance (optionnel pour données réelles)
# À la racine du projet :
BINANCE_API_KEY=votre_clé_api
BINANCE_API_SECRET=votre_secret_api
```

### Configuration du projet

Éditez `config/config.py` pour modifier :

- **SYMBOLS** : Cryptos à tester (ex: `["BTCUSDT", "ETHUSDT", "SOLUSDT"]`)
- **BINANCE_INTERVAL** : Timeframe (ex: `"4h"`, `"2h"`, `"1h"`)
- **TEST_START_DATE** : Date de début du test (ex: `"2025-10-01"`)
- **CONFIDENCE_THRESHOLD** : Seuil de confiance pour les signaux (ex: `0.45`)
- **STOP_LOSS_PCT** : Stop loss en % (ex: `0.05` = 5%)
- **TAKE_PROFIT_PCT** : Take profit en % (ex: `0.10` = 10%)

---

## Ordre d'exécution recommandé

```
1. python main.py                    ← Test rapide (1 crypto, 1 modèle)
2. python compare_models.py          ← Comparer 5 modèles
3. python run_portfolio.py           ← Portfolio multi-crypto
4. python optimize_strategy.py       ← Optimiser les paramètres
```

---

## Commandes détaillées

### 1. Test simple (main.py)

**Objectif** : Vérifier que tout fonctionne avec un seul modèle sur une seule crypto.

#### Commandes de base

```bash
# Test sur le symbole par défaut (AVAXUSDT) avec LGBM
python main.py

# Test sur un symbole spécifique
python main.py --symbol BTCUSDT

# Test sur plusieurs symboles
python main.py --symbols BTCUSDT,ETHUSDT,SOLUSDT

# Test avec un modèle spécifique
python main.py --model xgboost

# Combiner symbole et modèle
python main.py --symbol BTCUSDT --model xgboost
```

#### Modèles disponibles

- `lgbm` (LightGBM) - défaut, rapide et performant
- `xgboost` (XGBoost) - plus lent mais souvent meilleur
- `random_forest` (Random Forest) - simple mais moins performant
- `logistic_regression` (Logistic Regression) - baseline rapide
- `neural_network` (Neural Network) - complexe, peut overfitter

#### Résultats attendus

```
Step 1: Fetching data...
  Data: 13597 candles (2023-01-01 to 2026-02-07)

Step 2: Engineering features...
  Features: 50 columns, 13318 rows after NaN removal

Step 3: Preparing training data...
  X shape: (13313, 20), y shape: (13313,)

Step 4: Training LGBM model...
  Train: 10650 samples (2023-01-01 to 2025-10-01)
  Test:  2663 samples (2025-10-01 to 2026-02-07)

Step 5: Generating signals on test data...
  Signals: Buy=267, Hold=2210, Sell=186

Step 6: Backtesting...
  Return: 12.53% | B&H: -47.46% | Sharpe: 1.45 | MaxDD: 9.94%
  Trades: 7 | Win Rate: 42.9%

Step 7: Saving visualizations...
  Backtest chart saved: results/AVAXUSDT_lgbm_backtest.png
```

#### Fichiers générés

- `results/AVAXUSDT_lgbm_backtest.png` - Graphique 4 panneaux (prix + ordres, équité, drawdown, P&L)
- `logs/main_*.log` - Fichier log détaillé

---

### 2. Comparaison de modèles (compare_models.py)

**Objectif** : Tester les 5 modèles sur chaque crypto et identifier le meilleur.

#### Commandes de base

```bash
# Comparer les 5 modèles sur le symbole par défaut
python compare_models.py

# Comparer sur plusieurs symboles
python compare_models.py --symbols BTCUSDT,ETHUSDT,SOLUSDT,AVAXUSDT,XRPUSDT

# Comparer avec un nombre de trials personnalisé (pour l'optimisation interne)
python compare_models.py --symbols BTCUSDT,ETHUSDT
```

#### Résultats attendus

**Console output** :

```
======================================================================
BEST MODEL PER CRYPTO (by Sharpe ratio)
======================================================================
Crypto       Model                    Return %   Sharpe   Win Rate
----------------------------------------------------------------------
BTCUSDT      xgboost                     -5.70    -0.15      36.4%
ETHUSDT      neural_network             +13.62     0.52      48.7%
SOLUSDT      lgbm                        +2.02     0.21      44.4%
AVAXUSDT     neural_network             +25.55     0.89      47.6%
XRPUSDT      logistic_regression        +20.17     0.96      62.5%
======================================================================

Evaluation Period: 2025-10-01 to 2026-02-07 (129 days)
```

#### Fichiers générés

- `results/model_comparison_results.csv` - Tableau complet avec toutes les métriques (25 lignes = 5 modèles × 5 cryptos)
- `results/{SYMBOL}_model_comparison.png` - Barres comparatives (Return, Sharpe, Win Rate, etc.)
- `results/{SYMBOL}_equity_comparison.png` - Courbes d'équité superposées
- `results/{SYMBOL}_{best_model}_backtest.png` - Graphique détaillé du meilleur modèle uniquement
- `logs/compare_models_*.log` - Fichier log

**Structure du CSV** :

```
symbol,model,return,sharpe_ratio,win_rate,max_drawdown,num_trades,avg_trade_return,composite_score
BTCUSDT,lgbm,-20.6,-0.92,30.8,37.57,13,-1.6,0.123
BTCUSDT,xgboost,-5.7,-0.15,36.4,26.95,11,-0.32,0.456
...
```

---

### 3. Portfolio multi-crypto (run_portfolio.py)

**Objectif** : Simuler un portfolio diversifié avec le meilleur modèle pour chaque crypto.

#### Commandes de base

```bash
# Portfolio avec allocation égale (défaut)
python run_portfolio.py

# Portfolio avec allocation égale sur symboles spécifiques
python run_portfolio.py --symbols BTCUSDT,ETHUSDT,SOLUSDT,AVAXUSDT,XRPUSDT

# Portfolio avec allocation pondérée par le risque
python run_portfolio.py --allocation risk_parity

# Portfolio avec allocation pondérée par la performance
python run_portfolio.py --allocation performance_weighted

# Combiner symboles et allocation
python run_portfolio.py --symbols BTCUSDT,ETHUSDT,SOLUSDT --allocation performance_weighted
```

#### Méthodes d'allocation

| Allocation             | Description                              | Quand l'utiliser       |
| ---------------------- | ---------------------------------------- | ---------------------- |
| `equal`                | 33.3% par crypto (3 cryptos)             | Par défaut, simple     |
| `risk_parity`          | Plus de capital sur les moins risquées   | Minimiser le drawdown  |
| `performance_weighted` | Plus de capital sur les meilleurs Sharpe | Maximiser le rendement |

#### Résultats attendus

**Console output** :

```
STEP 1: Finding best models...
  BTCUSDT: Best model = xgboost (Sharpe: -0.15)
  ETHUSDT: Best model = neural_network (Sharpe: 0.52)
  SOLUSDT: Best model = lgbm (Sharpe: 0.21)

STEP 2: Allocating capital...
Capital Allocation (equal):
  BTCUSDT: 0.3333 (33.3%) - Model: xgboost
  ETHUSDT: 0.3333 (33.3%) - Model: neural_network
  SOLUSDT: 0.3333 (33.3%) - Model: lgbm

STEP 3: Running portfolio backtest...
  --- BTCUSDT with XGBOOST (capital: 0.3333) ---
    Return: -5.70%, Sharpe: -0.15
  --- ETHUSDT with NEURAL_NETWORK (capital: 0.3333) ---
    Return: +13.62%, Sharpe: 0.52
  --- SOLUSDT with LGBM (capital: 0.3333) ---
    Return: +2.02%, Sharpe: 0.21

STEP 4: Generating visualizations...
  Portfolio chart saved: results/portfolio_equal.png

STEP 5: Exporting results...
  Portfolio results saved: results/portfolio_equal_results.csv

======================================================================
PORTFOLIO RESULTS
======================================================================
   Symbol          Best Model  Allocated Capital  Return %  Sharpe  Max DD %
  BTCUSDT          xgboost               0.3333    -5.70    -0.15    26.95
  ETHUSDT      neural_network           0.3333   +13.62     0.52    31.20
  SOLUSDT                lgbm            0.3333    +2.02     0.21    32.27
PORTFOLIO               equal             1.0000    +3.31     0.23     8.50
======================================================================

Portfolio Return:    +3.31%
Buy & Hold Return:   -11.42%
Outperformance:      +14.73%
Portfolio Sharpe:    0.23
Portfolio Max DD:    8.50%
Allocation Method:   equal
Evaluation Period:   2025-10-01 to 2026-02-07 (129 days)
```

#### Fichiers générés

- `results/portfolio_{allocation}.png` - Graphique principal du portfolio (4 panneaux)
- `results/portfolio_{allocation}_results.csv` - Résultats détaillés
- `logs/portfolio_*.log` - Fichier log

---

### 4. Optimisation des paramètres (optimize_strategy.py)

**Objectif** : Trouver les meilleurs paramètres (stop loss, take profit) pour maximiser le Sharpe ratio.

#### Commandes de base

```bash
# Optimisation complète (hyperparamètres + walk-forward)
python optimize_strategy.py

# Optimiser un symbole spécifique
python optimize_strategy.py --symbol BTCUSDT

# Optimiser plusieurs symboles
python optimize_strategy.py --symbols BTCUSDT,ETHUSDT

# Nombre d'essais (défaut: 50)
python optimize_strategy.py --trials 100

# Désactiver l'optimisation des hyperparamètres
python optimize_strategy.py --no-hyperopt

# Désactiver la validation walk-forward
python optimize_strategy.py --no-wf

# Combiner plusieurs options
python optimize_strategy.py --symbol XRPUSDT --trials 150 --no-wf
```

#### Résultats attendus

**Console output** :

```
STEP 1: Optimizing hyperparameters...
  Trial 1/50: SL=0.04, TP=0.08 → Sharpe=0.45
  Trial 2/50: SL=0.06, TP=0.12 → Sharpe=0.52
  ...
  Trial 50/50: SL=0.05, TP=0.10 → Sharpe=0.89

  Best parameters found:
    Stop Loss: 5.5%
    Take Profit: 11.2%
    Sharpe Ratio: 0.89

STEP 2: Walk-forward validation...
  Period 1 (2025-10-01 to 2025-11-01): Sharpe=0.87
  Period 2 (2025-11-01 to 2025-12-01): Sharpe=0.91
  Period 3 (2025-12-01 to 2026-01-01): Sharpe=0.85
  Period 4 (2026-01-01 to 2026-02-07): Sharpe=0.93

  Average Sharpe (Walk-Forward): 0.89

STEP 3: Final backtest with optimized parameters...
  Return: 15.23% | B&H: -47.46% | Sharpe: 0.89 | MaxDD: 12.5%
  Trades: 12 | Win Rate: 58.3%

Evaluation Period: 2025-10-01 to 2026-02-07 (129 days)
```

#### Fichiers générés

- `results/{symbol}_optimization_results.png` - Courbes d'optimisation
- `results/{symbol}_walk_forward.png` - Résultats walk-forward
- `results/{symbol}_optimized_backtest.png` - Backtest avec paramètres optimisés
- `results/optimization_summary.csv` - Résumé des optimisations
- `logs/optimize_*.log` - Fichier log

---

## Fichiers de sortie

### Dossier `results/`

| Fichier                              | Généré par                 | Contenu                                                   |
| ------------------------------------ | -------------------------- | --------------------------------------------------------- |
| `{symbol}_{model}_backtest.png`      | main.py, compare_models.py | Graphique 4 panneaux (prix+ordres, équité, drawdown, P&L) |
| `{symbol}_model_comparison.png`      | compare_models.py          | Barres comparatives des 5 modèles                         |
| `{symbol}_equity_comparison.png`     | compare_models.py          | Courbes d'équité superposées                              |
| `model_comparison_results.csv`       | compare_models.py          | Tableau complet (25 lignes)                               |
| `portfolio_{allocation}.png`         | run_portfolio.py           | Graphique portfolio (4 panneaux)                          |
| `portfolio_{allocation}_results.csv` | run_portfolio.py           | Résultats détaillés du portfolio                          |
| `{symbol}_optimization_results.png`  | optimize_strategy.py       | Courbes d'optimisation                                    |
| `{symbol}_walk_forward.png`          | optimize_strategy.py       | Résultats walk-forward                                    |
| `{symbol}_optimized_backtest.png`    | optimize_strategy.py       | Backtest optimisé                                         |
| `optimization_summary.csv`           | optimize_strategy.py       | Résumé des optimisations                                  |

### Dossier `logs/`

Fichiers log détaillés pour chaque exécution (format: `{script}_{timestamp}.log`)

---

## Interprétation des métriques

| Métrique             | Formule                                             | Interprétation                        |
| -------------------- | --------------------------------------------------- | ------------------------------------- |
| **Return %**         | (Final Value - Initial Value) / Initial Value × 100 | Rendement total en %                  |
| **B&H Return %**     | Rendement Buy & Hold                                | Benchmark (faire rien)                |
| **Outperformance %** | Return - B&H Return                                 | Surperformance vs benchmark           |
| **Sharpe Ratio**     | (Return - Risk-Free Rate) / Std Dev                 | Rendement ajusté au risque (>0.5 bon) |
| **Max Drawdown %**   | Perte maximale depuis le pic                        | Pire scénario (plus bas = mieux)      |
| **Win Rate %**       | Trades gagnants / Total trades                      | % de trades profitables               |
| **Profit Factor**    | Gains totaux / Pertes totales                       | >1.5 est bon, >2.0 excellent          |
| **Composite Score**  | 60% Return + 30% Sharpe + 10% Win Rate              | Score global pour comparaison         |

---

## Dépannage

### Erreur : "Could not fetch from Binance"

**Cause** : Vous êtes en France ou région bloquée par Binance.

**Solutions** :

1. Utiliser un VPN pour contourner le blocage
2. Créer un fichier `.env` avec vos clés API Binance
3. Télécharger les données historiques et les sauvegarder en CSV

### Erreur : "Input X contains infinity or a value too large"

**Cause** : Les indicateurs techniques contiennent des infinités (division par zéro).

**Solution** : Déjà corrigée dans `feature_engineer.py`. Relancez le script.

### Erreur : "Found array with 0 sample(s)"

**Cause** : La date de test (`TEST_START_DATE`) est avant toutes les données.

**Solution** : Modifiez `TEST_START_DATE` dans `config.py` pour une date dans la plage des données.

### Résultats aléatoires à chaque exécution

**Cause** : Les modèles utilisent du hasard (SMOTE, bagging, etc.).

**Solution** : Le seed est fixé à 42 dans `config.py`. Les résultats devraient être reproductibles.

---

## Workflow complet recommandé

```bash
# 1. Configuration
# Éditez config/config.py avec vos symboles et paramètres

# 2. Test rapide
python main.py

# 3. Comparaison des modèles
python compare_models.py --symbols BTCUSDT,ETHUSDT,SOLUSDT,AVAXUSDT,XRPUSDT

# 4. Portfolio diversifié
python run_portfolio.py --symbols BTCUSDT,ETHUSDT,SOLUSDT,AVAXUSDT,XRPUSDT --allocation performance_weighted

# 5. Optimisation (optionnel)
python optimize_strategy.py --symbol XRPUSDT --trials 100
python optimize_strategy.py --symbol AVAXUSDT --trials 100

# 6. Analyser les résultats
# Ouvrez les fichiers PNG dans results/
# Analysez les CSV pour les détails
```

---

## Notes importantes

- **Dates** : Les graphiques affichent les dates réelles (pas les numéros de candles)
- **Reproductibilité** : Tous les résultats sont reproductibles (seed=42)
- **Données réelles** : Créez un `.env` pour utiliser les vraies données Binance
- **Diversification** : Utilisez `run_portfolio.py` pour répartir le risque
- **Optimisation** : Utilisez `optimize_strategy.py` après avoir choisi vos meilleures cryptos
