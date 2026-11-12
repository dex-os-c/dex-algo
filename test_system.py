#!/usr/bin/env python3
"""
==============================================================================
Alpaca Quantitative Trading Terminal - System Verification Test Suite
==============================================================================
Comprehensive end-to-end verification covering:
1. SQLite Database operations & schema validation
2. Quantitative Strategy (EMA cross, RSI momentum, ATR volatility channels)
3. Risk Management & Position Sizing formulas
4. Alpaca Client & Mock Paper Engine fallback
5. FastAPI Server REST endpoints & Static Frontend mounting
==============================================================================
"""

import sys
import os
import math
import tempfile
import unittest

# Ensure project root and backend are on sys.path
PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

# Force Mock Mode for testing
os.environ["MOCK_MODE"] = "true"
os.environ["ALPACA_API_KEY"] = "MOCK_KEY_TEST"
os.environ["ALPACA_SECRET_KEY"] = "MOCK_SECRET_TEST"

import database
from config import BotConfig, get_config, update_config
from strategy import calculate_ema, calculate_rsi, calculate_atr, TrendMomentumStrategy
from risk_manager import RiskManager
from alpaca_client import AlpacaClient, MockAlpacaEngine
from server import app
from fastapi.testclient import TestClient


class TestDatabaseOperations(unittest.TestCase):
    """Verifies SQLite tables, queries, insertions, and metric calculations."""

    def setUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.temp_db.name
        self.temp_db.close()
        database.init_db(self.db_path)

    def tearDown(self):
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except OSError:
                pass

    def test_equity_history_operations(self):
        # Insert equity snapshots
        database.record_equity(100000.0, 95000.0, 190000.0, 0.0, 0.0, db_path=self.db_path)
        database.record_equity(101500.0, 96000.0, 192000.0, 500.0, 1500.0, db_path=self.db_path)

        # get_equity_history returns chronological ASC order for Chart.js
        history = database.get_equity_history(limit=10, db_path=self.db_path)
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["equity"], 100000.0)
        self.assertEqual(history[1]["equity"], 101500.0)

    def test_trades_operations(self):
        # Record new trade entry
        database.record_trade(
            order_id="test_ord_001",
            symbol="AAPL",
            side="buy",
            qty=10,
            price=150.0,
            stop_loss=145.0,
            take_profit=160.0,
            status="FILLED",
            db_path=self.db_path
        )

        trades = database.get_trades(limit=10, db_path=self.db_path)
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["symbol"], "AAPL")
        self.assertEqual(trades[0]["status"], "FILLED")
        self.assertEqual(trades[0]["qty"], 10)

        # Update trade exit with profit
        database.update_trade_exit(
            order_id="test_ord_001",
            exit_price=160.0,
            realized_pnl=100.0,
            status="CLOSED",
            db_path=self.db_path
        )

        closed_trades = database.get_trades(status="CLOSED", db_path=self.db_path)
        self.assertEqual(len(closed_trades), 1)
        self.assertEqual(closed_trades[0]["exit_price"], 160.0)
        self.assertEqual(closed_trades[0]["realized_pnl"], 100.0)

    def test_signals_and_logs(self):
        # Record signal
        database.record_signal(
            symbol="NVDA",
            signal_type="BUY",
            price=450.0,
            fast_ema=448.0,
            slow_ema=440.0,
            rsi=58.2,
            atr=12.5,
            reason="Bullish 9/21 EMA crossover with RSI confirmation",
            db_path=self.db_path
        )
        signals = database.get_signals(limit=5, db_path=self.db_path)
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]["symbol"], "NVDA")
        self.assertEqual(signals[0]["signal_type"], "BUY")

        # Record log
        database.add_log("INFO", "Test log message", db_path=self.db_path)
        logs = database.get_logs(limit=5, db_path=self.db_path)
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["level"], "INFO")
        self.assertEqual(logs[0]["message"], "Test log message")

    def test_bot_settings(self):
        database.set_setting("active_theme", "obsidian", db_path=self.db_path)
        val = database.get_setting("active_theme", default="light", db_path=self.db_path)
        self.assertEqual(val, "obsidian")

    def test_performance_metrics_calculation(self):
        # Seed 3 trades: 2 wins (+200, +100), 1 loss (-100)
        database.record_trade("ord_w1", "MSFT", "buy", 5, 200.0, status="FILLED", db_path=self.db_path)
        database.update_trade_exit("ord_w1", 240.0, 200.0, status="CLOSED", db_path=self.db_path)

        database.record_trade("ord_w2", "AAPL", "buy", 5, 100.0, status="FILLED", db_path=self.db_path)
        database.update_trade_exit("ord_w2", 120.0, 100.0, status="CLOSED", db_path=self.db_path)

        database.record_trade("ord_l1", "SPY", "buy", 5, 400.0, status="FILLED", db_path=self.db_path)
        database.update_trade_exit("ord_l1", 380.0, -100.0, status="CLOSED", db_path=self.db_path)

        metrics = database.get_performance_metrics(db_path=self.db_path)
        self.assertEqual(metrics["total_trades"], 3)
        self.assertEqual(metrics["winning_trades"], 2)
        self.assertEqual(metrics["losing_trades"], 1)
        self.assertAlmostEqual(metrics["win_rate"], 66.67, places=1)
        # Gross profit = 300, Gross loss = 100 -> Profit Factor = 3.0
        self.assertAlmostEqual(metrics["profit_factor"], 3.0, places=2)
        self.assertEqual(metrics["total_realized_pnl"], 200.0)


