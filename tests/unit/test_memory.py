"""Unit & Integration Tests for 3-Tier Stateful Operational Memory (Phase 6).

Covers:
- Tier 1: WorkingMemory (active investigation caching, TTL, approval locks)
- Tier 2: EpisodicMemory (relational incident archiving, signals, evidence, similarity search)
- Tier 3: SemanticMemory (dense TF-IDF vector embeddings, postmortem search, metadata filtering)
- OperationalMemoryCoordinator: Unified memory interface & postmortem bootstrapping
- Full Graph Integration: Memory recall and automatic archiving during incident lifecycle
"""

import time

import pytest

from ai.agents.graph import ReliabilityGraph
from ai.agents.state import AgentState
from ai.memory.coordinator import OperationalMemoryCoordinator
from ai.memory.episodic import EpisodicMemory
from ai.memory.semantic import SemanticMemory
from ai.memory.working import InMemoryWorkingStore, WorkingMemory
from data.schemas.events import (
    AnomalySignal,
    IncidentSeverity,
    IncidentStatus,
    RemediationProposal,
)


@pytest.fixture
def sample_signal() -> AnomalySignal:
    return AnomalySignal(
        signal_id="sig-test-1",
        service_id="checkout-service",
        metric_name="db_connection_pool_active_connections",
        detector_type="modified_z_score",
        observed_value=95.0,
        baseline_value=40.0,
        deviation_sigma=5.5,
        severity=IncidentSeverity.CRITICAL,
        is_anomaly=True,
        is_primary_driver=True,
    )


@pytest.fixture
def sample_state(sample_signal) -> AgentState:
    proposal = RemediationProposal(
        incident_id="INC-MEM-001",
        action_type="EXPAND_DB_CONNECTION_POOL",
        target_resource="checkout-service/aurora-postgres-pool",
        parameters={"max_connections": "250"},
        risk_level="HIGH",
        requires_human_approval=True,
        dry_run_simulation=True,
        justification="Test justification",
    )
    return AgentState(
        incident_id="INC-MEM-001",
        service_id="checkout-service",
        severity=IncidentSeverity.CRITICAL,
        status=IncidentStatus.HUMAN_APPROVAL_PENDING,
        raw_signals=[sample_signal],
        primary_driver=sample_signal,
        classifier_archetype="DB_CONNECTION_POOL_SATURATION",
        classifier_confidence=0.98,
        root_cause_hypothesis="PostgreSQL connection pool exhausted in checkout-service.",
        reasoning_trace=["Observed pool at 95%", "Caused client timeout cascading"],
        confidence_score=0.96,
        is_grounded=True,
        grounding_score=1.0,
        citations=[{"citation": "[RB-DB-001: Pool Saturation SOP]"}],
        remediation_proposal=proposal,
        approval_token="APPR-MEM-TEST",
        execution_result="DRY_RUN_PASSED",
    )


class TestWorkingMemory:
    """Tests for Tier 1 Working Memory."""

    def test_in_memory_store_set_get_ttl(self):
        store = InMemoryWorkingStore()
        store.set("key1", {"data": "test"}, ttl_seconds=1)
        assert store.get("key1") == {"data": "test"}

        # Wait for expiration
        time.sleep(1.05)
        assert store.get("key1") is None

    def test_working_memory_state_lifecycle(self, sample_state):
        wm = WorkingMemory()
        wm.set_state(sample_state)

        fetched = wm.get_state(sample_state.incident_id)
        assert fetched is not None
        assert fetched.incident_id == sample_state.incident_id
        assert fetched.service_id == "checkout-service"
        assert fetched.primary_driver.metric_name == "db_connection_pool_active_connections"

        # Update patch
        patched = wm.update_state_patch(sample_state.incident_id, {"is_approved": True})
        assert patched is not None
        assert patched.is_approved is True

        # List keys
        keys = wm.list_active_incident_ids()
        assert sample_state.incident_id in keys

        # Delete
        assert wm.delete_state(sample_state.incident_id) is True
        assert wm.get_state(sample_state.incident_id) is None

    def test_approval_lock_concurrency(self):
        wm = WorkingMemory()
        inc_id = "INC-LOCK-001"
        token_a = "TOKEN-A"
        token_b = "TOKEN-B"

        # Operator A acquires lock
        assert wm.acquire_approval_lock(inc_id, token_a, ttl_seconds=60) is True

        # Operator B attempts to acquire same lock
        assert wm.acquire_approval_lock(inc_id, token_b, ttl_seconds=60) is False

        # Operator B attempts to release Operator A's lock
        assert wm.verify_and_release_lock(inc_id, token_b) is False

        # Operator A successfully releases lock
        assert wm.verify_and_release_lock(inc_id, token_a) is True

        # Now Operator B can acquire
        assert wm.acquire_approval_lock(inc_id, token_b, ttl_seconds=60) is True


class TestEpisodicMemory:
    """Tests for Tier 2 Episodic Relational Memory."""

    def test_record_and_retrieve_incident(self, sample_state):
        em = EpisodicMemory()  # In-memory SQLite
        inc_id = em.record_incident(sample_state, postmortem_md="## Sample Postmortem")
        assert inc_id == sample_state.incident_id

        record = em.get_incident(inc_id)
        assert record is not None
        assert record["id"] == sample_state.incident_id
        assert record["service_id"] == "checkout-service"
        assert record["primary_driver_metric"] == "db_connection_pool_active_connections"
        assert len(record["signals"]) == 1
        assert len(record["evidence"]) == 1
        assert len(record["remediations"]) == 1
        assert record["remediations"][0]["action_type"] == "EXPAND_DB_CONNECTION_POOL"

    def test_find_similar_incidents(self, sample_state):
        em = EpisodicMemory()
        em.record_incident(sample_state)

        # Query similar by service and primary metric
        matches = em.find_similar_incidents(
            service_id="checkout-service",
            primary_metric="db_connection_pool_active_connections",
        )
        assert len(matches) == 1
        assert matches[0]["id"] == sample_state.incident_id
        assert matches[0]["applied_remediation"]["action_type"] == "EXPAND_DB_CONNECTION_POOL"

        # Query non-matching metric returns empty
        no_matches = em.find_similar_incidents(
            service_id="checkout-service",
            primary_metric="infra_memory_percent",
        )
        assert len(no_matches) == 0


