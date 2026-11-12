from typing import List, Dict, Any, Tuple
from config import get_config


def calculate_ema(prices: List[float], period: int) -> List[float]:
    """
    Computes the Exponential Moving Average (EMA) for a price series.
    Returns a list of the same length, where values prior to sufficient data
    contain simple averages or matching values.
    """
    if not prices:
        return []
    if len(prices) < period:
        # Fallback to cumulative average if not enough data
        ema = []
        cum = 0.0
        for i, p in enumerate(prices):
            cum += p
            ema.append(round(cum / (i + 1), 4))
        return ema

    k = 2.0 / (period + 1)
    ema = []
    
    # Seed with SMA of the first 'period' values
    sma = sum(prices[:period]) / period
    for _ in range(period - 1):
        ema.append(round(sma, 4))
    ema.append(round(sma, 4))

    # Calculate EMA for remaining elements
    current_ema = sma
    for price in prices[period:]:
        current_ema = (price * k) + (current_ema * (1.0 - k))
        ema.append(round(current_ema, 4))

    return ema


def calculate_rsi(prices: List[float], period: int = 14) -> List[float]:
    """
    Computes Relative Strength Index (RSI) using Wilder's smoothed method.
    Returns a list of RSI values (0.0 to 100.0).
    """
    if len(prices) <= 1:
        return [50.0] * len(prices)

    deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    gains = [max(d, 0.0) for d in deltas]
    losses = [abs(min(d, 0.0)) for d in deltas]

    rsi = [50.0]  # First point baseline

    if len(deltas) < period:
        # Not enough bars for full period; compute simple ratio
        for i in range(len(deltas)):
            sub_gains = gains[: i + 1]
            sub_losses = losses[: i + 1]
            avg_g = sum(sub_gains) / len(sub_gains)
            avg_l = sum(sub_losses) / len(sub_losses)
            if avg_l == 0:
                rsi.append(100.0 if avg_g > 0 else 50.0)
            else:
                rs = avg_g / avg_l
                rsi.append(round(100.0 - (100.0 / (1.0 + rs)), 2))
        return rsi

    # First smoothed averages
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for _ in range(period - 1):
        rsi.append(50.0)

    if avg_loss == 0:
        first_rsi = 100.0 if avg_gain > 0 else 50.0
    else:
        rs = avg_gain / avg_loss
        first_rsi = round(100.0 - (100.0 / (1.0 + rs)), 2)
    rsi.append(first_rsi)

    # Wilder's smoothing
    for i in range(period, len(deltas)):
        gain = gains[i]
        loss = losses[i]
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period

        if avg_loss == 0:
            val = 100.0 if avg_gain > 0 else 50.0
        else:
            rs = avg_gain / avg_loss
            val = round(100.0 - (100.0 / (1.0 + rs)), 2)
        rsi.append(val)

    return rsi


def calculate_atr(bars: List[Dict[str, Any]], period: int = 14) -> List[float]:
    """
    Computes Average True Range (ATR) across historical bars.
    True Range = max(H - L, abs(H - prev_Close), abs(L - prev_Close))
    """
    if not bars:
        return []

    tr_list = []
    for i in range(len(bars)):
        high = float(bars[i]["h"])
        low = float(bars[i]["l"])
        if i == 0:
            tr = high - low
        else:
            prev_close = float(bars[i - 1]["c"])
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close)
            )
        tr_list.append(tr)

    if len(tr_list) < period:
        # Return simple average of available bars
        avg_tr = sum(tr_list) / len(tr_list)
        return [round(avg_tr, 4)] * len(tr_list)

    atr = []
    # Seed ATR
    sma_tr = sum(tr_list[:period]) / period
    for _ in range(period - 1):
        atr.append(round(sma_tr, 4))
    atr.append(round(sma_tr, 4))

    current_atr = sma_tr
    for tr in tr_list[period:]:
        current_atr = (current_atr * (period - 1) + tr) / period
        atr.append(round(current_atr, 4))

    return atr


