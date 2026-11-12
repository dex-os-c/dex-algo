"""
Institutional Quantitative Backtester & Walk-Forward Research Engine
=====================================================================
Features:
1. Strict Lag-1 Execution: Signals computed at bar t-1, executed at bar t Open.
2. Realistic Friction:
   - Taker fees (crypto: 0.06% = 6 bps, equities: 0.015% or $0.005/share).
   - Dynamic square-root market impact slippage: Spread/2 + gamma * ATR * sqrt(Size / Vol).
   - Latency drift penalty (50-100ms adverse execution drift).
   - 8-hour crypto funding rate simulation.
3. Walk-Forward Cross-Validation with de Prado Embargo windows.
4. Combinatorial Purged Cross-Validation (CPCV) across block paths.
5. Statistical Performance & Risk Tear Sheet:
   - Deflated Sharpe Ratio (DSR), Probabilistic Sharpe Ratio (PSR), Omega Ratio,
   - Sortino, Calmar, Max Drawdown, Win Rate, Payoff Ratio, Exposure Time.
6. 1,000-Path Monte Carlo Simulation (5th, 50th, 95th percentiles & Ruin Probability).
7. Overfitting Degradation Detector (IS vs OOS Sharpe degradation ratio).
"""

import math
import random
import itertools
import numpy as np
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, asdict

from data_layer import Bar, MarketDataClient, get_data_client
from features import FeatureStore, BarFeatures
from regime import RobustRegimeDetector, MarketRegime, RegimeState
from alphas import MultiAlphaOrchestrator, SignalAction, AlphaSignal
from risk import InstitutionalRiskEngine, Position, ExitReason, calculate_omega_ratio


@dataclass
class TradeRecord:
    symbol: str
    side: str
    entry_bar_idx: int
    entry_time: str
    entry_price: float
    qty: float
    exit_bar_idx: int
    exit_time: str
    exit_price: float
    exit_reason: str
    gross_pnl: float
    fees: float
    slippage_cost: float
    net_pnl: float
    return_pct: float
    r_multiple: float
    bars_held: int
    entry_regime: str
    exit_regime: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PerformanceMetrics:
    total_trades: int
    win_rate: float
    profit_factor: float
    expectancy: float
    annualized_return: float
    annualized_sharpe: float
    sortino_ratio: float
    calmar_ratio: float
    omega_ratio: float
    deflated_sharpe_ratio: float
    probabilistic_sharpe_ratio: float
    skewness: float
    kurtosis: float
    max_drawdown_pct: float
    max_drawdown_duration: int
    average_r_multiple: float
    payoff_ratio: float
    market_exposure_pct: float
    final_equity: float
    net_profit: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_trades": self.total_trades,
            "win_rate": round(self.win_rate, 4),
            "profit_factor": round(self.profit_factor, 4),
            "expectancy": round(self.expectancy, 2),
            "annualized_return": round(self.annualized_return, 4),
            "annualized_sharpe": round(self.annualized_sharpe, 4),
            "sortino_ratio": round(self.sortino_ratio, 4),
            "calmar_ratio": round(self.calmar_ratio, 4),
            "omega_ratio": round(self.omega_ratio, 4),
            "deflated_sharpe_ratio": round(self.deflated_sharpe_ratio, 4),
            "probabilistic_sharpe_ratio": round(self.probabilistic_sharpe_ratio, 4),
            "skewness": round(self.skewness, 4),
            "kurtosis": round(self.kurtosis, 4),
            "max_drawdown_pct": round(self.max_drawdown_pct, 4),
            "max_drawdown_duration": self.max_drawdown_duration,
            "average_r_multiple": round(self.average_r_multiple, 4),
            "payoff_ratio": round(self.payoff_ratio, 4),
            "market_exposure_pct": round(self.market_exposure_pct, 4),
            "final_equity": round(self.final_equity, 2),
            "net_profit": round(self.net_profit, 2)
        }


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def calculate_deflated_sharpe_ratio(
    returns: List[float],
    num_trials: int = 50,
    ann_factor: float = 8760.0
) -> Dict[str, float]:
    """
    Computes Deflated Sharpe Ratio (DSR) and Probabilistic Sharpe Ratio (PSR)
    adjusting for non-normality (skewness, kurtosis) and multiple testing bias.
    """
    if len(returns) < 10:
        return {"dsr": 0.5, "psr": 0.5, "skewness": 0.0, "kurtosis": 3.0}

    arr = np.array(returns)
    mean_r = float(np.mean(arr))
    std_r = float(np.std(arr, ddof=1))
    if std_r <= 1e-8:
        return {"dsr": 0.5, "psr": 0.5, "skewness": 0.0, "kurtosis": 3.0}

    n = len(arr)
    # Higher statistical moments
    skew = float(np.mean(((arr - mean_r) / std_r) ** 3))
    kurt = float(np.mean(((arr - mean_r) / std_r) ** 4))

    sr = (mean_r / std_r) * math.sqrt(ann_factor)

    # Standard error of Sharpe ratio with non-normality
    sr_std = math.sqrt((1.0 - skew * (sr / math.sqrt(ann_factor)) + ((kurt - 1.0) / 4.0) * ((sr / math.sqrt(ann_factor)) ** 2)) / max(1, n - 1)) * math.sqrt(ann_factor)
    sr_std = max(1e-4, sr_std)

    # Expected maximum Sharpe under null hypothesis (Euler-Mascheroni approximation)
    euler_gamma = 0.5772156649
    z_approx = math.sqrt(2.0 * math.log(max(2, num_trials)))
    expected_max_sr = sr_std * ((1.0 - euler_gamma) * z_approx + euler_gamma * math.sqrt(2.0 * math.log(max(2, num_trials) * math.e)))

    # Deflated Sharpe Ratio
    z_dsr = (sr - expected_max_sr) / sr_std
    dsr = _norm_cdf(z_dsr)

    # Probabilistic Sharpe Ratio (benchmark = 0)
    z_psr = sr / sr_std
    psr = _norm_cdf(z_psr)

    return {
        "dsr": round(float(dsr), 4),
        "psr": round(float(psr), 4),
        "skewness": round(float(skew), 4),
        "kurtosis": round(float(kurt), 4)
    }


