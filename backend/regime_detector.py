"""
Market Regime Detection Engine for Institutional Quantitative Trading.

Markets are non-stationary dynamic systems. Static strategies (such as naive EMA crossovers)
fail predictably during regime transitions (e.g., getting chopped up in ranging consolidation,
or getting run over during high-volatility liquidity cascades).

This module classifies the market into four canonical quantitative regimes:
1. TRENDING_BULL: High ADX, +DI > -DI, Price > EMA(50). Optimal for Trend Following / Momentum.
2. TRENDING_BEAR: High ADX, -DI > +DI, Price < EMA(50). Optimal for Short Momentum / Hedging.
3. MEAN_REVERTING_CHOP: Low ADX, mid-range Bollinger Band Width. Optimal for Mean Reversion (%B, RSI).
4. HIGH_VOLATILITY_EXPANSION: Extreme ATR / BBW percentile rank (>85th). Danger of breakout/cascade;
   prioritizes Order Flow Imbalance (OFI), widens/tightens stops, and cuts risk.
"""

import math
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class MarketRegime(str, Enum):
    """Canonical market regime classifications."""
    TRENDING_BULL = "TRENDING_BULL"
    TRENDING_BEAR = "TRENDING_BEAR"
    MEAN_REVERTING_CHOP = "MEAN_REVERTING_CHOP"
    HIGH_VOLATILITY_EXPANSION = "HIGH_VOLATILITY_EXPANSION"


# Standard institutional weights for Alpha Ensemble blending per regime
REGIME_STRATEGY_WEIGHTS: Dict[str, Dict[str, float]] = {
    MarketRegime.TRENDING_BULL.value: {
        "trend": 0.60,
        "mean_reversion": 0.10,
        "order_flow": 0.30,
    },
    MarketRegime.TRENDING_BEAR.value: {
        "trend": 0.60,
        "mean_reversion": 0.10,
        "order_flow": 0.30,
    },
    MarketRegime.MEAN_REVERTING_CHOP.value: {
        "trend": 0.15,
        "mean_reversion": 0.60,
        "order_flow": 0.25,
    },
    MarketRegime.HIGH_VOLATILITY_EXPANSION.value: {
        "trend": 0.30,
        "mean_reversion": 0.20,
        "order_flow": 0.50,
    },
}

REGIME_DESCRIPTIONS: Dict[str, str] = {
    MarketRegime.TRENDING_BULL.value: (
        "Strong upward trend confirmed by ADX >= 25, +DI > -DI, and Price > EMA(50). "
        "Optimal for trend-following and momentum breakout alphas."
    ),
    MarketRegime.TRENDING_BEAR.value: (
        "Strong downward trend confirmed by ADX >= 25, -DI > +DI, and Price < EMA(50). "
        "Optimal for short momentum, hedging, and capital protection."
    ),
    MarketRegime.MEAN_REVERTING_CHOP.value: (
        "Non-directional consolidation range (ADX < 20, moderate volatility width). "
        "Trend alphas fail here; optimal for Bollinger %B and RSI mean reversion."
    ),
    MarketRegime.HIGH_VOLATILITY_EXPANSION.value: (
        "Extreme volatility surge (ATR or BBW > 85th percentile rank). "
        "High danger of flash crash or violent breakout; priority shifts to order flow imbalance."
    ),
}


