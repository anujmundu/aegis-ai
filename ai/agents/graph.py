"""LangGraph Multi-Agent Reliability Orchestrator for AegisAI.

Coordinates specialized autonomous agents:
  [START]
     │
     ▼
┌──────────────┐
│ Statistician │ ──(No Anomaly)──► [END] (Resolved)
└──────┬───────┘
       │ (Active Signals)
       ▼
┌──────────────┐
│  Retriever   │ (Hybrid RRF RAG: Runbooks & Postmortems)
└──────┬───────┘
       │
       ▼
┌──────────────┐ ◄────────────────┐
│ Investigator │                  │ Grounding Feedback
└──────┬───────┘                  │ (max 2 revisions)
       │                          │
       ▼                          │
┌──────────────┐                  │
│  Validator   │ ──(Score < 0.95)─┘
└──────┬───────┘
       │ (Score >= 0.95 or budget exhausted)
       ▼
┌──────────────┐
│ Action Agent │ (Deterministic Dry-Run Simulation & Proposal)
└──────┬───────┘
       │
       ├──(Low Risk / Pre-Approved)──────────► [END] (Remediation Executed)
       │
       ▼ (High/Critical Risk)
┌─────────────────────┐
│ Human Approval Gate │ ──► [END] (Awaiting Operator Token Sign-off)
└─────────────────────┘
"""

from pathlib import Path
from typing import Any, Dict, Optional

from langgraph.graph import END, START, StateGraph

from ai.agents.action import ActionAgent
from ai.agents.investigator import InvestigatorAgent
from ai.agents.retriever import RetrieverAgent
from ai.agents.state import AgentState
from ai.agents.statistician import StatisticianAgent
from ai.agents.supervisor import SupervisorAgent
from ai.agents.validator import ValidatorAgent
from ai.rag.hybrid import HybridRetriever
from data.schemas.events import IncidentStatus


def human_approval_gate_node(state: AgentState) -> Dict[str, Any]:
    """Node executed when an action requires explicit human operator sign-off."""
    audit_entry = {
        "agent": "approval_gate",
        "action": "AWAIT_OPERATOR_SIGN_OFF",
        "approval_token": state.approval_token,
        "target": (
            state.remediation_proposal.target_resource
            if state.remediation_proposal
            else "unknown"
        ),
        "status": IncidentStatus.HUMAN_APPROVAL_PENDING.value,
    }
    return {
        "status": IncidentStatus.HUMAN_APPROVAL_PENDING,
        "audit_log": state.audit_log + [audit_entry],
    }


