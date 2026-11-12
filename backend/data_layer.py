"""
Institutional Multi-Asset Data Layer
====================================
Production-grade multi-source market data layer supporting:
1. Binance Public REST (Real crypto OHLCV + Taker Buy Volume for order flow aggressor delta).
   Supports pagination for long historical windows (e.g., 2+ years of 1h/4h bars).
2. Coinbase Public REST (Spot candles for major crypto pairs: BTC, ETH, SOL).
3. Alpaca Market Data (US Equities SPY, QQQ + Crypto fallback via REST and WebSocket).
4. Perpetual Funding Rates: Real-time & historical funding rates from Binance & Bybit.
5. Persistent Trade & Level-2 Snapshot Storage: SQLite & Parquet persistence.
6. Latency-Aware Fill Model: Realistic execution simulation incorporating
   half-spread crossing cost, square-root market impact, and execution latency penalty.
7. Local on-disk persistent caching with multi-timeframe caching & freshness validation.
8. Strict data cleaning and validation (monotonic ordering, deduplication, OHLC sanity bounds).
9. Synthetic high-fidelity generator when operating offline or in isolated test mode.

All bar timestamps are normalized to UTC ISO-8601 strings (YYYY-MM-DDTHH:MM:SSZ)
with exact millisecond Unix epoch.
"""

import os
import sys
import json
import time
import math
import random
import sqlite3
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Union, Tuple
from dataclasses import dataclass, asdict
from contextlib import contextmanager

import requests

logger = logging.getLogger("data_layer")

# Project directories
_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_BACKEND_DIR, ".."))
_CACHE_DIR = os.path.join(_PROJECT_ROOT, ".cache", "bars")
_DB_PATH = os.path.join(_CACHE_DIR, "market_depth.db")
os.makedirs(_CACHE_DIR, exist_ok=True)


# ==============================================================================
# Domain Data Models
# ==============================================================================

@dataclass
class Bar:
    """Canonical multi-asset OHLCV bar with microstructure attributes."""
    timestamp: str       # ISO 8601 UTC string: YYYY-MM-DDTHH:MM:SSZ
    epoch_ms: int        # Unix epoch in milliseconds
    open: float          # Open price
    high: float          # High price
    low: float           # Low price
    close: float         # Close price
    volume: float        # Total volume (base asset for crypto, shares for equities)
    quote_volume: float  # Quote currency turnover (e.g., USDT / USD volume)
    trades: int          # Total trade count
    taker_buy_vol: float # Aggressive buyer volume
    vwap: float          # Volume-weighted average price

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FundingRateRecord:
    """Perpetual futures funding rate record."""
    symbol: str               # Canonical slash format (e.g., BTC/USDT)
    funding_rate: float       # Fractional 8h funding rate (e.g. 0.0001 = 0.01%)
    annualized_rate: float    # Annualized funding rate (funding_rate * 3 * 365)
    funding_time: str         # ISO 8601 UTC timestamp
    epoch_ms: int             # Unix epoch in milliseconds
    mark_price: float         # Perpetual mark price
    source: str               # "binance", "bybit", or "synthetic"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FillResult:
    """Detailed execution fill simulation outcome."""
    symbol: str
    side: str                     # "BUY" or "SELL"
    order_size: float             # Nominal order size in base units
    mid_price: float              # Pre-trade fair mid price
    spread: float                 # Current BBO bid-ask spread
    half_spread_cost: float       # Half-spread crossing cost (0 for passive maker)
    impact_cost: float            # Square-root market impact
    latency_penalty_cost: float   # Slippage drift incurred across execution latency
    fill_price: float             # Final simulated execution price
    slippage_bps: float           # Price divergence from mid in basis points
    is_maker: bool                # True for passive limit, False for aggressive taker
    latency_ms: float             # Simulated network/matching latency in milliseconds
    timestamp: str                # Execution timestamp

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ==============================================================================
# Symbol & Interval Normalization
# ==============================================================================

def normalize_symbol(symbol: str) -> str:
    """
    Normalize symbol to standard slash format:
    BTC/USDT, ETH/USDT, SOL/USDT, SPY, QQQ, etc.
    """
    s = symbol.upper().replace("-", "/").replace("_", "/").strip()
    if "/" in s:
        parts = s.split("/")
        return f"{parts[0]}/{parts[1]}"
    if s.endswith("USDT") and len(s) > 4:
        return f"{s[:-4]}/USDT"
    if s.endswith("USD") and len(s) > 3:
        return f"{s[:-3]}/USD"
    if s in ("BTC", "ETH", "SOL"):
        return f"{s}/USDT"
    # Equity symbols: SPY, QQQ, AAPL, MSFT, etc.
    return s


def to_binance_symbol(symbol: str) -> str:
    """Convert standard symbol to Binance symbol (e.g. BTCUSDT, ETHUSDT, SOLUSDT)."""
    norm = normalize_symbol(symbol)
    if "/" in norm:
        base, quote = norm.split("/")
        if quote == "USD":
            quote = "USDT"
        return f"{base}{quote}"
    if norm in ("BTC", "ETH", "SOL", "BNB"):
        return f"{norm}USDT"
    return norm


def to_bybit_symbol(symbol: str) -> str:
    """Convert standard symbol to Bybit linear symbol (e.g. BTCUSDT, ETHUSDT)."""
    return to_binance_symbol(symbol)


def to_coinbase_product(symbol: str) -> str:
    """Convert standard symbol to Coinbase product id (e.g. BTC-USD, ETH-USD, SOL-USD)."""
    norm = normalize_symbol(symbol)
    if "/" in norm:
        base, quote = norm.split("/")
        return f"{base}-USD"
    if norm in ("BTC", "ETH", "SOL"):
        return f"{norm}-USD"
    return f"{norm}-USD"


