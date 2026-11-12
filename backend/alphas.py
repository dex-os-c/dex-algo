"""
Institutional Multi-Alpha Quantitative Ensemble
===============================================
Three orthogonal, mathematically distinct alpha strategies:
1. Adaptive Trend (Donchian breakout + SuperTrend/EMA + volume confirmation + HTF filter).
2. Squeeze Mean-Reversion (BB %B extremes + 2-period RSI + VWAP reversion, strictly gated to low-vol squeeze).
3. Order Flow Breakout Continuation (Aggressive taker buy/sell volume delta imbalance + CVD).

Ensemble combines signals via dynamic regime-conditioned weights and enforces
strict liquidity and higher-timeframe directional bias filters.
"""

import math
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, asdict
from enum import Enum

from features import BarFeatures
from regime import MarketRegime, RegimeState


class SignalAction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class AlphaSignal:
    timestamp: str
    action: SignalAction
    composite_score: float      # Normalized between -1.0 and +1.0
    confidence: float           # 0.0 to 1.0
    trend_score: float          # Alpha 1: -1.0 to +1.0
    mean_rev_score: float       # Alpha 2: -1.0 to +1.0
    breakout_score: float       # Alpha 3: -1.0 to +1.0
    active_regime: str
    regime_weights: Dict[str, float]
    filters_passed: bool
    rejection_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "action": self.action.value,
            "composite_score": round(self.composite_score, 4),
            "confidence": round(self.confidence, 4),
            "alpha_scores": {
                "trend": round(self.trend_score, 4),
                "mean_reversion": round(self.mean_rev_score, 4),
                "breakout": round(self.breakout_score, 4)
            },
            "active_regime": self.active_regime,
            "regime_weights": {k: round(v, 4) for k, v in self.regime_weights.items()},
            "filters_passed": self.filters_passed,
            "rejection_reason": self.rejection_reason
        }


# ==============================================================================
# Helper Indicator: 2-Period RSI
# ==============================================================================

def calculate_2period_rsi(closes: List[float]) -> float:
    """Ultra-responsive 2-period RSI for mean-reversion exhaustion."""
    if len(closes) < 3:
        return 50.0
    gains = []
    losses = []
    for i in range(-2, 0):
        change = closes[i] - closes[i - 1]
        if change > 0:
            gains.append(change)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(abs(change))
    avg_gain = sum(gains) / 2.0
    avg_loss = sum(losses) / 2.0
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


# ==============================================================================
# Alpha 1: Adaptive Trend Strategy
# ==============================================================================

class AdaptiveTrendAlpha:
    """
    Captures multi-day persistent trends using Donchian breakout + EMA alignment
    with volume confirmation and higher-timeframe trend filter.
    """

    @staticmethod
    def evaluate(f: BarFeatures) -> float:
        # Strict trend filter: trend alpha is deactivated during choppy/non-trending markets
        if f.adx < 25.0:
            return 0.0

        score = 0.0

        # Bullish trend condition:
        # Close at or above Donchian Upper, Fast EMA > Slow EMA, +DI > -DI
        is_bull_break = (f.close >= (f.donchian_high * 0.998)) and (f.ema_fast >= f.ema_slow) and (f.plus_di > f.minus_di)
        is_bear_break = (f.close <= (f.donchian_low * 1.002)) and (f.ema_fast <= f.ema_slow) and (f.minus_di > f.plus_di)

        if is_bull_break:
            score = 0.70
            # Volume surge confirmation bonus
            if f.volume_delta_ratio > 0.15:
                score += 0.30
        elif is_bear_break:
            score = -0.70
            if f.volume_delta_ratio < -0.15:
                score -= 0.30

        return max(-1.0, min(1.0, score))


# ==============================================================================
# Alpha 2: Squeeze Mean-Reversion Strategy
# ==============================================================================

class SqueezeMeanReversionAlpha:
    """
    Exploits price exhaustion at Bollinger Band extremes strictly during
    low-volatility compression regimes (ADX < 22, BBW < 35%).
    In trending or breakout regimes, this alpha is strictly deactivated (0.0).
    """

    @staticmethod
    def evaluate(f: BarFeatures, regime: MarketRegime, rsi_2p: float = 50.0) -> float:
        # Strict gate: do not mean-revert in trending or breakout regimes!
        if regime != MarketRegime.LOW_VOL_COMPRESSION:
            return 0.0

        band_width = max(1e-5, f.bb_upper - f.bb_lower)
        pct_b = (f.close - f.bb_lower) / band_width

        score = 0.0
        # Long Mean-Reversion: Price pierced lower band and oversold
        if pct_b < 0.10 and (rsi_2p < 20.0 or f.vwap_zscore < -1.2):
            oversold_intensity = min(1.0, (0.10 - pct_b) / 0.10 + (20.0 - rsi_2p) / 20.0)
            score = 0.60 + 0.40 * oversold_intensity
        # Short Mean-Reversion: Price pierced upper band and overbought
        elif pct_b > 0.90 and (rsi_2p > 80.0 or f.vwap_zscore > 1.2):
            overbought_intensity = min(1.0, (pct_b - 0.90) / 0.10 + (rsi_2p - 80.0) / 20.0)
            score = -(0.60 + 0.40 * overbought_intensity)

        return max(-1.0, min(1.0, score))


