# SOP-105: Promotional Traffic Burst & Capacity Saturation (Black Friday)

## 1. Overview & Service Scope
- **Target Services**: `checkout-service`, `order-processing`
- **Target Resources**: `kubernetes-cluster-core`, `ingress-loadbalancer`
- **Criticality**: INFO / LOW (Benign High-Traffic Event)
- **Primary Owner**: Growth Engineering / Platform SRE

## 2. Telemetry Signature & Correlated Signals
An event is classified under this runbook when:
- **Application Tier**: `app_requests_per_sec` surges 300% to 500% above baseline (e.g., from 120 req/s to 500+ req/s).
- **Business Tier**: `biz_order_volume` and `biz_revenue_usd` scale up proportionally with request volume. `checkout_success_rate` remains high (>97.5%).
- **Error Rates**: `app_http_5xx_count` and error rate remain <0.5%. This is a healthy, revenue-generating event, NOT an operational incident failure!
- **Infrastructure Tier**: `infra_cpu_percent` and `infra_memory_percent` scale up to 65-80% within healthy headroom.

## 3. Recommended Operational Procedures

### Step 3.1: Proactive HPA Autoscaling Pre-Warm
Ensure Kubernetes Horizontal Pod Autoscaler has sufficient capacity ceiling:
- **Action Type**: `SCALE_SERVICE`
- **Target Resource**: `checkout-service-deployment`
- **Parameters**: `{"min_replicas": "15", "max_replicas": "50"}`
- **Risk Level**: LOW
- **Justification**: Pre-scale pods to absorb incoming flash sale wave without waiting for CPU threshold reaction time.

### Step 3.2: Edge Caching Policy Confirmation
Verify CDN edge nodes are caching static catalog payloads with 300s TTL.
- **Action Type**: `VERIFY_CACHE_TTL`
- **Target Resource**: `cloudflare-cdn-rules`
- **Parameters**: `{"catalog_ttl_seconds": "300"}`

## 4. Distinction from Incidents
AegisAI agents must NOT trigger incident declarations or disruptive mitigations during `BLACK_FRIDAY_TRAFFIC_BURST`, as business KPIs confirm operational health and scaling efficiency.
