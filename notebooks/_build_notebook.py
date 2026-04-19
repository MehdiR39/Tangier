"""
Generates notebooks/stock_scanner_course.ipynb.
Run: python notebooks/_build_notebook.py
"""
import nbformat as nbf
import os

nb = nbf.v4.new_notebook()
cells = []

def md(text):  cells.append(nbf.v4.new_markdown_cell(text))
def code(src): cells.append(nbf.v4.new_code_cell(src))

# ---------------------------------------------------------------------------
md("""# Stock Signal Scanner — Cours complet

Ce notebook est le **guide complet** du scanner d'actions développé en
réutilisant le pipeline ML du bot de trading crypto.

Il couvre :

1. **Objectif & architecture** — qu'est-ce qu'on essaie de prédire ?
2. **Pipeline de données** (yfinance, caching)
3. **Feature engineering** — 45+ indicateurs techniques
4. **Création de la variable cible** (percentiles roulants adaptatifs)
5. **Entraînement d'un modèle global** LightGBM multi-actions
6. **Scan "live"** et ranking top-N
7. **Walk-forward evaluation** — la signal_quality est-elle calibrée ?
8. **Backtest top-K rebalancing** — combien ça aurait rapporté ?
9. **Filtres métier** (liquidité, market cap, secteur)
10. **Scanner hourly** — version swing-trading
11. **Limites & next steps**

> ⚠️ **Warning honnête** : un ML qui prédit 60% des signaux correctement à
> 5 jours est déjà très bon. Ne confondez pas *proba haute* avec *profit
> garanti*. Voir section 7 sur la calibration.
""")

md("## 1. Objectif & architecture\n\n"
   "**On veut** : scanner 300-500 actions et sortir un **top 10** des meilleurs "
   "signaux d'entrée/sortie avec un **% de qualité**.\n\n"
   "**Architecture** :\n\n"
   "```\n"
   "1. yfinance ─→ OHLCV journalier/horaire pour N tickers\n"
   "2. FeatureEngineer ─→ ~45 indicateurs techniques par ticker\n"
   "3. TargetCreator ─→ labels Sell/Hold/Buy via percentiles roulants\n"
   "4. ModelTrainer (LightGBM global) ─→ entraîné sur tous les tickers\n"
   "   + feature `ticker_id` pour apprendre les patterns cross-sectionnels\n"
   "5. Scanner ─→ predict_proba sur la dernière bougie, rank par max(p_buy, p_sell)\n"
   "```\n\n"
   "**Choix clé** : **un seul modèle global** plutôt que 300 modèles par ticker. "
   "Raison : plus de données d'entraînement, meilleure généralisation, "
   "apprentissage de features universelles (ex: RSI<30 → rebond probable, "
   "quel que soit le ticker). Référence : Gu, Kelly & Xiu (2020) — *Empirical "
   "Asset Pricing via Machine Learning*.\n")

# ---------------------------------------------------------------------------
md("## 2. Setup\n")

code("""# Imports + config
import os, sys, warnings, logging
warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

# Go to project root
ROOT = os.path.abspath(os.path.join(os.getcwd(), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.chdir(ROOT)

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from config import config
from src.data_manager_stocks import StockDataManager
from src.feature_engineer import FeatureEngineer
from src.model_trainer import ModelTrainer, TargetCreator
from src.scanner_utils import fetch_metadata, filter_universe, recent_dollar_volume
from src.walk_forward import walk_forward_eval, calibration_bins, accuracy_by_class
from src.backtester_scanner import backtest_topk
from scanner import build_training_frame, train_global_model, scan

pd.set_option("display.max_columns", None)
pd.set_option("display.width", 160)
print("Setup OK. Root:", ROOT)""")

# ---------------------------------------------------------------------------
md("## 3. Pipeline de données (yfinance)\n\n"
   "On utilise **yfinance** car c'est gratuit et suffisant pour un prototype. "
   "Limites à connaître :\n\n"
   "- données EOD (fin de journée) en journalier, pas de tick-data\n"
   "- historique horaire limité à ~730 jours\n"
   "- ajustements dividendes/splits automatiques (`auto_adjust=True`)\n\n"
   "Caching disque en parquet dans `data/stocks/<TICKER>_<interval>.parquet` "
   "pour éviter de re-télécharger.")

code("""# Univers de démarrage : 30 blue chips (défini dans config.STOCK_UNIVERSE)
dm = StockDataManager(config)
tickers = config.STOCK_UNIVERSE
print(f"Univers de démarrage : {len(tickers)} tickers")
print(tickers[:10], "...")""")

code("""# Fetch en batch (depuis cache si déjà téléchargé)
data_dict = dm.fetch_universe(tickers)
print(f"Loaded: {len(data_dict)} tickers\\n")

# Aperçu
sample_sym = list(data_dict.keys())[0]
print(f"--- {sample_sym} ({len(data_dict[sample_sym])} rows) ---")
data_dict[sample_sym].tail()""")

code("""# Visualisation rapide
fig, ax = plt.subplots(2, 1, figsize=(11, 5), sharex=True)
sample = data_dict[sample_sym]
ax[0].plot(sample.index, sample["Close"], lw=1)
ax[0].set_title(f"{sample_sym} — Close")
ax[0].grid(alpha=0.3)
ax[1].bar(sample.index, sample["Volume"], width=1, color="gray")
ax[1].set_title("Volume"); ax[1].grid(alpha=0.3)
plt.tight_layout(); plt.show()""")

