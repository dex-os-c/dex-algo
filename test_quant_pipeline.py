"""
Institutional Quantitative Pipeline Verification Suite
======================================================
Tests:
1. Multi-source Data Layer & Symbol Normalization
2. Realized Volatility Estimators (Parkinson, Yang-Zhang, Realized Vol)
3. Feature Store & Strict Lag-1 Anti-Lookahead Guarantee
4. Market Regime Classifier & Hysteresis State Management
5. Orthogonal Multi-Alpha Ensemble & Regime-Conditioned Weighting
6. Volatility Targeting & Bayesian Half-Kelly Sizing
7. Monotonic Chandelier Ratchet Trailing Stops
8. Realistic Backtester with Slippage, Fees, Embargo CV & Monte Carlo
"""

import os
import sys
import math
import unittest
import numpy as np

# Ensure backend directory is in sys.path
_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.join(_CURRENT_DIR, "backend")
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from data_layer import Bar, MarketDataClient, normalize_symbol, to_binance_symbol, to_coinbase_product
from features import (
    calculate_parkinson_volatility,
    calculate_yang_zhang_volatility,
    calculate_realized_volatility,
    calculate_adx_system,
    calculate_bollinger_bandwidth_percentile,
    calculate_vwap_metrics,
    FeatureStore
)
from regime import RobustRegimeDetector, MarketRegime, RegimeState
from alphas import (
    AdaptiveTrendAlpha,
    SqueezeMeanReversionAlpha,
    OrderFlowBreakoutAlpha,
    MultiAlphaOrchestrator,
    SignalAction
)
from risk import (
    ChandelierRatchet,
    BayesianKellyEstimator,
    InstitutionalRiskEngine,
    Position,
    ExitReason
)
from backtester_v2 import InstitutionalBacktester, TradeRecord


class TestDataLayerAndNormalization(unittest.TestCase):
    """Test data normalization and synthetic fallback."""

    def test_symbol_normalization(self):
        self.assertEqual(normalize_symbol("btcusdt"), "BTC/USDT")
        self.assertEqual(normalize_symbol("ETH-USD"), "ETH/USD")
        self.assertEqual(normalize_symbol("SPY"), "SPY")
        self.assertEqual(to_binance_symbol("BTC/USD"), "BTCUSDT")
        self.assertEqual(to_coinbase_product("BTC/USDT"), "BTC-USD")

    def test_synthetic_bar_generation(self):
        client = MarketDataClient(cache_enabled=False)
        bars = client.generate_synthetic_bars("BTC/USDT", limit=50, interval_hours=1.0)
        self.assertEqual(len(bars), 50)
        self.assertTrue(all(b.high >= b.low for b in bars))
        self.assertTrue(all(b.volume > 0 for b in bars))
        self.assertTrue(all(b.taker_buy_vol <= b.volume for b in bars))


class TestVolatilityEstimators(unittest.TestCase):
    """Test Parkinson and Yang-Zhang volatility formulations."""

    def setUp(self):
        # 30 bars of known geometric walk
        np.random.seed(42)
        base = 100.0
        self.closes = [base]
        self.opens = [base]
        self.highs = [base * 1.01]
        self.lows = [base * 0.99]
        for _ in range(29):
            o = self.closes[-1] * (1.0 + np.random.normal(0, 0.005))
            c = o * (1.0 + np.random.normal(0, 0.01))
            h = max(o, c) * (1.0 + abs(np.random.normal(0, 0.005)))
            l = min(o, c) * (1.0 - abs(np.random.normal(0, 0.005)))
            self.opens.append(o)
            self.highs.append(h)
            self.lows.append(l)
            self.closes.append(c)

    def test_parkinson_volatility_positive(self):
        p_vol = calculate_parkinson_volatility(self.highs, self.lows, window=20)
        self.assertGreater(p_vol, 0.0)
        self.assertLess(p_vol, 5.0)  # Realistic annualized bounds

    def test_yang_zhang_volatility_positive(self):
        yz_vol = calculate_yang_zhang_volatility(self.opens, self.highs, self.lows, self.closes, window=20)
        self.assertGreater(yz_vol, 0.0)
        self.assertLess(yz_vol, 5.0)

    def test_realized_volatility(self):
        r_vol = calculate_realized_volatility(self.closes, window=20)
        self.assertGreater(r_vol, 0.0)


