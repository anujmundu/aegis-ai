"""Unit and Conformance Tests for Production Kubernetes Manifests (Phase 11).

Covers:
- Namespace isolation (`aegis-system`)
- Kustomization resource inclusion and common labels
- High-Availability Deployments (replicas, probes, initContainers, non-root security context)
- Horizontal Pod Autoscaler (HPA v2) metrics and scaling policies
- ClusterIP Services and Ingress routing rules
- ConfigMap and Secret parameters
"""

from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
K8S_DIR = PROJECT_ROOT / "infrastructure" / "kubernetes"


class TestKubernetesStructure:
    """Validates K8s directory topology and Kustomization root."""

    def test_kustomization_manifest(self):
        kust_path = K8S_DIR / "kustomization.yaml"
        assert kust_path.exists(), "kustomization.yaml missing"
        with open(kust_path, "r", encoding="utf-8") as f:
            kust = yaml.safe_load(f)

        assert kust["namespace"] == "aegis-system"
        resources = kust["resources"]
        assert "namespace.yaml" in resources
        assert "configmaps/aegis-config.yaml" in resources
        assert "secrets/aegis-secrets.yaml" in resources
        assert "services/aegis-services.yaml" in resources
        assert "deployments/aegis-api-deployment.yaml" in resources
        assert "deployments/aegis-worker-deployment.yaml" in resources
        assert "hpa.yaml" in resources
        assert "ingress.yaml" in resources

    def test_namespace_manifest(self):
        ns_path = K8S_DIR / "namespace.yaml"
        assert ns_path.exists()
        with open(ns_path, "r", encoding="utf-8") as f:
            ns = yaml.safe_load(f)
        assert ns["kind"] == "Namespace"
        assert ns["metadata"]["name"] == "aegis-system"


class TestDeploymentSpecifications:
    """Validates High-Availability Deployments, Probes, and Security Contexts."""

    @pytest.fixture
    def api_deployment(self) -> dict:
        dep_path = K8S_DIR / "deployments" / "aegis-api-deployment.yaml"
        assert dep_path.exists()
        with open(dep_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def test_api_deployment_ha_and_rollout_strategy(self, api_deployment: dict):
        spec = api_deployment["spec"]
        assert spec["replicas"] >= 3, "Production API must run at least 3 replicas for HA"

        strategy = spec["strategy"]
        assert strategy["type"] == "RollingUpdate"
        assert strategy["rollingUpdate"]["maxUnavailable"] == 0, "Zero-downtime required"
        assert strategy["rollingUpdate"]["maxSurge"] >= 1

    def test_api_security_context(self, api_deployment: dict):
        pod_spec = api_deployment["spec"]["template"]["spec"]
        pod_sec = pod_spec["securityContext"]
        assert pod_sec["runAsNonRoot"] is True
        assert pod_sec["runAsUser"] == 10001

        container = pod_spec["containers"][0]
        c_sec = container["securityContext"]
        assert c_sec["allowPrivilegeEscalation"] is False
        assert "ALL" in c_sec["capabilities"]["drop"]

    def test_api_probes_and_resources(self, api_deployment: dict):
        container = api_deployment["spec"]["template"]["spec"]["containers"][0]

        # Resources
        res = container["resources"]
        assert "requests" in res and "limits" in res
        assert "cpu" in res["requests"] and "memory" in res["requests"]
        assert "cpu" in res["limits"] and "memory" in res["limits"]

        # Probes
        assert "livenessProbe" in container
        assert "readinessProbe" in container
        assert "startupProbe" in container
        assert container["livenessProbe"]["httpGet"]["path"] == "/v1/health"
        assert container["readinessProbe"]["httpGet"]["path"] == "/v1/health"

    def test_api_init_containers(self, api_deployment: dict):
        init_containers = api_deployment["spec"]["template"]["spec"].get("initContainers", [])
        init_names = [c["name"] for c in init_containers]
        assert "wait-for-postgres" in init_names
        assert "wait-for-redis" in init_names


class TestHorizontalPodAutoscaler:
    """Validates HPA scaling targets and metrics."""

    @pytest.fixture
    def hpa_manifest(self) -> dict:
        hpa_path = K8S_DIR / "hpa.yaml"
        assert hpa_path.exists()
        with open(hpa_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def test_hpa_configuration(self, hpa_manifest: dict):
        spec = hpa_manifest["spec"]
        assert spec["scaleTargetRef"]["name"] == "aegis-api-deployment"
        assert spec["minReplicas"] == 3
        assert spec["maxReplicas"] >= 10

        metrics = spec["metrics"]
        metric_names = [m["resource"]["name"] for m in metrics if m.get("type") == "Resource"]
        assert "cpu" in metric_names
        assert "memory" in metric_names

        # Behavior scaling rules
        assert "behavior" in spec
        assert "scaleUp" in spec["behavior"]
        assert "scaleDown" in spec["behavior"]


class TestIngressAndServices:
    """Validates Ingress paths and Service routing."""

    def test_ingress_rules(self):
        ing_path = K8S_DIR / "ingress.yaml"
        assert ing_path.exists()
        with open(ing_path, "r", encoding="utf-8") as f:
            ing = yaml.safe_load(f)

        assert ing["kind"] == "Ingress"
        rules = ing["spec"]["rules"]
        hosts = [r["host"] for r in rules]
        assert "aegis.internal" in hosts
        assert "mlflow.aegis.internal" in hosts

    def test_services_definitions(self):
        svc_path = K8S_DIR / "services" / "aegis-services.yaml"
        assert svc_path.exists()
        with open(svc_path, "r", encoding="utf-8") as f:
            docs = list(yaml.safe_load_all(f))

        svc_names = [d["metadata"]["name"] for d in docs]
        assert "aegis-api-service" in svc_names
        assert "aegis-postgres-service" in svc_names
        assert "aegis-redis-service" in svc_names
        assert "aegis-mlflow-service" in svc_names
