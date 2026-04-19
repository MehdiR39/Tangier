"""
Candlestick patterns — 15 classical patterns as binary features.

Pure pandas implementation (no talib). Each pattern returns a boolean
Series (1 when pattern detected at bar t, 0 otherwise).

Pattern categories :
  1-bar (5) : Doji, Hammer, Shooting Star, Marubozu, Spinning Top
  2-bar (6) : Bullish/Bearish Engulfing, Bullish/Bearish Harami,
              Piercing Line, Dark Cloud Cover
  3-bar (4) : Morning Star, Evening Star, Three White Soldiers,
              Three Black Crows

All patterns are emitted as integer 0/1 columns — easy for LightGBM to
use as splitting variables.
"""

import logging
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper geometry
# ---------------------------------------------------------------------------
def _body(O: pd.Series, C: pd.Series) -> pd.Series:
    return (C - O).abs()


def _range(H: pd.Series, L: pd.Series) -> pd.Series:
    return (H - L).replace(0, np.nan)


def _upper_shadow(O: pd.Series, C: pd.Series, H: pd.Series) -> pd.Series:
    return H - np.maximum(O, C)


def _lower_shadow(O: pd.Series, C: pd.Series, L: pd.Series) -> pd.Series:
    return np.minimum(O, C) - L


def _is_bull(O: pd.Series, C: pd.Series) -> pd.Series:
    return C > O


def _is_bear(O: pd.Series, C: pd.Series) -> pd.Series:
    return C < O


# ---------------------------------------------------------------------------
# 1-bar patterns
# ---------------------------------------------------------------------------
def pattern_doji(O, H, L, C) -> pd.Series:
    """Body tiny vs range → indécision."""
    body = _body(O, C)
    rng = _range(H, L)
    return (body <= 0.1 * rng).astype(int).fillna(0)


def pattern_hammer(O, H, L, C) -> pd.Series:
    """Petit body, longue ombre basse, peu d'ombre haute → reversal haussier."""
    body = _body(O, C)
    rng = _range(H, L)
    upper = _upper_shadow(O, C, H)
    lower = _lower_shadow(O, C, L)
    cond = (
        (body <= 0.35 * rng) &
        (lower >= 2 * body) &
        (upper <= 0.3 * body)
    )
    return cond.astype(int).fillna(0)


def pattern_shooting_star(O, H, L, C) -> pd.Series:
    """Petit body, longue ombre haute, peu d'ombre basse → reversal baissier."""
    body = _body(O, C)
    rng = _range(H, L)
    upper = _upper_shadow(O, C, H)
    lower = _lower_shadow(O, C, L)
    cond = (
        (body <= 0.35 * rng) &
        (upper >= 2 * body) &
        (lower <= 0.3 * body)
    )
    return cond.astype(int).fillna(0)


def pattern_marubozu(O, H, L, C) -> pd.Series:
    """Bougie quasi sans ombre — conviction pure."""
    body = _body(O, C)
    rng = _range(H, L)
    return (body >= 0.95 * rng).astype(int).fillna(0)


def pattern_spinning_top(O, H, L, C) -> pd.Series:
    """Petit body, ombres des deux côtés → indécision avec volatilité."""
    body = _body(O, C)
    rng = _range(H, L)
    upper = _upper_shadow(O, C, H)
    lower = _lower_shadow(O, C, L)
    cond = (
        (body <= 0.3 * rng) &
        (upper > body) &
        (lower > body)
    )
    return cond.astype(int).fillna(0)


# ---------------------------------------------------------------------------
# 2-bar patterns
# ---------------------------------------------------------------------------
def pattern_bullish_engulfing(O, H, L, C) -> pd.Series:
    """Bougie verte qui avale le body de la rouge précédente."""
    prev_bear = _is_bear(O.shift(1), C.shift(1))
    curr_bull = _is_bull(O, C)
    engulf = (O <= C.shift(1)) & (C >= O.shift(1))
    curr_body_bigger = _body(O, C) > _body(O.shift(1), C.shift(1))
    return (prev_bear & curr_bull & engulf & curr_body_bigger).astype(int).fillna(0)


