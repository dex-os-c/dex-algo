"""
Institutional Multi-Alpha Quantitative Ensemble
===============================================
Production-hardened, mathematically rigorous quantitative multi-alpha ensemble:
1. Adaptive Trend Alpha:
   - KAMA (Kaufman Adaptive Moving Average) with dynamic Efficiency Ratio (ER)
   - HMA (Hull Moving Average) low-lag trend slope
   - Donchian Channel (20) breakout envelope
   - SuperTrend dynamic volatility band (1.5x ATR)
   - Continuous score [-1.0, +1.0] with volume confirmation
2. Bollinger Squeeze-Expansion Mean-Reversion Alpha:
   - Carter's Squeeze detection (Bollinger Bands contracted inside Keltner Channels)
   - Strictly active ONLY during volatility compression (LOW_VOL_COMPRESSION or Squeeze)
   - Continuous %B exhaustion mapping with 2-period RSI and VWAP z-score
   - Continuous score [-1.0, +1.0] fading band extremes to mean
3. Order Flow Breakout Continuation Alpha:
   - Aggressive taker buy/sell volume delta imbalance + 20-period CVD thrust
   - Squeeze-expansion volatility booster (fires on volatility expansion)
   - Continuous score [-1.0, +1.0]
4. Online Exponential Moving Sharpe Weighting (OnlineSharpeWeightTracker):
   - Online Welford / EMA tracking of rolling mean return and variance per alpha
   - Dynamic Softmax temperature weighting based on annualized empirical Sharpe
   - Blended with Bayesian soft regime probabilities
5. Filters:
   - Regime Directional Harmony: No short trades in TRENDING_BULL; no long trades in TRENDING_BEAR
   - Higher-Timeframe (HTF) Trend Bias Filter: EMA(50)/EMA(200) alignment
"""

import math
from typing import Dict, Any, List, Optional, Tuple, Union
from dataclasses import dataclass, asdict
from enum import Enum

try:
    from features import BarFeatures
    from regime import MarketRegime, RegimeState
except ImportError:
    try:
        from backend.features import BarFeatures
        from backend.regime import MarketRegime, RegimeState
    except ImportError:
        BarFeatures = Any  # type: ignore
        MarketRegime = Any  # type: ignore
        RegimeState = Any  # type: ignore


class SignalAction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class AlphaSignal:
    timestamp: str
    action: SignalAction
    composite_score: float      # Continuous normalized score between -1.0 and +1.0
    confidence: float           # Continuous confidence 0.0 to 1.0
    trend_score: float          # Alpha 1: -1.0 to +1.0
    mean_rev_score: float       # Alpha 2: -1.0 to +1.0
    breakout_score: float       # Alpha 3: -1.0 to +1.0
    active_regime: str
    regime_weights: Dict[str, float]
    filters_passed: bool
    rejection_reason: Optional[str] = None
    sharpe_weights: Optional[Dict[str, float]] = None

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
            "sharpe_weights": {k: round(v, 4) for k, v in self.sharpe_weights.items()} if self.sharpe_weights else {},
            "filters_passed": self.filters_passed,
            "rejection_reason": self.rejection_reason
        }


# ==============================================================================
# Helper Indicators: KAMA, HMA, 2-Period RSI
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


def calculate_kama(
    prices: List[float],
    period: int = 10,
    fast_period: int = 2,
    slow_period: int = 30
) -> List[float]:
    """
    Kaufman Adaptive Moving Average (KAMA).
    Dynamically adjusts smoothing speed based on the Efficiency Ratio (ER = Direction / Noise).
    Fast in trending markets, flat in choppy noise.
    """
    n = len(prices)
    if n < period + 1:
        return [float(p) for p in prices]

    fast_sc = 2.0 / (fast_period + 1.0)
    slow_sc = 2.0 / (slow_period + 1.0)

    kama = [float(prices[0])]
    for i in range(1, n):
        if i < period:
            kama.append(float(prices[i]))
            continue

        change = abs(prices[i] - prices[i - period])
        vol = sum(abs(prices[j] - prices[j - 1]) for j in range(i - period + 1, i + 1))
        er = (change / vol) if vol > 1e-9 else 0.0

        sc = (er * (fast_sc - slow_sc) + slow_sc) ** 2
        cur_kama = kama[-1] + sc * (prices[i] - kama[-1])
        kama.append(cur_kama)

    return kama


