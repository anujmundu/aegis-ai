# Postmortem: Aurora PostgreSQL Connection Pool Exhaustion Outage (March 2026)

## 1. Incident Metadata
- **Incident ID**: `INC-2026-03-14-01`
- **Severity**: Sev-1 (Critical)
- **Duration**: 24 minutes
- **Impacted Services**: `checkout-service`, `order-processing`
- **Estimated Revenue Loss**: $42,500 USD

## 2. Executive Summary
On March 14, 2026, at 14:15 UTC, the production `checkout-service` experienced an abrupt surge in HTTP 500 error rates to 43%, accompanied by checkout conversion dropping from 99.1% to 38.5%. The root cause was identified as a client connection leak in the checkout database driver pool, causing active PostgreSQL connections to reach the cluster maximum of 100 connections. New customer checkout requests were queued indefinitely until timing out.

## 3. Telemetry Indicators & Timeline
- `14:12 UTC`: DB connection pool utilization climbed from nominal 38% to 88%.
- `14:15 UTC`: Pool hit 100% capacity. Database query latency spiked from 8ms to 345ms.
- `14:16 UTC`: Application p99 latency surged to 1,850ms. HTTP 500 errors began escalating.
- `14:24 UTC`: On-call engineer executed `INCREASE_POOL(max_connections=200)` and terminated idle-in-transaction sessions.
- `14:28 UTC`: Pool utilization dropped back to 52%, latency normalized to 28ms, error rate collapsed to 0.1%.

## 4. Root Cause Analysis
A recent patch to the coupon validation service omitted a `finally: connection.close()` block on invalid coupon paths, causing connections to remain in `idle in transaction` state indefinitely until reaching server limits.

## 5. Lessons Learned & Action Items
- **Automated Remediation**: Action Agent should be authorized to provision emergency connection pool headroom (`INCREASE_POOL`) via dry-run simulation when pool > 95% and DB CPU < 70%.
- **Connection Leak Detection**: Set alert on sessions in `idle in transaction` lasting > 60 seconds.
