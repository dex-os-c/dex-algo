"""
Institutional Feature Store & Microstructure Analytics Engine
=============================================================
Calculates causal, strictly lag-1 shifted quantitative features:
1. Volatility Estimators:
   - Parkinson Volatility (High-Low range estimator, unbiased for zero drift)
   - Yang-Zhang Volatility (Minimum-variance drift-independent estimator)
   - Realized Volatility (Rolling log-return annualized standard deviation)
2. Directional & Trend Features:
   - ADX(14) with Wilder's Smoothed +DI and -DI
   - SuperTrend / Trend Direction
   - Higher-Timeframe (HTF) Trend Bias Filter (EMA 50 / 200)
3. Microstructure & Order Flow:
   - Rolling Bollinger Bandwidth (BBW) Percentile
   - Session VWAP and Price Distance Z-Score
   - Trade Aggressor Volume Delta (Taker Buy vs Taker Sell) & CVD
   - Donchian Channel High/Low (20-period)
4. Anti-Lookahead Protection:
   - All feature arrays can be shifted by 1 bar (lag-1) so signals executed at
     time t strictly evaluate data up to time t-1.
"""

import math
from typing import List, Dict, Any, Optional, Tuple, Union
from dataclasses import dataclass, asdict
import numpy as np

from data_layer import Bar


@dataclass
class BarFeatures:
    """Quantitative feature snapshot for a single bar."""
    timestamp: str
    close: float
    # Volatilities (annualized %)
    parkinson_vol: float
    yang_zhang_vol: float
    realized_vol: float
    # Trend & Directional
    adx: float
    plus_di: float
    minus_di: float
    ema_fast: float
    ema_slow: float
    htf_bias: int         # +1 (Bull), -1 (Bear), 0 (Neutral)
    # Bandwidth & Breakout
    bb_upper: float
    bb_lower: float
    bb_mid: float
    bbw_percentile: float # 0 to 100
    donchian_high: float
    donchian_low: float
    # Order Flow & Microstructure
    vwap: float
    vwap_zscore: float
    volume_delta: float
    volume_delta_ratio: float  # -1.0 to +1.0
    cvd: float
    atr: float
    is_liquid_hour: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ==============================================================================
# 1. Advanced Realized Volatility Estimators
# ==============================================================================

def calculate_parkinson_volatility(
    highs: List[float],
    lows: List[float],
    window: int = 20,
    annualization_factor: float = 365.0 * 24.0  # For hourly crypto
) -> float:
    """
    Parkinson (1980) High-Low Range Volatility:
    sigma = sqrt( (1 / (4 * ln(2) * N)) * sum( (ln(H_i / L_i))^2 ) ) * sqrt(F)
    5x more efficient than close-to-close volatility under geometric Brownian motion.
    """
    n = len(highs)
    if n < window or window < 2:
        return 0.0

    recent_h = highs[-window:]
    recent_l = lows[-window:]
    
    sum_sq_log_ratio = 0.0
    valid_count = 0
    for h, l in zip(recent_h, recent_l):
        if h > 0 and l > 0 and h >= l:
            log_hl = math.log(h / l)
            sum_sq_log_ratio += log_hl * log_hl
            valid_count += 1

    if valid_count < 2:
        return 0.0

    factor = 1.0 / (4.0 * math.log(2.0) * valid_count)
    var = factor * sum_sq_log_ratio
    sigma = math.sqrt(max(0.0, var))
    return float(sigma * math.sqrt(annualization_factor))