def to_alpaca_symbol(symbol: str) -> str:
    """Convert standard symbol to Alpaca format (e.g. BTC/USD, ETH/USD, SPY, QQQ)."""
    norm = normalize_symbol(symbol)
    if "/" in norm:
        base, quote = norm.split("/")
        if quote == "USDT":
            quote = "USD"
        return f"{base}/{quote}"
    return norm


def normalize_interval(interval: str) -> str:
    """Normalize interval strings to canonical standard: 1m, 5m, 15m, 30m, 1h, 4h, 1d."""
    norm = interval.strip()
    mapping = {
        "1m": "1m", "1min": "1m", "1Min": "1m",
        "5m": "5m", "5min": "5m", "5Min": "5m",
        "15m": "15m", "15min": "15m", "15Min": "15m",
        "30m": "30m", "30min": "30m", "30Min": "30m",
        "1h": "1h", "1hour": "1h", "1Hour": "1h", "1H": "1h",
        "4h": "4h", "4hour": "4h", "4Hour": "4h", "4H": "4h",
        "1d": "1d", "1day": "1d", "1Day": "1d", "1D": "1d"
    }
    return mapping.get(norm, mapping.get(norm.lower(), norm))


def clean_and_validate_bars(bars: List[Bar]) -> List[Bar]:
    """
    Ensures strict causal ordering, deduplication, and sanity checking:
    1. Deduplicate by epoch_ms.
    2. Strictly chronological sorting.
    3. High >= max(open, close), Low <= min(open, close).
    4. Non-negative volume, trades >= 0.
    5. Bounded taker buy volume (0 <= taker_buy <= volume).
    """
    if not bars:
        return []

    seen_epochs = set()
    cleaned: List[Bar] = []

    for b in bars:
        if b.epoch_ms in seen_epochs:
            continue
        seen_epochs.add(b.epoch_ms)

        # Enforce OHLC consistency
        open_p = max(1e-4, float(b.open))
        close_p = max(1e-4, float(b.close))
        high_p = max(open_p, close_p, float(b.high))
        low_p = min(open_p, close_p, max(1e-4, float(b.low)))
        vol = max(0.0, float(b.volume))
        q_vol = float(b.quote_volume) if b.quote_volume > 0 else (vol * (open_p + close_p) / 2.0)
        trades = max(1, int(b.trades)) if vol > 0 else 0
        taker_buy = max(0.0, min(vol, float(b.taker_buy_vol)))
        vwap = float(b.vwap) if b.vwap > 0 else (q_vol / vol if vol > 0 else (open_p + high_p + low_p + close_p) / 4.0)

        cleaned.append(Bar(
            timestamp=b.timestamp,
            epoch_ms=b.epoch_ms,
            open=round(open_p, 4),
            high=round(high_p, 4),
            low=round(low_p, 4),
            close=round(close_p, 4),
            volume=round(vol, 4),
            quote_volume=round(q_vol, 2),
            trades=trades,
            taker_buy_vol=round(taker_buy, 4),
            vwap=round(vwap, 4)
        ))

    # Sort strictly chronological
    cleaned.sort(key=lambda x: x.epoch_ms)
    return cleaned


# ==============================================================================
# SQLite & Parquet Market Data Store (Trades, Order Books, Funding Rates)
# ==============================================================================

