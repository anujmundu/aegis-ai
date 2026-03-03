"""Agent State Schema for LangGraph Multi-Agent Reliability Pipeline.

Maintains the complete operational investigation context:
- Incident metadata & operational status
- Correlated telemetry signals & isolated primary driver
- Hybrid RAG retrieved evidence & citations
- Root cause hypothesis & structured reasoning trace
- Anti-hallucination validation state & grounding score
- Remediation proposal & human approval safety gate
- Audit trail & execution log
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from ai.rag.models import RetrievedEvidence
from data.schemas.events import (
    AnomalySignal,
    IncidentSeverity,
    IncidentStatus,
    RemediationProposal,
)


class AgentState(BaseModel):
    """Central state passed across all specialized agent nodes in the LangGraph graph."""

    # 1. Incident Lifecycle Metadata
    incident_id: str = Field(..., description="Unique incident identifier")
    service_id: str = Field(..., description="Affected target microservice identifier")
    severity: IncidentSeverity = Field(default=IncidentSeverity.MEDIUM)
    status: IncidentStatus = Field(default=IncidentStatus.DETECTED)
    detected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # 2. Telemetry & Statistical Analysis
    raw_signals: List[AnomalySignal] = Field(default_factory=list)
    primary_driver: Optional[AnomalySignal] = Field(default=None)
    correlated_signal_names: List[str] = Field(default_factory=list)
    statistical_summary: str = Field(default="")

    # 3. Model Classification Context
    classifier_archetype: Optional[str] = Field(default=None)
    classifier_confidence: float = Field(default=0.0)

    # 4. Hybrid RAG Evidence
    retrieved_evidence: List[RetrievedEvidence] = Field(default_factory=list)
    citations: List[Dict[str, str]] = Field(default_factory=list)
    historical_context: Optional[str] = Field(
        default=None, description="Past incident history and recurring patterns from memory"
    )

    # 5. Diagnostic Investigation & Reasoning
    root_cause_hypothesis: Optional[str] = Field(default=None)
    reasoning_trace: List[str] = Field(default_factory=list)
    confidence_score: float = Field(default=0.0)

    # 6. Anti-Hallucination & Grounding Validation
    is_grounded: bool = Field(default=False)
    grounding_score: float = Field(default=0.0)
    validation_feedback: Optional[str] = Field(default=None)
    revision_count: int = Field(default=0)

    # 7. Action Remediation & Approval Gate
    remediation_proposal: Optional[RemediationProposal] = Field(default=None)
    requires_human_approval: bool = Field(default=True)
    is_approved: bool = Field(default=False)
    approval_token: Optional[str] = Field(default=None)
    execution_result: Optional[str] = Field(default=None)

    # 8. Orchestrator Audit Trail & Next Routing
    audit_log: List[Dict[str, Any]] = Field(default_factory=list)
    iteration_count: int = Field(default=0)
    next_node: str = Field(default="statistician")
