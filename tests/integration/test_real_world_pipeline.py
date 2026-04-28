"""Integration Tests for AegisAI Real-World Telemetry Pipeline.

Validates end-to-end processing of real-world production datasets:
- Numenta Anomaly Benchmark (NAB) real AWS CloudWatch metrics
- Server Machine Dataset (SMD) 38-channel cluster telemetry
- Physical data contract firewall enforcement
- High-performance statistical anomaly triage (<15ms)
- Machine Learning incident classification & anomaly detection
"""

import time
import pytest

from data.real_world.loader import RealWorldDataLoader, RealWorldDatasetTier
from data.schemas.events import AnomalySignal, IncidentSeverity
from data.validation.data_contract import DataContractValidator
from ml.features.feature_extractor import TelemetryFeatureExtractor
from ml.models.classical.incident_classifier import IncidentClassifier
from ml.models.classical.isolation_forest import IsolationForestDetector
from ml.models.statistical.engine import StatisticalAnomalyEngine


@pytest.fixture(scope="module")
def data_loader():
    """Shared RealWorldDataLoader fixture."""
    return RealWorldDataLoader()


@pytest.fixture(scope="module")
def small_dataset(data_loader):
    """Small tier real-world dataset fixture."""
    return data_loader.load_or_create(RealWorldDatasetTier.SMALL)


@pytest.fixture(scope="module")
def difficult_small_dataset(data_loader):
    """Difficult small tier real-world dataset fixture."""
    return data_loader.load_or_create(RealWorldDatasetTier.DIFFICULT_SMALL)


@pytest.fixture(scope="module")
def difficult_medium_dataset(data_loader):
    """Difficult medium tier real-world dataset fixture."""
    return data_loader.load_or_create(RealWorldDatasetTier.DIFFICULT_MEDIUM)


def test_real_world_dataset_contract_compliance(small_dataset):
    """Ensure 100% of real-world telemetry snapshots satisfy the Data Contract Firewall."""
    validator = DataContractValidator(enforce_monotonic_timestamps=False)
    assert len(small_dataset) >= 4000, f"Expected >= 4000 snapshots, got {len(small_dataset)}"

    sample_to_test = small_dataset[:500]
    valid_count = 0
    for snap in sample_to_test:
        res = validator.validate(snap)
        assert res.is_valid is True, f"Failed on snapshot {snap.trace_id}: {res.quarantine.error_message if res.quarantine else ''}"
        valid_count += 1

    assert valid_count == len(sample_to_test)


def test_real_world_physical_invariants(small_dataset):
    """Verify physical invariants: p50 <= p95 <= p99, CPU/Mem in [0, 100], positive throughput."""
    for snap in small_dataset[:500]:
        app = snap.application
        infra = snap.infrastructure
        db = snap.database
        biz = snap.business

        # Latency hierarchy
        assert app.latency_p50_ms <= app.latency_p95_ms <= app.latency_p99_ms
        # Percentage bounds
        assert 0.0 <= infra.cpu_percent <= 100.0
        assert 0.0 <= infra.memory_percent <= 100.0
        assert 0.0 <= db.connection_pool_utilization <= 100.0
        assert 0.0 <= biz.checkout_success_rate <= 100.0
        # Positive throughput
        assert app.requests_per_sec >= 0.0
        assert infra.network_ingress_mbps >= 0.0


def test_statistical_anomaly_engine_on_real_telemetry(small_dataset):
    """Verify statistical anomaly detection processes real AWS telemetry within <15ms SLA."""
    engine = StatisticalAnomalyEngine(service_id="checkout-service")

    latencies = []
    anomalies_detected = 0

    for snap in small_dataset[:200]:
        t0 = time.perf_counter()
        signals = engine.analyze_snapshot(snap)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        latencies.append(elapsed_ms)

        if signals:
            anomalies_detected += 1
            for s in signals:
                assert isinstance(s, AnomalySignal)
                assert s.service_id == "checkout-service"
                assert s.severity in [IncidentSeverity.CRITICAL, IncidentSeverity.HIGH, IncidentSeverity.MEDIUM, IncidentSeverity.LOW, IncidentSeverity.INFO]

    mean_latency = sum(latencies) / len(latencies)
    assert mean_latency < 15.0, f"Mean latency {mean_latency:.2f}ms exceeded 15ms SLA"
    assert anomalies_detected > 0, "Expected at least one real-world anomaly to be detected"