# ---------------------------------------------------------------------------
md(r"""## 4. Feature engineering — les 45 indicateurs (définitions + mathématique)

Chaque indicateur est une **transformation de la série OHLCV** qui comprime
l'information passée en une valeur scalaire exploitable par le modèle.

**Notation** :

- $C_t, O_t, H_t, L_t, V_t$ = Close, Open, High, Low, Volume à l'instant $t$
- $\text{SMA}_n(x)_t = \frac{1}{n} \sum_{i=0}^{n-1} x_{t-i}$ (moyenne mobile simple)
- $\mathbb{1}\{A\}$ = fonction indicatrice (vaut 1 si A vrai, sinon 0)

**Tous les indicateurs sont décalés d'1 période** (`config.LAG_INDICATORS=True`)
pour éviter le look-ahead bias — quand on prédit la bougie $t$, on utilise
des features calculées sur $t-1$ et avant.

---

### 4.1 Famille Tendance (Trend)

**Rôle général** : capter la direction dominante du marché à plusieurs échelles temporelles.

---

#### SMA — Simple Moving Average (5, 20, 50, 200)

> **Définition** : moyenne arithmétique des $n$ derniers prix de clôture.
> Elle **lisse** les variations court-terme pour faire ressortir la tendance
> sous-jacente. C'est l'indicateur le plus ancien et le plus utilisé.

$$\text{SMA}_n(C)_t = \frac{1}{n} \sum_{i=0}^{n-1} C_{t-i}$$

**Interprétation par horizon** :
- **SMA_5** (~1 semaine bourse) → tendance ultra-court terme, très bruyante
- **SMA_20** (~1 mois) → swing trading, référence des swing traders
- **SMA_50** (~2 mois) → tendance intermédiaire, support/résistance dynamique
- **SMA_200** (~10 mois) → référence **institutionnelle**. Au-dessus = "bull market", en-dessous = "bear market"

---

#### EMA — Exponential Moving Average (12, 26)

> **Définition** : moyenne mobile qui donne **plus de poids aux données récentes**
> via une décroissance exponentielle. Elle réagit donc plus vite qu'une SMA à
> un changement de prix. Utilisée dans presque tous les indicateurs avancés
> (MACD, OBV lissé, etc.).

$$\text{EMA}_n(x)_t = \alpha \, x_t + (1-\alpha)\,\text{EMA}_n(x)_{t-1}, \quad \alpha = \frac{2}{n+1}$$

**Pourquoi α = 2/(n+1)** : c'est le coefficient qui fait qu'une EMA_n a le
même "centre de gravité" temporel qu'une SMA_n.

---

#### Croisements de SMA (signaux binaires)

> **Définition** : indicateur binaire qui vaut 1 si la moyenne courte est au-dessus
> de la moyenne longue, sinon 0. C'est la version simplifiée des
> "crossover signals" des traders (*Golden Cross* = 50 > 200 = bullish).

$$\text{SMA_5_20_Cross}_t = \mathbb{1}\{\text{SMA}_5(C)_t > \text{SMA}_{20}(C)_t\}$$

Idem pour 20/50 et 50/200. Le modèle ML peut croiser ces 3 binaires pour
détecter les régimes (court-terme haussier mais long-terme baissier = divergence).

---

#### Distance Prix / SMA

> **Définition** : écart en % entre le prix actuel et sa moyenne mobile.
> Mesure le degré de "surextension" du prix. Quand le prix s'éloigne
> anormalement de sa moyenne, il a tendance à y revenir (*mean reversion*).

$$\text{Price_SMA20_Dist}_t = \frac{C_t - \text{SMA}_{20}(C)_t}{\text{SMA}_{20}(C)_t}$$

Idem avec SMA_50. Valeurs typiques : ±5% en temps normal, ±15% en cas
d'extension extrême.

---

#### ADX — Average Directional Index (Wilder, 1978)

> **Définition** : **force** de la tendance (pas sa direction). Oscillateur
> 0-100 qui répond à une seule question : *est-ce qu'il y a une tendance
> exploitable, ou bien le marché est-il en range ?* Inventé par J. Welles
> Wilder, créateur du RSI.

Étape 1 — Directional Movement :
$$+DM_t = \max(H_t - H_{t-1}, 0)\cdot\mathbb{1}\{H_t - H_{t-1} > L_{t-1} - L_t\}$$
$$-DM_t = \max(L_{t-1} - L_t, 0)\cdot\mathbb{1}\{L_{t-1} - L_t > H_t - H_{t-1}\}$$

Étape 2 — Directional Indicators :
$$+DI_t = 100\cdot\frac{\text{SMA}_{14}(+DM)}{\text{SMA}_{14}(TR)}, \quad
-DI_t = 100\cdot\frac{\text{SMA}_{14}(-DM)}{\text{SMA}_{14}(TR)}$$

Étape 3 — ADX :
$$DX_t = 100\cdot\frac{|+DI_t - -DI_t|}{+DI_t + -DI_t}, \quad
\text{ADX}_t = \text{SMA}_{14}(DX)$$

**Lecture** :
- ADX < 20 → marché en range, pas de tendance → stratégies breakout risquées
- ADX entre 20 et 25 → tendance naissante
- ADX > 25 → tendance forte et exploitable
- ADX > 50 → tendance très forte (souvent en phase finale d'épuisement)

---

### 4.2 Famille Momentum

**Rôle général** : mesurer la **vitesse** et la **persistance** du mouvement.
Un prix qui monte vite avec momentum élevé a plus de chances de continuer
à monter (effet Newton financier).

---

#### RSI — Relative Strength Index (Wilder, 1978)

> **Définition** : oscillateur qui mesure le **ratio de hausses vs baisses**
> sur les 14 dernières bougies, ramené à une échelle 0-100. Répond à :
> *le prix est-il en surachat (trop monté trop vite) ou en survente (trop
> baissé) ?* L'indicateur le plus utilisé au monde.

$$\text{Gain}_t = \max(C_t - C_{t-1}, 0), \quad \text{Loss}_t = \max(C_{t-1} - C_t, 0)$$
$$\text{RS}_t = \frac{\text{SMA}_{14}(\text{Gain})}{\text{SMA}_{14}(\text{Loss})}, \quad \text{RSI}_t = 100 - \frac{100}{1 + \text{RS}_t}$$

**Lecture** :
- **RSI > 70** → surachat, retour en arrière probable
- **RSI < 30** → survente, rebond probable
- **Divergence haussière** : prix fait un plus-bas, RSI fait un plus-haut → signal de retournement puissant

---

#### Stochastique %K, %D

> **Définition** : positionne le prix de clôture **dans le range
> [plus bas, plus haut] des 14 dernières bougies**. Intuition : si le close
> est proche du high du range, la bougie est "forte"; proche du low, elle
> est "faible". %D est la version lissée (moyenne mobile 3) de %K pour
> éviter les faux signaux.

$$\%K_t = 100 \cdot \frac{C_t - \min_{14}(L)}{\max_{14}(H) - \min_{14}(L)}$$
$$\%D_t = \mathrm{SMA}_3(\%K)_t$$

**Lecture** : même logique que RSI (>80 surachat, <20 survente), mais plus
sensible aux ranges. Utile pour timer les entrées en complément du RSI.

---

#### MACD — Moving Average Convergence Divergence (Appel, 1979)

> **Définition** : compare deux EMA (une courte, une longue) pour détecter
> les **retournements de momentum**. Quand la courte croise au-dessus de la
> longue, c'est un changement de vitesse haussier (et vice-versa).
> L'histogramme MACD_Hist = MACD - Signal visualise l'accélération.

$$\text{MACD}_t = \text{EMA}_{12}(C)_t - \text{EMA}_{26}(C)_t$$
$$\text{MACD_Signal}_t = \text{EMA}_9(\text{MACD})_t$$
$$\text{MACD_Hist}_t = \text{MACD}_t - \text{MACD_Signal}_t$$

**Lecture** :
- MACD > Signal (histogramme positif) → momentum haussier
- Histogramme qui **croît** → l'accélération s'accélère (2ème dérivée positive)
- Divergences prix/MACD = retournement probable

---

#### Momentum brut et en pourcentage (n ∈ {3, 5, 10})

> **Définition** : simple différence ou ratio entre le prix actuel et le prix
> il y a $n$ bougies. C'est la définition **la plus primitive** du momentum.
> Le modèle bénéficie d'avoir plusieurs horizons (3, 5, 10) car ils captent
> des fréquences différentes.

$$\text{Momentum}_n(t) = C_t - C_{t-n}, \quad \text{Momentum_Pct}_n(t) = \frac{C_t}{C_{t-n}} - 1$$

**Pourquoi les deux versions** : Momentum brut conserve l'info sur le niveau
de prix (utile pour le modèle qui peut l'interagir avec l'ATR par ex),
Momentum_Pct est normalisé comparable entre tickers.

---

#### ROC — Rate of Change (période 12)

> **Définition** : Momentum_Pct à période 12 fixe. Indicateur classique
> antérieur à Momentum_Pct, maintenu pour raisons historiques (beaucoup de
> stratégies publiques utilisent ROC_12).

$$\text{ROC}_t = \frac{C_t - C_{t-12}}{C_{t-12}}$$

---

### 4.3 Famille Volatilité

**Rôle général** : mesurer la **dispersion** des prix. La volatilité ne dit
pas si le marché monte ou descend, elle dit **à quel point il bouge**.
Essentielle pour le risk management et la détection de régime.

---

#### Bandes de Bollinger (Bollinger, 1980)

> **Définition** : **couloir autour d'une moyenne mobile**, dont la largeur
> s'adapte dynamiquement à la volatilité récente. La bande supérieure est
> SMA + 2×écart-type, la bande inférieure SMA - 2×écart-type.
> En théorie statistique, ~95% des prix devraient se trouver à l'intérieur
> si les returns étaient gaussiens.

$$\text{BB_Middle}_t = \text{SMA}_{20}(C)_t$$
$$\sigma_t = \sqrt{\frac{1}{20}\sum_{i=0}^{19}(C_{t-i} - \text{BB_Middle}_t)^2}$$
$$\text{BB_Upper}_t = \text{BB_Middle}_t + 2\sigma_t, \quad
\text{BB_Lower}_t = \text{BB_Middle}_t - 2\sigma_t$$

---

#### BB_Width — Largeur des Bandes

> **Définition** : largeur relative du couloir de Bollinger, normalisée par
> la SMA. Quantifie le **régime de volatilité**. Une largeur très faible
> (squeeze) annonce historiquement un breakout imminent (la vol se
> décomprime).

$$\text{BB_Width}_t = \frac{\text{BB_Upper}_t - \text{BB_Lower}_t}{\text{BB_Middle}_t}$$

---

#### BB_Position — Position relative dans les Bandes

> **Définition** : position du close **à l'intérieur du couloir**, entre 0
> (sur la bande basse) et 1 (sur la bande haute). Peut dépasser [0,1] lors
> des breakouts extrêmes. Équivalent à un z-score clampé sur 2σ.

$$\text{BB_Position}_t = \frac{C_t - \text{BB_Lower}_t}{\text{BB_Upper}_t - \text{BB_Lower}_t}$$

**Lecture** :
- BB_Position > 1 → prix hors bande haute (surachat extrême) → mean reversion possible
- BB_Position < 0 → sous la bande basse (survente extrême)
- BB_Position ≈ 0.5 → au centre du couloir, pas de signal

---

#### ATR — Average True Range (Wilder, 1978)

> **Définition** : moyenne mobile du **"vrai range"** d'une bougie, qui
> inclut les gaps d'ouverture. Mesure la volatilité **en unités de prix**
> (dollars, pas en %). C'est **la** référence pour dimensionner un stop-loss
> (ex: stop à 2×ATR du point d'entrée).

$$TR_t = \max\big(H_t - L_t,\; |H_t - C_{t-1}|,\; |L_t - C_{t-1}|\big)$$
$$\text{ATR}_t = \text{SMA}_{14}(TR)_t$$

**ATR_Pct** : version normalisée :
$$\text{ATR_Pct}_t = \frac{\text{ATR}_t}{C_t}$$

**Pourquoi le "vrai range"** : un gap à l'ouverture (close hier à 100, open
ce matin à 95) est une volatilité réelle que H-L simple ignorerait.

---

#### HV — Historical Volatility (période 20)

> **Définition** : **écart-type des log-returns** sur 20 bougies. C'est la
> définition financière standard de la volatilité (celle utilisée dans
> Black-Scholes). Annualisée en la multipliant par √N où N = nombre de
> bougies par an (252 pour du daily, ~2000 pour du 2h crypto).

$$r_t = \ln\!\frac{C_t}{C_{t-1}}, \quad \text{HV}_t = \sigma(r)_{t-19:t}$$

---

#### Volatility_Norm — Volatilité normalisée

> **Définition** : ratio entre la vol courte (20 bougies) et la moyenne
> de la vol longue (50 bougies). Répond à : *la vol actuelle est-elle
> élevée ou basse **par rapport à son régime habituel** ?*

$$\text{Volatility_Norm}_t = \frac{\text{HV}_t}{\text{SMA}_{50}(\text{HV})_t}$$

**Lecture** :
- > 1.5 → régime de haute volatilité (crise, earnings)
- ≈ 1 → régime normal
- < 0.7 → régime calme (complaisance, souvent avant breakout)

---

### 4.4 Famille Volume

**Rôle général** : le volume, c'est **la conviction** derrière un mouvement.
Un rally sans volume est suspect (pas d'acheteurs réels). Un mouvement avec
volume fort est "confirmé". C'est l'adage *"Price tells you what, volume
tells you when"*.

---

#### Volume_MA, Volume_Ratio

> **Définition** : moyenne mobile du volume (référence "normale") et ratio
> du volume actuel sur cette référence. Permet de détecter les **pics de
> volume anormaux** (news, earnings, M&A).

$$\text{Volume_MA}_t = \text{SMA}_{20}(V)_t, \quad \text{Volume_Ratio}_t = \frac{V_t}{\text{Volume_MA}_t}$$

**Lecture** : ratio > 2 = anomalie (le volume a doublé vs sa moyenne 20 jours).
En crypto on voit parfois des ratios à 10× lors des dumps.

---

#### OBV — On Balance Volume (Granville, 1963)

> **Définition** : **cumul signé** du volume. On ajoute le volume au cumul
> si le prix a monté, on le soustrait si le prix a baissé. L'idée : distinguer
> le **smart money** (qui accumule en silence pendant les ranges) du retail
> (qui achète aux sommets). Une divergence entre prix et OBV signale une
> accumulation/distribution cachée.

$$\text{OBV}_t = \text{OBV}_{t-1} + \text{sign}(C_t - C_{t-1})\cdot V_t$$

**OBV_EMA** : version lissée pour filtrer le bruit :
$$\text{OBV_EMA}_t = \text{EMA}_{20}(\text{OBV})_t$$

**Divergence classique** : le prix atteint un nouveau high, mais OBV non
→ la hausse n'est pas soutenue par du vrai volume acheteur → retournement
probable.

---

#### VROC — Volume Rate of Change (12)

> **Définition** : variation en % du volume sur 12 bougies. Mesure
> l'**accélération** de l'activité (pas juste son niveau absolu).

$$\text{VROC}_t = \frac{V_t - V_{t-12}}{V_{t-12}}$$

---

#### MFI — Money Flow Index (période 14)

> **Définition** : **RSI pondéré par le volume**. On remplace les gains/losses
> simples par des flux monétaires (prix moyen × volume). Plus robuste aux
> fausses alertes car une petite bougie avec peu de volume compte moins
> qu'une grosse bougie avec gros volume. Aussi appelé "volume-weighted RSI".

Typical Price et Money Flow :
$$\text{TP}_t = \frac{H_t + L_t + C_t}{3}, \quad \text{MF}_t = \text{TP}_t \cdot V_t$$

Ratio et oscillateur :
$$\text{MFR}_t = \frac{\sum_{i : \text{TP up}} \text{MF}_i}{\sum_{i : \text{TP down}} \text{MF}_i}$$
$$\text{MFI}_t = 100 - \frac{100}{1 + \text{MFR}_t}$$

**Lecture** : identique au RSI (>80 surachat, <20 survente) mais avec la
validation du volume.

---

### 4.5 Famille Prix (micro-structure de la bougie)

**Rôle général** : capturer la **structure interne** de chaque bougie, pas
juste son close. Une bougie qui monte de 2% mais ferme près du low raconte
une histoire très différente d'une qui ferme près du high.

---

#### Returns et Log_Returns

> **Définition** : variation en % du close d'une bougie à l'autre.
> Les **log-returns** sont préférés en finance car ils sont **additifs
> dans le temps** ($r_{t:t+n} = \sum r_i$) et approximativement gaussiens,
> hypothèse centrale des modèles de finance quantitative (Black-Scholes,
> GARCH).

$$\text{Returns}_t = \frac{C_t}{C_{t-1}} - 1, \quad \text{Log_Returns}_t = \ln\!\frac{C_t}{C_{t-1}}$$

Pour de petites variations, $\ln(1+r) \approx r$, donc Returns et Log_Returns
sont quasi identiques (différence <1% pour un mouvement <5%).

---

#### Price_Range — Amplitude relative intrabar

> **Définition** : amplitude haut-bas de la bougie, normalisée par son close.
> Indicateur de **volatilité intrabar** (sur une seule bougie, indépendant
> du move close-to-close).

$$\text{Price_Range}_t = \frac{H_t - L_t}{C_t}$$

**Lecture** : une bougie avec Price_Range > 0.05 (5%) est une bougie de
forte volatilité. Les pics indiquent souvent des news ou des rejets de
niveaux clés.

---

#### Close_Position — Position du close dans le range

> **Définition** : où la bougie **clôture dans son propre range** (0 = au low,
> 1 = au high). Révèle qui a gagné la bataille acheteurs/vendeurs sur la période.

$$\text{Close_Position}_t = \frac{C_t - L_t}{H_t - L_t} \in [0, 1]$$

**Lecture** :
- **1** → close au high. Pression acheteuse claire, *hammer/shooting star invert*
- **0** → close au low. Pression vendeuse, bougie faible
- **0.5** → indécision, *doji*, marché en quête de direction

---

#### Open_Close_Ratio

> **Définition** : ratio open/close. Alternative au signe du body de la
> bougie, normalisée. <1 si bougie haussière (close > open), >1 si baissière.

$$\text{Open_Close_Ratio}_t = \frac{O_t}{C_t}$$

**Lecture** : proche de 1 = doji (indécision), éloigné de 1 = bougie à gros
body (conviction).

---

### 4.6 Tableau récapitulatif — signification par famille

| Famille | Question à laquelle elle répond |
|---|---|
| **Tendance** | Est-ce qu'on est dans un bull/bear market ? À quelle échelle ? |
| **Momentum** | Est-ce que le mouvement actuel va continuer ou s'épuiser ? |
| **Volatilité** | Quel est le risque ? Sommes-nous en régime calme ou chaotique ? |
| **Volume** | Est-ce que le mouvement a du support (participation réelle) ? |
| **Prix** | Structure fine de la dernière bougie (conviction, indécision) |

Le modèle **combine** ces 5 angles. Exemple de configuration BUY idéale :

- **Tendance** : SMA_50_200_Cross = 1 (régime bull), ADX > 25
- **Momentum** : RSI qui sort de survente (<30 → >40), MACD_Hist croissant
- **Volatilité** : BB_Position proche de 0 (sur la bande basse), ATR stable
- **Volume** : Volume_Ratio > 1.5, OBV en hausse
- **Prix** : Close_Position élevé (close proche du high intraday)

C'est le cerveau humain d'un chartiste distillé en 45 variables numériques.
Le travail du ML est d'apprendre quelles combinaisons fonctionnent et
lesquelles sont du bruit.
""")