class TestSemanticMemory:
    """Tests for Tier 3 Semantic Vector Memory."""

    def test_semantic_search_and_relevance(self):
        sm = SemanticMemory()
        sm.add_entry(
            incident_id="INC-P1",
            service_id="checkout-service",
            title="Postmortem: Aurora Connection Pool Exhaustion",
            content="PostgreSQL connections leaked on coupon checkout path hitting 100% capacity.",
            tags=["postgres", "connection_pool", "database"],
        )
        sm.add_entry(
            incident_id="P2",
            service_id="payment-service",
            title="Postmortem: Heap Memory Leak",
            content="Unbounded cache growth triggered frequent Full GC pauses and high p99 latency.",
            tags=["memory", "jvm", "gc_pause"],
        )

        # Semantic query for database saturation
        db_results = sm.search("PostgreSQL connection starvation database pool", top_k=2)
        assert len(db_results) > 0
        assert db_results[0].entry.incident_id == "INC-P1"
        assert db_results[0].similarity_score > 0.3

        # Semantic query with service filter
        filtered = sm.search("memory leak pause", service_filter="payment-service")
        assert len(filtered) == 1
        assert filtered[0].entry.service_id == "payment-service"


class TestOperationalMemoryCoordinator:
    """Tests for unified Memory Coordinator and postmortem bootstrapping."""

    def test_bootstrap_and_recall_experience(self):
        coordinator = OperationalMemoryCoordinator(auto_bootstrap=True)

        # Verify bootstrapping loaded postmortems
        assert len(coordinator.semantic.entries) >= 3

        # Experience recall for checkout-service
        context = coordinator.recall_experience(
            service_id="checkout-service",
            primary_driver_metric="db_connection_pool_active_connections",
            diagnostic_query="checkout PostgreSQL aurora connection pool max limit",
        )

        assert context.service_id == "checkout-service"
        assert context.formatted_summary != ""
        assert "Institutional Memory Recall" in context.formatted_summary
        assert len(context.semantic_matches) > 0
        assert "Aurora PostgreSQL Connection Pool" in context.semantic_matches[0].entry.title

    def test_lifecycle_checkpoint_and_finalize(self, sample_state):
        coordinator = OperationalMemoryCoordinator(auto_bootstrap=False)

        # Checkpoint to working memory
        coordinator.checkpoint_active_investigation(sample_state)
        active = coordinator.get_active_investigation(sample_state.incident_id)
        assert active is not None
        assert active.incident_id == sample_state.incident_id

        # Finalize incident
        coordinator.finalize_incident(sample_state, postmortem_md="# Postmortem Finalized")

        # Working memory should be evicted
        assert coordinator.get_active_investigation(sample_state.incident_id) is None

        # Episodic and Semantic memory should contain the record
        episodic_rec = coordinator.episodic.get_incident(sample_state.incident_id)
        assert episodic_rec is not None
        assert episodic_rec["postmortem_markdown"] == "# Postmortem Finalized"

        matches = coordinator.semantic.search("PostgreSQL connection pool exhausted")
        assert len(matches) > 0
        assert matches[0].entry.incident_id == sample_state.incident_id


class TestReliabilityGraphMemoryIntegration:
    """Integration test: ReliabilityGraph with OperationalMemoryCoordinator."""

    def test_e2e_graph_with_memory_recall_and_archival(self, sample_signal):
        coordinator = OperationalMemoryCoordinator(auto_bootstrap=True)
        rg = ReliabilityGraph(memory_coordinator=coordinator)

        initial_state = AgentState(
            incident_id="INC-E2E-MEM-001",
            service_id="checkout-service",
            severity=IncidentSeverity.CRITICAL,
            raw_signals=[sample_signal],
            classifier_archetype="DB_CONNECTION_POOL_SATURATION",
        )

        # 1. Run graph: Should pull historical context and pause at approval gate
        paused_state = rg.run(initial_state)
        assert paused_state.status == IncidentStatus.HUMAN_APPROVAL_PENDING
        assert paused_state.historical_context is not None
        assert "Institutional Memory Recall" in paused_state.historical_context

        # Investigator reasoning trace should corroborate memory
        assert any("[Institutional Memory 4]" in step for step in paused_state.reasoning_trace)

        # Check that working memory holds active paused investigation
        in_flight = coordinator.get_active_investigation(initial_state.incident_id)
        assert in_flight is not None

        # 2. Operator approves with token
        final_state = rg.approve_and_execute(paused_state, paused_state.approval_token)
        assert final_state.status == IncidentStatus.REMEDIATION_EXECUTED

        # Working memory should be evicted and archived to Episodic & Semantic memories
        assert coordinator.get_active_investigation(initial_state.incident_id) is None
        archived = coordinator.episodic.get_incident(initial_state.incident_id)
        assert archived is not None
        assert archived["status"] == IncidentStatus.REMEDIATION_EXECUTED.value
