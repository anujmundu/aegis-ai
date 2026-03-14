"""Pydantic Request and Response Schemas for AegisAI FastAPI Microservice."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from data.schemas.events import (
    AnomalySignal,
    IncidentSeverity,
    IncidentStatus,
    RemediationProposal,
    TelemetrySnapshot,
)


class SubsystemHealth(BaseModel):
    """Status details for individual operational subsystems."""

    statistical_engine: str = "nominal"
    ml_ensemble: str = "nominal"
    rag_retriever: str = "nominal"
    operational_memory: str = "nominal"


class HealthResponse(BaseModel):
    """Service liveness and readiness response."""

    status: str = "healthy"
    service: str = "aegis-ai-reliability-engine"
    version: str = "0.7.0"
    environment: str = "production"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    subsystems: SubsystemHealth = Field(default_factory=SubsystemHealth)


class TelemetryIngestResponse(BaseModel):
    """Response returned upon ingesting and triaging a single telemetry snapshot."""

    service_id: str
    trace_id: str
    is_anomalous: bool
    anomaly_score: float
    signals_count: int
    primary_driver: Optional[str] = None
    signals: List[AnomalySignal] = Field(default_factory=list)
    triage_verdict: str
    execution_time_ms: float


class BatchTelemetryIngestRequest(BaseModel):
    """Batch ingestion request payload."""

    snapshots: List[TelemetrySnapshot] = Field(..., min_length=1, max_length=1000)


class BatchTelemetryIngestResponse(BaseModel):
    """Batch ingestion response payload."""

    total_ingested: int
    anomalies_detected: int
    anomaly_rate_pct: float
    anomaly_trace_ids: List[str] = Field(default_factory=list)
    execution_time_ms: float


class DetectionResponse(BaseModel):
    """Comprehensive multi-model ML anomaly detection and classification response."""

    service_id: str
    trace_id: str
    is_anomaly: bool
    ensemble_anomaly_score: float
    isolation_forest_anomaly: bool
    isolation_forest_score: float
    autoencoder_reconstruction_error: float
    predicted_archetype: str
    archetype_confidence: float
    top_contributing_features: List[Dict[str, Any]] = Field(default_factory=list)
    inference_time_ms: float


class IncidentTriageRequest(BaseModel):
    """Trigger request for full multi-agent incident diagnosis."""

    incident_id: str
    service_id: str
    severity: IncidentSeverity = IncidentSeverity.HIGH
    raw_signals: List[AnomalySignal]
    classifier_archetype: Optional[str] = None
    classifier_confidence: float = 0.0


class IncidentTriageResponse(BaseModel):
    """Response returned after executing the LangGraph multi-agent diagnostic cycle."""

    incident_id: str
    service_id: str
    status: IncidentStatus
    severity: IncidentSeverity
    primary_driver_metric: Optional[str] = None
    root_cause_hypothesis: Optional[str] = None
    confidence_score: float = 0.0
    is_grounded: bool = False
    grounding_score: float = 0.0
    citations: List[Dict[str, str]] = Field(default_factory=list)
    reasoning_trace: List[str] = Field(default_factory=list)
    historical_context_summary: Optional[str] = None
    remediation_proposal: Optional[RemediationProposal] = None
    requires_human_approval: bool = True
    is_approved: bool = False
    approval_token: Optional[str] = None
    execution_result: Optional[str] = None
    audit_trail_count: int = 0


class OperatorApprovalRequest(BaseModel):
    """Operator approval payload to authorize remediation action execution."""

    approval_token: str = Field(..., description="Approval token issued by Action Agent gate")
    operator_id: str = Field(default="on-call-sre", description="Operator identity or Slack user ID")
    notes: Optional[str] = Field(default=None, description="Optional operator commentary")


class OperatorApprovalResponse(BaseModel):
    """Response returned after operator approval execution."""

    incident_id: str
    status: IncidentStatus
    is_approved: bool
    action_type: str
    target_resource: str
    execution_result: str
    approved_by: str
    executed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class KnowledgeQueryRequest(BaseModel):
    """Diagnostic query request against hybrid knowledge base."""

    query: str = Field(..., min_length=2, description="Diagnostic query text")
    service_id: Optional[str] = Field(default=None, description="Optional service scope filter")
    top_k: int = Field(default=4, ge=1, le=20)


class KnowledgeQueryResponse(BaseModel):
    """Retrieved evidence citations from runbooks and postmortems."""

    query: str
    total_retrieved: int
    citations: List[Dict[str, Any]] = Field(default_factory=list)


class ActiveIncidentsListResponse(BaseModel):
    """List of active in-flight incidents in Working Memory."""

    total_active: int
    active_incident_ids: List[str] = Field(default_factory=list)