@dataclass
class RegimeAnalysis:
    """Quantitative summary of market regime analysis."""
    current_regime: str
    adx: float
    di_plus: float
    di_minus: float
    bb_width_pct: float
    atr_pct: float
    strategy_weights: Dict[str, float]
    bb_width: float = 0.0
    atr: float = 0.0
    ema_50: float = 0.0
    current_price: float = 0.0
    confidence: float = 1.0
    reason: str = ""
    timestamp: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serializes dataclass to a plain dictionary for JSON/WebSocket dispatch."""
        return {
            "current_regime": str(self.current_regime),
            "adx": round(self.adx, 2),
            "di_plus": round(self.di_plus, 2),
            "di_minus": round(self.di_minus, 2),
            "bb_width_pct": round(self.bb_width_pct, 2),
            "atr_pct": round(self.atr_pct, 2),
            "strategy_weights": {k: round(v, 4) for k, v in self.strategy_weights.items()},
            "bb_width": round(self.bb_width, 6),
            "atr": round(self.atr, 4),
            "ema_50": round(self.ema_50, 4),
            "current_price": round(self.current_price, 4),
            "confidence": round(self.confidence, 4),
            "reason": self.reason,
            "timestamp": self.timestamp,
        }


# =====================================================================
# Core Mathematical Indicators (Pure Python / Zero C-Extension Overhead)
# =====================================================================

def _extract_bar_ohlcv(bars: List[Dict[str, Any]]) -> Tuple[List[float], List[float], List[float], List[float], List[float]]:
    """Extracts High, Low, Close, Open, Volume series supporting both short and long key names."""
    highs: List[float] = []
    lows: List[float] = []
    closes: List[float] = []
    opens: List[float] = []
    volumes: List[float] = []

    for b in bars:
        h = float(b.get("h", b.get("high", 0.0)))
        l = float(b.get("l", b.get("low", 0.0)))
        c = float(b.get("c", b.get("close", 0.0)))
        o = float(b.get("o", b.get("open", c)))
        v = float(b.get("v", b.get("volume", 0.0)))

        # Sanitize zero or inverted bars
        if h < l:
            h, l = l, h
        if h == 0.0 and c > 0.0:
            h = c
        if l == 0.0 and c > 0.0:
            l = c

        highs.append(h)
        lows.append(l)
        closes.append(c)
        opens.append(o)
        volumes.append(v)

    return highs, lows, closes, opens, volumes


def calculate_ema(prices: List[float], period: int = 50) -> List[float]:
    """Computes Exponential Moving Average (EMA) for a price series."""
    if not prices:
        return []
    if len(prices) < period:
        sma = sum(prices) / len(prices)
        return [sma] * len(prices)

    k = 2.0 / (period + 1)
    ema_series: List[float] = []

    # Seed with initial SMA
    initial_sma = sum(prices[:period]) / period
    for _ in range(period - 1):
        ema_series.append(initial_sma)
    ema_series.append(initial_sma)

    curr_ema = initial_sma
    for price in prices[period:]:
        curr_ema = (price * k) + (curr_ema * (1.0 - k))
        ema_series.append(curr_ema)

    return ema_series


def calculate_bollinger_bands(
    prices: List[float], period: int = 20, num_std: float = 2.0
) -> Tuple[List[float], List[float], List[float], List[float]]:
    """
    Computes Bollinger Bands:
    - Upper Band = SMA + (num_std * std_dev)
    - Lower Band = SMA - (num_std * std_dev)
    - Band Width (BBW) = (Upper - Lower) / SMA
    Returns: (upper_bands, middle_bands, lower_bands, bbw_series)
    """
    if not prices:
        return [], [], [], []

    n = len(prices)
    upper_bands: List[float] = []
    middle_bands: List[float] = []
    lower_bands: List[float] = []
    bbw_series: List[float] = []

    for i in range(n):
        if i < period - 1:
            window = prices[: i + 1]
        else:
            window = prices[i - period + 1 : i + 1]

        sma = sum(window) / len(window)
        if len(window) > 1:
            variance = sum((x - sma) ** 2 for x in window) / len(window)
            std_dev = math.sqrt(max(0.0, variance))
        else:
            std_dev = 0.0

        upper = sma + (num_std * std_dev)
        lower = sma - (num_std * std_dev)
        bbw = ((upper - lower) / sma) if sma > 0.0 else 0.0

        upper_bands.append(upper)
        middle_bands.append(sma)
        lower_bands.append(lower)
        bbw_series.append(bbw)

    return upper_bands, middle_bands, lower_bands, bbw_series


def calculate_atr(bars: List[Dict[str, Any]], period: int = 14) -> List[float]:
    """Computes Average True Range (ATR) across bars using Wilder's smoothing."""
    if not bars:
        return []

    highs, lows, closes, _, _ = _extract_bar_ohlcv(bars)
    n = len(bars)
    tr_series: List[float] = []

    for i in range(n):
        if i == 0:
            tr = highs[0] - lows[0]
        else:
            prev_close = closes[i - 1]
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - prev_close),
                abs(lows[i] - prev_close),
            )
        tr_series.append(tr)

    if n < period:
        avg_tr = sum(tr_series) / max(1, len(tr_series))
        return [avg_tr] * n

    atr_series: List[float] = []
    initial_atr = sum(tr_series[:period]) / period
    for _ in range(period - 1):
        atr_series.append(initial_atr)
    atr_series.append(initial_atr)

    curr_atr = initial_atr
    for tr in tr_series[period:]:
        curr_atr = (curr_atr * (period - 1) + tr) / period
        atr_series.append(curr_atr)

    return atr_series


