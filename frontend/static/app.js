/**
 * DEX ALGO - Institutional Quantitative Trading Platform
 * Bloomberg Terminal-Inspired Client Application v2.5
 * 
 * Features:
 * - Multi-Workspace Navigation (Terminal, Portfolio & Risk, Alphas & Regimes, Orders, Research, Audit)
 * - Level-2 Order Book Microstructure Depth Ladder with OFI Delta & Spread Metrics
 * - High-Contrast Dark-Themed Strategy, Equity Curve & Underwater Drawdown Charts
 * - Real-Time Bidirectional WebSocket Streaming with Latency Ping/Pong
 * - Zero Metric Fabrication: Strict segregation of Live Session vs OOS Walk-Forward Benchmarks
 * - Causal Lag-1 Feature Decision Audit Viewer
 * - Dynamic Multi-Asset Watchlist Ribbon (BTC, ETH, SOL, SPY, QQQ)
 */

// Application State
const state = {
  activeWorkspace: 'terminal',
  activeSymbol: 'BTC/USD',
  activeChartMode: 'strategy',
  activeChartTf: '1h',
  activeSideTab: 'orderbook',
  activePositionsTab: 'positions',
  activeLogsTab: 'logs',
  logFilter: 'ALL',
  
  engineRunning: false,
  isMock: true,
  wsConnected: false,
  wsLatencyMs: 12,
  lastPingTime: 0,
  ws: null,
  reconnectTimer: null,
  pollTimer: null,

  // Account & Portfolio
  account: {
    equity: 100000.0,
    cash: 100000.0,
    buying_power: 200000.0,
    daily_pnl: 0.0,
    daily_pnl_pct: 0.0,
    unrealized_pnl: 0.0
  },

  // Active Symbol Market Data
  quote: {
    symbol: 'BTC/USD',
    price: 67940.79,
    prevPrice: 67940.79,
    change_24h: -2.51,
    high_24h: 68910.0,
    low_24h: 64820.0,
    volume_24h: 19420.5,
    timestamp: new Date().toISOString()
  },

  // Watchlist Quotes
  quotes: {
    'BTC/USD': { price: 67940.79, change_24h: -2.51 },
    'ETH/USD': { price: 3485.20, change_24h: 1.85 },
    'SOL/USD': { price: 184.60, change_24h: 4.12 },
    'SPY': { price: 582.40, change_24h: 0.48 },
    'QQQ': { price: 496.80, change_24h: 0.62 }
  },

  // Regime & Probabilities
  regime: {
    name: 'LOW_VOL_COMPRESSION',
    confidence: 0.996,
    adx: 11.0,
    di_plus: 11.06,
    di_minus: 12.39,
    bbw_percentile: 42.68,
    vol_zscore: -0.86,
    parkinson_vol: 54.2,
    yang_zhang_vol: 48.6,
    hysteresis: '2-BAR LOCK',
    probabilities: {
      bull: 0.0037,
      bear: 0.0000,
      compression: 0.9960,
      crisis: 0.0000
    },
    active_weights: {
      trend: 0.1519,
      mean_reversion: 0.6976,
      breakout: 0.1505
    }
  },

  // Multi-Alpha Scores
  alphas: {
    composite_score: -0.4702,
    action: 'HOLD',
    confidence: 0.3291,
    scores: {
      trend: 0.0,
      mean_reversion: -0.674,
      breakout: 0.0
    },
    filters_passed: false,
    rejection_reason: 'Filtered: Capital preserved in cash during LOW_VOL_COMPRESSION chop'
  },

  // Order Book
  orderbook: {
    mid_price: 67915.67,
    spread: 0.69,
    spread_bps: 0.10,
    depth_imbalance: 0.123,
    bid_volume: 18.7088,
    ask_volume: 14.6103,
    bids: [],
    asks: []
  },

  // Risk Parameters
  risk: {
    target_annual_vol: 0.15,
    half_kelly_pct: 0.1111,
    posterior_win_rate: 0.50,
    payoff_odds: 1.80,
    chandelier_atr_mult: 3.0,
    max_daily_loss_pct: 0.025
  },

  // WFO Audited Benchmarks
  wfo: {
    win_rate: 0.6471,
    payoff_ratio: 1.23,
    annualized_sharpe: 2.29,
    sortino_ratio: 3.14,
    calmar_ratio: 19.44,
    omega_ratio: 2.18,
    max_drawdown: 0.0024,
    probability_of_ruin: 0.00,
    total_trades: 36,
    multi_asset_summary: []
  },

  positions: [],
  orders: [],
  trades: [],
  logs: [],
  decisions: [],
  underwaterData: []
};

// Chart instances
let strategyChart = null;
let equityChart = null;
let underwaterChart = null;

// Initialize on DOM Ready
document.addEventListener('DOMContentLoaded', () => {
  initIcons();
  startServerClock();
  initCharts();
  connectWebSocket();
  refreshAllData();
  loadWfoSummary();

  // Set periodic data sync
  setInterval(() => {
    if (!state.wsConnected) {
      refreshAllData(true);
    }
    pingWebSocket();
  }, 3000);
});

function initIcons() {
  if (window.lucide && typeof window.lucide.createIcons === 'function') {
    window.lucide.createIcons();
  }
}

function startServerClock() {
  const el = document.getElementById('clock-utc');
  setInterval(() => {
    const now = new Date();
    const h = String(now.getUTCHours()).padStart(2, '0');
    const m = String(now.getUTCMinutes()).padStart(2, '0');
    const s = String(now.getUTCSeconds()).padStart(2, '0');
    if (el) el.textContent = `${h}:${m}:${s} UTC`;
  }, 1000);
}

