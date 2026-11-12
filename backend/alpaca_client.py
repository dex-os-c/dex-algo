import time
import math
import random
import datetime
import requests
from typing import Dict, Any, List, Optional
from config import get_config


class MockAlpacaEngine:
    """
    High-fidelity simulation engine for paper trading when Alpaca credentials
    are not supplied or when running in local sandbox/test mode.
    Provides realistic tick variations, position tracking, cash/equity updates,
    and historical OHLCV bar generation.
    """
    def __init__(self, starting_cash: float = 100000.0):
        self.starting_cash = starting_cash
        self.cash = starting_cash
        self.positions: Dict[str, Dict[str, Any]] = {}
        self.orders: List[Dict[str, Any]] = []
        
        # Base realistic prices
        self.base_prices = {
            "AAPL": 224.50,
            "MSFT": 428.10,
            "NVDA": 138.80,
            "SPY": 586.40,
            "QQQ": 502.90,
            "BTC/USD": 89450.00,
            "BTCUSD": 89450.00,
            "ETH/USD": 3120.00,
            "ETHUSD": 3120.00,
            "SOL/USD": 215.00,
            "SOLUSD": 215.00,
        }
        self.current_prices = dict(self.base_prices)

    def _get_live_price(self, symbol: str) -> float:
        symbol = symbol.upper()
        clean = symbol.replace("/", "")
        if symbol not in self.current_prices:
            if clean in self.current_prices:
                self.current_prices[symbol] = self.current_prices[clean]
            elif "BTC" in symbol:
                self.current_prices[symbol] = 89450.00
            elif "ETH" in symbol:
                self.current_prices[symbol] = 3120.00
            elif "SOL" in symbol:
                self.current_prices[symbol] = 215.00
            else:
                self.current_prices[symbol] = 150.00
        
        # Introduce micro-drift (+- 0.15%)
        drift = (random.random() - 0.49) * 0.003
        new_price = round(self.current_prices[symbol] * (1.0 + drift), 2)
        self.current_prices[symbol] = max(1.0, new_price)
        return self.current_prices[symbol]

    def reset_account(self, cash: float = 100000.0) -> Dict[str, Any]:
        """Resets the mock paper account back to starting cash and clears open positions."""
        self.cash = float(cash)
        self.starting_cash = float(cash)
        self.positions.clear()
        self.orders.clear()
        return self.get_account()

    def get_clock(self) -> Dict[str, Any]:
        now = datetime.datetime.now(datetime.timezone.utc)
        return {
            "timestamp": now.isoformat(),
            "is_open": True,  # Keep open for interactive simulation
            "next_open": (now + datetime.timedelta(days=1)).isoformat(),
            "next_close": (now + datetime.timedelta(hours=8)).isoformat()
        }

    def get_account(self) -> Dict[str, Any]:
        portfolio_val = 0.0
        for sym, pos in self.positions.items():
            curr_px = self._get_live_price(sym)
            qty = pos["qty"]
            mkt_val = qty * curr_px
            pos["current_price"] = curr_px
            pos["market_value"] = round(mkt_val, 2)
            cost_basis = qty * pos["avg_entry_price"]
            unrealized_pl = mkt_val - cost_basis
            pos["unrealized_pl"] = round(unrealized_pl, 2)
            pos["unrealized_plpc"] = round(unrealized_pl / cost_basis if cost_basis > 0 else 0.0, 4)
            portfolio_val += mkt_val

        equity = round(self.cash + portfolio_val, 2)
        daily_pnl = round(equity - self.starting_cash, 2)
        daily_pnl_pct = round((daily_pnl / self.starting_cash) * 100.0, 2)
        available_bp = max(0.0, round((equity * 2.0) - portfolio_val, 2))
        if available_bp <= 0 and self.cash > 0:
            available_bp = round(self.cash * 2.0, 2)

        return {
            "id": "mock-paper-account-01",
            "account_number": "MOCK-PA-9921",
            "status": "ACTIVE",
            "currency": "USD",
            "buying_power": str(available_bp),
            "cash": str(round(self.cash, 2)),
            "portfolio_value": str(equity),
            "equity": str(equity),
            "last_equity": str(round(self.starting_cash, 2)),
            "daily_pnl": daily_pnl,
            "daily_pnl_pct": daily_pnl_pct,
            "pattern_day_trader": False,
            "trading_blocked": False,
            "transfers_blocked": False,
            "account_blocked": False,
            "shorting_enabled": True
        }

    def get_positions(self) -> List[Dict[str, Any]]:
        self.get_account()  # Recalculates current values
        result = []
        for sym, pos in self.positions.items():
            result.append({
                "symbol": sym,
                "qty": str(pos["qty"]),
                "side": "long",
                "avg_entry_price": str(pos["avg_entry_price"]),
                "current_price": str(pos["current_price"]),
                "market_value": str(pos["market_value"]),
                "cost_basis": str(round(pos["qty"] * pos["avg_entry_price"], 2)),
                "unrealized_pl": str(pos["unrealized_pl"]),
                "unrealized_plpc": str(pos["unrealized_plpc"]),
                "stop_loss": pos.get("stop_loss", 0.0),
                "take_profit": pos.get("take_profit", 0.0)
            })
        return result

    def get_position(self, symbol: str) -> Optional[Dict[str, Any]]:
        sym = symbol.upper()
        clean_sym = sym.replace("/", "")
        target_key = sym if sym in self.positions else (clean_sym if clean_sym in self.positions else None)
        if not target_key:
            for k in self.positions:
                if k.upper().replace("/", "") == clean_sym:
                    target_key = k
                    break
        if target_key:
            for p in self.get_positions():
                if p["symbol"].upper().replace("/", "") == clean_sym:
                    return p
        return None

    def create_order(
        self,
        symbol: str,
        qty: Union[int, float],
        side: str,
        order_type: str = "market",
        time_in_force: str = "gtc",
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None
    ) -> Dict[str, Any]:
        sym = symbol.upper()
        clean_sym = sym.replace("/", "")
        qty = float(qty)
        fill_price = self._get_live_price(sym)
        order_id = f"mock-order-{int(time.time() * 1000)}-{random.randint(100, 999)}"
        side = side.lower()

        if side == "buy":
            total_cost = fill_price * qty
            # Compute current portfolio equity & 2x margin buying power
            portfolio_val = sum(pos["qty"] * self._get_live_price(sym_k) for sym_k, pos in self.positions.items())
            equity = self.cash + portfolio_val
            available_buying_power = max(0.0, (equity * 2.0) - portfolio_val)
            if self.cash > 0:
                available_buying_power = max(available_buying_power, self.cash * 2.0)

            if total_cost > available_buying_power:
                raise ValueError(f"Insufficient buying power: required ${total_cost:,.2f}, available ${available_buying_power:,.2f}")
            self.cash -= total_cost
            target_key = sym if sym in self.positions else (clean_sym if clean_sym in self.positions else sym)
            if target_key in self.positions:
                prev = self.positions[target_key]
                new_qty = prev["qty"] + qty
                new_cost = (prev["qty"] * prev["avg_entry_price"]) + total_cost
                prev["avg_entry_price"] = round(new_cost / new_qty, 2)
                prev["qty"] = new_qty
                if stop_loss:
                    prev["stop_loss"] = stop_loss
                if take_profit:
                    prev["take_profit"] = take_profit
            else:
                self.positions[target_key] = {
                    "qty": qty,
                    "avg_entry_price": fill_price,
                    "current_price": fill_price,
                    "market_value": round(total_cost, 2),
                    "unrealized_pl": 0.0,
                    "unrealized_plpc": 0.0,
                    "stop_loss": stop_loss or 0.0,
                    "take_profit": take_profit or 0.0
                }
        elif side == "sell":
            target_key = sym if sym in self.positions else (clean_sym if clean_sym in self.positions else None)
            if not target_key or self.positions[target_key]["qty"] < (qty - 1e-6):
                raise ValueError(f"Cannot sell {qty} units of {sym}: insufficient position")
            pos = self.positions[target_key]
            proceeds = fill_price * qty
            self.cash += proceeds
            pos["qty"] -= qty
            if pos["qty"] <= 1e-6:
                del self.positions[target_key]

        order_record = {
            "id": order_id,
            "client_order_id": order_id,
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "symbol": sym,
            "qty": str(qty),
            "filled_qty": str(qty),
            "type": order_type,
            "side": side,
            "time_in_force": time_in_force,
            "status": "filled",
            "filled_avg_price": str(fill_price),
            "stop_loss": stop_loss,
            "take_profit": take_profit
        }
        self.orders.append(order_record)
        return order_record

    def close_position(self, symbol: str) -> Dict[str, Any]:
        sym = symbol.upper()
        clean_sym = sym.replace("/", "")
        target_key = sym if sym in self.positions else (clean_sym if clean_sym in self.positions else None)
        if not target_key:
            for k in list(self.positions.keys()):
                if k.upper().replace("/", "") == clean_sym:
                    target_key = k
                    break
        if not target_key:
            raise ValueError(f"No position found for {sym}")
        pos = self.positions[target_key]
        qty = pos["qty"]
        return self.create_order(symbol=target_key, qty=qty, side="sell")

    def get_latest_trade(self, symbol: str) -> Dict[str, Any]:
        px = self._get_live_price(symbol)
        return {
            "symbol": symbol.upper(),
            "price": px,
            "size": random.randint(10, 500),
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
        }

    def get_bars(self, symbol: str, timeframe: str = "1Min", limit: int = 50) -> List[Dict[str, Any]]:
        sym = symbol.upper()
        current_px = self._get_live_price(sym)
        bars = []
        now = datetime.datetime.now(datetime.timezone.utc)
        
        # Synthesize realistic historical OHLCV with natural oscillating momentum
        # ending at current_px, generating healthy RSI and trend waves
        sym_seed = sum(ord(c) for c in sym)
        raw_closes = [current_px]
        for i in range(1, limit):
            wave = math.sin((i + sym_seed) * 0.35) * (current_px * 0.0035)
            noise = (random.random() - 0.49) * (current_px * 0.005)
            prev_p = max(1.0, round(raw_closes[-1] - wave - noise, 2))
            raw_closes.append(prev_p)
        raw_closes.reverse()

        for i, c in enumerate(raw_closes):
            bar_time = now - datetime.timedelta(minutes=(limit - i))
            o = raw_closes[i - 1] if i > 0 else round(c * (1.0 + (random.random() - 0.5) * 0.002), 2)
            spread = abs(c - o)
            h = round(max(o, c) + (random.random() * max(spread, current_px * 0.002)), 2)
            l = round(max(0.5, min(o, c) - (random.random() * max(spread, current_px * 0.002))), 2)
            v = random.randint(5000, 50000)
            bars.append({
                "t": bar_time.isoformat(),
                "o": o,
                "h": h,
                "l": l,
                "c": c,
                "v": v
            })
        # Ensure latest bar close exactly matches current live price
        bars[-1]["c"] = current_px
        bars[-1]["h"] = max(bars[-1]["h"], current_px)
        bars[-1]["l"] = min(bars[-1]["l"], current_px)
        return bars


