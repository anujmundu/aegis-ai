"""Pydantic v2 Data Models & Event Contracts for Multi-Tier Telemetry.

Covers Infrastructure, Application, Database, and Business KPI tiers,
plus the unified operational TelemetrySnapshot schema.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class IncidentSeverity(str, Enum):
    """Operational incident severity hierarchy."""
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


class IncidentStatus(str, Enum):
    """Incident lifecycle state machine."""
    DETECTED = "DETECTED"
    TRIAGED = "TRIAGED"
    INVESTIGATING = "INVESTIGATING"
    ROOT_CAUSE_IDENTIFIED = "ROOT_CAUSE_IDENTIFIED"
    REMEDIATION_PROPOSED = "REMEDIATION_PROPOSED"
    HUMAN_APPROVAL_PENDING = "HUMAN_APPROVAL_PENDING"
    REMEDIATION_EXECUTED = "REMEDIATION_EXECUTED"
    VERIFIED = "VERIFIED"
    POSTMORTEM_GENERATED = "POSTMORTEM_GENERATED"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class AnomalyArchetype(str, Enum):
    """Ground truth synthetic incident archetypes for evaluation."""
    NOMINAL = "NOMINAL"
    DB_CONNECTION_POOL_SATURATION = "DB_CONNECTION_POOL_SATURATION"
    MEMORY_LEAK_GC_PAUSE = "MEMORY_LEAK_GC_PAUSE"
    CASCADING_THIRD_PARTY_FAILURE = "CASCADING_THIRD_PARTY_FAILURE"
    PAYMENT_GATEWAY_OUTAGE = "PAYMENT_GATEWAY_OUTAGE"
    BLACK_FRIDAY_TRAFFIC_BURST = "BLACK_FRIDAY_TRAFFIC_BURST"


class InfrastructureMetrics(BaseModel):
    """Tier 1: Host and Container Infrastructure Metrics."""
    cpu_percent: float = Field(..., ge=0.0, le=100.0, description="CPU usage percentage")
    memory_percent: float = Field(..., ge=0.0, le=100.0, description="Memory utilization percentage")
    disk_io_mbps: float = Field(..., ge=0.0, description="Disk I/O throughput in MB/s")
    network_egress_mbps: float = Field(..., ge=0.0, description="Network egress throughput in Mbps")
    network_ingress_mbps: float = Field(..., ge=0.0, description="Network ingress throughput in Mbps")


class ApplicationMetrics(BaseModel):
    """Tier 2: Microservice & Application Metrics."""
    service_id: str = Field(..., min_length=2, max_length=64, examples=["checkout-service"])
    endpoint: str = Field(..., examples=["/api/v1/checkout"])
    requests_per_sec: float = Field(..., ge=0.0, description="HTTP requests per second")
    latency_p50_ms: float = Field(..., ge=0.0, description="Median response latency in ms")
    latency_p95_ms: float = Field(..., ge=0.0, description="95th percentile latency in ms")
    latency_p99_ms: float = Field(..., ge=0.0, description="99th percentile latency in ms")
    http_2xx_count: int = Field(default=0, ge=0)
    http_4xx_count: int = Field(default=0, ge=0)
    http_5xx_count: int = Field(default=0, ge=0)

    @property
    def error_rate(self) -> float:
        total = self.http_2xx_count + self.http_4xx_count + self.http_5xx_count
        return (self.http_5xx_count / total) if total > 0 else 0.0


class DatabaseMetrics(BaseModel):
    """Tier 3: Relational & Cache Database Metrics."""
    db_instance_id: str = Field(..., examples=["aurora-postgres-primary"])
    active_connections: int = Field(..., ge=0, description="Active client connections")
    connection_pool_utilization: float = Field(
        ..., ge=0.0, le=100.0, description="Pool capacity utilization percentage"
    )
    query_latency_mean_ms: float = Field(..., ge=0.0, description="Mean query execution time")
    slow_queries_per_sec: float = Field(default=0.0, ge=0.0, description="Queries taking >500ms")
    row_lock_waits: int = Field(default=0, ge=0, description="Active row lock contention count")


class BusinessMetrics(BaseModel):
    """Tier 4: Enterprise Business Impact & Transaction KPIs."""
    order_volume: int = Field(..., ge=0, description="Completed customer orders in time window")
    revenue_usd: float = Field(..., ge=0.0, description="Gross transactional revenue in USD")
    checkout_success_rate: float = Field(
        ..., ge=0.0, le=100.0, description="Successful checkouts percentage"
    )
    cart_abandonment_rate: float = Field(
        ..., ge=0.0, le=100.0, description="Abandoned carts percentage"
    )


class TelemetrySnapshot(BaseModel):
    """Unified Multi-Tier Operational Telemetry Snapshot.

    Combines all four architectural tiers with anomaly labels and metadata.
    """
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC measurement timestamp",
    )
    trace_id: str = Field(..., examples=["tr-9a8f21b4-7c3d"])
    service_id: str = Field(..., examples=["checkout-service"])

    # Architectural Tiers
    infrastructure: InfrastructureMetrics
    application: ApplicationMetrics
    database: DatabaseMetrics
    business: BusinessMetrics

    # Ground Truth Synthetic Evaluation Labels
    ground_truth_label: AnomalyArchetype = Field(default=AnomalyArchetype.NOMINAL)
    ground_truth_anomalous: bool = Field(default=False)
    simulated_root_cause: Optional[str] = None

    @field_validator("timestamp", mode="before")
    @classmethod
    def parse_timestamp(cls, val):
        if isinstance(val, str):
            return datetime.fromisoformat(val.replace("Z", "+00:00"))
        return val


class IncidentCreate(BaseModel):
    """Incident creation schema."""
    title: str = Field(..., min_length=5, max_length=256)
    severity: IncidentSeverity
    service_id: str
    summary: str
    correlated_signals: List[str]
    root_cause_hypothesis: Optional[str] = None
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    grounded_citations: List[Dict[str, str]] = Field(default_factory=list)


class RemediationProposal(BaseModel):
    """Remediation proposal from the Action Agent."""
    incident_id: str
    action_type: str = Field(..., examples=["SCALE_SERVICE", "INCREASE_POOL", "RESTART_CONTAINER"])
    target_resource: str = Field(..., examples=["aurora-postgres-pool", "payment-service-pods"])
    parameters: Dict[str, str] = Field(default_factory=dict)
    risk_level: str = Field(default="LOW", description="LOW | MEDIUM | HIGH")
    requires_human_approval: bool = Field(default=True)
    dry_run_simulation: bool = Field(default=True)
    justification: str


class AnomalySignal(BaseModel):
    """Normalized operational anomaly signal emitted by statistical and ML detectors."""
    signal_id: str = Field(..., description="Unique signal instance identifier")
    service_id: str
    metric_name: str
    detector_type: str = Field(
        ..., description="Detector type (e.g., z_score, modified_z_score, ewma, mahalanobis, correlation_drift)"
    )
    observed_value: float
    baseline_value: float
    deviation_sigma: float
    severity: IncidentSeverity = IncidentSeverity.LOW
    is_anomaly: bool = True
    is_primary_driver: bool = False
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, str] = Field(default_factory=dict)
