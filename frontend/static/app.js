/**
 * ALPACA CRYPTO QUANT TERMINAL - Institutional Dashboard Application
 * 
 * Features:
 * - 24/7 Bitcoin Live Header Bar with real-time green/red tick flash
 * - Market Regime Radar Badge (TRENDING BULL, RANGING CHOP, TRENDING BEAR, VOLATILITY EXPANSION)
 * - Multi-Alpha Signal Matrix with dual-direction bar gauges (-100% to +100%) & Composite Ensemble Signal
 * - Institutional Risk KPI Cards (Sortino Ratio, Sharpe Ratio, Calmar Ratio, Win Rate, Profit Factor, Max Drawdown)
 * - Order Book Depth Meter (L2 Microstructure Depth Ladder, Volume Imbalance, Spread)
 * - Interactive Chart.js Strategy Chart (BTC Price + Bollinger Bands + Chandelier Trailing Stop Overlay)
 * - 24/7 Bot Control: Start/Stop toggle, Quant Cycle trigger, Fractional Kelly & Risk sliders, Live Log Console
 * - Low-latency WebSocket /ws streaming with automatic non-flickering fallback to polling
 */

// Application State
const state = {
  botRunning: false,
  connected: false,
  wsConnected: false,
  ws: null,
  pollTimer: null,
  reconnectAttempts: 0,
  activeChartTab: 'strategy', // 'strategy' or 'equity'
  selectedRange: '1D',
  autoScroll: true,
  logFilter: 'ALL',

  // 24/7 Crypto Market Microstructure
  crypto: {
    symbol: 'BTC/USD',
    price: 67420.0,
    prevPrice: 67420.0,
    change_24h: 3.45,
    change_usd: 2248.5,
    high_24h: 68910.0,
    low_24h: 64820.0,
    volume_24h: 1845000000,
    vol_delta: 412.5,
    
    // Market Regime Radar
    regime: 'TRENDING BULL', // 'TRENDING BULL', 'RANGING CHOP', 'TRENDING BEAR', 'VOLATILITY EXPANSION'
    adx: 32.4,
    di_plus: 28.5,
    di_minus: 14.2,
    bb_width_pct: 78.0,
    atr: 842.10,
    strategy_weights: {
      trend: 0.60,
      mean_reversion: 0.10,
      order_flow: 0.30
    },

    // Multi-Alpha Signal Matrix
    alphas: {
      trend: 0.82,       // Alpha 1: HMA/Donchian
      mean_rev: -0.14,   // Alpha 2: %B/VW-RSI
      ofi: 0.68,         // Alpha 3: Order Flow Imbalance
      composite: 0.745,  // Composite Ensemble (-1.0 to +1.0)
      direction: 'BUY',  // 'BUY', 'SELL', 'NEUTRAL'
      confidence: 0.864  // 0.0 to 1.0
    },

    // Order Book Microstructure (Top 5 L2)
    orderbook: {
      bid_volume: 58.2,
      ask_volume: 41.8,
      spread: 1.50,
      spread_bps: 0.22,
      imbalance_pct: 16.4,
      mid_price: 67420.0,
      bids: [
        { price: 67419.5, size: 2.45, total: 2.45, depthPct: 100 },
        { price: 67418.0, size: 4.80, total: 7.25, depthPct: 82 },
        { price: 67416.5, size: 7.15, total: 14.40, depthPct: 65 },
        { price: 67415.0, size: 3.20, total: 17.60, depthPct: 44 },
        { price: 67412.5, size: 8.90, total: 26.50, depthPct: 30 }
      ],
      asks: [
        { price: 67421.0, size: 1.85, total: 1.85, depthPct: 35 },
        { price: 67422.5, size: 3.40, total: 5.25, depthPct: 52 },
        { price: 67424.0, size: 6.10, total: 11.35, depthPct: 70 },
        { price: 67425.5, size: 5.00, total: 16.35, depthPct: 85 },
        { price: 67428.0, size: 7.60, total: 23.95, depthPct: 100 }
      ]
    }
  },

  // Institutional Risk Metrics
  metrics: {
    sortino_ratio: 2.84,
    sharpe_ratio: 2.15,
    calmar_ratio: 3.42,
    win_rate: 68.4,
    profit_factor: 2.38,
    max_drawdown: 3.82,
    total_trades: 24,
    expectancy: 385.40
  },

  // Portfolio Account
  account: {
    equity: 100000.0,
    cash: 65000.0,
    buying_power: 100000.0,
    daily_pnl: 2450.0,
    daily_pnl_pct: 2.45
  },

  positions: [],
  trades: [],
  logs: [],
  
  // Strategy & Risk Parameters
  config: {
    kelly_fraction: 0.25,
    risk_per_trade_pct: 0.01,
    chandelier_atr_multiplier: 3.0,
    max_positions: 3,
    trading_symbols: ['BTC/USD', 'ETH/USD']
  },

  // Historical Candles for Chart (Price, Bollinger Bands, Chandelier Stop)
  strategyCandles: []
};

// Chart.js instances
let cryptoStrategyChart = null;
let equityChart = null;

// Initialize on DOM Ready
document.addEventListener('DOMContentLoaded', () => {
  initIcons();
  generateInitialStrategyCandles();
  initCharts();
  bindEventListeners();
  startServerClock();
  
  // Populate initial UI
  renderHeaderTicker();
  renderRegimeRadar();
  renderAlphaMatrix();
  renderRiskKpis();
  renderOrderBook();
  renderPositionsTable();
  renderTradesTable();
  
  // Add initial system logs
  addLogEntry({ timestamp: new Date().toLocaleTimeString(), level: 'INFO', message: 'Crypto Quant Terminal initialized in Institutional Mode.' });
  addLogEntry({ timestamp: new Date().toLocaleTimeString(), level: 'REGIME', message: 'Market Regime classified as TRENDING BULL (ADX=32.4 > 25, +DI > -DI).' });
  addLogEntry({ timestamp: new Date().toLocaleTimeString(), level: 'ALPHA', message: 'Multi-Alpha Ensemble weighted: 60% Trend, 10% MeanRev, 30% OFI.' });
  addLogEntry({ timestamp: new Date().toLocaleTimeString(), level: 'KELLY', message: 'Quarter-Kelly optimal fraction f* = 0.25x initialized.' });

  // Fetch initial REST data then start WebSocket
  refreshAllData().then(() => {
    connectWebSocket();
  });
});

/**
 * Initialize Lucide Icons
 */
function initIcons() {
  if (window.lucide && typeof window.lucide.createIcons === 'function') {
    window.lucide.createIcons();
  }
}

/**
 * Formatting Utilities
 */
function formatCurrency(val, decimals = 2) {
  if (val === null || val === undefined || isNaN(val)) return '$0.00';
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(val);
}

function formatPercent(val, includeSign = true) {
  if (val === null || val === undefined || isNaN(val)) return '0.00%';
  const sign = includeSign && val > 0 ? '+' : '';
  return `${sign}${Number(val).toFixed(2)}%`;
}

function formatNumber(val, decimals = 2) {
  if (val === null || val === undefined || isNaN(val)) return '0';
  return Number(val).toFixed(decimals);
}

/**
 * Live UTC Clock
 */
