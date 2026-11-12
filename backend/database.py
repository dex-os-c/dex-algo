"""
Quantitative & Crypto Analytics SQLite Database Engine
======================================================
Stores account equity snapshots, trade lifecycle records, signals, bot logs,
and institutional crypto analytics:
1. crypto_regimes: ADX trend strength, Bollinger Band width, and detected regimes.
2. alpha_signals: Multi-alpha composite scores, component scores (Trend, Mean Reversion, OFI), and actions.
3. orderbook_snapshots: Level 2 depth (bid/ask volume), spread, and order flow imbalance.
4. Institutional Metrics: Sharpe (annualized 365d), Sortino (downside-only), Calmar (return/MDD),
   Profit Factor, Win Rate, Expectancy, and Average Trade Duration.
"""

import sqlite3
import datetime
import math
import json
import dataclasses
import threading
from typing import List, Dict, Any, Optional, Union
from config import get_config

_db_lock = threading.Lock()


# =====================================================================
# Clean JSON Sanitization & Serialization Helpers
# =====================================================================

def sanitize_for_json(obj: Any) -> Any:
    """
    Recursively cleanses an arbitrary Python object into JSON-compliant primitives:
    - Replaces NaN and +/- Infinity with 0.0 or None to prevent JSON serialization errors
    - Converts Dataclasses, Pydantic models, NumPy scalars/arrays to native types
    - Converts Datetime, Date, and Enums to ISO strings / scalar values
    """
    if obj is None:
        return None
    if isinstance(obj, (bool, str, int)):
        return obj
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return 0.0
        return obj

    # NumPy support
    try:
        import numpy as np
        if isinstance(obj, (np.floating, np.integer, np.bool_)):
            val = obj.item()
            if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
                return 0.0
            return val
        if isinstance(obj, np.ndarray):
            return [sanitize_for_json(x) for x in obj.tolist()]
    except ImportError:
        pass

    if isinstance(obj, (datetime.datetime, datetime.date)):
        return obj.isoformat()
    if hasattr(obj, "value"):  # Enum
        return obj.value
    if hasattr(obj, "to_dict") and callable(obj.to_dict):
        try:
            return sanitize_for_json(obj.to_dict())
        except Exception:
            pass
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return sanitize_for_json(dataclasses.asdict(obj))
    if hasattr(obj, "model_dump") and callable(obj.model_dump):  # Pydantic v2
        return sanitize_for_json(obj.model_dump())
    if hasattr(obj, "dict") and callable(obj.dict):  # Pydantic v1
        return sanitize_for_json(obj.dict())
    if isinstance(obj, dict):
        return {str(k): sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [sanitize_for_json(x) for x in obj]
    return str(obj)


def safe_json_dumps(obj: Any, **kwargs) -> str:
    """Safely serializes any object to JSON string after thorough sanitization."""
    cleaned = sanitize_for_json(obj)
    return json.dumps(cleaned, **kwargs)


def get_db_path() -> str:
    return get_config().DB_PATH


def get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    path = db_path or get_db_path()
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Optional[str] = None):
    with _db_lock:
        conn = get_connection(db_path)
        cur = conn.cursor()
        
        # 1. Equity history table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS equity_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                equity REAL NOT NULL,
                cash REAL NOT NULL,
                buying_power REAL NOT NULL,
                unrealized_pnl REAL DEFAULT 0.0,
                daily_pnl REAL DEFAULT 0.0
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_equity_ts ON equity_history (timestamp)")

        # 2. Trades table (supports both integer equity shares and fractional crypto units)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT NOT NULL UNIQUE,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                qty REAL NOT NULL,
                price REAL NOT NULL,
                stop_loss REAL DEFAULT 0.0,
                take_profit REAL DEFAULT 0.0,
                status TEXT NOT NULL,
                realized_pnl REAL DEFAULT 0.0,
                timestamp TEXT NOT NULL,
                exit_timestamp TEXT,
                exit_price REAL DEFAULT 0.0
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades (symbol)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_trades_status ON trades (status)")

        # 3. Signals table (legacy/general signals)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                signal_type TEXT NOT NULL,
                price REAL NOT NULL,
                fast_ema REAL,
                slow_ema REAL,
                rsi REAL,
                atr REAL,
                reason TEXT
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_signals_ts ON signals (timestamp)")

        # 4. Bot logs table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bot_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                level TEXT NOT NULL,
                message TEXT NOT NULL
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_logs_ts ON bot_logs (timestamp)")

        # 5. Bot settings table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bot_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)

        # 6. Institutional Crypto Table: crypto_regimes
        cur.execute("""
            CREATE TABLE IF NOT EXISTS crypto_regimes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                regime TEXT NOT NULL,
                adx REAL,
                bb_width REAL,
                confidence REAL DEFAULT 1.0
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_crypto_regimes_ts ON crypto_regimes (timestamp)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_crypto_regimes_symbol ON crypto_regimes (symbol)")

        # 7. Institutional Crypto Table: alpha_signals
        cur.execute("""
            CREATE TABLE IF NOT EXISTS alpha_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                composite_score REAL NOT NULL,
                trend_score REAL,
                mean_rev_score REAL,
                ofi_score REAL,
                regime TEXT,
                action TEXT NOT NULL
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_alpha_signals_ts ON alpha_signals (timestamp)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_alpha_signals_symbol ON alpha_signals (symbol)")

        # 8. Institutional Crypto Table: orderbook_snapshots
        cur.execute("""
            CREATE TABLE IF NOT EXISTS orderbook_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                bid_depth REAL NOT NULL,
                ask_depth REAL NOT NULL,
                spread REAL NOT NULL,
                imbalance REAL NOT NULL,
                mid_price REAL,
                bids_json TEXT,
                asks_json TEXT
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_orderbook_ts ON orderbook_snapshots (timestamp)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_orderbook_symbol ON orderbook_snapshots (symbol)")

        # 9. Institutional Decision Snapshots Table (feature snapshots for all engine decisions)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS decision_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                action TEXT NOT NULL,
                price REAL NOT NULL,
                active_regime TEXT NOT NULL,
                regime_confidence REAL,
                parkinson_vol REAL,
                yang_zhang_vol REAL,
                realized_vol REAL,
                adx REAL,
                plus_di REAL,
                minus_di REAL,
                bbw_percentile REAL,
                vwap_zscore REAL,
                volume_delta_ratio REAL,
                cvd_20 REAL,
                atr REAL,
                htf_trend_bias TEXT,
                trend_score REAL,
                mean_rev_score REAL,
                breakout_score REAL,
                ofi_score REAL,
                composite_score REAL,
                kelly_fraction REAL,
                target_vol_size REAL,
                proposed_size REAL,
                executed_size REAL,
                reason TEXT,
                metadata TEXT
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_decisions_ts ON decision_snapshots (timestamp)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_decisions_symbol ON decision_snapshots (symbol)")

        # 10. Position Heatmaps Table (multi-asset exposure, weights, PnL, and heat scores)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS position_heatmaps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                total_equity REAL NOT NULL,
                gross_exposure REAL NOT NULL,
                net_exposure REAL NOT NULL,
                leverage REAL DEFAULT 1.0,
                positions_json TEXT NOT NULL,
                metadata_json TEXT
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_heatmaps_ts ON position_heatmaps (timestamp)")

        # 11. Walk-Forward Backtest & Cross-Validation Metrics Table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS walk_forward_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                strategy_name TEXT NOT NULL,
                total_trades INTEGER,
                win_rate REAL,
                profit_factor REAL,
                expectancy REAL,
                annualized_return REAL,
                annualized_sharpe REAL,
                sortino_ratio REAL,
                calmar_ratio REAL,
                max_drawdown_pct REAL,
                max_drawdown_duration INTEGER,
                average_r_multiple REAL,
                payoff_ratio REAL,
                market_exposure_pct REAL,
                final_equity REAL,
                net_profit REAL,
                in_sample_sharpe REAL,
                out_of_sample_sharpe REAL,
                degradation_ratio REAL,
                is_overfit INTEGER DEFAULT 0,
                folds_json TEXT,
                monte_carlo_json TEXT,
                metadata_json TEXT
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_wfo_ts ON walk_forward_metrics (timestamp)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_wfo_symbol ON walk_forward_metrics (symbol)")

        # Safe schema migrations for existing databases
        migrations = [
            "ALTER TABLE crypto_regimes ADD COLUMN plus_di REAL",
            "ALTER TABLE crypto_regimes ADD COLUMN minus_di REAL",
            "ALTER TABLE crypto_regimes ADD COLUMN bbw_percentile REAL",
            "ALTER TABLE crypto_regimes ADD COLUMN volatility_zscore REAL",
            "ALTER TABLE crypto_regimes ADD COLUMN weights TEXT",
            "ALTER TABLE alpha_signals ADD COLUMN confidence REAL",
            "ALTER TABLE alpha_signals ADD COLUMN weights TEXT",
            "ALTER TABLE orderbook_snapshots ADD COLUMN mid_price REAL",
            "ALTER TABLE orderbook_snapshots ADD COLUMN bids_json TEXT",
            "ALTER TABLE orderbook_snapshots ADD COLUMN asks_json TEXT",
        ]
        for mig in migrations:
            try:
                cur.execute(mig)
            except Exception:
                pass

        conn.commit()
        conn.close()


def record_equity(
    equity: float,
    cash: float,
    buying_power: float,
    unrealized_pnl: float = 0.0,
    daily_pnl: float = 0.0,
    timestamp: Optional[str] = None,
    db_path: Optional[str] = None
) -> int:
    ts = timestamp or datetime.datetime.now(datetime.timezone.utc).isoformat()
    with _db_lock:
        conn = get_connection(db_path)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO equity_history (timestamp, equity, cash, buying_power, unrealized_pnl, daily_pnl)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (ts, round(equity, 2), round(cash, 2), round(buying_power, 2), round(unrealized_pnl, 2), round(daily_pnl, 2)))
        inserted_id = cur.lastrowid
        conn.commit()
        conn.close()
        return inserted_id


def get_equity_history(limit: int = 100, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    with _db_lock:
        conn = get_connection(db_path)
        cur = conn.cursor()
        cur.execute("""
            SELECT id, timestamp, equity, cash, buying_power, unrealized_pnl, daily_pnl
            FROM equity_history
            ORDER BY id ASC
            LIMIT ?
        """, (limit,))
        rows = [dict(row) for row in cur.fetchall()]
        conn.close()
        return rows


def record_trade(
    order_id: str,
    symbol: str,
    side: str,
    qty: Union[int, float],
    price: float,
    stop_loss: float = 0.0,
    take_profit: float = 0.0,
    status: str = "OPEN",
    timestamp: Optional[str] = None,
    db_path: Optional[str] = None
) -> int:
    ts = timestamp or datetime.datetime.now(datetime.timezone.utc).isoformat()
    with _db_lock:
        conn = get_connection(db_path)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO trades (order_id, symbol, side, qty, price, stop_loss, take_profit, status, realized_pnl, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0.0, ?)
            ON CONFLICT(order_id) DO UPDATE SET
                status=excluded.status,
                price=excluded.price,
                stop_loss=excluded.stop_loss,
                take_profit=excluded.take_profit
        """, (
            order_id,
            symbol,
            side.upper(),
            float(qty) if isinstance(qty, float) else qty,
            round(price, 4),
            round(stop_loss, 4),
            round(take_profit, 4),
            status.upper(),
            ts
        ))
        row_id = cur.lastrowid
        conn.commit()
        conn.close()
        return row_id


def update_trade_exit(
    order_id: str,
    exit_price: float,
    realized_pnl: float,
    exit_timestamp: Optional[str] = None,
    status: str = "CLOSED",
    db_path: Optional[str] = None
) -> bool:
    ts = exit_timestamp or datetime.datetime.now(datetime.timezone.utc).isoformat()
    with _db_lock:
        conn = get_connection(db_path)
        cur = conn.cursor()
        cur.execute("""
            UPDATE trades
            SET exit_price = ?,
                realized_pnl = ?,
                exit_timestamp = ?,
                status = ?
            WHERE order_id = ?
        """, (round(exit_price, 4), round(realized_pnl, 2), ts, status.upper(), order_id))
        modified = cur.rowcount > 0
        conn.commit()
        conn.close()
        return modified


def get_trades(limit: int = 50, status: Optional[str] = None, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    with _db_lock:
        conn = get_connection(db_path)
        cur = conn.cursor()
        if status:
            cur.execute("""
                SELECT * FROM trades
                WHERE status = ?
                ORDER BY id DESC
                LIMIT ?
            """, (status.upper(), limit))
        else:
            cur.execute("""
                SELECT * FROM trades
                ORDER BY id DESC
                LIMIT ?
            """, (limit,))
        rows = [dict(row) for row in cur.fetchall()]
        conn.close()
        return rows


def record_signal(
    symbol: str,
    signal_type: str,
    price: float,
    fast_ema: Optional[float] = None,
    slow_ema: Optional[float] = None,
    rsi: Optional[float] = None,
    atr: Optional[float] = None,
    reason: str = "",
    timestamp: Optional[str] = None,
    db_path: Optional[str] = None
) -> int:
    ts = timestamp or datetime.datetime.now(datetime.timezone.utc).isoformat()
    with _db_lock:
        conn = get_connection(db_path)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO signals (timestamp, symbol, signal_type, price, fast_ema, slow_ema, rsi, atr, reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            ts,
            symbol,
            signal_type.upper(),
            round(price, 4),
            round(fast_ema, 4) if fast_ema is not None else None,
            round(slow_ema, 4) if slow_ema is not None else None,
            round(rsi, 2) if rsi is not None else None,
            round(atr, 4) if atr is not None else None,
            reason
        ))
        row_id = cur.lastrowid
        conn.commit()
        conn.close()
        return row_id


def get_signals(limit: int = 50, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    with _db_lock:
        conn = get_connection(db_path)
        cur = conn.cursor()
        cur.execute("SELECT * FROM signals ORDER BY id DESC LIMIT ?", (limit,))
        rows = [dict(row) for row in cur.fetchall()]
        conn.close()
        return rows


def add_log(level: str, message: str, timestamp: Optional[str] = None, db_path: Optional[str] = None) -> int:
    ts = timestamp or datetime.datetime.now(datetime.timezone.utc).isoformat()
    with _db_lock:
        conn = get_connection(db_path)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO bot_logs (timestamp, level, message)
            VALUES (?, ?, ?)
        """, (ts, level.upper(), message))
        row_id = cur.lastrowid
        conn.commit()
        conn.close()
        return row_id


def get_logs(limit: int = 100, level: Optional[str] = None, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    with _db_lock:
        conn = get_connection(db_path)
        cur = conn.cursor()
        if level:
            cur.execute("""
                SELECT * FROM bot_logs
                WHERE level = ?
                ORDER BY id DESC
                LIMIT ?
            """, (level.upper(), limit))
        else:
            cur.execute("""
                SELECT * FROM bot_logs
                ORDER BY id DESC
                LIMIT ?
            """, (limit,))
        rows = [dict(row) for row in cur.fetchall()]
        conn.close()
        return rows


def set_setting(key: str, value: str, db_path: Optional[str] = None):
    with _db_lock:
        conn = get_connection(db_path)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO bot_settings (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """, (key, str(value)))
        conn.commit()
        conn.close()


def get_setting(key: str, default: Optional[str] = None, db_path: Optional[str] = None) -> Optional[str]:
    with _db_lock:
        conn = get_connection(db_path)
        cur = conn.cursor()
        cur.execute("SELECT value FROM bot_settings WHERE key = ?", (key,))
        row = cur.fetchone()
        conn.close()
        return row["value"] if row else default


# ==============================================================================
# Institutional Crypto Analytics Database Functions
# ==============================================================================

def record_crypto_regime(
    symbol: str,
    regime: str,
    adx: Optional[float] = None,
    bb_width: Optional[float] = None,
    confidence: float = 1.0,
    plus_di: Optional[float] = None,
    minus_di: Optional[float] = None,
    bbw_percentile: Optional[float] = None,
    volatility_zscore: Optional[float] = None,
    weights: Optional[Dict[str, float]] = None,
    timestamp: Optional[str] = None,
    db_path: Optional[str] = None
) -> int:
    """
    Records detected market regime (TRENDING_BULL, TRENDING_BEAR, LOW_VOL_COMPRESSION, HIGH_VOL_BREAKOUT)
    along with directional ADX, Bollinger Band width percentile, dynamic alpha weights, and model confidence.
    """
    ts = timestamp or datetime.datetime.now(datetime.timezone.utc).isoformat()
    weights_json = safe_json_dumps(weights) if weights is not None else None
    bbw_val = bbw_percentile if bbw_percentile is not None else bb_width

    with _db_lock:
        conn = get_connection(db_path)
        cur = conn.cursor()
        try:
            cur.execute("""
                INSERT INTO crypto_regimes (timestamp, symbol, regime, adx, bb_width, confidence, plus_di, minus_di, bbw_percentile, volatility_zscore, weights)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                ts,
                symbol.upper(),
                regime.upper(),
                round(adx, 4) if adx is not None else None,
                round(bbw_val, 6) if bbw_val is not None else None,
                round(confidence, 4) if confidence is not None else 1.0,
                round(plus_di, 4) if plus_di is not None else None,
                round(minus_di, 4) if minus_di is not None else None,
                round(bbw_percentile, 4) if bbw_percentile is not None else (round(bb_width, 4) if bb_width is not None else None),
                round(volatility_zscore, 4) if volatility_zscore is not None else None,
                weights_json
            ))
        except Exception:
            # Fallback for baseline schema
            cur.execute("""
                INSERT INTO crypto_regimes (timestamp, symbol, regime, adx, bb_width, confidence)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                ts,
                symbol.upper(),
                regime.upper(),
                round(adx, 4) if adx is not None else None,
                round(bbw_val, 6) if bbw_val is not None else None,
                round(confidence, 4) if confidence is not None else 1.0
            ))
        row_id = cur.lastrowid
        conn.commit()
        conn.close()
        return row_id


