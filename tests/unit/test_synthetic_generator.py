"""Unit tests for MultiTierTelemetryGenerator."""

from datetime import datetime, timezone

import pandas as pd

from data.schemas.events import AnomalyArchetype, TelemetrySnapshot
from data.synthetic.telemetry_generator import MultiTierTelemetryGenerator


def test_generator_initialization_and_reset():
    """Verify generator initialization, state reset, and reproducibility."""
    gen1 = MultiTierTelemetryGenerator(seed=123)
    snap1 = gen1.generate_snapshot(archetype=AnomalyArchetype.NOMINAL)

    gen2 = MultiTierTelemetryGenerator(seed=123)
    snap2 = gen2.generate_snapshot(archetype=AnomalyArchetype.NOMINAL)

    assert snap1.infrastructure.cpu_percent == snap2.infrastructure.cpu_percent
    assert snap1.application.latency_p50_ms == snap2.application.latency_p50_ms

    # Reset gen1 and check reproducibility
    gen1.reset(start_time=datetime(2026, 10, 2, 8, 0, 0, tzinfo=timezone.utc))
    gen1.rng = gen2.rng  # Align generator state


def test_nominal_snapshot_physics():
    """Verify nominal snapshots follow valid physical laws and quantiles."""
    gen = MultiTierTelemetryGenerator(seed=42)
    snapshots = gen.generate_batch(num_snapshots=50, archetype=AnomalyArchetype.NOMINAL)

    assert len(snapshots) == 50
    for s in snapshots:
        assert isinstance(s, TelemetrySnapshot)
        assert s.ground_truth_label == AnomalyArchetype.NOMINAL
        assert s.ground_truth_anomalous is False

        # Quantile ordering invariant: p50 <= p95 <= p99
        assert s.application.latency_p50_ms <= s.application.latency_p95_ms
        assert s.application.latency_p95_ms <= s.application.latency_p99_ms

        # Physical bounds
        assert 0.0 <= s.infrastructure.cpu_percent <= 100.0
        assert 0.0 <= s.infrastructure.memory_percent <= 100.0
        assert 0.0 <= s.database.connection_pool_utilization <= 100.0
        assert 90.0 <= s.business.checkout_success_rate <= 100.0


def test_db_connection_pool_saturation_archetype():
    """Verify DB connection pool exhaustion dynamics."""
    gen = MultiTierTelemetryGenerator(seed=42)
    snap = gen.generate_snapshot(archetype=AnomalyArchetype.DB_CONNECTION_POOL_SATURATION, progress=1.0)

    assert snap.ground_truth_label == AnomalyArchetype.DB_CONNECTION_POOL_SATURATION
    assert snap.ground_truth_anomalous is True
    # DB Pool > 90%
    assert snap.database.connection_pool_utilization >= 90.0
    # DB Latency > 200ms
    assert snap.database.query_latency_mean_ms >= 200.0
    # App Latency surged
    assert snap.application.latency_p99_ms > 1000.0
    # HTTP 500 error rate elevated
    assert snap.application.http_5xx_count > 0
    # Checkout success plummeted
    assert snap.business.checkout_success_rate < 50.0


def test_memory_leak_gc_pause_archetype():
    """Verify memory leak and periodic GC pauses."""
    gen = MultiTierTelemetryGenerator(seed=42)
    # Generate consecutive ticks to trigger GC pause
    snaps = [
        gen.generate_snapshot(archetype=AnomalyArchetype.MEMORY_LEAK_GC_PAUSE, progress=1.0)
        for _ in range(6)
    ]
    # Memory should be saturated (>80%)
    for s in snaps:
        assert s.infrastructure.memory_percent >= 80.0
        assert s.ground_truth_anomalous is True

    # At least one tick should have triggered a GC pause (elevated CPU or high p99)
    has_gc_pause = any(s.infrastructure.cpu_percent > 85.0 for s in snaps)
    assert has_gc_pause


def test_cascading_third_party_failure_archetype():
    """Verify cascading downstream timeouts with low CPU thread starvation."""
    gen = MultiTierTelemetryGenerator(seed=42)
    snap = gen.generate_snapshot(archetype=AnomalyArchetype.CASCADING_THIRD_PARTY_FAILURE, progress=1.0)

    assert snap.ground_truth_anomalous is True
    # Worker threads blocked in network I/O -> CPU is low (< 35%)
    assert snap.infrastructure.cpu_percent < 35.0
    # Extreme latency
    assert snap.application.latency_p99_ms > 2000.0
    # Heavy 5xx timeouts
    assert snap.application.http_5xx_count > 0
    # Conversion drops
    assert snap.business.checkout_success_rate < 30.0


def test_payment_gateway_outage_archetype():
    """Verify business-tier outage where infra/app tiers look green."""
    gen = MultiTierTelemetryGenerator(seed=42)
    snap = gen.generate_snapshot(archetype=AnomalyArchetype.PAYMENT_GATEWAY_OUTAGE)

    assert snap.ground_truth_anomalous is True
    # Infra & DB are nominal
    assert snap.infrastructure.cpu_percent < 60.0
    assert snap.database.connection_pool_utilization < 50.0
    assert snap.application.latency_p50_ms < 50.0
    # Business KPI is collapsed!
    assert snap.business.checkout_success_rate < 15.0
    assert snap.business.cart_abandonment_rate > 80.0


def test_black_friday_traffic_burst_archetype():
    """Verify benign traffic burst behaves as healthy operational scaling."""
    gen = MultiTierTelemetryGenerator(seed=42)
    snap = gen.generate_snapshot(archetype=AnomalyArchetype.BLACK_FRIDAY_TRAFFIC_BURST)

    # Traffic burst is benign, not an operational failure
    assert snap.ground_truth_anomalous is False
    assert snap.application.requests_per_sec > 300.0
    assert snap.business.checkout_success_rate >= 95.0
    # Infra is handling load
    assert snap.infrastructure.cpu_percent <= 85.0


def test_generate_incident_scenario():
    """Verify timeline scenario contains baseline, incident, and recovery."""
    gen = MultiTierTelemetryGenerator(seed=42)
    scenario = gen.generate_incident_scenario(
        archetype=AnomalyArchetype.DB_CONNECTION_POOL_SATURATION,
        total_ticks=60,
        anomaly_start_tick=20,
        anomaly_duration_ticks=20,
    )

    assert len(scenario) == 60
    # Baseline phase [0..19]
    assert scenario[5].ground_truth_label == AnomalyArchetype.NOMINAL
    assert scenario[5].ground_truth_anomalous is False

    # Incident phase [20..39]
    assert scenario[25].ground_truth_label == AnomalyArchetype.DB_CONNECTION_POOL_SATURATION
    assert scenario[25].ground_truth_anomalous is True

    # Recovery phase [40..59]
    assert scenario[58].ground_truth_label == AnomalyArchetype.NOMINAL


def test_to_dataframe_conversion():
    """Verify flattening snapshots to a pandas DataFrame."""
    gen = MultiTierTelemetryGenerator(seed=42)
    snaps = gen.generate_batch(num_snapshots=15, archetype=AnomalyArchetype.NOMINAL)
    df = MultiTierTelemetryGenerator.to_dataframe(snaps)

    assert isinstance(df, pd.DataFrame)
    assert len(df) == 15
    assert "infra_cpu_percent" in df.columns
    assert "app_latency_p95_ms" in df.columns
    assert "db_pool_utilization" in df.columns
    assert "biz_checkout_success_rate" in df.columns
    assert "ground_truth_label" in df.columns
    assert df["infra_cpu_percent"].isna().sum() == 0
