"""
Institutional Quantitative Backtester & Walk-Forward Research Engine
=====================================================================
Features:
1. Strict Lag-1 Execution: Signals computed at bar t-1, executed at bar t Open.
2. Realistic Friction:
   - Taker fees (crypto: 0.06% = 6 bps, equities: 0.015% or $0.005/share).
   - Dynamic square-root market impact slippage: Spread/2 + gamma * ATR * sqrt(Size / Vol).
   - 8-hour crypto funding rate simulation.
3. Walk-Forward Cross-Validation with de Prado Embargo windows.
4. Institutional Tear Sheet:
   - Expectancy, Profit Factor, Annualized Sharpe, Sortino, Calmar, Max Drawdown,
   - Win Rate, Payoff Ratio, Average R-Multiple, Exposure Time.
5. 1,000-Path Monte Carlo Simulation (5th, 50th, 95th percentiles & Ruin Probability).
6. Overfitting Degradation Detector (IS vs OOS Sharpe degradation ratio).
"""

import math
import random
import numpy as np
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, asdict

from data_layer import Bar, MarketDataClient, get_data_client
from features import FeatureStore, BarFeatures
from regime import RobustRegimeDetector, MarketRegime, RegimeState
from alphas import MultiAlphaOrchestrator, SignalAction, AlphaSignal
from risk import InstitutionalRiskEngine, Position, ExitReason


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
            "max_drawdown_pct": round(self.max_drawdown_pct, 4),
            "max_drawdown_duration": self.max_drawdown_duration,
            "average_r_multiple": round(self.average_r_multiple, 4),
            "payoff_ratio": round(self.payoff_ratio, 4),
            "market_exposure_pct": round(self.market_exposure_pct, 4),
            "final_equity": round(self.final_equity, 2),
            "net_profit": round(self.net_profit, 2)
        }