# ==============================================================================
# Alpha 3: Order Flow Breakout Continuation Strategy
# ==============================================================================

class OrderFlowBreakoutAlpha:
    """
    Detects aggressive taker buying or selling imbalances with expanding volatility.
    """

    @staticmethod
    def evaluate(f: BarFeatures) -> float:
        # Significant buyer/seller imbalance in recent bars
        imbalance = f.volume_delta_ratio  # between -1.0 and +1.0

        if abs(imbalance) < 0.20:
            return 0.0

        score = 0.0
        if imbalance >= 0.25 and f.vwap_zscore > 0.3:
            # Bullish order flow thrust
            score = min(1.0, 0.50 + (imbalance / 0.75) * 0.50)
        elif imbalance <= -0.25 and f.vwap_zscore < -0.3:
            # Bearish order flow dump
            score = max(-1.0, -0.50 + (imbalance / 0.75) * 0.50)

        return max(-1.0, min(1.0, score))


# ==============================================================================
# Master Multi-Alpha Ensemble Orchestrator
# ==============================================================================

class MultiAlphaOrchestrator:
    """
    Aggregates the 3 orthogonal alphas using dynamic regime-conditioned weights,
    applies hard liquidity and HTF bias filters, and emits execution signals.
    """

    def __init__(self, entry_threshold: float = 0.35, exit_threshold: float = 0.15):
        self.entry_threshold = entry_threshold
        self.exit_threshold = exit_threshold

    def evaluate_signal(
        self,
        features: BarFeatures,
        regime_state: RegimeState,
        historical_closes: Optional[List[float]] = None
    ) -> AlphaSignal:
        """
        Evaluate all 3 alphas on lag-1 features and produce a final decision.
        """
        closes = historical_closes or [features.close]
        rsi_2p = calculate_2period_rsi(closes)

        # 1. Compute individual alpha scores
        s_trend = AdaptiveTrendAlpha.evaluate(features)
        s_mean_rev = SqueezeMeanReversionAlpha.evaluate(features, regime_state.regime, rsi_2p=rsi_2p)
        s_breakout = OrderFlowBreakoutAlpha.evaluate(features)

        # 2. Get dynamic regime weights
        weights = regime_state.active_weights
        w_trend = weights.get("trend", 0.40)
        w_mean_rev = weights.get("mean_reversion", 0.30)
        w_breakout = weights.get("breakout", 0.30)

        # 3. Dynamic Composite Score
        composite = (w_trend * s_trend) + (w_mean_rev * s_mean_rev) + (w_breakout * s_breakout)
        confidence = abs(composite)

        # 4. Filter Evaluation & Regime Alignment
        filters_passed = True
        rejection_reason = None

        # Filter A: Extreme low liquidity hours
        if not features.is_liquid_hour:
            filters_passed = False
            rejection_reason = "Filtered: Low liquidity rollover hour (00-02 UTC with sub-normal volume)"

        # Filter B: Strict Regime Directional Harmony
        # In Bull Trends: ONLY LONG trades permitted.
        # In Bear Trends: ONLY SHORT trades permitted.
        if filters_passed:
            if regime_state.regime == MarketRegime.TRENDING_BULL and composite < 0:
                filters_passed = False
                rejection_reason = "Filtered: Short signal blocked in TRENDING_BULL regime"
            elif regime_state.regime == MarketRegime.TRENDING_BEAR and composite > 0:
                filters_passed = False
                rejection_reason = "Filtered: Long signal blocked in TRENDING_BEAR regime"

        # Filter C: Higher-Timeframe Trend Bias Filter
        # Do not take Longs if HTF bias is strongly Bearish (-1)
        # Do not take Shorts if HTF bias is strongly Bullish (+1)
        if filters_passed:
            if composite > self.entry_threshold and features.htf_bias < 0:
                filters_passed = False
                rejection_reason = "Filtered: Long signal opposes bearish HTF trend bias"
            elif composite < -self.entry_threshold and features.htf_bias > 0:
                filters_passed = False
                rejection_reason = "Filtered: Short signal opposes bullish HTF trend bias"

        # 5. Determine Action
        action = SignalAction.HOLD
        if filters_passed:
            if composite >= self.entry_threshold:
                action = SignalAction.BUY
            elif composite <= -self.entry_threshold:
                action = SignalAction.SELL

        return AlphaSignal(
            timestamp=features.timestamp,
            action=action,
            composite_score=composite,
            confidence=confidence,
            trend_score=s_trend,
            mean_rev_score=s_mean_rev,
            breakout_score=s_breakout,
            active_regime=regime_state.regime.value,
            regime_weights=weights,
            filters_passed=filters_passed,
            rejection_reason=rejection_reason
        )