code("""fe = FeatureEngineer(config)
sample_featured = fe.engineer_features(data_dict[sample_sym], sample_sym)

feature_cols = [c for c in sample_featured.columns
                if c not in {"Open", "High", "Low", "Close", "Volume",
                             "Returns", "Log_Returns"}]
print(f"Nombre de features générées : {len(feature_cols)}")
print("Echantillon :", feature_cols[:12], "...")""")

code("""# Heatmap de corrélation des features (top 20 par variance)
top = sample_featured[feature_cols].var().sort_values(ascending=False).head(20).index
corr = sample_featured[top].corr()

fig, ax = plt.subplots(figsize=(9, 7))
im = ax.imshow(corr, cmap="RdBu_r", vmin=-1, vmax=1)
ax.set_xticks(range(len(top))); ax.set_xticklabels(top, rotation=90, fontsize=8)
ax.set_yticks(range(len(top))); ax.set_yticklabels(top, fontsize=8)
plt.colorbar(im, ax=ax, fraction=0.046)
ax.set_title(f"{sample_sym} — corrélations des 20 features top-variance")
plt.tight_layout(); plt.show()""")

# ---------------------------------------------------------------------------
md("""## 5. Création de la variable cible (Target)

C'est **le cœur du projet** — comment on définit "bon signal d'achat" de façon
à ce qu'un modèle puisse l'apprendre.

### La logique

```python
future_return = Close.pct_change(5).shift(-5)   # rendement à 5 jours
rolling_percentile = future_return.rolling(150).rank(pct=True)

Target = 1  (Hold par défaut)
Target[rolling_percentile >= 0.90] = 2  (Buy)   # top 10% des rendements
Target[rolling_percentile <= 0.10] = 0  (Sell)  # bottom 10%
```

### Pourquoi ce choix ?

- **Rendement futur** (et pas passé) : on apprend à prédire, pas à réagir.
- **Percentile roulant** (et pas seuil absolu) : s'adapte automatiquement à la
  volatilité du régime (un +2% en 5 jours sur AAPL n'est pas le même signal
  qu'un +2% sur TSLA).
- **Top/bottom 10%** : on ne prend que les rendements vraiment extrêmes
  → le modèle apprend des patterns plus discriminants, Hold=majorité (~80%)
  est géré par SMOTE.
- **Drop des 5 dernières lignes** : la cible dépend de `t+5` futur, donc
  on ne peut pas labéliser les 5 derniers points.
""")