def test_ml_incident_classification_on_real_telemetry(small_dataset):
    """Verify ML XGBoost classifier and Isolation Forest on real-world feature vectors."""
    import joblib
    clf = IncidentClassifier.load("models/checkpoints/incident_classifier.joblib")
    iso = IsolationForestDetector.load("models/checkpoints/isolation_forest.joblib")
    extractor = joblib.load("models/checkpoints/feature_extractor.joblib")

    # Extract features for a real snapshot
    snap = small_dataset[10]
    features = extractor.transform_snapshot(snap)
    assert features is not None
    assert features.shape == (1, len(extractor.feature_names))

    # ML Inference: XGBoost
    class_id, archetype, confidence, probas = clf.predict(features)
    assert isinstance(class_id, int)
    assert isinstance(archetype, str)
    assert 0.0 <= confidence <= 1.0
    assert isinstance(probas, dict)
    assert round(sum(probas.values()), 2) == 1.0

    # Isolation Forest Anomaly Scoring
    score, is_anom = iso.score(features)
    assert isinstance(score, float)
    assert 0.0 <= score <= 1.0
    assert isinstance(is_anom, bool)


def test_difficult_real_world_dataset_contract_compliance(difficult_small_dataset, difficult_medium_dataset):
    """Ensure 100% of difficult real-world telemetry snapshots satisfy the Data Contract Firewall."""
    validator = DataContractValidator(enforce_monotonic_timestamps=False)
    for ds in [difficult_small_dataset, difficult_medium_dataset]:
        sample = ds[:500]
        for snap in sample:
            res = validator.validate(snap)
            assert res.is_valid is True, f"Failed on snapshot {snap.trace_id}: {res.quarantine.error_message if res.quarantine else ''}"


def test_difficult_real_world_physical_invariants(difficult_small_dataset, difficult_medium_dataset):
    """Verify physical invariants on difficult datasets: p50 <= p95 <= p99, [0, 100] bounds."""
    for ds in [difficult_small_dataset, difficult_medium_dataset]:
        for snap in ds[:300]:
            app = snap.application
            infra = snap.infrastructure
            db = snap.database
            biz = snap.business

            assert app.latency_p50_ms <= app.latency_p95_ms <= app.latency_p99_ms
            assert 0.0 <= infra.cpu_percent <= 100.0
            assert 0.0 <= infra.memory_percent <= 100.0
            assert 0.0 <= db.connection_pool_utilization <= 100.0
            assert 0.0 <= biz.checkout_success_rate <= 100.0
            assert app.requests_per_sec >= 0.0
            assert infra.network_ingress_mbps >= 0.0


def test_statistical_anomaly_engine_on_difficult_telemetry(difficult_small_dataset):
    """Verify statistical anomaly detection processes high-variance bidding telemetry within <15ms SLA."""
    svc_id = difficult_small_dataset[0].service_id
    engine = StatisticalAnomalyEngine(service_id=svc_id)

    latencies = []
    anomalies_detected = 0

    for snap in difficult_small_dataset[:200]:
        t0 = time.perf_counter()
        signals = engine.analyze_snapshot(snap)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        latencies.append(elapsed_ms)

        if signals:
            anomalies_detected += 1
            for s in signals:
                assert isinstance(s, AnomalySignal)
                assert s.service_id == svc_id
                assert s.severity in [IncidentSeverity.CRITICAL, IncidentSeverity.HIGH, IncidentSeverity.MEDIUM, IncidentSeverity.LOW, IncidentSeverity.INFO]

    mean_latency = sum(latencies) / len(latencies)
    assert mean_latency < 15.0, f"Mean latency {mean_latency:.2f}ms exceeded 15ms SLA"
    assert anomalies_detected > 0, "Expected anomalies to be detected on high-variance telemetry"


def test_ml_incident_classification_on_difficult_telemetry(difficult_medium_dataset):
    """Verify ML XGBoost classifier and Isolation Forest on difficult labeled dataset."""
    import joblib
    clf = IncidentClassifier.load("models/checkpoints/incident_classifier.joblib")
    iso = IsolationForestDetector.load("models/checkpoints/isolation_forest.joblib")
    extractor = joblib.load("models/checkpoints/feature_extractor.joblib")

    snap = difficult_medium_dataset[10]
    features = extractor.transform_snapshot(snap)
    assert features is not None
    assert features.shape == (1, len(extractor.feature_names))

    class_id, archetype, confidence, probas = clf.predict(features)
    assert isinstance(class_id, int)
    assert isinstance(archetype, str)
    assert 0.0 <= confidence <= 1.0
    assert isinstance(probas, dict)

    score, is_anom = iso.score(features)
    assert isinstance(score, float)
    assert 0.0 <= score <= 1.0
    assert isinstance(is_anom, bool)

