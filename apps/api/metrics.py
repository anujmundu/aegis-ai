"""Prometheus Observability & Metrics Registry for AegisAI.

Provides:
- HTTP request counters and latency histograms
- Telemetry ingestion and anomaly detection metrics
- ML inference latency SLA tracking ($p99 < 15ms$)
- Multi-agent orchestration step timing and grounding scores
- Subsystem health and uptime gauges
"""

import time

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

# Central Prometheus Collector Registry
REGISTRY = CollectorRegistry(auto_describe=True)

# ------------------------------------------------------------------------------
# 1. HTTP & API Ingestion Telemetry
# ------------------------------------------------------------------------------
HTTP_REQUESTS_TOTAL = Counter(
    "aegisai_http_requests_total",
    "Total incoming HTTP requests processed by the AegisAI microservice",
    ["method", "endpoint", "status_code"],
    registry=REGISTRY,
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "aegisai_http_request_duration_seconds",
    "HTTP request execution latency in seconds",
    ["method", "endpoint"],
    buckets=(0.001, 0.005, 0.010, 0.025, 0.050, 0.100, 0.250, 0.500, 1.0, 2.5),
    registry=REGISTRY,
)

TELEMETRY_SNAPSHOTS_INGESTED_TOTAL = Counter(
    "aegisai_telemetry_snapshots_ingested_total",
    "Total multi-tier telemetry snapshots processed",
    ["service_id", "anomaly_detected"],
    registry=REGISTRY,
)

# ------------------------------------------------------------------------------
# 2. Machine Learning & Anomaly Detection Telemetry
# ------------------------------------------------------------------------------
ANOMALY_DETECTIONS_TOTAL = Counter(
    "aegisai_anomaly_detections_total",
    "Total operational anomaly signals flagged by detectors",
    ["service_id", "detector_type", "severity"],
    registry=REGISTRY,
)

DETECTION_LATENCY_SECONDS = Histogram(
    "aegisai_detection_latency_seconds",
    "Anomaly detector execution duration in seconds (Target p99 < 0.015s)",
    ["detector"],
    buckets=(0.0005, 0.001, 0.002, 0.005, 0.010, 0.015, 0.025, 0.050),
    registry=REGISTRY,
)

MODEL_PREDICTION_CONFIDENCE = Histogram(
    "aegisai_model_prediction_confidence",
    "XGBoost archetype classifier prediction confidence distribution",
    ["archetype"],
    buckets=(0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95, 0.98, 1.0),
    registry=REGISTRY,
)

# ------------------------------------------------------------------------------
# 3. Multi-Agent Orchestration & RAG Telemetry
# ------------------------------------------------------------------------------
AGENT_EXECUTIONS_TOTAL = Counter(
    "aegisai_agent_executions_total",
    "LangGraph multi-agent execution step count",
    ["agent_name", "status"],
    registry=REGISTRY,
)

AGENT_EXECUTION_DURATION_SECONDS = Histogram(
    "aegisai_agent_execution_duration_seconds",
    "Execution duration of individual LangGraph agent nodes",
    ["agent_name"],
    buckets=(0.005, 0.010, 0.025, 0.050, 0.100, 0.250, 0.500, 1.0, 2.5),
    registry=REGISTRY,
)

RAG_GROUNDING_SCORE = Histogram(
    "aegisai_rag_grounding_score",
    "Synthesized incident hypothesis grounding and citation verification score",
    ["service_id"],
    buckets=(0.70, 0.80, 0.85, 0.90, 0.95, 0.98, 1.0),
    registry=REGISTRY,
)

RAG_CITATIONS_RETRIEVED_TOTAL = Counter(
    "aegisai_rag_citations_retrieved_total",
    "Total authoritative citations retrieved from runbooks and postmortems",
    ["source_type"],
    registry=REGISTRY,
)

REMEDIATION_ACTIONS_TOTAL = Counter(
    "aegisai_remediation_actions_total",
    "Remediation actions proposed, approved, or executed",
    ["action_type", "status"],
    registry=REGISTRY,
)