def calculate_yang_zhang_volatility(
    opens: List[float],
    highs: List[float],
    lows: List[float],
    closes: List[float],
    window: int = 20,
    annualization_factor: float = 365.0 * 24.0
) -> float:
    """
    Yang-Zhang (2000) Volatility Estimator:
    Combines overnight jumps, open-to-close variance, and Rogers-Satchell drift-independent vol.
    sigma_YZ^2 = sigma_open^2 + k * sigma_close^2 + (1 - k) * sigma_RS^2
    where k = 0.34 / (1.34 + (N + 1) / (N - 1))
    """
    n = len(closes)
    if n < window + 1 or window < 3:
        return 0.0

    recent_o = opens[-window:]
    recent_h = highs[-window:]
    recent_l = lows[-window:]
    recent_c = closes[-window:]
    prev_c = closes[-(window + 1):-1]

    # 1. Overnight jump variance: ln(Open_i / Close_{i-1})
    u_list = [math.log(o / pc) for o, pc in zip(recent_o, prev_c) if o > 0 and pc > 0]
    if len(u_list) < 2:
        return 0.0
    u_mean = sum(u_list) / len(u_list)
    sigma_open_sq = sum((u - u_mean) ** 2 for u in u_list) / (len(u_list) - 1)

    # 2. Open-to-close variance: ln(Close_i / Open_i)
    c_list = [math.log(c / o) for c, o in zip(recent_c, recent_o) if c > 0 and o > 0]
    if len(c_list) < 2:
        return 0.0
    c_mean = sum(c_list) / len(c_list)
    sigma_close_sq = sum((c - c_mean) ** 2 for c in c_list) / (len(c_list) - 1)

    # 3. Rogers-Satchell variance (drift-independent):
    # RS_i = ln(H/C)*ln(H/O) + ln(L/C)*ln(L/O)
    rs_list = []
    for o, h, l, c in zip(recent_o, recent_h, recent_l, recent_c):
        if min(o, h, l, c) <= 0:
            continue
        # Protect against minor tick jitter where H < max(O,C) or L > min(O,C)
        h_adj = max(h, o, c)
        l_adj = min(l, o, c)
        rs = (math.log(h_adj / c) * math.log(h_adj / o)) + (math.log(l_adj / c) * math.log(l_adj / o))
        rs_list.append(max(0.0, rs))

    if not rs_list:
        return 0.0
    sigma_rs_sq = sum(rs_list) / len(rs_list)

    # 4. Weighting constant k
    N = float(len(u_list))
    if N <= 1.0:
        return 0.0
    k = 0.34 / (1.34 + (N + 1.0) / (N - 1.0))

    yz_var = sigma_open_sq + (k * sigma_close_sq) + ((1.0 - k) * sigma_rs_sq)
    sigma = math.sqrt(max(0.0, yz_var))
    return float(sigma * math.sqrt(annualization_factor))


def calculate_realized_volatility(
    closes: List[float],
    window: int = 20,
    annualization_factor: float = 365.0 * 24.0
) -> float:
    """Close-to-close log return annualized realized volatility."""
    if len(closes) < window + 1:
        return 0.0
    returns = [math.log(closes[i] / closes[i - 1]) for i in range(-window, 0)]
    std = float(np.std(returns, ddof=1)) if len(returns) > 1 else 0.0
    return float(std * math.sqrt(annualization_factor))


# ==============================================================================
# 2. Directional Movement & Trend Indicators
# ==============================================================================

def calculate_adx_system(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    period: int = 14
) -> Tuple[float, float, float]:
    """
    Wilder's Directional Movement System:
    Returns: (ADX, +DI, -DI)
    """
    n = len(closes)
    if n < period * 2:
        return 0.0, 0.0, 0.0

    tr_list = []
    plus_dm = []
    minus_dm = []

    for i in range(1, n):
        h = highs[i]
        l = lows[i]
        prev_c = closes[i - 1]
        prev_h = highs[i - 1]
        prev_l = lows[i - 1]

        # True Range
        tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
        tr_list.append(tr)

        # Directional Movement
        up_move = h - prev_h
        down_move = prev_l - l

        if up_move > down_move and up_move > 0:
            plus_dm.append(up_move)
        else:
            plus_dm.append(0.0)

        if down_move > up_move and down_move > 0:
            minus_dm.append(down_move)
        else:
            minus_dm.append(0.0)

    # Wilder's smoothing
    smoothed_tr = sum(tr_list[:period])
    smoothed_pdm = sum(plus_dm[:period])
    smoothed_mdm = sum(minus_dm[:period])

    dx_list = []
    for i in range(period, len(tr_list)):
        smoothed_tr = smoothed_tr - (smoothed_tr / period) + tr_list[i]
        smoothed_pdm = smoothed_pdm - (smoothed_pdm / period) + plus_dm[i]
        smoothed_mdm = smoothed_mdm - (smoothed_mdm / period) + minus_dm[i]

        pdi = 100.0 * (smoothed_pdm / smoothed_tr) if smoothed_tr > 0 else 0.0
        mdi = 100.0 * (smoothed_mdm / smoothed_tr) if smoothed_tr > 0 else 0.0

        denom = pdi + mdi
        dx = 100.0 * (abs(pdi - mdi) / denom) if denom > 0 else 0.0
        dx_list.append(dx)

    if len(dx_list) < period:
        return 0.0, 0.0, 0.0

    # Smooth DX to get ADX
    adx = sum(dx_list[:period]) / period
    for i in range(period, len(dx_list)):
        adx = (adx * (period - 1) + dx_list[i]) / period

    final_pdi = 100.0 * (smoothed_pdm / smoothed_tr) if smoothed_tr > 0 else 0.0
    final_mdi = 100.0 * (smoothed_mdm / smoothed_tr) if smoothed_tr > 0 else 0.0

    return float(round(adx, 2)), float(round(final_pdi, 2)), float(round(final_mdi, 2))


