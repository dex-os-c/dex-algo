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
| Crypto Major | **BTC/USDT** | 44 | 38.6% | 0.43 | $-19.79 | -2.57% | **-1.67** | -0.64 | 1.49% | -0.66 | 100.0% |
| Crypto Major | **ETH/USDT** | 21 | 61.9% | 0.20 | $-21.52 | -1.33% | **-2.61** | -0.87 | 0.59% | -0.13 | 100.0% |
| Liquid Alt | **SOL/USDT** | 23 | 47.8% | 0.20 | $-25.02 | -1.70% | **-3.76** | -1.20 | 0.63% | -0.23 | 100.0% |
| US Equity | **SPY** | 5 | 80.0% | 105.12 | $6372.11 | 35.62% | **0.41** | 3.86 | 0.95% | 0.63 | 0.0% |

---

## Detailed Walk-Forward & Overfitting Analysis

### 1. BTC/USDT Analysis
- **Total Bars Analyzed**: 3000 hourly bars
- **Final Net Profit**: $-870.85 on $100,000 initial equity
- **Total Realized Trades**: 44
- **Annualized Sharpe Ratio**: -1.67
- **Sortino Ratio**: -0.64
- **Maximum Drawdown**: 1.49% (Duration: 2749 bars)
- **Market Exposure Time**: 8.03%

#### Walk-Forward Folds (Rolling Train + Embargo + Test):
| Fold | In-Sample Sharpe | Out-of-Sample Sharpe | OOS Win Rate | OOS Profit Factor | OOS Max DD |
|---|---|---|---|---|---|
| #1 | -1.82 | 0.00 | 0.0% | 0.00 | 0.00% |
| #2 | -3.76 | 0.14 | 66.7% | 1.02 | 0.21% |
| #3 | -0.25 | -9.54 | 50.0% | 0.01 | 0.40% |
| #4 | -3.07 | -6.70 | 0.0% | 0.00 | 0.16% |
| #5 | -2.20 | -4.30 | 33.3% | 0.26 | 0.39% |
| #6 | -4.62 | -8.00 | 33.3% | 0.25 | 0.19% |
| #7 | -6.07 | -7.36 | 0.0% | 0.00 | 0.05% |
| #8 | -1.49 | -9.05 | 0.0% | 0.00 | 0.23% |

- **In-Sample vs Out-of-Sample Degradation Ratio**: `0.00`
- **Overfitting Detector Status**: **CONDITIONAL (Regime-sensitive)**

#### Monte Carlo 1,000-Path Bootstrapped Equity Cones:
- **5th Percentile (Stress Downside)**: $33,062.12
- **50th Percentile (Expected Median)**: $45,686.26
- **95th Percentile (Upside Tail)**: $63,288.58
- **95th Percentile Maximum Drawdown**: 67.61%

### 1. ETH/USDT Analysis
- **Total Bars Analyzed**: 3000 hourly bars
- **Final Net Profit**: $-451.80 on $100,000 initial equity
- **Total Realized Trades**: 21
- **Annualized Sharpe Ratio**: -2.61
- **Sortino Ratio**: -0.87
- **Maximum Drawdown**: 0.59% (Duration: 2898 bars)
- **Market Exposure Time**: 5.06%

#### Walk-Forward Folds (Rolling Train + Embargo + Test):
| Fold | In-Sample Sharpe | Out-of-Sample Sharpe | OOS Win Rate | OOS Profit Factor | OOS Max DD |
|---|---|---|---|---|---|
| #1 | -3.54 | 0.00 | 0.0% | 0.00 | 0.00% |
| #2 | -3.00 | 0.00 | 0.0% | 0.00 | 0.00% |
| #3 | -4.88 | -2.66 | 0.0% | 0.00 | 0.13% |
| #4 | -3.36 | 0.00 | 0.0% | 0.00 | 0.00% |
| #5 | 0.00 | -10.60 | 0.0% | 0.00 | 0.20% |
| #6 | -5.60 | -6.43 | 0.0% | 0.00 | 0.15% |
| #7 | -6.38 | 0.68 | 100.0% | 99.00 | 0.04% |
| #8 | -6.15 | -8.70 | 0.0% | 0.00 | 0.31% |

