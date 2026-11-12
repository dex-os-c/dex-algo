"""
Institutional Multi-Asset Data Layer
====================================
Production data layer supporting:
1. Binance Public REST (Real crypto OHLCV + Taker Buy Volume for order flow).
2. Coinbase Public REST (Spot candles for major crypto pairs).
3. Alpaca Market Data (US Equities + Crypto fallback).
4. Local on-disk persistent caching for fast, reproducible backtests.
5. Synthetic high-fidelity generator when operating fully offline.

All bar timestamps are normalized to UTC ISO-8601 strings or Unix millisecond epochs.
"""

import os
import sys
import json
import time
import math
import random
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Union, Tuple
from dataclasses import dataclass, asdict

import requests

logger = logging.getLogger("data_layer")

# Project directories
_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_BACKEND_DIR, ".."))
_CACHE_DIR = os.path.join(_PROJECT_ROOT, ".cache", "bars")
os.makedirs(_CACHE_DIR, exist_ok=True)


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


def normalize_symbol(symbol: str) -> str:
    """Normalize symbol to standard slash format: BTC/USDT, ETH/USDT, SPY, etc."""
    s = symbol.upper().replace("-", "").replace("_", "").strip()
    if "/" in symbol:
        parts = symbol.upper().split("/")
        return f"{parts[0]}/{parts[1]}"
    if s.endswith("USDT"):
        return f"{s[:-4]}/USDT"
    if s.endswith("USD"):
        return f"{s[:-3]}/USD"
    # Equity symbols: SPY, QQQ, AAPL, etc.
    return s


def to_binance_symbol(symbol: str) -> str:
    """Convert standard symbol to Binance symbol (e.g. BTCUSDT, ETHUSDT)."""
    norm = normalize_symbol(symbol)
    if "/" in norm:
        base, quote = norm.split("/")
        if quote == "USD":
            quote = "USDT"  # Binance uses USDT for spot
        return f"{base}{quote}"
    if norm in ("BTC", "ETH", "SOL", "BNB"):
        return f"{norm}USDT"
    return norm


def to_coinbase_product(symbol: str) -> str:
    """Convert standard symbol to Coinbase product id (e.g. BTC-USD, ETH-USD)."""
    norm = normalize_symbol(symbol)
    if "/" in norm:
        base, quote = norm.split("/")
        if quote == "USDT":
            quote = "USD"
        return f"{base}-{quote}"
    return f"{norm}-USD"