def pattern_bearish_engulfing(O, H, L, C) -> pd.Series:
    """Bougie rouge qui avale le body de la verte précédente."""
    prev_bull = _is_bull(O.shift(1), C.shift(1))
    curr_bear = _is_bear(O, C)
    engulf = (O >= C.shift(1)) & (C <= O.shift(1))
    curr_body_bigger = _body(O, C) > _body(O.shift(1), C.shift(1))
    return (prev_bull & curr_bear & engulf & curr_body_bigger).astype(int).fillna(0)


def pattern_bullish_harami(O, H, L, C) -> pd.Series:
    """Après rouge large, petite bougie verte contenue dans le body."""
    prev_bear = _is_bear(O.shift(1), C.shift(1))
    curr_bull = _is_bull(O, C)
    prev_body = _body(O.shift(1), C.shift(1))
    curr_body = _body(O, C)
    contained = (O >= C.shift(1)) & (C <= O.shift(1))
    smaller = curr_body < 0.6 * prev_body
    return (prev_bear & curr_bull & contained & smaller).astype(int).fillna(0)


def pattern_bearish_harami(O, H, L, C) -> pd.Series:
    """Après verte large, petite bougie rouge contenue dans le body."""
    prev_bull = _is_bull(O.shift(1), C.shift(1))
    curr_bear = _is_bear(O, C)
    prev_body = _body(O.shift(1), C.shift(1))
    curr_body = _body(O, C)
    contained = (O <= C.shift(1)) & (C >= O.shift(1))
    smaller = curr_body < 0.6 * prev_body
    return (prev_bull & curr_bear & contained & smaller).astype(int).fillna(0)


def pattern_piercing_line(O, H, L, C) -> pd.Series:
    """Reversal bullish : ouvre sous le low de la rouge, ferme au-dessus du mid."""
    prev_bear = _is_bear(O.shift(1), C.shift(1))
    curr_bull = _is_bull(O, C)
    gap_down = O < L.shift(1)
    prev_mid = (O.shift(1) + C.shift(1)) / 2
    closes_above_mid = (C > prev_mid) & (C < O.shift(1))
    return (prev_bear & curr_bull & gap_down & closes_above_mid).astype(int).fillna(0)


def pattern_dark_cloud_cover(O, H, L, C) -> pd.Series:
    """Reversal bearish : ouvre au-dessus du high de la verte, ferme sous le mid."""
    prev_bull = _is_bull(O.shift(1), C.shift(1))
    curr_bear = _is_bear(O, C)
    gap_up = O > H.shift(1)
    prev_mid = (O.shift(1) + C.shift(1)) / 2
    closes_below_mid = (C < prev_mid) & (C > O.shift(1))
    return (prev_bull & curr_bear & gap_up & closes_below_mid).astype(int).fillna(0)


# ---------------------------------------------------------------------------
# 3-bar patterns
# ---------------------------------------------------------------------------
def pattern_morning_star(O, H, L, C) -> pd.Series:
    """
    Reversal haussier en 3 bougies :
      1. grande rouge
      2. petit body gap down (doji/spinning)
      3. grande verte qui clôture dans le body de la 1ère
    """
    first_bear = _is_bear(O.shift(2), C.shift(2)) & (_body(O.shift(2), C.shift(2)) > 0.5 * _range(H.shift(2), L.shift(2)))
    second_small = _body(O.shift(1), C.shift(1)) < 0.3 * _body(O.shift(2), C.shift(2))
    gap_down = np.maximum(O.shift(1), C.shift(1)) < C.shift(2)
    third_bull = _is_bull(O, C) & (_body(O, C) > 0.5 * _range(H, L))
    closes_in_first_body = C > (O.shift(2) + C.shift(2)) / 2
    cond = first_bear & second_small & gap_down & third_bull & closes_in_first_body
    return cond.astype(int).fillna(0)


def pattern_evening_star(O, H, L, C) -> pd.Series:
    """Reversal baissier, miroir du morning star."""
    first_bull = _is_bull(O.shift(2), C.shift(2)) & (_body(O.shift(2), C.shift(2)) > 0.5 * _range(H.shift(2), L.shift(2)))
    second_small = _body(O.shift(1), C.shift(1)) < 0.3 * _body(O.shift(2), C.shift(2))
    gap_up = np.minimum(O.shift(1), C.shift(1)) > C.shift(2)
    third_bear = _is_bear(O, C) & (_body(O, C) > 0.5 * _range(H, L))
    closes_in_first_body = C < (O.shift(2) + C.shift(2)) / 2
    cond = first_bull & second_small & gap_up & third_bear & closes_in_first_body
    return cond.astype(int).fillna(0)


