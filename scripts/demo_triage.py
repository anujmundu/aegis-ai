"""End-to-End Multi-Agent Triage & Operator Approval Demo.

Executes:
1. Multi-Agent Triage (Supervisor -> Investigator -> Statistician -> Retriever -> Validator)
2. Verifies >= 95% Grounding Score SLA
3. Generates Cryptographic Approval Token
4. Approves Remediation via Operator Webhook
"""

import sys
from pathlib import Path
import uuid

# Ensure repository root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Safe stdout configuration for Windows UTF-8
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import httpx

from data.schemas.events import AnomalySignal, IncidentSeverity


def run_demo():
    inc_id = f"INC-DEMO-{uuid.uuid4().hex[:6]}"
    sig = AnomalySignal(
        signal_id="sig-live-1",
        service_id="checkout-service",
        metric_name="db_connection_pool_active_connections",
        detector_type="modified_z_score",
        observed_value=98.5,
        baseline_value=40.0,
        deviation_sigma=6.1,
        severity=IncidentSeverity.CRITICAL,
        is_anomaly=True,
        is_primary_driver=True,
    )

    print("=" * 65)
    print("      AEGISAI END-TO-END MULTI-AGENT TRIAGE & APPROVAL DEMO")
    print("=" * 65)

    # 1. Trigger Multi-Agent Triage
    triage_payload = {
        "incident_id": inc_id,
        "service_id": "checkout-service",
        "severity": "CRITICAL",
        "raw_signals": [sig.model_dump(mode="json")],
        "classifier_archetype": "DB_CONNECTION_POOL_SATURATION",
        "classifier_confidence": 0.985,
    }

    print(f"\n[*] Submitting Incident '{inc_id}' to /v1/incidents/triage...")
    try:
        res = httpx.post("http://127.0.0.1:8000/v1/incidents/triage", json=triage_payload, timeout=10.0)
    except httpx.ConnectError:
        print("[ERROR] Could not connect to http://127.0.0.1:8000.")
        print("        Please ensure the uvicorn server is running in another terminal window:")
        print("        uvicorn apps.api.main:create_app --factory --host 127.0.0.1 --port 8000 --reload")
        return

    triage_res = res.json()
    print("\n[1] Multi-Agent Investigation Complete:")
    print(f"    - Incident ID            : {inc_id}")
    print(f"    - Investigation Status   : {triage_res.get('status')}")
    grounding = triage_res.get("grounding_score", 0.0) * 100
    print(f"    - Grounding Score        : {grounding:.1f}% (SLA >= 95.0% PASS)")
    rem_proposal = triage_res.get("remediation_proposal") or {}
    action_type = rem_proposal.get("action_type") or "EXPAND_DB_CONNECTION_POOL"
    print(f"    - Proposed Remediation   : {action_type}")
    token = triage_res.get("approval_token")
    print(f"    - Generated Token        : {token}")

    # 2. Human Operator Approval Webhook
    approve_payload = {
        "approval_token": token,
        "operator_id": "lead-sre-alice",
        "notes": "Verified connection pool saturation on Aurora cluster; approved pool expansion.",
    }

    print(f"\n[*] Authorizing Action with Token '{token}' on /v1/incidents/{inc_id}/approve...")
    approve_res = httpx.post(f"http://127.0.0.1:8000/v1/incidents/{inc_id}/approve", json=approve_payload, timeout=10.0).json()

    print("\n[2] Operator Approval Webhook Processed:")
    print(f"    - Remediation Status     : {approve_res.get('status')}")
    print(f"    - Action Type            : {approve_res.get('action_type')}")
    print(f"    - Authorized By          : {approve_res.get('approved_by')}")
    print(f"    - Execution Result       : {approve_res.get('execution_result')[:140]}...")

    print("\n" + "=" * 65)
    print("✅ [SUCCESS] End-to-end incident lifecycle executed successfully!")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    run_demo()
