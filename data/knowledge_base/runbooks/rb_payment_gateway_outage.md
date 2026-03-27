# SOP-104: Payment Gateway Outage & Silent Transaction Rejection

## 1. Overview & Service Scope
- **Target Services**: `checkout-service`, `payment-orchestrator`
- **External Providers**: `stripe-primary`, `adyen-secondary`
- **Criticality**: CRITICAL (Sev-1)
- **Primary Owner**: Payment Operations / Platform SRE

## 2. Telemetry Signature & Correlated Signals
An incident is classified under this runbook when:
- **Infrastructure & Database Tiers**: 100% NOMINAL GREEN. CPU (35-45%), memory (45-55%), database pool (30-40%), and query latencies (8ms) show zero anomalies.
- **Application Tier**: App response latency is normal (20-30ms) and HTTP status codes are predominantly 200 OK. Single-tier infrastructure APM monitoring will completely miss this outage!
- **Business KPI Tier**: `checkout_success_rate` collapses catastrophically from nominal 99% to below 15%. `cart_abandonment_rate` spikes above 80%. `biz_order_volume` and `biz_revenue_usd` drop to near zero.
- **Root Cause Context**: External payment processor is experiencing an outage and returning `200 OK` with JSON payload `{"status": "declined", "code": "GATEWAY_DOWN"}`.

## 3. Diagnostic Triage Procedures
Run verification of payment gateway response payloads:

```bash
# 1. Inspect recent declined payment payloads
tail -n 200 /var/log/checkout/payment_audit.log | jq '. | select(.status=="declined") | .error_code' | sort | uniq -c

# 2. Check external gateway public status page API
curl -s https://status.stripe.com/api/v2/status.json | jq '.status.description'
```

## 4. Controlled Remediation Protocol

### Step 4.1: Failover to Secondary Payment Gateway
Switch active routing from degraded primary to healthy secondary processor:
- **Action Type**: `FAILOVER_PAYMENT_GATEWAY`
- **Target Resource**: `payment-routing-config`
- **Parameters**: `{"active_gateway": "adyen-secondary", "drain_timeout_seconds": "30"}`
- **Risk Level**: HIGH (Requires Human In The Loop Approval)
- **Justification**: Immediately redirect 100% of new checkout payment requests to Adyen secondary gateway to restore business revenue while Stripe recovers.

### Step 4.2: Enable Offline Payment Retry Queue
For declined transactions that occurred during the outage:
- **Action Type**: `ENABLE_RETRY_QUEUE`
- **Target Resource**: `payment-dead-letter-exchange`
- **Parameters**: `{"retry_interval_minutes": "15", "max_attempts": "3"}`
- **Risk Level**: LOW
- **Justification**: Re-submit eligible card charges once primary gateway status returns to operational.

## 5. Verification & Health Restoration
- Verify `biz_checkout_success_rate` recovers to > 97% within 2 minutes of routing switch.
- Verify `biz_order_volume` and `biz_revenue_usd` return to nominal circadian trajectory.
- Ensure zero double-charging occurred across failover window.