def calculate_ema(series: List[float], period: int) -> float:
    """Exponential Moving Average of series."""
    if not series:
        return 0.0
    if len(series) < period:
        return float(np.mean(series))
    alpha = 2.0 / (period + 1.0)
    ema = float(series[0])
    for val in series[1:]:
        ema = alpha * val + (1.0 - alpha) * ema
    return float(ema)


def calculate_atr(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    period: int = 14
) -> float:
    """Average True Range (Wilder)."""
    n = len(closes)
    if n < 2:
        return 0.0
    tr_vals = [
        max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        for i in range(1, n)
    ]
    if len(tr_vals) < period:
        return float(np.mean(tr_vals)) if tr_vals else 0.0
    atr = sum(tr_vals[:period]) / period
    for tr in tr_vals[period:]:
        atr = (atr * (period - 1) + tr) / period
    return float(atr)


# ==============================================================================
# 3. Microstructure & Order Flow Analytics
# ==============================================================================

def calculate_bollinger_bandwidth_percentile(
    closes: List[float],
    bb_period: int = 20,
    lookback_window: int = 100
) -> Tuple[float, float, float, float]:
    """
    Calculates Bollinger Bands and the historical percentile of current Bandwidth.
    Returns: (bb_upper, bb_mid, bb_lower, bbw_percentile)
    """
    n = len(closes)
    if n < bb_period:
        mid = closes[-1] if closes else 0.0
        return mid, mid, mid, 50.0

    recent = closes[-bb_period:]
    mid = float(np.mean(recent))
    std = float(np.std(recent, ddof=0))
    upper = mid + (2.0 * std)
    lower = mid - (2.0 * std)
    cur_bbw = (upper - lower) / mid if mid > 0 else 0.0

    # Calculate rolling bandwidth history
    history_bbw: List[float] = []
    max_idx = min(n, lookback_window)
    for i in range(n - max_idx, n):
        slice_vals = closes[max(0, i - bb_period + 1):i + 1]
        if len(slice_vals) >= bb_period:
            m = float(np.mean(slice_vals))
            s = float(np.std(slice_vals, ddof=0))
            w = (4.0 * s) / m if m > 0 else 0.0
            history_bbw.append(w)

    if not history_bbw:
        return upper, mid, lower, 50.0

    count_below = sum(1 for v in history_bbw if v < cur_bbw)
    count_equal = sum(1 for v in history_bbw if math.isclose(v, cur_bbw, rel_tol=1e-5))
    percentile = ((count_below + 0.5 * count_equal) / len(history_bbw)) * 100.0
    return float(upper), float(mid), float(lower), float(round(percentile, 2))


def calculate_donchian_channel(
    highs: List[float],
    lows: List[float],
    period: int = 20
) -> Tuple[float, float]:
    """20-period Donchian Channel (Highest High, Lowest Low)."""
    if len(highs) < period:
        h = max(highs) if highs else 0.0
        l = min(lows) if lows else 0.0
        return float(h), float(l)
    return float(max(highs[-period:])), float(min(lows[-period:]))


def calculate_vwap_metrics(
    closes: List[float],
    vwaps: List[float],
    window: int = 20
) -> Tuple[float, float]:
    """Returns current VWAP and price Z-score distance from VWAP."""
    if not vwaps or not closes:
        return 0.0, 0.0
    cur_vwap = vwaps[-1]
    cur_close = closes[-1]
    
    # Calculate rolling distance std
    recent_c = closes[-window:]
    recent_vw = vwaps[-window:]
    diffs = [c - vw for c, vw in zip(recent_c, recent_vw)]
    std_diff = float(np.std(diffs, ddof=1)) if len(diffs) > 1 else 1e-4
    if std_diff <= 1e-6:
        std_diff = 1e-4

    zscore = (cur_close - cur_vwap) / std_diff
    return float(cur_vwap), float(round(zscore, 3))


# ==============================================================================
# 4. Master Feature Store Generator
# ==============================================================================

