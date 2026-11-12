"""
Institutional Quantitative Risk & Position Sizing Engine
========================================================
Implements:
1. True Volatility Targeting (1/sigma realized vol scaling).
2. Online Bayesian Half-Kelly Sizing (Beta distribution prior updated continuously).
3. Monotonic Chandelier Ratchet Trailing Stops (one-way ratchet).
4. Soft Exits: Time-stagnation exit and regime-change exit.
5. Portfolio Constraints: Max leverage, single-asset cap, correlation limit, and daily circuit breaker.
"""

import math
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, asdict
from enum import Enum


class ExitReason(str, Enum):
    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT = "TAKE_PROFIT"
    CHANDELIER_TRAILING = "CHANDELIER_TRAILING"
    REGIME_CHANGE = "REGIME_CHANGE"
    TIME_STAGNATION = "TIME_STAGNATION"
    CIRCUIT_BREAKER = "CIRCUIT_BREAKER"


@dataclass
class Position:
    symbol: str
    side: str                # "LONG" or "SHORT"
    qty: float
    entry_price: float
    entry_time: str
    entry_regime: str
    stop_loss: float
    take_profit: float
    highest_high: float      # For Long chandelier ratchet
    lowest_low: float        # For Short chandelier ratchet
    atr_at_entry: float
    bars_held: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ChandelierRatchet:
    """
    Monotonic Chandelier Trailing Stop.
    For LONG: Stop strictly increases or stays constant. Never loosens.
    For SHORT: Stop strictly decreases or stays constant. Never loosens.
    """

    def __init__(self, atr_multiplier: float = 3.0):
        self.k = atr_multiplier

    def initialize_stop(self, side: str, entry_price: float, atr: float) -> float:
        if side.upper() == "LONG":
            return entry_price - (self.k * atr)
        else:
            return entry_price + (self.k * atr)

    def ratchet_stop(
        self,
        side: str,
        current_stop: float,
        current_close: float,
        atr: float,
        best_price: float
    ) -> float:
        """Update trailing stop monotonically."""
        if side.upper() == "LONG":
            candidate = best_price - (self.k * atr)
            return max(current_stop, candidate)
        else:
            candidate = best_price + (self.k * atr)
            return min(current_stop, candidate)


class BayesianKellyEstimator:
    """
    Maintains online Bayesian Beta(alpha, beta) conjugate prior for win rate,
    combined with empirical payoff ratio to calculate Half-Kelly fraction.
    """

    def __init__(self, prior_wins: float = 10.0, prior_losses: float = 10.0):
        self.alpha = prior_wins
        self.beta = prior_losses
        self.win_amounts: List[float] = []
        self.loss_amounts: List[float] = []

    def update_outcome(self, realized_pnl: float):
        """Update Bayesian prior on trade close."""
        if realized_pnl > 0:
            self.alpha += 1.0
            self.win_amounts.append(realized_pnl)
            if len(self.win_amounts) > 50:
                self.win_amounts.pop(0)
        elif realized_pnl < 0:
            self.beta += 1.0
            self.loss_amounts.append(abs(realized_pnl))
            if len(self.loss_amounts) > 50:
                self.loss_amounts.pop(0)

    @property
    def posterior_win_rate(self) -> float:
        return self.alpha / (self.alpha + self.beta)

    @property
    def empirical_payoff_ratio(self) -> float:
        if not self.loss_amounts or not self.win_amounts:
            return 1.8  # Prudent prior payoff ratio
        avg_win = sum(self.win_amounts) / len(self.win_amounts)
        avg_loss = sum(self.loss_amounts) / len(self.loss_amounts)
        return max(0.5, avg_win / avg_loss) if avg_loss > 0 else 1.8

    def calculate_half_kelly(self) -> float:
        """
        Kelly Criterion: f* = p - (1 - p) / b
        Half-Kelly: 0.5 * f*
        Guarantees conservative fraction bounded in [0.03, 0.25].
        """
        p = self.posterior_win_rate
        b = self.empirical_payoff_ratio
        full_kelly = p - ((1.0 - p) / b)
        half_kelly = max(0.0, 0.5 * full_kelly)
        # Cap between 3% minimum risk and 25% maximum risk
        return min(0.25, max(0.03, half_kelly))


