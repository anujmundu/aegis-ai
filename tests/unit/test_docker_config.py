"""Unit and Validation Tests for Multi-Container Docker Architecture (Phase 9).

Covers:
- Dockerfile syntax, multi-stage structure, security boundaries (non-root UID 10001)
- docker-compose.yml configuration, services, healthcheck definitions, volume bindings
- Prometheus configuration targets and scraping intervals
- Grafana auto-provisioning datasources, providers, and dashboard JSON schemas
- TelemetryStreamWorker payload generation and compatibility
"""

import json
from pathlib import Path

import pytest
import yaml

from apps.worker.telemetry_worker import TelemetryStreamWorker
from data.schemas.events import TelemetrySnapshot

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class TestDockerfileArchitecture:
    """Validates the multi-stage slim Dockerfile specification."""

    @pytest.fixture
    def dockerfile_content(self) -> str:
        dockerfile_path = PROJECT_ROOT / "Dockerfile"
        assert dockerfile_path.exists(), "Root Dockerfile does not exist"
        return dockerfile_path.read_text(encoding="utf-8")

    def test_multi_stage_structure(self, dockerfile_content: str):
        assert "AS builder" in dockerfile_content, "Missing builder stage"
        assert "AS runtime" in dockerfile_content, "Missing runtime stage"
        assert "python:3.11-slim-bookworm" in dockerfile_content

    def test_non_root_security_hardening(self, dockerfile_content: str):
        assert "10001" in dockerfile_content, "Missing non-root UID/GID 10001"
        assert "USER aegis" in dockerfile_content, "Container does not switch to non-root user aegis"

    def test_healthcheck_and_entrypoint(self, dockerfile_content: str):
        assert "HEALTHCHECK" in dockerfile_content, "Missing container HEALTHCHECK"
        assert "http://localhost:8000/v1/health" in dockerfile_content
        assert "ENTRYPOINT" in dockerfile_content

        entrypoint_path = PROJECT_ROOT / "infrastructure" / "docker" / "entrypoint.sh"
        assert entrypoint_path.exists(), "infrastructure/docker/entrypoint.sh does not exist"
        entry_text = entrypoint_path.read_text(encoding="utf-8")
        assert "exec \"$@\"" in entry_text, "Entrypoint must hand execution over via exec"


class TestDockerComposeArchitecture:
    """Validates docker-compose.yml configuration and service mesh."""

    @pytest.fixture
    def compose_dict(self) -> dict:
        compose_path = PROJECT_ROOT / "docker-compose.yml"
        assert compose_path.exists(), "docker-compose.yml does not exist"
        with open(compose_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def test_service_topology(self, compose_dict: dict):
        services = compose_dict.get("services", {})
        expected_services = [
            "aegis-api",
            "aegis-worker",
            "postgres",
            "redis",
            "mlflow",
            "prometheus",
            "grafana",
        ]
        for s in expected_services:
            assert s in services, f"Missing required service: {s}"

    def test_service_dependencies_and_healthchecks(self, compose_dict: dict):
        services = compose_dict["services"]

        # aegis-api must depend on postgres and redis being healthy
        api_deps = services["aegis-api"]["depends_on"]
        assert "postgres" in api_deps
        assert api_deps["postgres"]["condition"] == "service_healthy"
        assert "redis" in api_deps
        assert api_deps["redis"]["condition"] == "service_healthy"

        # grafana must depend on prometheus
        grafana_deps = services["grafana"]["depends_on"]
        assert "prometheus" in grafana_deps
        assert grafana_deps["prometheus"]["condition"] == "service_healthy"

        # All key infrastructure services must define healthchecks
        for svc_name in ["aegis-api", "postgres", "redis", "mlflow", "prometheus", "grafana"]:
            assert "healthcheck" in services[svc_name], f"Service {svc_name} missing healthcheck"

    def test_volume_and_network_isolation(self, compose_dict: dict):
        volumes = compose_dict.get("volumes", {})
        assert "postgres_data" in volumes
        assert "redis_data" in volumes
        assert "mlflow_data" in volumes
        assert "prometheus_data" in volumes
        assert "grafana_data" in volumes

        networks = compose_dict.get("networks", {})
        assert "aegis-network" in networks


class TestObservabilityProvisioning:
    """Validates Prometheus and Grafana configuration and dashboard schemas."""

    def test_prometheus_configuration(self):
        prom_path = PROJECT_ROOT / "infrastructure" / "docker" / "prometheus" / "prometheus.yml"
        assert prom_path.exists(), "prometheus.yml does not exist"
        with open(prom_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        assert "scrape_configs" in data
        job_names = [j["job_name"] for j in data["scrape_configs"]]
        assert "aegis-api" in job_names
        assert "prometheus" in job_names

    def test_grafana_datasource_and_dashboard_provisioning(self):
        ds_path = (
            PROJECT_ROOT
            / "infrastructure"
            / "docker"
            / "grafana"
            / "provisioning"
            / "datasources"
            / "datasource.yml"
        )
        assert ds_path.exists()
        with open(ds_path, "r", encoding="utf-8") as f:
            ds_data = yaml.safe_load(f)
        assert ds_data["datasources"][0]["type"] == "prometheus"
        assert "http://prometheus:9090" in ds_data["datasources"][0]["url"]

        dash_json_path = (
            PROJECT_ROOT
            / "infrastructure"
            / "docker"
            / "grafana"
            / "dashboards"
            / "aegis_reliability_dashboard.json"
        )
        assert dash_json_path.exists()
        with open(dash_json_path, "r", encoding="utf-8") as f:
            dash = json.load(f)

        assert "panels" in dash
        assert len(dash["panels"]) >= 4
        assert dash["uid"] == "aegis-reliability-overview"


class TestTelemetryStreamWorker:
    """Validates the continuous background telemetry worker logic."""

    def test_worker_snapshot_generation(self):
        worker = TelemetryStreamWorker(api_base_url="http://localhost:8000")
        snap = worker.generator.generate_snapshot()
        assert isinstance(snap, TelemetrySnapshot)
        assert snap.service_id is not None
        assert snap.infrastructure.cpu_percent >= 0.0
        assert snap.application.latency_p99_ms >= 0.0
        assert snap.database.active_connections >= 0
        assert snap.business.checkout_success_rate >= 0.0