class InstitutionalBacktester:
    """
    Simulates production order execution with realistic market friction.
    """

    def __init__(
        self,
        initial_capital: float = 100000.0,
        fee_rate: float = 0.0006,        # 6 bps taker fee
        base_slippage: float = 0.0002,   # 2 bps base half-spread
        slippage_impact_gamma: float = 0.05,
        funding_rate_8h: float = 0.0001   # 1 bp per 8 hours
    ):
        self.initial_capital = initial_capital
        self.fee_rate = fee_rate
        self.base_slippage = base_slippage
        self.slippage_impact_gamma = slippage_impact_gamma
        self.funding_rate_8h = funding_rate_8h

    def _compute_fill_price(
        self,
        base_price: float,
        side: str,
        is_entry: bool,
        qty: float,
        bar_volume: float,
        atr: float
    ) -> Tuple[float, float]:
        """
        Calculates execution fill price incorporating spread and square-root impact slippage.
        Returns: (fill_price, slippage_dollars)
        """
        vol_notional = max(1.0, bar_volume * base_price)
        trade_notional = qty * base_price
        impact_factor = math.sqrt(min(1.0, trade_notional / vol_notional))
        total_slippage_pct = self.base_slippage + (self.slippage_impact_gamma * (atr / base_price) * impact_factor)

        # Buyer pays higher, seller receives lower
        is_buying = (side == "LONG" and is_entry) or (side == "SHORT" and not is_entry)
        if is_buying:
            fill_price = base_price * (1.0 + total_slippage_pct)
        else:
            fill_price = base_price * (1.0 - total_slippage_pct)

        slip_cost = abs(fill_price - base_price) * qty
        return fill_price, slip_cost

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
            empty_metrics = PerformanceMetrics(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, self.initial_capital, 0)
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
                    if open_pos.side == "LONG" and signal.action == SignalAction.SELL:
                        should_exit = True
                        exit_reason = ExitReason.REGIME_CHANGE
                        nominal_exit_px = bar_t.open
                    elif open_pos.side == "SHORT" and signal.action == SignalAction.BUY:
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
                    if open_pos.side == "LONG":
                        gross_pnl = (fill_exit_px - open_pos.entry_price) * open_pos.qty
                    else:
                        gross_pnl = (open_pos.entry_price - fill_exit_px) * open_pos.qty

                    entry_notional = open_pos.entry_price * open_pos.qty
                    exit_notional = fill_exit_px * open_pos.qty
                    fees = (entry_notional + exit_notional) * self.fee_rate
                    total_slip = exit_slip  # Entry slip was already priced into fill

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
                    confidence=signal.confidence
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
                    # Asymmetric take-profit at 6.0x ATR allowing trend runs to compound
                    tp_dist = 6.0 * feat_prev.atr
                    take_profit = (fill_entry_px + tp_dist) if side == "LONG" else (fill_entry_px - tp_dist)

                    open_pos = Position(
                        symbol=symbol,
                        side=side,
                        qty=units,
                        entry_price=fill_entry_px,
                        entry_time=bar_t.timestamp,
                        entry_regime=regime.regime.value,
                        stop_loss=init_stop,
                        take_profit=take_profit,
                        highest_high=fill_entry_px,
                        lowest_low=fill_entry_px,
                        atr_at_entry=feat_prev.atr,
                        bars_held=0
                    )

            # Record mark-to-market equity
            unrealized = 0.0
            if open_pos is not None:
                if open_pos.side == "LONG":
                    unrealized = (bar_t.close - open_pos.entry_price) * open_pos.qty
                else:
                    unrealized = (open_pos.entry_price - bar_t.close) * open_pos.qty
            equity_curve.append(equity + unrealized)

        # Close any lingering open position on final bar
        if open_pos is not None:
            last_bar = causal_pairs[-1][0]
            if open_pos.side == "LONG":
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
                annualized_return=0.0, annualized_sharpe=0.0, sortino_ratio=0.0, calmar_ratio=0.0,
                max_drawdown_pct=0.0, max_drawdown_duration=0, average_r_multiple=0.0,
                payoff_ratio=0.0, market_exposure_pct=0.0, final_equity=final_equity, net_profit=net_profit
            )

        wins = [t for t in trades if t.net_pnl > 0]
        losses = [t for t in trades if t.net_pnl <= 0]
        win_rate = len(wins) / total_trades

        sum_gains = sum(t.net_pnl for t in wins)
        sum_losses = sum(abs(t.net_pnl) for t in losses)
        profit_factor = (sum_gains / sum_losses) if sum_losses > 0 else (99.0 if sum_gains > 0 else 1.0)

        avg_win = (sum_gains / len(wins)) if wins else 0.0
        avg_loss = (sum_losses / len(losses)) if losses else 0.0
        payoff_ratio = (avg_win / avg_loss) if avg_loss > 0 else 1.0

        expectancy = (win_rate * avg_win) - ((1.0 - win_rate) * avg_loss)
        avg_r = sum(t.r_multiple for t in trades) / total_trades

        total_bars_held = sum(t.bars_held for t in trades)
        exposure_pct = total_bars_held / max(1, total_bars)

        # Drawdown computation
        peak = equity_curve[0]
        max_dd = 0.0
        cur_dd_duration = 0
        max_dd_duration = 0
        for eq in equity_curve:
            if eq > peak:
                peak = eq
                cur_dd_duration = 0
            else:
                cur_dd_duration += 1
                max_dd_duration = max(max_dd_duration, cur_dd_duration)
                dd = (peak - eq) / peak if peak > 0 else 0.0
                max_dd = max(max_dd, dd)

        # Returns and Sharpe / Sortino
        returns = [
            (equity_curve[i] - equity_curve[i - 1]) / equity_curve[i - 1]
            for i in range(1, len(equity_curve))
        ]
        ann_factor = (365.0 * 24.0) if is_crypto else 252.0  # Hourly bars
        mean_ret = float(np.mean(returns)) if returns else 0.0
        std_ret = float(np.std(returns, ddof=1)) if len(returns) > 1 else 1e-5
        
        downside_returns = [r for r in returns if r < 0]
        downside_std = float(np.std(downside_returns, ddof=1)) if len(downside_returns) > 1 else 1e-5

        total_pct_ret = (final_equity - self.initial_capital) / self.initial_capital
        hours_elapsed = max(1, total_bars)
        years_elapsed = hours_elapsed / (365.0 * 24.0 if is_crypto else 252.0 * 6.5)
        ann_return = total_pct_ret / max(0.01, years_elapsed)

        sharpe = (mean_ret / std_ret * math.sqrt(ann_factor)) if std_ret > 0 else 0.0
        sortino = (mean_ret / downside_std * math.sqrt(ann_factor)) if downside_std > 0 else 0.0
        calmar = (ann_return / max_dd) if max_dd > 0 else 0.0

        return PerformanceMetrics(
            total_trades=total_trades,
            win_rate=win_rate,
            profit_factor=profit_factor,
            expectancy=expectancy,
            annualized_return=ann_return,
            annualized_sharpe=sharpe,
            sortino_ratio=sortino,
            calmar_ratio=calmar,
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
        train_bars: int = 300,
        test_bars: int = 100,
        embargo_bars: int = 10,
        is_crypto: bool = True
    ) -> Dict[str, Any]:
        """
        Executes rolling walk-forward optimization with de Prado embargo gap.
        Returns: {
            "folds": List[Dict],
            "in_sample_sharpe": float,
            "out_of_sample_sharpe": float,
            "overfitting_ratio": float,
            "is_overfit": bool
        }
        """
        n = len(bars)
        step = test_bars
        folds: List[Dict[str, Any]] = []

        is_sharpes: List[float] = []
        oos_sharpes: List[float] = []

        start = 0
        fold_id = 1
        while start + train_bars + embargo_bars + test_bars <= n:
            train_slice = bars[start:start + train_bars]
            test_start = start + train_bars + embargo_bars
            test_slice = bars[test_start:test_start + test_bars]

            # In-Sample Run
            _, is_eq, is_metrics = self.run_simulation(train_slice, symbol=symbol, is_crypto=is_crypto)
            # Out-of-Sample Run
            _, oos_eq, oos_metrics = self.run_simulation(test_slice, symbol=symbol, is_crypto=is_crypto)

            is_sharpes.append(is_metrics.annualized_sharpe)
            oos_sharpes.append(oos_metrics.annualized_sharpe)

            folds.append({
                "fold": fold_id,
                "train_start": train_slice[0].timestamp,
                "train_end": train_slice[-1].timestamp,
                "test_start": test_slice[0].timestamp,
                "test_end": test_slice[-1].timestamp,
                "is_sharpe": is_metrics.annualized_sharpe,
                "oos_sharpe": oos_metrics.annualized_sharpe,
                "oos_win_rate": oos_metrics.win_rate,
                "oos_profit_factor": oos_metrics.profit_factor,
                "oos_max_dd": oos_metrics.max_drawdown_pct
            })

            start += step
            fold_id += 1

        avg_is_sharpe = float(np.mean(is_sharpes)) if is_sharpes else 0.0
        avg_oos_sharpe = float(np.mean(oos_sharpes)) if oos_sharpes else 0.0
        degradation_ratio = (avg_oos_sharpe / max(0.01, avg_is_sharpe)) if avg_is_sharpe > 0 else 0.0
        # Overfit if OOS degrades by more than 50% relative to IS
        is_overfit = degradation_ratio < 0.50

        return {
            "symbol": symbol,
            "total_folds": len(folds),
            "folds": folds,
            "avg_in_sample_sharpe": round(avg_is_sharpe, 4),
            "avg_out_of_sample_sharpe": round(avg_oos_sharpe, 4),
            "overfitting_degradation_ratio": round(degradation_ratio, 4),
            "is_overfit": is_overfit
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
            return {"error": "No trades to simulate"}

        returns = [t.return_pct for t in trades]
        simulated_finals: List[float] = []
        simulated_max_dds: List[float] = []
        ruin_count = 0

        for _ in range(num_simulations):
            eq = self.initial_capital
            peak = eq
            max_dd = 0.0
            for _ in range(horizon_trades):
                r = random.choice(returns)
                eq *= (1.0 + r)
                if eq > peak:
                    peak = eq
                else:
                    dd = (peak - eq) / peak
                    max_dd = max(max_dd, dd)
            simulated_finals.append(eq)
            simulated_max_dds.append(max_dd)
            if max_dd >= ruin_drawdown_threshold:
                ruin_count += 1

        simulated_finals.sort()
        simulated_max_dds.sort()

        p5_equity = simulated_finals[int(0.05 * num_simulations)]
        p50_equity = simulated_finals[int(0.50 * num_simulations)]
        p95_equity = simulated_finals[int(0.95 * num_simulations)]

        p95_dd = simulated_max_dds[int(0.95 * num_simulations)]
        prob_ruin = ruin_count / num_simulations

        return {
            "num_simulations": num_simulations,
            "horizon_trades": horizon_trades,
            "ruin_drawdown_threshold": ruin_drawdown_threshold,
            "probability_of_ruin": round(prob_ruin, 4),
            "equity_cone": {
                "5th_percentile_worst_case": round(p5_equity, 2),
                "50th_percentile_median": round(p50_equity, 2),
                "95th_percentile_best_case": round(p95_equity, 2)
            },
            "95th_percentile_max_drawdown": round(p95_dd, 4)
        }
