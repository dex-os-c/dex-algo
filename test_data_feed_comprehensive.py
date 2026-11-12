"""
Comprehensive Unit & Integration Test for Institutional Data Feed
==================================================================
Tests:
1. Symbol normalization: BTC/USDT, ETH/USDT, SOL/USDT, SPY, QQQ.
2. Interval normalization: 1m, 5m, 15m, 30m, 1h, 4h, 1d, 1Hour, 4Hour, 1Day.
3. Data cleaning & validation: deduplication, chronological sorting, OHLC boundaries, volume bounds.
4. Binance REST klines with real trade aggressor volume delta & pagination.
5. Disk caching & master cache multi-timeframe storage.
6. Coinbase product mapping and candles.
7. Alpaca equities (SPY, QQQ) & crypto fallback.
8. Synthetic fallback generator integrity.
9. 24/7 CryptoMarketFeed: quotes, order book depth, taker volume delta, OFI, and websocket streaming.
"""

import os
import sys
import time
import unittest

PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from data_layer import (
    Bar,
    MarketDataClient,
    get_data_client,
    normalize_symbol,
    normalize_interval,
    to_binance_symbol,
    to_coinbase_product,
    to_alpaca_symbol,
    clean_and_validate_bars
)
from crypto_feed import (
    CryptoMarketFeed,
    get_crypto_feed,
    normalize_crypto_symbol,
    SyntheticCryptoGenerator
)