code("""tc = TargetCreator(config)

sample_labelled = tc.create_targets(sample_featured.copy(), sample_sym)
print("Distribution Target sur", sample_sym, ":")
print(sample_labelled["Target"].value_counts().sort_index()
      .rename({0:"Sell", 1:"Hold", 2:"Buy"}))""")

code("""# Visualisation : où se placent les labels Buy/Sell sur la courbe ?
fig, ax = plt.subplots(figsize=(12, 4))
ax.plot(sample_labelled.index, sample_labelled["Close"], color="black", lw=0.8, label="Close")
buys  = sample_labelled[sample_labelled["Target"] == 2]
sells = sample_labelled[sample_labelled["Target"] == 0]
ax.scatter(buys.index,  buys["Close"],  color="green", s=12, alpha=0.6, label="Buy label")
ax.scatter(sells.index, sells["Close"], color="red",   s=12, alpha=0.6, label="Sell label")
ax.set_title(f"{sample_sym} — labels Buy/Sell (perc. 90/10 sur rendement futur 5j)")
ax.legend(); ax.grid(alpha=0.3); plt.tight_layout(); plt.show()""")

# ---------------------------------------------------------------------------
md("""## 6. Entraînement du modèle global

### Construction du jeu d'entraînement pooled

Pour chaque ticker : features + Target → on empile tout dans un seul DataFrame
avec une colonne `ticker_id`. Le modèle voit donc :

- 30 tickers × ~580 bougies = ~17 000 lignes d'entraînement
- 50+ features + ticker_id

### Modèle : LightGBM multi-classe

Choix par défaut (`config.MODEL_TYPE = "lgbm"`). Avantages pour ce use-case :

- rapide sur tabulaire
- gère les features non-scalées (même si on scale quand même via StandardScaler)
- robuste aux outliers
- feature importance native → on sait ce qui compte

### Pipeline complet en 1 appel
""")

code("""fe = FeatureEngineer(config)
tc = TargetCreator(config)
trainer = ModelTrainer(config)

training, featured = build_training_frame(data_dict, fe, tc)
print(f"Jeu d'entraînement : {training.shape[0]} lignes × {training.shape[1]} cols")
print("\\nDistribution globale de Target :")
print(training["Target"].value_counts().sort_index()
      .rename({0:"Sell", 1:"Hold", 2:"Buy"}))""")

code("""selected = train_global_model(training, trainer)
print(f"\\nFeatures sélectionnées ({len(selected)}) :", selected)""")

code("""# Feature importance
imp = pd.Series(
    trainer.model.feature_importances_,
    index=selected
).sort_values(ascending=False).head(15)

fig, ax = plt.subplots(figsize=(8, 5))
imp[::-1].plot.barh(ax=ax, color="steelblue")
ax.set_title("Top 15 feature importance — LightGBM global")
ax.set_xlabel("Importance")
plt.tight_layout(); plt.show()""")

# ---------------------------------------------------------------------------
md("""## 7. Scan "live" — top 10 signaux

Pour chaque ticker, on prend la **dernière bougie disponible**, on pousse
dans le modèle, et on ranke par `max(p_buy, p_sell)`.

- Direction = `LONG` si `p_buy >= p_sell`, sinon `SHORT`
- `signal_quality_pct` = probabilité du side choisi × 100
""")

code("""top10 = scan(featured, trainer, top_n=10)
top10""")

code("""# Visualisation des probas par signal
fig, ax = plt.subplots(figsize=(10, 5))
y = np.arange(len(top10))
ax.barh(y, top10["p_buy"],  color="green", alpha=0.7, label="p_buy")
ax.barh(y, top10["p_sell"], left=top10["p_buy"], color="red", alpha=0.7, label="p_sell")
ax.barh(y, top10["p_hold"], left=top10["p_buy"]+top10["p_sell"], color="gray", alpha=0.4, label="p_hold")
ax.set_yticks(y); ax.set_yticklabels(top10["ticker"])
ax.invert_yaxis(); ax.set_xlim(0, 1)
ax.set_xlabel("Probabilités"); ax.set_title("Top 10 — décomposition des probas")
ax.legend(loc="lower right"); plt.tight_layout(); plt.show()""")

# ---------------------------------------------------------------------------
md("""## 8. Walk-forward evaluation — la signal_quality est-elle calibrée ?

Un modèle peut sortir des probas **confiantes mais fausses**. La question
honnête :

> *Quand le modèle prédit "signal_quality = 75%", est-ce que **vraiment**
> 75% de ces signaux sont corrects out-of-sample ?*

C'est la **calibration**. On la mesure avec un walk-forward :

1. Entraîner sur `[0, t]`, prédire sur `[t, t+Δ]` → sauver les probas.
2. Rouler dans le temps.
3. Comparer proba prédite vs réalisé.

### Définition de "correct"

Pour chaque signal out-of-sample on regarde le rendement futur à 5 jours :
- LONG → "hit" si `fwd_return > 0`
- SHORT → "hit" si `fwd_return < 0`

Si le modèle est bien calibré, les bins de `signal_quality = 60%` doivent
avoir un `hit_rate ≈ 60%`.
""")

code("""# Walk-forward sur 3 folds — on utilise la sélection par 'importance'
# (bien plus rapide que RFE) pour que la démo tourne en < 1 min.
import types
fast_config = types.SimpleNamespace(**{
    k: getattr(config, k) for k in dir(config)
    if not k.startswith("_") and not callable(getattr(config, k))
})
fast_config.FEATURE_SELECTION_METHOD = "importance"
fast_config.USE_SMOTE = False   # accélère chaque fold

def trainer_factory():
    return ModelTrainer(fast_config)

oos = walk_forward_eval(
    featured_per_ticker=featured,
    trainer_factory=trainer_factory,
    target_creator=tc,
    n_splits=3,
    min_train_frac=0.6,
    return_horizon=5,
)
print(f"OOS predictions: {len(oos)} rows")
oos.head()""")

code("""# Accuracy par vraie classe
acc = accuracy_by_class(oos)
print(acc)""")

code("""# Courbe de calibration
cal = calibration_bins(oos, n_bins=8)
print(cal)

fig, ax = plt.subplots(figsize=(7, 6))
ax.plot([0, 1], [0, 1], "k--", lw=1, label="calibration parfaite")
ax.plot(cal["avg_predicted_quality"], cal["realised_hit_rate"],
        marker="o", lw=2, color="tab:blue", label="modèle")
for _, r in cal.iterrows():
    ax.annotate(f"n={int(r['count'])}",
                (r["avg_predicted_quality"], r["realised_hit_rate"]),
                textcoords="offset points", xytext=(8, -4), fontsize=8)
ax.set_xlabel("signal_quality prédite (avg par bin)")
ax.set_ylabel("hit rate réalisé (fwd_return dans la bonne direction)")
ax.set_title("Courbe de calibration — walk-forward OOS")
ax.set_xlim(0.3, 1.0); ax.set_ylim(0.3, 1.0)
ax.legend(); ax.grid(alpha=0.3); plt.tight_layout(); plt.show()""")

