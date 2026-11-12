# Production Multi-Asset Algorithmic Trading System: Out-of-Sample Walk-Forward Research Report
### *Rigorous Empirical Validation on Real Market Data with Realistic Friction, Purged Cross-Validation & Monte Carlo Simulations*

---

## Executive Summary
This report documents the empirical out-of-sample performance, statistical stability, and risk characteristics of the **Dex Algo Production Quantitative Trading System**.
The system is evaluated against real historical market data spanning **Bitcoin (BTC/USDT)**, **Ethereum (ETH/USDT)**, **Solana (SOL/USDT)**, and major US equities (**SPY**, **QQQ**, **AAPL**, **MSFT**, **NVDA**) under strict execution assumptions:
- **Strict Lag-1 Causal Execution**: Every signal is computed at bar $t-1$ on finalized historical bars, executed at bar $t$ Open. Zero future lookahead bias.
- **Realistic Friction & Latency**: 6 bps taker fees for crypto (0.06%), 1.5 bps for equities, dynamic square-root impact slippage, and 75ms latency drift penalty.
- **Walk-Forward Cross-Validation**: Rolling window optimization with de Prado 15-bar purged embargo gaps between train and test slices to eliminate autocorrelation leakage.
- **Advanced Statistical Inference**: Evaluates Deflated Sharpe Ratio (DSR), Probabilistic Sharpe Ratio (PSR), and non-parametric Omega Ratio $\Omega(L)$ across non-normal return distributions.
- **1,000-Path Monte Carlo Analysis**: Empirical bootstrapping of trade returns over 100-trade horizons to estimate the 5th, 50th, and 95th percentile equity cones and ruin probabilities.

---

## Performance Tear Sheet Summary Table

| Asset Class | Symbol | Trades | Win Rate | Profit Factor | Payoff | Omega | DSR | Ann. Return | Ann. Sharpe | Sortino | Max DD | Exposure | Ruin Prob (<20% DD) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Crypto Major | **BTC/USDT** | 131 | 53.4% | 0.70 | 0.61x | 0.87 | 0.00 | -0.44% | **-0.82** | -0.54 | 1.08% | 24.0% | 0.0% |
| Crypto Major | **ETH/USDT** | 47 | 59.6% | 1.14 | 0.78x | 1.07 | 0.00 | 0.12% | **0.16** | 0.06 | 1.06% | 6.8% | 0.0% |
| Liquid Alt | **SOL/USDT** | 27 | 55.6% | 1.18 | 0.94x | 1.10 | 0.00 | 0.09% | **0.16** | 0.08 | 0.59% | 4.9% | 0.0% |
| US Equity | **SPY** | 26 | 73.1% | 94.22 | 34.71x | 9.08 | 0.17 | 42.24% | **1.07** | 35.83 | 0.33% | 19.9% | 0.0% |
| US Equity | **QQQ** | 35 | 54.3% | 0.29 | 0.25x | 0.76 | 0.00 | -1.89% | **-2.17** | -1.45 | 2.10% | 27.3% | 0.0% |
| US Equity | **AAPL** | 36 | 75.0% | 110.10 | 36.70x | 24.23 | 0.16 | 315.70% | **1.30** | 172.63 | 0.78% | 33.1% | 0.0% |
| US Equity | **MSFT** | 31 | 61.3% | 0.25 | 0.16x | 0.70 | 0.00 | -2.76% | **-2.84** | -2.04 | 1.93% | 25.9% | 0.0% |
| US Equity | **NVDA** | 42 | 69.0% | 0.54 | 0.24x | 0.87 | 0.00 | -1.49% | **-1.31** | -1.06 | 1.34% | 34.4% | 0.0% |

---

## Detailed Walk-Forward & Overfitting Analysis

### 1. BTC/USDT Analysis
- **Total Bars Analyzed**: 3000 bars
- **Final Net Profit**: $-600.74 on $100,000 initial equity
- **Total Realized Trades**: 131
- **Annualized Sharpe Ratio**: -0.82
- **Deflated Sharpe Ratio (DSR)**: 0.00
- **Omega Ratio**: 0.87
- **Sortino Ratio**: -0.54
- **Maximum Drawdown**: 1.08% (Duration: 2916 bars)
- **Market Exposure Time**: 24.01%

