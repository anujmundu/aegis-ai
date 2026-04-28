"""Unit Tests for LangGraph Multi-Agent Reliability Pipeline (Phase 5).

Covers:
- StatisticianAgent: Quantitative multi-tier triage & primary driver isolation
- RetrieverAgent: Diagnostic query formulation & Hybrid RRF RAG citation extraction
- InvestigatorAgent: Multi-tier causal sequencing & reasoning trace synthesis
- ValidatorAgent: Anti-hallucination verification & Grounding Score SLA (>= 0.95)
- ActionAgent: SOP matching, dry-run simulation, and human approval safety gate
- SupervisorAgent: Lifecycle state machine routing and revision budget loop
- ReliabilityGraph: Full end-to-end LangGraph execution, approval verification, and Mermaid export
"""

import pytest

from ai.agents.action import ActionAgent
from ai.agents.graph import ReliabilityGraph
from ai.agents.investigator import InvestigatorAgent
from ai.agents.retriever import RetrieverAgent
from ai.agents.state import AgentState
from ai.agents.statistician import StatisticianAgent
from ai.agents.supervisor import SupervisorAgent
from ai.agents.validator import ValidatorAgent
from data.schemas.events import AnomalySignal, IncidentSeverity, IncidentStatus


@pytest.fixture
def db_pool_signal() -> AnomalySignal:
    return AnomalySignal(
        signal_id="sig-db-1",
        service_id="checkout-service",
        metric_name="db_connection_pool_active_connections",
        detector_type="modified_z_score",
        observed_value=96.0,
        baseline_value=40.0,
        deviation_sigma=5.8,
        severity=IncidentSeverity.CRITICAL,
        is_anomaly=True,
        is_primary_driver=True,
    )


@pytest.fixture
def http_5xx_signal() -> AnomalySignal:
    return AnomalySignal(
        signal_id="sig-app-1",
        service_id="checkout-service",
        metric_name="app_http_error_rate_5xx",
        detector_type="z_score",
        observed_value=0.18,
        baseline_value=0.002,
        deviation_sigma=4.9,
        severity=IncidentSeverity.HIGH,
        is_anomaly=True,
        is_primary_driver=False,
    )


@pytest.fixture
def memory_signal() -> AnomalySignal:
    return AnomalySignal(
        signal_id="sig-mem-1",
        service_id="payment-service",
        metric_name="infra_memory_percent",
        detector_type="ewma",
        observed_value=91.5,
        baseline_value=55.0,
        deviation_sigma=6.1,
        severity=IncidentSeverity.HIGH,
        is_anomaly=True,
        is_primary_driver=True,
    )


class TestStatisticianAgent:
    """Tests for StatisticianAgent triage and driver isolation."""

    def test_nominal_telemetry_triage(self):
        agent = StatisticianAgent()
        state = AgentState(
            incident_id="INC-001",
            service_id="checkout-service",
            raw_signals=[],
        )
        update = agent.execute(state)
        assert update["status"] == IncidentStatus.RESOLVED
        assert "nominal" in update["statistical_summary"].lower()

    def test_primary_driver_isolation(self, db_pool_signal, http_5xx_signal):
        agent = StatisticianAgent()
        state = AgentState(
            incident_id="INC-002",
            service_id="checkout-service",
            raw_signals=[http_5xx_signal, db_pool_signal],
        )
        update = agent.execute(state)
        assert update["status"] == IncidentStatus.INVESTIGATING
        assert update["primary_driver"].metric_name == "db_connection_pool_active_connections"
        assert len(update["correlated_signal_names"]) == 2
        assert "PRIMARY DRIVER" in update["statistical_summary"]
        assert "DB Tier" in update["statistical_summary"]
        assert "APP Tier" in update["statistical_summary"]


class TestRetrieverAgent:
    """Tests for RetrieverAgent diagnostic query and citation retrieval."""

    def test_retrieve_citations(self, db_pool_signal):
        agent = RetrieverAgent()
        state = AgentState(
            incident_id="INC-003",
            service_id="checkout-service",
            primary_driver=db_pool_signal,
            classifier_archetype="DB_CONNECTION_POOL_SATURATION",
        )
        update = agent.execute(state)
        assert len(update["retrieved_evidence"]) > 0
        assert len(update["citations"]) > 0
        top_citation = update["citations"][0]
        assert "citation" in top_citation
        assert "chunk_id" in top_citation
        assert "rb_db_pool_exhaustion" in top_citation["citation"] or "pm_2026_03" in top_citation["citation"]