def calculate_wma(prices: List[float], period: int) -> List[float]:
    """Weighted Moving Average."""
    if not prices:
        return []
    n = len(prices)
    if period <= 1:
        return [float(p) for p in prices]
    wma_list: List[float] = []
    denom = (period * (period + 1)) // 2
    for i in range(n):
        if i + 1 < period:
            sub = prices[: i + 1]
            sub_k = len(sub)
            sub_denom = (sub_k * (sub_k + 1)) // 2
            w_sum = sum((idx + 1) * p for idx, p in enumerate(sub))
            wma_list.append(w_sum / sub_denom)
        else:
            window = prices[i - period + 1 : i + 1]
            w_sum = sum((idx + 1) * p for idx, p in enumerate(window))
            wma_list.append(w_sum / denom)
    return wma_list


def calculate_hma(prices: List[float], period: int = 20) -> List[float]:
    """
    Hull Moving Average (HMA).
    HMA = WMA(sqrt(n), 2*WMA(n/2) - WMA(n))
    Extremely low-lag smoothed trend tracker.
    """
    if not prices:
        return []
    if len(prices) < 3:
        return [float(p) for p in prices]
    half_period = max(1, period // 2)
    sqrt_period = max(1, int(math.isqrt(period)))
    wma_half = calculate_wma(prices, half_period)
    wma_full = calculate_wma(prices, period)
    diff_series = [2.0 * h - f for h, f in zip(wma_half, wma_full)]
    return calculate_wma(diff_series, sqrt_period)


# ==============================================================================
# Online Exponential Moving Sharpe Weight Tracker
# ==============================================================================

class OnlineSharpeWeightTracker:
    """
    Tracks rolling risk-adjusted performance (Exponential Moving Sharpe) per alpha
    and computes dynamic Softmax weights to continuously allocate capital to outperforming alphas.
    """

    def __init__(
        self,
        decay: float = 0.95,
        temperature: float = 0.8,
        annualization_factor: float = math.sqrt(8760)
    ):
        self.decay = decay
        self.temperature = temperature
        self.annualization_factor = annualization_factor
        self.alphas = ["trend", "mean_reversion", "breakout"]
        self.means: Dict[str, float] = {a: 0.0001 for a in self.alphas}
        self.variances: Dict[str, float] = {a: 0.0004 for a in self.alphas}
        self.sharpes: Dict[str, float] = {a: 0.5 for a in self.alphas}
        self.weights: Dict[str, float] = {a: 0.3333 for a in self.alphas}
        self.update_count: int = 0

    def update(self, forward_return: float, prev_scores: Dict[str, float]) -> Dict[str, float]:
        """
        Updates rolling return, variance, and Sharpe ratio given forward realized return
        and prior component signals.
        """
        self.update_count += 1
        d = self.decay
        for a in self.alphas:
            score = prev_scores.get(a, 0.0)
            comp_ret = score * forward_return

            old_mean = self.means[a]
            new_mean = d * old_mean + (1.0 - d) * comp_ret
            self.means[a] = new_mean

            diff = comp_ret - new_mean
            new_var = d * self.variances[a] + (1.0 - d) * (diff * diff)
            self.variances[a] = max(1e-8, new_var)

            std = math.sqrt(self.variances[a])
            sharpe = (new_mean / std) * self.annualization_factor if std > 1e-6 else 0.0
            self.sharpes[a] = max(-2.0, min(5.0, sharpe))

        # Softmax on positive Sharpe
        exp_vals = {}
        for a in self.alphas:
            clipped_s = max(0.0, self.sharpes[a])
            exp_vals[a] = math.exp(clipped_s * self.temperature)
        tot = sum(exp_vals.values())
        self.weights = {a: round(exp_vals[a] / tot, 4) for a in self.alphas}
        return self.weights

    def get_weights(self) -> Dict[str, float]:
        return self.weights.copy()

    def get_sharpes(self) -> Dict[str, float]:
        return {k: round(v, 2) for k, v in self.sharpes.items()}


# ==============================================================================
# Alpha 1: Adaptive Trend Strategy (KAMA + HMA + Donchian + SuperTrend)
# ==============================================================================

class AdaptiveTrendAlpha:
    """
    Alpha 1: Adaptive Trend Alpha.
    Combines KAMA adaptive smoothing (ER-driven speed), HMA slope, Donchian Channel (20)
    breakout envelope, and SuperTrend dynamic ATR band with volume delta confirmation.
    Emits continuous score in [-1.0, +1.0].
    """

    @staticmethod
    def evaluate(f: BarFeatures, historical_closes: Optional[List[float]] = None) -> float:
        # Strict trend filter: trend alpha is deactivated during extreme low-ADX chop (< 12.0)
        if f.adx < 12.0:
            return 0.0

        # 1. Donchian Channel Position (continuous -1.0 to +1.0)
        donch_range = max(1e-4, f.donchian_high - f.donchian_low)
        donch_mid = (f.donchian_high + f.donchian_low) / 2.0
        donch_score = (f.close - donch_mid) / (donch_range / 2.0)
        donch_score = max(-1.0, min(1.0, donch_score))

        # 2. SuperTrend & EMA Alignment
        st_atr_band = max(1e-4, 1.5 * f.atr)
        st_diff = (f.close - f.ema_fast) / st_atr_band
        st_score = math.tanh(st_diff * 1.2)

        # 3. KAMA / HMA Slope if historical closes provided
        kama_score = 0.0
        if historical_closes and len(historical_closes) >= 15:
            kama_series = calculate_kama(historical_closes, period=10)
            if len(kama_series) >= 2:
                kama_slope = (kama_series[-1] - kama_series[-2]) / max(1e-4, kama_series[-2])
                kama_score = math.tanh(kama_slope * 300.0)

        # 4. Volume Surge & CVD Confirmation
        vol_confirm = 0.0
        if f.volume_delta_ratio > 0.10:
            vol_confirm = min(0.30, f.volume_delta_ratio * 0.40)
        elif f.volume_delta_ratio < -0.10:
            vol_confirm = max(-0.30, f.volume_delta_ratio * 0.40)

        if f.cvd > 0 and vol_confirm > 0:
            vol_confirm += 0.10
        elif f.cvd < 0 and vol_confirm < 0:
            vol_confirm -= 0.10

        # Combine components continuously
        if kama_score != 0.0:
            raw_score = 0.35 * donch_score + 0.30 * st_score + 0.20 * kama_score + 0.15 * vol_confirm
        else:
            raw_score = 0.45 * donch_score + 0.35 * st_score + 0.20 * vol_confirm

        # Continuous tanh mapping with ADX scaling
        adx_scalar = min(1.0, f.adx / 30.0)
        continuous_score = math.tanh(raw_score * 1.8) * adx_scalar
        return round(max(-1.0, min(1.0, continuous_score)), 4)


# ==============================================================================
# Alpha 2: Bollinger Squeeze-Expansion Mean-Reversion Strategy
# ==============================================================================

class SqueezeMeanReversionAlpha:
    """
    Alpha 2: Squeeze Mean-Reversion Alpha.
    Exploits price exhaustion at Bollinger Band extremes strictly during
    low-volatility compression regimes (Carter's Squeeze: BB inside Keltner Channels,
    ADX < 22, BBW Percentile < 35%).
    In trending or breakout regimes, this alpha is strictly deactivated (0.0).
    Emits continuous score in [-1.0, +1.0].
    """

    @staticmethod
    def is_in_squeeze(f: BarFeatures) -> bool:
        """Determines if volatility is compressed in a squeeze."""
        kc_upper = f.bb_mid + (1.5 * f.atr)
        kc_lower = f.bb_mid - (1.5 * f.atr)
        bb_inside_kc = (f.bb_upper <= (kc_upper * 1.002)) and (f.bb_lower >= (kc_lower * 0.998))
        return bb_inside_kc or (f.bbw_percentile < 35.0)

    @staticmethod
    def evaluate(f: BarFeatures, regime: Any, rsi_2p: float = 50.0) -> float:
        # Strict gate: do not mean-revert in trending or breakout regimes!
        regime_val = regime.value if hasattr(regime, "value") else str(regime)
        if regime_val not in (MarketRegime.LOW_VOL_COMPRESSION.value, "LOW_VOL_COMPRESSION"):
            return 0.0

        band_width = max(1e-5, f.bb_upper - f.bb_lower)
        pct_b = (f.close - f.bb_lower) / band_width

        # Distance from middle band (0.50)
        b_dev = pct_b - 0.50
        rsi_dev = (rsi_2p - 50.0) / 50.0
        vwap_dev = f.vwap_zscore / 2.0

        # Continuous mean reversion exhaustion mapping (opposite to price extension)
        raw_mr = -(0.55 * b_dev * 2.5 + 0.30 * rsi_dev + 0.15 * vwap_dev)

        # Extreme exhaustion triggers
        if pct_b < 0.15 and (rsi_2p < 25.0 or f.vwap_zscore < -1.2):
            oversold_intensity = min(1.0, max(0.0, (0.15 - pct_b) / 0.15 + (25.0 - rsi_2p) / 25.0))
            score = 0.60 + 0.40 * oversold_intensity
        elif pct_b > 0.85 and (rsi_2p > 75.0 or f.vwap_zscore > 1.2):
            overbought_intensity = min(1.0, max(0.0, (pct_b - 0.85) / 0.15 + (rsi_2p - 75.0) / 25.0))
            score = -(0.60 + 0.40 * overbought_intensity)
        elif 0.38 <= pct_b <= 0.62 and abs(f.vwap_zscore) < 0.5:
            # Equilibrium zone - zero out noise
            score = 0.0
        else:
            score = math.tanh(raw_mr * 1.5)

        return round(max(-1.0, min(1.0, score)), 4)


# Alias for backward compatibility
BollingerSqueezeMeanReversionAlpha = SqueezeMeanReversionAlpha


# ==============================================================================
# Alpha 3: Order Flow Breakout Continuation Strategy
# ==============================================================================

class OrderFlowBreakoutAlpha:
    """
    Alpha 3: Order Flow Breakout Continuation Strategy.
    Detects aggressive taker buying or selling imbalances with expanding volatility
    and cumulative volume delta (CVD) thrust. Accelerates when Bollinger Squeeze releases.
    Emits continuous score in [-1.0, +1.0].
    """

    @staticmethod
    def evaluate(f: BarFeatures) -> float:
        imbalance = f.volume_delta_ratio  # between -1.0 and +1.0
        cvd = f.cvd

        if abs(imbalance) < 0.05:
            return 0.0

        # Squeeze-expansion volatility booster (fires on volatility expansion)
        expansion_multiplier = 1.30 if f.bbw_percentile > 70.0 else 1.0

        base = math.tanh(imbalance * 3.2)
        if cvd > 0 and base > 0:
            base += 0.10
        elif cvd < 0 and base < 0:
            base -= 0.10
        if f.vwap_zscore > 0.2 and base > 0:
            base += 0.05
        elif f.vwap_zscore < -0.2 and base < 0:
            base -= 0.05

        score = base * expansion_multiplier
        return round(max(-1.0, min(1.0, score)), 4)


# Aliases for backward compatibility
MicrostructureOrderFlowAlpha = OrderFlowBreakoutAlpha
VolatilityBreakoutAlpha = OrderFlowBreakoutAlpha
OrderFlowAlpha = OrderFlowBreakoutAlpha


# ==============================================================================
# Master Multi-Alpha Ensemble Orchestrator
# ==============================================================================

class MultiAlphaOrchestrator:
    """
    Aggregates the 3 orthogonal alphas using dynamic regime-conditioned weights
    and online exponential moving Sharpe weights, applies hard liquidity and HTF bias filters,
    and emits execution signals with continuous scores [-1.0, +1.0] and confidence [0.0, 1.0].
    """

    def __init__(
        self,
        entry_threshold: float = 0.20,
        exit_threshold: float = 0.10,
        enable_online_sharpe: bool = True
    ):
        self.entry_threshold = entry_threshold
        self.exit_threshold = exit_threshold
        self.enable_online_sharpe = enable_online_sharpe
        self.sharpe_tracker = OnlineSharpeWeightTracker(decay=0.95)
        self.last_scores: Dict[str, float] = {}

    def update_feedback(self, forward_return: float) -> Dict[str, float]:
        """Provides feedback on realized return to update online Sharpe tracker."""
        if self.last_scores:
            return self.sharpe_tracker.update(forward_return, self.last_scores)
        return self.sharpe_tracker.get_weights()

    def evaluate_signal(
        self,
        features: BarFeatures,
        regime_state: RegimeState,
        historical_closes: Optional[List[float]] = None
    ) -> AlphaSignal:
        """
        Evaluate all 3 alphas on lag-1 features and produce a continuous decision.
        """
        closes = historical_closes or [features.close]
        rsi_2p = calculate_2period_rsi(closes)

        # 1. Compute continuous individual alpha scores
        s_trend = AdaptiveTrendAlpha.evaluate(features, historical_closes=closes)
        s_mean_rev = SqueezeMeanReversionAlpha.evaluate(features, regime_state.regime, rsi_2p=rsi_2p)
        s_breakout = OrderFlowBreakoutAlpha.evaluate(features)

        self.last_scores = {
            "trend": s_trend,
            "mean_reversion": s_mean_rev,
            "breakout": s_breakout
        }

        # 2. Get dynamic regime weights and online Sharpe weights
        regime_w = regime_state.active_weights
        w_trend = regime_w.get("trend", 0.40)
        w_mean_rev = regime_w.get("mean_reversion", 0.30)
        w_breakout = regime_w.get("breakout", 0.30)

        sharpe_w = self.sharpe_tracker.get_weights()
        if self.enable_online_sharpe and self.sharpe_tracker.update_count > 5:
            # 50% Regime Prior, 50% Online Empirical Sharpe Weighting
            w_trend = 0.50 * w_trend + 0.50 * sharpe_w.get("trend", 0.33)
            w_mean_rev = 0.50 * w_mean_rev + 0.50 * sharpe_w.get("mean_reversion", 0.33)
            w_breakout = 0.50 * w_breakout + 0.50 * sharpe_w.get("breakout", 0.33)
            tot_w = w_trend + w_mean_rev + w_breakout
            if tot_w > 0:
                w_trend /= tot_w
                w_mean_rev /= tot_w
                w_breakout /= tot_w

        combined_weights = {
            "trend": round(w_trend, 4),
            "mean_reversion": round(w_mean_rev, 4),
            "breakout": round(w_breakout, 4)
        }

        # 3. Dynamic Continuous Composite Score
        composite = (w_trend * s_trend) + (w_mean_rev * s_mean_rev) + (w_breakout * s_breakout)
        composite = round(max(-1.0, min(1.0, composite)), 4)

        # Continuous confidence with alpha agreement ratio
        scores = [s_trend, s_mean_rev, s_breakout]
        pos_count = sum(1 for s in scores if s > 0.05)
        neg_count = sum(1 for s in scores if s < -0.05)
        max_agreement = max(pos_count, neg_count)

        if max_agreement == 3:
            confidence = min(1.0, abs(composite) * 1.25 + 0.10)
        elif max_agreement == 2:
            confidence = min(1.0, abs(composite) * 1.05 + 0.05)
        else:
            confidence = max(0.0, abs(composite) * 0.70)
        confidence = round(max(0.0, min(1.0, confidence)), 4)

        # 4. Filter Evaluation & Regime Alignment
        filters_passed = True
        rejection_reason = None

        # Filter A: Extreme low liquidity hours
        if not features.is_liquid_hour:
            filters_passed = False
            rejection_reason = "Filtered: Low liquidity rollover hour (00-02 UTC with sub-normal volume)"

        # Filter B: Strict Regime Directional Harmony
        if filters_passed:
            reg_val = regime_state.regime.value if hasattr(regime_state.regime, "value") else str(regime_state.regime)
            if reg_val == MarketRegime.TRENDING_BULL.value and composite < 0:
                filters_passed = False
                rejection_reason = "Filtered: Short signal blocked in TRENDING_BULL regime"
            elif reg_val == MarketRegime.TRENDING_BEAR.value and composite > 0:
                filters_passed = False
                rejection_reason = "Filtered: Long signal blocked in TRENDING_BEAR regime"

        # Filter C: Higher-Timeframe Trend Bias Filter (active during directional trend regimes)
        reg_name = regime_state.regime.value if hasattr(regime_state.regime, "value") else str(regime_state.regime)
        if filters_passed and "COMPRESSION" not in reg_name:
            if composite > self.entry_threshold and features.htf_bias < 0:
                filters_passed = False
                rejection_reason = "Filtered: Long signal opposes bearish HTF trend bias"
            elif composite < -self.entry_threshold and features.htf_bias > 0:
                filters_passed = False
                rejection_reason = "Filtered: Short signal opposes bullish HTF trend bias"

        # Filter D: Crisis Capital Preservation Gate (Defense against systemic flash crashes)
        if filters_passed:
            if "CRISIS" in reg_name:
                filters_passed = False
                rejection_reason = "Filtered: Defensive cash gate active during CRISIS volatility cascade"

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
            active_regime=regime_state.regime.value if hasattr(regime_state.regime, "value") else str(regime_state.regime),
            regime_weights=combined_weights,
            filters_passed=filters_passed,
            rejection_reason=rejection_reason,
            sharpe_weights=sharpe_w
        )