#### Walk-Forward Folds (Rolling Train + Purged Embargo + Test):
| Fold | In-Sample Sharpe | Out-of-Sample Sharpe | OOS Omega | OOS Win Rate | OOS Profit Factor | OOS Max DD |
|---|---|---|---|---|---|---|
| #1 | -0.70 | 0.46 | 1.07 | 87.5% | 1.23 | 0.32% |
| #2 | -0.09 | -2.66 | 0.59 | 66.7% | 0.05 | 0.14% |
| #3 | -2.03 | -1.66 | 0.71 | 66.7% | 0.46 | 0.22% |
| #4 | -0.95 | 0.13 | 1.02 | 60.0% | 1.04 | 0.42% |
| #5 | -1.19 | -7.07 | 0.34 | 57.1% | 0.02 | 0.26% |
| #6 | 0.29 | -4.82 | 0.45 | 50.0% | 0.28 | 0.27% |
| #7 | -0.91 | -4.60 | 0.61 | 18.2% | 0.01 | 0.34% |
| #8 | -4.58 | -5.18 | 0.48 | 50.0% | 0.13 | 0.22% |
| #9 | -2.97 | -4.37 | 0.49 | 33.3% | 0.19 | 0.23% |
| #10 | -2.47 | -3.76 | 0.57 | 0.0% | 0.00 | 0.11% |
| #11 | -2.82 | 2.78 | 1.60 | 57.1% | 2.09 | 0.21% |

- **In-Sample vs Out-of-Sample Degradation Ratio**: `0.00`
- **Overfitting Detector Status**: **CONDITIONAL (Regime-sensitive)**

#### Monte Carlo 1,000-Path Bootstrapped Equity Cones:
- **5th Percentile (Stress Downside)**: $98,831.70
- **50th Percentile (Expected Median)**: $99,514.25
- **95th Percentile (Upside Tail)**: $100,203.52
- **95th Percentile Maximum Drawdown**: 1.27%

### 2. ETH/USDT Analysis
- **Total Bars Analyzed**: 3000 bars
- **Final Net Profit**: $159.76 on $100,000 initial equity
- **Total Realized Trades**: 47
- **Annualized Sharpe Ratio**: 0.16
- **Deflated Sharpe Ratio (DSR)**: 0.00
- **Omega Ratio**: 1.07
- **Sortino Ratio**: 0.06
- **Maximum Drawdown**: 1.06% (Duration: 2409 bars)
- **Market Exposure Time**: 6.81%

#### Walk-Forward Folds (Rolling Train + Purged Embargo + Test):
| Fold | In-Sample Sharpe | Out-of-Sample Sharpe | OOS Omega | OOS Win Rate | OOS Profit Factor | OOS Max DD |
|---|---|---|---|---|---|---|
| #1 | 1.61 | 0.00 | 1.00 | 0.0% | 0.00 | 0.00% |
| #2 | 0.56 | 0.00 | 1.00 | 0.0% | 0.00 | 0.00% |
| #3 | 0.54 | -2.91 | 0.72 | 83.3% | 0.30 | 0.11% |
| #4 | -0.69 | -1.14 | 0.75 | 50.0% | 0.73 | 0.24% |
| #5 | -0.96 | 5.90 | 100.00 | 100.0% | 99.00 | 0.00% |
| #6 | -0.75 | -5.31 | 0.04 | 0.0% | 0.00 | 0.17% |
| #7 | -1.60 | -6.70 | 0.33 | 50.0% | 0.01 | 0.36% |
| #8 | -1.93 | 0.00 | 1.00 | 0.0% | 0.00 | 0.00% |
| #9 | -4.12 | -5.40 | 0.35 | 33.3% | 0.00 | 0.44% |
| #10 | -5.39 | -5.94 | 0.24 | 33.3% | 0.03 | 0.19% |
| #11 | -5.02 | 0.10 | 1.03 | 66.7% | 1.05 | 0.10% |

- **In-Sample vs Out-of-Sample Degradation Ratio**: `0.00`
- **Overfitting Detector Status**: **CONDITIONAL (Regime-sensitive)**

#### Monte Carlo 1,000-Path Bootstrapped Equity Cones:
- **5th Percentile (Stress Downside)**: $98,574.13
- **50th Percentile (Expected Median)**: $100,265.38
- **95th Percentile (Upside Tail)**: $102,168.89
- **95th Percentile Maximum Drawdown**: 1.93%

### 3. SOL/USDT Analysis
- **Total Bars Analyzed**: 3000 bars
- **Final Net Profit**: $125.60 on $100,000 initial equity
- **Total Realized Trades**: 27
- **Annualized Sharpe Ratio**: 0.16
- **Deflated Sharpe Ratio (DSR)**: 0.00
- **Omega Ratio**: 1.10
- **Sortino Ratio**: 0.08
- **Maximum Drawdown**: 0.59% (Duration: 1743 bars)
- **Market Exposure Time**: 4.89%