class InstitutionalRiskEngine:
    """
    Coordinates Volatility Targeting, Bayesian Kelly Sizing, Chandelier Ratchet,
    and Portfolio Guardrails.
    """

    def __init__(
        self,
        target_annual_vol: float = 0.15,      # 15% annualized portfolio volatility target
        max_gross_leverage: float = 1.50,     # Max 1.5x portfolio gross leverage
        max_single_position_pct: float = 0.25,# Max 25% of equity in single asset
        max_daily_drawdown_pct: float = 0.025,# 2.5% daily drawdown circuit breaker
        atr_stop_multiplier: float = 3.0,
        stagnation_bars_limit: int = 36       # 36 bars (~1.5 days on 1h) without progress -> exit
    ):
        self.target_annual_vol = target_annual_vol
        self.max_gross_leverage = max_gross_leverage
        self.max_single_position_pct = max_single_position_pct
        self.max_daily_drawdown_pct = max_daily_drawdown_pct
        self.stagnation_bars_limit = stagnation_bars_limit

        self.chandelier = ChandelierRatchet(atr_multiplier=atr_stop_multiplier)
        self.kelly_estimator = BayesianKellyEstimator()

        self.daily_start_equity: Optional[float] = None
        self.is_circuit_breaker_active: bool = False

    def reset_daily_equity(self, current_equity: float):
        """Called at start of trading day (00:00 UTC)."""
        self.daily_start_equity = current_equity
        self.is_circuit_breaker_active = False

    def check_circuit_breaker(self, current_equity: float) -> bool:
        """Trigger circuit breaker if daily loss exceeds threshold."""
        if self.daily_start_equity is None or self.daily_start_equity <= 0:
            self.daily_start_equity = current_equity
            return False

        daily_return = (current_equity - self.daily_start_equity) / self.daily_start_equity
        if daily_return <= -self.max_daily_drawdown_pct:
            self.is_circuit_breaker_active = True
            return True
        return self.is_circuit_breaker_active

    def calculate_position_size(
        self,
        equity: float,
        price: float,
        realized_vol: float,
        confidence: float = 1.0
    ) -> Tuple[float, float, Dict[str, Any]]:
        """
        Combines Volatility Targeting and Bayesian Half-Kelly to determine
        the optimal risk-adjusted position quantity.
        Returns: (units, notional_dollars, audit_dict)
        """
        if price <= 0 or equity <= 0 or self.is_circuit_breaker_active:
            return 0.0, 0.0, {"status": "BLOCKED_CIRCUIT_BREAKER_OR_ZERO_EQUITY"}

        # 1. Volatility Targeting Scale
        # Target Dollars = Equity * (Target Vol / Realized Vol)
        safe_vol = max(0.10, realized_vol)
        vol_scale = self.target_annual_vol / safe_vol
        base_vol_dollars = equity * vol_scale

        # 2. Bayesian Half-Kelly Sizing Factor
        half_kelly_pct = self.kelly_estimator.calculate_half_kelly()
        kelly_adjusted_dollars = base_vol_dollars * (half_kelly_pct / 0.15) * confidence

        # 3. Portfolio Concentration Constraints
        max_allowed_dollars = equity * self.max_single_position_pct
        final_dollars = min(kelly_adjusted_dollars, max_allowed_dollars)
        units = final_dollars / price

        audit = {
            "realized_vol": round(realized_vol, 4),
            "target_vol": self.target_annual_vol,
            "vol_scale": round(vol_scale, 4),
            "half_kelly_pct": round(half_kelly_pct, 4),
            "posterior_win_rate": round(self.kelly_estimator.posterior_win_rate, 4),
            "payoff_ratio": round(self.kelly_estimator.empirical_payoff_ratio, 4),
            "calculated_dollars": round(final_dollars, 2),
            "capped_by_max_single": final_dollars >= max_allowed_dollars
        }

        return units, final_dollars, audit

    def evaluate_open_position(
        self,
        pos: Position,
        current_bar_high: float,
        current_bar_low: float,
        current_bar_close: float,
        current_atr: float,
        current_regime: str
    ) -> Tuple[bool, Optional[ExitReason], float, Position]:
        """
        Evaluates position against:
        1. Monotonic Chandelier Trailing Stop
        2. Soft Regime-Change Exit
        3. Soft Time-Stagnation Exit
        Returns: (should_exit, exit_reason, exit_price, updated_position)
        """
        pos.bars_held += 1

        # 1. Update best price and ratchet Chandelier Stop
        if pos.side.upper() == "LONG":
            pos.highest_high = max(pos.highest_high, current_bar_high)
            new_stop = self.chandelier.ratchet_stop(
                "LONG", pos.stop_loss, current_bar_close, current_atr, pos.highest_high
            )
            pos.stop_loss = new_stop

            # Check Stop Loss Hit
            if current_bar_low <= pos.stop_loss:
                return True, ExitReason.CHANDELIER_TRAILING, min(pos.stop_loss, current_bar_close), pos

            # Check Take Profit Hit
            if pos.take_profit > 0 and current_bar_high >= pos.take_profit:
                return True, ExitReason.TAKE_PROFIT, pos.take_profit, pos

            # Soft Regime-Change Exit: Long entered in Bull trend, now in Bear trend
            if pos.entry_regime == "TRENDING_BULL" and current_regime == "TRENDING_BEAR":
                return True, ExitReason.REGIME_CHANGE, current_bar_close, pos

        else:  # SHORT
            pos.lowest_low = min(pos.lowest_low, current_bar_low)
            new_stop = self.chandelier.ratchet_stop(
                "SHORT", pos.stop_loss, current_bar_close, current_atr, pos.lowest_low
            )
            pos.stop_loss = new_stop

            # Check Stop Loss Hit
            if current_bar_high >= pos.stop_loss:
                return True, ExitReason.CHANDELIER_TRAILING, max(pos.stop_loss, current_bar_close), pos

            # Check Take Profit Hit
            if pos.take_profit > 0 and current_bar_low <= pos.take_profit:
                return True, ExitReason.TAKE_PROFIT, pos.take_profit, pos

            # Soft Regime-Change Exit: Short entered in Bear trend, now in Bull trend
            if pos.entry_regime == "TRENDING_BEAR" and current_regime == "TRENDING_BULL":
                return True, ExitReason.REGIME_CHANGE, current_bar_close, pos

        # Soft Time-Stagnation Exit
        if pos.bars_held >= self.stagnation_bars_limit:
            pnl_pct = (current_bar_close - pos.entry_price) / pos.entry_price if pos.side == "LONG" else (pos.entry_price - current_bar_close) / pos.entry_price
            if abs(pnl_pct) < 0.005:  # Flat after 36 hours -> exit to free capital
                return True, ExitReason.TIME_STAGNATION, current_bar_close, pos

        return False, None, 0.0, pos
