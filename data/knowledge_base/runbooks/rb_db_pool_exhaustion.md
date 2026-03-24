# SOP-101: PostgreSQL Connection Pool Saturation & Deadlock Remediation

## 1. Overview & Service Scope
- **Target Services**: `checkout-service`, `order-processing`
- **Target Resources**: `aurora-postgres-primary`, `pgbouncer-pool`
- **Criticality**: CRITICAL (Sev-1 / Sev-2)
- **Primary Owner**: Platform SRE / Database Engineering

## 2. Telemetry Signature & Correlated Signals
An incident is classified under this runbook when the following multi-tier pattern is observed:
- **Database Tier**: `connection_pool_utilization` exceeds 90% (nominal is 30-45%), `query_latency_mean_ms` spikes above 200ms (nominal 8ms).
- **Application Tier**: `app_latency_p99_ms` surges above 1000ms, `http_5xx_count` escalates due to connection acquisition timeouts.
- **Infrastructure Tier**: Application host `cpu_percent` remains low-to-moderate (35-50%), proving the bottleneck is external I/O queue wait rather than CPU starvation.
- **Business Tier**: `checkout_success_rate` drops below 60% as customer checkout transactions abort.

## 3. Immediate Diagnostic Triage
Run the following read-only diagnostic queries against Aurora PostgreSQL:

```sql
-- 1. Check active vs idle client connections
SELECT count(*), state, wait_event_type, wait_event 
FROM pg_stat_activity 
GROUP BY state, wait_event_type, wait_event 
ORDER BY count(*) DESC;

-- 2. Identify queries holding locks for > 30 seconds
SELECT pid, now() - query_start AS duration, query, state 
FROM pg_stat_activity 
WHERE (now() - query_start) > interval '30 seconds'
AND state != 'idle';
```

## 4. Controlled Remediation Protocol
Remediation actions must follow the verified safety protocol:

### Step 4.1: Expand Connection Pool (Dry-Run / Live)
If the pool is saturated due to organic concurrency and DB CPU is healthy (<70%):
- **Action Type**: `INCREASE_POOL`
- **Target Resource**: `aurora-postgres-pool`
- **Parameters**: `{"max_connections": "200", "pool_mode": "transaction"}`
- **Risk Level**: MEDIUM (requires Human Approval in Production)
- **Justification**: Expand pool capacity from 100 to 200 to alleviate client connection backlog while backend query latency recovers.

### Step 4.2: Terminate Long-Running Abandoned Backends
If unclosed connections or idle transactions are leaking:
- **Command**:
```sql
SELECT pg_terminate_backend(pid) 
FROM pg_stat_activity 
WHERE state = 'idle in transaction' 
AND state_change < NOW() - INTERVAL '5 minutes';
```

### Step 4.3: Fallback Service Throttling
If database CPU reaches 95%+, activate rate-limiting on non-essential endpoints:
- **Action Type**: `ENABLE_RATE_LIMITING`
- **Target Resource**: `checkout-service-gateway`
- **Parameters**: `{"rate_limit_rps": "80"}`

## 5. Verification & Rollback
- Verify `connection_pool_utilization` drops below 65%.
- Verify `app_latency_p95_ms` returns to <75ms within 3 minutes.
- If database CPU spikes above 90% after pool expansion, revert pool size to nominal 100.