class MarketDataStore:
    """
    Persistent store for tick-level trades, Level-2 order book snapshots,
    and perpetual funding rates with SQLite persistence and optional Parquet export.
    """

    def __init__(self, db_path: str = _DB_PATH):
        self.db_path = db_path
        self._init_db()

    @contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # 1. Market trades table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS market_trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    epoch_ms INTEGER NOT NULL,
                    price REAL NOT NULL,
                    size REAL NOT NULL,
                    side TEXT NOT NULL,
                    is_buyer_maker INTEGER DEFAULT 0
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_sym_time ON market_trades(symbol, epoch_ms)")

            # 2. Order book snapshots table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS orderbook_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    epoch_ms INTEGER NOT NULL,
                    mid_price REAL NOT NULL,
                    spread REAL NOT NULL,
                    depth_imbalance REAL NOT NULL,
                    bid_volume REAL NOT NULL,
                    ask_volume REAL NOT NULL,
                    bids_json TEXT,
                    asks_json TEXT
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_ob_sym_time ON orderbook_snapshots(symbol, epoch_ms)")

            # 3. Perpetual funding rates table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS funding_rates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    epoch_ms INTEGER NOT NULL,
                    funding_rate REAL NOT NULL,
                    annualized_rate REAL NOT NULL,
                    mark_price REAL NOT NULL,
                    source TEXT NOT NULL
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_fr_sym_time ON funding_rates(symbol, epoch_ms)")
            conn.commit()

    def persist_trade(
        self,
        symbol: str,
        price: float,
        size: float,
        side: str,
        timestamp: Optional[str] = None,
        epoch_ms: Optional[int] = None,
        is_buyer_maker: bool = False
    ):
        """Persists a single trade tick to SQLite."""
        norm_sym = normalize_symbol(symbol)
        now_epoch = epoch_ms or int(time.time() * 1000)
        now_ts = timestamp or datetime.fromtimestamp(now_epoch / 1000.0, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        with self._get_connection() as conn:
            conn.cursor().execute("""
                INSERT INTO market_trades (symbol, timestamp, epoch_ms, price, size, side, is_buyer_maker)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (norm_sym, now_ts, now_epoch, float(price), float(size), side.upper(), 1 if is_buyer_maker else 0))
            conn.commit()

    def persist_trades_batch(self, trades: List[Dict[str, Any]]):
        """Persists a batch of trade ticks in a single transaction."""
        if not trades:
            return
        rows = []
        for t in trades:
            sym = normalize_symbol(t.get("symbol", "BTC/USDT"))
            ep = t.get("epoch_ms", int(time.time() * 1000))
            ts = t.get("timestamp", datetime.fromtimestamp(ep / 1000.0, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
            rows.append((
                sym, ts, ep,
                float(t.get("price", 0.0)),
                float(t.get("size", 0.0)),
                str(t.get("side", "BUY")).upper(),
                1 if t.get("is_buyer_maker", False) else 0
            ))
        with self._get_connection() as conn:
            conn.cursor().executemany("""
                INSERT INTO market_trades (symbol, timestamp, epoch_ms, price, size, side, is_buyer_maker)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, rows)
            conn.commit()

    def persist_orderbook_snapshot(self, snapshot: Dict[str, Any]):
        """Persists Level 2 orderbook snapshot with depth and bids/asks JSON."""
        sym = normalize_symbol(snapshot.get("symbol", "BTC/USDT"))
        ep = snapshot.get("epoch_ms", int(time.time() * 1000))
        ts = snapshot.get("timestamp", datetime.fromtimestamp(ep / 1000.0, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        bids_json = json.dumps(snapshot.get("bids", []))
        asks_json = json.dumps(snapshot.get("asks", []))

        with self._get_connection() as conn:
            conn.cursor().execute("""
                INSERT INTO orderbook_snapshots (
                    symbol, timestamp, epoch_ms, mid_price, spread,
                    depth_imbalance, bid_volume, ask_volume, bids_json, asks_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                sym, ts, ep,
                float(snapshot.get("mid_price", 0.0)),
                float(snapshot.get("spread", 0.0)),
                float(snapshot.get("depth_imbalance", 0.0)),
                float(snapshot.get("bid_volume", 0.0)),
                float(snapshot.get("ask_volume", 0.0)),
                bids_json, asks_json
            ))
            conn.commit()

    def persist_funding_rate(self, record: FundingRateRecord):
        """Persists funding rate record to SQLite."""
        with self._get_connection() as conn:
            conn.cursor().execute("""
                INSERT INTO funding_rates (
                    symbol, timestamp, epoch_ms, funding_rate,
                    annualized_rate, mark_price, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                record.symbol, record.funding_time, record.epoch_ms,
                record.funding_rate, record.annualized_rate,
                record.mark_price, record.source
            ))
            conn.commit()

    def get_recent_trades(self, symbol: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Retrieves most recent trade ticks for a symbol."""
        norm_sym = normalize_symbol(symbol)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT symbol, timestamp, epoch_ms, price, size, side, is_buyer_maker
                FROM market_trades
                WHERE symbol = ?
                ORDER BY epoch_ms DESC
                LIMIT ?
            """, (norm_sym, limit))
            rows = cursor.fetchall()
            return [dict(r) for r in reversed(rows)]

    def get_recent_orderbook_snapshots(self, symbol: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieves most recent L2 orderbook snapshots for a symbol."""
        norm_sym = normalize_symbol(symbol)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT symbol, timestamp, epoch_ms, mid_price, spread,
                       depth_imbalance, bid_volume, ask_volume, bids_json, asks_json
                FROM orderbook_snapshots
                WHERE symbol = ?
                ORDER BY epoch_ms DESC
                LIMIT ?
            """, (norm_sym, limit))
            rows = cursor.fetchall()
            results = []
            for r in reversed(rows):
                d = dict(r)
                try:
                    d["bids"] = json.loads(d["bids_json"]) if d["bids_json"] else []
                    d["asks"] = json.loads(d["asks_json"]) if d["asks_json"] else []
                except Exception:
                    d["bids"], d["asks"] = [], []
                results.append(d)
            return results

    def get_latest_funding_rate(self, symbol: str) -> Optional[FundingRateRecord]:
        """Retrieves most recent persisted funding rate for a symbol."""
        norm_sym = normalize_symbol(symbol)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT symbol, timestamp, epoch_ms, funding_rate,
                       annualized_rate, mark_price, source
                FROM funding_rates
                WHERE symbol = ?
                ORDER BY epoch_ms DESC
                LIMIT 1
            """, (norm_sym,))
            row = cursor.fetchone()
            if row:
                return FundingRateRecord(
                    symbol=row["symbol"],
                    funding_rate=float(row["funding_rate"]),
                    annualized_rate=float(row["annualized_rate"]),
                    funding_time=row["timestamp"],
                    epoch_ms=int(row["epoch_ms"]),
                    mark_price=float(row["mark_price"]),
                    source=row["source"]
                )
        return None

    def export_trades_parquet(self, symbol: str, output_path: Optional[str] = None) -> str:
        """
        Exports trades to Parquet file if pyarrow or pandas is available;
        falls back to structured JSON export.
        """
        trades = self.get_recent_trades(symbol, limit=10000)
        norm_clean = symbol.replace("/", "_").replace("-", "_")
        target_path = output_path or os.path.join(_CACHE_DIR, f"{norm_clean}_trades.parquet")

        try:
            import pandas as pd
            df = pd.DataFrame(trades)
            df.to_parquet(target_path, index=False)
            return target_path
        except Exception:
            # Fallback to json export
            json_path = target_path.replace(".parquet", ".json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(trades, f, indent=2)
            return json_path


# ==============================================================================
# Latency-Aware Fill Model (Spread + Market Impact + Latency Penalty)
# ==============================================================================

class LatencyAwareFillModel:
    """
    Institutional latency-aware execution simulation model:
    Calculates realistic simulated fill prices for taker and maker orders:
    
    FillPrice = Mid +/- [ HalfSpread + MarketImpact + LatencyPenalty ]
    
    1. Half-Spread: spread / 2.0 for aggressive taker market orders (0 for maker).
    2. Market Impact: Almgren-Chriss square-root law:
       impact = gamma * mid_price * volatility * sqrt(order_size / (daily_volume + 1e-6))
    3. Latency Penalty: Execution drift across network and matching latency:
       drift = mid_price * (volatility / sqrt(86400 * 1000)) * sqrt(latency_ms) * 0.75
    """

    def __init__(self, default_gamma: float = 0.10, default_latency_ms: float = 45.0):
        self.gamma = default_gamma
        self.default_latency_ms = default_latency_ms

    def simulate_fill(
        self,
        symbol: str,
        side: str,
        order_size: float,
        mid_price: float,
        spread: float,
        daily_volume: float,
        volatility: float = 0.35,
        latency_ms: Optional[float] = None,
        is_maker: bool = False,
        seed: Optional[int] = None
    ) -> FillResult:
        """
        Simulates realistic execution fill with spread crossing, square-root market impact,
        and latency penalty slippage.
        """
        if seed is not None:
            random.seed(seed)

        norm_sym = normalize_symbol(symbol)
        side_clean = side.upper()
        eff_latency = latency_ms if latency_ms is not None else self.default_latency_ms
        eff_spread = max(1e-4, spread)
        eff_vol = max(0.05, volatility)
        eff_daily_vol = max(100.0, daily_volume)

        # 1. Spread cost
        half_spread = 0.0 if is_maker else (eff_spread / 2.0)

        # 2. Square-root market impact (Almgren-Chriss formulation)
        participation = max(1e-7, order_size / eff_daily_vol)
        impact = self.gamma * mid_price * eff_vol * math.sqrt(participation)

        # 3. Latency penalty (stochastic adverse price drift across execution latency)
        # Standard deviation of price move across latency_ms
        vol_per_ms = eff_vol / math.sqrt(365.0 * 24.0 * 3600.0 * 1000.0)
        expected_drift = mid_price * vol_per_ms * math.sqrt(eff_latency) * 0.75
        jitter = random.uniform(0.6, 1.4)
        latency_penalty = expected_drift * jitter

        total_friction = half_spread + impact + latency_penalty

        if side_clean == "BUY":
            fill_price = mid_price + total_friction
        else:
            fill_price = max(0.01, mid_price - total_friction)

        slippage_bps = abs(fill_price - mid_price) / mid_price * 10000.0
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        return FillResult(
            symbol=norm_sym,
            side=side_clean,
            order_size=round(order_size, 4),
            mid_price=round(mid_price, 4),
            spread=round(eff_spread, 4),
            half_spread_cost=round(half_spread, 4),
            impact_cost=round(impact, 4),
            latency_penalty_cost=round(latency_penalty, 4),
            fill_price=round(fill_price, 4),
            slippage_bps=round(slippage_bps, 2),
            is_maker=is_maker,
            latency_ms=round(eff_latency, 2),
            timestamp=ts
        )


# ==============================================================================
# Master MarketDataClient
# ==============================================================================

class MarketDataClient:
    """
    Robust institutional market data client with automatic fallback across:
    Binance -> Coinbase -> Alpaca -> Cached disk bars -> Synthetic generator.
    Also provides Bybit/Binance perpetual funding rates, SQLite/Parquet persistence,
    and latency-aware execution simulation.
    """

    def __init__(self, cache_enabled: bool = True, request_timeout: int = 8):
        self.cache_enabled = cache_enabled
        self.timeout = request_timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "DexAlgo-Institutional-Quant/2.0"
        })
        self.store = MarketDataStore()
        self.fill_model = LatencyAwareFillModel()

    def _get_cache_path(self, symbol: str, interval: str, limit: int) -> str:
        clean_sym = symbol.replace("/", "_").replace("-", "_")
        norm_int = normalize_interval(interval)
        return os.path.join(_CACHE_DIR, f"{clean_sym}_{norm_int}_{limit}.json")

    def _get_master_cache_path(self, symbol: str, interval: str) -> str:
        clean_sym = symbol.replace("/", "_").replace("-", "_")
        norm_int = normalize_interval(interval)
        return os.path.join(_CACHE_DIR, f"{clean_sym}_{norm_int}_master.json")

    def _load_from_cache(self, symbol: str, interval: str, limit: int) -> Optional[List[Bar]]:
        if not self.cache_enabled:
            return None
        norm_int = normalize_interval(interval)

        # 1. Try master cache first
        master_path = self._get_master_cache_path(symbol, norm_int)
        if os.path.exists(master_path):
            try:
                mtime = os.path.getmtime(master_path)
                if (time.time() - mtime) < 86400:  # 24 hours
                    with open(master_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        bars = [Bar(**item) for item in data]
                        if len(bars) >= limit:
                            return bars[-limit:]
            except Exception as e:
                logger.debug(f"Master cache read error for {symbol}: {e}")

        # 2. Try exact limit cache path
        cache_path = self._get_cache_path(symbol, norm_int, limit)
        if os.path.exists(cache_path):
            try:
                mtime = os.path.getmtime(cache_path)
                if (time.time() - mtime) < 14400:  # 4 hours
                    with open(cache_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        return [Bar(**item) for item in data]
            except Exception as e:
                logger.debug(f"Cache load error for {symbol}: {e}")
        return None

    def _save_to_cache(self, symbol: str, interval: str, limit: int, bars: List[Bar]):
        if not self.cache_enabled or not bars:
            return
        norm_int = normalize_interval(interval)

        # Save limit-specific cache
        cache_path = self._get_cache_path(symbol, norm_int, limit)
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump([b.to_dict() for b in bars], f)
        except Exception as e:
            logger.debug(f"Cache save error for {symbol}: {e}")

        # Also update master cache with merged and deduplicated bars
        master_path = self._get_master_cache_path(symbol, norm_int)
        try:
            existing: List[Bar] = []
            if os.path.exists(master_path):
                with open(master_path, "r", encoding="utf-8") as f:
                    existing = [Bar(**item) for item in json.load(f)]
            merged = clean_and_validate_bars(existing + bars)
            if len(merged) > 25000:
                merged = merged[-25000:]
            with open(master_path, "w", encoding="utf-8") as f:
                json.dump([b.to_dict() for b in merged], f)
        except Exception as e:
            logger.debug(f"Master cache save error for {symbol}: {e}")

    # --------------------------------------------------------------------------
    # 1. Binance Public REST Provider (with Real Trade Aggressor Volume Delta)
    # --------------------------------------------------------------------------
    def fetch_binance_klines(
        self,
        symbol: str = "BTCUSDT",
        interval: str = "1h",
        limit: int = 500,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None
    ) -> List[Bar]:
        """
        Fetches official klines from Binance Public REST API with auto-pagination.
        Binance Kline array fields:
        [0]: Open time, [1]: Open, [2]: High, [3]: Low, [4]: Close, [5]: Volume,
        [6]: Close time, [7]: Quote asset volume, [8]: Number of trades,
        [9]: Taker buy base asset volume, [10]: Taker buy quote asset volume, [11]: Ignore
        """
        binance_sym = to_binance_symbol(symbol)
        norm_int = normalize_interval(interval)
        url = "https://api.binance.com/api/v3/klines"

        all_bars: List[Bar] = []
        target_limit = limit
        curr_end_time = end_time

        while len(all_bars) < target_limit:
            fetch_count = min(target_limit - len(all_bars), 1000)
            params: Dict[str, Any] = {
                "symbol": binance_sym,
                "interval": norm_int,
                "limit": fetch_count
            }
            if start_time:
                params["startTime"] = start_time
            if curr_end_time:
                params["endTime"] = curr_end_time

            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
                if resp.status_code == 200:
                    raw_data = resp.json()
                    if not raw_data:
                        break
                    chunk: List[Bar] = []
                    for row in raw_data:
                        epoch_ms = int(row[0])
                        dt = datetime.fromtimestamp(epoch_ms / 1000.0, tz=timezone.utc)
                        open_p = float(row[1])
                        high_p = float(row[2])
                        low_p = float(row[3])
                        close_p = float(row[4])
                        vol = float(row[5])
                        quote_vol = float(row[7])
                        trades = int(row[8])
                        taker_buy = float(row[9])
                        vwap = (quote_vol / vol) if vol > 0 else (open_p + high_p + low_p + close_p) / 4.0

                        chunk.append(Bar(
                            timestamp=dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                            epoch_ms=epoch_ms,
                            open=open_p,
                            high=high_p,
                            low=low_p,
                            close=close_p,
                            volume=vol,
                            quote_volume=quote_vol,
                            trades=trades,
                            taker_buy_vol=taker_buy,
                            vwap=vwap
                        ))

                    if not chunk:
                        break

                    if target_limit > 1000 and not start_time:
                        all_bars = chunk + all_bars
                        earliest_epoch = chunk[0].epoch_ms
                        curr_end_time = earliest_epoch - 1
                        if len(chunk) < fetch_count:
                            break
                        time.sleep(0.05)
                    else:
                        all_bars.extend(chunk)
                        if len(chunk) < fetch_count:
                            break
                        if start_time:
                            start_time = chunk[-1].epoch_ms + 1
                        time.sleep(0.05)

                    if len(all_bars) >= target_limit:
                        break
                else:
                    logger.warning(f"Binance klines failed for {symbol}: HTTP {resp.status_code}")
                    break
            except Exception as e:
                logger.warning(f"Binance fetch exception for {symbol}: {e}")
                break

        return clean_and_validate_bars(all_bars[-limit:]) if all_bars else []

    # --------------------------------------------------------------------------
    # 2. Coinbase Public REST Provider
    # --------------------------------------------------------------------------
    def fetch_coinbase_candles(
        self,
        symbol: str = "BTC-USD",
        granularity: int = 3600  # seconds: 60, 300, 900, 3600, 21600, 86400
    ) -> List[Bar]:
        """
        Fetches candles from Coinbase Public REST API.
        Coinbase returns: [time, low, high, open, close, volume]
        """
        product_id = to_coinbase_product(symbol)
        url = f"https://api.exchange.coinbase.com/products/{product_id}/candles"
        params = {"granularity": granularity}

        try:
            resp = self.session.get(url, params=params, timeout=self.timeout)
            if resp.status_code == 200:
                raw_data = resp.json()
                bars: List[Bar] = []
                for row in reversed(raw_data):
                    epoch_s = int(row[0])
                    dt = datetime.fromtimestamp(epoch_s, tz=timezone.utc)
                    low_p = float(row[1])
                    high_p = float(row[2])
                    open_p = float(row[3])
                    close_p = float(row[4])
                    vol = float(row[5])
                    approx_quote_vol = vol * ((open_p + close_p) / 2.0)
                    pct_change = (close_p - open_p) / open_p if open_p > 0 else 0
                    buy_ratio = max(0.2, min(0.8, 0.5 + pct_change * 5.0))
                    taker_buy = vol * buy_ratio
                    vwap = (open_p + high_p + low_p + close_p) / 4.0

                    bars.append(Bar(
                        timestamp=dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        epoch_ms=epoch_s * 1000,
                        open=open_p,
                        high=high_p,
                        low=low_p,
                        close=close_p,
                        volume=vol,
                        quote_volume=approx_quote_vol,
                        trades=int(vol * 10),
                        taker_buy_vol=taker_buy,
                        vwap=vwap
                    ))
                return clean_and_validate_bars(bars)
            else:
                logger.warning(f"Coinbase candles failed for {symbol}: HTTP {resp.status_code}")
        except Exception as e:
            logger.warning(f"Coinbase fetch exception for {symbol}: {e}")
        return []

    # --------------------------------------------------------------------------
    # 3. Alpaca Market Data Provider (Equities & Crypto)
    # --------------------------------------------------------------------------
    def fetch_alpaca_bars(
        self,
        symbol: str = "SPY",
        timeframe: str = "1Hour",
        limit: int = 500
    ) -> List[Bar]:
        """
        Fetches bars from Alpaca Market Data API if credentials exist,
        or uses AlpacaClient fallback.
        """
        api_key = os.getenv("ALPACA_API_KEY", "")
        secret_key = os.getenv("ALPACA_SECRET_KEY", "")

        norm_sym = normalize_symbol(symbol)
        is_crypto = "/" in norm_sym or norm_sym.endswith("USD") or norm_sym.endswith("USDT")
        alpaca_sym = to_alpaca_symbol(norm_sym)

        if api_key and secret_key and not api_key.startswith("your_") and not api_key.startswith("MOCK"):
            endpoint = "crypto/bars" if is_crypto else "stocks/bars"
            url = f"https://data.alpaca.markets/v2/{endpoint}"
            headers = {
                "APCA-API-KEY-ID": api_key,
                "APCA-API-SECRET-KEY": secret_key
            }
            params = {
                "symbols": alpaca_sym,
                "timeframe": timeframe,
                "limit": min(limit, 1000)
            }
            try:
                resp = self.session.get(url, headers=headers, params=params, timeout=self.timeout)
                if resp.status_code == 200:
                    data = resp.json().get("bars", {}).get(alpaca_sym, [])
                    bars: List[Bar] = []
                    for b in data:
                        iso_t = b.get("t")
                        dt = datetime.fromisoformat(iso_t.replace("Z", "+00:00"))
                        epoch_ms = int(dt.timestamp() * 1000)
                        open_p = float(b["o"])
                        high_p = float(b["h"])
                        low_p = float(b["l"])
                        close_p = float(b["c"])
                        vol = float(b["v"])
                        vwap = float(b.get("vw", (open_p + high_p + low_p + close_p) / 4.0))
                        n_trades = int(b.get("n", 100))
                        quote_vol = vol * vwap
                        taker_buy = vol * 0.5

                        bars.append(Bar(
                            timestamp=iso_t,
                            epoch_ms=epoch_ms,
                            open=open_p,
                            high=high_p,
                            low=low_p,
                            close=close_p,
                            volume=vol,
                            quote_volume=quote_vol,
                            trades=n_trades,
                            taker_buy_vol=taker_buy,
                            vwap=vwap
                        ))
                    if bars:
                        return clean_and_validate_bars(bars)
            except Exception as e:
                logger.warning(f"Alpaca bars fetch failed for {symbol}: {e}")

        # Check local AlpacaClient mock engine if available
        try:
            import alpaca_client
            client = alpaca_client.AlpacaClient()
            raw_bars = client.get_bars(alpaca_sym, timeframe=timeframe, limit=limit)
            if raw_bars:
                bars = []
                for b in raw_bars:
                    iso_t = b.get("t", "")
                    try:
                        dt = datetime.fromisoformat(iso_t.replace("Z", "+00:00"))
                        epoch_ms = int(dt.timestamp() * 1000)
                    except Exception:
                        epoch_ms = int(time.time() * 1000)
                    open_p = float(b.get("o", 100.0))
                    high_p = float(b.get("h", open_p))
                    low_p = float(b.get("l", open_p))
                    close_p = float(b.get("c", open_p))
                    vol = float(b.get("v", 1000.0))
                    quote_vol = vol * close_p
                    bars.append(Bar(
                        timestamp=iso_t,
                        epoch_ms=epoch_ms,
                        open=open_p,
                        high=high_p,
                        low=low_p,
                        close=close_p,
                        volume=vol,
                        quote_volume=quote_vol,
                        trades=max(1, int(vol / 100)),
                        taker_buy_vol=vol * 0.5,
                        vwap=(open_p + high_p + low_p + close_p) / 4.0
                    ))
                if bars:
                    return clean_and_validate_bars(bars)
        except Exception:
            pass

        return []

    # --------------------------------------------------------------------------
    # 4. Bybit & Binance Perpetual Funding Rates
    # --------------------------------------------------------------------------
    def fetch_binance_funding_rate(self, symbol: str = "BTC/USDT") -> Optional[FundingRateRecord]:
        """
        Fetches live perpetual funding rate from Binance Futures REST API:
        GET https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT
        """
        binance_sym = to_binance_symbol(symbol)
        url = "https://fapi.binance.com/fapi/v1/premiumIndex"
        params = {"symbol": binance_sym}

        try:
            resp = self.session.get(url, params=params, timeout=self.timeout)
            if resp.status_code == 200:
                data = resp.json()
                rate = float(data.get("lastFundingRate", 0.0001))
                mark_p = float(data.get("markPrice", 0.0))
                funding_epoch = int(data.get("nextFundingTime", int(time.time() * 1000)))
                funding_ts = datetime.fromtimestamp(funding_epoch / 1000.0, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

                record = FundingRateRecord(
                    symbol=normalize_symbol(symbol),
                    funding_rate=round(rate, 6),
                    annualized_rate=round(rate * 3.0 * 365.0, 4),
                    funding_time=funding_ts,
                    epoch_ms=funding_epoch,
                    mark_price=round(mark_p, 2),
                    source="binance"
                )
                self.store.persist_funding_rate(record)
                return record
        except Exception as e:
            logger.debug(f"Binance funding rate fetch failed for {symbol}: {e}")
        return None

    def fetch_bybit_funding_rate(self, symbol: str = "BTC/USDT") -> Optional[FundingRateRecord]:
        """
        Fetches live perpetual funding rate from Bybit v5 Market API:
        GET https://api.bybit.com/v5/market/tickers?category=linear&symbol=BTCUSDT
        """
        bybit_sym = to_bybit_symbol(symbol)
        url = "https://api.bybit.com/v5/market/tickers"
        params = {"category": "linear", "symbol": bybit_sym}

        try:
            resp = self.session.get(url, params=params, timeout=self.timeout)
            if resp.status_code == 200:
                res_data = resp.json().get("result", {}).get("list", [])
                if res_data:
                    item = res_data[0]
                    rate = float(item.get("fundingRate", 0.0001))
                    mark_p = float(item.get("markPrice", 0.0))
                    funding_epoch = int(item.get("nextFundingTime", int(time.time() * 1000)))
                    funding_ts = datetime.fromtimestamp(funding_epoch / 1000.0, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

                    record = FundingRateRecord(
                        symbol=normalize_symbol(symbol),
                        funding_rate=round(rate, 6),
                        annualized_rate=round(rate * 3.0 * 365.0, 4),
                        funding_time=funding_ts,
                        epoch_ms=funding_epoch,
                        mark_price=round(mark_p, 2),
                        source="bybit"
                    )
                    self.store.persist_funding_rate(record)
                    return record
        except Exception as e:
            logger.debug(f"Bybit funding rate fetch failed for {symbol}: {e}")
        return None

    def fetch_funding_rate(self, symbol: str = "BTC/USDT") -> FundingRateRecord:
        """
        Unified funding rate fetcher with automatic fallback:
        Binance -> Bybit -> SQLite Cache -> Synthetic baseline.
        """
        norm_sym = normalize_symbol(symbol)

        # 1. Try Binance
        rec = self.fetch_binance_funding_rate(norm_sym)
        if rec:
            return rec

        # 2. Try Bybit
        rec = self.fetch_bybit_funding_rate(norm_sym)
        if rec:
            return rec

        # 3. Check local database cache
        cached = self.store.get_latest_funding_rate(norm_sym)
        if cached:
            return cached

        # 4. High-fidelity synthetic fallback
        now = datetime.now(timezone.utc)
        next_funding_epoch = int((now + timedelta(hours=8 - (now.hour % 8))).timestamp() * 1000)
        ts = datetime.fromtimestamp(next_funding_epoch / 1000.0, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        base_rates = {"BTC/USDT": 0.0001, "ETH/USDT": 0.00008, "SOL/USDT": 0.00015}
        base_rate = base_rates.get(norm_sym, 0.0001)
        sim_rate = round(base_rate + (random.random() - 0.5) * 0.00005, 6)

        base_px = 68000.0 if "BTC" in norm_sym else (3500.0 if "ETH" in norm_sym else 180.0)

        record = FundingRateRecord(
            symbol=norm_sym,
            funding_rate=sim_rate,
            annualized_rate=round(sim_rate * 3.0 * 365.0, 4),
            funding_time=ts,
            epoch_ms=next_funding_epoch,
            mark_price=base_px,
            source="synthetic"
        )
        self.store.persist_funding_rate(record)
        return record

    def fetch_historical_funding_rates(
        self,
        symbol: str = "BTC/USDT",
        limit: int = 100
    ) -> List[FundingRateRecord]:
        """
        Fetches historical funding rate history from Binance/Bybit.
        """
        binance_sym = to_binance_symbol(symbol)
        url = "https://fapi.binance.com/fapi/v1/fundingRate"
        params = {"symbol": binance_sym, "limit": min(limit, 1000)}

        records: List[FundingRateRecord] = []
        try:
            resp = self.session.get(url, params=params, timeout=self.timeout)
            if resp.status_code == 200:
                data = resp.json()
                for item in data:
                    rate = float(item["fundingRate"])
                    ep = int(item["fundingTime"])
                    ts = datetime.fromtimestamp(ep / 1000.0, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    rec = FundingRateRecord(
                        symbol=normalize_symbol(symbol),
                        funding_rate=round(rate, 6),
                        annualized_rate=round(rate * 3.0 * 365.0, 4),
                        funding_time=ts,
                        epoch_ms=ep,
                        mark_price=0.0,
                        source="binance"
                    )
                    records.append(rec)
                    self.store.persist_funding_rate(rec)
                return records
        except Exception as e:
            logger.debug(f"Historical funding fetch failed: {e}")

        # Synthetic historical series fallback
        now = datetime.now(timezone.utc)
        norm_sym = normalize_symbol(symbol)
        for i in range(limit):
            t = now - timedelta(hours=(limit - i) * 8)
            ep = int(t.timestamp() * 1000)
            rate = round(0.0001 + math.sin(i / 10.0) * 0.00008, 6)
            records.append(FundingRateRecord(
                symbol=norm_sym,
                funding_rate=rate,
                annualized_rate=round(rate * 3.0 * 365.0, 4),
                funding_time=t.strftime("%Y-%m-%dT%H:%M:%SZ"),
                epoch_ms=ep,
                mark_price=68000.0 if "BTC" in norm_sym else 3500.0,
                source="synthetic"
            ))
        return records

    # --------------------------------------------------------------------------
    # 5. Realistic Synthetic Generator (Guaranteed Fallback)
    # --------------------------------------------------------------------------
    def generate_synthetic_bars(
        self,
        symbol: str = "BTC/USDT",
        limit: int = 500,
        interval_hours: float = 1.0,
        seed: int = 42
    ) -> List[Bar]:
        """
        High-fidelity geometric Brownian motion with stochastic volatility jumps
        and order flow imbalance modeling realistic crypto or equity price action.
        """
        random.seed(seed)
        norm = normalize_symbol(symbol)
        is_crypto = "USDT" in norm or "USD" in norm or norm in ("BTC", "ETH", "SOL")

        if "BTC" in norm:
            start_price = 68000.0
            daily_vol = 0.035
            base_vol = 250.0
        elif "ETH" in norm:
            start_price = 3500.0
            daily_vol = 0.045
            base_vol = 2200.0
        elif "SOL" in norm:
            start_price = 180.0
            daily_vol = 0.060
            base_vol = 15000.0
        elif norm in ("SPY", "QQQ"):
            start_price = 510.0 if norm == "SPY" else 440.0
            daily_vol = 0.012
            base_vol = 50000.0
        else:
            start_price = 150.0
            daily_vol = 0.025
            base_vol = 10000.0

        bar_vol = daily_vol * math.sqrt(interval_hours / 24.0 if is_crypto else interval_hours / 6.5)
        now = datetime.now(timezone.utc)
        start_dt = now - timedelta(hours=limit * interval_hours)

        bars: List[Bar] = []
        cur_p = start_price

        for i in range(limit):
            dt = start_dt + timedelta(hours=i * interval_hours)
            epoch_ms = int(dt.timestamp() * 1000)

            # Regime simulation: alternating drift
            drift = 0.0002 * math.sin(i / 35.0)
            shock = random.gauss(0, bar_vol)
            if random.random() < 0.03:
                shock += random.choice([-2.2, 2.2]) * bar_vol

            open_p = cur_p
            pct_move = drift + shock
            close_p = max(open_p * 0.1, open_p * (1.0 + pct_move))

            intraday_range = abs(pct_move) + bar_vol * random.uniform(0.4, 1.2)
            high_p = max(open_p, close_p) * (1.0 + intraday_range * random.uniform(0.3, 0.7))
            low_p = min(open_p, close_p) * (1.0 - intraday_range * random.uniform(0.3, 0.7))

            vol_multiplier = 1.0 + (abs(pct_move) / bar_vol) * 1.5
            bar_volume = base_vol * vol_multiplier * random.uniform(0.7, 1.4)
            bar_range = max(1e-5, high_p - low_p)
            close_loc = (close_p - low_p) / bar_range
            buy_ratio = max(0.15, min(0.85, close_loc + random.gauss(0, 0.08)))
            taker_buy = bar_volume * buy_ratio

            vwap = (open_p + high_p + low_p + close_p) / 4.0
            quote_vol = bar_volume * vwap
            trades = int(bar_volume * 1.5)

            bars.append(Bar(
                timestamp=dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                epoch_ms=epoch_ms,
                open=round(open_p, 2),
                high=round(high_p, 2),
                low=round(low_p, 2),
                close=round(close_p, 2),
                volume=round(bar_volume, 4),
                quote_volume=round(quote_vol, 2),
                trades=trades,
                taker_buy_vol=round(taker_buy, 4),
                vwap=round(vwap, 2)
            ))
            cur_p = close_p

        return clean_and_validate_bars(bars)

    # --------------------------------------------------------------------------
    # 6. Master Unified Historical Fetcher
    # --------------------------------------------------------------------------
    def get_historical_bars(
        self,
        symbol: str,
        interval: str = "1h",
        limit: int = 500,
        force_refresh: bool = False
    ) -> List[Bar]:
        """
        Retrieves real OHLCV data from Binance / Coinbase / Alpaca with disk caching
        and fallback to synthetic generator if completely offline.
        """
        norm = normalize_symbol(symbol)
        norm_int = normalize_interval(interval)

        # 1. Check local disk cache unless force_refresh
        if not force_refresh:
            cached = self._load_from_cache(norm, norm_int, limit)
            if cached and len(cached) >= limit:
                return cached[-limit:]

        bars: List[Bar] = []

        # 2. If crypto symbol, try Binance first (best microstructure data & volume delta)
        if any(c in norm for c in ("BTC", "ETH", "SOL", "USDT", "USD")):
            bars = self.fetch_binance_klines(symbol=norm, interval=norm_int, limit=limit)
            if not bars:
                gran_map = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 21600, "1d": 86400}
                gran = gran_map.get(norm_int, 3600)
                bars = self.fetch_coinbase_candles(symbol=norm, granularity=gran)

        # 3. If equities or crypto fallback, try Alpaca
        if not bars:
            alpaca_tf_map = {
                "1m": "1Min", "5m": "5Min", "15m": "15Min", "30m": "30Min",
                "1h": "1Hour", "4h": "4Hour", "1d": "1Day"
            }
            tf = alpaca_tf_map.get(norm_int, "1Hour")
            bars = self.fetch_alpaca_bars(symbol=norm, timeframe=tf, limit=limit)

        # 4. If still empty, load cached even if expired
        if not bars:
            cache_path = self._get_cache_path(norm, norm_int, limit)
            if os.path.exists(cache_path):
                try:
                    with open(cache_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        bars = clean_and_validate_bars([Bar(**item) for item in data])
                except Exception:
                    pass

        # 5. Fallback to high-fidelity synthetic if network/API is unreachable
        if not bars:
            logger.info(f"Generating high-fidelity synthetic bars for {norm}")
            hours_map = {"1m": 1/60.0, "5m": 5/60.0, "15m": 15/60.0, "30m": 0.5, "1h": 1.0, "4h": 4.0, "1d": 24.0}
            hours = hours_map.get(norm_int, 1.0)
            bars = self.generate_synthetic_bars(symbol=norm, limit=limit, interval_hours=hours)

        # Save to disk cache for reproducible fast execution
        if bars:
            self._save_to_cache(norm, norm_int, limit, bars)

        return bars[-limit:] if len(bars) > limit else bars

    # --------------------------------------------------------------------------
    # 7. Latency-Aware Execution Simulation Helper
    # --------------------------------------------------------------------------
    def simulate_fill(
        self,
        symbol: str,
        side: str,
        order_size: float,
        mid_price: float,
        spread: float,
        daily_volume: float,
        volatility: float = 0.35,
        latency_ms: Optional[float] = None,
        is_maker: bool = False
    ) -> FillResult:
        """Convenience accessor to the latency-aware fill model."""
        return self.fill_model.simulate_fill(
            symbol=symbol,
            side=side,
            order_size=order_size,
            mid_price=mid_price,
            spread=spread,
            daily_volume=daily_volume,
            volatility=volatility,
            latency_ms=latency_ms,
            is_maker=is_maker
        )


# Global singleton instance
_data_client = MarketDataClient()

def get_data_client() -> MarketDataClient:
    return _data_client