def get_recent_regimes(
    limit: int = 50,
    symbol: Optional[str] = None,
    db_path: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Fetches historical market regimes in descending chronological order with parsed weights."""
    with _db_lock:
        conn = get_connection(db_path)
        cur = conn.cursor()
        if symbol:
            cur.execute("""
                SELECT * FROM crypto_regimes
                WHERE symbol = ?
                ORDER BY id DESC
                LIMIT ?
            """, (symbol.upper(), limit))
        else:
            cur.execute("""
                SELECT * FROM crypto_regimes
                ORDER BY id DESC
                LIMIT ?
            """, (limit,))
        raw_rows = [dict(row) for row in cur.fetchall()]
        conn.close()

    rows = []
    for r in raw_rows:
        item = sanitize_for_json(r)
        if "weights" in item and item["weights"] and isinstance(item["weights"], str):
            try:
                item["weights"] = json.loads(item["weights"])
            except Exception:
                pass
        rows.append(item)
    return rows


def get_latest_regime(
    symbol: Optional[str] = None,
    db_path: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Fetches the most recent detected crypto regime."""
    regimes = get_recent_regimes(limit=1, symbol=symbol, db_path=db_path)
    return regimes[0] if regimes else None


def record_alpha_signal(
    symbol: str,
    composite_score: float,
    trend_score: Optional[float] = None,
    mean_rev_score: Optional[float] = None,
    ofi_score: Optional[float] = None,
    regime: Optional[str] = None,
    action: str = "NEUTRAL",
    confidence: Optional[float] = None,
    weights: Optional[Dict[str, float]] = None,
    timestamp: Optional[str] = None,
    db_path: Optional[str] = None
) -> int:
    """
    Records composite multi-alpha signal (-1.0 to +1.0) along with underlying alpha component
    scores (Trend, Mean Reversion, Order Flow Imbalance), active regime, confidence, and recommended action.
    """
    ts = timestamp or datetime.datetime.now(datetime.timezone.utc).isoformat()
    weights_json = safe_json_dumps(weights) if weights is not None else None

    with _db_lock:
        conn = get_connection(db_path)
        cur = conn.cursor()
        try:
            cur.execute("""
                INSERT INTO alpha_signals (timestamp, symbol, composite_score, trend_score, mean_rev_score, ofi_score, regime, action, confidence, weights)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                ts,
                symbol.upper(),
                round(composite_score, 4),
                round(trend_score, 4) if trend_score is not None else None,
                round(mean_rev_score, 4) if mean_rev_score is not None else None,
                round(ofi_score, 4) if ofi_score is not None else None,
                regime.upper() if regime else None,
                action.upper(),
                round(confidence, 4) if confidence is not None else None,
                weights_json
            ))
        except Exception:
            cur.execute("""
                INSERT INTO alpha_signals (timestamp, symbol, composite_score, trend_score, mean_rev_score, ofi_score, regime, action)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                ts,
                symbol.upper(),
                round(composite_score, 4),
                round(trend_score, 4) if trend_score is not None else None,
                round(mean_rev_score, 4) if mean_rev_score is not None else None,
                round(ofi_score, 4) if ofi_score is not None else None,
                regime.upper() if regime else None,
                action.upper()
            ))
        row_id = cur.lastrowid
        conn.commit()
        conn.close()
        return row_id