#### Walk-Forward Folds (Rolling Train + Purged Embargo + Test):
| Fold | In-Sample Sharpe | Out-of-Sample Sharpe | OOS Omega | OOS Win Rate | OOS Profit Factor | OOS Max DD |
|---|---|---|---|---|---|---|
| #1 | 0.00 | 0.00 | 1.00 | 0.0% | 0.00 | 0.00% |
| #2 | 0.00 | 0.00 | 1.00 | 0.0% | 0.00 | 0.00% |
| #3 | 0.00 | 2.59 | 1.60 | 100.0% | 99.00 | 0.06% |
| #4 | 1.40 | 2.23 | 2.74 | 100.0% | 99.00 | 0.11% |
| #5 | 1.78 | -5.13 | 0.00 | 0.0% | 0.00 | 0.20% |
| #6 | 0.83 | -4.65 | 0.00 | 0.0% | 0.00 | 0.18% |
| #7 | 0.46 | -6.16 | 0.26 | 0.0% | 0.00 | 0.25% |
| #8 | -3.84 | 4.62 | 26.46 | 100.0% | 99.00 | 0.00% |
| #9 | -2.01 | -4.72 | 0.34 | 66.7% | 0.08 | 0.23% |
| #10 | -2.81 | 3.73 | 3.81 | 50.0% | 740.19 | 0.05% |
| #11 | -0.58 | 1.70 | 1.37 | 50.0% | 1.73 | 0.20% |

- **In-Sample vs Out-of-Sample Degradation Ratio**: `0.00`
- **Overfitting Detector Status**: **CONDITIONAL (Regime-sensitive)**

#### Monte Carlo 1,000-Path Bootstrapped Equity Cones:
- **5th Percentile (Stress Downside)**: $98,861.95
- **50th Percentile (Expected Median)**: $100,467.56
- **95th Percentile (Upside Tail)**: $101,943.89
- **95th Percentile Maximum Drawdown**: 1.76%

### 4. SPY Analysis
- **Total Bars Analyzed**: 1500 bars
- **Final Net Profit**: $37042.00 on $100,000 initial equity
- **Total Realized Trades**: 26
- **Annualized Sharpe Ratio**: 1.07
- **Deflated Sharpe Ratio (DSR)**: 0.17
- **Omega Ratio**: 9.08
- **Sortino Ratio**: 35.83
- **Maximum Drawdown**: 0.33% (Duration: 657 bars)
- **Market Exposure Time**: 19.93%

#### Walk-Forward Folds (Rolling Train + Purged Embargo + Test):
| Fold | In-Sample Sharpe | Out-of-Sample Sharpe | OOS Omega | OOS Win Rate | OOS Profit Factor | OOS Max DD |
|---|---|---|---|---|---|---|
| #1 | -0.82 | 1.39 | 1.17 | 80.0% | 44.07 | 0.57% |
| #2 | -0.14 | 0.00 | 1.00 | 0.0% | 0.00 | 0.00% |
| #3 | -0.14 | -1.81 | 0.82 | 50.0% | 0.13 | 0.51% |
| #4 | -3.07 | -6.45 | 0.42 | 0.0% | 0.00 | 0.65% |
| #5 | 0.38 | -0.71 | 0.94 | 57.1% | 0.47 | 0.33% |
| #6 | 0.19 | -0.57 | 0.94 | 0.0% | 0.00 | 0.32% |
| #7 | 0.10 | -3.83 | 0.50 | 0.0% | 0.00 | 0.37% |
| #8 | -0.51 | 0.00 | 1.00 | 0.0% | 0.00 | 0.00% |
| #9 | 0.33 | 1.32 | 1.14 | 75.0% | 1.66 | 0.95% |

- **In-Sample vs Out-of-Sample Degradation Ratio**: `0.00`
- **Overfitting Detector Status**: **CONDITIONAL (Regime-sensitive)**

#### Monte Carlo 1,000-Path Bootstrapped Equity Cones:
- **5th Percentile (Stress Downside)**: $137,809.82
- **50th Percentile (Expected Median)**: $247,038.65
- **95th Percentile (Upside Tail)**: $358,993.09
- **95th Percentile Maximum Drawdown**: 0.48%