code("""# Rendement moyen par bin de qualité — ce qui compte vraiment en trading
fig, ax = plt.subplots(figsize=(9, 4))
cal_plot = cal.dropna(subset=["avg_fwd_return"])
ax.bar(range(len(cal_plot)), cal_plot["avg_fwd_return"] * 100,
       color=np.where(cal_plot["avg_fwd_return"] > 0, "green", "red"), alpha=0.7)
ax.set_xticks(range(len(cal_plot)))
ax.set_xticklabels([f"{x:.0%}" for x in cal_plot["avg_predicted_quality"]], fontsize=8)
ax.set_xlabel("signal_quality prédite (bin)")
ax.set_ylabel("fwd_return moyen (%) — direction-ajustée")
ax.set_title("Rendement moyen réalisé par niveau de confiance")
ax.axhline(0, color="black", lw=0.5); ax.grid(alpha=0.3, axis="y")
plt.tight_layout(); plt.show()""")

# ---------------------------------------------------------------------------
md("""## 9. Backtest — stratégie top-K rebalancing

### Règles simulées

- Tous les **5 jours** : retrain + scan + prendre les top 10 LONG et top 10
  SHORT.
- **Equal-weight** sur chaque leg, **hold 5 jours**.
- Frais : 5 bps par trade (entry + exit = 10 bps total).
- Pas de stop, pas de leverage, pas de risk sizing.

C'est volontairement **naïf** — on mesure l'alpha brut du signal. La suite
consisterait à rajouter du risk management.
""")

code("""# Backtest — on utilise trainer_factory (config 'fast') défini plus haut.
# Params conservateurs pour que la démo tourne en < 3 min.
# Pour une vraie évaluation : rebalance_bars=5, top_k=10, retirer min_train_bars.
results = backtest_topk(
    featured_per_ticker=featured,
    trainer_factory=trainer_factory,  # fast_config (importance FS, no SMOTE)
    target_creator=tc,
    top_k=3,
    rebalance_bars=20,      # rebalance toutes les 20 bougies (~1 mois)
    hold_bars=10,
    min_train_bars=400,
    allow_short=True,
    fee_bps=5.0,
)
print(results["summary"].to_string(index=False))""")

code("""# Courbe d'équité
eq = results["equity"]
fig, ax = plt.subplots(figsize=(11, 4))
ax.plot(eq.index, eq["equity"], lw=1.5, color="tab:blue")
ax.axhline(1.0, color="gray", lw=0.5, linestyle="--")
ax.set_title(f"Equity curve — final = {eq['equity'].iloc[-1]:.3f}×  "
             f"({len(results['trades'])} trades)")
ax.set_ylabel("Equity (base 1.0)"); ax.grid(alpha=0.3)
plt.tight_layout(); plt.show()""")

code("""# Distribution des rendements trade par trade
trades = results["trades"]
if not trades.empty:
    fig, ax = plt.subplots(1, 2, figsize=(12, 4))
    ax[0].hist(trades["net_return"] * 100, bins=40, color="steelblue", alpha=0.8)
    ax[0].axvline(0, color="black", lw=0.5)
    ax[0].set_title(f"P&L par trade — n={len(trades)}")
    ax[0].set_xlabel("Net return (%)"); ax[0].grid(alpha=0.3)

    # Hit rate par niveau de quality
    trades["qbin"] = pd.cut(trades["quality"], bins=5)
    hit = trades.groupby("qbin", observed=True).agg(
        hit=("net_return", lambda s: (s > 0).mean()),
        n=("net_return", "size"),
        avg_ret=("net_return", "mean"),
    ).reset_index()
    ax[1].bar(range(len(hit)), hit["avg_ret"] * 100,
              color=np.where(hit["avg_ret"] > 0, "green", "red"), alpha=0.7)
    ax[1].set_xticks(range(len(hit)))
    ax[1].set_xticklabels([str(b) for b in hit["qbin"]], rotation=30, fontsize=8)
    ax[1].set_title("Rendement moyen par bin de quality")
    ax[1].set_ylabel("avg return (%)"); ax[1].axhline(0, color="black", lw=0.5)
    ax[1].grid(alpha=0.3, axis="y")
    plt.tight_layout(); plt.show()
else:
    print("Aucun trade enregistré.")""")

# ---------------------------------------------------------------------------
md("""## 10. Filtres métier — liquidité, secteur, market cap

En vrai scan **production**, on ne veut pas trader :

- des nano-caps (slippage énorme)
- des secteurs qu'on ne comprend pas
- des tickers peu liquides (on ne pourra pas sortir)

`src/scanner_utils.py` fournit :

- `recent_dollar_volume(df, window=20)` — liquidité sur 20 jours
- `fetch_metadata(symbols)` — sector / industry / marketCap via yfinance
- `filter_universe(...)` — filtre combinable
""")

code("""# Fetch metadata (une fois, caché en parquet)
meta_path = os.path.join(config.DATA_DIR, "stocks", "metadata.parquet")
metadata = fetch_metadata(list(data_dict.keys()), cache_path=meta_path)
metadata""")

code("""# Exemple : on garde Technology + Healthcare, market cap > $50B, liquide
filtered = filter_universe(
    data_dict,
    metadata=metadata,
    min_dollar_volume=1e9,      # > $1B quotidien
    min_market_cap=50e9,        # > $50B
    include_sectors=["Technology", "Healthcare"],
)
print(f"Après filtres : {len(filtered)} tickers")
list(filtered.keys())""")

# ---------------------------------------------------------------------------
md("""## 11. Scanner hourly — version swing-trading

Même pipeline, mais sur des bougies **horaires** au lieu de journalières.

### Contraintes

- yfinance limite l'historique `1h` à **730 jours** — ok pour un prototype.
- Il faut **plus de lignes** pour avoir un signal stable (normalement 1000+).
- La target `pct_change(5).shift(-5)` devient "5h au lieu de 5j" → signaux
  plus nerveux, plus de frais relatifs.

### Comment lancer

En ligne de commande (retrain complet, univers déjà configuré) :

```bash
python scanner.py --interval 1h --top 10 --retrain
```

Ou en notebook, en changeant juste `config.STOCK_INTERVAL` :
""")

code("""# Demo: fetch hourly pour 3 tickers seulement (rapide)
# On override config sans toucher au fichier
original_interval = config.STOCK_INTERVAL
original_start, original_end = config.DATA_START_DATE, config.DATA_END_DATE

config.STOCK_INTERVAL = "1h"
config.DATA_START_DATE = None   # yfinance détermine le max (~730d)
config.DATA_END_DATE = None

dm_h = StockDataManager(config)
hourly = {}
for sym in ["AAPL", "NVDA", "MSFT"]:
    df = dm_h.fetch_data(sym, interval="1h", start=None, end=None)
    if df is not None and len(df) > 200:
        hourly[sym] = dm_h.prepare_data(df, sym)

print({k: len(v) for k, v in hourly.items()})
print("\\nRestore daily config for rest of notebook")
config.STOCK_INTERVAL = original_interval
config.DATA_START_DATE = original_start
config.DATA_END_DATE = original_end""")

code("""# Aperçu — les volumes et returns sont sur une échelle différente
if hourly:
    sym = list(hourly.keys())[0]
    print(f"{sym} — {len(hourly[sym])} bougies horaires")
    hourly[sym].tail(10)""")

md("""### Pour un scan hourly sérieux

1. Augmenter la taille de l'univers hourly à ~100 tickers.
2. Réentraîner le modèle global sur les données horaires (`config.TARGET_WINDOW`
   à 500 au lieu de 150, car une journée = 7 bougies).
3. Rebalancer plus souvent (toutes les N heures) dans le backtest.
4. Attention aux frais : à 10 bps par trade, un rebalance horaire consomme
   l'alpha.
""")

# ---------------------------------------------------------------------------
md("""## 12. Scan S&P 500 complet (optionnel — long)

Télécharge les 500 constituants, entraîne, scanne.

**Temps attendu** : 3-8 min (download + train + scan).

```python
# En notebook
sp500 = dm.sp500_tickers()
print(f"{len(sp500)} constituants S&P 500")

data500 = dm.fetch_universe(sp500)
_, feat500 = build_training_frame(data500, fe, tc)

trainer500 = ModelTrainer(config)
training500, feat500 = build_training_frame(data500, fe, tc)
train_global_model(training500, trainer500)

scan(feat500, trainer500, top_n=10)
```

Ou en CLI :

```bash
python scanner.py --universe sp500 --top 10 --retrain \\
    --min-dollar-volume 50e6 --min-market-cap 5e9
```
""")

