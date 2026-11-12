# 🚀 Alpaca Quantitative Trading Terminal & Autonomous Bot

An enterprise-grade, high-frequency quantitative trading terminal and automated algorithmic execution engine built for **Alpaca Markets Paper Trading**. Featuring pure-Python technical indicators, adaptive volatility-based position sizing, a dynamic risk management framework, an interactive obsidian-glassmorphism web terminal, and high-fidelity simulated paper trading out of the box.

---

## 📑 Table of Contents

- [System Architecture & Overview](#-system-architecture--overview)
- [Key Features](#-key-features)
- [How to Obtain Free Alpaca Paper Trading Keys](#-how-to-obtain-free-alpaca-paper-trading-keys)
- [Quick Start & Installation](#-quick-start--installation)
- [Environment Configuration (`.env`)](#-environment-configuration-env)
- [Deep Dive: The Quantitative Strategy](#-deep-dive-the-quantitative-strategy)
  - [1. EMA Trend Crossover (9 / 21)](#1-exponential-moving-average-ema-trend-filter)
  - [2. RSI Momentum Oscillator (14)](#2-relative-strength-index-rsi-momentum-confirmation)
  - [3. ATR Adaptive Volatility Bands (14)](#3-average-true-range-atr-volatility-channel)
  - [Composite Signal Matrix](#composite-signal-decision-matrix)
- [Risk Management Framework](#-risk-management-framework)
  - [1% Capital Risk Per Trade](#1-capital-risk-allocation-budget)
  - [Volatility-Adjusted Share Sizing Math](#volatility-adjusted-share-sizing-formula)
  - [Dynamic Bracket Orders (SL & TP)](#dynamic-bracket-orders-stop-loss--take-profit)
  - [Portfolio Safety Constraints](#portfolio-safety-constraints)
- [Web Dashboard Walkthrough](#-web-dashboard-walkthrough)
- [REST API Reference & WebSocket Streaming](#-rest-api-reference--websocket-streaming)
- [Testing & Verification Suite](#-testing--verification-suite)
- [Troubleshooting & FAQ](#-troubleshooting--faq)

---

## 🏛 System Architecture & Overview

The Alpaca Quant Terminal is architected as an autonomous, modular trading system designed for reliability, sub-second execution, and full observability:

```
+-------------------------------------------------------------------------------+
|                             CLIENT / BROWSER                                  |
|  +-------------------------------------------------------------------------+  |
|  |     Obsidian Dark Quantitative Dashboard (HTML5 / Tailwind CSS CDN)     |  |
|  |     Chart.js Equity Curve  *  Underwater Drawdown  *  Real-time Tables  |  |
|  +-------------------------------------------------------------------------+  |
+---------------------------------------^---------------------------------------+
                                        |  (WebSocket /ws  &  REST Polling Fallback)
+---------------------------------------v---------------------------------------+
|                       FASTAPI SERVER (Uvicorn Async)                          |
|  - REST Endpoints (/api/status, /api/account, /api/positions, /api/trades...) |
|  - Real-Time WebSocket Broadcaster (/ws)                                      |
|  - Static Asset Delivery (/static)                                            |
+---------------------------------------^---------------------------------------+
                                        |
+---------------------------------------v---------------------------------------+
|                       EXECUTION ENGINE (Background Loop)                      |
|  - Autonomous Scan Cycle (every 30s)                                          |
|  - Account & Portfolio State Synchronization                                  |
|  - Position Stop-Loss & Take-Profit Monitor                                   |
|  - Market Scanner & Strategy Evaluator                                        |
+-------------------^---------------------------------------^-------------------+
                    |                                       |
+-------------------v-------------------+   +---------------v-------------------+
|     QUANTITATIVE STRATEGY ENGINE      |   |       RISK MANAGEMENT ENGINE      |
|  - EMA Fast (9) & Slow (21) Crossover |   |  - Fixed 1% Capital Risk Limit    |
|  - RSI (14) Momentum & Extreme Filter |   |  - ATR Volatility Share Sizer     |
|  - ATR (14) Dynamic Bracket Bands     |   |  - 25% Single-Position Cap        |
|  - Pure Python / High Precision Math  |   |  - Max 5 Concurrent Positions     |
+---------------------------------------+   +-----------------------------------+
                    |                                       |
+-------------------v---------------------------------------v-------------------+
|                            DATA & PERSISTENCE LAYER                           |
|  - SQLite3 Database (`trading_bot.db`)                                        |
|    * `equity_history`: Historical portfolio value, cash, buying power         |
|    * `trades`: Executed orders, fill prices, exit prices, realized P&L        |
|    * `signals`: Generated BUY/SELL/HOLD quantitative decisions & indicators  |
|    * `bot_logs`: Audit trail with log levels (INFO, BUY, SELL, RISK, WARN)    |
|    * `bot_settings`: Dynamic runtime configuration                            |
+---------------------------------------^---------------------------------------+
                                        |
+---------------------------------------v---------------------------------------+
|                    ALPACA CLIENT / MOCK PAPER ENGINE                          |
|  - Live Alpaca Paper Trading REST v2 (/v2/account, /v2/orders, /v2/positions) |
|  - Alpaca Market Data v2 (/v2/stocks/{symbol}/bars, /latest)                  |
|  - Auto-Fallback Mock Mode: High-fidelity synthetic simulator when keys are   |
|    missing or market is closed (zero external dependencies required)          |
+-------------------------------------------------------------------------------+
```

---

## ✨ Key Features

1. **Zero-Configuration Instant Start**: Works immediately out of the box. If no Alpaca API credentials are provided, the system automatically launches in **High-Fidelity Mock Mode**, simulating realistic $100,000 paper trading portfolios, bar generation, order fills, and bracket exits.
2. **Mathematically Rigorous Strategy**: Combines Exponential Moving Average (EMA) trend following, Relative Strength Index (RSI) momentum confirmation, and Average True Range (ATR) adaptive volatility bands.
3. **Institutional Risk Sizing**: Automatically calculates exact share quantities so that no trade risks more than 1% of total portfolio equity to its stop-loss level.
4. **Obsidian Glassmorphism Dashboard**: Dark slate UI (`#0f172a`), emerald gains (`#10b981`), rose drawdowns (`#f43f5e`), Chart.js equity curves, underwater drawdown charts, dynamic configuration sliders, and a real-time quant log terminal.
5. **Bi-Directional Real-Time Streaming**: High-speed WebSocket connection (`/ws`) broadcasts ticks, portfolio balance, active positions, closed trades, and logs, with transparent 3-second REST polling fallback.
6. **Robust SQLite Persistence**: Every order, fill, bracket exit, indicator calculation, and equity snapshot is recorded with indexing for sub-millisecond retrieval.

---

## 🔑 How to Obtain Free Alpaca Paper Trading Keys

Alpaca provides 100% free paper trading accounts with real-time US equity market data simulation:

1. **Sign Up**: Navigate to [Alpaca Markets](https://alpaca.markets/) and click **Sign Up** (or log in).
2. **Access Paper Account**: Once in the dashboard, switch the top-left toggle from **Live** to **Paper Trading**.
3. **Generate API Keys**:
   - In the right-hand panel under **Your API Keys**, click **Generate New Key** (or **View Keys**).
   - Copy the **API Key ID** (e.g. `PKXXXXXXXXXXXXXXXXXX`).
   - Copy the **Secret Key** (e.g. `XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX`).
   > [!IMPORTANT]
   > Save your Secret Key immediately; Alpaca will not display it again after you close the modal.
4. **Configure Endpoint**:
   - Paper Trading REST URL: `https://paper-api.alpaca.markets`
   - Data REST URL: `https://data.alpaca.markets/v2`

---

## ⚡ Quick Start & Installation

### Prerequisites
- Python 3.9+ (Python 3.10, 3.11, 3.12, or 3.14)
- `pip` package manager

### 1. Clone & Navigate
```bash
git clone https://github.com/your-repo/alpaca-quant-bot.git
cd alpaca-quant-bot
```

### 2. Configure Environment
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Edit `.env` with your Alpaca paper credentials (or leave them empty to run in simulated Mock Mode).

### 3. One-Click Launch
Run the automated startup script:
```bash
chmod +x run.sh
./run.sh
```

The script will automatically:
- Verify Python 3
- Set up or activate the virtual environment
- Install required dependencies (`fastapi`, `uvicorn`, `requests`, `pydantic`, `websockets`, `python-dotenv`)
- Start the FastAPI server on port 8000

### 4. Access the Dashboard
Open your browser and navigate to:
```
http://localhost:8000
```

---

## ⚙️ Environment Configuration (`.env`)

All parameters can be tuned in `.env` without modifying application code:

```ini
# ==============================================================================
# Alpaca Markets Credentials (Leave blank for Mock Mode)
# ==============================================================================
ALPACA_API_KEY=PKXXXXXXXXXXXXXXXXXX
ALPACA_SECRET_KEY=XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
ALPACA_BASE_URL=https://paper-api.alpaca.markets
ALPACA_DATA_URL=https://data.alpaca.markets/v2

# ==============================================================================
# Portfolio & Risk Limits
# ==============================================================================
# Maximum capital risked per trade (0.01 = 1% of total portfolio equity)
RISK_PER_TRADE_PCT=0.01

# Maximum simultaneous open positions
MAX_POSITIONS=5

# Comma-separated watchlist of ticker symbols
TRADING_SYMBOLS=AAPL,MSFT,NVDA,SPY,QQQ

# ==============================================================================
# Quantitative Indicator Settings
# ==============================================================================
FAST_EMA_PERIOD=9
SLOW_EMA_PERIOD=21
RSI_PERIOD=14
RSI_OVERSOLD=30.0
RSI_OVERBOUGHT=70.0
ATR_PERIOD=14

# Multiplier for Stop-Loss: Entry - (ATR * ATR_MULTIPLIER)
ATR_MULTIPLIER=2.0

# Multiplier for Take-Profit: Entry + (ATR * TAKE_PROFIT_MULTIPLIER)
TAKE_PROFIT_MULTIPLIER=3.0

# ==============================================================================
# Engine & Network Settings
# ==============================================================================
POLL_INTERVAL_SECONDS=30
MOCK_MODE=false
HOST=0.0.0.0
PORT=8000
```

---

## 🧠 Deep Dive: The Quantitative Strategy

The bot executes a multi-factor **Trend Following + Momentum + Adaptive Volatility** strategy designed to capture directional momentum while avoiding choppy sideways noise and market exhaustion.

### 1. Exponential Moving Average (EMA) Trend Filter
Moving averages identify directional trends by weighting recent prices exponentially higher:

$$\alpha = \frac{2}{N + 1}$$

$$\text{EMA}_t = (P_t \times \alpha) + (\text{EMA}_{t-1} \times (1 - \alpha))$$

Where:
- $N$: Period length (Fast $N = 9$, Slow $N = 21$)
- $P_t$: Close price at time $t$
- $\alpha$: Smoothing factor ($\alpha_9 \approx 0.200$, $\alpha_{21} \approx 0.0909$)

**Bullish Trend Condition**:
$$\text{EMA}_9 > \text{EMA}_{21} \quad \text{and} \quad P_t > \text{EMA}_9$$

---

### 2. Relative Strength Index (RSI) Momentum Confirmation
RSI measures the velocity and magnitude of directional price movements using Wilder's smoothed averages:

$$\text{RS} = \frac{\text{Smoothed Average Gain}}{\text{Smoothed Average Loss}}$$

$$\text{RSI} = 100 - \left( \frac{100}{1 + \text{RS}} \right)$$

- **Oversold Threshold**: $< 30$ (Potential mean-reversion bottom, or extreme selloff)
- **Overbought Threshold**: $> 70$ (Overextended rally, high probability of pullback)
- **Entry Momentum Sweet Spot**: $40 \le \text{RSI} \le 70$ (Confirms established upward momentum without being overbought)

---

### 3. Average True Range (ATR) Volatility Channel
ATR quantifies market volatility independent of price direction by evaluating gaps and high-low spreads:

$$\text{TR}_t = \max\Big( (H_t - L_t),\, |H_t - C_{t-1}|,\, |L_t - C_{t-1}| \Big)$$

$$\text{ATR}_t = \frac{(\text{ATR}_{t-1} \times (N - 1)) + \text{TR}_t}{N} \quad (N = 14)$$

Where:
- $H_t$: High price of current bar
- $L_t$: Low price of current bar
- $C_{t-1$: Close price of previous bar

---

### Composite Signal Decision Matrix

| Signal | Conditions | Action Taken |
| :--- | :--- | :--- |
| **BUY** | $\text{EMA}_9 > \text{EMA}_{21}$ AND $P_t > \text{EMA}_9$ AND $40 \le \text{RSI} \le 70$ | Trigger risk sizer, place bracket buy with dynamic SL & TP |
| **SELL** | $\text{EMA}_9 < \text{EMA}_{21}$ OR $\text{RSI} > 75$ OR $P_t \le \text{SL}$ OR $P_t \ge \text{TP}$ | Close existing long position, realize P&L, free capital |
| **HOLD** | Divergent indicators or choppy compression ($\text{EMA}_9 \approx \text{EMA}_{21}$) | Maintain active positions, scan remaining watchlist |

---

## 🛡 Risk Management Framework

Capital preservation is prioritized over raw trade frequency. The risk management engine enforces strict mathematical risk limits on every single trade before any order is submitted.

### 1% Capital Risk Allocation Budget
No individual trade is ever permitted to risk more than 1% of total portfolio equity:

$$\text{Risk Budget} = \text{Portfolio Equity} \times 0.01$$

*Example*: For a $\$100,000$ account, $\text{Risk Budget} = \$100,000 \times 0.01 = \$1,000$.

### Volatility-Adjusted Share Sizing Formula
The number of shares purchased is inversely proportional to asset volatility (ATR):

$$\text{Dollar Risk Per Share} = \text{ATR}_{14} \times \text{Multiplier}_{\text{SL}} = \text{ATR}_{14} \times 2.0$$

$$\text{Shares} = \left\lfloor \frac{\text{Portfolio Equity} \times \text{Risk Pct}}{\text{Dollar Risk Per Share}} \right\rfloor = \left\lfloor \frac{\text{Equity} \times 0.01}{\text{ATR}_{14} \times 2.0} \right\rfloor$$

#### Example Calculation:
- **Portfolio Equity**: $\$100,000.00$
- **Asset**: AAPL trading at $\$150.00$
- **$\text{ATR}_{14}$**: $\$2.50$
- **Stop Distance**: $2.0 \times \$2.50 = \$5.00$ per share
- **Stop Loss Price**: $\$150.00 - \$5.00 = \$145.00$
- **Take Profit Price**: $\$150.00 + (3.0 \times \$2.50) = \$157.50$ (1:1.5 Risk/Reward Ratio)
- **Position Size**:
  $$\text{Shares} = \left\lfloor \frac{100,000 \times 0.01}{5.00} \right\rfloor = \left\lfloor \frac{1,000}{5.00} \right\rfloor = 200 \text{ shares}$$
- **Capital Committed**: $200 \times \$150.00 = \$30,000.00$
- **Maximum Loss if SL hit**: $200 \times \$5.00 = \$1,000.00$ (exactly 1.0% of portfolio equity).

### Dynamic Bracket Orders (Stop-Loss & Take-Profit)
- **Stop-Loss Level**: $\text{Entry Price} - (2.0 \times \text{ATR}_{14})$
- **Take-Profit Level**: $\text{Entry Price} + (3.0 \times \text{ATR}_{14})$
- **Risk-to-Reward Ratio**: $1 : 1.5$ (requires only a 40% win rate to achieve long-term positive expectancy).

### Portfolio Safety Constraints
1. **Max Open Positions**: Capped at 5 positions simultaneously to prevent over-diversification and systemic drawdown.
2. **25% Single Position Cap**: The total dollar cost of any single trade cannot exceed 25% of total portfolio equity ($\text{Shares} \times \text{Price} \le 0.25 \times \text{Equity}$).
3. **Buying Power Buffer**: Orders must not exceed 95% of available cash/buying power to guard against margin spikes and slippage.
4. **Duplicate Prevention**: If a ticker already has an active open position, further buy signals for that ticker are automatically rejected.

---

## 🖥 Web Dashboard Walkthrough

The terminal dashboard is accessible at `http://localhost:8000`:

```
+-------------------------------------------------------------------------------+
| ALPACA QUANT TERMINAL [Live Paper Trading] [Market: OPEN] [Alpaca: CONNECTED] |
| [START BOT] [Refresh] [● WebSocket Connected]                   15:42:10 UTC  |
+-------------------------------------------------------------------------------+
| [Equity: $102,450.00] [Daily P&L: +$2,450 (+2.4%)] [Cash: $62,100 / BP: $124k] |
| [Win Rate: 68.4%]     [Profit Factor: 2.45]        [Max Drawdown: -1.8%]      |
+-------------------------------------------------------------------------------+
| +------------------------------------+  +-----------------------------------+ |
| | PORTFOLIO EQUITY CURVE             |  | UNDERWATER DRAWDOWN (%)           | |
| | [1D] [1W] [1M] [ALL]               |  | Peak-to-Trough Portfolio Retrace  | |
| | (Smooth emerald gradient fill)     |  | (Crimson shaded drawdown zone)    | |
| +------------------------------------+  +-----------------------------------+ |
+-------------------------------------------------------------------------------+
| ACTIVE POSITIONS (3)                                                          |
| Symbol | Side | Shares | Entry   | Current | Value    | Unrealized P&L | Action |
| AAPL   | LONG | 200    | $150.00 | $153.20 | $30,640  | +$640 (+2.1%)  | [CLOSE]|
| NVDA   | LONG | 80     | $450.00 | $458.50 | $36,680  | +$680 (+1.9%)  | [CLOSE]|
+-------------------------------------------------------------------------------+
| REAL-TIME QUANT LOG TERMINAL                                                  |
| 15:42:01 [INFO] Bot cycle started. Active symbols: AAPL, MSFT, NVDA, SPY, QQQ |
| 15:42:02 [BUY]  AAPL: Bullish 9/21 EMA cross (9: 151.2 > 21: 149.8), RSI: 58.4|
| 15:42:02 [RISK] Approved 200 shares AAPL (Risk: $1,000.00, SL: 145, TP: 157.5) |
+-------------------------------------------------------------------------------+
```

### Dashboard Components:
- **Header & Bot Controller**: Instant start/stop toggle, pulsing green/red status badge, live server clock, and WebSocket health indicator.
- **Top 6 KPI Summary Cards**: Real-time portfolio equity, daily P&L, cash & buying power, all-time win rate, profit factor, and maximum drawdown.
- **Interactive Chart Grid**: Chart.js portfolio equity curve with dynamic time filters (1D, 1W, 1M, ALL) and underwater drawdown chart.
- **Active Positions & Trades Table**: View symbol, entry price, current market price, unrealized P&L with color badges, and one-click manual close buttons.
- **Dynamic Risk Configuration**: Live sliders to tune risk percentage per trade (0.5% - 5%), maximum concurrent positions (1 - 10), and trading symbols list without restarting the server.
- **Quant Log Console**: High-speed terminal feed displaying execution cycles, technical indicator calculations, risk sizing decisions, and trade notifications.

---

## 📡 REST API Reference & WebSocket Streaming

### REST Endpoints

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/status` | Returns bot running state, Alpaca connection, market open/closed, and mock mode status. |
| `GET` | `/api/account` | Fetches portfolio equity, cash, buying power, and daily P&L. |
| `GET` | `/api/positions` | Lists all active open positions with unrealized P&L. |
| `DELETE` | `/api/positions/{symbol}` | Closes an active position immediately at market price. |
| `GET` | `/api/trades` | Retrieves historical filled, closed, and canceled trades (`?limit=50&status=CLOSED`). |
| `GET` | `/api/signals` | Lists technical indicator signals evaluated across watchlist tickers. |
| `GET` | `/api/metrics` | Calculates win rate, profit factor, max drawdown, and average trade return. |
| `GET` | `/api/equity-history` | Historical equity data points for Chart.js charting (`?limit=100`). |
| `POST` | `/api/bot/start` | Starts the autonomous background trading loop. |
| `POST` | `/api/bot/stop` | Stops the autonomous trading loop. |
| `POST` | `/api/bot/cycle` | Manually triggers an immediate single scan & execution cycle. |
| `GET` | `/api/bot/config` | Reads active risk and strategy configuration parameters. |
| `POST` | `/api/bot/config` | Updates risk %, max positions, or symbol watchlist dynamically at runtime. |
| `GET` | `/api/logs` | Fetches recent bot logs (`?limit=100&level=INFO`). |
| `GET` | `/api/crypto/state` | Returns live crypto price, 24h change, active market regime, and alpha score. |
| `GET` | `/api/crypto/regime` | Returns current regime (BULL, BEAR, COMPRESSION, BREAKOUT), ADX, and BBW. |
| `GET` | `/api/crypto/alphas` | Returns individual alpha scores (Trend, Mean-Rev, OFI) and composite score. |
| `GET` | `/api/crypto/features` | Returns strictly lag-1 causal feature matrix (Parkinson vol, Yang-Zhang vol, VWAP Z-score). |
| `GET` | `/api/risk/kelly` | Live Bayesian Half-Kelly parameters (alpha prior, beta prior, win rate, target vol scale). |
| `GET` | `/api/backtest/walkforward` | Executes walk-forward optimization with de Prado embargo cross-validation & Monte Carlo cones. |

### WebSocket Live Stream (`/ws`)
Connect via `ws://localhost:8000/ws`:
- **Initial Connection**: Automatically receives `INIT_SNAPSHOT` payload containing current status, account info, open positions, metrics, and recent logs.
- **Tick Stream**: Broadcasts `TICK_UPDATE` payload every 3 seconds with updated equity and market prices.
- **Trade Events**: Broadcasts real-time notifications on order placement, bracket exit fills, and strategy signals.

---

## 🧪 Testing & Verification Suite

The repository includes a comprehensive, standalone verification test suite (`test_system.py`) covering all functional layers:

```bash
python3 test_system.py
```

### Verified Test Categories:
- **`TestDatabaseOperations`**: Table initialization, equity recording, trade entry/exit lifecycle, signal logging, settings persistence, and win rate / profit factor math.
- **`TestStrategyCalculations`**: 9-period and 21-period EMA smoothing, Wilder's 14-period RSI calculations, 14-period ATR True Range logic, and bullish crossover signal generation.
- **`TestRiskManagement`**: Fixed 1% risk position sizing formula, max open positions enforcement (5), duplicate position prevention, 25% equity capital cap, and SL/TP exit triggers.
- **`TestAlpacaClientAndMock`**: Mock client initialization, synthetic bar generation, account data structure, market clock simulation, and paper order management.
- **`TestFastAPIServerEndpoints`**: REST endpoint response codes and schemas (`/api/status`, `/api/account`, `/api/positions`, `/api/trades`, `/api/metrics`, `/api/equity-history`, `/api/bot/config`), dynamic config POST updates, and static frontend index mounting.

---

## 🔧 Troubleshooting & FAQ

### 1. Can I run the bot without an Alpaca account?
**Yes!** The bot is built with high-fidelity local mock simulation. If `ALPACA_API_KEY` is absent or `MOCK_MODE=true` in `.env`, the bot will simulate realistic account balances ($100k), live ticker bars, orders, and bracket exits automatically.

### 2. Why are orders not executing in Paper Trading?
- **Market Hours**: US Equities trade between 9:30 AM and 4:00 PM EST. Outside market hours, Alpaca paper trading queues orders or rejects market orders depending on account configuration.
- **Key Permissions**: Verify your API keys are from the **Paper Trading** dashboard and not Live Trading.
- **Risk Limits**: Check the Quant Log Terminal in the dashboard; if your risk budget or buying power is insufficient for even 1 share of an expensive stock, the risk manager will log `Risk sizing yielded 0 shares`.

### 3. How do I change the scanned stock symbols?
You can update `TRADING_SYMBOLS` directly in `.env` (e.g. `TRADING_SYMBOLS=TSLA,AMD,GOOGL,AMZN`), or modify it on the fly via the Web Dashboard **Risk & Strategy Configuration** panel without restarting the bot.

---

## 📄 License
This project is open-source and distributed under the MIT License.