class MarketDataClient:
    """
    Robust institutional market data client with automatic fallback across:
    Binance -> Coinbase -> Alpaca -> Cached disk bars -> Synthetic generator.
    """

    def __init__(self, cache_enabled: bool = True, request_timeout: int = 8):
        self.cache_enabled = cache_enabled
        self.timeout = request_timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "DexAlgo-Institutional-Quant/2.0"
        })

    def _get_cache_path(self, symbol: str, interval: str, limit: int) -> str:
        clean_sym = symbol.replace("/", "_").replace("-", "_")
        return os.path.join(_CACHE_DIR, f"{clean_sym}_{interval}_{limit}.json")

    def _load_from_cache(self, symbol: str, interval: str, limit: int) -> Optional[List[Bar]]:
        if not self.cache_enabled:
            return None
        cache_path = self._get_cache_path(symbol, interval, limit)
        if os.path.exists(cache_path):
            try:
                # Check cache freshness (e.g. < 4 hours old for historical analysis)
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
        cache_path = self._get_cache_path(symbol, interval, limit)
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump([b.to_dict() for b in bars], f)
        except Exception as e:
            logger.debug(f"Cache save error for {symbol}: {e}")

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
        Fetches official klines from Binance Public REST API.
        Binance Kline array fields:
        [0]: Open time, [1]: Open, [2]: High, [3]: Low, [4]: Close, [5]: Volume,
        [6]: Close time, [7]: Quote asset volume, [8]: Number of trades,
        [9]: Taker buy base asset volume, [10]: Taker buy quote asset volume, [11]: Ignore
        """
        binance_sym = to_binance_symbol(symbol)
        url = "https://api.binance.com/api/v3/klines"
        params: Dict[str, Any] = {
            "symbol": binance_sym,
            "interval": interval,
            "limit": min(limit, 1000)
        }
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time

        try:
            resp = self.session.get(url, params=params, timeout=self.timeout)
            if resp.status_code == 200:
                raw_data = resp.json()
                bars: List[Bar] = []
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

                    bars.append(Bar(
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
                return bars
            else:
                logger.warning(f"Binance klines failed for {symbol}: HTTP {resp.status_code}")
        except Exception as e:
            logger.warning(f"Binance fetch exception for {symbol}: {e}")
        return []

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
                # Coinbase returns newest first; reverse to chronological order
                for row in reversed(raw_data):
                    epoch_s = int(row[0])
                    dt = datetime.fromtimestamp(epoch_s, tz=timezone.utc)
                    low_p = float(row[1])
                    high_p = float(row[2])
                    open_p = float(row[3])
                    close_p = float(row[4])
                    vol = float(row[5])
                    approx_quote_vol = vol * ((open_p + close_p) / 2.0)
                    # Proxy taker buy volume as 50% +/- price direction
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
                return bars
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
        Fetches bars from Alpaca Market Data API if credentials exist.
        """
        api_key = os.getenv("ALPACA_API_KEY", "")
        secret_key = os.getenv("ALPACA_SECRET_KEY", "")
        if not api_key or not secret_key:
            return []

        is_crypto = "/" in symbol or symbol.upper().endswith("USD")
        endpoint = "crypto/bars" if is_crypto else "stocks/bars"
        url = f"https://data.alpaca.markets/v2/{endpoint}"
        headers = {
            "APCA-API-KEY-ID": api_key,
            "APCA-API-SECRET-KEY": secret_key
        }
        params = {
            "symbols": symbol,
            "timeframe": timeframe,
            "limit": limit
        }
        try:
            resp = self.session.get(url, headers=headers, params=params, timeout=self.timeout)
            if resp.status_code == 200:
                data = resp.json().get("bars", {}).get(symbol, [])
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
                    taker_buy = vol * 0.5  # Alpaca stocks doesn't give taker buy vol

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
                return bars
        except Exception as e:
            logger.warning(f"Alpaca bars fetch failed for {symbol}: {e}")
        return []

    # --------------------------------------------------------------------------
    # 4. Realistic Synthetic Generator (Guaranteed Fallback)
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
            # Occasional jump shock (liquidity sweep)
            if random.random() < 0.03:
                shock += random.choice([-2.2, 2.2]) * bar_vol

            open_p = cur_p
            pct_move = drift + shock
            close_p = max(open_p * 0.1, open_p * (1.0 + pct_move))

            intraday_range = abs(pct_move) + bar_vol * random.uniform(0.4, 1.2)
            high_p = max(open_p, close_p) * (1.0 + intraday_range * random.uniform(0.3, 0.7))
            low_p = min(open_p, close_p) * (1.0 - intraday_range * random.uniform(0.3, 0.7))

            # Realistic volume with spikes on high volatility
            vol_multiplier = 1.0 + (abs(pct_move) / bar_vol) * 1.5
            bar_volume = base_vol * vol_multiplier * random.uniform(0.7, 1.4)
            # Taker buy proportion depends on close position relative to range
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

        return bars

    # --------------------------------------------------------------------------
    # 5. Master Unified Historical Fetcher
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

        # 1. Check local disk cache unless force_refresh
        if not force_refresh:
            cached = self._load_from_cache(norm, interval, limit)
            if cached and len(cached) >= limit:
                return cached[-limit:]

        bars: List[Bar] = []

        # 2. If crypto symbol, try Binance first (best microstructure data)
        if any(c in norm for c in ("BTC", "ETH", "SOL", "USDT", "USD")):
            bars = self.fetch_binance_klines(symbol=norm, interval=interval, limit=limit)
            if not bars:
                # Try Coinbase
                gran_map = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "1d": 86400}
                gran = gran_map.get(interval, 3600)
                bars = self.fetch_coinbase_candles(symbol=norm, granularity=gran)

        # 3. If equities, try Alpaca
        if not bars:
            alpaca_tf_map = {"1m": "1Min", "5m": "5Min", "15m": "15Min", "1h": "1Hour", "1d": "1Day"}
            tf = alpaca_tf_map.get(interval, "1Hour")
            bars = self.fetch_alpaca_bars(symbol=norm, timeframe=tf, limit=limit)

        # 4. If still empty, load cached even if expired
        if not bars:
            cache_path = self._get_cache_path(norm, interval, limit)
            if os.path.exists(cache_path):
                try:
                    with open(cache_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        bars = [Bar(**item) for item in data]
                except Exception:
                    pass

        # 5. Fallback to high-fidelity synthetic if network/API is unreachable
        if not bars:
            logger.info(f"Generating high-fidelity synthetic bars for {norm}")
            hours = 1.0 if interval == "1h" else (24.0 if interval == "1d" else 0.25)
            bars = self.generate_synthetic_bars(symbol=norm, limit=limit, interval_hours=hours)

        # Save to disk cache for reproducible fast execution
        if bars:
            self._save_to_cache(norm, interval, limit, bars)

        return bars[-limit:] if len(bars) > limit else bars


# Global singleton instance
_data_client = MarketDataClient()

def get_data_client() -> MarketDataClient:
    return _data_client