class ReliabilityGraph:
    """Production LangGraph orchestrator executing the end-to-end multi-agent diagnostic cycle."""

    def __init__(
        self,
        retriever: Optional[HybridRetriever] = None,
        knowledge_base_dir: Optional[Path] = None,
        grounding_threshold: float = 0.95,
        max_revisions: int = 2,
        memory_coordinator: Optional[Any] = None,
    ) -> None:
        self.grounding_threshold = grounding_threshold
        self.max_revisions = max_revisions
        self.memory_coordinator = memory_coordinator

        # Initialize specialist agent nodes
        self.supervisor = SupervisorAgent(max_revisions=max_revisions)
        self.statistician = StatisticianAgent()
        self.retriever = RetrieverAgent(
            retriever=retriever,
            knowledge_base_dir=knowledge_base_dir,
            memory_coordinator=memory_coordinator,
        )
        self.investigator = InvestigatorAgent()
        self.validator = ValidatorAgent(
            grounding_threshold=grounding_threshold, max_revisions=max_revisions
        )
        self.action_agent = ActionAgent()

        # Build and compile LangGraph
        self.graph = self._build_graph()

    def _should_continue_after_triage(self, state: AgentState) -> str:
        """Route to retriever if active anomalies exist, else exit to END."""
        if state.status == IncidentStatus.RESOLVED or not state.raw_signals:
            return "end"
        return "retriever"

    def _should_revise_or_act(self, state: AgentState) -> str:
        """Route back to investigator if ungrounded and within revision budget, else action agent."""
        if not state.is_grounded and state.revision_count < self.max_revisions:
            return "investigator"
        return "action_agent"

    def _should_gate_approval(self, state: AgentState) -> str:
        """Route to human approval gate if required and unapproved, else finish."""
        if state.requires_human_approval and not state.is_approved:
            return "approval_gate"
        return "end"

    def _build_graph(self):
        """Construct LangGraph StateGraph topology with conditional looping and safety gates."""
        builder = StateGraph(AgentState)

        # 1. Register Nodes
        builder.add_node("statistician", self.statistician.execute)
        builder.add_node("retriever", self.retriever.execute)
        builder.add_node("investigator", self.investigator.execute)
        builder.add_node("validator", self.validator.execute)
        builder.add_node("action_agent", self.action_agent.execute)
        builder.add_node("approval_gate", human_approval_gate_node)

        # 2. Add Edges & Conditional Flows
        builder.add_edge(START, "statistician")

        # Triage conditional exit
        builder.add_conditional_edges(
            "statistician",
            self._should_continue_after_triage,
            {
                "retriever": "retriever",
                "end": END,
            },
        )

        builder.add_edge("retriever", "investigator")
        builder.add_edge("investigator", "validator")

        # Validation feedback loop edge
        builder.add_conditional_edges(
            "validator",
            self._should_revise_or_act,
            {
                "investigator": "investigator",
                "action_agent": "action_agent",
            },
        )

        # Action execution vs Human Gate edge
        builder.add_conditional_edges(
            "action_agent",
            self._should_gate_approval,
            {
                "approval_gate": "approval_gate",
                "end": END,
            },
        )

        builder.add_edge("approval_gate", END)

        return builder.compile()

    def run(self, initial_state: AgentState) -> AgentState:
        """Execute the multi-agent graph from an initial state and return the updated AgentState."""
        if self.memory_coordinator:
            self.memory_coordinator.checkpoint_active_investigation(initial_state)

        res_dict = self.graph.invoke(initial_state)
        result_state = AgentState(**res_dict)

        if self.memory_coordinator:
            if result_state.status in [IncidentStatus.RESOLVED, IncidentStatus.REMEDIATION_EXECUTED]:
                self.memory_coordinator.finalize_incident(result_state)
            else:
                self.memory_coordinator.checkpoint_active_investigation(result_state)

        return result_state

    def approve_and_execute(
        self, state: AgentState, approval_token: str
    ) -> AgentState:
        """Process operator approval and execute simulated remediation with verified rollback plan."""
        if state.status != IncidentStatus.HUMAN_APPROVAL_PENDING:
            raise ValueError(
                f"Incident '{state.incident_id}' is in status '{state.status.value}', not awaiting approval."
            )

        if not state.approval_token or state.approval_token != approval_token:
            raise ValueError(
                f"Invalid approval token '{approval_token}'. Expected '{state.approval_token}'."
            )

        # Update state to approved
        approved_state = state.model_copy(
            update={
                "is_approved": True,
                "status": IncidentStatus.REMEDIATION_PROPOSED,
            }
        )

        # Execute simulated action
        action_update = self.action_agent.execute(approved_state)
        final_dict = approved_state.model_dump()
        final_dict.update(action_update)

        audit_entry = {
            "agent": "approval_gate",
            "action": "HUMAN_OPERATOR_APPROVED",
            "approval_token": approval_token,
            "status": final_dict["status"],
        }
        final_dict["audit_log"].append(audit_entry)

        final_state = AgentState(**final_dict)
        if self.memory_coordinator:
            self.memory_coordinator.finalize_incident(final_state)

        return final_state

    def export_mermaid_diagram(self) -> str:
        """Export Mermaid diagram string for visualization."""
        return self.graph.get_graph().draw_mermaid()
