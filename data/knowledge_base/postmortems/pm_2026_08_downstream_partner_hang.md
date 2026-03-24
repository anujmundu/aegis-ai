# Postmortem: Cascading Downstream Fraud Partner Hang & Thread Starvation (August 2026)

## 1. Incident Metadata
- **Incident ID**: `INC-2026-08-09-03`
- **Severity**: Sev-2 (High)
- **Duration**: 18 minutes
- **Impacted Services**: `checkout-service`
- **Estimated Revenue Loss**: $28,000 USD

## 2. Executive Summary
On August 9, 2026, a third-party risk analysis partner (`api.partner-fraud-check.com`) suffered an internal deadlock. Synchronous REST calls from `checkout-service` to the partner hung without response. Because the HTTP client had a default socket read timeout of 30 seconds, all 128 application worker threads became occupied in socket read wait, causing all incoming checkout requests to queue and time out with HTTP 504 Gateway Timeout.

## 3. Key Telemetry Signatures
- `app_latency_p99_ms` surged to 4,800ms.
- HTTP 504 status codes skyrocketed to 65% of all traffic.
- Application host CPU dropped from 40% to 14% (indicating worker thread starvation, NOT compute bottleneck).
- Relational database connections and latencies remained completely nominal.

## 4. Root Cause Analysis
The synchronous fraud evaluation call lacked an active circuit breaker. A single unresponsive external vendor paralyzed the entire checkout pipeline.

## 5. Remediation & Long-Term Fixes
- **Circuit Breaker**: Implemented resilience4j / pybreaker circuit breaker with 800ms timeout (`TRIP_CIRCUIT_BREAKER`).
- **Asynchronous Queue Fallback**: When circuit breaker is OPEN, orders proceed with asynchronous background risk evaluation rather than synchronous blocking.
