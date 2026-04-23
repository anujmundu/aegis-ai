"""Continuous Live Observability Traffic Generator for AegisAI.

Ensures real-time non-zero metric values across all Prometheus counters,
histograms, gauges, and rates for Grafana dashboards:
- Anomaly detections across all 5 detector types (Z-Score, Modified Z-Score, EWMA, Mahalanobis, Correlation Drift)
- Detection latency SLA (< 15ms target)
- Multi-agent orchestration and RAG grounding fidelity (>= 95% SLA)
- Remediation pipeline proposed and executed actions
- End-to-end API HTTP requests and latency percentiles (p50 / p95 / p99)
"""

import random
import time
import uuid
from datetime import datetime, timezone, timedelta
import httpx

from data.schemas.events import AnomalyArchetype, AnomalySignal, IncidentSeverity
from data.synthetic.telemetry_generator import MultiTierTelemetryGenerator

API_BASE_URL = "http://localhost:8000"

def emit_continuous_traffic(duration_seconds: int = 120):
    print(f"[*] Starting live observability traffic stream for {duration_seconds}s...")
    gen = MultiTierTelemetryGenerator(seed=int(time.time()))
    client = httpx.Client(base_url=API_BASE_URL, timeout=10.0)

    start_time = time.time()
    tick = 0
    now = datetime.now(timezone.utc)

    archetypes = [
        AnomalyArchetype.DB_CONNECTION_POOL_SATURATION,
        AnomalyArchetype.CASCADING_THIRD_PARTY_FAILURE,
        AnomalyArchetype.MEMORY_LEAK_SLOW_BURN,
        AnomalyArchetype.TRAFFIC_SPIKE_FLASH_CROWD,
    ]

    action_types = [
        "EXPAND_DB_CONNECTION_POOL",
        "RESTART_CONTAINER",
        "SCALE_DEPLOYMENT_REPLICAS",
        "FLUSH_QUERY_CACHE",
        "ENABLE_RATE_LIMITING",
    ]

    while time.time() - start_time < duration_seconds:
        tick += 1
        now += timedelta(seconds=2)

        # 1. Telemetry Snapshot Ingestion (Generates anomaly detections + latency histogram)
        arch = random.choice(archetypes)
        snap = gen.generate_snapshot(archetype=arch)
        snap.timestamp = now
        try:
            client.post("/v1/telemetry/snapshot", json=snap.model_dump(mode="json"))
        except Exception:
            pass

        # 2. General HTTP traffic (Generates HTTP requests rate + API latency SLA)
        try:
            client.get("/v1/health")
            client.get("/v1/incidents/active")
        except Exception:
            pass

        # 3. Multi-Agent Incident Triage & Operator Approval (Generates RAG grounding + remediation actions)
        if tick % 4 == 0:
            inc_id = f"INC-LIVE-{uuid.uuid4().hex[:6]}"
            act = random.choice(action_types)
            sig = AnomalySignal(
                signal_id=f"sig-{tick}",
                service_id="checkout-service",
                metric_name="db_connection_pool_active_connections" if "DB" in act else "application.latency_p99_ms",
                detector_type=random.choice(["modified_z_score", "z_score", "ewma", "mahalanobis"]),
                observed_value=88.0 + random.uniform(5.0, 30.0),
                baseline_value=40.0,
                deviation_sigma=round(random.uniform(5.2, 7.5), 2),
                severity=IncidentSeverity.CRITICAL if tick % 2 == 0 else IncidentSeverity.HIGH,
                is_anomaly=True,
                is_primary_driver=True,
            )
            triage_payload = {
                "incident_id": inc_id,
                "service_id": "checkout-service",
                "severity": "CRITICAL",
                "raw_signals": [sig.model_dump(mode="json")],
                "classifier_archetype": arch.value,
                "classifier_confidence": round(random.uniform(0.96, 0.995), 3),
            }
            try:
                r = client.post("/v1/incidents/triage", json=triage_payload)
                if r.status_code == 200:
                    token = r.json().get("approval_token")
                    if token:
                        client.post(
                            f"/v1/incidents/{inc_id}/approve",
                            json={"approval_token": token, "operator_id": "lead-sre-oncall"},
                        )
            except Exception:
                pass

        time.sleep(0.5)

    print("[+] Observability stream cycle completed successfully.")

if __name__ == "__main__":
    emit_continuous_traffic(duration_seconds=90)
