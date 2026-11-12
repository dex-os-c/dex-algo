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
import threading
from typing import List, Dict, Any, Optional, Union
from config import get_config

_db_lock = threading.Lock()


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
                imbalance REAL NOT NULL
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_orderbook_ts ON orderbook_snapshots (timestamp)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_orderbook_symbol ON orderbook_snapshots (symbol)")

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
    timestamp: Optional[str] = None,
    db_path: Optional[str] = None
) -> int:
    """
    Records detected market regime (TRENDING_BULL, TRENDING_BEAR, MEAN_REVERTING_CHOP, HIGH_VOLATILITY_EXPANSION)
    along with directional ADX, Bollinger Band width percentile, and model confidence.
    """
    ts = timestamp or datetime.datetime.now(datetime.timezone.utc).isoformat()
    with _db_lock:
        conn = get_connection(db_path)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO crypto_regimes (timestamp, symbol, regime, adx, bb_width, confidence)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            ts,
            symbol.upper(),
            regime.upper(),
            round(adx, 4) if adx is not None else None,
            round(bb_width, 6) if bb_width is not None else None,
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
    """Fetches historical market regimes in descending chronological order."""
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
        rows = [dict(row) for row in cur.fetchall()]
        conn.close()
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
    timestamp: Optional[str] = None,
    db_path: Optional[str] = None
) -> int:
    """
    Records composite multi-alpha signal (-1.0 to +1.0) along with underlying alpha component
    scores (Trend, Mean Reversion, Order Flow Imbalance), active regime, and recommended action.
    """
    ts = timestamp or datetime.datetime.now(datetime.timezone.utc).isoformat()
    with _db_lock:
        conn = get_connection(db_path)
        cur = conn.cursor()
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
        rows = [dict(row) for row in cur.fetchall()]
        conn.close()
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
    timestamp: Optional[str] = None,
    db_path: Optional[str] = None
) -> int:
    """
    Records microstructure order book snapshot including aggregate bid volume,
    ask volume, bid-ask spread, and order flow imbalance ratio.
    """
    ts = timestamp or datetime.datetime.now(datetime.timezone.utc).isoformat()
    with _db_lock:
        conn = get_connection(db_path)
        cur = conn.cursor()
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
    """Fetches recent order book snapshots in descending chronological order."""
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
        rows = [dict(row) for row in cur.fetchall()]
        conn.close()
        return rows


def get_latest_orderbook_snapshot(
    symbol: Optional[str] = None,
    db_path: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Fetches the most recent order book snapshot."""
    snapshots = get_recent_orderbook_snapshots(limit=1, symbol=symbol, db_path=db_path)
    return snapshots[0] if snapshots else None


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


_global_db_instance: Optional[DatabaseManager] = None

def get_db(db_path: Optional[str] = None) -> DatabaseManager:
    global _global_db_instance
    if _global_db_instance is None or db_path is not None:
        _global_db_instance = DatabaseManager(db_path)
    return _global_db_instance