class TestInvestigatorAgent:
    """Tests for InvestigatorAgent causal hypothesis synthesis."""

    def test_db_pool_causal_synthesis(self, db_pool_signal):
        agent = InvestigatorAgent()
        state = AgentState(
            incident_id="INC-004",
            service_id="checkout-service",
            primary_driver=db_pool_signal,
            classifier_archetype="DB_CONNECTION_POOL_SATURATION",
            classifier_confidence=0.97,
            citations=[{"citation": "[RB-DB-001: Pool SOP]"}],
        )
        update = agent.execute(state)
        assert update["status"] == IncidentStatus.ROOT_CAUSE_IDENTIFIED
        assert "connection pool" in update["root_cause_hypothesis"].lower()
        assert len(update["reasoning_trace"]) >= 3
        assert update["confidence_score"] >= 0.90

    def test_memory_leak_causal_synthesis(self, memory_signal):
        agent = InvestigatorAgent()
        state = AgentState(
            incident_id="INC-005",
            service_id="payment-service",
            primary_driver=memory_signal,
            classifier_archetype="MEMORY_LEAK_GC_PAUSE",
            classifier_confidence=0.95,
            citations=[{"citation": "[RB-MEM-002: GC SOP]"}],
        )
        update = agent.execute(state)
        assert "memory" in update["root_cause_hypothesis"].lower()
        assert "garbage collection" in update["root_cause_hypothesis"].lower()


class TestValidatorAgent:
    """Tests for ValidatorAgent anti-hallucination verification."""

    def test_grounded_hypothesis_passes_sla(self, db_pool_signal):
        agent = ValidatorAgent(grounding_threshold=0.95)
        citation_str = "[RB-DB-001: DB Pool SOP]"
        state = AgentState(
            incident_id="INC-006",
            service_id="checkout-service",
            primary_driver=db_pool_signal,
            classifier_archetype="DB_CONNECTION_POOL_SATURATION",
            citations=[{"citation": citation_str}],
            root_cause_hypothesis=(
                f"PostgreSQL connection pool saturated in checkout-service. "
                f"Causal mechanism conforms to {citation_str}."
            ),
            reasoning_trace=[
                "Primary metric db_connection_pool_active_connections observed at 96.0.",
                "Corroborates DB_CONNECTION_POOL_SATURATION archetype.",
            ],
        )
        update = agent.execute(state)
        assert update["is_grounded"] is True
        assert update["grounding_score"] >= 0.95
        assert update["validation_feedback"] is None

    def test_ungrounded_hallucination_fails_and_requests_revision(self, db_pool_signal):
        agent = ValidatorAgent(grounding_threshold=0.95)
        # Hypothesis completely ignores the service, metric, citation, and archetype
        state = AgentState(
            incident_id="INC-007",
            service_id="checkout-service",
            primary_driver=db_pool_signal,
            classifier_archetype="DB_CONNECTION_POOL_SATURATION",
            citations=[{"citation": "[RB-DB-001: Pool SOP]"}],
            root_cause_hypothesis="DNS servers in billing-service went down due to solar flares.",
            reasoning_trace=["External internet routing issue."],
            revision_count=0,
        )
        update = agent.execute(state)
        assert update["is_grounded"] is False
        assert update["grounding_score"] < 0.95
        assert update["revision_count"] == 1
        assert update["validation_feedback"] is not None
        assert "Grounding score" in update["validation_feedback"]


class TestActionAgent:
    """Tests for ActionAgent SOP mapping and safety gate."""

    def test_high_risk_requires_human_approval(self, db_pool_signal):
        agent = ActionAgent()
        state = AgentState(
            incident_id="INC-008",
            service_id="checkout-service",
            severity=IncidentSeverity.CRITICAL,
            primary_driver=db_pool_signal,
            classifier_archetype="DB_CONNECTION_POOL_SATURATION",
        )
        update = agent.execute(state)
        proposal = update["remediation_proposal"]
        assert proposal.action_type == "EXPAND_DB_CONNECTION_POOL"
        assert proposal.dry_run_simulation is True
        assert proposal.risk_level == "HIGH"
        assert update["requires_human_approval"] is True
        assert update["status"] == IncidentStatus.HUMAN_APPROVAL_PENDING
        assert update["approval_token"].startswith("APPR-")

    def test_pre_approved_action_executes_simulation(self, db_pool_signal):
        agent = ActionAgent()
        state = AgentState(
            incident_id="INC-009",
            service_id="checkout-service",
            severity=IncidentSeverity.HIGH,
            primary_driver=db_pool_signal,
            classifier_archetype="DB_CONNECTION_POOL_SATURATION",
            is_approved=True,
            approval_token="APPR-TEST-1234",
        )
        update = agent.execute(state)
        assert update["status"] == IncidentStatus.REMEDIATION_EXECUTED
        assert "SIMULATION_SUCCESS" in update["execution_result"]