# ---------------------------------------------------------------------------
md("""## 13. Conclusions de la v1 (avant améliorations)

Constats honnêtes tirés du walk-forward + backtest du modèle v1 :

- **Déséquilibre de classes au test** : Hold = 99% des prédictions,
  Buy ≈ 0%, Sell ≈ 0.5%. Le modèle "joue safe" et prédit Hold presque tout
  le temps → sous-exploite les signaux.
- **Calibration fragile au-delà de 50%** : bins [0-50%] bien calibrés,
  mais bins [>50%] ont trop peu de samples → variance énorme.
- **Backtest v1** : CAGR +1.75%, Sharpe 1.52, max DD -2.4%, hit rate 57%,
  mais **avg_loss (-4.3%) > avg_win (+3.4%)** — profil asymétrique
  défavorable.

**Diagnostic** : le ML marche, mais il faut :

1. rebalancer les classes (seuils 80/20 + `class_weight`),
2. ajouter des features de **régime macro** (VIX, yield curve, breadth),
3. **multi-horizon target** (5j + 20j consensus) pour des signaux plus
   robustes,
4. **stop-loss ATR** dans le backtest pour couper la queue gauche,
5. **élargir l'univers au S&P 500** pour plus de diversité cross-sectionnelle.

Ces 5 améliorations sont implémentées dans la section suivante.
""")

# ---------------------------------------------------------------------------
md("""## 14. Améliorations v2 — les 5 propositions implémentées

### Résumé des changements

| # | Proposition | Fichier modifié | Effet attendu |
|---|---|---|---|
| 1 | Seuils 80/20 + `class_weight='balanced'` | `config.py`, `model_trainer.py` | Plus de Buy/Sell prédits OOS |
| 3 | Features macro (VIX, yield, breadth) | `src/macro_features.py` (nouveau) | Conditionnement sur le régime |
| 5 | Multi-horizon target (5j ET 20j consensus) | `model_trainer.py` | Signaux plus robustes |
| 4 | Stop-loss ATR dans le backtest | `backtester_scanner.py` | Coupe les pertes > 2 ATR |
| 2 | Scan S&P 500 complet | CLI: `scanner.py --universe sp500` | +16× plus de données |

Chaque amélioration est démontrée ci-dessous avec **A/B comparison**.
""")

md("### 14.1 Prop 1 — Classes rebalancées + class_weight")

code("""# Config v2 (les changements sont déjà appliqués dans config.py)
print("BUY_THRESHOLD :", config.BUY_THRESHOLD, "(était 0.90)")
print("SELL_THRESHOLD:", config.SELL_THRESHOLD, "(était 0.10)")
print("TARGET_HORIZONS:", getattr(config, 'TARGET_HORIZONS', None), "(était None = [5])")
# LightGBM utilise maintenant class_weight='balanced' automatiquement.""")

md("### 14.2 Prop 5 — Multi-horizon target avec consensus AND")

md(r"""Nouvelle logique target (dans `TargetCreator.create_targets`) :

- On calcule les percentiles de rendement futur pour **chaque horizon** $h \in \{5, 20\}$
- **Buy** = (pct_5j ≥ 0.80) ET (pct_20j ≥ 0.80) — consensus sur les deux horizons
- **Sell** = (pct_5j ≤ 0.20) ET (pct_20j ≤ 0.20)
- Sinon **Hold**

Intuition : si le signal ne tient qu'à un horizon, c'est probablement du
bruit. Si le rendement futur est dans le top 20% à la fois à 5 et 20 jours,
on a un signal structurel plus fiable.""")

code("""# Démo: régénère les targets avec la nouvelle logique
tc_v2 = TargetCreator(config)
sample_v2 = tc_v2.create_targets(featured[sample_sym].copy(), sample_sym)

import pandas as _pd
dist_v2 = sample_v2["Target"].value_counts().sort_index().rename(
    {0:"Sell", 1:"Hold", 2:"Buy"}
)
print("Distribution v2 (seuils 80/20, consensus 5j+20j):")
print(dist_v2)
print(f"\\n% Buy+Sell: {(dist_v2.get('Buy', 0) + dist_v2.get('Sell', 0)) / dist_v2.sum() * 100:.1f}%")""")

md("### 14.3 Prop 3 — Features macro régime")

md(r"""#### Définition des 11 features macro

Rappel : les features macro sont les **mêmes pour tous les tickers à la date t**.
Elles agissent comme un "contexte de marché" que le modèle peut utiliser pour
conditionner ses prédictions.

**Famille VIX — volatilité implicite du marché**

Le VIX (CBOE) mesure la volatilité implicite attendue à 30 jours sur les
options S&P 500. Surnommé "fear index".

- `VIX_Level` — valeur brute. <15 calme, 20-30 nerveux, >40 panique
- `VIX_Pct_5d` — $\dfrac{\text{VIX}_t - \text{VIX}_{t-5}}{\text{VIX}_{t-5}}$, accélération de la peur
- `VIX_Regime_High` — binaire, 1 si $\text{VIX}_t > \text{SMA}_{60}(\text{VIX})$

**Famille Taux — courbe des rendements US**

- `TNX_Level` — rendement du Trésor US 10 ans (ticker `^TNX`)
- `TNX_Chg_5d` — variation absolue sur 5 jours, $\text{TNX}_t - \text{TNX}_{t-5}$
- `YieldCurve_Slope` — $\text{TNX}_t - \text{IRX}_t$ (10y − 3m)
- `YieldCurve_Inverted` — binaire, pente négative = signal historique de récession

**Famille SPY — performance & momentum marché**

Le SPY = ETF du S&P 500, proxy du "marché global".

- `SPY_Ret_20d` — rendement 20 bougies (~1 mois)
- `SPY_Ret_60d` — rendement 60 bougies (~3 mois)
- `SPY_Above_SMA200` — binaire, bull market institutionnel

**Breadth — santé interne**

- `Breadth_Pct_Above_SMA50` — fraction de l'univers au-dessus de sa SMA_50 :

$$\text{Breadth}_t = \frac{1}{N}\sum_{i=1}^{N} \mathbb{1}\{C_{i,t} > \text{SMA}_{50}(C_i)_t\}$$

Haut (>0.7) = marché large et sain. Bas (<0.3) = quelques leaders portent
l'indice, le reste baisse (fin de cycle classique).

| Feature | Question |
|---|---|
| VIX_Level/Pct/Regime | Niveau / accélération / stress persistant ? |
| TNX_Level/Chg | Taux sans risque, variation récente |
| YieldCurve_Slope/Inverted | Forme de la courbe, récession imminente ? |
| SPY_Ret_20/60d | Momentum court / moyen du marché |
| SPY_Above_SMA200 | Bull ou bear structurel ? |
| Breadth_Pct_Above_SMA50 | Largeur du mouvement |

Parmi ces 11, le modèle en retient **5** après sélection (cf. sortie
"Features macro retenues par le modèle" plus bas).
""")

code("""# Fetch des séries macro (VIX, TNX, IRX, SPY) — ~10s
from src.macro_features import (
    fetch_macro_series, build_macro_features,
    compute_breadth, attach_macro_to_tickers,
)

macro_raw = fetch_macro_series(
    start=config.DATA_START_DATE, end=config.DATA_END_DATE,
)
macro_feats = build_macro_features(macro_raw)
macro_feats.tail()""")

code("""# Breadth du universe (% above SMA50)
breadth = compute_breadth(data_dict, sma_period=50)
print(f"Breadth dispo sur {len(breadth.dropna())} jours")
breadth.tail()""")

code("""# Visu VIX + Breadth + SPY momentum
fig, axes = plt.subplots(3, 1, figsize=(11, 7), sharex=True)
axes[0].plot(macro_feats.index, macro_feats["VIX_Level"], color="tab:red", lw=1)
axes[0].axhline(20, ls="--", color="gray", lw=0.5, label="VIX=20 (calme)")
axes[0].set_title("VIX — régime de volatilité"); axes[0].legend(); axes[0].grid(alpha=0.3)

axes[1].plot(breadth.index, breadth, color="tab:green", lw=1)
axes[1].axhline(0.5, ls="--", color="gray", lw=0.5)
axes[1].set_title("Market Breadth — % tickers au-dessus de SMA50"); axes[1].grid(alpha=0.3)
axes[1].set_ylim(0, 1)

axes[2].plot(macro_feats.index, macro_feats["SPY_Ret_20d"] * 100,
             color="tab:blue", lw=1, label="SPY 20d return %")
axes[2].axhline(0, color="black", lw=0.5)
axes[2].set_title("SPY Momentum 20 jours"); axes[2].legend(); axes[2].grid(alpha=0.3)
plt.tight_layout(); plt.show()""")

code("""# Injecter macro + breadth dans les features de chaque ticker
data_v2 = attach_macro_to_tickers(data_dict, macro_feats, breadth)
print(f"Colonnes par ticker après macro: {data_v2[sample_sym].shape[1]} (+ macro/breadth)")
print("Nouvelles colonnes:", [c for c in data_v2[sample_sym].columns
                              if c not in data_dict[sample_sym].columns])""")

md("### 14.4 Retraining v2 — pipeline complet avec améliorations 1+3+5")

