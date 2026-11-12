# Institutional Multi-Asset Algorithmic Trading System: Out-of-Sample Walk-Forward Research Report
### *Rigorous Empirical Validation on Real Market Data with Transaction Costs, Purged Cross-Validation & Monte Carlo Simulations*

---

## Executive Summary
This report documents the empirical out-of-sample performance, statistical stability, and risk characteristics of the **Dex Algo Institutional Quantitative Trading System**.
The system is evaluated against real historical market data spanning **Bitcoin (BTC/USDT)**, **Ethereum (ETH/USDT)**, **Solana (SOL/USDT)**, and **S&P 500 ETF (SPY)** under strict execution assumptions:
- **Strict Lag-1 Execution**: Every signal is computed at bar $t-1$ on finalized historical bars, executed at bar $t$ Open. Zero future lookahead bias.
- **Realistic Friction**: 6 bps taker fees for crypto (0.06%), 1.5 bps for equities, plus dynamic square-root impact slippage: $\text{Spread}/2 + \gamma \cdot \text{ATR} \cdot \sqrt{\frac{\text{Trade Notional}}{\text{Volume Notional}}}$.
- **Walk-Forward Cross-Validation**: Rolling window optimization with de Prado 10-bar embargo gaps between train and test slices to prevent autocorrelation leakage.
- **1,000-Path Monte Carlo Analysis**: Empirical bootstrapping of trade returns over 100-trade horizons to estimate the 5th, 50th, and 95th percentile equity cones and ruin probabilities.

---

## Performance Tear Sheet Summary Table

| Asset Class | Symbol | Trades | Win Rate | Profit Factor | Exp. ($) | Ann. Return | Ann. Sharpe | Sortino | Max DD | Avg R | Ruin Prob (<20% DD) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Crypto Major | **BTC/USDT** | 11 | 9.1% | 0.05 | $-64.56 | -13.31% | **-7.65** | -3.66 | 0.75% | -1.45 | 100.0% |
| Crypto Major | **ETH/USDT** | 5 | 0.0% | 0.00 | $-137.78 | -12.98% | **-7.10** | -3.02 | 0.74% | -0.81 | 100.0% |
| Liquid Alt | **SOL/USDT** | 9 | 33.3% | 0.20 | $-24.89 | -4.22% | **-3.87** | -2.03 | 0.35% | -0.32 | 100.0% |
| US Equity | **SPY** | 26 | 26.9% | 0.76 | $-24.09 | -2.16% | **-0.31** | -0.35 | 2.76% | -0.27 | 61.5% |

---

## Detailed Walk-Forward & Overfitting Analysis

### 1. BTC/USDT Analysis
- **Total Bars Analyzed**: 500 hourly bars
- **Final Net Profit**: $-706.35 on $100,000 initial equity
- **Total Realized Trades**: 11
- **Annualized Sharpe Ratio**: -7.65
- **Sortino Ratio**: -3.66
- **Maximum Drawdown**: 0.75% (Duration: 448 bars)
- **Market Exposure Time**: 21.51%

#### Walk-Forward Folds (Rolling Train + Embargo + Test):
| Fold | In-Sample Sharpe | Out-of-Sample Sharpe | OOS Win Rate | OOS Profit Factor | OOS Max DD |
|---|---|---|---|---|---|
| #1 | -10.74 | -7.74 | 0.0% | 0.00 | 0.14% |
| #2 | -6.70 | -10.98 | 0.0% | 0.00 | 0.07% |
| #3 | -6.82 | 7.64 | 100.0% | 99.00 | 0.24% |

- **In-Sample vs Out-of-Sample Degradation Ratio**: `0.00`
- **Overfitting Detector Status**: **CONDITIONAL (Regime-sensitive)**

#### Monte Carlo 1,000-Path Bootstrapped Equity Cones:
- **5th Percentile (Stress Downside)**: $50,779.52
- **50th Percentile (Expected Median)**: $57,467.86
- **95th Percentile (Upside Tail)**: $65,064.39
- **95th Percentile Maximum Drawdown**: 49.47%

### 1. ETH/USDT Analysis
- **Total Bars Analyzed**: 500 hourly bars
- **Final Net Profit**: $-688.90 on $100,000 initial equity
- **Total Realized Trades**: 5
- **Annualized Sharpe Ratio**: -7.10
- **Sortino Ratio**: -3.02
- **Maximum Drawdown**: 0.74% (Duration: 337 bars)
- **Market Exposure Time**: 11.18%

#### Walk-Forward Folds (Rolling Train + Embargo + Test):
| Fold | In-Sample Sharpe | Out-of-Sample Sharpe | OOS Win Rate | OOS Profit Factor | OOS Max DD |
|---|---|---|---|---|---|
| #1 | -9.04 | 0.00 | 0.0% | 0.00 | 0.00% |
| #2 | -12.38 | -17.87 | 0.0% | 0.00 | 0.43% |
| #3 | -7.86 | -16.47 | 0.0% | 0.00 | 1.20% |

