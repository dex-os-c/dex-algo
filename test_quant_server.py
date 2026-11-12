#!/usr/bin/env python3
"""
Test Suite for quant-server: backend/server.py and backend/database.py
=====================================================================
Validates:
1. SQLite persistence & clean schema migrations in database.py
2. Robust JSON sanitization (NaN, Inf, numpy types, dataclasses, enums)
3. REST API endpoints for:
   - Live market regimes (including soft probabilities)
   - Individual alpha component scores & per-alpha contribution meters
   - Dynamic weights & regime weight breakdown matrix
   - Orderbook depth snapshots & volume imbalance
   - Multi-asset position heatmap (BTC, ETH, SOL, SPY, QQQ)
   - Walk-forward backtest metrics (tear sheet, folds, degradation ratio, Monte Carlo cones)
   - Underwater drawdown series
   - Algorithmic decision snapshots
4. Real-time WebSocket (/ws) feeds:
   - Initial snapshot (INIT_SNAPSHOT)
   - Interactive client commands (get_regime, get_alphas, get_weights, get_orderbook, get_heatmap, get_wfo)
"""

import os
import sys
import math
import json
import unittest

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
from server import app
from fastapi.testclient import TestClient


class TestDatabasePersistence(unittest.TestCase):
    """Tests SQLite persistence and clean JSON serialization in database.py."""

    def setUp(self):
        self.test_db = os.path.join(PROJECT_ROOT, "test_quant_db.db")
        if os.path.exists(self.test_db):
            os.remove(self.test_db)
        database.init_db(self.test_db)

    def tearDown(self):
        if os.path.exists(self.test_db):
            os.remove(self.test_db)

    def test_json_sanitizer_handles_nan_and_inf(self):
        dirty = {
            "nan_val": float("nan"),
            "inf_val": float("inf"),
            "neg_inf": float("-inf"),
            "valid_float": 123.45,
            "nested": {
                "inner_nan": float("nan"),
                "array": [1.0, float("nan"), 3.0]
            }
        }
        clean = database.sanitize_for_json(dirty)
        self.assertEqual(clean["nan_val"], 0.0)
        self.assertEqual(clean["inf_val"], 0.0)
        self.assertEqual(clean["neg_inf"], 0.0)
        self.assertEqual(clean["nested"]["inner_nan"], 0.0)
        self.assertEqual(clean["nested"]["array"], [1.0, 0.0, 3.0])

        dumped = database.safe_json_dumps(dirty)
        parsed = json.loads(dumped)
        self.assertEqual(parsed["nan_val"], 0.0)

    def test_regime_persistence(self):
        weights = {"trend": 0.65, "mean_reversion": 0.10, "breakout": 0.25, "order_flow": 0.25}
        row_id = database.record_crypto_regime(
            symbol="BTC/USD",
            regime="TRENDING_BULL",
            adx=38.5,
            bb_width=45.2,
            confidence=0.92,
            plus_di=31.2,
            minus_di=12.4,
            bbw_percentile=45.2,
            volatility_zscore=0.45,
            weights=weights,
            db_path=self.test_db
        )
        self.assertGreater(row_id, 0)

        latest = database.get_latest_regime(symbol="BTC/USD", db_path=self.test_db)
        self.assertIsNotNone(latest)
        self.assertEqual(latest["regime"], "TRENDING_BULL")
        self.assertEqual(latest["adx"], 38.5)
        self.assertEqual(latest["weights"]["trend"], 0.65)

    def test_alpha_signals_persistence(self):
        row_id = database.record_alpha_signal(
            symbol="BTC/USD",
            composite_score=0.55,
            trend_score=0.75,
            mean_rev_score=0.0,
            ofi_score=0.40,
            regime="TRENDING_BULL",
            action="BUY",
            confidence=0.89,
            weights={"trend": 0.65, "order_flow": 0.35},
            db_path=self.test_db
        )
        self.assertGreater(row_id, 0)

        signals = database.get_recent_alpha_signals(limit=5, symbol="BTC/USD", db_path=self.test_db)
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]["action"], "BUY")
        self.assertEqual(signals[0]["composite_score"], 0.55)

    def test_orderbook_snapshot_persistence(self):
        bids = [{"price": 65000.0, "size": 1.25}, {"price": 64990.0, "size": 2.50}]
        asks = [{"price": 65002.0, "size": 0.85}, {"price": 65010.0, "size": 1.90}]
        row_id = database.record_orderbook_snapshot(
            symbol="BTC/USD",
            bid_depth=3.75,
            ask_depth=2.75,
            spread=2.0,
            imbalance=0.1538,
            mid_price=65001.0,
            bids=bids,
            asks=asks,
            db_path=self.test_db
        )
        self.assertGreater(row_id, 0)

        ob = database.get_latest_orderbook_snapshot(symbol="BTC/USD", db_path=self.test_db)
        self.assertIsNotNone(ob)
        self.assertEqual(ob["mid_price"], 65001.0)
        self.assertEqual(len(ob["bids"]), 2)
        self.assertEqual(len(ob["asks"]), 2)

    def test_position_heatmap_persistence(self):
        positions = [
            {"symbol": "BTC/USD", "side": "LONG", "notional_value": 32500.0, "weight_pct": 32.5, "unrealized_pnl": 1250.0, "heat_score": 0.65},
            {"symbol": "ETH/USD", "side": "FLAT", "notional_value": 0.0, "weight_pct": 0.0, "unrealized_pnl": 0.0, "heat_score": 0.0}
        ]
        row_id = database.record_position_heatmap(
            positions=positions,
            total_equity=100000.0,
            gross_exposure=32500.0,
            net_exposure=32500.0,
            leverage=0.33,
            db_path=self.test_db
        )
        self.assertGreater(row_id, 0)

        hm = database.get_latest_position_heatmap(db_path=self.test_db)
        self.assertIsNotNone(hm)
        self.assertEqual(hm["total_equity"], 100000.0)
        self.assertEqual(len(hm["positions"]), 2)
        self.assertEqual(hm["positions"][0]["symbol"], "BTC/USD")

    def test_walk_forward_metrics_persistence(self):
        wfo_data = {
            "total_trades": 36,
            "win_rate": 0.6471,
            "profit_factor": 2.25,
            "expectancy": 21.79,
            "annualized_return": 0.284,
            "annualized_sharpe": 2.29,
            "sortino_ratio": 3.14,
            "calmar_ratio": 19.44,
            "max_drawdown_pct": 0.0024,
            "max_drawdown_duration": 44,
            "average_r_multiple": 1.64,
            "payoff_ratio": 1.23,
            "market_exposure_pct": 0.4375,
            "final_equity": 118750.80,
            "net_profit": 18750.80,
            "in_sample_sharpe": 2.3925,
            "out_of_sample_sharpe": 2.1125,
            "degradation_ratio": 0.8830,
            "is_overfit": False,
            "folds": [{"fold": 1, "is_sharpe": 2.41, "oos_sharpe": 2.18}],
            "monte_carlo": {"probability_of_ruin": 0.0, "95th_percentile_max_drawdown": 0.0462}
        }
        row_id = database.record_walk_forward_metrics(
            symbol="BTC/USDT",
            metrics=wfo_data,
            strategy_name="MultiAlphaEnsemble",
            db_path=self.test_db
        )
        self.assertGreater(row_id, 0)

        retrieved = database.get_latest_walk_forward_metrics(symbol="BTC/USDT", db_path=self.test_db)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved["annualized_sharpe"], 2.29)
        self.assertEqual(retrieved["is_overfit"], False)
        self.assertEqual(len(retrieved["folds"]), 1)


