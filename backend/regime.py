"""
Probabilistic Market Regime Detection & Classification Engine
=============================================================
Combines Online Bayesian Inference, Gaussian Mixture Emission Likelihoods,
Markov Transition Priors, Kalman Exponential Smoothing, and State Hysteresis.

Canonical Regimes:
1. TRENDING (BULL / BEAR): High ADX, directional DI divergence, EMA alignment.
2. MEAN_REVERTING (LOW_VOL_COMPRESSION): Low ADX, compressed BBW percentile, tight range.
3. HIGH_VOL (HIGH_VOL_BREAKOUT): Expanding volatility, elevated BBW %, volume delta thrust.
4. CRISIS: Extreme liquidity cascades, volatility explosions (>95th percentile), heavy dumps.

Features:
- Continuous soft probability distribution: P = [p_trend, p_mr, p_high_vol, p_crisis]
- Kalman transition smoothing to eliminate high-frequency probability noise.
- Multi-bar state hysteresis to prevent boundary churn and premature stop flips.
- Smooth probability-conditioned alpha weights with crisis cash preservation.
"""

from enum import Enum
from typing import Dict, Any, List, Optional, Tuple, Union
from dataclasses import dataclass, asdict
import math

try:
    from features import BarFeatures
except ImportError:
    try:
        from backend.features import BarFeatures
    except ImportError:
        BarFeatures = Any  # type: ignore


class MarketRegime(str, Enum):
    """Canonical market regime classifications with probabilistic and legacy aliases."""
    TRENDING = "TRENDING"
    TRENDING_BULL = "TRENDING_BULL"
    TRENDING_BEAR = "TRENDING_BEAR"
    MEAN_REVERTING = "MEAN_REVERTING"
    LOW_VOL_COMPRESSION = "LOW_VOL_COMPRESSION"
    HIGH_VOL = "HIGH_VOL"
    HIGH_VOL_BREAKOUT = "HIGH_VOL_BREAKOUT"
    CRISIS = "CRISIS"

    # Backward compatibility aliases
    MEAN_REVERTING_CHOP = "LOW_VOL_COMPRESSION"
    HIGH_VOLATILITY_EXPANSION = "HIGH_VOL_BREAKOUT"
    RANGING_CHOP = "LOW_VOL_COMPRESSION"
    CHOP = "LOW_VOL_COMPRESSION"
    VOLATILITY_EXPANSION = "HIGH_VOL_BREAKOUT"

    @classmethod
    def _missing_(cls, value: object) -> Any:
        if isinstance(value, str):
            val_upper = value.upper().strip()
            aliases = {
                "MEAN_REVERTING_CHOP": cls.LOW_VOL_COMPRESSION,
                "HIGH_VOLATILITY_EXPANSION": cls.HIGH_VOL_BREAKOUT,
                "RANGING_CHOP": cls.LOW_VOL_COMPRESSION,
                "CHOP": cls.LOW_VOL_COMPRESSION,
                "VOLATILITY_EXPANSION": cls.HIGH_VOL_BREAKOUT,
                "HIGH_VOLATILITY": cls.HIGH_VOL_BREAKOUT,
                "COMPRESSION": cls.LOW_VOL_COMPRESSION,
            }
            if val_upper in aliases:
                return aliases[val_upper]
            for member in cls:
                if member.value == val_upper:
                    return member
        return None


REGIME_DESCRIPTIONS: Dict[str, str] = {
    MarketRegime.TRENDING_BULL.value: "Sustained upward price trend with strong directional momentum and volume support.",
    MarketRegime.TRENDING_BEAR.value: "Sustained downward price distribution with elevated selling pressure.",
    MarketRegime.LOW_VOL_COMPRESSION.value: "Tight consolidation inside Bollinger bands with suppressed volatility; ripe for mean-reversion.",
    MarketRegime.HIGH_VOL_BREAKOUT.value: "Volatile breakout expansion with widening bands and aggressive order flow delta.",
    MarketRegime.CRISIS.value: "Extreme liquidity vacuum, flash cascade, or volatility explosion (>95th percentile). Defensive cash gate.",
}

