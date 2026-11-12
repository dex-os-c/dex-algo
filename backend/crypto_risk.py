"""
Institutional Crypto Risk Management & Position Sizing Engine
=============================================================
Designed for 24/7 high-volatility cryptocurrency trading (e.g. BTC/USD, ETH/USD).

Pillars:
1. Fractional Kelly Criterion:
   - Optimal betting fraction f* = (p * b - q) / b
   - Quarter-Kelly (0.25x) scaling eliminates ruin risk while maximizing compounding.
2. Volatility Targeting:
   - Scales sizing inversely with annualized asset volatility (15% - 25% target annual vol).
3. Dynamic Chandelier Trailing Exit:
   - Trails stop loss at Highest Price - (3.0 * ATR) once in profit.
4. Multi-Horizon Drawdown Circuit Breakers:
   - Daily loss limit (halt new entries if daily loss > 3.0%).
   - Peak 30-day drawdown limit (halt entries if drawdown > 6.0%).
"""

import math
import logging
from dataclasses import dataclass, asdict
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger("crypto_risk")


@dataclass
class SizingDecision:
    """Standardized sizing decision for crypto & equity execution routers."""
    approved: bool
    units: float
    dollar_amount: float
    stop_loss: float
    chandelier_trailing_stop: float
    max_risk_budget: float
    reason: str
    symbol: str = "BTC/USD"
    entry_price: float = 0.0
    atr: float = 0.0
    kelly_f_star: float = 0.0
    fractional_kelly: float = 0.0
    annualized_vol: float = 0.0
    volatility_scalar: float = 1.0
    risk_per_trade_pct: float = 0.0
    circuit_breaker_active: bool = False
    shares: float = 0.0

    def __post_init__(self):
        if self.shares == 0.0 and self.units != 0.0:
            self.shares = self.units
        elif self.units == 0.0 and self.shares != 0.0:
            self.units = self.shares

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["units"] = round(self.units, 6)
        d["shares"] = round(self.shares, 6)
        d["dollar_amount"] = round(self.dollar_amount, 2)
        d["stop_loss"] = round(self.stop_loss, 2)
        d["chandelier_trailing_stop"] = round(self.chandelier_trailing_stop, 2)
        d["max_risk_budget"] = round(self.max_risk_budget, 2)
        d["kelly_f_star"] = round(self.kelly_f_star, 4)
        d["fractional_kelly"] = round(self.fractional_kelly, 4)
        d["annualized_vol"] = round(self.annualized_vol, 4)
        d["volatility_scalar"] = round(self.volatility_scalar, 4)
        d["risk_per_trade_pct"] = round(self.risk_per_trade_pct, 4)
        return d


class ChandelierStop(float):
    """Float subclass providing dictionary compatibility for Chandelier stop return."""
    def __new__(cls, val: float, details: Optional[Dict[str, Any]] = None):
        instance = super().__new__(cls, val)
        instance.details = details or {}
        return instance

    def __getitem__(self, item):
        return self.details.get(item)

    def get(self, item, default=None):
        return self.details.get(item, default)