def get_recent_alpha_signals(
    limit: int = 50,
    symbol: Optional[str] = None,
    db_path: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Fetches recent alpha signals in descending chronological order."""
    with _db_lock:
        conn = get_connection(db_path)
        cur = conn.cursor()
        if symbol:
            cur.execute("""
                SELECT * FROM alpha_signals
                WHERE symbol = ?
                ORDER BY id DESC
                LIMIT ?
            """, (symbol.upper(), limit))
        else:
            cur.execute("""
                SELECT * FROM alpha_signals
                ORDER BY id DESC
                LIMIT ?
            """, (limit,))
        raw_rows = [dict(row) for row in cur.fetchall()]
        conn.close()

    rows = []
    for r in raw_rows:
        item = sanitize_for_json(r)
        if "weights" in item and item["weights"] and isinstance(item["weights"], str):
            try:
                item["weights"] = json.loads(item["weights"])
            except Exception:
                pass
        rows.append(item)
    return rows


def get_latest_alpha_signal(
    symbol: Optional[str] = None,
    db_path: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Fetches the most recent alpha signal snapshot."""
    signals = get_recent_alpha_signals(limit=1, symbol=symbol, db_path=db_path)
    return signals[0] if signals else None


def record_orderbook_snapshot(
    symbol: str,
    bid_depth: float,
    ask_depth: float,
    spread: float,
    imbalance: float,
    mid_price: Optional[float] = None,
    bids: Optional[List[Dict[str, Any]]] = None,
    asks: Optional[List[Dict[str, Any]]] = None,
    timestamp: Optional[str] = None,
    db_path: Optional[str] = None
) -> int:
    """
    Records microstructure order book snapshot including aggregate bid volume,
    ask volume, bid-ask spread, order flow imbalance ratio, and Level-2 depth lists.
    """
    ts = timestamp or datetime.datetime.now(datetime.timezone.utc).isoformat()
    bids_json = safe_json_dumps(bids) if bids is not None else None
    asks_json = safe_json_dumps(asks) if asks is not None else None

    with _db_lock:
        conn = get_connection(db_path)
        cur = conn.cursor()
        try:
            cur.execute("""
                INSERT INTO orderbook_snapshots (timestamp, symbol, bid_depth, ask_depth, spread, imbalance, mid_price, bids_json, asks_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                ts,
                symbol.upper(),
                round(bid_depth, 4),
                round(ask_depth, 4),
                round(spread, 6),
                round(imbalance, 6),
                round(mid_price, 4) if mid_price is not None else None,
                bids_json,
                asks_json
            ))
        except Exception:
            cur.execute("""
                INSERT INTO orderbook_snapshots (timestamp, symbol, bid_depth, ask_depth, spread, imbalance)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                ts,
                symbol.upper(),
                round(bid_depth, 4),
                round(ask_depth, 4),
                round(spread, 6),
                round(imbalance, 6)
            ))
        row_id = cur.lastrowid
        conn.commit()
        conn.close()
        return row_id