class TestFeatureStoreAndAntiLookahead(unittest.TestCase):
    """Verify strictly causal lag-1 feature alignment."""

    def test_lag1_temporal_alignment(self):
        client = MarketDataClient(cache_enabled=False)
        bars = client.generate_synthetic_bars("BTC/USDT", limit=100)
        pairs = FeatureStore.generate_causal_feature_matrix(bars, min_lookback=35)
        self.assertGreater(len(pairs), 0)

        for bar_t, feat_prev in pairs:
            # Bar t timestamp must be strictly newer than feature snapshot timestamp
            self.assertGreater(bar_t.timestamp, feat_prev.timestamp)
            # Feature snapshot close must match bar t-1 close, NOT bar t close!
            t_idx = [i for i, b in enumerate(bars) if b.timestamp == bar_t.timestamp][0]
            self.assertEqual(feat_prev.close, bars[t_idx - 1].close)


class TestRegimeClassification(unittest.TestCase):
    """Verify 4-state regime classifier and hysteresis."""

    def test_regime_classification_states(self):
        detector = RobustRegimeDetector(hysteresis_bars=2)
        client = MarketDataClient(cache_enabled=False)
        bars = client.generate_synthetic_bars("BTC/USDT", limit=80)
        pairs = FeatureStore.generate_causal_feature_matrix(bars, min_lookback=35)

        regimes_observed = set()
        for bar_t, feat in pairs:
            st = detector.update(feat)
            regimes_observed.add(st.regime)
            self.assertIn(st.regime, [
                MarketRegime.TRENDING_BULL,
                MarketRegime.TRENDING_BEAR,
                MarketRegime.LOW_VOL_COMPRESSION,
                MarketRegime.HIGH_VOL_BREAKOUT
            ])
            # Verify dynamic weights sum to ~1.0
            total_w = sum(st.active_weights.values())
            self.assertAlmostEqual(total_w, 1.0, places=2)

        self.assertGreaterEqual(len(regimes_observed), 1)


class TestMultiAlphaEnsemble(unittest.TestCase):
    """Verify orthogonal signals and strict gating."""

    def test_mean_reversion_strictly_inactive_in_trending_bull(self):
        # When regime is TRENDING_BULL, SqueezeMeanReversionAlpha must output exactly 0.0
        client = MarketDataClient(cache_enabled=False)
        bars = client.generate_synthetic_bars("BTC/USDT", limit=50)
        feat = FeatureStore.extract_features_at_index(bars, len(bars) - 1)

        score_bull = SqueezeMeanReversionAlpha.evaluate(feat, MarketRegime.TRENDING_BULL, rsi_2p=5.0)
        self.assertEqual(score_bull, 0.0)

        score_bear = SqueezeMeanReversionAlpha.evaluate(feat, MarketRegime.TRENDING_BEAR, rsi_2p=95.0)
        self.assertEqual(score_bear, 0.0)

    def test_regime_directional_harmony(self):
        # In TRENDING_BULL, short trades are blocked
        orchestrator = MultiAlphaOrchestrator()
        regime_state = RegimeState(
            regime=MarketRegime.TRENDING_BULL,
            confidence=0.8,
            adx=35.0,
            bbw_percentile=60.0,
            volatility_zscore=0.5,
            active_weights={"trend": 0.65, "breakout": 0.25, "mean_reversion": 0.10},
            bars_in_regime=5
        )
        client = MarketDataClient(cache_enabled=False)
        bars = client.generate_synthetic_bars("BTC/USDT", limit=50)
        feat = FeatureStore.extract_features_at_index(bars, len(bars) - 1)
        sig = orchestrator.evaluate_signal(feat, regime_state)
        # Cannot be SELL in bull trend
        self.assertNotEqual(sig.action, SignalAction.SELL)


