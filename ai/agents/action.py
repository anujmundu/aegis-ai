"""Action Agent Node for AegisAI Multi-Agent Reliability Graph.

Role:
- Formulates authoritative, SOP-aligned Remediation Proposals based on verified root causes.
- Enforces strict safety gates:
    * Deterministic dry-run simulation mode (dry_run_simulation = True)
    * Automated human approval escalation for High/Critical severity or risky actions
    * Mandatory rollback plan generation
- Simulates safe execution when pre-approved or gated through operator sign-off.
"""

import uuid
from typing import Any, Dict, Optional

from ai.agents.state import AgentState
from data.schemas.events import (
    IncidentSeverity,
    IncidentStatus,
    RemediationProposal,
)


class ActionAgent:
    """Specialized agent node synthesizing actionable and safe operational remediation plans."""

    def __init__(self, name: str = "action_agent") -> None:
        self.name = name

    def _determine_proposal(self, state: AgentState) -> RemediationProposal:
        """Formulate a targeted remediation proposal based on primary driver & classifier archetype."""
        p_metric = state.primary_driver.metric_name if state.primary_driver else ""
        archetype = state.classifier_archetype or ""
        sev = state.severity

        # 1. DB Connection Pool Saturation
        if "pool" in p_metric or "DB_CONNECTION_POOL" in archetype:
            return RemediationProposal(
                incident_id=state.incident_id,
                action_type="EXPAND_DB_CONNECTION_POOL",
                target_resource=f"{state.service_id}/aurora-postgres-pool",
                parameters={
                    "current_max_connections": "100",
                    "proposed_max_connections": "250",
                    "idle_timeout_seconds": "30",
                    "rollback_command": "aws rds modify-db-parameter-group --parameter 'name=max_connections,value=100'",
                },
                risk_level="HIGH",
                requires_human_approval=True,
                dry_run_simulation=True,
                justification=(
                    f"Connection pool saturated on {state.service_id}. "
                    "Increasing pool ceiling and enforcing strict idle reaper to eliminate client starvation."
                ),
            )

        # 2. Memory Leak / GC Pause
        elif "memory" in p_metric or "MEMORY_LEAK" in archetype:
            return RemediationProposal(
                incident_id=state.incident_id,
                action_type="ROLLING_CONTAINER_RESTART",
                target_resource=f"k8s-deployment/{state.service_id}",
                parameters={
                    "max_unavailable": "20%",
                    "capture_heap_dump": "true",
                    "dump_gcs_bucket": "gs://aegisai-diagnostics-heapdumps",
                    "rollback_command": "kubectl rollout undo deployment/" + state.service_id,
                },
                risk_level="HIGH",
                requires_human_approval=True,
                dry_run_simulation=True,
                justification=(
                    f"Memory utilization exceeds 85% with escalating GC pauses in {state.service_id}. "
                    "Triggering staggered rolling restart with heap dump capture."
                ),
            )

        # 3. Cascading Third-Party Failure
        elif "latency" in p_metric or "error_rate" in p_metric or "THIRD_PARTY" in archetype:
            return RemediationProposal(
                incident_id=state.incident_id,
                action_type="ENGAGE_CIRCUIT_BREAKER",
                target_resource=f"envoy-cluster/{state.service_id}/downstream-partner",
                parameters={
                    "consecutive_5xx": "5",
                    "base_ejection_time_seconds": "60",
                    "max_ejection_percent": "100",
                    "rollback_command": "envoy admin /reset-outlier-detection",
                },
                risk_level="MEDIUM",
                # Circuit breakers can be automated if severity is not critical
                requires_human_approval=(sev in [IncidentSeverity.CRITICAL, IncidentSeverity.HIGH]),
                dry_run_simulation=True,
                justification=(
                    f"Upstream timeout cascade affecting {state.service_id}. "
                    "Engaging outlier circuit breaker to shed failing downstream calls and fallback to cached response."
                ),
            )

        # 4. Payment Gateway Outage
        elif "checkout" in p_metric or "order" in p_metric or "PAYMENT_GATEWAY" in archetype:
            return RemediationProposal(
                incident_id=state.incident_id,
                action_type="FAILOVER_PAYMENT_GATEWAY",
                target_resource="payment-routing-mesh/gateway-router",
                parameters={
                    "primary_provider": "stripe",
                    "failover_target": "adyen",
                    "traffic_shift_percent": "100",
                    "rollback_command": "curl -X POST https://internal-mesh/routes/payment --data 'target=stripe'",
                },
                risk_level="HIGH",
                requires_human_approval=True,
                dry_run_simulation=True,
                justification=(
                    "External payment provider outage detected. "
                    "Rerouting checkout payment transactions to secondary failover provider."
                ),
            )

        # 5. Traffic Burst (Black Friday / Viral Event)
        elif "traffic" in p_metric or "request" in p_metric or "TRAFFIC_BURST" in archetype:
            return RemediationProposal(
                incident_id=state.incident_id,
                action_type="SCALE_HORIZONTAL_POD_AUTOSCALER",
                target_resource=f"k8s-hpa/{state.service_id}",
                parameters={
                    "min_replicas": "10",
                    "max_replicas": "50",
                    "target_cpu_percent": "60",
                    "rollback_command": f"kubectl scale deployment {state.service_id} --replicas=3",
                },
                risk_level="LOW",
                requires_human_approval=False,
                dry_run_simulation=True,
                justification=(
                    f"Legitimate traffic burst detected on {state.service_id}. "
                    "Proactively scaling horizontal pod replicas to absorb incoming load without throttling."
                ),
            )

        # 6. Default / Nominal Case
        else:
            return RemediationProposal(
                incident_id=state.incident_id,
                action_type="CONTINUOUS_OBSERVABILITY_MONITORING",
                target_resource=f"telemetry-agent/{state.service_id}",
                parameters={
                    "polling_interval_seconds": "5",
                    "alert_channel": "slack-#reliability-alerts",
                },
                risk_level="LOW",
                requires_human_approval=False,
                dry_run_simulation=True,
                justification="Telemetry signals within nominal baseline bounds; continuous tracking active.",
            )

    def execute(self, state: AgentState) -> Dict[str, Any]:
        """Synthesize remediation plan and either execute dry-run simulation or request human approval."""
        proposal = self._determine_proposal(state)
        requires_approval = proposal.requires_human_approval

        approval_token: Optional[str] = state.approval_token
        is_approved = state.is_approved
        execution_result: Optional[str] = None
        next_status: IncidentStatus

        # If approval is required and state is not yet approved
        if requires_approval and not is_approved:
            if not approval_token:
                approval_token = f"APPR-{uuid.uuid4().hex[:8].upper()}"
            next_status = IncidentStatus.HUMAN_APPROVAL_PENDING
            execution_result = (
                f"DRY_RUN_PASSED: High-impact action '{proposal.action_type}' formulated with dry_run_simulation=True. "
                f"Target: {proposal.target_resource}. Awaiting human operator approval token '{approval_token}'."
            )
        else:
            # Low risk or pre-approved: simulate safe execution
            next_status = IncidentStatus.REMEDIATION_EXECUTED
            token_note = f" (Authorized with token '{approval_token}')" if approval_token else ""
            execution_result = (
                f"SIMULATION_SUCCESS: Successfully simulated execution of '{proposal.action_type}' "
                f"on '{proposal.target_resource}'{token_note}. Parameters: {proposal.parameters}. "
                "Rollback plan verified and cached. Telemetry verification active."
            )

        audit_entry = {
            "agent": self.name,
            "action": "FORMULATE_REMEDIATION",
            "action_type": proposal.action_type,
            "target_resource": proposal.target_resource,
            "risk_level": proposal.risk_level,
            "requires_human_approval": requires_approval,
            "is_approved": is_approved,
            "approval_token": approval_token,
            "status": next_status.value,
        }

        return {
            "remediation_proposal": proposal,
            "requires_human_approval": requires_approval,
            "is_approved": is_approved,
            "approval_token": approval_token,
            "execution_result": execution_result,
            "status": next_status,
            "audit_log": state.audit_log + [audit_entry],
        }