def calculate_adx(
    bars: List[Dict[str, Any]], period: int = 14
) -> Tuple[List[float], List[float], List[float]]:
    """
    Computes Wilder's DMI system:
    - +DI (Plus Directional Indicator)
    - -DI (Minus Directional Indicator)
    - ADX (Average Directional Index)

    Returns: (adx_series, di_plus_series, di_minus_series)
    """
    n = len(bars)
    if n < 2:
        return [0.0] * n, [0.0] * n, [0.0] * n

    highs, lows, closes, _, _ = _extract_bar_ohlcv(bars)

    tr_list: List[float] = [highs[0] - lows[0]]
    dm_plus_list: List[float] = [0.0]
    dm_minus_list: List[float] = [0.0]

    for i in range(1, n):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        up_move = highs[i] - highs[i - 1]
        down_move = lows[i - 1] - lows[i]

        dm_plus = up_move if (up_move > down_move and up_move > 0.0) else 0.0
        dm_minus = down_move if (down_move > up_move and down_move > 0.0) else 0.0

        tr_list.append(tr)
        dm_plus_list.append(dm_plus)
        dm_minus_list.append(dm_minus)

    # Initial sums over first 'period' elements
    effective_period = min(period, n)
    smooth_tr = sum(tr_list[:effective_period])
    smooth_dm_plus = sum(dm_plus_list[:effective_period])
    smooth_dm_minus = sum(dm_minus_list[:effective_period])

    di_plus_series: List[float] = []
    di_minus_series: List[float] = []
    dx_series: List[float] = []

    def compute_di_dx(s_tr: float, s_plus: float, s_minus: float) -> Tuple[float, float, float]:
        if s_tr <= 0.0:
            return 0.0, 0.0, 0.0
        di_p = 100.0 * (s_plus / s_tr)
        di_m = 100.0 * (s_minus / s_tr)
        di_sum = di_p + di_m
        dx = (100.0 * abs(di_p - di_m) / di_sum) if di_sum > 0.0 else 0.0
        return di_p, di_m, dx

    # Seed initial period
    p_di, m_di, initial_dx = compute_di_dx(smooth_tr, smooth_dm_plus, smooth_dm_minus)
    for _ in range(effective_period):
        di_plus_series.append(p_di)
        di_minus_series.append(m_di)
        dx_series.append(initial_dx)

    # Wilder's smoothing for subsequent bars
    for i in range(effective_period, n):
        smooth_tr = smooth_tr - (smooth_tr / period) + tr_list[i]
        smooth_dm_plus = smooth_dm_plus - (smooth_dm_plus / period) + dm_plus_list[i]
        smooth_dm_minus = smooth_dm_minus - (smooth_dm_minus / period) + dm_minus_list[i]

        p_di, m_di, dx = compute_di_dx(smooth_tr, smooth_dm_plus, smooth_dm_minus)
        di_plus_series.append(p_di)
        di_minus_series.append(m_di)
        dx_series.append(dx)

    # Now smooth DX to compute ADX
    adx_series: List[float] = []
    if n < period * 2:
        # Graceful fallback: return simple moving average of available DX values
        cum_adx = 0.0
        for idx, dx in enumerate(dx_series):
            cum_adx += dx
            adx_series.append(cum_adx / (idx + 1))
    else:
        adx_seed = sum(dx_series[:period]) / period
        for _ in range(period - 1):
            adx_series.append(adx_seed)
        adx_series.append(adx_seed)

        curr_adx = adx_seed
        for dx in dx_series[period:]:
            curr_adx = ((curr_adx * (period - 1)) + dx) / period
            adx_series.append(curr_adx)

    # Ensure all series have identical length matching n
    adx_series = (adx_series + [0.0] * n)[:n]
    di_plus_series = (di_plus_series + [0.0] * n)[:n]
    di_minus_series = (di_minus_series + [0.0] * n)[:n]

    return adx_series, di_plus_series, di_minus_series


