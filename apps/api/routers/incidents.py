"""Multi-Agent Incident Investigation & Operator Approval Webhook Router."""

from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status

from ai.agents.graph import ReliabilityGraph
from ai.agents.state import AgentState
from ai.memory.coordinator import OperationalMemoryCoordinator
from apps.api.dependencies import get_memory_coordinator, get_reliability_graph
from apps.api.schemas import (
    ActiveIncidentsListResponse,
    IncidentTriageRequest,
    IncidentTriageResponse,
    OperatorApprovalRequest,
    OperatorApprovalResponse,
)
from data.schemas.events import IncidentStatus

router = APIRouter(prefix="/v1/incidents", tags=["Multi-Agent Incident Reliability"])


@router.post(
    "/triage",
    response_model=IncidentTriageResponse,
    summary="Trigger Multi-Agent Incident Investigation",
    description="Dispatches LangGraph multi-agent diagnostic cycle: Statistician -> Retriever -> Investigator -> Validator -> Action Agent.",
)
def triage_incident(
    req: IncidentTriageRequest,
    graph: ReliabilityGraph = Depends(get_reliability_graph),
) -> IncidentTriageResponse:
    """Execute end-to-end multi-agent triage from an initial incident trigger."""
    initial_state = AgentState(
        incident_id=req.incident_id,
        service_id=req.service_id,
        severity=req.severity,
        raw_signals=req.raw_signals,
        classifier_archetype=req.classifier_archetype,
        classifier_confidence=req.classifier_confidence,
    )

    result_state = graph.run(initial_state)

    # Prometheus Observability Instrumentation
    from apps.api.metrics import track_rag_grounding, track_remediation_action
    track_rag_grounding(
        service_id=result_state.service_id,
        grounding_score=float(result_state.grounding_score),
        citations_count=len(result_state.citations),
    )
    if result_state.remediation_proposal:
        track_remediation_action(
            action_type=result_state.remediation_proposal.action_type,
            status="PROPOSED",
        )

    p_metric = result_state.primary_driver.metric_name if result_state.primary_driver else None

    return IncidentTriageResponse(
        incident_id=result_state.incident_id,
        service_id=result_state.service_id,
        status=result_state.status,
        severity=result_state.severity,
        primary_driver_metric=p_metric,
        root_cause_hypothesis=result_state.root_cause_hypothesis,
        confidence_score=round(result_state.confidence_score, 4),
        is_grounded=result_state.is_grounded,
        grounding_score=round(result_state.grounding_score, 4),
        citations=result_state.citations,
        reasoning_trace=result_state.reasoning_trace,
        historical_context_summary=result_state.historical_context,
        remediation_proposal=result_state.remediation_proposal,
        requires_human_approval=result_state.requires_human_approval,
        is_approved=result_state.is_approved,
        approval_token=result_state.approval_token,
        execution_result=result_state.execution_result,
        audit_trail_count=len(result_state.audit_log),
    )


@router.get(
    "/active",
    response_model=ActiveIncidentsListResponse,
    summary="List Active In-Flight Incidents",
    description="Returns all active incident investigation states currently resident in Tier 1 Working Memory.",
)
def list_active_incidents(
    coordinator: OperationalMemoryCoordinator = Depends(get_memory_coordinator),
) -> ActiveIncidentsListResponse:
    """List active incident IDs in working memory."""
    active_ids = coordinator.working.list_active_incident_ids()
    return ActiveIncidentsListResponse(
        total_active=len(active_ids),
        active_incident_ids=active_ids,
    )


@router.get(
    "/{incident_id}",
    summary="Get Incident Investigation State",
    description="Fetches an incident from active Working Memory or historical Episodic Memory.",
)
def get_incident_details(
    incident_id: str,
    coordinator: OperationalMemoryCoordinator = Depends(get_memory_coordinator),
) -> Dict[str, Any]:
    """Retrieve full incident state and audit trail."""
    # 1. Check Working Memory (Active)
    active_state = coordinator.get_active_investigation(incident_id)
    if active_state:
        data = active_state.model_dump()
        data["memory_tier"] = "TIER_1_WORKING_MEMORY"
        return data

    # 2. Check Episodic Memory (Historical / Resolved)
    archived = coordinator.episodic.get_incident(incident_id)
    if archived:
        archived["memory_tier"] = "TIER_2_EPISODIC_MEMORY"
        return archived

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Incident '{incident_id}' not found in active or archived memory.",
    )


@router.post(
    "/{incident_id}/approve",
    response_model=OperatorApprovalResponse,
    summary="Operator Remediation Approval Webhook",
    description="Validates operator approval token, executes simulated remediation action, verifies rollback plan, and archives to Episodic & Semantic memories.",
)
def approve_remediation(
    incident_id: str,
    req: OperatorApprovalRequest,
    graph: ReliabilityGraph = Depends(get_reliability_graph),
    coordinator: OperationalMemoryCoordinator = Depends(get_memory_coordinator),
) -> OperatorApprovalResponse:
    """Operator sign-off endpoint to unblock and execute remediation proposal."""
    # 1. Load active in-flight state from Working Memory
    state = coordinator.get_active_investigation(incident_id)
    if not state:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Active incident '{incident_id}' not found in working memory.",
        )

    if state.status != IncidentStatus.HUMAN_APPROVAL_PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Incident is in status '{state.status.value}', not awaiting operator approval.",
        )

    # 2. Validate token and acquire lock
    if not state.approval_token or state.approval_token != req.approval_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid operator approval token.",
        )

    # 3. Execute approved action via ReliabilityGraph
    try:
        final_state = graph.approve_and_execute(state, req.approval_token)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    proposal = final_state.remediation_proposal
    action_type = proposal.action_type if proposal else "UNKNOWN"
    target_res = proposal.target_resource if proposal else "UNKNOWN"

    from apps.api.metrics import track_remediation_action
    track_remediation_action(action_type=action_type, status="EXECUTED")

    return OperatorApprovalResponse(
        incident_id=final_state.incident_id,
        status=final_state.status,
        is_approved=final_state.is_approved,
        action_type=action_type,
        target_resource=target_res,
        execution_result=final_state.execution_result or "Execution completed.",
        approved_by=req.operator_id,
        executed_at=datetime.now(timezone.utc),
    )


@router.get(
    "/{incident_id}/history",
    summary="Recall Historical Incident Context",
    description="Queries 3-Tier memory for past incidents and postmortems with similar failure signatures.",
)
def recall_incident_history(
    incident_id: str,
    coordinator: OperationalMemoryCoordinator = Depends(get_memory_coordinator),
) -> Dict[str, Any]:
    """Retrieve historical postmortems and recurring pattern analysis."""
    # Lookup incident to get service_id
    state = coordinator.get_active_investigation(incident_id)
    if not state:
        archived = coordinator.episodic.get_incident(incident_id)
        if not archived:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Incident '{incident_id}' not found.",
            )
        service_id = archived["service_id"]
        primary_metric = archived.get("primary_driver_metric")
    else:
        service_id = state.service_id
        primary_metric = state.primary_driver.metric_name if state.primary_driver else None

    context = coordinator.recall_experience(
        service_id=service_id,
        primary_driver_metric=primary_metric,
    )
    return context.model_dump()
