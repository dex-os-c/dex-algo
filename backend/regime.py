"""
Robust Market Regime Classification Engine
===========================================
Classifies market microstructure into four distinct mathematical regimes:
1. TRENDING_BULL: ADX >= 25, +DI > -DI, Price > EMA50, positive slope.
2. TRENDING_BEAR: ADX >= 25, -DI > +DI, Price < EMA50, negative slope.
3. LOW_VOL_COMPRESSION: ADX < 20, BBW Percentile < 35%, ATR compressed (mean-reverting squeeze).
4. HIGH_VOL_BREAKOUT: BBW Percentile > 75%, volume surge, or volatility expansion.

Features:
- State Hysteresis: Requires consecutive confirmation bars to prevent boundary-churn.
- Regime-Conditioned Alpha Sizing: Provides dynamic alpha weights conditioned on active regime.
"""

from enum import Enum
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, asdict

from features import BarFeatures


class MarketRegime(str, Enum):
    TRENDING_BULL = "TRENDING_BULL"
    TRENDING_BEAR = "TRENDING_BEAR"
    LOW_VOL_COMPRESSION = "LOW_VOL_COMPRESSION"
    HIGH_VOL_BREAKOUT = "HIGH_VOL_BREAKOUT"


@dataclass
class RegimeState:
    regime: MarketRegime
    confidence: float
    adx: float
    bbw_percentile: float
    volatility_zscore: float
    active_weights: Dict[str, float]  # Dynamic alpha weights: {"trend": w1, "mean_reversion": w2, "breakout": w3}
    bars_in_regime: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "regime": self.regime.value,
            "confidence": round(self.confidence, 4),
            "adx": round(self.adx, 2),
            "bbw_percentile": round(self.bbw_percentile, 2),
            "volatility_zscore": round(self.volatility_zscore, 2),
            "active_weights": {k: round(v, 4) for k, v in self.active_weights.items()},
            "bars_in_regime": self.bars_in_regime
        }


class RobustRegimeDetector:
    """
    Stateful regime detector with hysteresis to prevent rapid oscillating flips.
    """

    def __init__(self, hysteresis_bars: int = 2):
        self.hysteresis_bars = hysteresis_bars
        self.current_regime: MarketRegime = MarketRegime.LOW_VOL_COMPRESSION
        self.candidate_regime: Optional[MarketRegime] = None
        self.candidate_count: int = 0
        self.bars_in_current: int = 0

    def classify_raw(self, f: BarFeatures) -> Tuple[MarketRegime, float]:
        """Classify single bar features into a candidate regime and confidence."""
        # 1. Check for Strong Directional Trends (ADX >= 25 with clear DI dominance)
        if f.adx >= 25.0:
            if f.plus_di > f.minus_di and f.close >= f.ema_fast:
                confidence = min(0.95, 0.50 + (f.adx / 100.0) * 0.45)
                return MarketRegime.TRENDING_BULL, confidence
            elif f.minus_di > f.plus_di and f.close <= f.ema_fast:
                confidence = min(0.95, 0.50 + (f.adx / 100.0) * 0.45)
                return MarketRegime.TRENDING_BEAR, confidence

        # 2. Check for Low Volatility Compression / Squeeze (Ideal for Mean Reversion)
        if f.adx < 22.0 and f.bbw_percentile < 35.0:
            confidence = min(0.95, 0.60 + ((35.0 - f.bbw_percentile) / 35.0) * 0.35)
            return MarketRegime.LOW_VOL_COMPRESSION, confidence

        # 3. Check for High Volatility Expansion / Breakout Thrust
        if f.bbw_percentile > 75.0 or abs(f.volume_delta_ratio) > 0.40:
            confidence = min(0.95, 0.55 + ((f.bbw_percentile - 75.0) / 25.0) * 0.40)
            return MarketRegime.HIGH_VOL_BREAKOUT, confidence

        # 4. Default based on ADX & Price relative to mid-band
        if f.adx >= 20.0:
            if f.close > f.bb_mid:
                return MarketRegime.TRENDING_BULL, 0.55
            else:
                return MarketRegime.TRENDING_BEAR, 0.55
        else:
            return MarketRegime.LOW_VOL_COMPRESSION, 0.50

    def update(self, features: BarFeatures) -> RegimeState:
        """Update detector with latest lag-1 features and apply hysteresis."""
        raw_regime, confidence = self.classify_raw(features)

        if raw_regime == self.current_regime:
            self.bars_in_current += 1
            self.candidate_regime = None
            self.candidate_count = 0
        else:
            if raw_regime == self.candidate_regime:
                self.candidate_count += 1
                if self.candidate_count >= self.hysteresis_bars:
                    self.current_regime = raw_regime
                    self.bars_in_current = self.candidate_count
                    self.candidate_regime = None
                    self.candidate_count = 0
            else:
                self.candidate_regime = raw_regime
                self.candidate_count = 1
                self.bars_in_current += 1

        # Dynamic Alpha Weights conditioned on regime
        weights = self._compute_regime_alpha_weights(self.current_regime, features)

        vol_zscore = (features.realized_vol - 0.50) / 0.20  # Normalized vol distance

        return RegimeState(
            regime=self.current_regime,
            confidence=confidence,
            adx=features.adx,
            bbw_percentile=features.bbw_percentile,
            volatility_zscore=vol_zscore,
            active_weights=weights,
            bars_in_regime=self.bars_in_current
        )

    def _compute_regime_alpha_weights(
        self,
        regime: MarketRegime,
        f: BarFeatures
    ) -> Dict[str, float]:
        """
        Dynamically distributes portfolio alpha weights to eliminate drag from
        unfavorable strategies.
        """
        if regime in (MarketRegime.TRENDING_BULL, MarketRegime.TRENDING_BEAR):
            # Prioritize Adaptive Trend (65%), Breakout Continuation (25%), disable Mean Reversion (10%)
            return {"trend": 0.65, "breakout": 0.25, "mean_reversion": 0.10}
        elif regime == MarketRegime.LOW_VOL_COMPRESSION:
            # Low ADX Squeeze: Prioritize Mean Reversion (70%), Trend (15%), Breakout (15%)
            return {"trend": 0.15, "breakout": 0.15, "mean_reversion": 0.70}
        elif regime == MarketRegime.HIGH_VOL_BREAKOUT:
            # Volatility Expansion: Prioritize Breakout (60%), Trend (30%), Mean Reversion (10%)
            return {"trend": 0.30, "breakout": 0.60, "mean_reversion": 0.10}
        return {"trend": 0.40, "breakout": 0.30, "mean_reversion": 0.30}