def calculate_percentile_rank(values: List[float], current_val: float) -> float:
    """
    Computes historical mid-point percentile rank (0.0 to 100.0) of current_val
    relative to historical values window.
    """
    if not values:
        return 50.0

    val_min = min(values)
    val_max = max(values)
    if abs(val_max - val_min) < 1e-6:
        return 50.0

    count_below = sum(1 for v in values if v < current_val)
    count_equal = sum(1 for v in values if abs(v - current_val) < 1e-6)
    percentile = ((count_below + 0.5 * count_equal) / len(values)) * 100.0
    return max(0.0, min(100.0, percentile))


# =====================================================================
# Market Regime Detector Class
# =====================================================================

class MarketRegimeDetector:
    """
    Institutional Market Regime Detection Engine.

    Continuously evaluates:
    - ADX(14), +DI, -DI for directional trend strength.
    - Bollinger Band Width (BBW) & ATR percentile ranks to detect volatility squeezes vs expansions.
    - EMA(50) for structural price trend direction.

    Outputs RegimeAnalysis with dynamic multi-alpha ensemble weights.
    """

    def __init__(
        self,
        adx_period: int = 14,
        bb_period: int = 20,
        bb_std: float = 2.0,
        atr_period: int = 14,
        ema_period: int = 50,
        percentile_lookback: int = 100,
    ):
        self.adx_period = adx_period
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.atr_period = atr_period
        self.ema_period = ema_period
        self.percentile_lookback = percentile_lookback

    def detect_regime(self, bars: List[Dict[str, Any]]) -> RegimeAnalysis:
        """
        Classifies current market regime from historical bar sequence.
        Bars should be ordered oldest -> newest.
        """
        if not bars:
            return RegimeAnalysis(
                current_regime=MarketRegime.MEAN_REVERTING_CHOP.value,
                adx=0.0,
                di_plus=0.0,
                di_minus=0.0,
                bb_width_pct=50.0,
                atr_pct=50.0,
                strategy_weights=REGIME_STRATEGY_WEIGHTS[MarketRegime.MEAN_REVERTING_CHOP.value],
                bb_width=0.0,
                atr=0.0,
                ema_50=0.0,
                current_price=0.0,
                confidence=0.5,
                reason="Insufficient historical bars; defaulted to neutral mean reversion chop.",
            )

        highs, lows, closes, _, _ = _extract_bar_ohlcv(bars)
        current_price = closes[-1]
        last_bar = bars[-1]
        timestamp = last_bar.get("t", last_bar.get("timestamp", None))

        # 1. Directional Trend Strength (ADX, +DI, -DI)
        adx_series, di_plus_series, di_minus_series = calculate_adx(bars, period=self.adx_period)
        latest_adx = adx_series[-1] if adx_series else 0.0
        latest_di_plus = di_plus_series[-1] if di_plus_series else 0.0
        latest_di_minus = di_minus_series[-1] if di_minus_series else 0.0

        # 2. Bollinger Band Width & Historical Percentile Rank
        _, _, _, bbw_series = calculate_bollinger_bands(
            closes, period=self.bb_period, num_std=self.bb_std
        )
        latest_bbw = bbw_series[-1] if bbw_series else 0.0
        bbw_window = bbw_series[-self.percentile_lookback:] if bbw_series else [latest_bbw]
        bbw_pct = calculate_percentile_rank(bbw_window, latest_bbw)

        # 3. ATR Volatility & Historical Percentile Rank
        atr_series = calculate_atr(bars, period=self.atr_period)
        latest_atr = atr_series[-1] if atr_series else 0.0
        atr_window = atr_series[-self.percentile_lookback:] if atr_series else [latest_atr]
        atr_pct = calculate_percentile_rank(atr_window, latest_atr)

        # 4. Structural Trend Baseline (EMA 50)
        ema_series = calculate_ema(closes, period=self.ema_period)
        latest_ema50 = ema_series[-1] if ema_series else current_price

        # =================================================================
        # Regime Classification Decision Matrix
        # =================================================================
        regime: str
        confidence: float
        reason: str

        # Rule 1: Trending Bull
        # ADX >= 25, +DI > -DI, Price >= EMA(50)
        if latest_adx >= 25.0 and (latest_di_plus > latest_di_minus) and (current_price >= latest_ema50):
            regime = MarketRegime.TRENDING_BULL.value
            adx_factor = min(1.0, (latest_adx - 25.0) / 25.0)
            di_spread = max(0.0, min(1.0, (latest_di_plus - latest_di_minus) / 50.0))
            confidence = 0.70 + 0.15 * adx_factor + 0.15 * di_spread
            reason = (
                f"Bullish trend confirmed: ADX ({latest_adx:.1f}) >= 25, "
                f"+DI ({latest_di_plus:.1f}) > -DI ({latest_di_minus:.1f}), "
                f"and Price ({current_price:.2f}) >= EMA50 ({latest_ema50:.2f})."
            )

        # Rule 2: Trending Bear
        # ADX >= 25, -DI > +DI, Price <= EMA(50)
        elif latest_adx >= 25.0 and (latest_di_minus > latest_di_plus) and (current_price <= latest_ema50):
            regime = MarketRegime.TRENDING_BEAR.value
            adx_factor = min(1.0, (latest_adx - 25.0) / 25.0)
            di_spread = max(0.0, min(1.0, (latest_di_minus - latest_di_plus) / 50.0))
            confidence = 0.70 + 0.15 * adx_factor + 0.15 * di_spread
            reason = (
                f"Bearish trend confirmed: ADX ({latest_adx:.1f}) >= 25, "
                f"-DI ({latest_di_minus:.1f}) > +DI ({latest_di_plus:.1f}), "
                f"and Price ({current_price:.2f}) <= EMA50 ({latest_ema50:.2f})."
            )

        # Rule 3: High Volatility Expansion
        # Severe volatility expansion confirmed across both ATR and BBW percentiles without directional trend.
        elif (atr_pct >= 85.0 and bbw_pct >= 80.0) or (atr_pct >= 90.0 and bbw_pct >= 75.0):
            regime = MarketRegime.HIGH_VOLATILITY_EXPANSION.value
            max_pct = max(atr_pct, bbw_pct)
            confidence = min(1.0, 0.70 + (max_pct - 85.0) / 50.0)
            reason = (
                f"High volatility expansion triggered: ATR percentile ({atr_pct:.1f}%) "
                f"or BBW percentile ({bbw_pct:.1f}%) exceeds 85th percentile. "
                f"Prioritizing order flow imbalance & tightening stops."
            )

        # Rule 4: Mean Reverting Chop
        # ADX < 20 and BBW percentile between 20th and 60th percentile
        elif latest_adx < 20.0 and (20.0 <= bbw_pct <= 60.0):
            regime = MarketRegime.MEAN_REVERTING_CHOP.value
            adx_chop_factor = max(0.0, (20.0 - latest_adx) / 20.0)
            confidence = 0.65 + 0.35 * adx_chop_factor
            reason = (
                f"Mean reverting chop detected: ADX ({latest_adx:.1f}) < 20 and "
                f"BBW percentile ({bbw_pct:.1f}%) in range [20%, 60%]. "
                f"Optimal for RSI & Bollinger %B reversals."
            )

        # Rule 5: Transitional / Intermediate Regimes
        else:
            if latest_adx >= 25.0:
                if latest_di_plus >= latest_di_minus:
                    regime = MarketRegime.TRENDING_BULL.value
                    confidence = 0.65
                    reason = (
                        f"Trending Bull (ADX {latest_adx:.1f} >= 25 with +DI > -DI; "
                        f"Price hovering relative to EMA50)."
                    )
                else:
                    regime = MarketRegime.TRENDING_BEAR.value
                    confidence = 0.65
                    reason = (
                        f"Trending Bear (ADX {latest_adx:.1f} >= 25 with -DI > +DI; "
                        f"Price hovering relative to EMA50)."
                    )
            elif bbw_pct < 20.0:
                regime = MarketRegime.MEAN_REVERTING_CHOP.value
                confidence = 0.60
                reason = (
                    f"Volatility squeeze (BBW percentile {bbw_pct:.1f}% < 20th). "
                    f"Low momentum consolidation range."
                )
            elif latest_adx > 20.0 and (latest_di_plus > latest_di_minus) and (current_price > latest_ema50):
                regime = MarketRegime.TRENDING_BULL.value
                confidence = 0.60
                reason = f"Emerging bullish trend (ADX {latest_adx:.1f}, +DI > -DI, Price > EMA50)."
            elif latest_adx > 20.0 and (latest_di_minus > latest_di_plus) and (current_price < latest_ema50):
                regime = MarketRegime.TRENDING_BEAR.value
                confidence = 0.60
                reason = f"Emerging bearish trend (ADX {latest_adx:.1f}, -DI > +DI, Price < EMA50)."
            else:
                regime = MarketRegime.MEAN_REVERTING_CHOP.value
                confidence = 0.55
                reason = (
                    f"Consolidation baseline: ADX ({latest_adx:.1f}) and BBW ({bbw_pct:.1f}%) "
                    f"indicate non-trending market conditions."
                )

        weights = REGIME_STRATEGY_WEIGHTS.get(
            regime, REGIME_STRATEGY_WEIGHTS[MarketRegime.MEAN_REVERTING_CHOP.value]
        )

        return RegimeAnalysis(
            current_regime=regime,
            adx=latest_adx,
            di_plus=latest_di_plus,
            di_minus=latest_di_minus,
            bb_width_pct=bbw_pct,
            atr_pct=atr_pct,
            strategy_weights=weights,
            bb_width=latest_bbw,
            atr=latest_atr,
            ema_50=latest_ema50,
            current_price=current_price,
            confidence=confidence,
            reason=reason,
            timestamp=str(timestamp) if timestamp else None,
        )

    def analyze(self, bars: List[Dict[str, Any]]) -> RegimeAnalysis:
        """Alias for detect_regime."""
        return self.detect_regime(bars)

    @staticmethod
    def get_strategy_weights(regime: str) -> Dict[str, float]:
        """Returns the canonical strategy weights for a given regime name."""
        return REGIME_STRATEGY_WEIGHTS.get(
            regime, REGIME_STRATEGY_WEIGHTS[MarketRegime.MEAN_REVERTING_CHOP.value]
        )

    @staticmethod
    def get_description(regime: str) -> str:
        """Returns detailed institutional explanation of the regime."""
        return REGIME_DESCRIPTIONS.get(regime, "Custom or unclassified regime.")


# Convenience module-level singleton instance
regime_detector = MarketRegimeDetector()


def detect_market_regime(bars: List[Dict[str, Any]]) -> RegimeAnalysis:
    """Convenience functional interface for one-off regime classification."""
    return regime_detector.detect_regime(bars)