class TestSupervisorAgent:
    """Tests for SupervisorAgent lifecycle state routing."""

    def test_routing_decisions(self, db_pool_signal):
        sup = SupervisorAgent()

        # Step 1: Needs triage
        s1 = AgentState(incident_id="1", service_id="svc", raw_signals=[db_pool_signal])
        assert sup.decide_next_node(s1) == "statistician"

        # Step 2: Needs retriever
        s2 = s1.model_copy(update={"primary_driver": db_pool_signal})
        assert sup.decide_next_node(s2) == "retriever"

        # Step 3: Needs investigator
        s3 = s2.model_copy(update={"citations": [{"citation": "c1"}]})
        assert sup.decide_next_node(s3) == "investigator"

        # Step 4: Needs initial validator
        s4 = s3.model_copy(update={"root_cause_hypothesis": "cause"})
        assert sup.decide_next_node(s4) == "validator"

        # Step 5: Loops back if ungrounded and revisions < 2
        s5 = s4.model_copy(update={"is_grounded": False, "validation_feedback": "err", "revision_count": 1})
        assert sup.decide_next_node(s5) == "investigator"

        # Step 6: Advances to action agent once grounded
        s6 = s4.model_copy(update={"is_grounded": True})
        assert sup.decide_next_node(s6) == "action_agent"


class TestReliabilityGraph:
    """End-to-End integration tests for the LangGraph reliability graph."""

    def test_e2e_db_pool_incident_flow(self, db_pool_signal, http_5xx_signal):
        rg = ReliabilityGraph()
        initial_state = AgentState(
            incident_id="INC-E2E-001",
            service_id="checkout-service",
            severity=IncidentSeverity.CRITICAL,
            raw_signals=[db_pool_signal, http_5xx_signal],
            classifier_archetype="DB_CONNECTION_POOL_SATURATION",
            classifier_confidence=0.99,
        )

        # 1. Run graph until human approval checkpoint
        paused_state = rg.run(initial_state)
        assert paused_state.status == IncidentStatus.HUMAN_APPROVAL_PENDING
        assert paused_state.is_grounded is True
        assert paused_state.grounding_score >= 0.95
        assert paused_state.approval_token is not None
        assert paused_state.remediation_proposal.action_type == "EXPAND_DB_CONNECTION_POOL"
        assert len(paused_state.audit_log) >= 5

        # 2. Rejection with invalid token raises ValueError
        with pytest.raises(ValueError, match="Invalid approval token"):
            rg.approve_and_execute(paused_state, "APPR-INVALID-TOKEN")

        # 3. Successful operator approval & simulated execution
        final_state = rg.approve_and_execute(paused_state, paused_state.approval_token)
        assert final_state.status == IncidentStatus.REMEDIATION_EXECUTED
        assert final_state.is_approved is True
        assert "SIMULATION_SUCCESS" in final_state.execution_result

    def test_e2e_nominal_telemetry_flow(self):
        rg = ReliabilityGraph()
        nom_state = AgentState(
            incident_id="INC-E2E-NOMINAL",
            service_id="user-service",
            severity=IncidentSeverity.INFO,
            raw_signals=[],
        )
        result = rg.run(nom_state)
        assert result.status == IncidentStatus.RESOLVED
        assert result.primary_driver is None
        assert result.remediation_proposal is None

    def test_mermaid_export(self):
        rg = ReliabilityGraph()
        mermaid = rg.export_mermaid_diagram()
        assert "graph TD" in mermaid
        assert "statistician" in mermaid
        assert "retriever" in mermaid
        assert "investigator" in mermaid
        assert "validator" in mermaid
        assert "action_agent" in mermaid