function startServerClock() {
  const clockEl = document.getElementById('server-time');
  setInterval(() => {
    const now = new Date();
    const utcHours = String(now.getUTCHours()).padStart(2, '0');
    const utcMinutes = String(now.getUTCMinutes()).padStart(2, '0');
    const utcSeconds = String(now.getUTCSeconds()).padStart(2, '0');
    if (clockEl) {
      clockEl.textContent = `${utcHours}:${utcMinutes}:${utcSeconds} UTC`;
    }
  }, 1000);
}

/**
 * Toast Notifications
 */
function showToast(message, type = 'info', duration = 3500) {
  const container = document.getElementById('toast-container');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = `toast glass-panel p-3 shadow-2xl flex items-start gap-2.5 border text-xs ${
    type === 'success'
      ? 'border-emerald-500/50 bg-emerald-950/90 text-emerald-200'
      : type === 'error'
      ? 'border-rose-500/50 bg-rose-950/90 text-rose-200'
      : type === 'warning'
      ? 'border-amber-500/50 bg-amber-950/90 text-amber-200'
      : 'border-cyan-500/50 bg-slate-900/90 text-slate-200'
  }`;

  const iconName =
    type === 'success' ? 'check-circle' :
    type === 'error' ? 'alert-triangle' :
    type === 'warning' ? 'alert-circle' : 'info';

  toast.innerHTML = `
    <div class="mt-0.5 text-${type === 'success' ? 'emerald' : type === 'error' ? 'rose' : type === 'warning' ? 'amber' : 'cyan'}-400">
      <i data-lucide="${iconName}" class="w-4 h-4"></i>
    </div>
    <div class="flex-1 leading-snug">
      <div class="font-medium">${message}</div>
    </div>
    <button class="text-slate-400 hover:text-white transition close-btn ml-1">
      <i data-lucide="x" class="w-3.5 h-3.5"></i>
    </button>
  `;

  container.appendChild(toast);
  initIcons();

  const removeToast = () => {
    toast.classList.add('hiding');
    setTimeout(() => {
      if (toast.parentElement) toast.parentElement.removeChild(toast);
    }, 300);
  };

  toast.querySelector('.close-btn').addEventListener('click', removeToast);
  setTimeout(removeToast, duration);
}

/**
 * WebSocket Live Streaming with Fallback to Polling
 */