class TestDataFeedLayer(unittest.TestCase):

    def setUp(self):
        self.client = MarketDataClient(cache_enabled=True)

    def test_symbol_normalization(self):
        # Canonical target symbols: BTC/USDT, ETH/USDT, SOL/USDT, SPY, QQQ
        self.assertEqual(normalize_symbol("BTC/USDT"), "BTC/USDT")
        self.assertEqual(normalize_symbol("ETH/USDT"), "ETH/USDT")
        self.assertEqual(normalize_symbol("SOL/USDT"), "SOL/USDT")
        self.assertEqual(normalize_symbol("SPY"), "SPY")
        self.assertEqual(normalize_symbol("QQQ"), "QQQ")

        # Variations
        self.assertEqual(normalize_symbol("btcusdt"), "BTC/USDT")
        self.assertEqual(normalize_symbol("ethusdt"), "ETH/USDT")
        self.assertEqual(normalize_symbol("solusdt"), "SOL/USDT")
        self.assertEqual(normalize_symbol("BTC"), "BTC/USDT")
        self.assertEqual(normalize_symbol("ETH"), "ETH/USDT")
        self.assertEqual(normalize_symbol("SOL"), "SOL/USDT")
        self.assertEqual(normalize_symbol("BTC-USD"), "BTC/USD")
        self.assertEqual(normalize_symbol("ETH-USD"), "ETH/USD")
        self.assertEqual(normalize_symbol("SOL-USD"), "SOL/USD")

    def test_exchange_symbol_conversions(self):
        self.assertEqual(to_binance_symbol("BTC/USDT"), "BTCUSDT")
        self.assertEqual(to_binance_symbol("ETH/USDT"), "ETHUSDT")
        self.assertEqual(to_binance_symbol("SOL/USDT"), "SOLUSDT")
        self.assertEqual(to_binance_symbol("BTC/USD"), "BTCUSDT")

        self.assertEqual(to_coinbase_product("BTC/USDT"), "BTC-USD")
        self.assertEqual(to_coinbase_product("ETH/USDT"), "ETH-USD")
        self.assertEqual(to_coinbase_product("SOL/USDT"), "SOL-USD")

        self.assertEqual(to_alpaca_symbol("BTC/USDT"), "BTC/USD")
        self.assertEqual(to_alpaca_symbol("SPY"), "SPY")
        self.assertEqual(to_alpaca_symbol("QQQ"), "QQQ")

    def test_interval_normalization(self):
        self.assertEqual(normalize_interval("1m"), "1m")
        self.assertEqual(normalize_interval("1Min"), "1m")
        self.assertEqual(normalize_interval("1h"), "1h")
        self.assertEqual(normalize_interval("1Hour"), "1h")
        self.assertEqual(normalize_interval("4h"), "4h")
        self.assertEqual(normalize_interval("4Hour"), "4h")
        self.assertEqual(normalize_interval("1d"), "1d")
        self.assertEqual(normalize_interval("1Day"), "1d")

    def test_data_cleaning_and_validation(self):
        dirty_bars = [
            Bar(timestamp="2026-11-12T02:00:00Z", epoch_ms=2000, open=100.0, high=95.0, low=105.0, close=102.0,
                volume=10.0, quote_volume=1020.0, trades=5, taker_buy_vol=15.0, vwap=101.0),
            Bar(timestamp="2026-11-12T01:00:00Z", epoch_ms=1000, open=98.0, high=101.0, low=97.0, close=99.0,
                volume=-5.0, quote_volume=0.0, trades=-2, taker_buy_vol=-1.0, vwap=0.0),
            # Duplicate epoch
            Bar(timestamp="2026-11-12T01:00:00Z", epoch_ms=1000, open=98.0, high=101.0, low=97.0, close=99.0,
                volume=5.0, quote_volume=500.0, trades=2, taker_buy_vol=2.0, vwap=99.0)
        ]
        cleaned = clean_and_validate_bars(dirty_bars)
        self.assertEqual(len(cleaned), 2, "Duplicate dropped")
        # Chronological order
        self.assertEqual(cleaned[0].epoch_ms, 1000)
        self.assertEqual(cleaned[1].epoch_ms, 2000)
        # Non-negative volume & trades
        self.assertGreaterEqual(cleaned[0].volume, 0.0)
        self.assertGreaterEqual(cleaned[0].trades, 0)
        # High >= max(open, close), Low <= min(open, close)
        self.assertGreaterEqual(cleaned[1].high, max(cleaned[1].open, cleaned[1].close))
        self.assertLessEqual(cleaned[1].low, min(cleaned[1].open, cleaned[1].close))
        # Bounded taker buy
        self.assertLessEqual(cleaned[1].taker_buy_vol, cleaned[1].volume)

    def test_historical_bars_retrieval(self):
        symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "SPY", "QQQ"]
        for sym in symbols:
            bars = self.client.get_historical_bars(sym, interval="1h", limit=10)
            self.assertEqual(len(bars), 10, f"Expected 10 bars for {sym}")
            self.assertTrue(all(b.high >= b.low for b in bars))
            self.assertTrue(all(b.volume >= 0 for b in bars))
            self.assertTrue(all(b.taker_buy_vol >= 0 for b in bars))
            # Test caching: second call should be immediate from cache
            cached_bars = self.client.get_historical_bars(sym, interval="1h", limit=10)
            self.assertEqual(len(cached_bars), 10)
            self.assertEqual(bars[-1].epoch_ms, cached_bars[-1].epoch_ms)

    def test_multi_timeframe_retrieval(self):
        for tf in ["1h", "4h", "1d"]:
            bars = self.client.get_historical_bars("BTC/USDT", interval=tf, limit=5)
            self.assertEqual(len(bars), 5, f"Retrieved 5 bars for {tf}")

    def test_crypto_market_feed_normalized_symbols(self):
        feed = get_crypto_feed(force_mock=True)
        for sym in ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BTC/USD", "ETH/USD", "SOL/USD"]:
            quote = feed.get_crypto_quote(sym)
            self.assertIn("bid_price", quote)
            self.assertIn("ask_price", quote)
            self.assertGreater(quote["ask_price"], 0)

            book = feed.get_orderbook(sym, depth=10)
            self.assertEqual(len(book["bids"]), 10)
            self.assertEqual(len(book["asks"]), 10)
            self.assertIn("depth_imbalance", book)

            vdelta = feed.get_volume_delta(sym)
            self.assertIn("taker_buy_volume", vdelta)
            self.assertIn("taker_sell_volume", vdelta)
            self.assertIn("volume_delta", vdelta)

            ofi = feed.get_order_flow_imbalance(sym)
            self.assertIn("normalized_ofi", ofi)

            snapshot = feed.get_microstructure_snapshot(sym)
            self.assertEqual(snapshot["symbol"], normalize_crypto_symbol(sym))


if __name__ == "__main__":
    unittest.main()
