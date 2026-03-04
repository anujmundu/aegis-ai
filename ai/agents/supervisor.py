"""Supervisor Agent Node for AegisAI Multi-Agent Reliability Graph.

Role:
- Central director overseeing state lifecycle transitions across all specialist nodes.
- Evaluates exit conditions, loop budgets, and conditional routing:
    * Loops back to Investigator when Validator detects grounding deficiencies (up to max 2 revisions)
    * Fast-tracks nominal telemetry to resolution
    * Routes to Action Agent once root cause is verified and grounded
    * Enforces human approval safety checkpoint prior to execution
"""

from typing import Any, Dict, Literal

from ai.agents.state import AgentState
from data.schemas.events import IncidentStatus

RouteDestination = Literal[
    "statistician",
    "retriever",
    "investigator",
    "validator",
    "action_agent",
    "approval_gate",
    "end",
]


class SupervisorAgent:
    """Specialized supervisor node managing dynamic routing in the reliability graph."""

    def __init__(self, name: str = "supervisor", max_revisions: int = 2) -> None:
        self.name = name
        self.max_revisions = max_revisions

    def decide_next_node(self, state: AgentState) -> RouteDestination:
        """Evaluate current state and return the next node destination."""
        # 1. Check if incident was resolved early (nominal telemetry)
        if state.status == IncidentStatus.RESOLVED and not state.raw_signals:
            return "end"

        # 2. Check if primary driver telemetry triage is completed
        if state.primary_driver is None and state.raw_signals:
            return "statistician"

        # 3. Check if RAG citations were retrieved
        if not state.citations and state.primary_driver is not None:
            return "retriever"

        # 4. Check if root cause hypothesis exists
        if not state.root_cause_hypothesis and state.citations:
            return "investigator"

        # 5. Check validation / grounding
        if state.root_cause_hypothesis and not state.is_grounded:
            if state.revision_count < self.max_revisions and state.validation_feedback is not None:
                # Loop back to investigator to address grounding critique
                return "investigator"
            elif state.validation_feedback is None:
                # Needs initial validation
                return "validator"
            else:
                # Reached max revisions; escalate to action agent with audit notice
                return "action_agent"

        # 6. Check remediation proposal
        if state.is_grounded and state.remediation_proposal is None:
            return "action_agent"

        # 7. Check human approval gate
        if state.remediation_proposal is not None:
            if state.requires_human_approval and not state.is_approved:
                return "approval_gate"
            else:
                return "end"

        return "end"

    def execute(self, state: AgentState) -> Dict[str, Any]:
        """Supervisor step logging execution and annotating next routing target."""
        next_step = self.decide_next_node(state)
        audit_entry = {
            "agent": self.name,
            "action": "SUPERVISE_ROUTING",
            "next_node": next_step,
            "revision_count": state.revision_count,
            "is_grounded": state.is_grounded,
            "status": state.status.value,
        }
        return {
            "next_node": next_step,
            "iteration_count": state.iteration_count + 1,
            "audit_log": state.audit_log + [audit_entry],
        }
