"""Unit and Integration Tests for AegisAI FastAPI Production Microservice (Phase 7).

Covers:
- Root, Health & Prometheus Metrics endpoints
- Request Timing & Correlation ID Middleware
- Real-Time Telemetry Ingestion & Data Contract Firewall
- Batch Ingestion & Streaming Anomaly Evaluation
- Multi-Model ML Anomaly Inference & Classification (/v1/detect)
- Hybrid RAG Knowledge Retrieval (/v1/knowledge/query)
- LangGraph Multi-Agent Incident Triage & Working Memory Checkpointing
- Human-in-the-Loop Operator Approval Webhook & Archival to Episodic Memory
"""

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from data.schemas.events import AnomalyArchetype, AnomalySignal, IncidentSeverity
from data.synthetic.telemetry_generator import MultiTierTelemetryGenerator


@pytest.fixture(scope="module")
def client() -> TestClient:
    """Create a persistent FastAPI TestClient instance with pre-warmed lifespan."""
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def generator() -> MultiTierTelemetryGenerator:
    return MultiTierTelemetryGenerator(seed=123)


@pytest.fixture
def nominal_snapshot(generator):
    return generator.generate_snapshot(archetype=AnomalyArchetype.NOMINAL)


@pytest.fixture
def anomalous_snapshot(generator):
    return generator.generate_snapshot(archetype=AnomalyArchetype.DB_CONNECTION_POOL_SATURATION, progress=1.0)


class TestHealthAndObservability:
    """Tests for health, root, and metrics exposition endpoints."""

    def test_root_endpoint(self, client):
        res = client.get("/")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ONLINE"
        assert "/docs" in data["documentation"]

    def test_health_probes(self, client):
        for path in ["/health", "/v1/health"]:
            res = client.get(path)
            assert res.status_code == 200
            data = res.json()
            assert data["status"] == "healthy"
            assert data["subsystems"]["statistical_engine"] == "nominal"
            assert data["subsystems"]["ml_ensemble"] == "nominal"

    def test_prometheus_metrics(self, client):
        res = client.get("/metrics")
        assert res.status_code == 200
        assert "text/plain" in res.headers["content-type"]
        assert "aegisai_service_uptime_seconds" in res.text
        assert 'aegisai_subsystem_health{subsystem="statistical_engine"}' in res.text

    def test_correlation_id_and_timing_middleware(self, client):
        custom_id = "test-corr-id-999"
        res = client.get("/health", headers={"X-Correlation-ID": custom_id})
        assert res.status_code == 200
        assert res.headers.get("X-Correlation-ID") == custom_id
        assert "X-Process-Time-Ms" in res.headers


