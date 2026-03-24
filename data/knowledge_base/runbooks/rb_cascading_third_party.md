# SOP-103: Cascading Third-Party Partner Timeout & Circuit Breaking

## 1. Overview & Service Scope
- **Target Services**: `checkout-service`
- **Downstream Dependency**: `fraud-detection-api`, `address-verification-service`
- **Criticality**: HIGH (Sev-2)
- **Primary Owner**: Payment & Checkout Team / SRE

## 2. Telemetry Signature & Correlated Signals
An incident is classified under this runbook when:
- **Application Tier**: `app_latency_p95_ms` > 1500ms, `app_latency_p99_ms` > 3500ms; HTTP 504 Gateway Timeout count increases dramatically.
- **Infrastructure Tier**: Application host `cpu_percent` is anomalously LOW (15-25%), which contrasts sharply with high latency. This is classic thread starvation where all worker threads are blocked waiting for external network sockets.
- **Correlation Decoupling**: Pearson correlation between `app_requests_per_sec` and `infra_cpu_percent` breaks down.
- **Database Tier**: Relational database connection pool and query latencies are 100% healthy.

## 3. Diagnostic Triage Procedures
Identify which downstream endpoint is hanging:

```bash
# 1. Trace outbound HTTP egress socket states
netstat -anp | grep :443 | grep ESTABLISHED | wc -l

# 2. Inspect application gateway access logs for upstream status
tail -n 100 /var/log/checkout/access.log | grep -E "upstream_status=(504|TIMEDOUT)"

# 3. Test latency directly to external partner
curl -w "DNS: %{time_namelookup} Connect: %{time_connect} Total: %{time_total}\n" \
     -o /dev/null -s https://api.partner-fraud-check.com/health
```

## 4. Controlled Remediation Protocol

### Step 4.1: Trip Circuit Breaker with Fallback
Isolate the hanging dependency immediately:
- **Action Type**: `TRIP_CIRCUIT_BREAKER`
- **Target Resource**: `fraud-detection-client`
- **Parameters**: `{"circuit_state": "OPEN", "fallback_mode": "ASYNC_RISK_EVALUATION"}`
- **Risk Level**: MEDIUM (requires Human Confirmation or Automated Policy Approval)
- **Justification**: Open circuit breaker to stop synchronous HTTP calls to partner. Fall back to queuing transactions for asynchronous risk scoring, unblocking client checkout threads immediately.

### Step 4.2: Reduce Client Connect & Read Timeouts
If circuit breaker cannot be tripped:
- **Action Type**: `UPDATE_CONFIG`
- **Target Resource**: `checkout-client-config`
- **Parameters**: `{"http_read_timeout_ms": "800", "http_connect_timeout_ms": "300"}`
- **Risk Level**: LOW
- **Justification**: Fail fast within 800ms rather than tying up application threads for 10 seconds.

## 5. Verification & Post-Remediation Checks
- Verify `app_latency_p99_ms` collapses back under 150ms.
- Observe application worker thread queue utilization returning to normal (<30%).
- Ensure transactions are placed on the asynchronous evaluation queue without dropped orders.