REGIME_STRATEGY_WEIGHTS: Dict[str, Dict[str, float]] = {
    MarketRegime.TRENDING_BULL.value: {"trend": 0.65, "mean_reversion": 0.10, "breakout": 0.25, "order_flow": 0.25, "ofi": 0.25, "cash_reserve": 0.0},
    MarketRegime.TRENDING_BEAR.value: {"trend": 0.65, "mean_reversion": 0.10, "breakout": 0.25, "order_flow": 0.25, "ofi": 0.25, "cash_reserve": 0.0},
    MarketRegime.LOW_VOL_COMPRESSION.value: {"trend": 0.15, "mean_reversion": 0.70, "breakout": 0.15, "order_flow": 0.15, "ofi": 0.15, "cash_reserve": 0.0},
    MarketRegime.HIGH_VOL_BREAKOUT.value: {"trend": 0.30, "mean_reversion": 0.10, "breakout": 0.60, "order_flow": 0.60, "ofi": 0.60, "cash_reserve": 0.0},
    MarketRegime.CRISIS.value: {"trend": 0.05, "mean_reversion": 0.00, "breakout": 0.15, "order_flow": 0.15, "ofi": 0.15, "cash_reserve": 0.80},
}


@dataclass
class RegimeState:
    """Rich regime diagnostics snapshot with soft continuous probabilities."""
    regime: MarketRegime
    confidence: float
    adx: float
    bbw_percentile: float
    volatility_zscore: float
    active_weights: Dict[str, float]
    bars_in_regime: int
    probabilities: Dict[str, float] = None  # type: ignore
    di_plus: float = 0.0
    di_minus: float = 0.0
    reason: str = ""
    timestamp: Optional[str] = None

    def __post_init__(self):
        if self.probabilities is None:
            self.probabilities = {
                "TRENDING": 0.35 if "TREND" in self.regime.value else 0.15,
                "MEAN_REVERTING": 0.60 if self.regime == MarketRegime.LOW_VOL_COMPRESSION else 0.15,
                "HIGH_VOL": 0.60 if self.regime == MarketRegime.HIGH_VOL_BREAKOUT else 0.15,
                "CRISIS": 0.80 if self.regime == MarketRegime.CRISIS else 0.02,
            }
            tot = sum(self.probabilities.values())
            self.probabilities = {k: round(v / tot, 4) for k, v in self.probabilities.items()}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "regime": self.regime.value,
            "confidence": round(self.confidence, 4),
            "adx": round(self.adx, 2),
            "bbw_percentile": round(self.bbw_percentile, 2),
            "volatility_zscore": round(self.volatility_zscore, 2),
            "active_weights": {k: round(v, 4) for k, v in self.active_weights.items()},
            "bars_in_regime": self.bars_in_regime,
            "probabilities": {k: round(v, 4) for k, v in self.probabilities.items()},
            "di_plus": round(self.di_plus, 2),
            "di_minus": round(self.di_minus, 2),
            "reason": self.reason,
            "timestamp": self.timestamp,
        }


def _extract_val(obj: Any, keys: List[str], default: float = 0.0) -> float:
    for k in keys:
        if hasattr(obj, k):
            v = getattr(obj, k)
            if v is not None:
                try:
                    return float(v)
                except (ValueError, TypeError):
                    pass
        elif isinstance(obj, dict) and k in obj:
            v = obj[k]
            if v is not None:
                try:
                    return float(v)
                except (ValueError, TypeError):
                    pass
    return default


def _extract_str(obj: Any, keys: List[str], default: Optional[str] = None) -> Optional[str]:
    for k in keys:
        if hasattr(obj, k):
            v = getattr(obj, k)
            if v is not None:
                return str(v)
        elif isinstance(obj, dict) and k in obj:
            v = obj[k]
            if v is not None:
                return str(v)
    return default