class TestStrategyCalculations(unittest.TestCase):
    """Verifies EMA9, EMA21, RSI14, and ATR14 technical indicators and cross signals."""

    def test_calculate_ema(self):
        prices = [10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0, 19.0]
        ema5 = calculate_ema(prices, 5)
        self.assertEqual(len(ema5), len(prices))
        # Initial values reflect SMA of first 5 items = (10+11+12+13+14)/5 = 12.0
        self.assertEqual(ema5[4], 12.0)
        # Higher prices should drive EMA upward
        self.assertGreater(ema5[-1], ema5[4])

    def test_calculate_rsi(self):
        # Monotonically increasing prices -> RSI should be high (> 70)
        up_prices = [10.0 + i * 2.0 for i in range(25)]
        rsi_up = calculate_rsi(up_prices, 14)
        self.assertEqual(len(rsi_up), len(up_prices))
        self.assertGreaterEqual(rsi_up[-1], 70.0)

        # Monotonically decreasing prices -> RSI should be low (< 30)
        down_prices = [100.0 - i * 2.0 for i in range(25)]
        rsi_down = calculate_rsi(down_prices, 14)
        self.assertLessEqual(rsi_down[-1], 30.0)

    def test_calculate_atr(self):
        bars = [
            {"h": 105.0 + i, "l": 95.0 + i, "c": 100.0 + i}
            for i in range(20)
        ]
        atr14 = calculate_atr(bars, 14)
        self.assertEqual(len(atr14), len(bars))
        # Since high - low is 10.0 each bar, ATR should stabilize around 10.0
        self.assertAlmostEqual(atr14[-1], 10.0, places=1)

    def test_trend_momentum_strategy_crossover(self):
        strategy = TrendMomentumStrategy()

        # Build synthetic bars where price drops then surges up (bullish 9/21 cross)
        bars = []
        base = 100.0
        # 15 flat bars
        for _ in range(15):
            bars.append({"o": base, "h": base + 1.0, "l": base - 1.0, "c": base, "v": 1000})
        # 15 upward surging bars
        for i in range(1, 16):
            p = base + i * 2.5
            bars.append({"o": p - 1.0, "h": p + 2.0, "l": p - 2.0, "c": p, "v": 2000})

        decision = strategy.evaluate(bars)
        self.assertIn("signal", decision)
        self.assertIn("fast_ema", decision)
        self.assertIn("slow_ema", decision)
        self.assertIn("rsi", decision)
        self.assertIn("atr", decision)
        self.assertIn("stop_loss", decision)
        self.assertIn("take_profit", decision)
        # Fast EMA should be greater than Slow EMA due to upward surge
        self.assertGreater(decision["fast_ema"], decision["slow_ema"])
        # Stop loss must be below price, take profit above
        self.assertLess(decision["stop_loss"], decision["price"])
        self.assertGreater(decision["take_profit"], decision["price"])