def pattern_three_white_soldiers(O, H, L, C) -> pd.Series:
    """3 vertes consécutives, chacune ouvrant dans le body précédent et clôturant près du high."""
    b1 = _is_bull(O.shift(2), C.shift(2))
    b2 = _is_bull(O.shift(1), C.shift(1))
    b3 = _is_bull(O, C)
    # Chaque bougie ouvre dans le body précédent
    open_in_prev = (O.shift(1) >= O.shift(2)) & (O.shift(1) <= C.shift(2)) & \
                    (O >= O.shift(1)) & (O <= C.shift(1))
    # Chaque close > close précédent
    higher_close = (C.shift(1) > C.shift(2)) & (C > C.shift(1))
    # Petits upper shadows (clôture près du high)
    short_shadow = (_upper_shadow(O, C, H) < 0.3 * _body(O, C))
    return (b1 & b2 & b3 & open_in_prev & higher_close & short_shadow).astype(int).fillna(0)


def pattern_three_black_crows(O, H, L, C) -> pd.Series:
    """3 rouges consécutives, miroir des three white soldiers."""
    b1 = _is_bear(O.shift(2), C.shift(2))
    b2 = _is_bear(O.shift(1), C.shift(1))
    b3 = _is_bear(O, C)
    open_in_prev = (O.shift(1) <= O.shift(2)) & (O.shift(1) >= C.shift(2)) & \
                    (O <= O.shift(1)) & (O >= C.shift(1))
    lower_close = (C.shift(1) < C.shift(2)) & (C < C.shift(1))
    short_shadow = (_lower_shadow(O, C, L) < 0.3 * _body(O, C))
    return (b1 & b2 & b3 & open_in_prev & lower_close & short_shadow).astype(int).fillna(0)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
PATTERN_REGISTRY = {
    # 1-bar
    "Pattern_Doji":             pattern_doji,
    "Pattern_Hammer":           pattern_hammer,
    "Pattern_ShootingStar":     pattern_shooting_star,
    "Pattern_Marubozu":         pattern_marubozu,
    "Pattern_SpinningTop":      pattern_spinning_top,
    # 2-bar
    "Pattern_BullEngulfing":    pattern_bullish_engulfing,
    "Pattern_BearEngulfing":    pattern_bearish_engulfing,
    "Pattern_BullHarami":       pattern_bullish_harami,
    "Pattern_BearHarami":       pattern_bearish_harami,
    "Pattern_PiercingLine":     pattern_piercing_line,
    "Pattern_DarkCloudCover":   pattern_dark_cloud_cover,
    # 3-bar
    "Pattern_MorningStar":      pattern_morning_star,
    "Pattern_EveningStar":      pattern_evening_star,
    "Pattern_3WhiteSoldiers":   pattern_three_white_soldiers,
    "Pattern_3BlackCrows":      pattern_three_black_crows,
}


def add_all_patterns(data: pd.DataFrame) -> pd.DataFrame:
    """
    Add all 15 candlestick pattern columns to the DataFrame.
    Requires columns : Open, High, Low, Close.
    """
    df = data.copy()
    O, H, L, C = df["Open"], df["High"], df["Low"], df["Close"]
    for name, func in PATTERN_REGISTRY.items():
        try:
            df[name] = func(O, H, L, C)
        except Exception as e:
            logger.warning(f"pattern {name} failed: {e}")
            df[name] = 0
    return df


def pattern_frequency_table(data_dict: dict) -> pd.DataFrame:
    """
    Utility for sanity check — how often does each pattern fire per ticker?
    Expects dict of {ticker: DataFrame with pattern cols}.
    """
    rows = []
    for sym, df in data_dict.items():
        cols = [c for c in df.columns if c.startswith("Pattern_")]
        counts = {c: int(df[c].sum()) for c in cols}
        counts["ticker"] = sym
        counts["n_bars"] = len(df)
        rows.append(counts)
    return pd.DataFrame(rows)
