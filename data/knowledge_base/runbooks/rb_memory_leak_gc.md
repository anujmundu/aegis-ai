# SOP-102: Memory Leak & Garbage Collection Stop-the-World Remediation

## 1. Overview & Service Scope
- **Target Services**: `checkout-service`, `order-processing`
- **Target Resources**: `kubernetes-pods-checkout`
- **Criticality**: HIGH (Sev-2)
- **Primary Owner**: Microservices Engineering / Platform SRE

## 2. Telemetry Signature & Correlated Signals
An incident is classified under this runbook when:
- **Infrastructure Tier**: Monotonic linear upward drift in `infra_memory_percent` from baseline (45%) to near-OOM limit (>85%).
- **Garbage Collection Dynamics**: Periodic severe spikes in `infra_cpu_percent` (90-99%) every 2 to 5 minutes corresponding to Full Garbage Collection / heap compaction sweeps.
- **Application Tier**: Multimodal latency distribution; `app_latency_p99_ms` surges above 800ms during GC pause sweeps, while nominal requests between sweeps remain acceptable.
- **Database & Business**: Database metrics are nominal; `checkout_success_rate` drops moderately (85-92%) strictly due to socket read timeouts during stop-the-world pauses.

## 3. Diagnostic Triage Procedures
Execute diagnostic memory profiling commands:

```bash
# 1. Inspect container memory usage and limit
kubectl top pod -l app=checkout-service -n production

# 2. Trigger non-invasive memory allocation profiling
py-spy dump --pid $(pgrep -f "checkout_service")

# 3. Check for OOMKilled events in pod history
kubectl get events --field-selector reason=OOMKilled -n production
```

## 4. Controlled Remediation Protocol

### Step 4.1: Rolling Container Restart
To clear accumulated in-memory object leaks without dropping in-flight traffic:
- **Action Type**: `RESTART_CONTAINER`
- **Target Resource**: `checkout-service-pods`
- **Parameters**: `{"rolling_update": "true", "max_unavailable": "25%"}`
- **Risk Level**: LOW (Automated dry-run simulation supported)
- **Justification**: Rolling restart recreates worker pods one-by-one, restoring nominal 45% heap footprint without service outage.

### Step 4.2: Temporary Replica Scale-Out
If memory drift rate is high and traffic cannot be paused:
- **Action Type**: `SCALE_SERVICE`
- **Target Resource**: `checkout-service-deployment`
- **Parameters**: `{"replicas": "+3"}`
- **Risk Level**: LOW
- **Justification**: Spreads request load across more instances, reducing heap accumulation velocity per pod.

## 5. Verification & Post-Action Telemetry Checks
- Observe `infra_memory_percent` resetting to 40-50% on restarted pods.
- Verify `app_latency_p99_ms` stabilizes below 120ms without periodic 800ms spikes.
- Confirm zero pod restarts or OOMKilled events over the next 15 minutes.
