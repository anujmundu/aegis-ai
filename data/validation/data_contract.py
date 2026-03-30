"""Production Data Contract Firewall & Quarantine DLQ for AegisAI.

Enforces zero-trust ingestion boundaries on all multi-tier telemetry streams:
- Schema type conformity & field completeness
- Strict physical bounds validation (CPU/Memory/Pool in [0, 100], latencies >= 0)
- Cross-tier physical invariants (p50 <= p95 <= p99)
- Monotonic timestamp progression per service
- Dead Letter Queue (DLQ) Quarantine envelope for malformed records
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union

from pydantic import BaseModel, Field, ValidationError

from data.schemas.events import TelemetrySnapshot


class DataContractErrorCode(str, Enum):
    """Standardized validation rejection codes."""
    SCHEMA_VALIDATION_FAILED = "SCHEMA_VALIDATION_FAILED"
    BOUNDS_OUT_OF_RANGE = "BOUNDS_OUT_OF_RANGE"
    CROSS_FIELD_INVARIANT_VIOLATION = "CROSS_FIELD_INVARIANT_VIOLATION"
    TIMESTAMP_NON_MONOTONIC = "TIMESTAMP_NON_MONOTONIC"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


class QuarantineEnvelope(BaseModel):
    """Dead Letter Queue (DLQ) wrapper for quarantined telemetry payloads."""
    error_code: DataContractErrorCode
    error_message: str
    raw_payload: Dict[str, Any]
    quarantined_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    service_id: Optional[str] = None
    trace_id: Optional[str] = None


class ValidationResult(BaseModel):
    """Result returned by the DataContractValidator."""
    is_valid: bool
    snapshot: Optional[TelemetrySnapshot] = None
    quarantine: Optional[QuarantineEnvelope] = None
    warnings: List[str] = Field(default_factory=list)


class DataContractValidator:
    """Firewall enforcing strict physical & semantic contracts on telemetry."""

    def __init__(self, enforce_monotonic_timestamps: bool = True) -> None:
        self.enforce_monotonic_timestamps = enforce_monotonic_timestamps
        # Tracks last observed timestamp per service_id
        self._last_seen_timestamps: Dict[str, datetime] = {}

    def reset(self) -> None:
        """Reset historical timestamp cache."""
        self._last_seen_timestamps.clear()

    def validate(self, payload: Union[Dict[str, Any], TelemetrySnapshot]) -> ValidationResult:
        """Validate a single incoming record against the data contract."""
        raw_dict: Dict[str, Any] = (
            payload.model_dump(mode="json") if isinstance(payload, TelemetrySnapshot) else payload
        )

        # 1. Parse and validate Pydantic Schema
        snapshot: TelemetrySnapshot
        if isinstance(payload, TelemetrySnapshot):
            snapshot = payload
        else:
            try:
                snapshot = TelemetrySnapshot.model_validate(payload)
            except ValidationError as e:
                return ValidationResult(
                    is_valid=False,
                    quarantine=QuarantineEnvelope(
                        error_code=DataContractErrorCode.SCHEMA_VALIDATION_FAILED,
                        error_message=str(e),
                        raw_payload=raw_dict,
                        service_id=raw_dict.get("service_id"),
                        trace_id=raw_dict.get("trace_id"),
                    ),
                )
            except Exception as e:
                return ValidationResult(
                    is_valid=False,
                    quarantine=QuarantineEnvelope(
                        error_code=DataContractErrorCode.UNKNOWN_ERROR,
                        error_message=f"Unexpected parsing error: {e}",
                        raw_payload=raw_dict,
                    ),
                )

        warnings: List[str] = []

        # 2. Strict Cross-Tier Physical Invariants
        app = snapshot.application
        if not (app.latency_p50_ms <= app.latency_p95_ms <= app.latency_p99_ms):
            return ValidationResult(
                is_valid=False,
                quarantine=QuarantineEnvelope(
                    error_code=DataContractErrorCode.CROSS_FIELD_INVARIANT_VIOLATION,
                    error_message=(
                        f"Latency quantile violation: p50={app.latency_p50_ms}ms, "
                        f"p95={app.latency_p95_ms}ms, p99={app.latency_p99_ms}ms "
                        f"(Expected p50 <= p95 <= p99)"
                    ),
                    raw_payload=raw_dict,
                    service_id=snapshot.service_id,
                    trace_id=snapshot.trace_id,
                ),
            )

        # 3. Numeric Bounds Verification
        infra = snapshot.infrastructure
        if infra.cpu_percent < 0.0 or infra.cpu_percent > 100.0:
            return ValidationResult(
                is_valid=False,
                quarantine=QuarantineEnvelope(
                    error_code=DataContractErrorCode.BOUNDS_OUT_OF_RANGE,
                    error_message=f"CPU percentage out of bounds [0, 100]: {infra.cpu_percent}",
                    raw_payload=raw_dict,
                    service_id=snapshot.service_id,
                    trace_id=snapshot.trace_id,
                ),
            )

        if infra.memory_percent < 0.0 or infra.memory_percent > 100.0:
            return ValidationResult(
                is_valid=False,
                quarantine=QuarantineEnvelope(
                    error_code=DataContractErrorCode.BOUNDS_OUT_OF_RANGE,
                    error_message=f"Memory percentage out of bounds [0, 100]: {infra.memory_percent}",
                    raw_payload=raw_dict,
                    service_id=snapshot.service_id,
                    trace_id=snapshot.trace_id,
                ),
            )

        db = snapshot.database
        if db.connection_pool_utilization < 0.0 or db.connection_pool_utilization > 100.0:
            return ValidationResult(
                is_valid=False,
                quarantine=QuarantineEnvelope(
                    error_code=DataContractErrorCode.BOUNDS_OUT_OF_RANGE,
                    error_message=f"DB pool utilization out of bounds [0, 100]: {db.connection_pool_utilization}",
                    raw_payload=raw_dict,
                    service_id=snapshot.service_id,
                    trace_id=snapshot.trace_id,
                ),
            )

        biz = snapshot.business
        if biz.checkout_success_rate < 0.0 or biz.checkout_success_rate > 100.0:
            return ValidationResult(
                is_valid=False,
                quarantine=QuarantineEnvelope(
                    error_code=DataContractErrorCode.BOUNDS_OUT_OF_RANGE,
                    error_message=f"Checkout success rate out of bounds [0, 100]: {biz.checkout_success_rate}",
                    raw_payload=raw_dict,
                    service_id=snapshot.service_id,
                    trace_id=snapshot.trace_id,
                ),
            )

        # 4. Monotonic Timestamp Verification
        if self.enforce_monotonic_timestamps:
            last_ts = self._last_seen_timestamps.get(snapshot.service_id)
            if last_ts is not None and snapshot.timestamp < last_ts:
                return ValidationResult(
                    is_valid=False,
                    quarantine=QuarantineEnvelope(
                        error_code=DataContractErrorCode.TIMESTAMP_NON_MONOTONIC,
                        error_message=(
                            f"Non-monotonic timestamp detected for {snapshot.service_id}: "
                            f"incoming {snapshot.timestamp.isoformat()} < last {last_ts.isoformat()}"
                        ),
                        raw_payload=raw_dict,
                        service_id=snapshot.service_id,
                        trace_id=snapshot.trace_id,
                    ),
                )
            self._last_seen_timestamps[snapshot.service_id] = snapshot.timestamp

        return ValidationResult(is_valid=True, snapshot=snapshot, warnings=warnings)

    def validate_batch(
        self, payloads: List[Union[Dict[str, Any], TelemetrySnapshot]]
    ) -> Tuple[List[TelemetrySnapshot], List[QuarantineEnvelope]]:
        """Validate a batch of payloads, separating valid snapshots and quarantined DLQ items."""
        valid_snapshots: List[TelemetrySnapshot] = []
        quarantined: List[QuarantineEnvelope] = []

        for p in payloads:
            res = self.validate(p)
            if res.is_valid and res.snapshot is not None:
                valid_snapshots.append(res.snapshot)
            elif res.quarantine is not None:
                quarantined.append(res.quarantine)

        return valid_snapshots, quarantined