class AlpacaClient:
    """
    Unified Alpaca Paper Trading REST client with transparent fallback to
    high-fidelity MockAlpacaEngine when keys are invalid or not configured.
    """
    def __init__(self):
        self.config = get_config()
        self.api_key = self.config.ALPACA_API_KEY.strip()
        self.secret_key = self.config.ALPACA_SECRET_KEY.strip()
        self.base_url = self.config.ALPACA_BASE_URL.rstrip("/")
        self.data_url = self.config.ALPACA_DATA_URL.rstrip("/")
        self.mock_engine = MockAlpacaEngine()
        self._force_mock = self.config.MOCK_MODE or not self.api_key or not self.secret_key
        self._headers = {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.secret_key,
            "Content-Type": "application/json"
        }

    def is_mock(self) -> bool:
        return self._force_mock

    @property
    def mock_mode(self) -> bool:
        return self._force_mock

    def test_connection(self) -> Dict[str, Any]:
        if self._force_mock:
            return {"connected": True, "mode": "MOCK", "status": "Simulated Paper Trading Active"}
        try:
            resp = requests.get(f"{self.base_url}/v2/account", headers=self._headers, timeout=5)
            if resp.status_code == 200:
                return {"connected": True, "mode": "LIVE_PAPER", "status": "Connected to Alpaca Paper API"}
            else:
                self._force_mock = True
                return {
                    "connected": True,
                    "mode": "FALLBACK_MOCK",
                    "status": f"Alpaca auth failed ({resp.status_code}), running in Simulation Mode"
                }
        except Exception as e:
            self._force_mock = True
            return {
                "connected": True,
                "mode": "FALLBACK_MOCK",
                "status": f"Connection error: {str(e)[:40]}, running in Simulation Mode"
            }

    def get_clock(self) -> Dict[str, Any]:
        if self._force_mock:
            return self.mock_engine.get_clock()
        try:
            resp = requests.get(f"{self.base_url}/v2/clock", headers=self._headers, timeout=5)
            resp.raise_for_status()
            return resp.json()
        except Exception:
            return self.mock_engine.get_clock()

    def reset_account(self, cash: float = 100000.0) -> Dict[str, Any]:
        """Resets the account balance and closes all positions in mock paper mode."""
        return self.mock_engine.reset_account(cash)

    def get_account(self) -> Dict[str, Any]:
        if self._force_mock:
            return self.mock_engine.get_account()
        try:
            resp = requests.get(f"{self.base_url}/v2/account", headers=self._headers, timeout=5)
            resp.raise_for_status()
            data = resp.json()
            eq = float(data.get("equity", 0))
            last_eq = float(data.get("last_equity", eq))
            daily_pnl = round(eq - last_eq, 2)
            daily_pnl_pct = round((daily_pnl / last_eq * 100.0) if last_eq > 0 else 0.0, 2)
            data["daily_pnl"] = daily_pnl
            data["daily_pnl_pct"] = daily_pnl_pct
            return data
        except Exception:
            return self.mock_engine.get_account()

    def get_positions(self) -> List[Dict[str, Any]]:
        if self._force_mock:
            return self.mock_engine.get_positions()
        try:
            resp = requests.get(f"{self.base_url}/v2/positions", headers=self._headers, timeout=5)
            resp.raise_for_status()
            return resp.json()
        except Exception:
            return self.mock_engine.get_positions()

    def get_position(self, symbol: str) -> Optional[Dict[str, Any]]:
        if self._force_mock:
            return self.mock_engine.get_position(symbol)
        try:
            resp = requests.get(f"{self.base_url}/v2/positions/{symbol.upper()}", headers=self._headers, timeout=5)
            if resp.status_code == 200:
                return resp.json()
            return None
        except Exception:
            return self.mock_engine.get_position(symbol)

    def close_position(self, symbol: str) -> Dict[str, Any]:
        if self._force_mock:
            return self.mock_engine.close_position(symbol)
        try:
            resp = requests.delete(f"{self.base_url}/v2/positions/{symbol.upper()}", headers=self._headers, timeout=5)
            resp.raise_for_status()
            return resp.json()
        except Exception:
            return self.mock_engine.close_position(symbol)

    def create_order(
        self,
        symbol: str,
        qty: int,
        side: str,
        order_type: str = "market",
        time_in_force: str = "gtc",
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None
    ) -> Dict[str, Any]:
        if self._force_mock:
            return self.mock_engine.create_order(
                symbol=symbol,
                qty=qty,
                side=side,
                order_type=order_type,
                time_in_force=time_in_force,
                stop_loss=stop_loss,
                take_profit=take_profit
            )
        try:
            payload: Dict[str, Any] = {
                "symbol": symbol.upper(),
                "qty": str(qty),
                "side": side.lower(),
                "type": order_type,
                "time_in_force": time_in_force
            }
            # Add bracket order legs if stop loss and take profit are provided
            if stop_loss and take_profit:
                payload["order_class"] = "bracket"
                payload["take_profit"] = {"limit_price": str(round(take_profit, 2))}
                payload["stop_loss"] = {"stop_price": str(round(stop_loss, 2))}
            
            resp = requests.post(f"{self.base_url}/v2/orders", headers=self._headers, json=payload, timeout=5)
            resp.raise_for_status()
            return resp.json()
        except Exception:
            # Fallback to local execution if remote rejected or errored
            return self.mock_engine.create_order(
                symbol=symbol,
                qty=qty,
                side=side,
                order_type=order_type,
                time_in_force=time_in_force,
                stop_loss=stop_loss,
                take_profit=take_profit
            )

    def get_latest_trade(self, symbol: str) -> Dict[str, Any]:
        if self._force_mock:
            return self.mock_engine.get_latest_trade(symbol)
        try:
            resp = requests.get(f"{self.data_url}/stocks/{symbol.upper()}/trades/latest", headers=self._headers, timeout=5)
            resp.raise_for_status()
            data = resp.json()
            trade = data.get("trade", {})
            return {
                "symbol": symbol.upper(),
                "price": float(trade.get("p", 0.0)),
                "size": int(trade.get("s", 0)),
                "timestamp": trade.get("t", datetime.datetime.now(datetime.timezone.utc).isoformat())
            }
        except Exception:
            return self.mock_engine.get_latest_trade(symbol)

    def get_bars(self, symbol: str, timeframe: str = "1Min", limit: int = 50) -> List[Dict[str, Any]]:
        if self._force_mock:
            return self.mock_engine.get_bars(symbol, timeframe, limit)
        try:
            resp = requests.get(
                f"{self.data_url}/stocks/{symbol.upper()}/bars",
                headers=self._headers,
                params={"timeframe": timeframe, "limit": limit},
                timeout=5
            )
            resp.raise_for_status()
            bars_data = resp.json().get("bars", [])
            if not bars_data:
                return self.mock_engine.get_bars(symbol, timeframe, limit)
            result = []
            for b in bars_data:
                result.append({
                    "t": b["t"],
                    "o": float(b["o"]),
                    "h": float(b["h"]),
                    "l": float(b["l"]),
                    "c": float(b["c"]),
                    "v": int(b["v"])
                })
            return result
        except Exception:
            return self.mock_engine.get_bars(symbol, timeframe, limit)