### 5. QQQ Analysis
- **Total Bars Analyzed**: 1500 bars
- **Final Net Profit**: $-1695.23 on $100,000 initial equity
- **Total Realized Trades**: 35
- **Annualized Sharpe Ratio**: -2.17
- **Deflated Sharpe Ratio (DSR)**: 0.00
- **Omega Ratio**: 0.76
- **Sortino Ratio**: -1.45
- **Maximum Drawdown**: 2.10% (Duration: 1125 bars)
- **Market Exposure Time**: 27.30%

#### Walk-Forward Folds (Rolling Train + Purged Embargo + Test):
| Fold | In-Sample Sharpe | Out-of-Sample Sharpe | OOS Omega | OOS Win Rate | OOS Profit Factor | OOS Max DD |
|---|---|---|---|---|---|---|
| #1 | -2.33 | -4.97 | 0.62 | 33.3% | 0.05 | 1.41% |
| #2 | -2.61 | -0.90 | 0.85 | 0.0% | 0.00 | 0.27% |
| #3 | -5.52 | 0.94 | 1.13 | 100.0% | 99.00 | 0.50% |
| #4 | -2.12 | -7.16 | 0.49 | 0.0% | 0.00 | 1.07% |
| #5 | -3.87 | -2.22 | 0.83 | 60.0% | 0.61 | 0.49% |
| #6 | -2.24 | 0.00 | 1.00 | 0.0% | 0.00 | 0.00% |
| #7 | -3.16 | -4.21 | 0.69 | 50.0% | 0.04 | 1.12% |
| #8 | -1.58 | 2.09 | 1.21 | 100.0% | 99.00 | 0.85% |
| #9 | -1.34 | 0.26 | 1.03 | 100.0% | 99.00 | 0.43% |

- **In-Sample vs Out-of-Sample Degradation Ratio**: `0.00`
- **Overfitting Detector Status**: **CONDITIONAL (Regime-sensitive)**

#### Monte Carlo 1,000-Path Bootstrapped Equity Cones:
- **5th Percentile (Stress Downside)**: $93,015.45
- **50th Percentile (Expected Median)**: $95,172.64
- **95th Percentile (Upside Tail)**: $97,083.40
- **95th Percentile Maximum Drawdown**: 7.11%

### 6. AAPL Analysis
- **Total Bars Analyzed**: 1000 bars
- **Final Net Profit**: $131495.53 on $100,000 initial equity
- **Total Realized Trades**: 36
- **Annualized Sharpe Ratio**: 1.30
- **Deflated Sharpe Ratio (DSR)**: 0.16
- **Omega Ratio**: 24.23
- **Sortino Ratio**: 172.63
- **Maximum Drawdown**: 0.78% (Duration: 965 bars)
- **Market Exposure Time**: 33.06%

#### Walk-Forward Folds (Rolling Train + Purged Embargo + Test):
| Fold | In-Sample Sharpe | Out-of-Sample Sharpe | OOS Omega | OOS Win Rate | OOS Profit Factor | OOS Max DD |
|---|---|---|---|---|---|---|
| #1 | -1.82 | -2.00 | 0.83 | 71.4% | 0.39 | 1.51% |
| #2 | -0.95 | 0.03 | 1.00 | 75.0% | 1.02 | 0.57% |
| #3 | -0.85 | -2.20 | 0.83 | 80.0% | 0.25 | 0.81% |
| #4 | -0.80 | 0.00 | 1.00 | 0.0% | 0.00 | 0.00% |

- **In-Sample vs Out-of-Sample Degradation Ratio**: `0.00`
- **Overfitting Detector Status**: **CONDITIONAL (Regime-sensitive)**

#### Monte Carlo 1,000-Path Bootstrapped Equity Cones:
- **5th Percentile (Stress Downside)**: $177,390.96
- **50th Percentile (Expected Median)**: $443,380.96
- **95th Percentile (Upside Tail)**: $786,331.31
- **95th Percentile Maximum Drawdown**: 1.38%

### 7. MSFT Analysis
- **Total Bars Analyzed**: 1000 bars
- **Final Net Profit**: $-1635.30 on $100,000 initial equity
- **Total Realized Trades**: 31
- **Annualized Sharpe Ratio**: -2.84
- **Deflated Sharpe Ratio (DSR)**: 0.00
- **Omega Ratio**: 0.70
- **Sortino Ratio**: -2.04
- **Maximum Drawdown**: 1.93% (Duration: 900 bars)
- **Market Exposure Time**: 25.91%