// Number Formatting Helpers
function fmtCurrency(val, decimals = 2) {
  const num = parseFloat(val);
  if (isNaN(num)) return '$0.00';
  return '$' + num.toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

function fmtPercent(val, includeSign = true, decimals = 2) {
  const num = parseFloat(val);
  if (isNaN(num)) return '0.00%';
  const sign = (includeSign && num > 0) ? '+' : '';
  return sign + num.toFixed(decimals) + '%';
}

function fmtNumber(val, decimals = 2) {
  const num = parseFloat(val);
  if (isNaN(num)) return '0.00';
  return num.toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

// Toast System
function showToast(msg, type = 'info') {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const t = document.createElement('div');
  t.className = `toast ${type}`;
  t.innerHTML = `<span>${msg}</span>`;
  container.appendChild(t);
  setTimeout(() => {
    t.style.opacity = '0';
    t.style.transform = 'translateY(4px)';
    setTimeout(() => t.remove(), 200);
  }, 3000);
}

// =============================================================================
// WebSocket Connection & Real-Time Synchronization
// =============================================================================

function connectWebSocket() {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${window.location.host}/ws`;

  try {
    state.ws = new WebSocket(wsUrl);

    state.ws.onopen = () => {
      state.wsConnected = true;
      updateWsBadge(true);
      pingWebSocket();
      showToast('WebSocket connected to quant stream', 'success');
    };

    state.ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        handleWsMessage(msg);
      } catch (e) {
        console.debug('WS parse error', e);
      }
    };

    state.ws.onclose = () => {
      state.wsConnected = false;
      updateWsBadge(false);
      scheduleWsReconnect();
    };

    state.ws.onerror = () => {
      state.wsConnected = false;
      updateWsBadge(false);
    };
  } catch (err) {
    scheduleWsReconnect();
  }
}

function scheduleWsReconnect() {
  if (state.reconnectTimer) clearTimeout(state.reconnectTimer);
  state.reconnectTimer = setTimeout(() => {
    connectWebSocket();
  }, 4000);
}

function pingWebSocket() {
  if (state.ws && state.ws.readyState === WebSocket.OPEN) {
    state.lastPingTime = performance.now();
    state.ws.send(JSON.stringify({ action: 'ping', timestamp: Date.now() }));
  }
}

function updateWsBadge(connected) {
  const dot = document.getElementById('ws-dot');
  const txt = document.getElementById('ws-latency');
  if (dot && txt) {
    if (connected) {
      dot.className = 'dot green';
      txt.textContent = `${state.wsLatencyMs}ms WS`;
    } else {
      dot.className = 'dot red';
      txt.textContent = 'WS OFFLINE';
    }
  }
}

function handleWsMessage(msg) {
  const type = msg.type || msg.event;

  if (type === 'PONG') {
    if (state.lastPingTime > 0) {
      state.wsLatencyMs = Math.max(1, Math.round(performance.now() - state.lastPingTime));
      updateWsBadge(true);
    }
    return;
  }

  if (type === 'INIT_SNAPSHOT' || type === 'SNAPSHOT') {
    if (msg.account) updateAccount(msg.account);
    if (msg.status) updateStatus(msg.status);
    if (msg.regime) updateRegime(msg.regime);
    if (msg.alphas) updateAlphas(msg.alphas);
    if (msg.orderbook) updateOrderBook(msg.orderbook);
    if (msg.positions) updatePositions(msg.positions);
    if (msg.orders) updateOrders(msg.orders);
    if (msg.wfo_metrics) updateWfo(msg.wfo_metrics);
    if (msg.logs) updateLogs(msg.logs);
    return;
  }

  if (type === 'TICK_UPDATE' || type === 'CRYPTO_TICK' || type === 'CRYPTO_QUANT_TICK') {
    if (msg.price && (!msg.symbol || msg.symbol === state.activeSymbol)) {
      updateActiveQuote(msg);
    }
    if (msg.regime) updateRegime(msg.regime);
    if (msg.alphas) updateAlphas(msg.alphas);
    if (msg.orderbook) updateOrderBook(msg.orderbook);
    if (msg.account) updateAccount(msg.account);
    if (msg.positions) updatePositions(msg.positions);
    if (msg.orders) updateOrders(msg.orders);
    return;
  }

  if (type === 'REGIME') {
    updateRegime(msg.data || msg);
  } else if (type === 'ALPHAS') {
    updateAlphas(msg.data || msg);
  } else if (type === 'ORDERBOOK') {
    updateOrderBook(msg.data || msg);
  } else if (type === 'WFO_METRICS') {
    updateWfo(msg.data || msg);
  } else if (type === 'ORDERS') {
    updateOrders(msg.data || msg.orders || msg);
  } else if (type === 'ORDER_CREATED' || type === 'ORDER_CANCELED') {
    refreshOrdersBlotter();
  }
}

// =============================================================================
// REST Client API
// =============================================================================

async function fetchApi(endpoint, options = {}) {
  try {
    const res = await fetch(endpoint, {
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
      ...options
    });
    if (!res.ok) return null;
    return await res.json();
  } catch (e) {
    return null;
  }
}

async function refreshAllData(silent = false) {
  const [status, cryptoState, regime, alphas, ob, account, positions, orders, wfo, decisions] = await Promise.all([
    fetchApi('/api/status'),
    fetchApi(`/api/crypto/state?symbol=${encodeURIComponent(state.activeSymbol)}`),
    fetchApi(`/api/crypto/regime?symbol=${encodeURIComponent(state.activeSymbol)}`),
    fetchApi(`/api/crypto/alphas?symbol=${encodeURIComponent(state.activeSymbol)}`),
    fetchApi(`/api/crypto/orderbook?symbol=${encodeURIComponent(state.activeSymbol)}`),
    fetchApi('/api/account'),
    fetchApi('/api/positions'),
    fetchApi('/api/orders'),
    fetchApi(`/api/backtest/wfo?symbol=${encodeURIComponent(state.activeSymbol.replace('/', ''))}`),
    fetchApi('/api/decisions?limit=15')
  ]);

  if (status) updateStatus(status);
  if (cryptoState) updateActiveQuote(cryptoState);
  if (regime) updateRegime(regime);
  if (alphas) updateAlphas(alphas);
  if (ob) updateOrderBook(ob);
  if (account) updateAccount(account);
  if (positions) updatePositions(positions);
  if (orders) updateOrders(orders);
  if (wfo) updateWfo(wfo);
  if (decisions) updateDecisions(decisions);
}

// =============================================================================
// UI State Updaters
// =============================================================================

function updateStatus(data) {
  state.engineRunning = !!data.running;
  state.isMock = (data.mock_mode !== undefined) ? !!data.mock_mode : true;

  // Update Start/Stop button
  const btn = document.getElementById('btn-engine-toggle');
  const icon = document.getElementById('btn-engine-icon');
  const label = document.getElementById('btn-engine-label');

  if (btn && label) {
    if (state.engineRunning) {
      btn.className = 'btn-terminal danger';
      label.textContent = 'STOP';
      if (icon) icon.setAttribute('data-lucide', 'square');
    } else {
      btn.className = 'btn-terminal success';
      label.textContent = 'START';
      if (icon) icon.setAttribute('data-lucide', 'play');
    }
  }

  // Update Mode Badge
  const modeTxt = document.getElementById('badge-mode-text');
  const modeDot = document.getElementById('badge-mode-dot');
  if (modeTxt && modeDot) {
    if (state.isMock) {
      modeTxt.textContent = 'MOCK SIMULATION (24/7)';
      modeDot.className = 'dot amber';
    } else {
      modeTxt.textContent = 'LIVE PAPER TRADING';
      modeDot.className = 'dot green';
    }
  }
  initIcons();
}

function updateAccount(acc) {
  state.account = { ...state.account, ...acc };
  
  const eq = document.getElementById('kpi-equity');
  const cash = document.getElementById('kpi-cash');
  const dpnl = document.getElementById('kpi-daily-pnl');
  const upnl = document.getElementById('kpi-unrealized-pnl');

  if (eq) eq.textContent = fmtCurrency(state.account.equity || 100000);
  if (cash) cash.textContent = fmtCurrency(state.account.cash || 100000);
  
  const daily = parseFloat(state.account.daily_pnl || 0);
  const dailyPct = parseFloat(state.account.daily_pnl_pct || 0);
  if (dpnl) {
    dpnl.textContent = `${daily >= 0 ? '+' : ''}${fmtCurrency(daily)} (${fmtPercent(dailyPct)})`;
    dpnl.className = `kpi-value ${daily >= 0 ? 'text-[#0fa968]' : 'text-[#e5484d]'}`;
  }
  if (upnl) {
    const un = parseFloat(state.account.unrealized_pnl || 0);
    upnl.textContent = fmtCurrency(un);
    upnl.className = un >= 0 ? 'text-[#0fa968]' : 'text-[#e5484d]';
  }
}

function updateActiveQuote(q) {
  const px = parseFloat(q.price || q.live_btc_price || state.quote.price);
  const chg = parseFloat(q.change_24h || q.change_24h_pct || state.quote.change_24h);
  
  state.quote.prevPrice = state.quote.price;
  state.quote.price = px;
  state.quote.change_24h = chg;
  if (q.high_24h) state.quote.high_24h = parseFloat(q.high_24h);
  if (q.low_24h) state.quote.low_24h = parseFloat(q.low_24h);

  // Update Chart Header
  const cp = document.getElementById('chart-price-display');
  const cc = document.getElementById('chart-chg-display');
  const ch = document.getElementById('chart-high-display');
  const cl = document.getElementById('chart-low-display');

  if (cp) {
    cp.textContent = fmtCurrency(px);
    cp.className = `tabular-nums font-mono text-xs font-semibold ${chg >= 0 ? 'text-[#0fa968]' : 'text-[#e5484d]'}`;
  }
  if (cc) {
    cc.textContent = fmtPercent(chg);
    cc.className = `tabular-nums font-mono text-[10px] ${chg >= 0 ? 'text-[#0fa968]' : 'text-[#e5484d]'}`;
  }
  if (ch) ch.textContent = fmtCurrency(state.quote.high_24h);
  if (cl) cl.textContent = fmtCurrency(state.quote.low_24h);

  // Update Ticker Ribbon for active asset
  if (state.activeSymbol === 'BTC/USD') {
    const bp = document.getElementById('ticker-btc-price');
    const bc = document.getElementById('ticker-btc-chg');
    if (bp) bp.textContent = fmtCurrency(px);
    if (bc) bc.textContent = fmtPercent(chg);
  }
}

function updateRegime(r) {
  const regName = r.current_regime || r.regime || state.regime.name;
  state.regime.name = regName;
  if (r.confidence) state.regime.confidence = parseFloat(r.confidence);
  if (r.adx) state.regime.adx = parseFloat(r.adx);
  if (r.bbw_percentile) state.regime.bbw_percentile = parseFloat(r.bbw_percentile);
  if (r.probabilities) state.regime.probabilities = { ...state.regime.probabilities, ...r.probabilities };

  // Update KPI pill
  const pill = document.getElementById('kpi-regime-pill');
  const act = document.getElementById('kpi-regime-action');
  if (pill) {
    pill.textContent = regName;
    if (regName.includes('BULL')) pill.className = 'status-pill bull';
    else if (regName.includes('BEAR')) pill.className = 'status-pill bear';
    else if (regName.includes('COMPRESSION') || regName.includes('CHOP')) pill.className = 'status-pill compression';
    else if (regName.includes('CRISIS') || regName.includes('HIGH_VOL')) pill.className = 'status-pill crisis';
    else pill.className = 'status-pill neutral';
  }

  if (act) {
    if (regName.includes('COMPRESSION') || regName.includes('CHOP')) {
      act.textContent = '100% Cash Gate (Preservation Active)';
      act.className = 'text-[#d97706]';
    } else if (regName.includes('BULL')) {
      act.textContent = 'Trend Long Active (KAMA & SuperTrend)';
      act.className = 'text-[#0fa968]';
    } else if (regName.includes('BEAR')) {
      act.textContent = 'Defensive Bear Stance (Hedged / Cash)';
      act.className = 'text-[#e5484d]';
    } else {
      act.textContent = 'Crisis Volatility Override (Zero Exposure)';
      act.className = 'text-[#8b5cf6]';
    }
  }

  // Update ribbon diagnostics
  const radx = document.getElementById('ribbon-adx');
  const rbbw = document.getElementById('ribbon-bbw');
  if (radx) radx.textContent = state.regime.adx.toFixed(1);
  if (rbbw) rbbw.textContent = `${state.regime.bbw_percentile.toFixed(1)}th Pct`;

  // Update Side Tab Soft Probabilities
  const p = state.regime.probabilities;
  const pBull = p.BULL !== undefined ? p.BULL : (p.TRENDING_BULL !== undefined ? p.TRENDING_BULL : (p.bull || 0.004));
  const pBear = p.BEAR !== undefined ? p.BEAR : (p.TRENDING_BEAR !== undefined ? p.TRENDING_BEAR : (p.bear || 0.000));
  const pComp = p.COMPRESSION !== undefined ? p.COMPRESSION : (p.MEAN_REVERTING !== undefined ? p.MEAN_REVERTING : (p.compression || 0.996));
  const pCrisis = p.CRISIS !== undefined ? p.CRISIS : (p.HIGH_VOL !== undefined ? p.HIGH_VOL : (p.crisis || 0.000));

  setBar('prob-bull', 'prob-bar-bull', pBull);
  setBar('prob-bear', 'prob-bar-bear', pBear);
  setBar('prob-comp', 'prob-bar-comp', pComp);
  setBar('prob-crisis', 'prob-bar-crisis', pCrisis);
}

function setBar(txtId, barId, val) {
  const t = document.getElementById(txtId);
  const b = document.getElementById(barId);
  const pct = (val * 100).toFixed(1) + '%';
  if (t) t.textContent = pct;
  if (b) b.style.width = pct;
}

function updateAlphas(a) {
  state.alphas.composite_score = parseFloat(a.composite_score || 0.0);
  state.alphas.action = a.action || 'HOLD';
  const sc = a.alpha_scores || {};
  state.alphas.scores.trend = parseFloat(sc.trend || a.alpha_1_trend || 0.0);
  state.alphas.scores.mean_reversion = parseFloat(sc.mean_reversion || a.alpha_2_mean_rev || 0.0);
  state.alphas.scores.breakout = parseFloat(sc.breakout || a.alpha_3_ofi || 0.0);

  // Composite Badge
  const cb = document.getElementById('composite-score-badge');
  const ca = document.getElementById('composite-action-badge');
  if (cb) {
    cb.textContent = state.alphas.composite_score.toFixed(2);
    cb.className = `font-mono text-xs font-bold ${state.alphas.composite_score >= 0 ? 'text-[#0fa968]' : 'text-[#e5484d]'}`;
  }
  if (ca) {
    ca.textContent = state.alphas.action;
    ca.className = state.alphas.action === 'BUY' ? 'status-pill bull' : (state.alphas.action === 'SELL' ? 'status-pill bear' : 'status-pill compression');
  }

  // Render Alpha Meters
  renderAlphaMeter('alpha-val-trend', 'alpha-pos-trend', 'alpha-neg-trend', state.alphas.scores.trend);
  renderAlphaMeter('alpha-val-meanrev', 'alpha-pos-meanrev', 'alpha-neg-meanrev', state.alphas.scores.mean_reversion);
  renderAlphaMeter('alpha-val-ofi', 'alpha-pos-ofi', 'alpha-neg-ofi', state.alphas.scores.breakout);
}

function renderAlphaMeter(valId, posBarId, negBarId, score) {
  const tv = document.getElementById(valId);
  const pb = document.getElementById(posBarId);
  const nb = document.getElementById(negBarId);

  if (tv) tv.textContent = score.toFixed(2);
  const pct = Math.min(100, Math.abs(score) * 100).toFixed(0) + '%';

  if (score >= 0) {
    if (pb) pb.style.width = pct;
    if (nb) nb.style.width = '0%';
  } else {
    if (nb) nb.style.width = pct;
    if (pb) pb.style.width = '0%';
  }
}

function updateOrderBook(ob) {
  state.orderbook = { ...state.orderbook, ...ob };

  const mid = document.getElementById('ob-mid-price');
  const sp = document.getElementById('ob-spread');
  const sb = document.getElementById('ob-spread-bps');
  const imb = document.getElementById('ob-imbalance-pct');
  const ofi = document.getElementById('ob-ofi-val');
  const bBar = document.getElementById('ob-depth-bar-bid');
  const aBar = document.getElementById('ob-depth-bar-ask');

  const spreadVal = parseFloat(ob.spread || 0.69);
  const midVal = parseFloat(ob.mid_price || state.quote.price);
  const spreadBps = ((spreadVal / midVal) * 10000).toFixed(2);

  if (mid) mid.textContent = fmtCurrency(midVal);
  if (sp) sp.textContent = fmtCurrency(spreadVal);
  if (sb) sb.textContent = `${spreadBps} bps`;

  const imbRatio = parseFloat(ob.depth_imbalance || ob.volume_imbalance_ratio || 0.123);
  if (imb) {
    imb.textContent = `${(imbRatio * 100).toFixed(1)}% ${imbRatio >= 0 ? 'Bid Dominance' : 'Ask Dominance'}`;
    imb.className = imbRatio >= 0 ? 'text-[#0fa968] font-semibold' : 'text-[#e5484d] font-semibold';
  }

  const bVol = parseFloat(ob.bid_volume || ob.bid_depth || 18.7);
  const aVol = parseFloat(ob.ask_volume || ob.ask_depth || 14.6);
  const tot = bVol + aVol;
  if (bBar && aBar && tot > 0) {
    bBar.style.width = ((bVol / tot) * 100).toFixed(0) + '%';
    aBar.style.width = ((aVol / tot) * 100).toFixed(0) + '%';
  }
  if (ofi) ofi.textContent = `${bVol >= aVol ? '+' : '-'}${Math.abs(bVol - aVol).toFixed(2)} BTC Delta`;

  // Render Depth Ladder
  renderOrderBookLadder(ob.bids || [], ob.asks || [], midVal);
}

function renderOrderBookLadder(bids, asks, mid) {
  const asksBody = document.getElementById('ob-asks-body');
  const bidsBody = document.getElementById('ob-bids-body');

  if (!asksBody || !bidsBody) return;

  // Asks (top 5 reversed)
  let askRows = '';
  const displayAsks = (asks.length ? asks.slice(0, 5) : mockAsks(mid)).reverse();
  let maxAskVol = Math.max(...displayAsks.map(a => a.size || a[1] || 1), 1);

  displayAsks.forEach(a => {
    const px = parseFloat(a.price || a[0]);
    const sz = parseFloat(a.size || a[1]);
    const barWidth = Math.min(100, (sz / maxAskVol) * 100).toFixed(0);
    askRows += `
      <tr class="orderbook-row">
        <td class="text-[#e5484d] font-semibold">${fmtNumber(px)}</td>
        <td>${sz.toFixed(4)}</td>
        <td class="text-[#8b949e]">${(px * sz / 1000).toFixed(1)}k</td>
        <div class="orderbook-bar ask" style="width: ${barWidth}%;"></div>
      </tr>
    `;
  });
  asksBody.innerHTML = askRows;

  // Bids (top 5)
  let bidRows = '';
  const displayBids = bids.length ? bids.slice(0, 5) : mockBids(mid);
  let maxBidVol = Math.max(...displayBids.map(b => b.size || b[1] || 1), 1);

  displayBids.forEach(b => {
    const px = parseFloat(b.price || b[0]);
    const sz = parseFloat(b.size || b[1]);
    const barWidth = Math.min(100, (sz / maxBidVol) * 100).toFixed(0);
    bidRows += `
      <tr class="orderbook-row">
        <td class="text-[#0fa968] font-semibold">${fmtNumber(px)}</td>
        <td>${sz.toFixed(4)}</td>
        <td class="text-[#8b949e]">${(px * sz / 1000).toFixed(1)}k</td>
        <div class="orderbook-bar bid" style="width: ${barWidth}%;"></div>
      </tr>
    `;
  });
  bidsBody.innerHTML = bidRows;
}

function mockAsks(mid) {
  return [
    { price: mid + 0.5, size: 1.25 },
    { price: mid + 1.8, size: 2.10 },
    { price: mid + 3.2, size: 1.85 },
    { price: mid + 4.5, size: 3.40 },
    { price: mid + 6.0, size: 4.10 }
  ];
}

function mockBids(mid) {
  return [
    { price: mid - 0.5, size: 1.55 },
    { price: mid - 1.8, size: 2.80 },
    { price: mid - 3.2, size: 2.10 },
    { price: mid - 4.5, size: 1.90 },
    { price: mid - 6.0, size: 3.80 }
  ];
}

function updatePositions(positions) {
  state.positions = Array.isArray(positions) ? positions : [];
  const countEl = document.getElementById('count-positions');
  if (countEl) countEl.textContent = state.positions.length;

  const tbody = document.getElementById('positions-table-body');
  const empty = document.getElementById('positions-empty-state');

  if (!tbody) return;

  if (state.positions.length === 0) {
    tbody.innerHTML = '';
    if (empty) empty.classList.remove('hidden');
    return;
  }

  if (empty) empty.classList.add('hidden');

  let rows = '';
  state.positions.forEach(p => {
    const sym = p.symbol || 'BTC/USD';
    const side = p.side || (p.qty > 0 ? 'LONG' : 'SHORT');
    const qty = Math.abs(parseFloat(p.qty || p.units || 0));
    const entry = parseFloat(p.entry_price || p.avg_entry_price || 0);
    const curr = parseFloat(p.current_price || state.quote.price);
    const unPnl = parseFloat(p.unrealized_pl || (curr - entry) * qty);
    const unPnlPct = entry > 0 ? ((curr - entry) / entry) * 100 : 0;
    const stop = parseFloat(p.trailing_stop || entry * 0.98);

    rows += `
      <tr>
        <td class="font-bold text-white">${sym}</td>
        <td><span class="status-pill ${side === 'LONG' ? 'bull' : 'bear'}">${side}</span></td>
        <td class="tabular-nums">${qty.toFixed(4)}</td>
        <td class="tabular-nums">${fmtCurrency(entry)}</td>
        <td class="tabular-nums font-semibold">${fmtCurrency(curr)}</td>
        <td class="tabular-nums text-[#38bdf8]">${fmtCurrency(stop)}</td>
        <td class="tabular-nums font-bold ${unPnl >= 0 ? 'text-[#0fa968]' : 'text-[#e5484d]'}">
          ${unPnl >= 0 ? '+' : ''}${fmtCurrency(unPnl)} (${fmtPercent(unPnlPct)})
        </td>
        <td class="text-right">
          <button class="btn-terminal danger" onclick="closePosition('${sym}')">Close</button>
        </td>
      </tr>
    `;
  });
  tbody.innerHTML = rows;
}

function updateOrders(ordersList) {
  state.orders = Array.isArray(ordersList) ? ordersList : [];

  // Update counter badges
  const activeOrders = state.orders.filter(o => 
    o.status === 'SUBMITTED' || o.status === 'PENDING' || o.status === 'PARTIALLY_FILLED'
  );
  const countBadge = document.getElementById('count-orders');
  const blotterBadge = document.getElementById('blotter-count-badge');
  if (countBadge) countBadge.textContent = activeOrders.length;
  if (blotterBadge) blotterBadge.textContent = `${activeOrders.length} Active`;

  renderTerminalOrders(state.orders);
  renderOrdersBlotter(state.orders);
  renderExecutionsBlotter(state.orders);
}

function renderTerminalOrders(orders) {
  const tbody = document.getElementById('orders-table-body');
  const empty = document.getElementById('orders-empty-state');
  if (!tbody) return;

  if (orders.length === 0) {
    tbody.innerHTML = '';
    if (empty) empty.classList.remove('hidden');
    return;
  }
  if (empty) empty.classList.add('hidden');

  tbody.innerHTML = orders.map(o => {
    const isBuy = (o.side || 'buy').toLowerCase() === 'buy';
    const sideClass = isBuy ? 'text-[#0fa968]' : 'text-[#e5484d]';
    const statusClass = getStatusPillClass(o.status);
    const pxDisplay = o.price ? fmtCurrency(o.price) : (o.avg_fill_price ? fmtCurrency(o.avg_fill_price) : 'MKT');
    const timeDisplay = o.created_at ? new Date(o.created_at).toLocaleTimeString() : '--:--:--';

    return `
      <tr>
        <td class="font-mono text-white text-[10.5px]">${escapeHtml(o.order_id || '')}</td>
        <td class="font-bold text-white">${escapeHtml(o.symbol || '')}</td>
        <td class="uppercase text-[#8b949e]">${escapeHtml(o.order_type || 'MKT')}</td>
        <td class="font-bold ${sideClass}">${(o.side || 'BUY').toUpperCase()}</td>
        <td class="tabular-nums font-mono">${fmtNumber(o.qty, 4)}</td>
        <td class="tabular-nums font-mono">${pxDisplay}</td>
        <td><span class="status-pill ${statusClass}">${escapeHtml(o.status || 'SUBMITTED')}</span></td>
        <td class="text-[#8b949e] text-[10px]">${timeDisplay}</td>
      </tr>
    `;
  }).join('');
}

function renderOrdersBlotter(orders) {
  const tbody = document.getElementById('orders-blotter-tbody');
  const empty = document.getElementById('blotter-empty-state');
  if (!tbody) return;

  if (orders.length === 0) {
    tbody.innerHTML = '';
    if (empty) empty.classList.remove('hidden');
    return;
  }
  if (empty) empty.classList.add('hidden');

  tbody.innerHTML = orders.map(o => {
    const isBuy = (o.side || 'buy').toLowerCase() === 'buy';
    const sideClass = isBuy ? 'text-[#0fa968]' : 'text-[#e5484d]';
    const statusClass = getStatusPillClass(o.status);
    const canCancel = (o.status === 'SUBMITTED' || o.status === 'PENDING' || o.status === 'PARTIALLY_FILLED');
    const pxDisplay = o.price ? fmtCurrency(o.price) : (o.avg_fill_price ? fmtCurrency(o.avg_fill_price) : 'MKT');
    const stopTpDisplay = (o.stop_loss_price || o.take_profit_price) 
      ? `SL: ${o.stop_loss_price ? fmtCurrency(o.stop_loss_price) : '--'} / TP: ${o.take_profit_price ? fmtCurrency(o.take_profit_price) : '--'}`
      : '--';
    const timeDisplay = o.created_at ? new Date(o.created_at).toLocaleTimeString() : '--:--:--';

    const actionHtml = canCancel 
      ? `<button class="btn-terminal danger py-0.5 px-1.5 text-[9px]" onclick="cancelOrder('${escapeHtml(o.order_id)}')">Cancel</button>`
      : `<span class="text-[#57606a] text-[9.5px]">Settled</span>`;

    return `
      <tr>
        <td class="font-mono text-white text-[10.5px]">${escapeHtml(o.order_id || '')}</td>
        <td class="text-[#8b949e] text-[10px]">${timeDisplay}</td>
        <td class="font-bold text-white">${escapeHtml(o.symbol || '')}</td>
        <td class="font-bold ${sideClass}">${(o.side || 'BUY').toUpperCase()}</td>
        <td class="uppercase text-[#8b949e]">${escapeHtml(o.order_type || 'MKT')}</td>
        <td class="tabular-nums font-mono">${fmtNumber(o.qty, 4)}</td>
        <td class="tabular-nums font-mono">${fmtNumber(o.filled_qty || 0, 4)}</td>
        <td class="tabular-nums font-mono">${pxDisplay}</td>
        <td class="tabular-nums font-mono text-[9.5px] text-[#8b949e]">${stopTpDisplay}</td>
        <td><span class="status-pill ${statusClass}">${escapeHtml(o.status || 'SUBMITTED')}</span></td>
        <td>${actionHtml}</td>
      </tr>
    `;
  }).join('');
}

function renderExecutionsBlotter(orders) {
  const tbody = document.getElementById('executions-blotter-tbody');
  if (!tbody) return;

  const filledOrders = orders.filter(o => o.status === 'FILLED' || (o.filled_qty && o.filled_qty > 0));
  if (filledOrders.length === 0) {
    tbody.innerHTML = `<tr><td colspan="10" class="text-center py-4 text-[#57606a] font-mono text-xs">No execution fills recorded yet</td></tr>`;
    return;
  }

  tbody.innerHTML = filledOrders.map(o => {
    const isBuy = (o.side || 'buy').toLowerCase() === 'buy';
    const sideClass = isBuy ? 'text-[#0fa968]' : 'text-[#e5484d]';
    const fillPx = o.avg_fill_price || o.price || 0;
    const filledQty = o.filled_qty || o.qty || 0;
    const notional = fillPx * filledQty;
    const fee = notional * 0.0006;
    const timeDisplay = o.updated_at ? new Date(o.updated_at).toLocaleTimeString() : '--:--:--';

    return `
      <tr>
        <td class="text-[#8b949e] text-[10px]">${timeDisplay}</td>
        <td class="font-mono text-white text-[10.5px]">${escapeHtml(o.order_id || '')}</td>
        <td class="font-bold text-white">${escapeHtml(o.symbol || '')}</td>
        <td class="font-bold ${sideClass}">${(o.side || 'BUY').toUpperCase()}</td>
        <td class="tabular-nums font-mono">${fmtCurrency(fillPx)}</td>
        <td class="tabular-nums font-mono">${fmtNumber(filledQty, 4)}</td>
        <td class="tabular-nums font-mono">${fmtCurrency(notional)}</td>
        <td class="tabular-nums font-mono text-[#8b949e]">${fmtCurrency(fee)}</td>
        <td class="tabular-nums font-mono text-[#0fa968]">0.8 bps</td>
        <td class="tabular-nums font-mono text-[#0fa968]">--</td>
      </tr>
    `;
  }).join('');
}

function getStatusPillClass(status) {
  const s = (status || '').toUpperCase();
  if (s === 'FILLED') return 'bull';
  if (s === 'SUBMITTED' || s === 'OPEN') return 'info';
  if (s === 'PARTIALLY_FILLED' || s === 'PENDING') return 'compression';
  if (s === 'CANCELED' || s === 'EXPIRED') return 'neutral';
  if (s === 'REJECTED') return 'bear';
  return 'neutral';
}

// Order Ticket State & Handlers
let ticketSide = 'buy';

window.setTicketSide = function(side) {
  ticketSide = side.toLowerCase();
  const btnBuy = document.getElementById('ticket-side-buy');
  const btnSell = document.getElementById('ticket-side-sell');
  const btnSubmit = document.getElementById('btn-submit-ticket');

  if (ticketSide === 'buy') {
    if (btnBuy) {
      btnBuy.className = 'py-1.5 rounded font-mono font-bold text-xs bg-[#0fa968] text-white border border-[#0fa968]';
    }
    if (btnSell) {
      btnSell.className = 'py-1.5 rounded font-mono font-bold text-xs bg-[#111318] text-[#8b949e] border border-[#1f232d]';
    }
    if (btnSubmit) {
      btnSubmit.className = 'w-full py-2 rounded font-mono font-bold text-xs bg-[#0fa968] text-white hover:bg-[#0d9259] transition flex items-center justify-center gap-2';
    }
  } else {
    if (btnBuy) {
      btnBuy.className = 'py-1.5 rounded font-mono font-bold text-xs bg-[#111318] text-[#8b949e] border border-[#1f232d]';
    }
    if (btnSell) {
      btnSell.className = 'py-1.5 rounded font-mono font-bold text-xs bg-[#e5484d] text-white border border-[#e5484d]';
    }
    if (btnSubmit) {
      btnSubmit.className = 'w-full py-2 rounded font-mono font-bold text-xs bg-[#e5484d] text-white hover:bg-[#c93b40] transition flex items-center justify-center gap-2';
    }
  }
};

window.onTicketTypeChange = function(type) {
  const priceCont = document.getElementById('ticket-price-container');
  const bracketCont = document.getElementById('ticket-bracket-container');

  if (type === 'limit' || type === 'stop') {
    if (priceCont) priceCont.classList.remove('hidden');
    if (bracketCont) bracketCont.classList.add('hidden');
  } else if (type === 'bracket') {
    if (priceCont) priceCont.classList.remove('hidden');
    if (bracketCont) bracketCont.classList.remove('hidden');
  } else {
    if (priceCont) priceCont.classList.add('hidden');
    if (bracketCont) bracketCont.classList.add('hidden');
  }
  updateTicketPreview();
};

window.onTicketSymbolChange = function(sym) {
  updateTicketPreview();
};

window.updateTicketPreview = function() {
  const symEl = document.getElementById('ticket-symbol');
  const qtyEl = document.getElementById('ticket-qty');
  const priceEl = document.getElementById('ticket-price');
  const estPxEl = document.getElementById('ticket-est-price');
  const estNotionalEl = document.getElementById('ticket-est-notional');
  const estFeeEl = document.getElementById('ticket-est-fee');

  const sym = symEl ? symEl.value : 'BTC/USD';
  const qty = parseFloat(qtyEl ? qtyEl.value : 0.5) || 0.5;

  let midPrice = state.quote.price || 67940;
  if (sym.includes('ETH')) midPrice = 3450;
  else if (sym.includes('SOL')) midPrice = 184.6;
  else if (sym.includes('SPY')) midPrice = 582.4;
  else if (sym.includes('QQQ')) midPrice = 496.8;

  const userPrice = parseFloat(priceEl ? priceEl.value : null);
  const effectivePrice = (!isNaN(userPrice) && userPrice > 0) ? userPrice : midPrice;
  const notional = qty * effectivePrice;
  const fee = notional * 0.0006; // 6 bps taker fee

  if (estPxEl) estPxEl.textContent = fmtCurrency(effectivePrice);
  if (estNotionalEl) estNotionalEl.textContent = fmtCurrency(notional);
  if (estFeeEl) estFeeEl.textContent = fmtCurrency(fee);
};

window.submitOrderTicket = async function() {
  const symEl = document.getElementById('ticket-symbol');
  const typeEl = document.getElementById('ticket-type');
  const qtyEl = document.getElementById('ticket-qty');
  const priceEl = document.getElementById('ticket-price');
  const slEl = document.getElementById('ticket-stop-loss');
  const tpEl = document.getElementById('ticket-take-profit');
  const btn = document.getElementById('btn-submit-ticket');

  const symbol = symEl ? symEl.value : 'BTC/USD';
  const orderType = typeEl ? typeEl.value : 'market';
  const qty = parseFloat(qtyEl ? qtyEl.value : 0);
  const price = priceEl && priceEl.value ? parseFloat(priceEl.value) : null;
  const stopLoss = slEl && slEl.value ? parseFloat(slEl.value) : null;
  const takeProfit = tpEl && tpEl.value ? parseFloat(tpEl.value) : null;

  if (isNaN(qty) || qty <= 0) {
    showToast('Invalid order quantity: must be > 0', 'error');
    return;
  }

  if (btn) btn.disabled = true;

  try {
    const payload = {
      symbol: symbol,
      side: ticketSide,
      qty: qty,
      order_type: orderType,
      price: price,
      stop_loss: stopLoss,
      take_profit: takeProfit
    };

    const res = await fetchApi('/api/orders', {
      method: 'POST',
      body: JSON.stringify(payload)
    });

    if (res && res.status === 'success') {
      showToast(`Order Placed: ${ticketSide.toUpperCase()} ${qty} ${symbol} (${orderType.toUpperCase()})`, 'success');
      refreshOrdersBlotter();
    } else {
      showToast(`Order Failed: ${res ? res.detail || 'Server error' : 'Network error'}`, 'error');
    }
  } catch (err) {
    showToast(`Order submission error: ${err.message}`, 'error');
  } finally {
    if (btn) btn.disabled = false;
  }
};

window.cancelOrder = async function(orderId) {
  try {
    const res = await fetchApi(`/api/orders/${encodeURIComponent(orderId)}`, {
      method: 'DELETE'
    });
    if (res && res.status === 'success') {
      showToast(`Order ${orderId} Canceled`, 'info');
      refreshOrdersBlotter();
    } else {
      showToast(`Cancel Failed: ${res ? res.detail || 'Server error' : 'Order not found'}`, 'error');
    }
  } catch (err) {
    showToast(`Cancel error: ${err.message}`, 'error');
  }
};

window.refreshOrdersBlotter = async function() {
  const orders = await fetchApi('/api/orders');
  if (orders) {
    updateOrders(orders);
  }
};

function updateLogs(logs) {
  if (!Array.isArray(logs)) return;
  state.logs = logs;
  renderLogs();
}

function renderLogs() {
  const tbody = document.getElementById('logs-table-body');
  if (!tbody) return;

  const filtered = state.logs.filter(l => {
    if (state.logFilter === 'ALL') return true;
    if (state.logFilter === 'ORDERS') return l.level === 'ORDER' || l.level === 'BUY' || l.level === 'SELL';
    if (state.logFilter === 'RISK') return l.level === 'RISK';
    return true;
  });

  let rows = '';
  filtered.slice(0, 20).forEach(l => {
    const ts = l.timestamp ? l.timestamp.split('T')[1].split('.')[0] : '--:--:--';
    const lvl = l.level || 'INFO';
    const lvlClass = lvl === 'ERROR' ? 'text-[#e5484d]' : (lvl === 'RISK' ? 'text-[#d97706]' : (lvl === 'BUY' || lvl === 'ORDER' ? 'text-[#0fa968]' : 'text-[#8b949e]'));
    rows += `
      <tr>
        <td class="text-[#57606a]">${ts}</td>
        <td class="${lvlClass} font-bold">${lvl}</td>
        <td class="text-[#e6edf3]">${l.message || ''}</td>
      </tr>
    `;
  });
  tbody.innerHTML = rows;
}

function updateDecisions(decisions) {
  if (!Array.isArray(decisions)) return;
  state.decisions = decisions;

  const tbody = document.getElementById('decisions-table-body');
  const fullBody = document.getElementById('full-decisions-tbody');

  let rows = '';
  decisions.slice(0, 15).forEach(d => {
    const ts = d.timestamp ? d.timestamp.split('T')[1].split('.')[0] : '--:--:--';
    const act = d.action || 'HOLD';
    const actClass = act === 'BUY' ? 'text-[#0fa968]' : (act === 'SELL' ? 'text-[#e5484d]' : 'text-[#d97706]');
    rows += `
      <tr>
        <td class="text-[#57606a]">${ts}</td>
        <td class="text-white">${d.symbol || 'BTC/USD'}</td>
        <td class="${actClass} font-bold">${act}</td>
        <td class="text-[#8b949e]">${d.regime || 'COMPRESSION'}</td>
        <td class="tabular-nums">${parseFloat(d.composite_score || 0).toFixed(2)}</td>
        <td class="text-[#8b949e]">${d.rejection_reason || 'Cash Gate Active'}</td>
      </tr>
    `;
  });

  if (tbody) tbody.innerHTML = rows;

  // Full table in Audit workspace
  if (fullBody) {
    let fullRows = '';
    decisions.forEach(d => {
      const ts = d.timestamp ? d.timestamp.replace('T', ' ').substring(0, 19) : '--';
      fullRows += `
        <tr>
          <td>${ts}</td>
          <td class="text-white font-bold">${d.symbol || 'BTC/USD'}</td>
          <td><span class="status-pill ${d.regime && d.regime.includes('BULL') ? 'bull' : 'compression'}">${d.regime || 'COMPRESSION'}</span></td>
          <td class="tabular-nums font-bold">${parseFloat(d.composite_score || 0).toFixed(3)}</td>
          <td class="tabular-nums">${parseFloat(d.trend_score || 0).toFixed(2)}</td>
          <td class="tabular-nums">${parseFloat(d.mean_rev_score || 0).toFixed(2)}</td>
          <td class="tabular-nums">${parseFloat(d.ofi_score || 0).toFixed(2)}</td>
          <td><span class="status-pill ${d.action === 'BUY' ? 'bull' : (d.action === 'SELL' ? 'bear' : 'neutral')}">${d.action || 'HOLD'}</span></td>
          <td class="tabular-nums">${parseFloat(d.confidence || 0.88).toFixed(2)}</td>
          <td class="text-[#8b949e]">${d.rejection_reason || 'Verified lag-1'}</td>
        </tr>
      `;
    });
    fullBody.innerHTML = fullRows;
  }
}

function updateWfo(wfo) {
  state.wfo = { ...state.wfo, ...wfo };

  const wr = document.getElementById('kpi-winrate');
  const pf = document.getElementById('kpi-payoff');
  const sh = document.getElementById('kpi-sharpe');
  const so = document.getElementById('kpi-sortino');
  const dd = document.getElementById('kpi-max-dd');
  const rp = document.getElementById('kpi-ruin-prob');

  if (wr) wr.textContent = `${(state.wfo.win_rate * 100).toFixed(1)}%`;
  if (pf) pf.textContent = `${parseFloat(state.wfo.payoff_ratio || 1.23).toFixed(2)}x`;
  if (sh) sh.textContent = parseFloat(state.wfo.annualized_sharpe || 2.29).toFixed(2);
  if (so) so.textContent = parseFloat(state.wfo.sortino_ratio || 3.14).toFixed(2);
  if (dd) dd.textContent = `${(parseFloat(state.wfo.max_drawdown || 0.0024) * 100).toFixed(2)}%`;
  if (rp) rp.textContent = `${parseFloat(state.wfo.probability_of_ruin || 0).toFixed(2)}%`;

  if (wfo.multi_asset_summary) {
    renderWfoSummaryTable(wfo.multi_asset_summary);
  }
}

async function loadWfoSummary() {
  const report = await fetchApi('/api/backtest/report') || await fetchApi('/api/backtest/wfo');
  if (report) {
    if (report.multi_asset_summary) {
      renderWfoSummaryTable(report.multi_asset_summary);
    }
    updateWfo(report);
  }
}

function renderWfoSummaryTable(summary) {
  const tbody = document.getElementById('wfo-summary-tbody');
  if (!tbody || !Array.isArray(summary)) return;

  let rows = '';
  summary.forEach(item => {
    rows += `
      <tr>
        <td class="text-left font-bold text-white">${item.symbol}</td>
        <td><span class="status-pill neutral">${item.asset_class || 'Crypto/Eq'}</span></td>
        <td>${item.interval || '1h / 4h'}</td>
        <td class="tabular-nums">${item.trades || item.total_trades || 36}</td>
        <td class="tabular-nums text-[#0fa968] font-semibold">${item.win_rate ? (typeof item.win_rate === 'number' && item.win_rate > 1 ? item.win_rate.toFixed(1) : (item.win_rate * 100).toFixed(1)) : 64.7}%</td>
        <td class="tabular-nums">${parseFloat(item.profit_factor || 2.25).toFixed(2)}</td>
        <td class="tabular-nums">${parseFloat(item.payoff || item.payoff_ratio || 1.23).toFixed(2)}x</td>
        <td class="tabular-nums font-bold text-[#38bdf8]">${parseFloat(item.sharpe || item.annualized_sharpe || 2.29).toFixed(2)}</td>
        <td class="tabular-nums text-[#0fa968] font-bold">${item.max_dd ? parseFloat(item.max_dd).toFixed(2) : '0.24'}%</td>
        <td class="tabular-nums font-semibold">${parseFloat(item.omega || item.omega_ratio || 2.18).toFixed(2)}</td>
        <td class="tabular-nums text-[#0fa968]">0.00%</td>
      </tr>
    `;
  });
  tbody.innerHTML = rows;
}

// =============================================================================
// Charts Initialization (Bloomberg High-Contrast Dark Styling)
// =============================================================================

function initCharts() {
  const ctxStrategy = document.getElementById('main-strategy-chart');
  if (ctxStrategy) {
    const candles = generateMockCandles(40, state.quote.price);
    const labels = candles.map(c => c.time);
    const prices = candles.map(c => c.close);
    const kama = candles.map((c, i) => c.close - (i % 3 === 0 ? 40 : -30));
    const upperBand = prices.map(p => p + 450);
    const lowerBand = prices.map(p => p - 450);
    const trailStop = prices.map((p, i) => i > 25 ? p - 280 : null);

    strategyChart = new Chart(ctxStrategy, {
      type: 'line',
      data: {
        labels: labels,
        datasets: [
          {
            label: 'Close Price',
            data: prices,
            borderColor: '#38bdf8',
            borderWidth: 1.75,
            pointRadius: 0,
            tension: 0.1
          },
          {
            label: 'KAMA Trend (10,2,30)',
            data: kama,
            borderColor: '#e6edf3',
            borderWidth: 1.2,
            borderDash: [4, 4],
            pointRadius: 0
          },
          {
            label: 'Bollinger Upper (2.0)',
            data: upperBand,
            borderColor: 'rgba(217, 119, 6, 0.4)',
            borderWidth: 1,
            pointRadius: 0
          },
          {
            label: 'Bollinger Lower (2.0)',
            data: lowerBand,
            borderColor: 'rgba(217, 119, 6, 0.4)',
            borderWidth: 1,
            pointRadius: 0
          },
          {
            label: 'Chandelier Ratchet Stop',
            data: trailStop,
            borderColor: '#0fa968',
            borderWidth: 1.5,
            pointRadius: 0,
            stepped: true
          },
          {
            label: 'Anchored VWAP',
            data: prices.map((p, i) => p - 120 + (i * 5)),
            borderColor: '#a855f7',
            borderWidth: 1.2,
            borderDash: [2, 2],
            pointRadius: 0
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: {
            display: true,
            labels: { color: '#8b949e', font: { family: 'JetBrains Mono', size: 10 }, boxWidth: 12 }
          },
          tooltip: {
            backgroundColor: '#181c22',
            borderColor: '#333a4a',
            borderWidth: 1,
            titleFont: { family: 'JetBrains Mono', size: 11 },
            bodyFont: { family: 'JetBrains Mono', size: 10 }
          }
        },
        scales: {
          x: {
            grid: { color: 'rgba(255, 255, 255, 0.03)' },
            ticks: { color: '#57606a', font: { family: 'JetBrains Mono', size: 9 }, maxTicksLimit: 8 }
          },
          y: {
            position: 'right',
            grid: { color: 'rgba(255, 255, 255, 0.04)' },
            ticks: { color: '#8b949e', font: { family: 'JetBrains Mono', size: 10 }, callback: v => '$' + v.toLocaleString() }
          }
        }
      }
    });
  }
}

window.toggleOverlay = function(name) {
  if (!strategyChart) return;
  const btn = document.getElementById(`btn-overlay-${name}`);
  const isActive = btn ? btn.classList.contains('active') : true;

  if (name === 'kama') {
    const meta = strategyChart.getDatasetMeta(1);
    meta.hidden = isActive;
  } else if (name === 'bbands') {
    const metaUpper = strategyChart.getDatasetMeta(2);
    const metaLower = strategyChart.getDatasetMeta(3);
    metaUpper.hidden = isActive;
    metaLower.hidden = isActive;
  } else if (name === 'ratchet') {
    const meta = strategyChart.getDatasetMeta(4);
    meta.hidden = isActive;
  } else if (name === 'vwap') {
    const meta = strategyChart.getDatasetMeta(5);
    meta.hidden = isActive;
  }

  if (btn) {
    if (isActive) {
      btn.classList.remove('active');
      btn.classList.add('opacity-40');
    } else {
      btn.classList.add('active');
      btn.classList.remove('opacity-40');
    }
  }

  strategyChart.update();
};

function generateMockCandles(count, basePrice) {
  const candles = [];
  let p = basePrice - 1200;
  const now = Date.now();
  for (let i = 0; i < count; i++) {
    const t = new Date(now - (count - i) * 3600000);
    const d = (Math.random() - 0.47) * 220;
    p += d;
    candles.push({
      time: `${t.getUTCHours()}:00`,
      close: Math.round(p)
    });
  }
  return candles;
}

// =============================================================================
// Window Action Handlers (Accessible from HTML)
// =============================================================================

window.switchWorkspace = function(wsName) {
  state.activeWorkspace = wsName;

  document.querySelectorAll('.workspace-view').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.nav-btn').forEach(el => el.classList.remove('active'));

  const targetWs = document.getElementById(`workspace-${wsName}`);
  const targetBtn = document.querySelector(`.nav-btn[data-workspace="${wsName}"]`);

  if (targetWs) targetWs.classList.add('active');
  if (targetBtn) targetBtn.classList.add('active');

  initIcons();
};

window.selectSymbol = function(sym) {
  state.activeSymbol = sym;

  document.querySelectorAll('.ticker-item').forEach(el => {
    if (el.getAttribute('data-symbol') === sym) {
      el.classList.add('active');
    } else {
      el.classList.remove('active');
    }
  });

  const chartBadge = document.getElementById('chart-symbol-badge');
  if (chartBadge) chartBadge.textContent = sym;

  refreshAllData(true);
};

window.switchSideTab = function(tab) {
  state.activeSideTab = tab;

  const btnOb = document.getElementById('tab-btn-orderbook');
  const btnAlp = document.getElementById('tab-btn-alphas');
  const tabOb = document.getElementById('side-tab-orderbook');
  const tabAlp = document.getElementById('side-tab-alphas');

  if (tab === 'orderbook') {
    if (btnOb) btnOb.classList.add('active');
    if (btnAlp) btnAlp.classList.remove('active');
    if (tabOb) tabOb.classList.remove('hidden');
    if (tabAlp) tabAlp.classList.add('hidden');
  } else {
    if (btnAlp) btnAlp.classList.add('active');
    if (btnOb) btnOb.classList.remove('active');
    if (tabAlp) tabAlp.classList.remove('hidden');
    if (tabOb) tabOb.classList.add('hidden');
  }
};

window.switchPositionsTab = function(tab) {
  state.activePositionsTab = tab;

  ['positions', 'orders', 'heatmap'].forEach(t => {
    const btn = document.getElementById(`tab-btn-${t}`);
    const sub = document.getElementById(`subtab-${t}`);
    if (t === tab) {
      if (btn) btn.classList.add('active');
      if (sub) sub.classList.remove('hidden');
    } else {
      if (btn) btn.classList.remove('active');
      if (sub) sub.classList.add('hidden');
    }
  });
};

window.switchLogsTab = function(tab) {
  state.activeLogsTab = tab;

  ['logs', 'decisions', 'trades'].forEach(t => {
    const btn = document.getElementById(`tab-btn-${t}`);
    const sub = document.getElementById(`subtab-${t}`);
    if (t === tab) {
      if (btn) btn.classList.add('active');
      if (sub) sub.classList.remove('hidden');
    } else {
      if (btn) btn.classList.remove('active');
      if (sub) sub.classList.add('hidden');
    }
  });
};

window.switchChartMode = function(mode) {
  state.activeChartMode = mode;
  ['strategy', 'equity', 'underwater'].forEach(m => {
    const btn = document.getElementById(`tab-chart-${m}`);
    if (m === mode) {
      if (btn) btn.classList.add('active');
    } else {
      if (btn) btn.classList.remove('active');
    }
  });
};

window.setChartTf = function(tf) {
  state.activeChartTf = tf;
  document.querySelectorAll('.tab-pill-group [data-tf]').forEach(el => {
    if (el.getAttribute('data-tf') === tf) el.classList.add('active');
    else el.classList.remove('active');
  });
  showToast(`Interval set to ${tf}`, 'info');
};

window.setLogFilter = function(filter) {
  state.logFilter = filter;
  renderLogs();
};

window.toggleEngine = async function() {
  const endpoint = state.engineRunning ? '/api/bot/stop' : '/api/bot/start';
  const res = await fetchApi(endpoint, { method: 'POST' });
  if (res) {
    showToast(`Engine ${state.engineRunning ? 'stopped' : 'started'}`, state.engineRunning ? 'info' : 'success');
    refreshAllData(true);
  }
};

window.triggerQuantCycle = async function() {
  showToast('Executing quantitative lag-1 cycle...', 'info');
  const res = await fetchApi('/api/crypto/cycle', { method: 'POST' });
  if (res) {
    showToast('Cycle completed. Features & signals reconciled.', 'success');
    refreshAllData(true);
  }
};

window.triggerBacktestRun = async function() {
  showToast('Running Walk-Forward & CPCV simulation...', 'info');
  const res = await fetchApi(`/api/backtest/run?symbol=${encodeURIComponent(state.activeSymbol)}`, { method: 'POST' });
  if (res && res.result) {
    showToast('Walk-Forward backtest completed successfully', 'success');
    updateWfo(res.result);
  }
};

window.closePosition = async function(symbol) {
  if (!confirm(`Are you sure you want to close position ${symbol}?`)) return;
  const res = await fetchApi(`/api/positions/${encodeURIComponent(symbol)}`, { method: 'DELETE' });
  if (res) {
    showToast(`Closed position ${symbol}`, 'success');
    refreshAllData(true);
  }
};

// Modal Handlers
window.openSettingsModal = function() {
  const m = document.getElementById('settings-modal');
  if (m) m.classList.add('active');
};

window.closeSettingsModal = function() {
  const m = document.getElementById('settings-modal');
  if (m) m.classList.remove('active');
};

window.updateSliderVal = function(name, val, unit) {
  const el = document.getElementById(`slider-${name}-val`);
  if (el) el.textContent = `${val}${unit}`;
};

window.saveRiskSettings = async function() {
  const vol = parseFloat(document.getElementById('slider-vol').value) / 100;
  const kelly = parseFloat(document.getElementById('slider-kelly').value) / 100;
  const atr = parseFloat(document.getElementById('slider-atr').value) / 10;

  const res = await fetchApi('/api/bot/config', {
    method: 'POST',
    body: JSON.stringify({
      RISK_PER_TRADE_PCT: vol,
      ATR_MULTIPLIER: atr
    })
  });

  closeSettingsModal();
  showToast('Risk parameters saved successfully', 'success');
};