# ------------------------------------------------------------------------------
# 4. System Uptime & Subsystem Health Gauges
# ------------------------------------------------------------------------------
SUBSYSTEM_HEALTH_STATUS = Gauge(
    "aegisai_subsystem_health",
    "Operational status of core subsystems (1=Nominal, 0=Degraded)",
    ["subsystem"],
    registry=REGISTRY,
)

SERVICE_UPTIME_SECONDS = Gauge(
    "aegisai_service_uptime_seconds",
    "Total runtime of AegisAI service in seconds",
    registry=REGISTRY,
)

START_TIME = time.time()

# Pre-initialize default subsystem statuses to nominal
for sub in ["statistical_engine", "ml_ensemble", "rag_retriever", "operational_memory"]:
    SUBSYSTEM_HEALTH_STATUS.labels(subsystem=sub).set(1)


# ------------------------------------------------------------------------------
# Helper Instrumentation Utilities
# ------------------------------------------------------------------------------
def track_http_request(method: str, endpoint: str, status_code: int, duration_seconds: float) -> None:
    """Record an HTTP request transaction and execution duration."""
    HTTP_REQUESTS_TOTAL.labels(method=method, endpoint=endpoint, status_code=str(status_code)).inc()
    HTTP_REQUEST_DURATION_SECONDS.labels(method=method, endpoint=endpoint).observe(duration_seconds)


def track_snapshot_ingested(service_id: str, anomaly_detected: bool) -> None:
    """Record an ingested telemetry snapshot and detection state."""
    TELEMETRY_SNAPSHOTS_INGESTED_TOTAL.labels(
        service_id=service_id,
        anomaly_detected=str(anomaly_detected).lower(),
    ).inc()


def track_anomaly_detection(
    service_id: str,
    detector_type: str,
    severity: str,
    duration_seconds: float,
) -> None:
    """Record an anomaly detection event and execution duration."""
    ANOMALY_DETECTIONS_TOTAL.labels(
        service_id=service_id,
        detector_type=detector_type,
        severity=severity,
    ).inc()
    DETECTION_LATENCY_SECONDS.labels(detector=detector_type).observe(duration_seconds)


def track_model_inference(
    archetype: str,
    confidence: float,
    duration_seconds: float,
) -> None:
    """Record classifier inference metrics."""
    MODEL_PREDICTION_CONFIDENCE.labels(archetype=archetype).observe(confidence)
    DETECTION_LATENCY_SECONDS.labels(detector="xgboost_classifier").observe(duration_seconds)


def track_agent_step(agent_name: str, status: str, duration_seconds: float) -> None:
    """Record agent node execution latency and status."""
    AGENT_EXECUTIONS_TOTAL.labels(agent_name=agent_name, status=status).inc()
    AGENT_EXECUTION_DURATION_SECONDS.labels(agent_name=agent_name).observe(duration_seconds)


def track_rag_grounding(service_id: str, grounding_score: float, citations_count: int, source_type: str = "runbook") -> None:
    """Record RAG grounding score and citation count."""
    RAG_GROUNDING_SCORE.labels(service_id=service_id).observe(grounding_score)
    RAG_CITATIONS_RETRIEVED_TOTAL.labels(source_type=source_type).inc(citations_count)


def track_remediation_action(action_type: str, status: str) -> None:
    """Record proposed or executed remediation actions."""
    REMEDIATION_ACTIONS_TOTAL.labels(action_type=action_type, status=status).inc()


def set_subsystem_health(subsystem: str, is_nominal: bool) -> None:
    """Update subsystem health status gauge."""
    SUBSYSTEM_HEALTH_STATUS.labels(subsystem=subsystem).set(1 if is_nominal else 0)


def get_prometheus_metrics() -> bytes:
    """Serialize all metrics in standard Prometheus exposition text format."""
    # Update service uptime gauge dynamically before export
    SERVICE_UPTIME_SECONDS.set(time.time() - START_TIME)
    return generate_latest(REGISTRY)