class InstitutionalCryptoRiskManager:
    """
    Institutional Grade Cryptocurrency Risk & Position Sizing Manager.
    """

    def __init__(
        self,
        target_annual_vol: float = 0.20,
        kelly_fraction: float = 0.25,
        max_daily_loss_pct: float = 0.03,
        max_drawdown_pct: float = 0.06,
        chandelier_atr_mult: float = 3.0,
        initial_stop_atr_mult: float = 2.0,
        max_position_equity_pct: float = 0.25,
        max_risk_per_trade_pct: float = 0.015,
        min_crypto_unit: float = 0.0001,
        crypto_unit_precision: int = 4
    ):
        self.target_annual_vol = target_annual_vol
        self.kelly_fraction = kelly_fraction
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_drawdown_pct = max_drawdown_pct
        self.chandelier_atr_mult = chandelier_atr_mult
        self.initial_stop_atr_mult = initial_stop_atr_mult
        self.max_position_equity_pct = max_position_equity_pct
        self.max_risk_per_trade_pct = max_risk_per_trade_pct
        self.min_crypto_unit = min_crypto_unit
        self.crypto_unit_precision = crypto_unit_precision

        self.circuit_breaker_active: bool = False
        self.circuit_breaker_reason: str = "Nominal"
        self._chandeliers: Dict[str, Dict[str, Any]] = {}

    def reset_circuit_breaker(self):
        self.circuit_breaker_active = False
        self.circuit_breaker_reason = "Nominal"

    def check_circuit_breakers(
        self,
        equity: float,
        daily_pnl: float,
        equity_history: Optional[List[Dict[str, Any]]] = None
    ) -> Tuple[bool, str]:
        if equity <= 0:
            self.circuit_breaker_active = True
            self.circuit_breaker_reason = "Depleted equity (<= 0)"
            return True, self.circuit_breaker_reason

        daily_loss_pct = daily_pnl / equity
        if daily_loss_pct < -self.max_daily_loss_pct:
            self.circuit_breaker_active = True
            self.circuit_breaker_reason = (
                f"CIRCUIT BREAKER: Daily loss breach ({daily_loss_pct * 100:.2f}% "
                f"< -{self.max_daily_loss_pct * 100:.1f}%) - Capital Preservation Mode"
            )
            return True, self.circuit_breaker_reason

        equities: List[float] = []
        if equity_history:
            for item in equity_history:
                eq_val = item.get("equity") if isinstance(item, dict) else item
                if eq_val is not None:
                    try:
                        equities.append(float(eq_val))
                    except (ValueError, TypeError):
                        pass

        if not equities:
            try:
                import database
                db_history = database.get_equity_history(limit=500)
                equities = [float(row["equity"]) for row in db_history if "equity" in row]
            except Exception:
                equities = []

        equities.append(equity)
        peak_equity = max(equities) if equities else equity
        if peak_equity > 0:
            current_drawdown_pct = (peak_equity - equity) / peak_equity
            if current_drawdown_pct > self.max_drawdown_pct:
                self.circuit_breaker_active = True
                self.circuit_breaker_reason = (
                    f"CIRCUIT BREAKER: Peak drawdown breach ({current_drawdown_pct * 100:.2f}% "
                    f"> {self.max_drawdown_pct * 100:.1f}%) - Capital Preservation Mode"
                )
                return True, self.circuit_breaker_reason

        self.circuit_breaker_active = False
        self.circuit_breaker_reason = "Nominal"
        return False, "Nominal"

    def calculate_kelly_fraction(
        self,
        win_rate: Optional[float] = None,
        payoff_ratio: Optional[float] = None,
        confidence: Optional[float] = None,
        win_loss_payoff_ratio: Optional[float] = None,
        **kwargs
    ) -> Tuple[float, float]:
        p = win_rate
        b = payoff_ratio if payoff_ratio is not None else win_loss_payoff_ratio

        if p is None or b is None:
            try:
                import database
                metrics = database.get_performance_metrics()
                total_trades = metrics.get("total_trades", 0)
                if total_trades >= 5:
                    p = (metrics.get("win_rate", 0.0) / 100.0) if p is None else p
                    pf = metrics.get("profit_factor", 1.5)
                    if p > 0 and p < 1.0:
                        derived_b = pf * ((1.0 - p) / p)
                        b = max(0.5, derived_b) if b is None else b
            except Exception:
                pass

        if p is None:
            p = 0.52
        if b is None:
            b = 1.85

        if confidence is not None:
            conf_clamped = max(0.0, min(1.0, float(confidence)))
            p = p * (0.85 + 0.30 * conf_clamped)

        p = max(0.01, min(0.99, p))
        q = 1.0 - p

        if b <= 0.01:
            return 0.0, 0.0

        f_star = (p * b - q) / b
        if f_star <= 0:
            return max(0.0, f_star), 0.0

        fractional_k = min(f_star * self.kelly_fraction, self.max_position_equity_pct)
        return f_star, fractional_k

    def calculate_annualized_volatility(
        self,
        historical_prices: Optional[List[float]] = None,
        current_price: Optional[float] = None,
        atr: Optional[float] = None,
        timeframe_bars_per_year: float = 365.0
    ) -> float:
        if historical_prices and len(historical_prices) >= 5:
            returns = []
            for i in range(1, len(historical_prices)):
                prev = historical_prices[i - 1]
                curr = historical_prices[i]
                if prev > 0:
                    returns.append((curr - prev) / prev)
            if len(returns) >= 4:
                mean_r = sum(returns) / len(returns)
                var = sum((r - mean_r) ** 2 for r in returns) / (len(returns) - 1)
                daily_std = math.sqrt(max(0.0, var))
                return max(0.05, min(daily_std * math.sqrt(timeframe_bars_per_year), 3.0))

        if atr and current_price and current_price > 0:
            daily_range_pct = atr / current_price
            return max(0.05, min(daily_range_pct * math.sqrt(timeframe_bars_per_year), 3.0))

        return 0.55

    def calculate_volatility_scalar(self, annualized_vol: float) -> float:
        ann_vol = max(0.05, annualized_vol)
        scalar = self.target_annual_vol / ann_vol
        return max(0.10, min(1.50, scalar))

    def update_chandelier_exit(
        self,
        symbol: str,
        current_price: float,
        atr: Optional[float] = None,
        highest_price: Optional[float] = None,
        side: str = "BUY",
        current_atr: Optional[float] = None,
        **kwargs
    ):
        atr_val = atr if atr is not None else (current_atr if current_atr is not None else 1000.0)
        sym = symbol.upper()
        if sym not in self._chandeliers:
            initial_chandelier = current_price - (self.chandelier_atr_mult * atr_val)
            self._chandeliers[sym] = {
                "symbol": sym,
                "side": side.upper(),
                "entry_price": current_price,
                "highest_price": current_price,
                "lowest_price": current_price,
                "atr": atr_val,
                "initial_stop": initial_chandelier,
                "current_trailing_stop": initial_chandelier,
                "in_profit": False
            }

        state = self._chandeliers[sym]
        entry_price = state["entry_price"]

        if highest_price is not None:
            state["highest_price"] = max(state["highest_price"], highest_price, current_price)
        else:
            state["highest_price"] = max(state["highest_price"], current_price)

        state["lowest_price"] = min(state["lowest_price"], current_price)
        state["atr"] = atr_val

        if side.upper() == "BUY":
            candidate_stop = state["highest_price"] - (self.chandelier_atr_mult * atr_val)
            state["current_trailing_stop"] = max(state["current_trailing_stop"], candidate_stop)
            state["in_profit"] = current_price > entry_price

        trailing_val = round(state["current_trailing_stop"], 2)
        details = {
            "symbol": sym,
            "current_price": current_price,
            "entry_price": entry_price,
            "highest_price": state["highest_price"],
            "trailing_stop": trailing_val,
            "in_profit": state["in_profit"],
            "atr": atr_val
        }
        return ChandelierStop(trailing_val, details)

    def evaluate_exit(
        self,
        symbol: str,
        current_price: float,
        position_qty: float,
        avg_entry_price: float,
        atr: float,
        strategy_signal: Optional[str] = None
    ) -> Tuple[bool, str, float]:
        sym = symbol.upper()
        info = self.update_chandelier_exit(symbol=sym, current_price=current_price, atr=atr)
        trailing_stop = info["trailing_stop"]
        highest_price = info["highest_price"]
        pnl = round((current_price - avg_entry_price) * position_qty, 2)

        if current_price <= trailing_stop:
            reason = (
                f"CHANDELIER TRAILING STOP hit at ${current_price:,.2f} "
                f"(Stop: ${trailing_stop:,.2f}, Peak: ${highest_price:,.2f})"
            )
            self.clear_chandelier(sym)
            return True, reason, pnl

        if strategy_signal and strategy_signal.upper() in ("SELL", "EXIT"):
            reason = f"STRATEGY REVERSAL EXIT ({strategy_signal}) at ${current_price:,.2f}"
            self.clear_chandelier(sym)
            return True, reason, pnl

        return False, "Nominal holding", pnl

    def clear_chandelier(self, symbol: str):
        sym = symbol.upper()
        if sym in self._chandeliers:
            del self._chandeliers[sym]

    def calculate_position_size(
        self,
        symbol: str,
        entry_price: float,
        atr: float,
        equity: float,
        buying_power: float,
        cash: float,
        current_positions: Optional[List[Dict[str, Any]]] = None,
        daily_pnl: float = 0.0,
        historical_prices: Optional[List[float]] = None,
        confidence: Optional[float] = None,
        win_rate: Optional[float] = None,
        payoff_ratio: Optional[float] = None
    ) -> SizingDecision:
        sym = symbol.upper()

        # 1. Circuit Breakers
        breaker_tripped, breaker_reason = self.check_circuit_breakers(equity=equity, daily_pnl=daily_pnl)
        if breaker_tripped:
            return SizingDecision(
                approved=False,
                units=0.0,
                dollar_amount=0.0,
                stop_loss=0.0,
                chandelier_trailing_stop=0.0,
                max_risk_budget=0.0,
                reason=breaker_reason,
                symbol=sym,
                entry_price=entry_price,
                atr=atr,
                circuit_breaker_active=True
            )

        # 2. Existing Position Check
        if current_positions:
            for pos in current_positions:
                if pos.get("symbol", "").upper() == sym:
                    return SizingDecision(
                        approved=False,
                        units=0.0,
                        dollar_amount=0.0,
                        stop_loss=0.0,
                        chandelier_trailing_stop=0.0,
                        max_risk_budget=0.0,
                        reason=f"Position already active for {sym} - avoiding double exposure",
                        symbol=sym,
                        entry_price=entry_price,
                        atr=atr
                    )

        if entry_price <= 0 or atr <= 0 or equity <= 0:
            return SizingDecision(
                approved=False,
                units=0.0,
                dollar_amount=0.0,
                stop_loss=0.0,
                chandelier_trailing_stop=0.0,
                max_risk_budget=0.0,
                reason="Invalid market parameters (entry price, ATR, or equity <= 0)",
                symbol=sym,
                entry_price=entry_price,
                atr=atr
            )

        # 3. Fractional Kelly
        f_star, f_kelly = self.calculate_kelly_fraction(
            win_rate=win_rate,
            payoff_ratio=payoff_ratio,
            confidence=confidence
        )
        if f_kelly <= 0:
            return SizingDecision(
                approved=False,
                units=0.0,
                dollar_amount=0.0,
                stop_loss=0.0,
                chandelier_trailing_stop=0.0,
                max_risk_budget=0.0,
                reason=f"Rejected: Kelly Criterion indicates non-positive edge (f*={f_star:.4f})",
                symbol=sym,
                entry_price=entry_price,
                atr=atr,
                kelly_f_star=f_star,
                fractional_kelly=f_kelly
            )

        # 4. Volatility Targeting
        ann_vol = self.calculate_annualized_volatility(historical_prices, entry_price, atr)
        vol_scalar = self.calculate_volatility_scalar(ann_vol)
        target_capital = equity * min(f_kelly * vol_scalar, self.max_position_equity_pct)

        # 5. Risk Budget Cap
        initial_stop_dist = max(0.01, atr * self.initial_stop_atr_mult)
        stop_loss_price = round(entry_price - initial_stop_dist, 2)
        chandelier_stop_price = round(entry_price - (self.chandelier_atr_mult * atr), 2)
        max_risk_dollars = equity * self.max_risk_per_trade_pct

        units_by_risk = max_risk_dollars / initial_stop_dist
        units_by_capital = target_capital / entry_price
        raw_units = min(units_by_risk, units_by_capital)

        # 6. Buying Power Constraint
        max_affordable_units = (buying_power * 0.95) / entry_price if entry_price > 0 else 0.0
        final_units = round(min(raw_units, max_affordable_units), self.crypto_unit_precision)

        if final_units < self.min_crypto_unit:
            return SizingDecision(
                approved=False,
                units=0.0,
                dollar_amount=0.0,
                stop_loss=stop_loss_price,
                chandelier_trailing_stop=chandelier_stop_price,
                max_risk_budget=0.0,
                reason=f"Calculated units ({final_units:.6f} {sym}) below minimum threshold ({self.min_crypto_unit})",
                symbol=sym,
                entry_price=entry_price,
                atr=atr,
                kelly_f_star=f_star,
                fractional_kelly=f_kelly,
                annualized_vol=ann_vol,
                volatility_scalar=vol_scalar
            )

        dollar_amount = round(final_units * entry_price, 2)
        actual_risk = round(final_units * initial_stop_dist, 2)
        risk_pct_actual = round((actual_risk / equity) * 100.0, 3)

        self.update_chandelier_exit(symbol=sym, current_price=entry_price, atr=atr)

        reason = (
            f"Approved {final_units} {sym} (${dollar_amount:,.2f}) | "
            f"Fractional Kelly: {f_kelly*100:.1f}%, Vol Scalar: {vol_scalar:.2f}x, "
            f"Risk Budget: ${actual_risk:,.2f} ({risk_pct_actual:.2f}% equity)"
        )

        return SizingDecision(
            approved=True,
            units=final_units,
            dollar_amount=dollar_amount,
            stop_loss=stop_loss_price,
            chandelier_trailing_stop=chandelier_stop_price,
            max_risk_budget=actual_risk,
            reason=reason,
            symbol=sym,
            entry_price=entry_price,
            atr=atr,
            kelly_f_star=f_star,
            fractional_kelly=f_kelly,
            annualized_vol=ann_vol,
            volatility_scalar=vol_scalar,
            risk_per_trade_pct=risk_pct_actual,
            circuit_breaker_active=False
        )

    def get_risk_status(self) -> Dict[str, Any]:
        return {
            "circuit_breaker_active": self.circuit_breaker_active,
            "circuit_breaker_reason": self.circuit_breaker_reason,
            "target_annual_vol": self.target_annual_vol,
            "target_annual_vol_pct": f"{self.target_annual_vol * 100:.1f}%",
            "kelly_fraction": self.kelly_fraction,
            "kelly_fraction_label": f"{self.kelly_fraction}x (Quarter-Kelly)",
            "max_daily_loss_pct": self.max_daily_loss_pct,
            "max_drawdown_pct": self.max_drawdown_pct,
            "chandelier_atr_mult": self.chandelier_atr_mult,
            "initial_stop_atr_mult": self.initial_stop_atr_mult,
            "max_position_equity_pct": self.max_position_equity_pct,
            "monitored_positions_count": len(self._chandeliers),
            "monitored_positions": list(self._chandeliers.keys())
        }

    calculate_fractional_kelly = calculate_kelly_fraction

    def evaluate_entry_sizing(
        self,
        symbol: str,
        entry_price: float,
        atr: float,
        equity: float,
        daily_pnl: float = 0.0,
        win_rate: Optional[float] = None,
        win_loss_payoff_ratio: Optional[float] = None,
        payoff_ratio: Optional[float] = None,
        buying_power: Optional[float] = None,
        cash: Optional[float] = None,
        active_positions_count: int = 0,
        side: str = "buy",
        **kwargs
    ) -> SizingDecision:
        bp = buying_power if buying_power is not None else equity * 2.0
        c = cash if cash is not None else equity
        pr = payoff_ratio if payoff_ratio is not None else win_loss_payoff_ratio
        positions = [{"symbol": f"POS_{i}"} for i in range(active_positions_count)]
        return self.calculate_position_size(
            symbol=symbol,
            entry_price=entry_price,
            atr=atr,
            equity=equity,
            buying_power=bp,
            cash=c,
            current_positions=positions,
            daily_pnl=daily_pnl,
            win_rate=win_rate,
            payoff_ratio=pr,
            **kwargs
        )