"""Unit and Integration Tests for Observability, Metrics & Grafana Dashboards (Phase 10).

Covers:
- Prometheus metrics registry and custom collectors (HTTP, Anomaly, Inference, RAG, Memory)
- Automated FastAPI ObservabilityMiddleware instrumentation and response headers
- Prometheus alerting rules syntax and threshold assertions
- Grafana dashboard schemas and PromQL query targets
"""

import json
from pathlib import Path

import pytest
import yaml
from starlette.testclient import TestClient

from apps.api.main import create_app
from apps.api.metrics import (
    get_prometheus_metrics,
    set_subsystem_health,
    track_agent_step,
    track_anomaly_detection,
    track_http_request,
    track_model_inference,
    track_rag_grounding,
    track_remediation_action,
    track_snapshot_ingested,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class TestPrometheusMetricsRegistry:
    """Validates the central Prometheus metrics registry and collection functions."""

    def test_metrics_instrumentation_helpers(self):
        # 1. HTTP Request
        track_http_request("POST", "/v1/test", 200, 0.012)

        # 2. Telemetry Ingestion
        track_snapshot_ingested("checkout-service", True)

        # 3. Anomaly Detection
        track_anomaly_detection("checkout-service", "z_score", "CRITICAL", 0.0025)

        # 4. Model Inference
        track_model_inference("DB_CONNECTION_POOL_SATURATION", 0.985, 0.0014)

        # 5. Agent Node Step
        track_agent_step("investigator", "SUCCESS", 0.045)

        # 6. RAG Grounding & Citations
        track_rag_grounding("checkout-service", 0.975, 4, "runbook")

        # 7. Remediation Action
        track_remediation_action("EXPAND_DB_CONNECTION_POOL", "PROPOSED")

        # 8. Subsystem Health
        set_subsystem_health("statistical_engine", True)

        # Serialize
        metrics_bytes = get_prometheus_metrics()
        metrics_text = metrics_bytes.decode("utf-8")

        assert "aegisai_http_requests_total" in metrics_text
        assert "aegisai_telemetry_snapshots_ingested_total" in metrics_text
        assert "aegisai_anomaly_detections_total" in metrics_text
        assert "aegisai_detection_latency_seconds" in metrics_text
        assert "aegisai_model_prediction_confidence" in metrics_text
        assert "aegisai_agent_executions_total" in metrics_text
        assert "aegisai_rag_grounding_score" in metrics_text
        assert "aegisai_remediation_actions_total" in metrics_text
        assert "aegisai_subsystem_health" in metrics_text
        assert "aegisai_service_uptime_seconds" in metrics_text


class TestObservabilityMiddlewareIntegration:
    """Validates HTTP request tracing and middleware headers."""

    @pytest.fixture(scope="class")
    @classmethod
    def client(cls):
        app = create_app()
        return TestClient(app)

    def test_observability_headers_and_metrics_scrape(self, client: TestClient):
        # Make request to health endpoint
        res = client.get("/v1/health")
        assert res.status_code == 200
        assert "X-Response-Time" in res.headers
        assert "X-Trace-ID" in res.headers
        assert "ms" in res.headers["X-Response-Time"]

        # Scrape /metrics endpoint
        metrics_res = client.get("/metrics")
        assert metrics_res.status_code == 200
        assert "text/plain" in metrics_res.headers["content-type"]
        text = metrics_res.text
        assert "aegisai_service_uptime_seconds" in text
        assert "aegisai_subsystem_health" in text


class TestPrometheusAlertRules:
    """Validates Prometheus alerting rules definition."""

    @pytest.fixture
    def alerts_data(self) -> dict:
        alerts_path = PROJECT_ROOT / "infrastructure" / "docker" / "prometheus" / "alerts.yml"
        assert alerts_path.exists(), "infrastructure/docker/prometheus/alerts.yml missing"
        with open(alerts_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def test_alert_rules_structure(self, alerts_data: dict):
        assert "groups" in alerts_data
        group = alerts_data["groups"][0]
        assert group["name"] == "aegisai_reliability_alerts"
        rules = group["rules"]
        assert len(rules) >= 4

        alert_names = [r["alert"] for r in rules]
        assert "HighAnomalyDetectionLatencySLA" in alert_names
        assert "ElevatedAnomalyRate" in alert_names
        assert "DegradedSubsystemHealth" in alert_names
        assert "LowRAGGroundingScore" in alert_names

        for r in rules:
            assert "expr" in r
            assert "for" in r
            assert "labels" in r
            assert "annotations" in r


class TestGrafanaDashboards:
    """Validates Grafana dashboard JSON models."""

    @pytest.mark.parametrize(
        "dashboard_filename,expected_uid",
        [
            ("sre_operational_overview.json", "aegis-sre-overview"),
            ("ai_model_observability.json", "aegis-model-observability"),
        ],
    )
    def test_dashboard_json_schema(self, dashboard_filename: str, expected_uid: str):
        dash_path = (
            PROJECT_ROOT
            / "infrastructure"
            / "docker"
            / "grafana"
            / "dashboards"
            / dashboard_filename
        )
        assert dash_path.exists(), f"Missing dashboard {dashboard_filename}"
        with open(dash_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert data["uid"] == expected_uid
        assert "title" in data
        assert "panels" in data
        assert len(data["panels"]) >= 4

        # Verify panels have targets with PromQL expressions
        for panel in data["panels"]:
            if panel.get("type") not in ("row", None):
                targets = panel.get("targets", [])
                assert len(targets) > 0, f"Panel {panel.get('title')} has no metrics targets"
                for t in targets:
                    assert "expr" in t, f"Target in {panel.get('title')} missing PromQL expression"