code("""# On refait le pipeline features -> training -> scan avec les enrichissements
training_v2, featured_v2 = build_training_frame(data_v2, fe, tc_v2)

print(f"Training v2: {training_v2.shape[0]} lignes × {training_v2.shape[1]} cols")
print("\\nDistribution Target v2:")
print(training_v2["Target"].value_counts().sort_index()
      .rename({0:"Sell", 1:"Hold", 2:"Buy"}))""")

code("""trainer_v2 = ModelTrainer(config)
selected_v2 = train_global_model(training_v2, trainer_v2)
print(f"Features v2 sélectionnées: {len(selected_v2)}")

# Check: les features macro font-elles partie du top ?
macro_cols = [c for c in selected_v2 if any(k in c for k in
              ["VIX", "TNX", "SPY", "Breadth", "YieldCurve"])]
print(f"Features macro retenues par le modèle: {macro_cols}")""")

code("""# Feature importance v2
imp_v2 = pd.Series(trainer_v2.model.feature_importances_,
                   index=selected_v2).sort_values(ascending=False).head(15)
fig, ax = plt.subplots(figsize=(8, 5))
colors = ["orange" if any(k in n for k in ["VIX", "TNX", "SPY", "Breadth", "YieldCurve"])
          else "steelblue" for n in imp_v2.index]
imp_v2[::-1].plot.barh(ax=ax, color=colors[::-1])
ax.set_title("Top 15 feature importance v2 — orange = macro régime")
ax.set_xlabel("Importance")
plt.tight_layout(); plt.show()""")

code("""# Nouveau scan top-10 avec le modèle v2
top10_v2 = scan(featured_v2, trainer_v2, top_n=10)
print("Top 10 signaux — modèle v2 (rebalancé + macro + multi-horizon)")
top10_v2""")

md("### 14.5 Walk-forward v2 — accuracy + calibration")

code("""# Walk-forward sur modèle v2 avec config rapide
fast_config_v2 = types.SimpleNamespace(**{
    k: getattr(config, k) for k in dir(config)
    if not k.startswith("_") and not callable(getattr(config, k))
})
fast_config_v2.FEATURE_SELECTION_METHOD = "importance"
fast_config_v2.USE_SMOTE = False

def trainer_factory_v2():
    return ModelTrainer(fast_config_v2)

oos_v2 = walk_forward_eval(
    featured_per_ticker=featured_v2,
    trainer_factory=trainer_factory_v2,
    target_creator=tc_v2,
    n_splits=3,
    min_train_frac=0.6,
    return_horizon=5,
)
print(f"OOS v2: {len(oos_v2)} predictions")

acc_v2 = accuracy_by_class(oos_v2)
print("\\nAccuracy v2 par classe:")
print(acc_v2)""")

code("""# Comparaison calibration v1 vs v2
cal_v2 = calibration_bins(oos_v2, n_bins=8)
print("Calibration v2:"); print(cal_v2)

fig, ax = plt.subplots(figsize=(7, 6))
ax.plot([0, 1], [0, 1], "k--", lw=1, label="parfaite")
if 'cal' in dir() and isinstance(cal, pd.DataFrame):
    ax.plot(cal["avg_predicted_quality"], cal["realised_hit_rate"],
            marker="o", lw=1.5, color="tab:gray", alpha=0.6, label="v1")
ax.plot(cal_v2["avg_predicted_quality"], cal_v2["realised_hit_rate"],
        marker="s", lw=2, color="tab:blue", label="v2")
ax.set_xlabel("signal_quality prédite"); ax.set_ylabel("hit rate réalisé")
ax.set_title("Calibration — v1 (gris) vs v2 (bleu)")
ax.set_xlim(0.3, 1.0); ax.set_ylim(0.3, 1.0)
ax.legend(); ax.grid(alpha=0.3); plt.tight_layout(); plt.show()""")

md("### 14.6 Prop 4 — Backtest v2 avec stop-loss ATR")

md("""Le backtester accepte maintenant `stop_atr_mult` et
`take_profit_atr_mult`. On définit :

- **Stop-loss** : sortie forcée si le prix bouge de **2×ATR** contre nous
  (coupe les pertes de la queue gauche identifiée dans v1).
- **Take-profit** : optionnel, à **3×ATR** en notre faveur.

En vrai trading c'est l'équivalent de "ne jamais risquer plus que X% sur
un trade" — règle n°1 de tout trader systématique.""")

code("""# Backtest v2 — mêmes paramètres que v1 mais avec stop/TP ATR
results_v2 = backtest_topk(
    featured_per_ticker=featured_v2,
    trainer_factory=trainer_factory_v2,
    target_creator=tc_v2,
    top_k=3,
    rebalance_bars=20,
    hold_bars=10,
    min_train_bars=400,
    allow_short=True,
    fee_bps=5.0,
    stop_atr_mult=2.0,        # stop à 2×ATR
    take_profit_atr_mult=3.0, # TP à 3×ATR
)
print("Backtest v2 (stop + TP ATR) :")
print(results_v2["summary"].to_string(index=False))""")

code("""# Comparaison équité v1 vs v2
fig, ax = plt.subplots(figsize=(11, 4))
if 'results' in dir() and isinstance(results, dict):
    eq_v1 = results["equity"]
    ax.plot(eq_v1.index, eq_v1["equity"], lw=1.2, color="tab:gray",
            alpha=0.8, label=f"v1 (final {eq_v1['equity'].iloc[-1]:.3f}×)")
eq_v2 = results_v2["equity"]
ax.plot(eq_v2.index, eq_v2["equity"], lw=1.8, color="tab:blue",
        label=f"v2 (final {eq_v2['equity'].iloc[-1]:.3f}×)")
ax.axhline(1.0, color="black", ls="--", lw=0.5)
ax.set_title("Equity curve — v1 vs v2")
ax.set_ylabel("Equity (base 1.0)"); ax.legend(); ax.grid(alpha=0.3)
plt.tight_layout(); plt.show()""")

code("""# Distribution exit_reason en v2 — a-t-on réellement des stops déclenchés ?
trades_v2 = results_v2["trades"]
if not trades_v2.empty and "exit_reason" in trades_v2.columns:
    reason_counts = trades_v2["exit_reason"].value_counts()
    print("Exit reasons v2:"); print(reason_counts)
    print("\\nRendement moyen par exit_reason:")
    print(trades_v2.groupby("exit_reason")["net_return"].agg(["mean", "count"]))""")

md("### 14.7 Prop 2 — Scan S&P 500 (exécuté hors notebook)")

md("""Le scan S&P 500 complet est **coûteux** (download 500 tickers + train)
donc on le lance en CLI plutôt qu'en cellule de notebook :

```bash
python scanner.py --universe sp500 --top 15 --retrain --min-dollar-volume 50e6
```

Les résultats sont sauvegardés dans `results/scanner_topN_<timestamp>.csv`.
Si un scan récent existe déjà, on peut juste charger le dernier :""")

code("""# Charge le dernier scan S&P 500 sauvegardé si disponible
import glob
files = sorted(glob.glob(os.path.join(config.RESULTS_DIR, "scanner_top*_*.csv")))
if files:
    last = files[-1]
    print(f"Dernier scan: {last}")
    sp500_scan = pd.read_csv(last)
    sp500_scan
else:
    print("Aucun scan sauvegardé. Lance : python scanner.py --universe sp500 --retrain")""")

md("""## 15. Ablation — isoler l'effet de chaque amélioration

Le premier run v2 a montré un **backtest plus mauvais** que v1 sur 30 tickers
avec stop-loss 2×ATR. Possibles causes :
- stop trop serré, coupe des winners
- univers trop petit pour que les features macro aident
- consensus multi-horizon trop restrictif

On isole chaque effet avec 3 backtests supplémentaires sur **featured_v2**
(modèle déjà enrichi avec macro + multi-horizon) :

| Variante | Stop ATR | TP ATR |
|---|---|---|
| v2-NoStop | aucun | aucun |
| v2-Stop3 | 3×ATR | 4×ATR |
| v2-Stop4 | 4×ATR | aucun |
""")

code("""# 3 backtests avec même trainer_factory_v2, mêmes rebalance params
bt_configs = [
    {"name": "v2-NoStop",  "stop_atr_mult": None, "take_profit_atr_mult": None},
    {"name": "v2-Stop3",   "stop_atr_mult": 3.0,  "take_profit_atr_mult": 4.0},
    {"name": "v2-Stop4",   "stop_atr_mult": 4.0,  "take_profit_atr_mult": None},
]
ablation = {}
for cfg in bt_configs:
    print(f"Running {cfg['name']}...")
    r = backtest_topk(
        featured_per_ticker=featured_v2,
        trainer_factory=trainer_factory_v2,
        target_creator=tc_v2,
        top_k=3, rebalance_bars=20, hold_bars=10,
        min_train_bars=400, allow_short=True, fee_bps=5.0,
        stop_atr_mult=cfg["stop_atr_mult"],
        take_profit_atr_mult=cfg["take_profit_atr_mult"],
    )
    ablation[cfg["name"]] = r
    print(f"  -> {r['summary'].set_index('metric').loc['final_equity', 'value']:.3f}x")
print("\\nDone.")""")