def get_recent_orderbook_snapshots(
    limit: int = 50,
    symbol: Optional[str] = None,
    db_path: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Fetches recent order book snapshots in descending chronological order with parsed bids/asks."""
    with _db_lock:
        conn = get_connection(db_path)
        cur = conn.cursor()
        if symbol:
            cur.execute("""
                SELECT * FROM orderbook_snapshots
                WHERE symbol = ?
                ORDER BY id DESC
                LIMIT ?
            """, (symbol.upper(), limit))
        else:
            cur.execute("""
                SELECT * FROM orderbook_snapshots
                ORDER BY id DESC
                LIMIT ?
            """, (limit,))
        raw_rows = [dict(row) for row in cur.fetchall()]
        conn.close()

    rows = []
    for r in raw_rows:
        item = sanitize_for_json(r)
        if "bids_json" in item and item["bids_json"] and isinstance(item["bids_json"], str):
            try:
                item["bids"] = json.loads(item["bids_json"])
            except Exception:
                pass
        if "asks_json" in item and item["asks_json"] and isinstance(item["asks_json"], str):
            try:
                item["asks"] = json.loads(item["asks_json"])
            except Exception:
                pass
        rows.append(item)
    return rows


def get_latest_orderbook_snapshot(
    symbol: Optional[str] = None,
    db_path: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Fetches the most recent order book snapshot."""
    snapshots = get_recent_orderbook_snapshots(limit=1, symbol=symbol, db_path=db_path)
    return snapshots[0] if snapshots else None


# ==============================================================================
# Institutional Decision Snapshots Persistence
# ==============================================================================

def record_decision_snapshot(snapshot: Dict[str, Any], db_path: Optional[str] = None) -> int:
    """
    Persists complete microstructural decision snapshots into SQLite `decision_snapshots`.
    """
    ts = snapshot.get("timestamp") or datetime.datetime.now(datetime.timezone.utc).isoformat()
    meta_json = safe_json_dumps(snapshot.get("metadata", {}))

    with _db_lock:
        conn = get_connection(db_path)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO decision_snapshots (
                timestamp, symbol, action, price, active_regime, regime_confidence,
                parkinson_vol, yang_zhang_vol, realized_vol, adx, plus_di, minus_di,
                bbw_percentile, vwap_zscore, volume_delta_ratio, cvd_20, atr,
                htf_trend_bias, trend_score, mean_rev_score, breakout_score, ofi_score,
                composite_score, kelly_fraction, target_vol_size, proposed_size,
                executed_size, reason, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            ts,
            str(snapshot.get("symbol", "BTC/USD")).upper(),
            str(snapshot.get("action", "HOLD")).upper(),
            float(snapshot.get("price", 0.0)),
            str(snapshot.get("active_regime", "UNKNOWN")),
            float(snapshot.get("regime_confidence", 0.0)),
            float(snapshot.get("parkinson_vol", 0.0)),
            float(snapshot.get("yang_zhang_vol", 0.0)),
            float(snapshot.get("realized_vol", 0.0)),
            float(snapshot.get("adx", 0.0)),
            float(snapshot.get("plus_di", 0.0)),
            float(snapshot.get("minus_di", 0.0)),
            float(snapshot.get("bbw_percentile", 0.0)),
            float(snapshot.get("vwap_zscore", 0.0)),
            float(snapshot.get("volume_delta_ratio", 0.0)),
            float(snapshot.get("cvd_20", 0.0)),
            float(snapshot.get("atr", 0.0)),
            str(snapshot.get("htf_trend_bias", "NEUTRAL")),
            float(snapshot.get("trend_score", 0.0)),
            float(snapshot.get("mean_rev_score", 0.0)),
            float(snapshot.get("breakout_score", 0.0)),
            float(snapshot.get("ofi_score", 0.0)),
            float(snapshot.get("composite_score", 0.0)),
            float(snapshot.get("kelly_fraction", 0.0)),
            float(snapshot.get("target_vol_size", 0.0)),
            float(snapshot.get("proposed_size", 0.0)),
            float(snapshot.get("executed_size", 0.0)),
            str(snapshot.get("reason", "")),
            meta_json
        ))
        row_id = cur.lastrowid
        conn.commit()
        conn.close()
        return row_id