#### Walk-Forward Folds (Rolling Train + Purged Embargo + Test):
| Fold | In-Sample Sharpe | Out-of-Sample Sharpe | OOS Omega | OOS Win Rate | OOS Profit Factor | OOS Max DD |
|---|---|---|---|---|---|---|
| #1 | -4.27 | 0.00 | 1.00 | 0.0% | 0.00 | 0.00% |
| #2 | -3.14 | -1.63 | 0.82 | 50.0% | 0.37 | 0.67% |
| #3 | -1.13 | -4.05 | 0.70 | 62.5% | 0.28 | 0.74% |
| #4 | -2.25 | -9.49 | 0.44 | 33.3% | 0.03 | 1.45% |

- **In-Sample vs Out-of-Sample Degradation Ratio**: `0.00`
- **Overfitting Detector Status**: **CONDITIONAL (Regime-sensitive)**

#### Monte Carlo 1,000-Path Bootstrapped Equity Cones:
- **5th Percentile (Stress Downside)**: $92,273.29
- **50th Percentile (Expected Median)**: $94,859.71
- **95th Percentile (Upside Tail)**: $97,239.44
- **95th Percentile Maximum Drawdown**: 7.89%

### 8. NVDA Analysis
- **Total Bars Analyzed**: 1000 bars
- **Final Net Profit**: $-881.40 on $100,000 initial equity
- **Total Realized Trades**: 42
- **Annualized Sharpe Ratio**: -1.31
- **Deflated Sharpe Ratio (DSR)**: 0.00
- **Omega Ratio**: 0.87
- **Sortino Ratio**: -1.06
- **Maximum Drawdown**: 1.34% (Duration: 700 bars)
- **Market Exposure Time**: 34.40%

#### Walk-Forward Folds (Rolling Train + Purged Embargo + Test):
| Fold | In-Sample Sharpe | Out-of-Sample Sharpe | OOS Omega | OOS Win Rate | OOS Profit Factor | OOS Max DD |
|---|---|---|---|---|---|---|
| #1 | -1.84 | -1.27 | 0.90 | 75.0% | 0.46 | 1.01% |
| #2 | -0.93 | -0.08 | 0.99 | 50.0% | 0.63 | 0.38% |
| #3 | -0.89 | 3.12 | 1.33 | 62.5% | 2.46 | 0.95% |
| #4 | 0.77 | -0.22 | 0.96 | 50.0% | 0.40 | 0.77% |

- **In-Sample vs Out-of-Sample Degradation Ratio**: `0.00`
- **Overfitting Detector Status**: **CONDITIONAL (Regime-sensitive)**

#### Monte Carlo 1,000-Path Bootstrapped Equity Cones:
- **5th Percentile (Stress Downside)**: $95,914.03
- **50th Percentile (Expected Median)**: $97,906.86
- **95th Percentile (Upside Tail)**: $99,927.68
- **95th Percentile Maximum Drawdown**: 4.23%


---

## Production Architecture Highlights

1. **Data Layer (`backend/data_layer.py`)**:
   Seamless multi-asset integration with Binance Public REST, Bybit Perpetual funding rates, Coinbase, and Alpaca. Stores L2 depth snapshots and tick trades in SQLite/Parquet.
2. **Causal Feature Store (`backend/features.py`)**:
   Computes Parkinson High-Low range volatility, Yang-Zhang drift-independent volatility, ADX/DI, rolling BBW percentile, VWAP $Z$-scores, and strictly enforces lag-1 shifting.
3. **Probabilistic Regime Engine (`backend/regime.py`)**:
   Classifies market states into 4 canonical regimes (TRENDING, MEAN_REVERTING, HIGH_VOL, CRISIS) with online Bayesian inference, Kalman probability smoothing, and 2-bar state hysteresis.
4. **Multi-Alpha Ensemble (`backend/alphas.py`)**:
   Orthogonal strategies (KAMA/HMA Adaptive Trend, Bollinger Squeeze Mean-Reversion, Order Flow Imbalance, Volatility Breakout) dynamically blended with online Exponential Moving Sharpe weights.
5. **Portfolio Risk Engine (`backend/risk.py`)**:
   Target portfolio annualized volatility ($1/\sigma$), online Bayesian Half-Kelly sizing (Beta prior), monotonic progressive Chandelier ratchets, rolling correlation matrix filter, and daily drawdown circuit breakers.
6. **Production Backtester (`backend/backtester_v2.py`)**:
   Realistic transaction costs (fees, spread, market impact, latency drift), Combinatorial Purged Cross-Validation (CPCV) with embargo windows, Deflated Sharpe Ratio, and Monte Carlo equity paths.