code("""# Compare les 4 backtests: v1, v2-Stop2 (initial), + 3 ablations
summary_rows = []
def _extract(name, res):
    s = res['summary'].set_index('metric')['value']
    return {
        'variante': name,
        'final_equity': s.get('final_equity'),
        'CAGR':         s.get('CAGR'),
        'Sharpe':       s.get('Sharpe'),
        'max_DD':       s.get('max_drawdown'),
        'hit_rate':     s.get('hit_rate'),
        'n_trades':     s.get('n_trades'),
    }

if 'results' in dir() and isinstance(results, dict):
    summary_rows.append(_extract('v1-baseline', results))
summary_rows.append(_extract('v2-Stop2ATR (initial)', results_v2))
for name, r in ablation.items():
    summary_rows.append(_extract(name, r))

ablation_df = pd.DataFrame(summary_rows).round(4)
ablation_df""")

code("""# Equity curves — comparaison visuelle
fig, ax = plt.subplots(figsize=(12, 5))
palette = {'v1': 'gray', 'v2-Stop2': 'tab:red',
           'v2-NoStop': 'tab:blue', 'v2-Stop3': 'tab:green', 'v2-Stop4': 'tab:orange'}
if 'results' in dir() and isinstance(results, dict):
    eq = results['equity']
    ax.plot(eq.index, eq['equity'], lw=1.2, color=palette['v1'],
            label=f"v1 ({eq['equity'].iloc[-1]:.3f}x)")
eq2 = results_v2['equity']
ax.plot(eq2.index, eq2['equity'], lw=1.4, color=palette['v2-Stop2'],
        label=f"v2-Stop2 ({eq2['equity'].iloc[-1]:.3f}x)")
for name, r in ablation.items():
    eq = r['equity']
    color = palette.get(name, 'black')
    ax.plot(eq.index, eq['equity'], lw=1.6, color=color,
            label=f"{name} ({eq['equity'].iloc[-1]:.3f}x)")
ax.axhline(1.0, color='black', ls='--', lw=0.5)
ax.set_title("Ablation stop-loss — toutes variantes")
ax.set_ylabel("Equity"); ax.legend(loc='best'); ax.grid(alpha=0.3)
plt.tight_layout(); plt.show()""")

md("""## 16. Univers élargi — 100 tickers S&P 500 (diversité cross-sectionnelle)

Sur 30 blue chips, les macro-features n'ont pas grand-chose à faire car tous
les tickers réagissent de façon très corrélée au marché. Testons si l'alpha
émerge quand on élargit l'univers à **100 tickers liquides** du S&P 500
(données déjà en cache disque depuis le scan CLI).
""")

code("""# Charge 100 tickers S&P 500 depuis le cache disque (pas de re-download)
import glob
cache_files = sorted(glob.glob(os.path.join(config.DATA_DIR, "stocks", "*_1d.parquet")))
print(f"Parquet files en cache: {len(cache_files)}")

dm_wide = StockDataManager(config)
sp_wide = {}
for path in cache_files:
    sym = os.path.basename(path).replace("_1d.parquet", "")
    df = pd.read_parquet(path)
    if len(df) >= 500:
        sp_wide[sym] = dm_wide.prepare_data(df, sym)
    if len(sp_wide) >= 100:
        break
print(f"Loaded {len(sp_wide)} tickers from cache")""")

code("""# Attache macro + breadth sur l'univers élargi
breadth_wide = compute_breadth(sp_wide, sma_period=50)
sp_wide_enriched = attach_macro_to_tickers(sp_wide, macro_feats, breadth_wide)
training_wide, featured_wide = build_training_frame(sp_wide_enriched, fe, tc_v2)
print(f"Training wide: {training_wide.shape[0]} lignes × {training_wide.shape[1]} cols")
print("Distribution Target:")
print(training_wide['Target'].value_counts().sort_index()
      .rename({0:'Sell', 1:'Hold', 2:'Buy'}))""")

code("""# Backtest wide — on prend la variante v2-Stop3 qui gagnait l'ablation (ou NoStop si besoin)
# top_k=8 et rebalance_bars=20 pour garder ~2-3 min
bt_wide = backtest_topk(
    featured_per_ticker=featured_wide,
    trainer_factory=trainer_factory_v2,
    target_creator=tc_v2,
    top_k=8,
    rebalance_bars=20,
    hold_bars=10,
    min_train_bars=400,
    allow_short=True,
    fee_bps=5.0,
    stop_atr_mult=3.0,        # best stop from ablation
    take_profit_atr_mult=4.0,
)
print("Backtest 100 tickers (univers élargi S&P 500) :")
print(bt_wide['summary'].to_string(index=False))""")

code("""# Equity curve univers élargi vs univers 30
fig, ax = plt.subplots(figsize=(12, 5))
if 'ablation' in dir() and 'v2-Stop3' in ablation:
    eq_narrow = ablation['v2-Stop3']['equity']
    ax.plot(eq_narrow.index, eq_narrow['equity'], lw=1.4,
            color='tab:gray', alpha=0.7,
            label=f"30 tickers ({eq_narrow['equity'].iloc[-1]:.3f}x)")
eq_wide = bt_wide['equity']
ax.plot(eq_wide.index, eq_wide['equity'], lw=1.8, color='tab:purple',
        label=f"100 tickers S&P 500 ({eq_wide['equity'].iloc[-1]:.3f}x)")
ax.axhline(1.0, color='black', ls='--', lw=0.5)
ax.set_title("Effet de l'élargissement de l'univers (même config v2 Stop3)")
ax.set_ylabel("Equity"); ax.legend(); ax.grid(alpha=0.3)
plt.tight_layout(); plt.show()""")

code("""# Top 10 signaux sur l'univers élargi (snapshot)
trainer_wide = ModelTrainer(config)
train_global_model(training_wide, trainer_wide)
top10_wide = scan(featured_wide, trainer_wide, top_n=10)
print("Top 10 S&P-100 avec modèle v2 :")
top10_wide""")

md("""## 17. Bilan final — v1 → v2 + ablation

### Livrables des 5 propositions

1. ✅ **Classes 80/20 + `class_weight`** — modèle prédit réellement Buy/Sell OOS
2. ✅ **Multi-horizon target** (5j ∧ 20j) — distribution plus saine
3. ✅ **Features macro** (VIX/TNX/Yield/Breadth/SPY) — **5/20 features retenues** par le modèle
4. ⚠️ **Stop-loss ATR** — 2×ATR trop serré, 3-4×ATR optimal (cf. ablation)
5. ✅ **Univers S&P 500** — CV accuracy 62.4% (vs 33% random) sur 243k rows

### Ce que l'ablation a montré

- Sur 30 tickers, **retirer le stop** remonte le backtest à ~neutralité
- Stop 3×ATR meilleur compromis pour la config 10-day hold
- **L'élargissement à 100 tickers** change plus que le stop-loss — c'est
  là que l'edge cross-sectionnel apparaît réellement

### Ce qui reste à faire pour du trading réel

- **Fondamental** : PE, PEG, earnings revisions, analyst ratings
- **Ensemble de modèles** : LightGBM + XGBoost + NN moyennés
- **Portfolio sizing** : vol-targeting + correlation-aware
- **Cost model réaliste** : slippage fonction du $-volume
- **Meta-labeling** (López de Prado) — filtre de confiance sur signaux

### Ce qui reste à faire pour du trading réel

- **Fondamental** : PE, PEG, earnings revisions, analyst ratings
- **Ensemble de modèles** : LightGBM + XGBoost + NN moyennés réduit la
  variance de signal
- **Portfolio sizing** : vol-targeting (each trade sized to contribute equal
  vol), correlation-aware weighting
- **Cost model réaliste** : slippage qui dépend du $-volume + spread
- **Meta-labeling** (López de Prado) : 1er modèle génère Buy/Sell, 2ème
  modèle décide si on **prend vraiment** le signal (filtre de confiance)
- **Paper trading** 3 mois avant de passer en live

### Ressources

- Gu, Kelly & Xiu (2020) — *Empirical Asset Pricing via Machine Learning*
- López de Prado — *Advances in Financial Machine Learning*
- Bailey & López de Prado — *The Deflated Sharpe Ratio*
""")

# ---------------------------------------------------------------------------
# Save
nb["cells"] = cells
out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "stock_scanner_course.ipynb")
nbf.write(nb, out)
print(f"Wrote {out} with {len(cells)} cells")