- **In-Sample vs Out-of-Sample Degradation Ratio**: `0.00`
- **Overfitting Detector Status**: **CONDITIONAL (Regime-sensitive)**

#### Monte Carlo 1,000-Path Bootstrapped Equity Cones:
- **5th Percentile (Stress Downside)**: $40,282.11
- **50th Percentile (Expected Median)**: $43,747.45
- **95th Percentile (Upside Tail)**: $47,562.58
- **95th Percentile Maximum Drawdown**: 59.72%

### 1. SOL/USDT Analysis
- **Total Bars Analyzed**: 500 hourly bars
- **Final Net Profit**: $-224.03 on $100,000 initial equity
- **Total Realized Trades**: 9
- **Annualized Sharpe Ratio**: -3.87
- **Sortino Ratio**: -2.03
- **Maximum Drawdown**: 0.35% (Duration: 461 bars)
- **Market Exposure Time**: 17.20%

#### Walk-Forward Folds (Rolling Train + Embargo + Test):
| Fold | In-Sample Sharpe | Out-of-Sample Sharpe | OOS Win Rate | OOS Profit Factor | OOS Max DD |
|---|---|---|---|---|---|
| #1 | -6.68 | 0.00 | 0.0% | 0.00 | 0.00% |
| #2 | -13.35 | 0.00 | 0.0% | 0.00 | 0.00% |
| #3 | 0.65 | -7.34 | 0.0% | 0.00 | 0.14% |

- **In-Sample vs Out-of-Sample Degradation Ratio**: `0.00`
- **Overfitting Detector Status**: **CONDITIONAL (Regime-sensitive)**

#### Monte Carlo 1,000-Path Bootstrapped Equity Cones:
- **5th Percentile (Stress Downside)**: $44,143.08
- **50th Percentile (Expected Median)**: $54,151.90
- **95th Percentile (Upside Tail)**: $65,014.64
- **95th Percentile Maximum Drawdown**: 56.27%

### 1. SPY Analysis
- **Total Bars Analyzed**: 500 hourly bars
- **Final Net Profit**: $-613.20 on $100,000 initial equity
- **Total Realized Trades**: 26
- **Annualized Sharpe Ratio**: -0.31
- **Sortino Ratio**: -0.35
- **Maximum Drawdown**: 2.76% (Duration: 411 bars)
- **Market Exposure Time**: 69.68%

#### Walk-Forward Folds (Rolling Train + Embargo + Test):
| Fold | In-Sample Sharpe | Out-of-Sample Sharpe | OOS Win Rate | OOS Profit Factor | OOS Max DD |
|---|---|---|---|---|---|
| #1 | -0.16 | -8.08 | 0.0% | 0.00 | 1.60% |
| #2 | -2.72 | 0.00 | 0.0% | 0.00 | 0.00% |
| #3 | -2.47 | 0.00 | 0.0% | 0.00 | 0.00% |

- **In-Sample vs Out-of-Sample Degradation Ratio**: `0.00`
- **Overfitting Detector Status**: **CONDITIONAL (Regime-sensitive)**

#### Monte Carlo 1,000-Path Bootstrapped Equity Cones:
- **5th Percentile (Stress Downside)**: $65,697.82
- **50th Percentile (Expected Median)**: $89,235.82
- **95th Percentile (Upside Tail)**: $125,385.15
- **95th Percentile Maximum Drawdown**: 38.51%


---

## Institutional Architecture Highlights

1. **Data Layer (`backend/data_layer.py`)**:
   Seamless multi-asset integration with Binance Public REST, Coinbase, and Alpaca. Real trade aggressor volume delta ($V_{\text{buy}} - V_{\text{sell}}$) extracted directly from exchange microstructure.
2. **Feature Store (`backend/features.py`)**:
   Computes Parkinson High-Low range volatility (5x efficiency), Yang-Zhang drift-independent volatility, ADX/DI, rolling BBW percentile, VWAP $Z$-scores, and strictly enforces lag-1 shifting.
3. **Regime Engine (`backend/regime.py`)**:
   Classifies market states into 4 canonical regimes with 2-bar state hysteresis to eliminate whipsawing.
4. **Multi-Alpha Ensemble (`backend/alphas.py`)**:
   Three orthogonal strategies (Adaptive Trend, Squeeze Mean-Reversion, Order Flow Breakout) dynamically weighted by regime.
5. **Institutional Risk Engine (`backend/risk.py`)**:
   Target portfolio annualized volatility ($1/\sigma$), online Bayesian Half-Kelly sizing ($	ext{Beta}(\alpha, \beta)$ prior), monotonic Chandelier ratchets, and 2.5% daily drawdown circuit breakers.
6. **Production Backtester (`backend/backtester_v2.py`)**:
   Realistic transaction costs (fees, spread, market impact), walk-forward cross-validation with embargo windows, and Monte Carlo equity paths.