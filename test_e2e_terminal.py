#!/usr/bin/env python3
"""
End-to-End Terminal Integration & Microstructure Verification Suite
==================================================================
Tests:
1. REST Market Quotes & Provenance Tagging (BTC, ETH, SOL, SPY, QQQ)
2. Interactive Order Ticket REST API (Market, Limit, OCO Brackets, Opposing Leg Cancellation)
3. WebSocket Interactive Protocol (INIT_SNAPSHOT, ping/PONG, get_quotes, get_orders, create_order, cancel_order)
4. API Key Authorization Security Gate (X-API-Key & Bearer Token)
5. Anti-Fabrication & Metric Integrity Guarantee
"""

import os
import sys
import json
import unittest
from fastapi.testclient import TestClient

# Ensure repo root and backend/ are in sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(BASE_DIR, "backend")
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from backend.server import app, get_engine, get_alpaca
import backend.database as database


class TestTerminalEndToEnd(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def setUp(self):
        self.prev_key = os.environ.get("DEX_API_KEY")
        if "DEX_API_KEY" in os.environ:
            del os.environ["DEX_API_KEY"]

    def tearDown(self):
        if self.prev_key is not None:
            os.environ["DEX_API_KEY"] = self.prev_key
        elif "DEX_API_KEY" in os.environ:
            del os.environ["DEX_API_KEY"]

    def test_01_market_quotes_multi_asset(self):
        """Verifies that all 5 key assets are quoted with realistic institutional pricing and explicit provenance."""
        resp = self.client.get("/api/market/quotes")
        self.assertEqual(resp.status_code, 200)
        quotes = resp.json()
        self.assertIsInstance(quotes, list)
        self.assertGreaterEqual(len(quotes), 5)

        symbol_map = {q["symbol"]: q for q in quotes}
        expected_symbols = ["BTC/USD", "ETH/USD", "SOL/USD", "SPY", "QQQ"]

        for sym in expected_symbols:
            self.assertIn(sym, symbol_map, f"Missing quote for {sym}")
            q = symbol_map[sym]
            self.assertGreater(q["price"], 0)
            self.assertIn("change_24h", q)
            self.assertIn("bid", q)
            self.assertIn("ask", q)
            self.assertGreaterEqual(q["ask"], q["bid"])
            # Provenance check: Never fabricate mock data as real data without disclosure
            self.assertIn("is_mock", q)
            self.assertIn("data_source", q)
            self.assertTrue(q["is_mock"])
            self.assertEqual(q["data_source"], "SIMULATED_MOCK")

        # Price range reality checks
        self.assertGreater(symbol_map["BTC/USD"]["price"], 50000.0)
        self.assertGreater(symbol_map["ETH/USD"]["price"], 2000.0)
        self.assertGreater(symbol_map["SOL/USD"]["price"], 100.0)
        self.assertGreater(symbol_map["SPY"]["price"], 400.0)
        self.assertGreater(symbol_map["QQQ"]["price"], 350.0)

    def test_02_order_lifecycle_and_validation(self):
        """Tests manual order submission, validation, retrieval, and status filtering."""
        # 1. Invalid order validation: negative quantity
        bad_resp = self.client.post("/api/orders", json={
            "symbol": "BTC/USD",
            "side": "buy",
            "qty": -0.5,
            "order_type": "market"
        })
        self.assertEqual(bad_resp.status_code, 400)

        # 2. Invalid order validation: invalid side
        bad_side = self.client.post("/api/orders", json={
            "symbol": "BTC/USD",
            "side": "hold",
            "qty": 1.0,
            "order_type": "market"
        })
        self.assertEqual(bad_side.status_code, 400)

        # 3. Submit valid limit order
        create_resp = self.client.post("/api/orders", json={
            "symbol": "ETH/USD",
            "side": "buy",
            "qty": 1.5,
            "order_type": "limit",
            "price": 3400.0
        })
        self.assertEqual(create_resp.status_code, 200)
        order_data = create_resp.json()["order"]
        order_id = order_data["order_id"]
        self.assertEqual(order_data["symbol"], "ETH/USD")
        self.assertEqual(order_data["side"], "buy")
        self.assertEqual(order_data["qty"], 1.5)

        # 4. Fetch orders and verify presence
        list_resp = self.client.get("/api/orders")
        self.assertEqual(list_resp.status_code, 200)
        orders = list_resp.json()
        self.assertTrue(any(o["order_id"] == order_id for o in orders))

        # 5. Filter by symbol
        eth_orders = self.client.get("/api/orders?symbol=ETH/USD").json()
        self.assertTrue(all(o["symbol"] == "ETH/USD" for o in eth_orders))

    def test_03_bracket_oco_order_and_cancellation_invariant(self):
        """Verifies bracket orders create child OCO legs, and cancelling one cancels the opposing leg."""
        bracket_resp = self.client.post("/api/orders", json={
            "symbol": "BTC/USD",
            "side": "buy",
            "qty": 0.5,
            "order_type": "market",
            "stop_loss": 62000.0,
            "take_profit": 72000.0
        })
        self.assertEqual(bracket_resp.status_code, 200)
        parent = bracket_resp.json()["order"]
        self.assertEqual(parent["order_class"], "bracket")
        self.assertEqual(len(parent["child_orders"]), 2)

        sl_id = [cid for cid in parent["child_orders"] if cid.startswith("sl-")][0]
        tp_id = [cid for cid in parent["child_orders"] if cid.startswith("tp-")][0]

        # Verify both child legs exist
        all_orders = {o["order_id"]: o for o in self.client.get("/api/orders").json()}
        self.assertIn(sl_id, all_orders)
        self.assertIn(tp_id, all_orders)
        self.assertEqual(all_orders[sl_id]["status"], "SUBMITTED")
        self.assertEqual(all_orders[tp_id]["status"], "SUBMITTED")

        # Cancel Stop-Loss leg: Opposing Take-Profit leg must be automatically cancelled (OCO invariant)
        cancel_resp = self.client.delete(f"/api/orders/{sl_id}")
        self.assertEqual(cancel_resp.status_code, 200)

        updated_orders = {o["order_id"]: o for o in self.client.get("/api/orders").json()}
        self.assertEqual(updated_orders[sl_id]["status"], "CANCELED")
        self.assertEqual(updated_orders[tp_id]["status"], "CANCELED")
        self.assertIn("canceled_reason", updated_orders[tp_id]["meta"])

    def test_04_api_key_security_gate(self):
        """Ensures X-API-Key and Authorization Bearer protection when DEX_API_KEY is configured."""
        os.environ["DEX_API_KEY"] = "institutional-secret-key-42"

        try:
            # Mutating call without auth header -> 401 Unauthorized
            unauth_resp = self.client.post("/api/orders", json={
                "symbol": "SPY",
                "side": "buy",
                "qty": 10.0,
                "order_type": "market"
            })
            self.assertEqual(unauth_resp.status_code, 401)

            # Mutating call with invalid key -> 401 Unauthorized
            bad_key_resp = self.client.post("/api/orders", json={
                "symbol": "SPY",
                "side": "buy",
                "qty": 10.0,
                "order_type": "market"
            }, headers={"X-API-Key": "wrong-key"})
            self.assertEqual(bad_key_resp.status_code, 401)

            # Mutating call with valid X-API-Key -> 200 OK
            valid_resp = self.client.post("/api/orders", json={
                "symbol": "SPY",
                "side": "buy",
                "qty": 5.0,
                "order_type": "market"
            }, headers={"X-API-Key": "institutional-secret-key-42"})
            self.assertEqual(valid_resp.status_code, 200)
            spy_order_id = valid_resp.json()["order"]["order_id"]

            # Delete order with Bearer token -> 200 OK
            del_resp = self.client.delete(
                f"/api/orders/{spy_order_id}",
                headers={"Authorization": "Bearer institutional-secret-key-42"}
            )
            self.assertEqual(del_resp.status_code, 200)
        finally:
            if "DEX_API_KEY" in os.environ:
                del os.environ["DEX_API_KEY"]

    def test_05_websocket_interactive_session(self):
        """Tests interactive WebSocket protocol: init snapshot, ping/pong, and command actions."""
        def receive_type(ws, expected_type, max_reads=10):
            for _ in range(max_reads):
                raw = ws.receive_text()
                msg = json.loads(raw)
                if msg.get("type") == expected_type:
                    return msg
            raise AssertionError(f"Expected message type {expected_type} not received within {max_reads} messages")

        with self.client.websocket_connect("/ws") as ws:
            # 1. Initial snapshot on connection
            init_msg = receive_type(ws, "INIT_SNAPSHOT")
            self.assertEqual(init_msg["type"], "INIT_SNAPSHOT")
            self.assertIn("account", init_msg)
            self.assertIn("positions", init_msg)
            self.assertIn("orders", init_msg)
            self.assertIn("regime", init_msg)
            self.assertIn("alphas", init_msg)
            self.assertIn("orderbook", init_msg)
            self.assertIn("wfo_metrics", init_msg)

            # 2. Ping -> PONG
            ws.send_text(json.dumps({"action": "ping"}))
            pong_msg = receive_type(ws, "PONG")
            self.assertEqual(pong_msg["type"], "PONG")
            self.assertIn("timestamp", pong_msg)

            # 3. get_quotes -> QUOTES
            ws.send_text(json.dumps({"action": "get_quotes"}))
            q_msg = receive_type(ws, "QUOTES")
            self.assertEqual(q_msg["type"], "QUOTES")
            self.assertGreaterEqual(len(q_msg["data"]), 5)

            # 4. get_orders -> ORDERS
            ws.send_text(json.dumps({"action": "get_orders"}))
            orders_msg = receive_type(ws, "ORDERS")
            self.assertEqual(orders_msg["type"], "ORDERS")
            self.assertIsInstance(orders_msg["data"], list)

            # 5. create_order -> ORDER_CREATED
            ws.send_text(json.dumps({
                "action": "create_order",
                "symbol": "QQQ",
                "side": "buy",
                "qty": 2.0,
                "order_type": "market"
            }))
            created_msg = receive_type(ws, "ORDER_CREATED")
            self.assertEqual(created_msg["type"], "ORDER_CREATED")
            qqq_order_id = created_msg["data"]["order_id"]
            self.assertEqual(created_msg["data"]["symbol"], "QQQ")

            # 6. cancel_order -> ORDER_CANCELED
            ws.send_text(json.dumps({
                "action": "cancel_order",
                "order_id": qqq_order_id,
                "reason": "WS_TEST_CANCEL"
            }))
            canceled_msg = receive_type(ws, "ORDER_CANCELED")
            self.assertEqual(canceled_msg["type"], "ORDER_CANCELED")
            self.assertEqual(canceled_msg["data"]["order_id"], qqq_order_id)

    def test_06_metric_integrity_and_no_nan_inf(self):
        """Verifies that all server JSON responses are strictly sanitised and contain zero NaN or Infinity."""
        endpoints = [
            "/api/status",
            "/api/market/quotes",
            "/api/account",
            "/api/positions",
            "/api/orders",
            "/api/regime",
            "/api/alphas",
            "/api/weights",
            "/api/orderbook",
            "/api/positions/heatmap",
            "/api/backtest/wfo",
            "/api/backtest/underwater",
            "/api/market/bars?symbol=BTC/USD&timeframe=1Min&limit=20"
        ]

        for ep in endpoints:
            resp = self.client.get(ep)
            self.assertEqual(resp.status_code, 200, f"Endpoint {ep} failed with status {resp.status_code}")
            text = resp.text
            # Strict JSON specification check: NaN and Infinity are illegal in JSON
            self.assertNotIn("NaN", text, f"Illegal NaN in endpoint {ep}")
            self.assertNotIn("Infinity", text, f"Illegal Infinity in endpoint {ep}")
            self.assertNotIn("-Infinity", text, f"Illegal -Infinity in endpoint {ep}")

    def test_07_account_reset_and_candlestick_bars(self):
        """Verifies market bars for candlestick chart and 1-click account reset endpoint."""
        # 1. Fetch OHLCV Candlestick Bars
        bars_resp = self.client.get("/api/market/bars?symbol=BTC/USD&timeframe=1Min&limit=30")
        self.assertEqual(bars_resp.status_code, 200)
        bars_data = bars_resp.json()
        self.assertEqual(bars_data["status"], "success")
        self.assertEqual(bars_data["symbol"], "BTC/USD")
        self.assertGreaterEqual(bars_data["count"], 10)
        sample_bar = bars_data["bars"][0]
        self.assertIn("open", sample_bar)
        self.assertIn("high", sample_bar)
        self.assertIn("low", sample_bar)
        self.assertIn("close", sample_bar)
        self.assertIn("volume", sample_bar)
        self.assertGreater(sample_bar["high"], 0.0)

        # 2. Test Account Reset
        reset_resp = self.client.post("/api/account/reset?cash=100000.0")
        self.assertEqual(reset_resp.status_code, 200)
        reset_data = reset_resp.json()
        self.assertEqual(reset_data["status"], "success")
        acc = reset_data["account"]
        self.assertEqual(float(acc["cash"]), 100000.0)
        self.assertEqual(float(acc["portfolio_value"]), 100000.0)


if __name__ == "__main__":
    unittest.main()