class TestTelemetryIngestion:
    """Tests for telemetry ingestion and data contract validation firewall."""

    def test_nominal_telemetry_ingest(self, client, nominal_snapshot):
        payload = nominal_snapshot.model_dump(mode="json")
        res = client.post("/v1/telemetry/ingest", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["is_anomalous"] is False
        assert data["triage_verdict"] == "NOMINAL"
        assert data["execution_time_ms"] < 25.0

    def test_anomalous_telemetry_ingest(self, client, anomalous_snapshot):
        payload = anomalous_snapshot.model_dump(mode="json")
        res = client.post("/v1/telemetry/ingest", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["is_anomalous"] is True
        assert data["triage_verdict"] == "ANOMALY_CONFIRMED"
        assert data["signals_count"] > 0
        assert data["primary_driver"] is not None

    def test_contract_violation_quarantine(self, client, nominal_snapshot):
        payload = nominal_snapshot.model_dump(mode="json")
        # Corrupt payload to violate Pydantic/contract validation (CPU > 100%)
        payload["infrastructure"]["cpu_percent"] = 150.0

        res = client.post("/v1/telemetry/ingest", json=payload)
        assert res.status_code == 422

    def test_batch_telemetry_ingest(self, client, generator):
        batch = generator.generate_batch(num_snapshots=15)
        payload = {"snapshots": [s.model_dump(mode="json") for s in batch]}

        res = client.post("/v1/telemetry/batch", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["total_ingested"] == 15
        assert "anomaly_rate_pct" in data


class TestMLDetectionInference:
    """Tests for /v1/detect multi-model ML ensemble."""

    def test_ml_detect_endpoint(self, client, anomalous_snapshot):
        payload = anomalous_snapshot.model_dump(mode="json")
        res = client.post("/v1/detect", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert "autoencoder_reconstruction_error" in data
        assert "isolation_forest_score" in data
        assert "predicted_archetype" in data
        assert "archetype_confidence" in data
        assert len(data["top_contributing_features"]) > 0
        assert data["inference_time_ms"] < 100.0


class TestKnowledgeAndRAG:
    """Tests for /v1/knowledge search endpoints."""

    def test_hybrid_knowledge_query(self, client):
        payload = {
            "query": "PostgreSQL connection pool max_connections saturation aurora",
            "service_id": "checkout-service",
            "top_k": 3,
        }
        res = client.post("/v1/knowledge/query", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["total_retrieved"] > 0
        top = data["citations"][0]
        assert "citation" in top
        assert "rerank_score" in top

    def test_semantic_memory_search(self, client):
        payload = {
            "query": "checkout connection leak transaction timeout",
            "service_id": "checkout-service",
            "top_k": 2,
        }
        res = client.post("/v1/knowledge/search-memory", json=payload)
        assert res.status_code == 200
        matches = res.json()
        assert len(matches) > 0
        assert "similarity_score" in matches[0]


class TestIncidentInvestigationAndApprovalFlow:
    """End-to-End tests for incident triage, working memory, and human approval webhook."""

    def test_e2e_incident_lifecycle(self, client):
        inc_id = "INC-API-TEST-001"
        sig = AnomalySignal(
            signal_id="sig-api-1",
            service_id="checkout-service",
            metric_name="db_connection_pool_active_connections",
            detector_type="modified_z_score",
            observed_value=97.0,
            baseline_value=42.0,
            deviation_sigma=6.0,
            severity=IncidentSeverity.CRITICAL,
            is_anomaly=True,
            is_primary_driver=True,
        )

        triage_payload = {
            "incident_id": inc_id,
            "service_id": "checkout-service",
            "severity": "CRITICAL",
            "raw_signals": [sig.model_dump(mode="json")],
            "classifier_archetype": "DB_CONNECTION_POOL_SATURATION",
            "classifier_confidence": 0.985,
        }

        # 1. Trigger Multi-Agent Triage
        res_triage = client.post("/v1/incidents/triage", json=triage_payload)
        assert res_triage.status_code == 200
        triage_data = res_triage.json()
        assert triage_data["status"] == "HUMAN_APPROVAL_PENDING"
        assert triage_data["is_grounded"] is True
        assert triage_data["grounding_score"] >= 0.95
        assert triage_data["requires_human_approval"] is True
        approval_token = triage_data["approval_token"]
        assert approval_token is not None

        # 2. Check active incidents list
        res_active = client.get("/v1/incidents/active")
        assert res_active.status_code == 200
        active_data = res_active.json()
        assert inc_id in active_data["active_incident_ids"]

        # 3. Fetch active state from working memory
        res_get = client.get(f"/v1/incidents/{inc_id}")
        assert res_get.status_code == 200
        state_data = res_get.json()
        assert state_data["memory_tier"] == "TIER_1_WORKING_MEMORY"

        # 4. Attempt approval with invalid token (should return 403)
        res_bad_appr = client.post(
            f"/v1/incidents/{inc_id}/approve",
            json={"approval_token": "INVALID-TOKEN-999"},
        )
        assert res_bad_appr.status_code == 403

        # 5. Approve with valid token
        res_good_appr = client.post(
            f"/v1/incidents/{inc_id}/approve",
            json={
                "approval_token": approval_token,
                "operator_id": "sre-lead-alice",
                "notes": "Pool headroom verified on Aurora cluster.",
            },
        )
        assert res_good_appr.status_code == 200
        appr_data = res_good_appr.json()
        assert appr_data["status"] == "REMEDIATION_EXECUTED"
        assert appr_data["is_approved"] is True
        assert appr_data["action_type"] == "EXPAND_DB_CONNECTION_POOL"
        assert appr_data["approved_by"] == "sre-lead-alice"

        # 6. Verify evicted from working memory and archived to episodic memory
        res_archived = client.get(f"/v1/incidents/{inc_id}")
        assert res_archived.status_code == 200
        archived_data = res_archived.json()
        assert archived_data["memory_tier"] == "TIER_2_EPISODIC_MEMORY"

        # 7. Check incident history recall
        res_history = client.get(f"/v1/incidents/{inc_id}/history")
        assert res_history.status_code == 200
        hist_data = res_history.json()
        assert hist_data["service_id"] == "checkout-service"
        assert "Institutional Memory Recall" in hist_data["formatted_summary"]
