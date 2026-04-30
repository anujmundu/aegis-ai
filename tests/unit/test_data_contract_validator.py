"""Unit tests for DataContractValidator and DLQ Quarantine Envelope."""

from datetime import datetime, timedelta, timezone

from data.schemas.events import AnomalyArchetype
from data.synthetic.telemetry_generator import MultiTierTelemetryGenerator
from data.validation.data_contract import (
    DataContractErrorCode,
    DataContractValidator,
)


def test_validator_accepts_valid_snapshot():
    """Verify validator accepts compliant generated snapshots."""
    gen = MultiTierTelemetryGenerator(seed=42)
    snap = gen.generate_snapshot(archetype=AnomalyArchetype.NOMINAL)

    validator = DataContractValidator(enforce_monotonic_timestamps=True)
    res = validator.validate(snap)

    assert res.is_valid is True
    assert res.snapshot is not None
    assert res.quarantine is None
    assert res.snapshot.trace_id == snap.trace_id


def test_validator_quarantines_malformed_schema():
    """Verify validator intercepts unparseable payloads into DLQ."""
    malformed_payload = {
        "service_id": "checkout-service",
        "infrastructure": {"cpu_percent": "invalid_string"},  # Corrupted type
    }

    validator = DataContractValidator()
    res = validator.validate(malformed_payload)

    assert res.is_valid is False
    assert res.snapshot is None
    assert res.quarantine is not None
    assert res.quarantine.error_code == DataContractErrorCode.SCHEMA_VALIDATION_FAILED
    assert "cpu_percent" in res.quarantine.error_message


def test_validator_quarantines_quantile_violation():
    """Verify p50 > p95 or p95 > p99 quantile violation triggers quarantine."""
    gen = MultiTierTelemetryGenerator(seed=42)
    snap = gen.generate_snapshot(archetype=AnomalyArchetype.NOMINAL)

    # Invert quantile order
    snap_dict = snap.model_dump(mode="json")
    snap_dict["application"]["latency_p50_ms"] = 150.0  # p50 > p95 (58ms)

    validator = DataContractValidator(enforce_monotonic_timestamps=False)
    res = validator.validate(snap_dict)

    assert res.is_valid is False
    assert res.quarantine is not None
    assert res.quarantine.error_code == DataContractErrorCode.CROSS_FIELD_INVARIANT_VIOLATION
    assert "Latency quantile violation" in res.quarantine.error_message


def test_validator_quarantines_out_of_bounds_metrics():
    """Verify out-of-range metrics (CPU > 100) are quarantined."""
    gen = MultiTierTelemetryGenerator(seed=42)
    snap = gen.generate_snapshot(archetype=AnomalyArchetype.NOMINAL)

    raw = snap.model_dump(mode="json")
    raw["infrastructure"]["cpu_percent"] = 105.0

    validator = DataContractValidator(enforce_monotonic_timestamps=False)
    res = validator.validate(raw)

    assert res.is_valid is False
    assert res.quarantine is not None
    # Caught by Pydantic schema validator or bounds check
    assert res.quarantine.error_code in (
        DataContractErrorCode.BOUNDS_OUT_OF_RANGE,
        DataContractErrorCode.SCHEMA_VALIDATION_FAILED,
    )


def test_validator_enforces_monotonic_timestamps():
    """Verify backwards timestamps are quarantined for the same service."""
    now = datetime.now(timezone.utc)
    gen = MultiTierTelemetryGenerator(seed=42)

    snap1 = gen.generate_snapshot(timestamp=now)
    snap2 = gen.generate_snapshot(timestamp=now - timedelta(seconds=30))  # 30 seconds backwards!

    validator = DataContractValidator(enforce_monotonic_timestamps=True)
    res1 = validator.validate(snap1)
    assert res1.is_valid is True

    res2 = validator.validate(snap2)
    assert res2.is_valid is False
    assert res2.quarantine is not None
    assert res2.quarantine.error_code == DataContractErrorCode.TIMESTAMP_NON_MONOTONIC


def test_validate_batch_separates_valid_and_dlq():
    """Verify batch validation correctly segregates healthy and corrupted payloads."""
    gen = MultiTierTelemetryGenerator(seed=42)
    valid_snaps = gen.generate_batch(num_snapshots=5, archetype=AnomalyArchetype.NOMINAL)

    corrupted_item = {"service_id": "corrupted", "bad_data": True}
    batch = [s.model_dump(mode="json") for s in valid_snaps] + [corrupted_item]

    validator = DataContractValidator()
    valid_out, quarantined_out = validator.validate_batch(batch)

    assert len(valid_out) == 5
    assert len(quarantined_out) == 1
    assert quarantined_out[0].error_code == DataContractErrorCode.SCHEMA_VALIDATION_FAILED