class TestRiskManagement(unittest.TestCase):
    """Verifies position sizing math, 1% capital risk, and position limits."""

    def setUp(self):
        from config import update_config
        update_config({"RISK_PER_TRADE_PCT": 0.01, "ATR_MULTIPLIER": 2.0, "MAX_POSITIONS": 3})
        self.risk_manager = RiskManager()

    def test_position_sizing_formula(self):
        # Sizing formula: shares = int((equity * risk_pct) / (ATR * atr_multiplier))
        equity = 100000.0
        risk_pct = 0.01  # 1% = $1,000 risk budget
        entry_price = 50.0  # At $50/share, 200 shares = $10,000 (well within 25% single-position cap of $25,000)
        atr = 2.50
        atr_multiplier = 2.0  # Stop distance = 2.50 * 2.0 = $5.00 / share
        expected_shares = int((equity * risk_pct) / (atr * atr_multiplier))  # 1000 / 5 = 200 shares

        res = self.risk_manager.calculate_position_size(
            symbol="AAPL",
            entry_price=entry_price,
            atr=atr,
            equity=equity,
            buying_power=200000.0,
            cash=100000.0,
            current_positions=[]
        )

        self.assertTrue(res["approved"])
        self.assertEqual(res["shares"], expected_shares)
        self.assertEqual(res["stop_loss"], round(entry_price - (atr * atr_multiplier), 2))
        self.assertEqual(res["take_profit"], round(entry_price + (atr * 3.0), 2))

    def test_position_sizing_25pct_capital_cap(self):
        # Sizing formula produces 200 shares, but at $150/sh total cost is $30,000 > $25,000 (25% cap)
        equity = 100000.0
        entry_price = 150.0
        atr = 2.50
        res = self.risk_manager.calculate_position_size(
            symbol="MSFT",
            entry_price=entry_price,
            atr=atr,
            equity=equity,
            buying_power=200000.0,
            cash=100000.0,
            current_positions=[]
        )
        self.assertTrue(res["approved"])
        # Should be capped at int(25000 / 150) = 166 shares
        self.assertEqual(res["shares"], 166)
        self.assertLessEqual(res["shares"] * entry_price, equity * 0.25)

    def test_max_positions_enforcement(self):
        # Fill up 5 positions
        positions = [{"symbol": f"SYM_{i}"} for i in range(5)]
        res = self.risk_manager.calculate_position_size(
            symbol="NEW_SYM",
            entry_price=100.0,
            atr=2.0,
            equity=100000.0,
            buying_power=50000.0,
            cash=50000.0,
            current_positions=positions
        )
        self.assertFalse(res["approved"])
        self.assertIn("Max open positions reached", res["reason"])

    def test_duplicate_position_prevention(self):
        positions = [{"symbol": "NVDA"}]
        res = self.risk_manager.calculate_position_size(
            symbol="NVDA",
            entry_price=450.0,
            atr=5.0,
            equity=100000.0,
            buying_power=100000.0,
            cash=100000.0,
            current_positions=positions
        )
        self.assertFalse(res["approved"])
        self.assertIn("Position already exists", res["reason"])

    def test_exit_conditions_sl_and_tp(self):
        pos = {
            "symbol": "MSFT",
            "qty": 10,
            "avg_entry_price": 300.0,
            "stop_loss": 290.0,
            "take_profit": 320.0
        }

        # Normal price inside bracket: no exit
        should_exit, reason, pnl = self.risk_manager.should_exit_position(pos, 305.0)
        self.assertFalse(should_exit)

        # Price hits Stop-Loss (<= 290)
        should_exit, reason, pnl = self.risk_manager.should_exit_position(pos, 289.5)
        self.assertTrue(should_exit)
        self.assertIn("STOP-LOSS", reason)
        self.assertLess(pnl, 0.0)

        # Price hits Take-Profit (>= 320)
        should_exit, reason, pnl = self.risk_manager.should_exit_position(pos, 321.0)
        self.assertTrue(should_exit)
        self.assertIn("TAKE-PROFIT", reason)
        self.assertGreater(pnl, 0.0)