class RobustRegimeDetector:
    """
    Online Probabilistic Regime Classifier combining:
    1. Online Bayesian inference on ADX, BBW %, realized vol, and volume delta.
    2. Kalman exponential probability smoothing (K=0.25).
    3. State Hysteresis to eliminate boundary whipsawing.
    4. Crisis fast-trip circuit trigger.
    """

    def __init__(self, hysteresis_bars: int = 2, kalman_gain: float = 0.25):
        self.hysteresis_bars = max(1, hysteresis_bars)
        self.kalman_gain = min(1.0, max(0.05, kalman_gain))
        self.current_regime: MarketRegime = MarketRegime.LOW_VOL_COMPRESSION
        self.candidate_regime: Optional[MarketRegime] = None
        self.candidate_count: int = 0
        self.bars_in_current: int = 0

        # State probability distribution
        self.probabilities: Dict[str, float] = {
            "TRENDING": 0.25,
            "MEAN_REVERTING": 0.45,
            "HIGH_VOL": 0.25,
            "CRISIS": 0.05,
        }

        # Transition matrix priors P(S_t | S_{t-1})
        self.transition_matrix: Dict[str, Dict[str, float]] = {
            "TRENDING": {"TRENDING": 0.88, "MEAN_REVERTING": 0.05, "HIGH_VOL": 0.05, "CRISIS": 0.02},
            "MEAN_REVERTING": {"TRENDING": 0.08, "MEAN_REVERTING": 0.82, "HIGH_VOL": 0.08, "CRISIS": 0.02},
            "HIGH_VOL": {"TRENDING": 0.15, "MEAN_REVERTING": 0.10, "HIGH_VOL": 0.70, "CRISIS": 0.05},
            "CRISIS": {"TRENDING": 0.05, "MEAN_REVERTING": 0.15, "HIGH_VOL": 0.30, "CRISIS": 0.50},
        }

        # Gaussian mixture parameters (mu, sigma)
        self.emission_models: Dict[str, Dict[str, Tuple[float, float]]] = {
            "TRENDING": {
                "adx": (36.0, 9.0),
                "bbw": (55.0, 18.0),
                "vol": (0.35, 0.15),
            },
            "MEAN_REVERTING": {
                "adx": (15.0, 5.0),
                "bbw": (22.0, 10.0),
                "vol": (0.22, 0.08),
            },
            "HIGH_VOL": {
                "adx": (28.0, 10.0),
                "bbw": (82.0, 12.0),
                "vol": (0.55, 0.20),
            },
            "CRISIS": {
                "adx": (35.0, 15.0),
                "bbw": (94.0, 8.0),
                "vol": (0.85, 0.25),
            },
        }

    def _gaussian_log_likelihood(self, x: float, mu: float, sigma: float) -> float:
        var = max(1e-4, sigma ** 2)
        diff = x - mu
        return -0.5 * math.log(2.0 * math.pi * var) - (diff ** 2) / (2.0 * var)

    def compute_likelihoods(
        self,
        adx: float,
        bbw_pct: float,
        realized_vol: float,
        volume_delta_abs: float
    ) -> Dict[str, float]:
        """Calculates normalized emission likelihoods per regime state."""
        log_likes: Dict[str, float] = {}
        for state, params in self.emission_models.items():
            ll = (
                self._gaussian_log_likelihood(adx, params["adx"][0], params["adx"][1]) +
                self._gaussian_log_likelihood(bbw_pct, params["bbw"][0], params["bbw"][1]) +
                self._gaussian_log_likelihood(realized_vol, params["vol"][0], params["vol"][1])
            )
            if state == "HIGH_VOL" and volume_delta_abs > 0.30:
                ll += 1.2
            elif state == "CRISIS" and (realized_vol > 0.85 or bbw_pct > 95.0):
                ll += 2.5
            log_likes[state] = ll

        max_ll = max(log_likes.values())
        unnormalized = {k: math.exp(v - max_ll) for k, v in log_likes.items()}
        tot = sum(unnormalized.values())
        return {k: v / tot for k, v in unnormalized.items()} if tot > 0 else {k: 0.25 for k in log_likes}

    def update_probabilities(self, likelihoods: Dict[str, float]) -> Dict[str, float]:
        """Bayesian update + Kalman exponential smoothing."""
        prior_state = "MEAN_REVERTING"
        if self.current_regime in (MarketRegime.TRENDING_BULL, MarketRegime.TRENDING_BEAR):
            prior_state = "TRENDING"
        elif self.current_regime == MarketRegime.HIGH_VOL_BREAKOUT:
            prior_state = "HIGH_VOL"
        elif self.current_regime == MarketRegime.CRISIS:
            prior_state = "CRISIS"

        t_priors = self.transition_matrix.get(prior_state, {"TRENDING": 0.25, "MEAN_REVERTING": 0.25, "HIGH_VOL": 0.25, "CRISIS": 0.25})

        posteriors = {}
        for s in self.probabilities:
            p_prior = t_priors.get(s, 0.25)
            p_lik = likelihoods.get(s, 0.25)
            posteriors[s] = p_prior * p_lik

        tot = sum(posteriors.values())
        if tot > 0:
            posteriors = {k: v / tot for k, v in posteriors.items()}
        else:
            posteriors = {k: 0.25 for k in posteriors}

        # Kalman Filter smoothing: P_t = (1 - K)*P_{t-1} + K*P_post
        k = self.kalman_gain
        smoothed = {}
        for s in self.probabilities:
            smoothed[s] = (1.0 - k) * self.probabilities[s] + k * posteriors[s]

        tot_s = sum(smoothed.values())
        self.probabilities = {k: v / tot_s for k, v in smoothed.items()}
        return self.probabilities

    def classify_raw(self, f: Any) -> Tuple[MarketRegime, float, str]:
        """Maps continuous diagnostics into discrete candidate regime."""
        adx = _extract_val(f, ["adx"], 20.0)
        plus_di = _extract_val(f, ["plus_di", "di_plus"], 20.0)
        minus_di = _extract_val(f, ["minus_di", "di_minus"], 20.0)
        bbw_pct = _extract_val(f, ["bbw_percentile", "bb_width_pct"], 35.0)
        vol = _extract_val(f, ["realized_vol", "parkinson_vol"], 0.30)
        vol_delta_ratio = _extract_val(f, ["volume_delta_ratio", "delta_ratio"], 0.0)
        close_p = _extract_val(f, ["close", "price"], 0.0)
        ema_f = _extract_val(f, ["ema_fast", "ema50"], close_p)
        bb_mid = _extract_val(f, ["bb_mid", "bb_middle"], close_p)

        # 1. CRISIS Check: Extreme volatility or massive cascade
        if vol >= 0.85 or (bbw_pct >= 95.0 and vol_delta_ratio < -0.45):
            conf = min(0.98, 0.70 + (vol / 1.5) * 0.25)
            return MarketRegime.CRISIS, conf, f"Extreme volatility spike (vol={vol:.2f}, BBW%={bbw_pct:.1f}%)"

        # 2. Strong Directional Trends (ADX >= 25 with DI dominance)
        if adx >= 25.0:
            di_spread = abs(plus_di - minus_di)
            if plus_di > minus_di and close_p >= ema_f:
                conf = min(0.95, 0.55 + (adx / 100.0) * 0.40)
                return MarketRegime.TRENDING_BULL, conf, f"Bull trend (ADX={adx:.1f}, +DI={plus_di:.1f} > -DI={minus_di:.1f})"
            elif minus_di > plus_di and close_p <= ema_f:
                conf = min(0.95, 0.55 + (adx / 100.0) * 0.40)
                return MarketRegime.TRENDING_BEAR, conf, f"Bear trend (ADX={adx:.1f}, -DI={minus_di:.1f} > +DI={plus_di:.1f})"

        # 3. Low Volatility Compression Squeeze
        if adx < 22.0 and bbw_pct < 38.0:
            conf = min(0.95, 0.60 + ((38.0 - bbw_pct) / 38.0) * 0.35)
            return MarketRegime.LOW_VOL_COMPRESSION, conf, f"Low-vol squeeze (ADX={adx:.1f}, BBW%={bbw_pct:.1f}%)"

        # 4. High Volatility Expansion Breakout
        if bbw_pct > 75.0 or abs(vol_delta_ratio) > 0.35:
            conf = min(0.95, 0.55 + ((bbw_pct - 75.0) / 25.0) * 0.40)
            return MarketRegime.HIGH_VOL_BREAKOUT, conf, f"Breakout expansion (BBW%={bbw_pct:.1f}%, DeltaRatio={vol_delta_ratio:.2f})"

        # 5. Default based on ADX & Price location
        if adx >= 20.0:
            if close_p >= bb_mid:
                return MarketRegime.TRENDING_BULL, 0.55, f"Mild bull bias (ADX={adx:.1f})"
            else:
                return MarketRegime.TRENDING_BEAR, 0.55, f"Mild bear bias (ADX={adx:.1f})"
        else:
            return MarketRegime.LOW_VOL_COMPRESSION, 0.50, f"Neutral consolidation (ADX={adx:.1f})"

    def update(self, features: Any) -> RegimeState:
        """Processes lag-1 features and outputs smoothed probabilistic regime."""
        adx = _extract_val(features, ["adx"], 20.0)
        plus_di = _extract_val(features, ["plus_di", "di_plus"], 20.0)
        minus_di = _extract_val(features, ["minus_di", "di_minus"], 20.0)
        bbw_pct = _extract_val(features, ["bbw_percentile", "bb_width_pct"], 35.0)
        vol = _extract_val(features, ["realized_vol", "parkinson_vol"], 0.30)
        vol_delta_ratio = _extract_val(features, ["volume_delta_ratio", "delta_ratio"], 0.0)
        ts = _extract_str(features, ["timestamp", "t"], None)

        # 1. Update Continuous Probabilities
        likelihoods = self.compute_likelihoods(adx, bbw_pct, vol, abs(vol_delta_ratio))
        probs = self.update_probabilities(likelihoods)

        # 2. Discrete Candidate & Hysteresis
        raw_regime, raw_conf, reason = self.classify_raw(features)

        # Crisis fast-trip
        if raw_regime == MarketRegime.CRISIS and probs["CRISIS"] > 0.55:
            self.current_regime = MarketRegime.CRISIS
            self.bars_in_current += 1
            self.candidate_regime = None
            self.candidate_count = 0
            reason = f"CRISIS cascade fast-trip triggered (P={probs['CRISIS']:.2f})"
        elif raw_regime == self.current_regime:
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
                    reason = f"{reason} [Hysteresis confirmed after {self.hysteresis_bars} bars]"
                else:
                    self.bars_in_current += 1
                    reason = f"Confirmed {self.current_regime.value} ({self.bars_in_current} bars); candidate {raw_regime.value} ({self.candidate_count}/{self.hysteresis_bars})"
            else:
                self.candidate_regime = raw_regime
                self.candidate_count = 1
                self.bars_in_current += 1
                reason = f"Confirmed {self.current_regime.value} ({self.bars_in_current} bars); new candidate {raw_regime.value} (1/{self.hysteresis_bars})"

        # 3. Soft Dynamic Alpha Weights Blending
        p_tr = probs["TRENDING"]
        p_mr = probs["MEAN_REVERTING"]
        p_hv = probs["HIGH_VOL"]
        p_cr = probs["CRISIS"]

        w_trend = round(p_tr * 0.65 + p_mr * 0.15 + p_hv * 0.30 + p_cr * 0.05, 4)
        w_mr = round(p_tr * 0.10 + p_mr * 0.70 + p_hv * 0.10 + p_cr * 0.00, 4)
        w_breakout = round(p_tr * 0.25 + p_mr * 0.15 + p_hv * 0.60 + p_cr * 0.15, 4)
        tot = w_trend + w_mr + w_breakout
        if tot > 0:
            weights = {
                "trend": round(w_trend / tot, 4),
                "breakout": round(w_breakout / tot, 4),
                "mean_reversion": round(w_mr / tot, 4),
            }
        else:
            base_w = self.get_strategy_weights(self.current_regime)
            weights = {
                "trend": base_w.get("trend", 0.40),
                "breakout": base_w.get("breakout", 0.30),
                "mean_reversion": base_w.get("mean_reversion", 0.30)
            }

        vol_zscore = (vol - 0.35) / 0.15

        return RegimeState(
            regime=self.current_regime,
            confidence=round(probs[max(probs, key=probs.get)], 4),
            adx=round(adx, 2),
            bbw_percentile=round(bbw_pct, 2),
            volatility_zscore=round(vol_zscore, 2),
            active_weights=weights,
            bars_in_regime=self.bars_in_current,
            probabilities=probs,
            di_plus=round(plus_di, 2),
            di_minus=round(minus_di, 2),
            reason=reason,
            timestamp=ts,
        )

    @staticmethod
    def get_strategy_weights(regime: Union[MarketRegime, str]) -> Dict[str, float]:
        reg_str = str(regime.value if isinstance(regime, MarketRegime) else regime).upper()
        return REGIME_STRATEGY_WEIGHTS.get(reg_str, REGIME_STRATEGY_WEIGHTS[MarketRegime.LOW_VOL_COMPRESSION.value])

    @staticmethod
    def get_description(regime: Union[MarketRegime, str]) -> str:
        reg_str = str(regime.value if isinstance(regime, MarketRegime) else regime).upper()
        return REGIME_DESCRIPTIONS.get(reg_str, "Dynamic or unclassified market regime.")


# Convenience module-level detector singleton
robust_regime_detector = RobustRegimeDetector()

def get_robust_regime_detector(hysteresis_bars: int = 2) -> RobustRegimeDetector:
    return RobustRegimeDetector(hysteresis_bars=hysteresis_bars)