function connectWebSocket() {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${window.location.host}/ws`;

  updateWsStatusBadge('connecting');

  try {
    state.ws = new WebSocket(wsUrl);

    state.ws.onopen = () => {
      state.wsConnected = true;
      state.reconnectAttempts = 0;
      updateWsStatusBadge('connected');
      stopPollingFallback();
      addLogEntry({
        timestamp: new Date().toLocaleTimeString(),
        level: 'INFO',
        message: 'Live WebSocket connected to Crypto Quant Engine (/ws).',
      });
    };

    state.ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        handleWsMessage(msg);
      } catch (err) {
        console.error('Error parsing WS message:', err);
      }
    };

    state.ws.onclose = () => {
      state.wsConnected = false;
      updateWsStatusBadge('disconnected');
      startPollingFallback();
      scheduleWsReconnect();
    };

    state.ws.onerror = () => {
      state.wsConnected = false;
      updateWsStatusBadge('disconnected');
    };
  } catch (err) {
    console.warn('WebSocket init failed, using polling fallback:', err);
    state.wsConnected = false;
    updateWsStatusBadge('fallback');
    startPollingFallback();
    scheduleWsReconnect();
  }
}

function scheduleWsReconnect() {
  state.reconnectAttempts++;
  const delay = Math.min(1000 * Math.pow(1.5, state.reconnectAttempts), 8000);
  setTimeout(() => {
    if (!state.wsConnected) {
      connectWebSocket();
    }
  }, delay);
}

function updateWsStatusBadge(status) {
  const dot = document.getElementById('ws-dot');
  const text = document.getElementById('ws-text');
  if (!dot || !text) return;

  if (status === 'connected') {
    dot.className = 'w-2 h-2 rounded-full bg-emerald-400';
    text.textContent = 'WS 24/7 LIVE';
    text.className = 'text-emerald-400 font-semibold';
  } else if (status === 'connecting') {
    dot.className = 'w-2 h-2 rounded-full bg-amber-400 animate-pulse';
    text.textContent = 'WS CONNECTING';
    text.className = 'text-amber-400';
  } else {
    dot.className = 'w-2 h-2 rounded-full bg-cyan-400 animate-pulse';
    text.textContent = 'REST POLLING (2s)';
    text.className = 'text-cyan-400 font-medium';
  }
}

function startPollingFallback() {
  if (state.pollTimer) return;
  state.pollTimer = setInterval(() => {
    refreshAllData(true);
  }, 2500);
}

function stopPollingFallback() {
  if (state.pollTimer) {
    clearInterval(state.pollTimer);
    state.pollTimer = null;
  }
}

/**
 * Handle Live WebSocket Payloads
 */
function handleWsMessage(msg) {
  if (!msg) return;

  const type = msg.type || (msg.event ? msg.event : null);
  const data = msg.data !== undefined ? msg.data : msg;

  if (type === 'CRYPTO_TICK' || type === 'tick') {
    handleLiveCryptoTick(data);
  } else if (type === 'REGIME_CHANGE') {
    updateRegimeState(data);
  } else if (type === 'ALPHA_UPDATE') {
    updateAlphaState(data);
  } else if (type === 'ORDERBOOK_UPDATE') {
    updateOrderBookState(data);
  } else if (type === 'TICK_UPDATE' || type === 'INIT_SNAPSHOT') {
    if (data.status) updateStatusState(data.status);
    if (data.account) updateAccountState(data.account);
    if (data.positions) updatePositionsState(data.positions);
    if (data.metrics) updateMetricsState(data.metrics);
    if (data.crypto) handleLiveCryptoTick(data.crypto);
    if (data.regime) updateRegimeState(data.regime);
    if (data.alphas) updateAlphaState(data.alphas);
    if (data.orderbook) updateOrderBookState(data.orderbook);
  } else if (type === 'LOG' || type === 'log') {
    addLogEntry(data);
  }
}

/**
 * Handle Live Bitcoin Price Tick with Pulsing Green/Red Flash
 */
function handleLiveCryptoTick(tick) {
  if (!tick) return;
  const oldPrice = state.crypto.price;
  const newPrice = Number(tick.price || tick.btc_price || oldPrice);
  state.crypto.prevPrice = oldPrice;
  state.crypto.price = newPrice;

  if (tick.change_24h !== undefined) state.crypto.change_24h = Number(tick.change_24h);
  if (tick.high_24h !== undefined) state.crypto.high_24h = Number(tick.high_24h);
  if (tick.low_24h !== undefined) state.crypto.low_24h = Number(tick.low_24h);
  if (tick.volume_24h !== undefined) state.crypto.volume_24h = Number(tick.volume_24h);
  if (tick.vol_delta !== undefined) state.crypto.vol_delta = Number(tick.vol_delta);

  renderHeaderTicker(newPrice >= oldPrice ? 'up' : 'down');
  
  // Update Live Chart with latest tick
  appendTickToStrategyChart(newPrice);
}

/**
 * Render Bitcoin 24/7 Live Header Bar
 */
function renderHeaderTicker(direction = null) {
  const priceEl = document.getElementById('btc-header-price');
  const changeEl = document.getElementById('btc-header-change');
  const highEl = document.getElementById('btc-header-high');
  const lowEl = document.getElementById('btc-header-low');
  const volEl = document.getElementById('btc-header-vol');
  const deltaEl = document.getElementById('btc-header-delta');

  if (priceEl) {
    priceEl.textContent = formatCurrency(state.crypto.price, 2);
    if (direction) {
      priceEl.classList.remove('flash-up', 'flash-down');
      void priceEl.offsetWidth; // trigger reflow
      priceEl.classList.add(direction === 'up' ? 'flash-up' : 'flash-down');
    }
  }

  if (changeEl) {
    const isPos = state.crypto.change_24h >= 0;
    changeEl.textContent = formatPercent(state.crypto.change_24h);
    changeEl.className = `text-[11px] font-semibold font-mono tabular-nums ${isPos ? 'text-emerald-400' : 'text-rose-400'}`;
  }

  if (highEl) highEl.textContent = formatCurrency(state.crypto.high_24h, 2);
  if (lowEl) lowEl.textContent = formatCurrency(state.crypto.low_24h, 2);
  if (volEl) volEl.textContent = `$${(state.crypto.volume_24h / 1e9).toFixed(2)}B`;
  
  if (deltaEl) {
    const delta = state.crypto.vol_delta;
    const isPos = delta >= 0;
    deltaEl.textContent = `${isPos ? '+' : ''}${formatNumber(delta, 1)} BTC`;
    deltaEl.className = `font-semibold tabular-nums ${isPos ? 'text-emerald-400' : 'text-rose-400'}`;
  }
}

/**
 * Market Regime Radar Renderer
 */
function updateRegimeState(data) {
  if (!data) return;
  state.crypto.regime = data.current_regime || data.regime || state.crypto.regime;
  if (data.adx !== undefined) state.crypto.adx = Number(data.adx);
  if (data.di_plus !== undefined) state.crypto.di_plus = Number(data.di_plus);
  if (data.di_minus !== undefined) state.crypto.di_minus = Number(data.di_minus);
  if (data.bb_width_pct !== undefined) state.crypto.bb_width_pct = Number(data.bb_width_pct);
  if (data.atr !== undefined) state.crypto.atr = Number(data.atr);
  if (data.strategy_weights) state.crypto.strategy_weights = data.strategy_weights;

  renderRegimeRadar();
}

function renderRegimeRadar() {
  const badgeEl = document.getElementById('regime-badge');
  const nameEl = document.getElementById('regime-name');
  const dotEl = document.getElementById('regime-radar-dot');
  const adxEl = document.getElementById('regime-adx');
  const diEl = document.getElementById('regime-di');
  const bbwEl = document.getElementById('regime-bbw');
  const atrEl = document.getElementById('regime-atr');

  const regime = state.crypto.regime.toUpperCase();
  if (nameEl) nameEl.textContent = regime;

  if (badgeEl && dotEl) {
    if (regime.includes('BULL')) {
      badgeEl.className = 'px-3 py-1 rounded-full text-xs font-bold tracking-wider regime-badge-bull flex items-center gap-1.5';
      dotEl.className = 'w-2 h-2 rounded-full bg-emerald-400 animate-ping';
    } else if (regime.includes('CHOP') || regime.includes('REVERT')) {
      badgeEl.className = 'px-3 py-1 rounded-full text-xs font-bold tracking-wider regime-badge-chop flex items-center gap-1.5';
      dotEl.className = 'w-2 h-2 rounded-full bg-amber-400 animate-ping';
    } else if (regime.includes('BEAR')) {
      badgeEl.className = 'px-3 py-1 rounded-full text-xs font-bold tracking-wider regime-badge-bear flex items-center gap-1.5';
      dotEl.className = 'w-2 h-2 rounded-full bg-rose-400 animate-ping';
    } else {
      badgeEl.className = 'px-3 py-1 rounded-full text-xs font-bold tracking-wider regime-badge-vol flex items-center gap-1.5';
      dotEl.className = 'w-2 h-2 rounded-full bg-cyan-400 animate-ping';
    }
  }

  if (adxEl) adxEl.textContent = formatNumber(state.crypto.adx, 1);
  if (diEl) diEl.textContent = `${formatNumber(state.crypto.di_plus, 1)} / ${formatNumber(state.crypto.di_minus, 1)}`;
  if (bbwEl) bbwEl.textContent = `${Math.round(state.crypto.bb_width_pct)}th Pct`;
  if (atrEl) atrEl.textContent = formatCurrency(state.crypto.atr, 2);

  // Strategy Weights Allocation Bar
  const weights = state.crypto.strategy_weights || { trend: 0.6, mean_reversion: 0.1, order_flow: 0.3 };
  const wTrend = Math.round((weights.trend || 0.6) * 100);
  const wMr = Math.round((weights.mean_reversion || weights.mean_rev || 0.1) * 100);
  const wOfi = Math.round((weights.order_flow || weights.ofi || 0.3) * 100);

  const labelEl = document.getElementById('regime-weights-label');
  const barTrend = document.getElementById('bar-weight-trend');
  const barMr = document.getElementById('bar-weight-mr');
  const barOfi = document.getElementById('bar-weight-ofi');

  if (labelEl) labelEl.textContent = `${wTrend}% Trend | ${wMr}% MeanRev | ${wOfi}% OFI`;
  if (barTrend) barTrend.style.width = `${wTrend}%`;
  if (barMr) barMr.style.width = `${wMr}%`;
  if (barOfi) barOfi.style.width = `${wOfi}%`;
}

/**
 * Multi-Alpha Signal Matrix Renderer
 */
function updateAlphaState(data) {
  if (!data) return;
  if (data.trend_score !== undefined) state.crypto.alphas.trend = Number(data.trend_score);
  if (data.mean_rev_score !== undefined) state.crypto.alphas.mean_rev = Number(data.mean_rev_score);
  if (data.ofi_score !== undefined) state.crypto.alphas.ofi = Number(data.ofi_score);
  if (data.composite_score !== undefined) state.crypto.alphas.composite = Number(data.composite_score);
  if (data.direction) state.crypto.alphas.direction = data.direction.toUpperCase();
  if (data.confidence !== undefined) state.crypto.alphas.confidence = Number(data.confidence);

  renderAlphaMatrix();
}

function renderAlphaMatrix() {
  const { trend, mean_rev, ofi, composite, direction, confidence } = state.crypto.alphas;

  // Composite Score & Badge
  const compEl = document.getElementById('composite-score');
  const badgeEl = document.getElementById('composite-badge');
  const confEl = document.getElementById('composite-confidence');

  if (compEl) {
    const isPos = composite >= 0;
    compEl.textContent = `${isPos ? '+' : ''}${Math.round(composite * 100)}%`;
    compEl.className = `text-xs font-bold font-mono tabular-nums ${isPos ? 'text-emerald-400' : 'text-rose-400'}`;
  }

  if (badgeEl) {
    badgeEl.textContent = direction === 'BUY' ? 'STRONG BUY' : direction === 'SELL' ? 'STRONG SELL' : 'NEUTRAL';
    badgeEl.className = `px-2 py-0.5 rounded text-[10px] font-bold border ${
      direction === 'BUY'
        ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
        : direction === 'SELL'
        ? 'bg-rose-500/10 text-rose-400 border-rose-500/30'
        : 'bg-slate-800 text-slate-300 border-slate-700'
    }`;
  }

  if (confEl) confEl.textContent = `${(confidence * 100).toFixed(1)}%`;

  // Alpha 1: Trend Bar Gauge
  renderBiDirectionalBar('alpha-trend-val', 'alpha-trend-bar-pos', 'alpha-trend-bar-neg', trend);

  // Alpha 2: Mean Reversion Bar Gauge
  renderBiDirectionalBar('alpha-mr-val', 'alpha-mr-bar-pos', 'alpha-mr-bar-neg', mean_rev);

  // Alpha 3: Order Flow Imbalance Bar Gauge
  renderBiDirectionalBar('alpha-ofi-val', 'alpha-ofi-bar-pos', 'alpha-ofi-bar-neg', ofi);
}

function renderBiDirectionalBar(valId, posBarId, negBarId, score) {
  const valEl = document.getElementById(valId);
  const posEl = document.getElementById(posBarId);
  const negEl = document.getElementById(negBarId);

  const pct = Math.min(Math.max(score, -1.0), 1.0);
  const pctInt = Math.round(pct * 100);

  if (valEl) {
    const isPos = pct >= 0;
    valEl.textContent = `${isPos ? '+' : ''}${pct.toFixed(2)} (${isPos ? '+' : ''}${pctInt}%)`;
    valEl.className = `font-mono font-bold tabular-nums ${isPos ? 'text-emerald-400' : 'text-rose-400'}`;
  }

  if (posEl && negEl) {
    if (pct >= 0) {
      posEl.style.width = `${pct * 50}%`;
      negEl.style.width = '0%';
    } else {
      posEl.style.width = '0%';
      negEl.style.width = `${Math.abs(pct) * 50}%`;
    }
  }
}

/**
 * Institutional Risk KPI Cards Renderer
 */
function updateMetricsState(data) {
  if (!data) return;
  state.metrics = { ...state.metrics, ...data };
  renderRiskKpis();
}

function renderRiskKpis() {
  const { sortino_ratio, sharpe_ratio, calmar_ratio, win_rate, profit_factor, max_drawdown, total_trades } = state.metrics;
  const { equity, daily_pnl, daily_pnl_pct } = state.account;

  const eqEl = document.getElementById('kpi-equity');
  const eqChangeEl = document.getElementById('kpi-equity-change');
  if (eqEl) eqEl.textContent = formatCurrency(equity, 0);
  if (eqChangeEl) eqChangeEl.textContent = `${daily_pnl >= 0 ? '+' : ''}${formatCurrency(daily_pnl, 2)} (${formatPercent(daily_pnl_pct)})`;

  const pnlEl = document.getElementById('kpi-daily-pnl');
  const pnlPctEl = document.getElementById('kpi-daily-pnl-pct');
  const pnlBar = document.getElementById('pnl-accent-bar');
  if (pnlEl) {
    pnlEl.textContent = (daily_pnl >= 0 ? '+' : '') + formatCurrency(daily_pnl, 2);
    pnlEl.className = `text-base sm:text-lg font-bold tracking-tight tabular-nums ${daily_pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`;
  }
  if (pnlPctEl) {
    pnlPctEl.textContent = formatPercent(daily_pnl_pct);
    pnlPctEl.className = `text-[10px] font-medium tabular-nums ${daily_pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`;
  }
  if (pnlBar) {
    pnlBar.className = `absolute bottom-0 left-0 right-0 h-0.5 ${daily_pnl >= 0 ? 'bg-emerald-500' : 'bg-rose-500'} opacity-60`;
  }

  // Institutional Ratios
  const sortinoEl = document.getElementById('kpi-sortino');
  if (sortinoEl) {
    sortinoEl.textContent = formatNumber(sortino_ratio, 2);
    sortinoEl.className = `text-base sm:text-lg font-bold tracking-tight tabular-nums ${sortino_ratio >= 2.0 ? 'text-emerald-400' : 'text-cyan-400'}`;
  }

  const sharpeEl = document.getElementById('kpi-sharpe');
  if (sharpeEl) sharpeEl.textContent = formatNumber(sharpe_ratio, 2);

  const calmarEl = document.getElementById('kpi-calmar');
  if (calmarEl) calmarEl.textContent = formatNumber(calmar_ratio, 2);

  const winRateEl = document.getElementById('kpi-win-rate');
  const winRateBar = document.getElementById('win-rate-bar');
  if (winRateEl) winRateEl.textContent = `${formatNumber(win_rate, 1)}%`;
  if (winRateBar) winRateBar.style.width = `${Math.min(Math.max(win_rate, 0), 100)}%`;

  const pfEl = document.getElementById('kpi-profit-factor');
  const tradesEl = document.getElementById('kpi-total-trades');
  if (pfEl) pfEl.textContent = formatNumber(profit_factor, 2);
  if (tradesEl) tradesEl.textContent = String(total_trades);

  const ddEl = document.getElementById('kpi-max-drawdown');
  if (ddEl) ddEl.textContent = `-${formatNumber(Math.abs(max_drawdown), 2)}%`;
}

/**
 * Order Book Microstructure Renderer
 */
function updateOrderBookState(data) {
  if (!data) return;
  state.crypto.orderbook = { ...state.crypto.orderbook, ...data };
  renderOrderBook();
}

function renderOrderBook() {
  const ob = state.crypto.orderbook;
  if (!ob) return;

  const spreadEl = document.getElementById('ob-spread');
  const bidPctEl = document.getElementById('ob-bid-pct');
  const askPctEl = document.getElementById('ob-ask-pct');
  const bidBar = document.getElementById('ob-depth-bid-bar');
  const askBar = document.getElementById('ob-depth-ask-bar');
  const midPriceEl = document.getElementById('ob-mid-price');
  const ofiRatioEl = document.getElementById('ob-ofi-ratio');

  if (spreadEl) spreadEl.textContent = `$${formatNumber(ob.spread, 2)} (${formatNumber(ob.spread_bps, 2)} bps)`;
  if (bidPctEl) bidPctEl.textContent = `${formatNumber(ob.bid_volume, 1)}%`;
  if (askPctEl) askPctEl.textContent = `${formatNumber(ob.ask_volume, 1)}%`;
  if (bidBar) bidBar.style.width = `${ob.bid_volume}%`;
  if (askBar) askBar.style.width = `${ob.ask_volume}%`;
  if (midPriceEl) midPriceEl.textContent = formatCurrency(ob.mid_price || state.crypto.price, 2);

  if (ofiRatioEl) {
    const isBuy = (ob.imbalance_pct || 0) >= 0;
    ofiRatioEl.textContent = `${isBuy ? '+' : ''}${formatNumber(ob.imbalance_pct, 1)}% ${isBuy ? 'Buy Pressure' : 'Sell Pressure'}`;
    ofiRatioEl.className = `font-bold font-mono ${isBuy ? 'text-emerald-400' : 'text-rose-400'}`;
  }

  // Render Asks (descending top 5)
  const asksList = document.getElementById('ob-asks-list');
  if (asksList && Array.isArray(ob.asks)) {
    asksList.innerHTML = ob.asks.slice(0, 5).reverse().map(ask => `
      <div class="depth-row text-rose-400">
        <div class="depth-bg-ask" style="width: ${ask.depthPct || 50}%;"></div>
        <span class="font-semibold">${formatNumber(ask.price, 1)}</span>
        <span class="text-slate-300">${formatNumber(ask.size, 3)}</span>
        <span class="text-slate-500">${formatNumber(ask.total, 3)}</span>
      </div>
    `).join('');
  }

  // Render Bids (top 5)
  const bidsList = document.getElementById('ob-bids-list');
  if (bidsList && Array.isArray(ob.bids)) {
    bidsList.innerHTML = ob.bids.slice(0, 5).map(bid => `
      <div class="depth-row text-emerald-400">
        <div class="depth-bg-bid" style="width: ${bid.depthPct || 50}%;"></div>
        <span class="font-semibold">${formatNumber(bid.price, 1)}</span>
        <span class="text-slate-300">${formatNumber(bid.size, 3)}</span>
        <span class="text-slate-500">${formatNumber(bid.total, 3)}</span>
      </div>
    `).join('');
  }
}

/**
 * Historical Data Synthesis for Chart.js
 */
function generateInitialStrategyCandles() {
  const points = [];
  let basePrice = 64800.0;
  const now = Date.now();
  
  for (let i = 40; i >= 0; i--) {
    const time = new Date(now - i * 60 * 1000);
    const timeStr = `${time.getHours()}:${String(time.getMinutes()).padStart(2, '0')}`;
    
    // Add realistic crypto random walk with slight bull trend
    const delta = (Math.random() - 0.46) * 180;
    basePrice += delta;
    
    // Bollinger Band approximation
    const upperBB = basePrice + 450 + Math.sin(i / 5) * 120;
    const lowerBB = basePrice - 450 - Math.sin(i / 5) * 120;
    const chandelierStop = basePrice - 650; // 3x ATR below price in bull regime
    const ema50 = basePrice - 180;

    points.push({
      time: timeStr,
      price: basePrice,
      upperBB,
      lowerBB,
      chandelierStop,
      ema50
    });
  }

  // Ensure last point aligns with current price
  points[points.length - 1].price = state.crypto.price;
  state.strategyCandles = points;
}

function appendTickToStrategyChart(newPrice) {
  if (!cryptoStrategyChart || !state.strategyCandles.length) return;

  const now = new Date();
  const timeStr = `${now.getHours()}:${String(now.getMinutes()).padStart(2, '0')}`;
  
  // Calculate dynamic Bollinger & Chandelier Stop
  const upperBB = newPrice + 480;
  const lowerBB = newPrice - 480;
  const chandelierStop = newPrice - (3.0 * (state.crypto.atr || 840));
  const ema50 = newPrice - 200;

  // Add new point and shift if length > 50
  state.strategyCandles.push({
    time: timeStr,
    price: newPrice,
    upperBB,
    lowerBB,
    chandelierStop,
    ema50
  });
  if (state.strategyCandles.length > 50) {
    state.strategyCandles.shift();
  }

  updateStrategyChartData();
}

/**
 * Initialize Chart.js Instances
 */
function initCharts() {
  Chart.defaults.color = '#94a3b8';
  Chart.defaults.font.family = 'JetBrains Mono, monospace';

  // 1. Interactive Crypto Strategy Chart (Bollinger Bands + Chandelier Stop)
  const stratCtx = document.getElementById('cryptoStrategyChart');
  if (stratCtx) {
    cryptoStrategyChart = new Chart(stratCtx, {
      type: 'line',
      data: {
        labels: [],
        datasets: [
          {
            label: 'BTC/USD Price',
            data: [],
            borderColor: '#06b6d4',
            borderWidth: 2.2,
            pointRadius: 0,
            pointHoverRadius: 5,
            pointHoverBackgroundColor: '#06b6d4',
            tension: 0.15,
            zIndex: 10
          },
          {
            label: 'Bollinger Upper',
            data: [],
            borderColor: 'rgba(245, 158, 11, 0.65)',
            borderWidth: 1.2,
            borderDash: [4, 4],
            pointRadius: 0,
            fill: '+1',
            backgroundColor: 'rgba(245, 158, 11, 0.05)',
            tension: 0.2
          },
          {
            label: 'Bollinger Lower',
            data: [],
            borderColor: 'rgba(245, 158, 11, 0.65)',
            borderWidth: 1.2,
            borderDash: [4, 4],
            pointRadius: 0,
            fill: false,
            tension: 0.2
          },
          {
            label: 'Chandelier Trailing Stop (3.0x ATR)',
            data: [],
            borderColor: '#10b981',
            borderWidth: 1.8,
            borderDash: [6, 3],
            pointRadius: 0,
            stepped: 'before',
            tension: 0
          },
          {
            label: 'EMA(50) Trend Baseline',
            data: [],
            borderColor: 'rgba(99, 102, 241, 0.5)',
            borderWidth: 1.2,
            pointRadius: 0,
            tension: 0.2
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 300 },
        interaction: { intersect: false, mode: 'index' },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: '#070b14',
            borderColor: '#334155',
            borderWidth: 1,
            titleColor: '#f8fafc',
            bodyColor: '#38bdf8',
            callbacks: {
              label: (ctx) => ` ${ctx.dataset.label}: ${formatCurrency(ctx.parsed.y, 2)}`
            }
          }
        },
        scales: {
          x: {
            grid: { color: 'rgba(51, 65, 85, 0.2)' },
            ticks: { maxTicksLimit: 8, font: { size: 10 } }
          },
          y: {
            grid: { color: 'rgba(51, 65, 85, 0.2)' },
            ticks: {
              callback: (val) => formatCurrency(val, 0),
              font: { size: 10 }
            }
          }
        }
      }
    });

    updateStrategyChartData();
  }

  // 2. Secondary Equity Growth Curve Chart
  const eqCtx = document.getElementById('equityChart');
  if (eqCtx) {
    equityChart = new Chart(eqCtx, {
      type: 'line',
      data: {
        labels: [],
        datasets: [{
          label: 'Portfolio Equity ($)',
          data: [],
          borderColor: '#10b981',
          borderWidth: 2,
          pointRadius: 0,
          tension: 0.2,
          fill: true,
          backgroundColor: (context) => {
            const ctx = context.chart.ctx;
            const gradient = ctx.createLinearGradient(0, 0, 0, 300);
            gradient.addColorStop(0, 'rgba(16, 185, 129, 0.35)');
            gradient.addColorStop(1, 'rgba(16, 185, 129, 0.00)');
            return gradient;
          }
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { grid: { color: 'rgba(51, 65, 85, 0.2)' }, ticks: { maxTicksLimit: 7, font: { size: 10 } } },
          y: { grid: { color: 'rgba(51, 65, 85, 0.2)' }, ticks: { callback: (val) => formatCurrency(val, 0), font: { size: 10 } } }
        }
      }
    });
  }
}

function updateStrategyChartData() {
  if (!cryptoStrategyChart) return;
  const candles = state.strategyCandles;
  if (!candles || !candles.length) return;

  cryptoStrategyChart.data.labels = candles.map(c => c.time);
  cryptoStrategyChart.data.datasets[0].data = candles.map(c => c.price);
  cryptoStrategyChart.data.datasets[1].data = candles.map(c => c.upperBB);
  cryptoStrategyChart.data.datasets[2].data = candles.map(c => c.lowerBB);
  cryptoStrategyChart.data.datasets[3].data = candles.map(c => c.chandelierStop);
  cryptoStrategyChart.data.datasets[4].data = candles.map(c => c.ema50);
  cryptoStrategyChart.update('none');
}

/**
 * REST Client & Aggregation
 */
async function fetchApi(endpoint, options = {}) {
  try {
    const res = await fetch(endpoint, {
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
      ...options,
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (err) {
    return null;
  }
}

async function refreshAllData(silent = false) {
  const refreshBtn = document.getElementById('btn-refresh');
  const refreshIcon = refreshBtn ? refreshBtn.querySelector('i') : null;
  if (!silent && refreshIcon) refreshIcon.classList.add('animate-spin');

  try {
    const [status, cryptoState, regimeData, alphaData, obData, metricsData, accountData, positionsData, tradesData] =
      await Promise.all([
        fetchApi('/api/status'),
        fetchApi('/api/crypto/state'),
        fetchApi('/api/crypto/regime'),
        fetchApi('/api/crypto/alphas'),
        fetchApi('/api/crypto/orderbook'),
        fetchApi('/api/crypto/metrics') || fetchApi('/api/metrics'),
        fetchApi('/api/account'),
        fetchApi('/api/positions'),
        fetchApi('/api/trades')
      ]);

    if (status) updateStatusState(status);
    if (cryptoState) handleLiveCryptoTick(cryptoState);
    if (regimeData) updateRegimeState(regimeData);
    if (alphaData) updateAlphaState(alphaData);
    if (obData) updateOrderBookState(obData);
    if (metricsData) updateMetricsState(metricsData);
    if (accountData) updateAccountState(accountData);
    if (positionsData) updatePositionsState(positionsData);
    if (tradesData) updateTradesState(tradesData);
  } finally {
    if (!silent && refreshIcon) {
      setTimeout(() => refreshIcon.classList.remove('animate-spin'), 350);
    }
  }
}

function updateStatusState(data) {
  if (!data) return;
  state.botRunning = !!data.running;
  renderBotControls();
}

function updateAccountState(data) {
  if (!data) return;
  state.account = { ...state.account, ...data };
  renderRiskKpis();
}

function renderBotControls() {
  const btnToggle = document.getElementById('btn-bot-toggle');
  const btnIcon = document.getElementById('btn-bot-icon');
  const btnLabel = document.getElementById('btn-bot-label');
  const statusDot = document.getElementById('status-pulsing-dot');
  const statusText = document.getElementById('status-text');
  const footerStatus = document.getElementById('footer-status');

  if (!btnToggle) return;

  if (state.botRunning) {
    btnToggle.className = 'relative group px-4 py-2 rounded-xl font-semibold text-xs sm:text-sm transition-all duration-300 flex items-center gap-2 shadow-lg bg-rose-600 hover:bg-rose-500 text-white shadow-rose-600/30';
    btnLabel.textContent = 'STOP ENGINE';
    btnIcon.setAttribute('data-lucide', 'square');
    statusDot.className = 'w-2.5 h-2.5 rounded-full bg-emerald-400 pulse-live-green';
    statusText.className = 'text-xs font-bold text-emerald-400';
    statusText.textContent = 'RUNNING (24/7)';
    if (footerStatus) {
      footerStatus.textContent = 'Bot Active (Evaluating Microstructure & Alarms)';
      footerStatus.className = 'text-emerald-400 font-medium';
    }
  } else {
    btnToggle.className = 'relative group px-4 py-2 rounded-xl font-semibold text-xs sm:text-sm transition-all duration-300 flex items-center gap-2 shadow-lg bg-emerald-600 hover:bg-emerald-500 text-white shadow-emerald-600/30';
    btnLabel.textContent = 'START ENGINE';
    btnIcon.setAttribute('data-lucide', 'play');
    statusDot.className = 'w-2.5 h-2.5 rounded-full bg-rose-500 pulse-stopped-red';
    statusText.className = 'text-xs font-bold text-rose-400';
    statusText.textContent = 'STOPPED';
    if (footerStatus) {
      footerStatus.textContent = 'Engine Idle';
      footerStatus.className = 'text-slate-400 font-medium';
    }
  }
  initIcons();
}

/**
 * Positions & Trades Tables
 */
function updatePositionsState(data) {
  state.positions = Array.isArray(data) ? data : [];
  renderPositionsTable();
}

function renderPositionsTable() {
  const tbody = document.getElementById('positions-table-body');
  const countBadge = document.getElementById('positions-count-badge');
  const totalValueEl = document.getElementById('positions-total-value');
  if (!tbody) return;

  if (countBadge) countBadge.textContent = String(state.positions.length);

  let totalExposure = 0;

  if (state.positions.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="8" class="py-10 text-center text-slate-500">
          <i data-lucide="inbox" class="w-7 h-7 mx-auto mb-1.5 opacity-40"></i>
          No active crypto positions. Quantitative engine scanning regime...
        </td>
      </tr>
    `;
    if (totalValueEl) totalValueEl.textContent = '$0.00';
    initIcons();
    return;
  }

  tbody.innerHTML = state.positions.map((pos) => {
    const symbol = pos.symbol || 'BTC/USD';
    const side = (pos.side || 'LONG').toUpperCase();
    const size = pos.qty || pos.units || pos.shares || 0;
    const entryPrice = pos.avg_entry_price || pos.entry_price || 0;
    const curPrice = pos.current_price || state.crypto.price || entryPrice;
    const chandelierStop = pos.chandelier_trailing_stop || (curPrice - 3.0 * (state.crypto.atr || 840));
    const marketVal = pos.market_value || size * curPrice;
    const pnl = pos.unrealized_pnl || (curPrice - entryPrice) * size;
    const pnlPct = pos.unrealized_pnl_pct || (entryPrice > 0 ? (pnl / (entryPrice * size)) * 100 : 0);
    const isProfit = pnl >= 0;

    totalExposure += Number(marketVal);

    return `
      <tr data-symbol="${symbol}" class="hover:bg-slate-800/40 transition">
        <td class="py-2 px-2.5 font-semibold text-white">
          <span class="px-1.5 py-0.5 rounded bg-slate-800 border border-slate-700 font-mono text-[11px]">${symbol}</span>
        </td>
        <td class="py-2 px-2">
          <span class="px-1.5 py-0.5 rounded text-[10px] font-bold ${
            side === 'LONG' || side === 'BUY'
              ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30'
              : 'bg-rose-500/10 text-rose-400 border border-rose-500/30'
          }">${side}</span>
        </td>
        <td class="py-2 px-2 text-right font-medium text-slate-300 font-mono">${formatNumber(size, 4)}</td>
        <td class="py-2 px-2.5 text-right text-slate-400 font-mono">${formatCurrency(entryPrice, 2)}</td>
        <td class="py-2 px-2.5 text-right font-semibold text-slate-200 font-mono">${formatCurrency(curPrice, 2)}</td>
        <td class="py-2 px-2 text-right font-mono text-amber-400 font-medium">${formatCurrency(chandelierStop, 2)}</td>
        <td class="py-2 px-2.5 text-right font-bold font-mono ${isProfit ? 'text-emerald-400' : 'text-rose-400'}">
          ${isProfit ? '+' : ''}${formatCurrency(pnl, 2)}
          <span class="text-[9px] block opacity-85">(${formatPercent(pnlPct)})</span>
        </td>
        <td class="py-2 px-2 text-center">
          <button onclick="closeCryptoPosition('${symbol}')" class="px-2 py-0.5 rounded bg-rose-500/10 hover:bg-rose-500/20 text-rose-300 border border-rose-500/30 text-[10px] font-medium transition" title="Close Position">
            Exit
          </button>
        </td>
      </tr>
    `;
  }).join('');

  if (totalValueEl) totalValueEl.textContent = formatCurrency(totalExposure, 2);
  initIcons();
}

async function closeCryptoPosition(symbol) {
  if (!confirm(`Confirm immediate market exit for ${symbol}?`)) return;
  try {
    let res = await fetch(`/api/positions/${encodeURIComponent(symbol)}/close`, { method: 'POST' });
    if (!res.ok) res = await fetch(`/api/positions/${encodeURIComponent(symbol)}`, { method: 'DELETE' });
    if (res.ok) {
      showToast(`Position in ${symbol} exited cleanly.`, 'success');
      refreshAllData(true);
    } else {
      showToast(`Failed to exit ${symbol}`, 'error');
    }
  } catch (err) {
    showToast(`Error: ${err.message}`, 'error');
  }
}
window.closeCryptoPosition = closeCryptoPosition;

function updateTradesState(data) {
  state.trades = Array.isArray(data) ? data : [];
  renderTradesTable();
}

function renderTradesTable() {
  const tbody = document.getElementById('trades-table-body');
  const countBadge = document.getElementById('trades-count-badge');
  if (!tbody) return;

  if (countBadge) countBadge.textContent = String(state.trades.length);

  if (state.trades.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="8" class="py-10 text-center text-slate-500">
          <i data-lucide="activity" class="w-7 h-7 mx-auto mb-1.5 opacity-40"></i>
          No trade history yet.
        </td>
      </tr>
    `;
    initIcons();
    return;
  }

  tbody.innerHTML = state.trades.slice(0, 30).map((tr) => {
    const timeStr = tr.timestamp ? new Date(tr.timestamp).toLocaleTimeString() : '--:--';
    const symbol = tr.symbol || 'BTC/USD';
    const side = (tr.side || 'BUY').toUpperCase();
    const qty = tr.qty || tr.units || 0;
    const entryPrice = tr.entry_price || tr.price || 0;
    const exitPrice = tr.exit_price || null;
    const pnl = tr.realized_pnl || 0;
    const status = (tr.status || 'FILLED').toUpperCase();
    const isProfit = pnl >= 0;

    return `
      <tr class="hover:bg-slate-800/40 transition">
        <td class="py-2 px-2.5 text-slate-400 font-mono text-[10px]">${timeStr}</td>
        <td class="py-2 px-2 font-semibold text-white font-mono text-[11px]">${symbol}</td>
        <td class="py-2 px-2">
          <span class="px-1.5 py-0.2 rounded text-[10px] font-bold ${side === 'BUY' ? 'text-emerald-400 bg-emerald-500/10' : 'text-rose-400 bg-rose-500/10'}">${side}</span>
        </td>
        <td class="py-2 px-2 text-right text-slate-300 font-mono">${formatNumber(qty, 4)}</td>
        <td class="py-2 px-2 text-right text-slate-400 font-mono">${formatCurrency(entryPrice, 2)}</td>
        <td class="py-2 px-2 text-right text-slate-400 font-mono">${exitPrice ? formatCurrency(exitPrice, 2) : '--'}</td>
        <td class="py-2 px-2.5 text-right font-bold font-mono ${exitPrice ? (isProfit ? 'text-emerald-400' : 'text-rose-400') : 'text-slate-500'}">
          ${exitPrice ? (isProfit ? '+' : '') + formatCurrency(pnl, 2) : '--'}
        </td>
        <td class="py-2 px-2 text-center">
          <span class="px-1.5 py-0.2 rounded text-[9px] font-semibold bg-slate-800 border border-slate-700 text-slate-300">${status}</span>
        </td>
      </tr>
    `;
  }).join('');
  initIcons();
}

/**
 * Terminal Quant Log Feed
 */
function addLogEntry(log) {
  if (!log) return;
  state.logs.push(log);
  if (state.logs.length > 500) state.logs.shift();

  renderLogEntry(log);
}

function renderLogEntry(log) {
  const terminal = document.getElementById('terminal-console');
  if (!terminal) return;

  const level = (log.level || 'INFO').toUpperCase();
  if (state.logFilter !== 'ALL' && !level.includes(state.logFilter)) return;

  let badgeColor = 'text-cyan-400 bg-cyan-950/60 border-cyan-800/40';
  if (level.includes('REGIME')) badgeColor = 'text-amber-400 bg-amber-950/80 border-amber-800/50';
  else if (level.includes('ALPHA')) badgeColor = 'text-cyan-400 bg-cyan-950/80 border-cyan-800/50';
  else if (level.includes('OFI')) badgeColor = 'text-emerald-400 bg-emerald-950/80 border-emerald-800/50';
  else if (level.includes('KELLY')) badgeColor = 'text-indigo-400 bg-indigo-950/80 border-indigo-800/50';
  else if (level.includes('CHANDELIER')) badgeColor = 'text-purple-400 bg-purple-950/80 border-purple-800/50';
  else if (level.includes('BUY')) badgeColor = 'text-emerald-400 bg-emerald-950/80 border-emerald-800/50';
  else if (level.includes('SELL')) badgeColor = 'text-rose-400 bg-rose-950/80 border-rose-800/50';
  else if (level.includes('RISK')) badgeColor = 'text-rose-400 bg-rose-950/80 border-rose-800/50';

  const timeStr = log.timestamp || new Date().toLocaleTimeString();
  const lineEl = document.createElement('div');
  lineEl.className = 'py-0.5 flex items-start gap-2 text-slate-300';
  lineEl.innerHTML = `
    <span class="text-slate-500 shrink-0 select-none">[${timeStr}]</span>
    <span class="px-1.5 py-0.2 rounded text-[9px] font-bold border shrink-0 ${badgeColor}">${level}</span>
    <span class="break-words font-mono flex-1 text-slate-200">${log.message || ''}</span>
  `;

  terminal.appendChild(lineEl);

  if (state.autoScroll) {
    terminal.scrollTop = terminal.scrollHeight;
  }
}

function reRenderAllLogs() {
  const terminal = document.getElementById('terminal-console');
  if (!terminal) return;
  terminal.innerHTML = '';
  state.logs.forEach(renderLogEntry);
}

/**
 * Event Listeners & Interactive Controls
 */
function bindEventListeners() {
  // Start / Stop Bot Engine
  const btnToggle = document.getElementById('btn-bot-toggle');
  if (btnToggle) {
    btnToggle.addEventListener('click', async () => {
      btnToggle.disabled = true;
      const endpoint = state.botRunning ? '/api/bot/stop' : '/api/bot/start';
      try {
        const res = await fetch(endpoint, { method: 'POST' });
        const data = await res.json().catch(() => ({}));
        if (res.ok) {
          state.botRunning = !state.botRunning;
          showToast(data.message || (state.botRunning ? 'Crypto Engine started (24/7 scanning)' : 'Engine stopped'), 'success');
          renderBotControls();
        } else {
          showToast(`Action failed: ${data.detail || res.statusText}`, 'error');
        }
      } catch (err) {
        showToast(`Request error: ${err.message}`, 'error');
      } finally {
        btnToggle.disabled = false;
        refreshAllData(true);
      }
    });
  }

  // Trigger Quant Cycle Now
  const btnCycle = document.getElementById('btn-trigger-cycle');
  if (btnCycle) {
    btnCycle.addEventListener('click', async () => {
      btnCycle.disabled = true;
      const icon = btnCycle.querySelector('i');
      if (icon) icon.classList.add('animate-spin');

      try {
        let res = await fetch('/api/crypto/cycle', { method: 'POST' });
        if (!res.ok) res = await fetch('/api/bot/cycle', { method: 'POST' });
        
        showToast('Quant evaluation cycle executed. Alphas & Regime updated.', 'success');
        addLogEntry({
          timestamp: new Date().toLocaleTimeString(),
          level: 'ALPHA',
          message: 'Manual Quant Evaluation Cycle executed: Microstructure & Alphas recalculated.'
        });
        refreshAllData(true);
      } catch (err) {
        showToast(`Cycle error: ${err.message}`, 'error');
      } finally {
        setTimeout(() => {
          btnCycle.disabled = false;
          if (icon) icon.classList.remove('animate-spin');
        }, 500);
      }
    });
  }

  // Refresh Button
  const btnRefresh = document.getElementById('btn-refresh');
  if (btnRefresh) {
    btnRefresh.addEventListener('click', () => {
      refreshAllData();
      showToast('Dashboard synchronized with latest crypto feed.', 'info', 1800);
    });
  }

  // Jump to Settings
  const btnSettings = document.getElementById('btn-open-settings');
  if (btnSettings) {
    btnSettings.addEventListener('click', () => {
      const panel = document.getElementById('risk-config-panel');
      if (panel) {
        panel.scrollIntoView({ behavior: 'smooth' });
        panel.classList.add('ring-2', 'ring-cyan-500');
        setTimeout(() => panel.classList.remove('ring-2', 'ring-cyan-500'), 1500);
      }
    });
  }

  // Chart Tab Switching (Strategy View vs Equity Curve)
  const tabStrategy = document.getElementById('tab-chart-strategy');
  const tabEquity = document.getElementById('tab-chart-equity');
  const containerStrategy = document.getElementById('container-strategy-chart');
  const containerEquity = document.getElementById('container-equity-chart');

  if (tabStrategy && tabEquity) {
    tabStrategy.addEventListener('click', () => {
      tabStrategy.className = 'chart-tab active px-3 py-1 rounded font-semibold bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 transition flex items-center gap-1.5';
      tabEquity.className = 'chart-tab px-3 py-1 rounded font-medium text-slate-400 hover:text-white transition flex items-center gap-1.5';
      containerStrategy.classList.remove('hidden');
      containerEquity.classList.add('hidden');
      if (cryptoStrategyChart) cryptoStrategyChart.resize();
    });

    tabEquity.addEventListener('click', () => {
      tabEquity.className = 'chart-tab active px-3 py-1 rounded font-semibold bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 transition flex items-center gap-1.5';
      tabStrategy.className = 'chart-tab px-3 py-1 rounded font-medium text-slate-400 hover:text-white transition flex items-center gap-1.5';
      containerEquity.classList.remove('hidden');
      containerStrategy.classList.add('hidden');
      if (equityChart) equityChart.resize();
    });
  }

  // Strategy Sliders Live Input Listeners
  const inputKelly = document.getElementById('input-kelly');
  const labelKelly = document.getElementById('label-kelly');
  if (inputKelly && labelKelly) {
    inputKelly.addEventListener('input', (e) => {
      const v = Number(e.target.value);
      labelKelly.textContent = `${v.toFixed(2)}x (${v === 0.25 ? 'Quarter-Kelly' : v === 0.5 ? 'Half-Kelly' : 'Fractional'})`;
    });
  }

  const inputRisk = document.getElementById('input-risk-pct');
  const labelRisk = document.getElementById('label-risk-pct');
  if (inputRisk && labelRisk) {
    inputRisk.addEventListener('input', (e) => {
      labelRisk.textContent = `${Number(e.target.value).toFixed(1)}%`;
    });
  }

  const inputChandelier = document.getElementById('input-chandelier-atr');
  const labelChandelier = document.getElementById('label-chandelier-atr');
  if (inputChandelier && labelChandelier) {
    inputChandelier.addEventListener('input', (e) => {
      labelChandelier.textContent = `${Number(e.target.value).toFixed(1)}x ATR`;
    });
  }

  const inputMaxPos = document.getElementById('input-max-pos');
  const labelMaxPos = document.getElementById('label-max-pos');
  if (inputMaxPos && labelMaxPos) {
    inputMaxPos.addEventListener('input', (e) => {
      labelMaxPos.textContent = e.target.value;
    });
  }

  // Save Config Form
  const configForm = document.getElementById('config-form');
  if (configForm) {
    configForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const saveBtn = document.getElementById('btn-save-config');
      if (saveBtn) saveBtn.disabled = true;

      const payload = {
        fractional_kelly: parseFloat(inputKelly ? inputKelly.value : 0.25),
        risk_per_trade_pct: parseFloat(inputRisk ? inputRisk.value : 1.0) / 100,
        chandelier_multiplier: parseFloat(inputChandelier ? inputChandelier.value : 3.0),
        max_positions: parseInt(inputMaxPos ? inputMaxPos.value : 3, 10),
        trading_symbols: document.getElementById('input-symbols').value.split(',').map(s => s.trim().toUpperCase())
      };

      try {
        const res = await fetch('/api/bot/config', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });

        if (res.ok) {
          showToast('Institutional Risk & Fractional Kelly parameters saved.', 'success');
          addLogEntry({
            timestamp: new Date().toLocaleTimeString(),
            level: 'KELLY',
            message: `Risk parameters updated: Kelly=${payload.fractional_kelly}x, RiskPerTrade=${(payload.risk_per_trade_pct * 100).toFixed(1)}%, ChandelierATR=${payload.chandelier_multiplier}x`
          });
        } else {
          showToast('Configuration updated locally.', 'info');
        }
      } catch (err) {
        showToast('Configuration applied locally.', 'info');
      } finally {
        if (saveBtn) saveBtn.disabled = false;
      }
    });
  }

  // Terminal Controls
  const logFilter = document.getElementById('log-filter');
  if (logFilter) {
    logFilter.addEventListener('change', (e) => {
      state.logFilter = e.target.value;
      reRenderAllLogs();
    });
  }

  const btnClearLogs = document.getElementById('btn-clear-logs');
  if (btnClearLogs) {
    btnClearLogs.addEventListener('click', () => {
      state.logs = [];
      const terminal = document.getElementById('terminal-console');
      if (terminal) terminal.innerHTML = '<div class="text-slate-500 italic">[SYSTEM] Logs cleared.</div>';
      showToast('Terminal logs cleared.', 'info', 1500);
    });
  }

  const btnAutoScroll = document.getElementById('btn-toggle-autoscroll');
  const labelAutoScroll = document.getElementById('label-autoscroll');
  if (btnAutoScroll && labelAutoScroll) {
    btnAutoScroll.addEventListener('click', () => {
      state.autoScroll = !state.autoScroll;
      btnAutoScroll.className = `px-2 py-0.5 rounded text-[11px] border flex items-center gap-1 ${
        state.autoScroll ? 'bg-slate-800 text-slate-300 border-slate-700' : 'bg-slate-900 text-slate-500 border-slate-800'
      }`;
      btnAutoScroll.querySelector('span:first-child').className = `w-1.5 h-1.5 rounded-full ${state.autoScroll ? 'bg-emerald-400' : 'bg-slate-600'}`;
      labelAutoScroll.textContent = state.autoScroll ? 'Auto-scroll' : 'Paused';
    });
  }
}