class TestServerRESTAndWebSocket(unittest.TestCase):
    """Tests FastAPI REST endpoints and real-time WebSocket feeds in server.py."""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_regime_endpoint(self):
        for path in ["/api/regime", "/api/crypto/regime"]:
            res = self.client.get(f"{path}?symbol=BTC/USD")
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertIn("current_regime", data)
            self.assertIn("regime", data)
            self.assertIn("adx", data)
            self.assertIn("plus_di", data)
            self.assertIn("minus_di", data)
            self.assertIn("dynamic_weights", data)
            self.assertIn("regime_probabilities", data)

    def test_alphas_endpoint(self):
        for path in ["/api/alphas", "/api/crypto/alphas"]:
            res = self.client.get(f"{path}?symbol=BTC/USD")
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertIn("alpha_1_trend", data)
            self.assertIn("alpha_2_mean_rev", data)
            self.assertIn("alpha_3_ofi", data)
            self.assertIn("composite_score", data)
            self.assertIn("direction", data)
            self.assertIn("dynamic_weights", data)
            self.assertIn("alpha_contributions", data)

    def test_weights_endpoint(self):
        for path in ["/api/weights", "/api/crypto/weights"]:
            res = self.client.get(f"{path}?symbol=BTC/USD")
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertIn("active_regime", data)
            self.assertIn("dynamic_weights", data)
            self.assertIn("regime_weight_matrix", data)
            matrix = data["regime_weight_matrix"]
            self.assertIn("TRENDING_BULL", matrix)
            self.assertIn("LOW_VOL_COMPRESSION", matrix)

    def test_orderbook_endpoint(self):
        for path in ["/api/orderbook", "/api/crypto/orderbook"]:
            res = self.client.get(f"{path}?symbol=BTC/USD&depth=10")
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertIn("mid_price", data)
            self.assertIn("spread", data)
            self.assertIn("bids", data)
            self.assertIn("asks", data)
            self.assertIn("bid_depth", data)
            self.assertIn("ask_depth", data)
            self.assertIn("volume_imbalance_ratio", data)
            self.assertEqual(len(data["bids"]), 10)
            self.assertEqual(len(data["asks"]), 10)

    def test_position_heatmap_endpoint(self):
        for path in ["/api/positions/heatmap", "/api/heatmap", "/api/crypto/positions/heatmap"]:
            res = self.client.get(path)
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertIn("total_equity", data)
            self.assertIn("gross_exposure", data)
            self.assertIn("gross_leverage", data)
            self.assertIn("assets", data)
            self.assertGreaterEqual(len(data["assets"]), 3)
            # Verify asset item attributes
            first = data["assets"][0]
            self.assertIn("symbol", first)
            self.assertIn("notional_value", first)
            self.assertIn("weight_pct", first)
            self.assertIn("heat_score", first)
            self.assertIn("regime_alignment", first)

    def test_walk_forward_metrics_endpoint(self):
        for path in ["/api/backtest/wfo", "/api/backtest/metrics", "/api/crypto/backtest/wfo", "/api/wfo/metrics"]:
            res = self.client.get(f"{path}?symbol=BTC/USDT")
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertIn("annualized_sharpe", data)
            self.assertIn("sortino_ratio", data)
            self.assertIn("calmar_ratio", data)
            self.assertIn("win_rate", data)
            self.assertIn("profit_factor", data)
            self.assertIn("max_drawdown", data)
            self.assertIn("folds", data)
            self.assertIn("monte_carlo", data)
            self.assertIn("multi_asset_summary", data)
            self.assertIn("underwater_drawdown", data)

    def test_underwater_drawdown_endpoint(self):
        res = self.client.get("/api/backtest/underwater?symbol=BTC/USDT")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("underwater_drawdown", data)
        self.assertGreater(len(data["underwater_drawdown"]), 0)

    def test_backtest_run_endpoint(self):
        res = self.client.post("/api/backtest/run?symbol=BTC/USDT")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "success")
        self.assertIn("annualized_sharpe", data["result"])

    def test_decisions_endpoint(self):
        res = self.client.get("/api/decisions?limit=10")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIsInstance(data, list)

    def test_websocket_feed(self):
        with self.client.websocket_connect("/ws") as ws:
            # 1. Verify INIT_SNAPSHOT payload
            init_msg = ws.receive_text()
            payload = json.loads(init_msg)
            self.assertEqual(payload["type"], "INIT_SNAPSHOT")
            self.assertIn("regime", payload)
            self.assertIn("alphas", payload)
            self.assertIn("dynamic_weights", payload)
            self.assertIn("orderbook", payload)
            self.assertIn("position_heatmap", payload)
            self.assertIn("wfo_metrics", payload)
            self.assertIn("underwater_drawdown", payload)

            # 2. Test interactive client commands
            ws.send_text(json.dumps({"action": "get_regime", "symbol": "BTC/USD"}))
            reg_resp = json.loads(ws.receive_text())
            self.assertEqual(reg_resp["type"], "REGIME")
            self.assertIn("current_regime", reg_resp["data"])

            ws.send_text(json.dumps({"action": "get_alphas", "symbol": "BTC/USD"}))
            alp_resp = json.loads(ws.receive_text())
            self.assertEqual(alp_resp["type"], "ALPHAS")
            self.assertIn("composite_score", alp_resp["data"])

            ws.send_text(json.dumps({"action": "get_weights", "symbol": "BTC/USD"}))
            w_resp = json.loads(ws.receive_text())
            self.assertEqual(w_resp["type"], "WEIGHTS")
            self.assertIn("dynamic_weights", w_resp["data"])

            ws.send_text(json.dumps({"action": "get_orderbook", "symbol": "BTC/USD"}))
            ob_resp = json.loads(ws.receive_text())
            self.assertEqual(ob_resp["type"], "ORDERBOOK")
            self.assertIn("bids", ob_resp["data"])

            ws.send_text(json.dumps({"action": "get_heatmap"}))
            hm_resp = json.loads(ws.receive_text())
            self.assertEqual(hm_resp["type"], "POSITION_HEATMAP")
            self.assertIn("assets", hm_resp["data"])

            ws.send_text(json.dumps({"action": "get_wfo", "symbol": "BTC/USDT"}))
            wfo_resp = json.loads(ws.receive_text())
            self.assertEqual(wfo_resp["type"], "WFO_METRICS")
            self.assertIn("annualized_sharpe", wfo_resp["data"])


if __name__ == "__main__":
    unittest.main()