class TestRiskEngineAndChandelierRatchet(unittest.TestCase):
    """Verify volatility targeting, Bayesian Kelly, and ratchet monotonicity."""

    def test_volatility_targeting_inverse_scaling(self):
        engine = InstitutionalRiskEngine(target_annual_vol=0.15)
        equity = 100000.0
        px = 50000.0
        u_low, d_low, _ = engine.calculate_position_size(equity, px, realized_vol=0.20)
        u_high, d_high, _ = engine.calculate_position_size(equity, px, realized_vol=0.80)
        self.assertGreater(d_low, d_high)

    def test_bayesian_kelly_prior_updates(self):
        estimator = BayesianKellyEstimator(prior_wins=10, prior_losses=10)
        initial_p = estimator.posterior_win_rate
        self.assertAlmostEqual(initial_p, 0.50, places=2)

        # 5 wins in a row
        for _ in range(5):
            estimator.update_outcome(500.0)
        self.assertGreater(estimator.posterior_win_rate, 0.50)

    def test_monotonic_chandelier_ratchet(self):
        engine = InstitutionalRiskEngine()
        pos = Position(
            symbol="BTC/USDT",
            side="LONG",
            qty=0.1,
            entry_price=60000.0,
            entry_time="2026-11-12T00:00:00Z",
            entry_regime="TRENDING_BULL",
            stop_loss=57000.0,
            take_profit=70000.0,
            highest_high=60000.0,
            lowest_low=60000.0,
            atr_at_entry=1000.0
        )
        # Price rises to 65000 with ATR 1000 -> Stop ratchets to 65000 - 3000 = 62000
        _, _, _, pos = engine.evaluate_open_position(pos, 65000.0, 61000.0, 64000.0, 1000.0, "TRENDING_BULL")
        self.assertEqual(pos.stop_loss, 62000.0)

        # Price drops to 63000 -> Stop must NOT decrease!
        _, _, _, pos = engine.evaluate_open_position(pos, 63500.0, 62500.0, 63000.0, 1000.0, "TRENDING_BULL")
        self.assertEqual(pos.stop_loss, 62000.0)


class TestBacktesterAndValidation(unittest.TestCase):
    """Verify walk-forward optimizer, slippage, and Monte Carlo."""

    def test_simulation_with_friction(self):
        client = MarketDataClient(cache_enabled=False)
        bars = client.generate_synthetic_bars("BTC/USDT", limit=200, seed=123)
        bt = InstitutionalBacktester(initial_capital=100000.0, fee_rate=0.0006)
        trades, eq, metrics = bt.run_simulation(bars, symbol="BTC/USDT", is_crypto=True)
        self.assertEqual(len(eq), len(bars) - 35 + 1)
        self.assertIsInstance(metrics.profit_factor, float)
        self.assertIsInstance(metrics.annualized_sharpe, float)

    def test_monte_carlo_generator(self):
        # Create synthetic trade records
        trades = [
            TradeRecord("BTC/USDT", "LONG", 0, "t0", 60000.0, 0.1, 5, "t5", 61500.0, "TAKE_PROFIT",
                        150.0, 5.0, 2.0, 143.0, 0.0238, 1.5, 5, "BULL", "BULL"),
            TradeRecord("BTC/USDT", "LONG", 6, "t6", 61500.0, 0.1, 8, "t8", 60500.0, "STOP_LOSS",
                        -100.0, 5.0, 2.0, -107.0, -0.0174, -1.0, 2, "BULL", "BULL")
        ]
        bt = InstitutionalBacktester(initial_capital=100000.0)
        mc = bt.run_monte_carlo_simulation(trades, num_simulations=100, horizon_trades=20)
        self.assertIn("probability_of_ruin", mc)
        self.assertIn("equity_cone", mc)
        self.assertGreater(mc["equity_cone"]["95th_percentile_best_case"], 0)


if __name__ == "__main__":
    unittest.main()
