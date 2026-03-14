"""Telemetry Ingestion & Real-Time Statistical Triage Router."""

import time

from fastapi import APIRouter, Depends, HTTPException, status

from apps.api.dependencies import get_contract_validator, get_statistical_engine
from apps.api.metrics import track_anomaly_detection, track_snapshot_ingested
from apps.api.schemas import (
    BatchTelemetryIngestRequest,
    BatchTelemetryIngestResponse,
    TelemetryIngestResponse,
)
from data.schemas.events import TelemetrySnapshot
from data.validation.data_contract import DataContractValidator
from ml.models.statistical.engine import StatisticalAnomalyEngine

router = APIRouter(prefix="/v1/telemetry", tags=["Telemetry Ingestion"])


@router.post(
    "/ingest",
    response_model=TelemetryIngestResponse,
    summary="Ingest & Triage Telemetry Snapshot",
    description="Validates incoming multi-tier snapshot against data contract firewall and executes real-time statistical anomaly detection (p99 < 15ms).",
)
@router.post("/snapshot", response_model=TelemetryIngestResponse, include_in_schema=False)
def ingest_telemetry(
    snapshot: TelemetrySnapshot,
    validator: DataContractValidator = Depends(get_contract_validator),
    engine: StatisticalAnomalyEngine = Depends(get_statistical_engine),
) -> TelemetryIngestResponse:
    """Ingest single telemetry snapshot and evaluate real-time anomaly signals."""
    start_t = time.perf_counter()

    # 1. Firewall Contract Validation
    val_res = validator.validate(snapshot)
    if not val_res.is_valid:
        quarantine = val_res.quarantine
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": quarantine.error_code.value if quarantine else "DATA_CONTRACT_VIOLATION",
                "message": quarantine.error_message if quarantine else "Snapshot failed data contract validation.",
            },
        )

    # 2. Real-Time Statistical Anomaly Triage
    signals = engine.analyze_snapshot(snapshot)
    exec_ms = (time.perf_counter() - start_t) * 1000.0

    is_anom = len(signals) > 0
    primary_sig = next((s for s in signals if s.is_primary_driver), signals[0] if signals else None)
    primary_name = primary_sig.metric_name if primary_sig else None
    max_sigma = max([abs(s.deviation_sigma) for s in signals], default=0.0)
    anom_score = min(max_sigma / 6.0, 1.0)
    triage_str = "ANOMALY_CONFIRMED" if is_anom else "NOMINAL"

    # 3. Prometheus Observability Instrumentation
    track_snapshot_ingested(snapshot.service_id, is_anom)
    for s in signals:
        sev_str = s.severity.value if hasattr(s.severity, "value") else str(s.severity)
        track_anomaly_detection(
            service_id=snapshot.service_id,
            detector_type=s.detector_type,
            severity=sev_str,
            duration_seconds=exec_ms / 1000.0,
        )

    return TelemetryIngestResponse(
        service_id=snapshot.service_id,
        trace_id=snapshot.trace_id,
        is_anomalous=is_anom,
        anomaly_score=round(anom_score, 4),
        signals_count=len(signals),
        primary_driver=primary_name,
        signals=signals,
        triage_verdict=triage_str,
        execution_time_ms=round(exec_ms, 2),
    )


@router.post(
    "/batch",
    response_model=BatchTelemetryIngestResponse,
    summary="Batch Ingest Telemetry Snapshots",
    description="High-throughput batch ingestion endpoint with streaming statistical anomaly scoring.",
)
def ingest_batch_telemetry(
    payload: BatchTelemetryIngestRequest,
    engine: StatisticalAnomalyEngine = Depends(get_statistical_engine),
) -> BatchTelemetryIngestResponse:
    """Ingest and evaluate a sequence of telemetry snapshots."""
    start_t = time.perf_counter()
    anomalous_traces = []

    for snap in payload.snapshots:
        sigs = engine.analyze_snapshot(snap)
        if len(sigs) > 0:
            anomalous_traces.append(snap.trace_id)

    exec_ms = (time.perf_counter() - start_t) * 1000.0
    total = len(payload.snapshots)
    anom_count = len(anomalous_traces)
    rate = (anom_count / total * 100.0) if total > 0 else 0.0

    return BatchTelemetryIngestResponse(
        total_ingested=total,
        anomalies_detected=anom_count,
        anomaly_rate_pct=round(rate, 2),
        anomaly_trace_ids=anomalous_traces,
        execution_time_ms=round(exec_ms, 2),
    )