class FeatureStore:
    """
    Computes a complete, strictly causal feature matrix for any bar sequence.
    Guarantees no lookahead bias by shifting feature vectors by 1 bar.
    """

    @staticmethod
    def extract_features_at_index(
        bars: List[Bar],
        idx: int,
        is_crypto: bool = True
    ) -> BarFeatures:
        """
        Extract features strictly up to index `idx` (inclusive).
        To generate signal for bar `t`, call with `idx = t - 1` (Lag-1 Rule).
        """
        sub_bars = bars[:idx + 1]
        target_bar = sub_bars[-1]

        opens = [b.open for b in sub_bars]
        highs = [b.high for b in sub_bars]
        lows = [b.low for b in sub_bars]
        closes = [b.close for b in sub_bars]
        vwaps = [b.vwap for b in sub_bars]
        volumes = [b.volume for b in sub_bars]
        taker_buys = [b.taker_buy_vol for b in sub_bars]

        ann_factor = (365.0 * 24.0) if is_crypto else 252.0

        # Volatilities
        p_vol = calculate_parkinson_volatility(highs, lows, window=20, annualization_factor=ann_factor)
        yz_vol = calculate_yang_zhang_volatility(opens, highs, lows, closes, window=20, annualization_factor=ann_factor)
        r_vol = calculate_realized_volatility(closes, window=20, annualization_factor=ann_factor)

        # ADX & Directional
        adx, pdi, mdi = calculate_adx_system(highs, lows, closes, period=14)
        ema_fast = calculate_ema(closes, period=9)
        ema_slow = calculate_ema(closes, period=21)

        # Higher-Timeframe Trend Bias (Proxy via 50 and 200 EMA)
        ema_50 = calculate_ema(closes, period=50)
        ema_200 = calculate_ema(closes, period=min(len(closes), 200))
        if ema_50 > ema_200 and closes[-1] > ema_50:
            htf_bias = 1
        elif ema_50 < ema_200 and closes[-1] < ema_50:
            htf_bias = -1
        else:
            htf_bias = 0

        # Bollinger Bands & Bandwidth Percentile
        upper, mid, lower, bbw_pct = calculate_bollinger_bandwidth_percentile(closes, bb_period=20, lookback_window=100)
        donch_h, donch_l = calculate_donchian_channel(highs, lows, period=20)
        atr_val = calculate_atr(highs, lows, closes, period=14)

        # VWAP & Microstructure
        vwap_val, vwap_z = calculate_vwap_metrics(closes, vwaps, window=20)

        # Order Flow Imbalance / Volume Delta
        cur_vol = volumes[-1]
        cur_taker_buy = taker_buys[-1]
        taker_sell = max(0.0, cur_vol - cur_taker_buy)
        vol_delta = cur_taker_buy - taker_sell
        vol_delta_ratio = (vol_delta / cur_vol) if cur_vol > 0 else 0.0

        # Cumulative Volume Delta (last 20 bars)
        recent_buys = sum(taker_buys[-20:])
        recent_vols = sum(volumes[-20:])
        recent_sells = max(0.0, recent_vols - recent_buys)
        cvd_val = recent_buys - recent_sells

        # Liquidity Hour Check: Exclude rollover 00:00-02:00 UTC if volume collapses
        # (Crypto runs 24/7, but low liquidity hours often produce false breakouts)
        is_liquid = True
        try:
            bar_hour = int(target_bar.timestamp[11:13])
            # If volume is in the bottom 15% of recent bars during 00-02 UTC
            recent_avg_vol = float(np.mean(volumes[-50:])) if len(volumes) >= 50 else cur_vol
            if bar_hour in (0, 1) and cur_vol < (0.35 * recent_avg_vol):
                is_liquid = False
        except Exception:
            is_liquid = True

        return BarFeatures(
            timestamp=target_bar.timestamp,
            close=target_bar.close,
            parkinson_vol=round(p_vol, 4),
            yang_zhang_vol=round(yz_vol, 4),
            realized_vol=round(r_vol, 4),
            adx=adx,
            plus_di=pdi,
            minus_di=mdi,
            ema_fast=round(ema_fast, 2),
            ema_slow=round(ema_slow, 2),
            htf_bias=htf_bias,
            bb_upper=round(upper, 2),
            bb_lower=round(lower, 2),
            bb_mid=round(mid, 2),
            bbw_percentile=bbw_pct,
            donchian_high=round(donch_h, 2),
            donchian_low=round(donch_l, 2),
            vwap=round(vwap_val, 2),
            vwap_zscore=vwap_z,
            volume_delta=round(vol_delta, 4),
            volume_delta_ratio=round(vol_delta_ratio, 4),
            cvd=round(cvd_val, 4),
            atr=round(atr_val, 2),
            is_liquid_hour=is_liquid
        )

    @classmethod
    def generate_causal_feature_matrix(
        cls,
        bars: List[Bar],
        min_lookback: int = 50,
        is_crypto: bool = True
    ) -> List[Tuple[Bar, BarFeatures]]:
        """
        Generates paired list of (bar_t, features_t_minus_1).
        This guarantees:
        AT BAR t (which opens at bar_t.open):
        THE ONLY DATA AVAILABLE IS features_t_minus_1!
        """
        results: List[Tuple[Bar, BarFeatures]] = []
        n = len(bars)
        if n < min_lookback + 1:
            return results

        for t in range(min_lookback, n):
            bar_t = bars[t]
            # Lag-1 computation: features strictly up to t - 1
            feat_lag1 = cls.extract_features_at_index(bars, t - 1, is_crypto=is_crypto)
            results.append((bar_t, feat_lag1))

        return results