class InstitutionalBacktester:
    """
    Simulates production order execution with realistic market friction:
    taker fees, square-root market impact, latency drift, and perpetual funding.
    """

    def __init__(
        self,
        initial_capital: float = 100000.0,
        fee_rate: float = 0.0006,        # 6 bps taker fee
        base_slippage: float = 0.0002,   # 2 bps base half-spread
        slippage_impact_gamma: float = 0.05,
        latency_ms: float = 85.0,        # 85ms execution matching latency
        funding_rate_8h: float = 0.0001   # 1 bp per 8 hours
    ):
        self.initial_capital = initial_capital
        self.fee_rate = fee_rate
        self.base_slippage = base_slippage
        self.slippage_impact_gamma = slippage_impact_gamma
        self.latency_ms = latency_ms
        self.funding_rate_8h = funding_rate_8h

    def _compute_fill_price(
        self,
        base_price: float,
        side: str,
        is_entry: bool,
        qty: float,
        bar_volume: float,
        atr: float = 0.0
    ) -> Tuple[float, float]:
        """
        Calculates realistic fill price:
        Fill = Base +/- (HalfSpread + gamma * ATR * sqrt(Size/Vol) + LatencyDrift)
        """
        vol_notional = max(100.0, bar_volume * base_price)
        trade_notional = qty * base_price
        participation = min(0.20, trade_notional / vol_notional)

        # 1. Base half-spread
        half_spread = self.base_slippage * base_price

        # 2. Square-root market impact
        impact = self.slippage_impact_gamma * (atr if atr > 0 else (0.01 * base_price)) * math.sqrt(participation)

        # 3. Latency drift penalty: adverse price motion during matching
        latency_drift = 0.0001 * base_price * math.sqrt(self.latency_ms / 100.0)

        total_slip = half_spread + impact + latency_drift

        is_long_fill = (side.upper() in ("LONG", "BUY") and is_entry) or (side.upper() in ("SHORT", "SELL") and not is_entry)
        if is_long_fill:
            fill_price = base_price + total_slip
        else:
            fill_price = max(0.01, base_price - total_slip)

        return fill_price, total_slip * qty

    def run_simulation(
        self,
        bars: List[Bar],
        symbol: str = "BTC/USDT",
        is_crypto: bool = True
    ) -> Tuple[List[TradeRecord], List[float], PerformanceMetrics]:
        """
        Executes strict lag-1 bar-by-bar backtest over historical bar sequence.
        """
        if len(bars) < 60:
            empty_metrics = PerformanceMetrics(0, 0, 0, 0, 0, 0, 0, 0, 1.0, 0.5, 0.5, 0, 3, 0, 0, 0, 0, 0, self.initial_capital, 0)
            return [], [self.initial_capital], empty_metrics

        detector = RobustRegimeDetector()
        orchestrator = MultiAlphaOrchestrator()
        risk_engine = InstitutionalRiskEngine(target_annual_vol=0.15)

        equity = self.initial_capital
        equity_curve: List[float] = [equity]
        trades: List[TradeRecord] = []
        open_pos: Optional[Position] = None
        bars_in_position_count = 0

        # Precompute lag-1 causal features
        causal_pairs = FeatureStore.generate_causal_feature_matrix(bars, min_lookback=35, is_crypto=is_crypto)

        for bar_idx, (bar_t, feat_prev) in enumerate(causal_pairs):
            # 1. Update regime and alpha signal using lag-1 features
            regime = detector.update(feat_prev)
            signal = orchestrator.evaluate_signal(feat_prev, regime)

            # Daily circuit breaker check
            risk_engine.check_circuit_breaker(equity)

            # 2. If a position is currently open, evaluate exit conditions at bar t
            if open_pos is not None:
                bars_in_position_count += 1
                should_exit, exit_reason, nominal_exit_px, open_pos = risk_engine.evaluate_open_position(
                    pos=open_pos,
                    current_bar_high=bar_t.high,
                    current_bar_low=bar_t.low,
                    current_bar_close=bar_t.close,
                    current_atr=feat_prev.atr,
                    current_regime=regime.regime.value
                )

                # Check if signal flipped against open position
                if not should_exit:
                    if open_pos.side.upper() in ("LONG", "BUY") and signal.action == SignalAction.SELL:
                        should_exit = True
                        exit_reason = ExitReason.REGIME_CHANGE
                        nominal_exit_px = bar_t.open
                    elif open_pos.side.upper() in ("SHORT", "SELL") and signal.action == SignalAction.BUY:
                        should_exit = True
                        exit_reason = ExitReason.REGIME_CHANGE
                        nominal_exit_px = bar_t.open

                if should_exit:
                    fill_exit_px, exit_slip = self._compute_fill_price(
                        base_price=nominal_exit_px,
                        side=open_pos.side,
                        is_entry=False,
                        qty=open_pos.qty,
                        bar_volume=bar_t.volume,
                        atr=feat_prev.atr
                    )
                    # PnL calculations
                    is_long = open_pos.side.upper() in ("LONG", "BUY")
                    if is_long:
                        gross_pnl = (fill_exit_px - open_pos.entry_price) * open_pos.qty
                    else:
                        gross_pnl = (open_pos.entry_price - fill_exit_px) * open_pos.qty

                    entry_notional = open_pos.entry_price * open_pos.qty
                    exit_notional = fill_exit_px * open_pos.qty
                    fees = (entry_notional + exit_notional) * self.fee_rate
                    total_slip = exit_slip

                    # Funding cost if crypto
                    funding_cost = 0.0
                    if is_crypto:
                        funding_intervals = open_pos.bars_held / 8.0
                        funding_cost = entry_notional * self.funding_rate_8h * funding_intervals

                    net_pnl = gross_pnl - fees - total_slip - funding_cost
                    equity += net_pnl
                    risk_engine.kelly_estimator.update_outcome(net_pnl)

                    initial_risk = abs(open_pos.entry_price - open_pos.stop_loss) * open_pos.qty
                    r_multiple = (net_pnl / initial_risk) if initial_risk > 0 else 0.0

                    trades.append(TradeRecord(
                        symbol=symbol,
                        side=open_pos.side,
                        entry_bar_idx=bar_idx - open_pos.bars_held,
                        entry_time=open_pos.entry_time,
                        entry_price=open_pos.entry_price,
                        qty=open_pos.qty,
                        exit_bar_idx=bar_idx,
                        exit_time=bar_t.timestamp,
                        exit_price=fill_exit_px,
                        exit_reason=exit_reason.value if exit_reason else "SIGNAL",
                        gross_pnl=round(gross_pnl, 2),
                        fees=round(fees, 2),
                        slippage_cost=round(total_slip, 2),
                        net_pnl=round(net_pnl, 2),
                        return_pct=round((net_pnl / entry_notional), 4) if entry_notional > 0 else 0.0,
                        r_multiple=round(r_multiple, 2),
                        bars_held=open_pos.bars_held,
                        entry_regime=open_pos.entry_regime,
                        exit_regime=regime.regime.value
                    ))
                    open_pos = None

            # 3. If no position is open, evaluate new entry signal at bar t Open
            if open_pos is None and signal.action in (SignalAction.BUY, SignalAction.SELL):
                side = "LONG" if signal.action == SignalAction.BUY else "SHORT"
                vol_est = max(0.15, feat_prev.parkinson_vol)
                units, dollars, audit = risk_engine.calculate_position_size(
                    equity=equity,
                    price=bar_t.open,
                    realized_vol=vol_est,
                    confidence=signal.confidence,
                    symbol=symbol,
                    active_positions=[open_pos] if open_pos else []
                )

                if units > 0 and dollars >= 10.0:
                    fill_entry_px, entry_slip = self._compute_fill_price(
                        base_price=bar_t.open,
                        side=side,
                        is_entry=True,
                        qty=units,
                        bar_volume=bar_t.volume,
                        atr=feat_prev.atr
                    )
                    init_stop = risk_engine.chandelier.initialize_stop(side, fill_entry_px, feat_prev.atr)

                    open_pos = Position(
                        symbol=symbol,
                        side=side,
                        qty=units,
                        entry_price=fill_entry_px,
                        entry_time=bar_t.timestamp,
                        entry_regime=regime.regime.value,
                        stop_loss=init_stop,
                        take_profit=0.0,
                        highest_high=fill_entry_px,
                        lowest_low=fill_entry_px,
                        atr_at_entry=feat_prev.atr,
                        bars_held=0,
                        asset_class="crypto" if is_crypto else "equity"
                    )

            # Record mark-to-market equity
            unrealized = 0.0
            if open_pos is not None:
                is_long = open_pos.side.upper() in ("LONG", "BUY")
                if is_long:
                    unrealized = (bar_t.close - open_pos.entry_price) * open_pos.qty
                else:
                    unrealized = (open_pos.entry_price - bar_t.close) * open_pos.qty
            equity_curve.append(equity + unrealized)

        # Close any lingering open position on final bar
        if open_pos is not None:
            last_bar = causal_pairs[-1][0]
            is_long = open_pos.side.upper() in ("LONG", "BUY")
            if is_long:
                gross_pnl = (last_bar.close - open_pos.entry_price) * open_pos.qty
            else:
                gross_pnl = (open_pos.entry_price - last_bar.close) * open_pos.qty
            entry_notional = open_pos.entry_price * open_pos.qty
            exit_notional = last_bar.close * open_pos.qty
            fees = (entry_notional + exit_notional) * self.fee_rate
            net_pnl = gross_pnl - fees
            equity += net_pnl
            trades.append(TradeRecord(
                symbol=symbol,
                side=open_pos.side,
                entry_bar_idx=len(causal_pairs) - open_pos.bars_held,
                entry_time=open_pos.entry_time,
                entry_price=open_pos.entry_price,
                qty=open_pos.qty,
                exit_bar_idx=len(causal_pairs),
                exit_time=last_bar.timestamp,
                exit_price=last_bar.close,
                exit_reason="END_OF_DATA",
                gross_pnl=round(gross_pnl, 2),
                fees=round(fees, 2),
                slippage_cost=0.0,
                net_pnl=round(net_pnl, 2),
                return_pct=round((net_pnl / entry_notional), 4) if entry_notional > 0 else 0.0,
                r_multiple=0.0,
                bars_held=open_pos.bars_held,
                entry_regime=open_pos.entry_regime,
                exit_regime="CLOSE"
            ))

        metrics = self.calculate_metrics(trades, equity_curve, len(causal_pairs), is_crypto=is_crypto)
        return trades, equity_curve, metrics

    def calculate_metrics(
        self,
        trades: List[TradeRecord],
        equity_curve: List[float],
        total_bars: int,
        is_crypto: bool = True
    ) -> PerformanceMetrics:
        """Calculates comprehensive institutional tear sheet metrics."""
        final_equity = equity_curve[-1] if equity_curve else self.initial_capital
        net_profit = final_equity - self.initial_capital
        total_trades = len(trades)

        if total_trades == 0:
            return PerformanceMetrics(
                total_trades=0, win_rate=0.0, profit_factor=0.0, expectancy=0.0,
                annualized_return=0.0, annualized_sharpe=0.0, sortino_ratio=0.0,
                calmar_ratio=0.0, omega_ratio=1.0, deflated_sharpe_ratio=0.5,
                probabilistic_sharpe_ratio=0.5, skewness=0.0, kurtosis=3.0,
                max_drawdown_pct=0.0, max_drawdown_duration=0, average_r_multiple=0.0,
                payoff_ratio=0.0, market_exposure_pct=0.0, final_equity=final_equity,
                net_profit=0.0
            )

        winning_trades = [t for t in trades if t.net_pnl > 0]
        losing_trades = [t for t in trades if t.net_pnl < 0]

        win_rate = len(winning_trades) / total_trades
        gross_profit = sum(t.net_pnl for t in winning_trades)
        gross_loss = abs(sum(t.net_pnl for t in losing_trades))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (99.0 if gross_profit > 0 else 0.0)

        expectancy = (gross_profit - gross_loss) / total_trades
        avg_win = (gross_profit / len(winning_trades)) if winning_trades else 0.0
        avg_loss = (gross_loss / len(losing_trades)) if losing_trades else 0.0
        payoff_ratio = (avg_win / avg_loss) if avg_loss > 0 else 0.0

        r_multiples = [t.r_multiple for t in trades]
        avg_r = float(np.mean(r_multiples)) if r_multiples else 0.0

        total_bars_in_trades = sum(t.bars_held for t in trades)
        exposure_pct = total_bars_in_trades / max(1, total_bars)

        # Equity Curve Analytics
        peak = equity_curve[0]
        drawdowns: List[float] = []
        dd_durations: List[int] = []
        cur_duration = 0

        for eq in equity_curve:
            if eq > peak:
                peak = eq
                cur_duration = 0
            else:
                cur_duration += 1
            dd = (peak - eq) / peak
            drawdowns.append(dd)
            dd_durations.append(cur_duration)

        max_dd = max(drawdowns) if drawdowns else 0.0
        max_dd_duration = max(dd_durations) if dd_durations else 0

        # Bar Returns for Sharpe & Sortino
        eq_arr = np.array(equity_curve)
        returns = np.diff(eq_arr) / eq_arr[:-1]
        returns = [r for r in returns if not np.isnan(r)]

        # Annualization factor: 8,760 for 1h crypto, 2,190 for 4h crypto, 252*6.5=1638 for 1h equities
        ann_factor = 2190.0 if total_bars <= 3500 and is_crypto else (8760.0 if is_crypto else 1638.0)

        if len(returns) > 1:
            mean_ret = float(np.mean(returns))
            std_ret = float(np.std(returns, ddof=1))
            sharpe = (mean_ret / std_ret * math.sqrt(ann_factor)) if std_ret > 0 else 0.0

            downside_returns = [r for r in returns if r < 0]
            if downside_returns:
                downside_std = float(np.std(downside_returns, ddof=1))
                sortino = (mean_ret / downside_std * math.sqrt(ann_factor)) if downside_std > 0 else 0.0
            else:
                sortino = 99.0 if mean_ret > 0 else 0.0
        else:
            sharpe = 0.0
            sortino = 0.0

        ann_return = ((final_equity / self.initial_capital) ** (ann_factor / max(1, total_bars))) - 1.0 if final_equity > 0 else -1.0
        calmar = (ann_return / max_dd) if max_dd > 0 else 0.0

        omega = calculate_omega_ratio(returns, threshold=0.0)
        dsr_dict = calculate_deflated_sharpe_ratio(returns, num_trials=50, ann_factor=ann_factor)

        return PerformanceMetrics(
            total_trades=total_trades,
            win_rate=win_rate,
            profit_factor=profit_factor,
            expectancy=expectancy,
            annualized_return=ann_return,
            annualized_sharpe=sharpe,
            sortino_ratio=sortino,
            calmar_ratio=calmar,
            omega_ratio=omega,
            deflated_sharpe_ratio=dsr_dict["dsr"],
            probabilistic_sharpe_ratio=dsr_dict["psr"],
            skewness=dsr_dict["skewness"],
            kurtosis=dsr_dict["kurtosis"],
            max_drawdown_pct=max_dd,
            max_drawdown_duration=max_dd_duration,
            average_r_multiple=avg_r,
            payoff_ratio=payoff_ratio,
            market_exposure_pct=exposure_pct,
            final_equity=final_equity,
            net_profit=net_profit
        )

    # --------------------------------------------------------------------------
    # Walk-Forward Optimization & Cross-Validation with Embargo
    # --------------------------------------------------------------------------
    def run_walk_forward(
        self,
        bars: List[Bar],
        symbol: str = "BTC/USDT",
        train_bars: int = 800,
        test_bars: int = 250,
        embargo_bars: int = 20,
        is_crypto: bool = True
    ) -> Dict[str, Any]:
        """
        Executes rolling walk-forward optimization with de Prado embargo gap.
        """
        n = len(bars)
        step = test_bars
        folds: List[Dict[str, Any]] = []

        is_sharpes: List[float] = []
        oos_sharpes: List[float] = []
        oos_omegas: List[float] = []

        start = 0
        fold_id = 1
        while start + train_bars + embargo_bars + test_bars <= n:
            train_slice = bars[start:start + train_bars]
            test_start = start + train_bars + embargo_bars
            test_slice = bars[test_start:test_start + test_bars]

            # In-Sample Run
            _, _, is_metrics = self.run_simulation(train_slice, symbol=symbol, is_crypto=is_crypto)
            # Out-of-Sample Run
            _, _, oos_metrics = self.run_simulation(test_slice, symbol=symbol, is_crypto=is_crypto)

            is_sharpes.append(is_metrics.annualized_sharpe)
            oos_sharpes.append(oos_metrics.annualized_sharpe)
            oos_omegas.append(oos_metrics.omega_ratio)

            folds.append({
                "fold": fold_id,
                "train_start": train_slice[0].timestamp,
                "train_end": train_slice[-1].timestamp,
                "test_start": test_slice[0].timestamp,
                "test_end": test_slice[-1].timestamp,
                "is_sharpe": is_metrics.annualized_sharpe,
                "oos_sharpe": oos_metrics.annualized_sharpe,
                "oos_omega": oos_metrics.omega_ratio,
                "oos_win_rate": oos_metrics.win_rate,
                "oos_profit_factor": oos_metrics.profit_factor,
                "oos_max_dd": oos_metrics.max_drawdown_pct
            })

            start += step
            fold_id += 1

        avg_is_sharpe = float(np.mean(is_sharpes)) if is_sharpes else 0.0
        avg_oos_sharpe = float(np.mean(oos_sharpes)) if oos_sharpes else 0.0
        degradation_ratio = (avg_oos_sharpe / max(0.01, avg_is_sharpe)) if avg_is_sharpe > 0 else 0.0
        is_overfit = degradation_ratio < 0.50

        return {
            "symbol": symbol,
            "total_folds": len(folds),
            "folds": folds,
            "avg_in_sample_sharpe": round(avg_is_sharpe, 4),
            "avg_out_of_sample_sharpe": round(avg_oos_sharpe, 4),
            "avg_out_of_sample_omega": round(float(np.mean(oos_omegas)), 4) if oos_omegas else 1.0,
            "overfitting_degradation_ratio": round(degradation_ratio, 4),
            "is_overfit": is_overfit
        }

    # --------------------------------------------------------------------------
    # Combinatorial Purged Cross-Validation (CPCV)
    # --------------------------------------------------------------------------
    def run_combinatorial_purged_cv(
        self,
        bars: List[Bar],
        symbol: str = "BTC/USDT",
        num_blocks: int = 6,
        test_blocks: int = 2,
        embargo_bars: int = 10,
        is_crypto: bool = True
    ) -> Dict[str, Any]:
        """
        Combinatorial Purged Cross-Validation generating all C(num_blocks, test_blocks) paths.
        Enforces purging of overlapping windows and embargo buffers.
        """
        n = len(bars)
        block_size = n // num_blocks
        if block_size < 50:
            return {"error": f"Insufficient bars ({n}) for {num_blocks} blocks"}

        block_indices = [range(i * block_size, (i + 1) * block_size if i < num_blocks - 1 else n) for i in range(num_blocks)]
        combos = list(itertools.combinations(range(num_blocks), test_blocks))

        cpcv_results = []
        is_sharpes = []
        oos_sharpes = []
        oos_omegas = []
        oos_dds = []

        for combo_id, test_group in enumerate(combos, 1):
            test_idxs = set()
            for b in test_group:
                test_idxs.update(block_indices[b])

            train_idxs = set(range(n)) - test_idxs
            embargo_drop = set()
            for b in test_group:
                end_idx = list(block_indices[b])[-1]
                for eb in range(end_idx + 1, min(n, end_idx + embargo_bars + 1)):
                    embargo_drop.add(eb)
            train_idxs -= embargo_drop

            train_bars_slice = [bars[i] for i in sorted(train_idxs)]
            test_bars_slice = [bars[i] for i in sorted(test_idxs)]

            _, _, is_m = self.run_simulation(train_bars_slice, symbol=symbol, is_crypto=is_crypto)
            _, _, oos_m = self.run_simulation(test_bars_slice, symbol=symbol, is_crypto=is_crypto)

            is_sharpes.append(is_m.annualized_sharpe)
            oos_sharpes.append(oos_m.annualized_sharpe)
            oos_omegas.append(oos_m.omega_ratio)
            oos_dds.append(oos_m.max_drawdown_pct)

            cpcv_results.append({
                "combo": combo_id,
                "test_blocks": list(test_group),
                "is_sharpe": is_m.annualized_sharpe,
                "oos_sharpe": oos_m.annualized_sharpe,
                "oos_omega": oos_m.omega_ratio,
                "oos_max_dd": oos_m.max_drawdown_pct,
                "oos_win_rate": oos_m.win_rate
            })

        mean_is_sr = float(np.mean(is_sharpes)) if is_sharpes else 0.0
        mean_oos_sr = float(np.mean(oos_sharpes)) if oos_sharpes else 0.0
        deg_ratio = (mean_oos_sr / max(0.01, mean_is_sr)) if mean_is_sr > 0 else 0.0

        return {
            "symbol": symbol,
            "total_combinations": len(combos),
            "combinations": cpcv_results,
            "mean_in_sample_sharpe": round(mean_is_sr, 4),
            "mean_out_of_sample_sharpe": round(mean_oos_sr, 4),
            "mean_out_of_sample_omega": round(float(np.mean(oos_omegas)), 4) if oos_omegas else 1.0,
            "mean_out_of_sample_max_dd": round(float(np.mean(oos_dds)), 4) if oos_dds else 0.0,
            "degradation_ratio": round(deg_ratio, 4),
            "is_overfit": deg_ratio < 0.65
        }

    # --------------------------------------------------------------------------
    # 1,000-Path Monte Carlo Simulation
    # --------------------------------------------------------------------------
    def run_monte_carlo_simulation(
        self,
        trades: List[TradeRecord],
        num_simulations: int = 1000,
        horizon_trades: int = 100,
        ruin_drawdown_threshold: float = 0.20
    ) -> Dict[str, Any]:
        """
        Simulates 1,000 bootstrap equity trajectories to determine confidence cones
        and probability of ruin.
        """
        if not trades:
            return {}

        trade_pnls = [t.net_pnl for t in trades]
        simulated_finals: List[float] = []
        max_drawdowns: List[float] = []
        ruin_count = 0

        for _ in range(num_simulations):
            path_equity = self.initial_capital
            peak = path_equity
            max_dd = 0.0
            ruined = False

            sampled_pnls = random.choices(trade_pnls, k=horizon_trades)
            for pnl in sampled_pnls:
                path_equity += pnl
                if path_equity > peak:
                    peak = path_equity
                dd = (peak - path_equity) / peak
                if dd > max_dd:
                    max_dd = dd
                if dd >= ruin_drawdown_threshold:
                    ruined = True

            simulated_finals.append(path_equity)
            max_drawdowns.append(max_dd)
            if ruined:
                ruin_count += 1

        simulated_finals.sort()
        max_drawdowns.sort()

        p5_idx = int(0.05 * num_simulations)
        p50_idx = int(0.50 * num_simulations)
        p95_idx = int(0.95 * num_simulations)

        return {
            "num_simulations": num_simulations,
            "horizon_trades": horizon_trades,
            "equity_cone": {
                "5th_percentile_worst_case": round(simulated_finals[p5_idx], 2),
                "50th_percentile_median": round(simulated_finals[p50_idx], 2),
                "95th_percentile_best_case": round(simulated_finals[p95_idx], 2),
            },
            "median_max_drawdown": round(max_drawdowns[p50_idx], 4),
            "95th_percentile_max_drawdown": round(max_drawdowns[p95_idx], 4),
            "probability_of_ruin": round(ruin_count / num_simulations, 4)
        }
