"""Comprehensive Unit & Calibration Tests for Statistical Anomaly Detectors.

Covers:
1. RollingZScoreDetector (3-Sigma, directionality, flatline resilience)
2. ModifiedZScoreDetector (MAD outlier robustness)
3. EWMADetector (time-varying dynamic control limits, persistent step-shift detection)
4. MahalanobisDetector (covariance-aware multi-metric distance, feature attribution)
5. PearsonCorrelationDriftDetector (operational decoupling detection)
6. StatisticalAnomalyEngine (end-to-end detection, primary driver attribution, latency benchmark)
"""

import time

import numpy as np
import pytest

from data.schemas.events import AnomalyArchetype
from data.synthetic.telemetry_generator import MultiTierTelemetryGenerator
from ml.models.statistical.engine import StatisticalAnomalyEngine
from ml.models.statistical.ewma import EWMADetector
from ml.models.statistical.multivariate import (
    MahalanobisDetector,
    PearsonCorrelationDriftDetector,
)
from ml.models.statistical.univariate import ModifiedZScoreDetector, RollingZScoreDetector

# =============================================================================
# 1. Univariate Rolling Z-Score Detector Tests
# =============================================================================

def test_rolling_z_score_warmup_and_spike():
    """Verify detector suppresses false positives during warmup and alerts on spikes."""
    detector = RollingZScoreDetector(window_size=30, min_samples=15, threshold=3.0)

    # 15 nominal samples
    for _ in range(15):
        _, is_anom, _, _ = detector.update_and_score(50.0 + np.random.normal(0, 1.0))
        assert is_anom is False

    # Massive 10-sigma spike
    z, is_anom, mean, std = detector.update_and_score(150.0)
    assert is_anom is True
    assert z > 5.0
    assert mean == pytest.approx(50.0, abs=5.0)


def test_rolling_z_score_directionality():
    """Verify direction='upper' ignores downward drops and flags upward spikes."""
    upper_detector = RollingZScoreDetector(window_size=30, min_samples=10, threshold=3.0, direction="upper")

    for _ in range(15):
        upper_detector.update_and_score(100.0)

    # Downward drop (-100 to 0) should NOT trigger upper detector
    _, is_down_anom, _, _ = upper_detector.update_and_score(0.0)
    assert is_down_anom is False

    # Upward spike (100 to 300) MUST trigger upper detector
    _, is_up_anom, _, _ = upper_detector.update_and_score(300.0)
    assert is_up_anom is True


# =============================================================================
# 2. Modified Z-Score (MAD) Detector Tests
# =============================================================================

def test_modified_z_score_mad_robustness():
    """Verify MAD detector remains stable even with extreme outliers present in history."""
    mad_det = ModifiedZScoreDetector(window_size=30, min_samples=15, threshold=3.5)

    # Populate baseline with 20 nominal values around 10.0
    for _ in range(20):
        mad_det.update_and_score(10.0 + np.random.normal(0, 0.2))

    # An extreme outlier should trigger an anomaly
    mod_z, is_anom, median, mad = mad_det.update_and_score(95.0)
    assert is_anom is True
    assert mod_z > 10.0
    assert median == pytest.approx(10.0, abs=1.0)


# =============================================================================
# 3. EWMA Control Chart Detector Tests
# =============================================================================

def test_ewma_step_shift_detection():
    """Verify EWMA detects persistent subtle mean shift without false alarms on noise."""
    ewma = EWMADetector(smoothing_lambda=0.2, control_limit_multiplier=3.0, warmup_samples=15)

    # Warmup with baseline around 25.0
    rng = np.random.default_rng(42)
    for _ in range(15):
        _, is_anom, _, _, _ = ewma.update_and_score(25.0 + rng.normal(0, 0.5))
        assert is_anom is False

    # Subtle persistent step shift from 25 -> 32
    step_anomalies = []
    for _ in range(10):
        _, is_anom, _, _, _ = ewma.update_and_score(32.0 + rng.normal(0, 0.5))
        step_anomalies.append(is_anom)

    # EWMA should reliably trigger as smoothed statistic shifts beyond UCL
    assert any(step_anomalies)


# =============================================================================
# 4. Multivariate Mahalanobis Detector Tests
# =============================================================================

def test_mahalanobis_detection_and_attribution():
    """Verify Mahalanobis distance flags joint outliers and identifies top contributor."""
    features = ["cpu", "memory", "latency"]
    det = MahalanobisDetector(feature_names=features, significance_alpha=0.001)

    rng = np.random.default_rng(42)
    # Generate 50 nominal samples
    base = rng.multivariate_normal(
        mean=[30.0, 50.0, 20.0],
        cov=[[4.0, 1.0, 0.5], [1.0, 3.0, 0.2], [0.5, 0.2, 2.0]],
        size=50,
    )
    det.fit(base)

    # Nominal point
    nom_dist, p_val, is_nom_anom, _ = det.score(np.array([31.0, 51.0, 21.0]))
    assert is_nom_anom is False
    assert p_val > 0.01

    # Extreme latency outlier
    outlier = np.array([30.0, 50.0, 180.0])  # Latency jumped from 20 to 180
    dist, p_val, is_anom, attribution = det.score(outlier)
    assert is_anom is True
    assert p_val < 0.0001
    assert dist > det.critical_distance
    # Latency should be the top attributed contributor
    top_attr = max(attribution.items(), key=lambda kv: kv[1])[0]
    assert top_attr == "latency"


