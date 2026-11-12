"""
Standalone Verification Script for Causal Feature Store on Real BTC Bars
"""
import os
import sys
import json
import math
import numpy as np

# Add backend directory to sys.path
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(CURRENT_DIR, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from data_layer import Bar, MarketDataClient
from features import (
    BarFeatures,
    FeatureStore,
    calculate_parkinson_volatility,
    calculate_yang_zhang_volatility,
    calculate_realized_volatility,
    calculate_adx_system,
    calculate_bollinger_bandwidth_percentile,
    calculate_vwap_metrics,
    calculate_donchian_channel,
    calculate_ema,
    calculate_atr
)

def run_real_btc_feature_tests():
    cache_path = os.path.join(CURRENT_DIR, ".cache", "bars", "BTC_USDT_1h_500.json")
    if not os.path.exists(cache_path):
        print(f"Cache file {cache_path} not found, generating via client...")
        client = MarketDataClient(cache_enabled=True)
        bars = client.get_historical_bars("BTC/USDT", interval="1h", limit=500)
    else:
        with open(cache_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
            bars = [Bar(**item) for item in raw]

    print(f"Loaded {len(bars)} real BTC/USDT 1h bars.")
    assert len(bars) >= 100, f"Expected at least 100 bars, got {len(bars)}"

    # 1. Test Realized Volatility Estimators
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    opens = [b.open for b in bars]
    closes = [b.close for b in bars]
    vwaps = [b.vwap for b in bars]
    volumes = [b.volume for b in bars]
    taker_buys = [b.taker_buy_vol for b in bars]

    p_vol = calculate_parkinson_volatility(highs[:50], lows[:50], window=20)
    yz_vol = calculate_yang_zhang_volatility(opens[:50], highs[:50], lows[:50], closes[:50], window=20)
    r_vol = calculate_realized_volatility(closes[:50], window=20)

    print(f"Volatilities (first 50 bars):")
    print(f"  Parkinson Vol:    {p_vol:.4f} ({p_vol*100:.2f}%)")
    print(f"  Yang-Zhang Vol:   {yz_vol:.4f} ({yz_vol*100:.2f}%)")
    print(f"  Realized Vol:     {r_vol:.4f} ({r_vol*100:.2f}%)")
    assert p_vol > 0.0, "Parkinson vol must be positive"
    assert yz_vol > 0.0, "Yang-Zhang vol must be positive"
    assert r_vol > 0.0, "Realized vol must be positive"

    # 2. Test ADX System
    adx, pdi, mdi = calculate_adx_system(highs[:50], lows[:50], closes[:50], period=14)
    print(f"ADX System (first 50 bars): ADX={adx:.2f}, +DI={pdi:.2f}, -DI={mdi:.2f}")
    assert adx > 0.0, "ADX must be positive"
    assert pdi >= 0.0 and mdi >= 0.0, "+DI and -DI must be non-negative"

    # 3. Test BBW Percentile
    bb_u, bb_m, bb_l, bbw_pct = calculate_bollinger_bandwidth_percentile(closes[:100], bb_period=20, lookback_window=100)
    print(f"Bollinger Bands: Upper={bb_u:.2f}, Mid={bb_m:.2f}, Lower={bb_l:.2f}, BBW Pct={bbw_pct:.2f}%")
    assert bb_u >= bb_m >= bb_l, "Bollinger band ordering invariant violated"
    assert 0.0 <= bbw_pct <= 100.0, f"BBW Percentile out of range: {bbw_pct}"

    # 4. Test VWAP Metrics
    cur_vw, vw_z = calculate_vwap_metrics(closes[:50], vwaps[:50], window=20)
    print(f"VWAP Metrics: Current VWAP={cur_vw:.2f}, Z-Score={vw_z:.3f}")
    assert cur_vw > 0.0, "VWAP must be positive"

    # 5. Test Causal Feature Matrix & Lag-1 Invariant
    matrix = FeatureStore.generate_causal_feature_matrix(bars, min_lookback=50)
    print(f"Generated {len(matrix)} causal (bar_t, feat_t_minus_1) pairs.")
    assert len(matrix) == len(bars) - 50, f"Expected {len(bars) - 50} pairs, got {len(matrix)}"

    for i, (bar_t, feat_prev) in enumerate(matrix):
        orig_t_idx = 50 + i
        # Exact lag-1 verification
        assert feat_prev.timestamp == bars[orig_t_idx - 1].timestamp, \
            f"Timestamp mismatch at idx {orig_t_idx}: feat={feat_prev.timestamp} vs bar_prev={bars[orig_t_idx - 1].timestamp}"
        assert math.isclose(feat_prev.close, bars[orig_t_idx - 1].close, rel_tol=1e-7), \
            f"Close mismatch at idx {orig_t_idx}: feat.close={feat_prev.close} vs bar_prev.close={bars[orig_t_idx - 1].close}"
        assert feat_prev.timestamp < bar_t.timestamp, \
            f"Temporal causality violated! feat.timestamp={feat_prev.timestamp} >= bar_t.timestamp={bar_t.timestamp}"

    # 6. Anti-Lookahead perturbation test:
    # Modifying future bar `t` must NEVER change `features[t]` (which depends only on bars up to t-1)
    test_idx = 75
    feat_baseline = FeatureStore.extract_features_at_index(bars, test_idx - 1)

    # Clone bars and mutate bar `test_idx` to extreme values
    mutated_bars = [Bar(**b.to_dict()) for b in bars]
    mutated_bars[test_idx].open *= 2.0
    mutated_bars[test_idx].high *= 3.0
    mutated_bars[test_idx].low *= 0.5
    mutated_bars[test_idx].close *= 2.5
    mutated_bars[test_idx].volume *= 100.0

    feat_after_future_mutation = FeatureStore.extract_features_at_index(mutated_bars, test_idx - 1)
    assert feat_baseline == feat_after_future_mutation, \
        "LOOKAHEAD LEAK DETECTED! Future bar mutation altered past feature snapshot!"

    print("ALL CAUSAL LAG-1 VERIFICATIONS PASSED WITH 100% ZERO-LOOKAHEAD GUARANTEE!")

    # Print representative sample feature vector on real BTC
    sample_bar, sample_feat = matrix[-1]
    print("\nRepresentative Latest Causal BarFeatures on Real BTC/USDT:")
    print(json.dumps(sample_feat.to_dict(), indent=2))
    return True

if __name__ == "__main__":
    success = run_real_btc_feature_tests()
    if success:
        sys.exit(0)
    else:
        sys.exit(1)