def get_decision_snapshots(
    limit: int = 50,
    symbol: Optional[str] = None,
    db_path: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Fetches historical algorithmic decision snapshots."""
    with _db_lock:
        conn = get_connection(db_path)
        cur = conn.cursor()
        if symbol:
            cur.execute("""
                SELECT * FROM decision_snapshots
                WHERE symbol = ?
                ORDER BY id DESC
                LIMIT ?
            """, (symbol.upper(), limit))
        else:
            cur.execute("""
                SELECT * FROM decision_snapshots
                ORDER BY id DESC
                LIMIT ?
            """, (limit,))
        raw_rows = [dict(row) for row in cur.fetchall()]
        conn.close()

    rows = []
    for r in raw_rows:
        item = sanitize_for_json(r)
        if "metadata" in item and item["metadata"] and isinstance(item["metadata"], str):
            try:
                item["metadata"] = json.loads(item["metadata"])
            except Exception:
                pass
        rows.append(item)
    return rows


# ==============================================================================
# Institutional Position Heatmap Persistence
# ==============================================================================

def record_position_heatmap(
    positions: List[Dict[str, Any]],
    total_equity: float,
    gross_exposure: float,
    net_exposure: float,
    leverage: float = 1.0,
    metadata: Optional[Dict[str, Any]] = None,
    timestamp: Optional[str] = None,
    db_path: Optional[str] = None
) -> int:
    """
    Persists a position heatmap snapshot containing multi-asset weights,
    notional values, unrealized PnL, leverage, and heat scores into SQLite.
    """
    ts = timestamp or datetime.datetime.now(datetime.timezone.utc).isoformat()
    pos_json = safe_json_dumps(positions)
    meta_json = safe_json_dumps(metadata or {})

    with _db_lock:
        conn = get_connection(db_path)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO position_heatmaps (timestamp, total_equity, gross_exposure, net_exposure, leverage, positions_json, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            ts,
            round(total_equity, 2),
            round(gross_exposure, 2),
            round(net_exposure, 2),
            round(leverage, 4),
            pos_json,
            meta_json
        ))
        row_id = cur.lastrowid
        conn.commit()
        conn.close()
        return row_id


def get_latest_position_heatmap(db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Fetches the most recent position heatmap snapshot with parsed position lists."""
    with _db_lock:
        conn = get_connection(db_path)
        cur = conn.cursor()
        cur.execute("SELECT * FROM position_heatmaps ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        conn.close()

    if not row:
        return None

    item = sanitize_for_json(dict(row))
    if "positions_json" in item and item["positions_json"]:
        try:
            item["positions"] = json.loads(item["positions_json"])
        except Exception:
            item["positions"] = []
    if "metadata_json" in item and item["metadata_json"]:
        try:
            item["metadata"] = json.loads(item["metadata_json"])
        except Exception:
            item["metadata"] = {}
    return item


def get_recent_position_heatmaps(limit: int = 20, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Fetches recent position heatmap snapshots."""
    with _db_lock:
        conn = get_connection(db_path)
        cur = conn.cursor()
        cur.execute("SELECT * FROM position_heatmaps ORDER BY id DESC LIMIT ?", (limit,))
        raw_rows = [dict(row) for row in cur.fetchall()]
        conn.close()

    rows = []
    for r in raw_rows:
        item = sanitize_for_json(r)
        if "positions_json" in item and item["positions_json"]:
            try:
                item["positions"] = json.loads(item["positions_json"])
            except Exception:
                item["positions"] = []
        rows.append(item)
    return rows


# ==============================================================================
# Walk-Forward Backtest & Cross-Validation Metrics Persistence
# ==============================================================================

def record_walk_forward_metrics(
    symbol: str,
    metrics: Dict[str, Any],
    strategy_name: str = "MultiAlphaEnsemble",
    timestamp: Optional[str] = None,
    db_path: Optional[str] = None
) -> int:
    """
    Persists Walk-Forward Optimization (WFO) results, cross-validation folds,
    overfitting degradation ratio, and Monte Carlo equity cone simulations into SQLite.
    """
    ts = timestamp or datetime.datetime.now(datetime.timezone.utc).isoformat()
    folds_json = safe_json_dumps(metrics.get("folds", []))
    monte_carlo_json = safe_json_dumps(metrics.get("monte_carlo", {}))
    meta_json = safe_json_dumps(metrics.get("metadata", {}))

    with _db_lock:
        conn = get_connection(db_path)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO walk_forward_metrics (
                timestamp, symbol, strategy_name, total_trades, win_rate, profit_factor,
                expectancy, annualized_return, annualized_sharpe, sortino_ratio, calmar_ratio,
                max_drawdown_pct, max_drawdown_duration, average_r_multiple, payoff_ratio,
                market_exposure_pct, final_equity, net_profit, in_sample_sharpe,
                out_of_sample_sharpe, degradation_ratio, is_overfit, folds_json,
                monte_carlo_json, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            ts,
            symbol.upper(),
            strategy_name,
            int(metrics.get("total_trades", 0)),
            float(metrics.get("win_rate", 0.0)),
            float(metrics.get("profit_factor", 1.0)),
            float(metrics.get("expectancy", 0.0)),
            float(metrics.get("annualized_return", 0.0)),
            float(metrics.get("annualized_sharpe", 0.0)),
            float(metrics.get("sortino_ratio", 0.0)),
            float(metrics.get("calmar_ratio", 0.0)),
            float(metrics.get("max_drawdown_pct", 0.0)),
            int(metrics.get("max_drawdown_duration", 0)),
            float(metrics.get("average_r_multiple", 0.0)),
            float(metrics.get("payoff_ratio", 1.0)),
            float(metrics.get("market_exposure_pct", 0.0)),
            float(metrics.get("final_equity", 100000.0)),
            float(metrics.get("net_profit", 0.0)),
            float(metrics.get("in_sample_sharpe", metrics.get("avg_in_sample_sharpe", 0.0))),
            float(metrics.get("out_of_sample_sharpe", metrics.get("avg_out_of_sample_sharpe", 0.0))),
            float(metrics.get("degradation_ratio", metrics.get("overfitting_degradation_ratio", 0.0))),
            1 if metrics.get("is_overfit", False) else 0,
            folds_json,
            monte_carlo_json,
            meta_json
        ))
        row_id = cur.lastrowid
        conn.commit()
        conn.close()
        return row_id


def get_latest_walk_forward_metrics(
    symbol: Optional[str] = None,
    db_path: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Fetches the latest Walk-Forward Optimization tear sheet and cross-validation metrics."""
    with _db_lock:
        conn = get_connection(db_path)
        cur = conn.cursor()
        if symbol:
            cur.execute("""
                SELECT * FROM walk_forward_metrics
                WHERE symbol = ?
                ORDER BY id DESC
                LIMIT 1
            """, (symbol.upper(),))
        else:
            cur.execute("SELECT * FROM walk_forward_metrics ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        conn.close()

    if not row:
        return None

    item = sanitize_for_json(dict(row))
    if "folds_json" in item and item["folds_json"]:
        try:
            item["folds"] = json.loads(item["folds_json"])
        except Exception:
            item["folds"] = []
    if "monte_carlo_json" in item and item["monte_carlo_json"]:
        try:
            item["monte_carlo"] = json.loads(item["monte_carlo_json"])
        except Exception:
            item["monte_carlo"] = {}
    if "metadata_json" in item and item["metadata_json"]:
        try:
            item["metadata"] = json.loads(item["metadata_json"])
        except Exception:
            item["metadata"] = {}
    item["is_overfit"] = bool(item.get("is_overfit", 0))
    if "max_drawdown" not in item:
        item["max_drawdown"] = item.get("max_drawdown_pct", 0.0)
    return item


def get_all_walk_forward_metrics(
    limit: int = 20,
    db_path: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Fetches historical Walk-Forward Optimization runs across symbols."""
    with _db_lock:
        conn = get_connection(db_path)
        cur = conn.cursor()
        cur.execute("SELECT * FROM walk_forward_metrics ORDER BY id DESC LIMIT ?", (limit,))
        raw_rows = [dict(row) for row in cur.fetchall()]
        conn.close()

    rows = []
    for r in raw_rows:
        item = sanitize_for_json(r)
        if "folds_json" in item and item["folds_json"]:
            try:
                item["folds"] = json.loads(item["folds_json"])
            except Exception:
                item["folds"] = []
        if "monte_carlo_json" in item and item["monte_carlo_json"]:
            try:
                item["monte_carlo"] = json.loads(item["monte_carlo_json"])
            except Exception:
                item["monte_carlo"] = {}
        item["is_overfit"] = bool(item.get("is_overfit", 0))
        if "max_drawdown" not in item:
            item["max_drawdown"] = item.get("max_drawdown_pct", 0.0)
        rows.append(item)
    return rows


# ==============================================================================
# Institutional Risk & Performance Metrics Engine
# ==============================================================================

def get_institutional_metrics(db_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Calculates comprehensive institutional risk-adjusted performance metrics:
    - Sharpe Ratio (Annualized across 24/7/365 crypto calendar: mean / total std * sqrt(365))
    - Sortino Ratio (Annualized downside risk: penalizes only downside variance, critical for crypto)
    - Calmar Ratio (Annualized return / maximum peak-to-trough drawdown)
    - Profit Factor (Gross Profits / Gross Losses)
    - Win Rate (% of winning closed trades)
    - Expectancy (Average mathematical expected dollar value per trade)
    - Average Trade Duration (Formatted string and seconds between entry and exit)
    - Total Trades, Realized PnL, and Maximum Drawdown %
    """
    with _db_lock:
        conn = get_connection(db_path)
        cur = conn.cursor()

        # 1. Closed trades
        cur.execute("""
            SELECT id, order_id, symbol, side, qty, price, realized_pnl, timestamp, exit_timestamp
            FROM trades
            WHERE status = 'CLOSED'
            ORDER BY id ASC
        """)
        trades = [dict(row) for row in cur.fetchall()]

        # 2. Equity history
        cur.execute("""
            SELECT timestamp, equity
            FROM equity_history
            ORDER BY id ASC
        """)
        equity_rows = [dict(row) for row in cur.fetchall()]
        conn.close()

    pnls = [t["realized_pnl"] for t in trades]
    total_closed = len(pnls)
    winning_trades = sum(1 for p in pnls if p > 0)
    losing_trades = sum(1 for p in pnls if p < 0)
    total_realized_pnl = round(sum(pnls), 2)

    # Win Rate (%)
    win_rate = round((winning_trades / total_closed * 100.0), 1) if total_closed > 0 else 0.0

    # Profit Factor
    gross_profit = sum(p for p in pnls if p > 0)
    gross_loss = abs(sum(p for p in pnls if p < 0))
    if gross_loss > 0:
        profit_factor = round(gross_profit / gross_loss, 2)
    elif gross_profit > 0:
        profit_factor = round(gross_profit, 2)
    else:
        profit_factor = 1.0

    # Expectancy ($ per trade)
    expectancy = round(total_realized_pnl / total_closed, 2) if total_closed > 0 else 0.0

    # Average Trade Duration
    durations_seconds: List[float] = []
    for t in trades:
        t_entry_str = t.get("timestamp")
        t_exit_str = t.get("exit_timestamp")
        if t_entry_str and t_exit_str:
            try:
                t_entry = datetime.datetime.fromisoformat(t_entry_str.replace("Z", "+00:00"))
                t_exit = datetime.datetime.fromisoformat(t_exit_str.replace("Z", "+00:00"))
                duration = (t_exit - t_entry).total_seconds()
                if duration >= 0:
                    durations_seconds.append(duration)
            except Exception:
                pass

    if durations_seconds:
        avg_duration_sec = sum(durations_seconds) / len(durations_seconds)
    else:
        avg_duration_sec = 0.0

    # Human-formatted duration string
    if avg_duration_sec >= 86400:
        days = int(avg_duration_sec // 86400)
        hours = int((avg_duration_sec % 86400) // 3600)
        avg_trade_duration = f"{days}d {hours}h"
    elif avg_duration_sec >= 3600:
        hours = int(avg_duration_sec // 3600)
        minutes = int((avg_duration_sec % 3600) // 60)
        avg_trade_duration = f"{hours}h {minutes}m"
    elif avg_duration_sec >= 60:
        minutes = int(avg_duration_sec // 60)
        seconds = int(avg_duration_sec % 60)
        avg_trade_duration = f"{minutes}m {seconds}s"
    elif avg_duration_sec > 0:
        avg_trade_duration = f"{int(avg_duration_sec)}s"
    else:
        avg_trade_duration = "0m"

    # Max Drawdown from equity history (or cumulative trade PnL fallback)
    equities = [row["equity"] for row in equity_rows]
    max_dd_pct = 0.0
    if len(equities) >= 1:
        peak = equities[0]
        for eq in equities:
            if eq > peak:
                peak = eq
            if peak > 0:
                dd = (peak - eq) / peak * 100.0
                if dd > max_dd_pct:
                    max_dd_pct = dd
    elif total_closed > 0:
        sim_eq = 100000.0
        peak = sim_eq
        for p in pnls:
            sim_eq += p
            if sim_eq > peak:
                peak = sim_eq
            if peak > 0:
                dd = (peak - sim_eq) / peak * 100.0
                if dd > max_dd_pct:
                    max_dd_pct = dd

    max_dd_pct = round(max_dd_pct, 2)

    # Returns series for Sharpe, Sortino, Calmar
    returns: List[float] = []
    if len(equities) >= 2:
        for i in range(1, len(equities)):
            prev = equities[i - 1]
            if prev > 0:
                returns.append((equities[i] - prev) / prev)
    elif total_closed >= 1:
        base_cap = equities[0] if equities and equities[0] > 0 else 100000.0
        returns = [p / base_cap for p in pnls]

    # Annualization factor: 24/7/365 crypto calendar = sqrt(365)
    crypto_annual_factor = math.sqrt(365.0)

    sharpe_ratio = 0.0
    sortino_ratio = 0.0
    if len(returns) >= 2:
        mean_ret = sum(returns) / len(returns)
        variance = sum((r - mean_ret) ** 2 for r in returns) / (len(returns) - 1)
        std_ret = math.sqrt(variance) if variance > 0 else 0.0

        if std_ret > 1e-8:
            sharpe_ratio = round((mean_ret / std_ret) * crypto_annual_factor, 2)

        # Sortino Ratio: penalizes ONLY downside volatility (returns < 0)
        downside_returns = [min(r, 0.0) for r in returns]
        downside_var = sum(r ** 2 for r in downside_returns) / len(returns)
        downside_dev = math.sqrt(downside_var) if downside_var > 0 else 0.0

        if downside_dev > 1e-8:
            sortino_ratio = round((mean_ret / downside_dev) * crypto_annual_factor, 2)
        elif mean_ret > 0:
            sortino_ratio = round(max(sharpe_ratio, round(mean_ret * crypto_annual_factor * 10.0, 2)), 2)
            sortino_ratio = min(sortino_ratio, 99.99)
    elif len(returns) == 1:
        r = returns[0]
        if r > 0:
            sharpe_ratio = round(r * crypto_annual_factor, 2)
            sortino_ratio = round(sharpe_ratio * 1.5, 2)
        elif r < 0:
            sharpe_ratio = round(r * crypto_annual_factor, 2)
            sortino_ratio = round(r * crypto_annual_factor, 2)

    # Annualized Return & Calmar Ratio
    if len(equities) >= 2 and equities[0] > 0:
        total_return_pct = ((equities[-1] - equities[0]) / equities[0]) * 100.0
        try:
            t0 = datetime.datetime.fromisoformat(equity_rows[0]["timestamp"].replace("Z", "+00:00"))
            t1 = datetime.datetime.fromisoformat(equity_rows[-1]["timestamp"].replace("Z", "+00:00"))
            span_days = (t1 - t0).total_seconds() / 86400.0
            if span_days >= 1.0:
                annualized_return_pct = total_return_pct * (365.0 / span_days)
            else:
                annualized_return_pct = total_return_pct
        except Exception:
            annualized_return_pct = total_return_pct
    elif total_closed > 0:
        base_cap = equities[0] if equities and equities[0] > 0 else 100000.0
        total_return_pct = (total_realized_pnl / base_cap) * 100.0
        annualized_return_pct = total_return_pct
    else:
        total_return_pct = 0.0
        annualized_return_pct = 0.0

    annualized_return_pct = round(annualized_return_pct, 2)

    # Calmar ratio = Annualized Return / Max Drawdown
    if max_dd_pct > 0:
        calmar_ratio = round(annualized_return_pct / max_dd_pct, 2)
    elif annualized_return_pct > 0:
        calmar_ratio = round(min(annualized_return_pct, 10.0), 2)
    else:
        calmar_ratio = 0.0

    return {
        "sharpe_ratio": sharpe_ratio,
        "sortino_ratio": sortino_ratio,
        "calmar_ratio": calmar_ratio,
        "profit_factor": profit_factor,
        "win_rate": win_rate,
        "expectancy": expectancy,
        "avg_trade_duration": avg_trade_duration,
        "avg_trade_duration_seconds": round(avg_duration_sec, 1),
        "total_trades": total_closed,
        "winning_trades": winning_trades,
        "losing_trades": losing_trades,
        "total_realized_pnl": total_realized_pnl,
        "avg_trade_pnl": expectancy,
        "max_drawdown": max_dd_pct,
        "annualized_return": annualized_return_pct
    }


def get_performance_metrics(db_path: Optional[str] = None) -> Dict[str, Any]:
    """Legacy alias providing both base and institutional performance metrics for full compatibility."""
    return get_institutional_metrics(db_path=db_path)


class DatabaseManager:
    """Object-oriented wrapper around database module functions."""
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path
        init_db(db_path)

    def calculate_performance_metrics(self) -> Dict[str, Any]:
        return get_institutional_metrics(self.db_path)

    def get_performance_metrics(self) -> Dict[str, Any]:
        return get_institutional_metrics(self.db_path)

    def get_institutional_metrics(self) -> Dict[str, Any]:
        return get_institutional_metrics(self.db_path)

    def record_crypto_regime(self, *args, **kwargs) -> int:
        kwargs["db_path"] = self.db_path
        return record_crypto_regime(*args, **kwargs)

    def get_recent_regimes(self, *args, **kwargs) -> List[Dict[str, Any]]:
        kwargs["db_path"] = self.db_path
        return get_recent_regimes(*args, **kwargs)

    def get_latest_regime(self, *args, **kwargs) -> Optional[Dict[str, Any]]:
        kwargs["db_path"] = self.db_path
        return get_latest_regime(*args, **kwargs)

    def record_alpha_signal(self, *args, **kwargs) -> int:
        kwargs["db_path"] = self.db_path
        return record_alpha_signal(*args, **kwargs)

    def get_recent_alpha_signals(self, *args, **kwargs) -> List[Dict[str, Any]]:
        kwargs["db_path"] = self.db_path
        return get_recent_alpha_signals(*args, **kwargs)

    def get_latest_alpha_signal(self, *args, **kwargs) -> Optional[Dict[str, Any]]:
        kwargs["db_path"] = self.db_path
        return get_latest_alpha_signal(*args, **kwargs)

    def record_orderbook_snapshot(self, *args, **kwargs) -> int:
        kwargs["db_path"] = self.db_path
        return record_orderbook_snapshot(*args, **kwargs)

    def get_recent_orderbook_snapshots(self, *args, **kwargs) -> List[Dict[str, Any]]:
        kwargs["db_path"] = self.db_path
        return get_recent_orderbook_snapshots(*args, **kwargs)

    def get_latest_orderbook_snapshot(self, *args, **kwargs) -> Optional[Dict[str, Any]]:
        kwargs["db_path"] = self.db_path
        return get_latest_orderbook_snapshot(*args, **kwargs)

    def record_decision_snapshot(self, *args, **kwargs) -> int:
        kwargs["db_path"] = self.db_path
        return record_decision_snapshot(*args, **kwargs)

    def get_decision_snapshots(self, *args, **kwargs) -> List[Dict[str, Any]]:
        kwargs["db_path"] = self.db_path
        return get_decision_snapshots(*args, **kwargs)

    def record_position_heatmap(self, *args, **kwargs) -> int:
        kwargs["db_path"] = self.db_path
        return record_position_heatmap(*args, **kwargs)

    def get_latest_position_heatmap(self, *args, **kwargs) -> Optional[Dict[str, Any]]:
        kwargs["db_path"] = self.db_path
        return get_latest_position_heatmap(*args, **kwargs)

    def get_recent_position_heatmaps(self, *args, **kwargs) -> List[Dict[str, Any]]:
        kwargs["db_path"] = self.db_path
        return get_recent_position_heatmaps(*args, **kwargs)

    def record_walk_forward_metrics(self, *args, **kwargs) -> int:
        kwargs["db_path"] = self.db_path
        return record_walk_forward_metrics(*args, **kwargs)

    def get_latest_walk_forward_metrics(self, *args, **kwargs) -> Optional[Dict[str, Any]]:
        kwargs["db_path"] = self.db_path
        return get_latest_walk_forward_metrics(*args, **kwargs)

    def get_all_walk_forward_metrics(self, *args, **kwargs) -> List[Dict[str, Any]]:
        kwargs["db_path"] = self.db_path
        return get_all_walk_forward_metrics(*args, **kwargs)


_global_db_instance: Optional[DatabaseManager] = None

def get_db(db_path: Optional[str] = None) -> DatabaseManager:
    global _global_db_instance
    if _global_db_instance is None or db_path is not None:
        _global_db_instance = DatabaseManager(db_path)
    return _global_db_instance