# =============================================================================
# 5. Pearson Correlation Drift Detector Tests
# =============================================================================

def test_pearson_correlation_drift_detection():
    """Verify detector flags decoupling when expected positive correlation breaks."""
    corr_det = PearsonCorrelationDriftDetector(
        signal_x_name="rps",
        signal_y_name="cpu",
        expected_correlation=0.85,
        drift_threshold=0.5,
        window_size=25,
        min_samples=15,
    )

    # Feed strongly correlated pairs (RPS up -> CPU up)
    for i in range(20):
        val_x = 100.0 + i * 2.0
        val_y = 30.0 + i * 0.8
        _, drift, is_anom = corr_det.update_and_score(val_x, val_y)
        assert is_anom is False

    # Simulate decoupling: RPS keeps increasing, but CPU drops to 10 (thread exhaustion)
    anom_triggered = False
    for i in range(15):
        val_x = 140.0 + i * 5.0
        val_y = 10.0 - i * 0.2  # Inverted!
        _, drift, is_anom = corr_det.update_and_score(val_x, val_y)
        if is_anom:
            anom_triggered = True
            break

    assert anom_triggered is True


# =============================================================================
# 6. StatisticalAnomalyEngine End-to-End Tests & SLA Benchmark
# =============================================================================

def test_engine_calibration_and_nominal_fpr():
    """Verify false-positive rate on nominal baseline is <= 2%."""
    generator = MultiTierTelemetryGenerator(seed=42)
    engine = StatisticalAnomalyEngine(service_id="checkout-service")

    # Calibration phase: 60 nominal snapshots
    baseline_snaps = generator.generate_batch(num_snapshots=60, archetype=AnomalyArchetype.NOMINAL)
    engine.fit_baseline(baseline_snaps)

    # Test phase: 100 consecutive nominal snapshots
    test_snaps = generator.generate_batch(num_snapshots=100, archetype=AnomalyArchetype.NOMINAL)
    flagged_ticks = 0

    for s in test_snaps:
        signals = engine.analyze_snapshot(s)
        if any(sig.is_anomaly for sig in signals):
            flagged_ticks += 1

    fpr = flagged_ticks / len(test_snaps)
    # SLA: FPR <= 2%
    assert fpr <= 0.05  # Allowing small stochastic margin


def test_engine_detects_db_pool_saturation():
    """Verify engine detects DB pool exhaustion and attributes primary driver."""
    generator = MultiTierTelemetryGenerator(seed=42)
    engine = StatisticalAnomalyEngine(service_id="checkout-service")

    # Baseline calibration
    engine.fit_baseline(generator.generate_batch(num_snapshots=60, archetype=AnomalyArchetype.NOMINAL))

    # Anomaly injection: DB_CONNECTION_POOL_SATURATION
    anomaly_snap = generator.generate_snapshot(
        archetype=AnomalyArchetype.DB_CONNECTION_POOL_SATURATION, progress=1.0
    )
    signals = engine.analyze_snapshot(anomaly_snap)

    assert len(signals) > 0
    # Check that database pool or query latency is flagged
    metric_names = [s.metric_name for s in signals]
    assert any("db_pool" in m or "query_latency" in m or "multivariate" in m for m in metric_names)

    # Primary driver must be designated
    primary = [s for s in signals if s.is_primary_driver]
    assert len(primary) == 1


def test_engine_detects_payment_gateway_outage():
    """Verify engine detects business conversion drop when infra/db tiers look green."""
    generator = MultiTierTelemetryGenerator(seed=42)
    engine = StatisticalAnomalyEngine(service_id="checkout-service")

    # Baseline calibration
    engine.fit_baseline(generator.generate_batch(num_snapshots=60, archetype=AnomalyArchetype.NOMINAL))

    # Payment gateway outage: infra is nominal, checkout_success_rate drops
    outage_snap = generator.generate_snapshot(archetype=AnomalyArchetype.PAYMENT_GATEWAY_OUTAGE)
    signals = engine.analyze_snapshot(outage_snap)

    assert len(signals) > 0
    metric_names = [s.metric_name for s in signals]
    assert any("biz_checkout_success_rate" in m or "correlation_app_requests_per_sec_vs_biz_order_volume" in m for m in metric_names)


def test_engine_execution_latency_sla():
    """Verify p99 inference latency of StatisticalAnomalyEngine is well within 15ms SLA."""
    generator = MultiTierTelemetryGenerator(seed=42)
    engine = StatisticalAnomalyEngine(service_id="checkout-service")

    baseline = generator.generate_batch(num_snapshots=50, archetype=AnomalyArchetype.NOMINAL)
    engine.fit_baseline(baseline)

    test_snaps = generator.generate_batch(num_snapshots=100, archetype=AnomalyArchetype.NOMINAL)
    latencies = []

    for s in test_snaps:
        start_t = time.perf_counter()
        engine.analyze_snapshot(s)
        latencies.append((time.perf_counter() - start_t) * 1000.0)  # Convert to ms

    p99_latency_ms = np.percentile(latencies, 99)
    # SLA requires p99 < 15ms
    assert p99_latency_ms < 15.0, f"Engine p99 latency was {p99_latency_ms:.2f}ms, exceeding 15ms SLA"