- **In-Sample vs Out-of-Sample Degradation Ratio**: `0.00`
- **Overfitting Detector Status**: **CONDITIONAL (Regime-sensitive)**

#### Monte Carlo 1,000-Path Bootstrapped Equity Cones:
- **5th Percentile (Stress Downside)**: $18,976.09
- **50th Percentile (Expected Median)**: $30,532.27
- **95th Percentile (Upside Tail)**: $50,965.04
- **95th Percentile Maximum Drawdown**: 81.45%

### 1. SOL/USDT Analysis
- **Total Bars Analyzed**: 3000 hourly bars
- **Final Net Profit**: $-575.56 on $100,000 initial equity
- **Total Realized Trades**: 23
- **Annualized Sharpe Ratio**: -3.76
- **Sortino Ratio**: -1.20
- **Maximum Drawdown**: 0.63% (Duration: 2966 bars)
- **Market Exposure Time**: 5.87%

#### Walk-Forward Folds (Rolling Train + Embargo + Test):
| Fold | In-Sample Sharpe | Out-of-Sample Sharpe | OOS Win Rate | OOS Profit Factor | OOS Max DD |
|---|---|---|---|---|---|
| #1 | -4.40 | 0.00 | 0.0% | 0.00 | 0.00% |
| #2 | -0.57 | -10.89 | 0.0% | 0.00 | 0.33% |
| #3 | -2.25 | -0.18 | 0.0% | 0.00 | 0.12% |
| #4 | -5.20 | -11.53 | 0.0% | 0.00 | 0.34% |
| #5 | -7.56 | -4.16 | 75.0% | 0.03 | 0.40% |
| #6 | -4.30 | -5.20 | 50.0% | 0.05 | 0.30% |
| #7 | -5.15 | 0.00 | 0.0% | 0.00 | 0.00% |
| #8 | -2.85 | -0.56 | 50.0% | 0.89 | 0.18% |

- **In-Sample vs Out-of-Sample Degradation Ratio**: `0.00`
- **Overfitting Detector Status**: **CONDITIONAL (Regime-sensitive)**

#### Monte Carlo 1,000-Path Bootstrapped Equity Cones:
- **5th Percentile (Stress Downside)**: $8,429.68
- **50th Percentile (Expected Median)**: $14,644.76
- **95th Percentile (Upside Tail)**: $25,843.41
- **95th Percentile Maximum Drawdown**: 91.76%

### 1. SPY Analysis
- **Total Bars Analyzed**: 1500 hourly bars
- **Final Net Profit**: $31860.53 on $100,000 initial equity
- **Total Realized Trades**: 5
- **Annualized Sharpe Ratio**: 0.41
- **Sortino Ratio**: 3.86
- **Maximum Drawdown**: 0.95% (Duration: 734 bars)
- **Market Exposure Time**: 4.03%

#### Walk-Forward Folds (Rolling Train + Embargo + Test):
| Fold | In-Sample Sharpe | Out-of-Sample Sharpe | OOS Win Rate | OOS Profit Factor | OOS Max DD |
|---|---|---|---|---|---|
| #1 | -0.14 | 0.00 | 0.0% | 0.00 | 0.00% |
| #2 | -0.14 | 0.00 | 0.0% | 0.00 | 0.00% |

- **In-Sample vs Out-of-Sample Degradation Ratio**: `0.00`
- **Overfitting Detector Status**: **CONDITIONAL (Regime-sensitive)**

#### Monte Carlo 1,000-Path Bootstrapped Equity Cones:
- **5th Percentile (Stress Downside)**: $225,880,821,567,226,944.00
- **50th Percentile (Expected Median)**: $34,568,393,368,305,045,340,160.00
- **95th Percentile (Upside Tail)**: $6,419,384,928,691,071,195,772,092,416.00
- **95th Percentile Maximum Drawdown**: 7.43%


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