class TestAlpacaClientAndMock(unittest.TestCase):
    """Verifies Alpaca REST client and fallback mock engine."""

    def test_mock_client_initialization(self):
        client = AlpacaClient()
        self.assertTrue(client.mock_mode)
        self.assertTrue(client.is_mock())

    def test_mock_account_and_clock(self):
        client = AlpacaClient()
        account = client.get_account()
        self.assertIn("equity", account)
        self.assertIn("cash", account)
        self.assertIn("buying_power", account)
        self.assertGreaterEqual(float(account["equity"]), 1000.0)

        clock = client.get_clock()
        self.assertIn("is_open", clock)
        self.assertTrue(clock["is_open"])

    def test_mock_bars_generation(self):
        client = AlpacaClient()
        bars = client.get_bars("AAPL", timeframe="1Min", limit=30)
        self.assertEqual(len(bars), 30)
        for b in bars:
            self.assertIn("c", b)
            self.assertIn("h", b)
            self.assertIn("l", b)
            self.assertGreater(b["h"], 0)


class TestFastAPIServerEndpoints(unittest.TestCase):
    """Verifies FastAPI REST endpoints and dashboard static mounting."""

    @classmethod
    def setUpClass(cls):
        # Enter lifespan context to start engine, db, and mock client
        cls._client_cm = TestClient(app)
        cls.client = cls._client_cm.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls._client_cm.__exit__(None, None, None)

    def test_status_endpoint(self):
        response = self.client.get("/api/status")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("running", data)
        self.assertIn("mock_mode", data)
        self.assertIn("market_open", data)
        self.assertIn("connection", data)

    def test_account_endpoint(self):
        response = self.client.get("/api/account")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("equity", data)
        self.assertIn("cash", data)

    def test_positions_endpoint(self):
        response = self.client.get("/api/positions")
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.json(), list)

    def test_trades_endpoint(self):
        response = self.client.get("/api/trades")
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.json(), list)

    def test_metrics_endpoint(self):
        response = self.client.get("/api/metrics")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("win_rate", data)
        self.assertIn("profit_factor", data)
        self.assertIn("max_drawdown", data)

    def test_equity_history_endpoint(self):
        response = self.client.get("/api/equity-history")
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.json(), list)

    def test_bot_config_get_and_post(self):
        # GET config
        res_get = self.client.get("/api/bot/config")
        self.assertEqual(res_get.status_code, 200)
        config_data = res_get.json()
        self.assertIn("RISK_PER_TRADE_PCT", config_data)

        # POST config update
        update_payload = {"RISK_PER_TRADE_PCT": 0.015, "MAX_POSITIONS": 4}
        res_post = self.client.post("/api/bot/config", json=update_payload)
        self.assertEqual(res_post.status_code, 200)
        updated_data = res_post.json()
        self.assertEqual(updated_data["config"]["RISK_PER_TRADE_PCT"], 0.015)
        self.assertEqual(updated_data["config"]["MAX_POSITIONS"], 4)

    def test_static_frontend_mounting(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        # Verify content contains terminal dashboard markers
        content = response.text
        self.assertTrue("ALPACA" in content or "Quant" in content or "Terminal" in content)


def run_all_tests():
    print("=" * 70)
    print(" ALPACA QUANT TERMINAL - SYSTEM VERIFICATION SUITE")
    print("=" * 70)
    suite = unittest.TestSuite()
    loader = unittest.TestLoader()

    suite.addTests(loader.loadTestsFromTestCase(TestDatabaseOperations))
    suite.addTests(loader.loadTestsFromTestCase(TestStrategyCalculations))
    suite.addTests(loader.loadTestsFromTestCase(TestRiskManagement))
    suite.addTests(loader.loadTestsFromTestCase(TestAlpacaClientAndMock))
    suite.addTests(loader.loadTestsFromTestCase(TestFastAPIServerEndpoints))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "=" * 70)
    if result.wasSuccessful():
        print(f" [+] ALL {result.testsRun} TESTS PASSED SUCCESSFULLY!")
        print("=" * 70)
        return 0
    else:
        print(f" [-] TESTS FAILED: {len(result.failures)} failures, {len(result.errors)} errors.")
        print("=" * 70)
        return 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