class TrendMomentumStrategy:
    """
    Quantitative Trading Strategy:
    1. Trend: Fast EMA (default 9) vs Slow EMA (default 21).
    2. Momentum: RSI (default 14) confirms entry strength and filters extreme states.
    3. Volatility Channel: ATR (default 14) establishes adaptive Stop-Loss & Take-Profit bands.
    """
    def __init__(self):
        self.config = get_config()

    def evaluate(self, bars: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Evaluates bar series and returns signal decision:
        {
            'signal': 'BUY' | 'SELL' | 'HOLD',
            'price': float,
            'fast_ema': float,
            'slow_ema': float,
            'rsi': float,
            'atr': float,
            'stop_loss': float,
            'take_profit': float,
            'reason': str
        }
        """
        cfg = get_config()
        if not bars or len(bars) < max(cfg.EMA_SLOW_PERIOD, cfg.ATR_PERIOD, cfg.RSI_PERIOD):
            # Not enough data for full calculation
            curr_px = float(bars[-1]["c"]) if bars else 100.0
            return {
                "signal": "HOLD",
                "price": curr_px,
                "fast_ema": curr_px,
                "slow_ema": curr_px,
                "rsi": 50.0,
                "atr": curr_px * 0.015,
                "stop_loss": curr_px * 0.98,
                "take_profit": curr_px * 1.03,
                "reason": "Insufficient historical bars to compute indicators"
            }

        closes = [float(b["c"]) for b in bars]
        fast_emas = calculate_ema(closes, cfg.EMA_FAST_PERIOD)
        slow_emas = calculate_ema(closes, cfg.EMA_SLOW_PERIOD)
        rsis = calculate_rsi(closes, cfg.RSI_PERIOD)
        atrs = calculate_atr(bars, cfg.ATR_PERIOD)

        curr_px = round(closes[-1], 2)
        curr_fast = fast_emas[-1]
        curr_slow = slow_emas[-1]
        prev_fast = fast_emas[-2]
        prev_slow = slow_emas[-2]
        curr_rsi = rsis[-1]
        curr_atr = max(atrs[-1], curr_px * 0.005)  # Floor ATR at 0.5% of price

        # Dynamic Stop-Loss & Take-Profit calculations
        stop_loss = round(curr_px - (cfg.ATR_MULTIPLIER * curr_atr), 2)
        take_profit = round(curr_px + (cfg.TAKE_PROFIT_MULTIPLIER * curr_atr), 2)

        # Bullish cross or bullish continuation with healthy RSI
        bullish_cross = (prev_fast <= prev_slow and curr_fast > curr_slow)
        bullish_trend = (curr_fast > curr_slow and (curr_fast - curr_slow) >= (prev_fast - prev_slow))
        healthy_momentum = (cfg.RSI_OVERSOLD <= curr_rsi <= cfg.RSI_OVERBOUGHT)

        # Bearish indicators
        bearish_cross = (prev_fast >= prev_slow and curr_fast < curr_slow)
        bearish_trend = (curr_fast < curr_slow)
        overbought = curr_rsi >= 75.0
        oversold_collapse = curr_rsi <= 32.0

        if (bullish_cross or bullish_trend) and healthy_momentum:
            signal = "BUY"
            reason = f"Bullish EMA({cfg.EMA_FAST_PERIOD}/{cfg.EMA_SLOW_PERIOD}) alignment with RSI {curr_rsi:.1f} in buy zone"
        elif bearish_cross or overbought or oversold_collapse:
            signal = "SELL"
            if overbought:
                reason = f"RSI overbought ({curr_rsi:.1f} >= 75.0), take profit / exit"
            elif bearish_cross:
                reason = f"Bearish EMA({cfg.EMA_FAST_PERIOD}/{cfg.EMA_SLOW_PERIOD}) death cross"
            else:
                reason = f"RSI breakdown ({curr_rsi:.1f} <= 32.0)"
        elif bearish_trend and curr_rsi < 45.0:
            signal = "SELL"
            reason = f"Downtrend confirmed (Fast EMA < Slow EMA, RSI {curr_rsi:.1f})"
        else:
            signal = "HOLD"
            reason = f"Neutral state: Fast EMA {curr_fast:.2f}, Slow EMA {curr_slow:.2f}, RSI {curr_rsi:.1f}"

        return {
            "signal": signal,
            "price": curr_px,
            "fast_ema": curr_fast,
            "slow_ema": curr_slow,
            "rsi": curr_rsi,
            "atr": curr_atr,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "reason": reason
        }
