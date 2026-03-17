# 📊 Tableau Workbook Specification: AegisAI Executive Reliability & Financial ROI

**Target Audience:** CTO, VP of Engineering, Head of Infrastructure, SRE Leads  
**Workbook Dimensions:** 1440px $\times$ 900px (Desktop Responsive)  
**Primary Data Source:** `fact_incident_financials.csv` joined to `dim_service.csv`, `dim_severity.csv`, and `dim_archetype.csv`

---

## 🏛️ Dashboard Layout Topology

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ 🛡️ AEGISAI EXECUTIVE RELIABILITY & BUSINESS IMPACT DASHBOARD                          │
├───────────────────┬───────────────────┬───────────────────┬────────────────────────────┤
│ [1] MTTR REDUCTION│ [2] HOURS SAVED   │ [3] RISK MITIGATED│ [4] NET ROI & PAYBACK      │
│   22.0 mins       │   163.2 Hours     │   $3,354,666      │   +5,594% ROI              │
│   ▼ 75.5% vs 90m  │   SRE Labor Back  │   Gross Exposure  │   Payback < 2.5 Weeks      │
├───────────────────┴───────────────────┴───────────────────┴────────────────────────────┤
│ [CHART A] MTTR Waterfall Reduction       │ [CHART B] Monthly Downtime Exposure Avoided │
│  Baseline (90m) -> Diagnostic (8m) ->     │  Dual-Axis: Incurred Downtime vs Avoided    │
│  Runbook Retrieval (6m) -> AutoRem (8m)   │  Value across 12-month timeline             │
├───────────────────────────────────────────┼────────────────────────────────────────────┤
│ [CHART C] Microservice Health & SLA Matrix│ [CHART D] Failure Archetype Pareto (80/20) │
│  Service Tier, Critical P1s, Availability │  Top Root Causes ranked by Cost Avoided    │
│  SLA % (99.9%+) and Savings Avoided       │  (Connection Pool, Memory Leak, Gateway)   │
└───────────────────────────────────────────┴────────────────────────────────────────────┘
```

---

## 📐 Worksheet Visual Specifications

### 1. KPI Executive Banners (Top Row Cards)
- **Card 1: MTTR Compression**
  - Big Number: `22.0 min`
  - Subtitle: `Reduced from 90.0 min baseline (-75.5%)`
  - Sparkline: Monthly MTTR trend line
- **Card 2: Engineering Hours Reclaimed**
  - Big Number: `163.2 hrs`
  - Subtitle: `Equivalent to $15.5k in senior engineering capacity`
- **Card 3: Gross Financial Risk Avoided**
  - Big Number: `$3.35M`
  - Subtitle: `Grounded in downtime rates: $180k/hr (P1), $120k/hr (P2)`
- **Card 4: Net Realized ROI (25% Model)**
  - Big Number: `+5,594%`
  - Subtitle: `$838.6k net return / < 2.5 week payback on $15k cost`

### 2. Chart A: MTTR Waterfall Analysis (Gantt / Waterfall)
- **Dimensions:** Remediation Phase (`Baseline Discovery`, `Signal Correlation`, `Knowledge RAG Retrieval`, `Operator Approval`, `Resolution Verification`)
- **Measure:** Minutes elapsed per stage
- **Visual Encoding:** Gradient color bar highlighting automated agent steps vs manual legacy steps.

### 3. Chart B: Monthly Reliability & Financial Value (Dual-Axis Bar & Line)
- **X-Axis:** `Date (Month)`
- **Left Y-Axis (Bar):** `Total Downtime Savings Avoided ($)` in Emerald Green (`#10B981`)
- **Right Y-Axis (Line):** `Incident Count` split by Severity (P1, P2, P3)

### 4. Chart C: Microservice Tier SLA Matrix (Heatmap / Horizontal Bullet)
- **Rows:** `Service Name`, `Tier`, `Criticality`
- **Columns:** `Incident Count`, `Critical P1s`, `Availability SLA %`, `Total Downtime Cost Avoided`
- **Color Ramp:** Blue-to-Green gradient for SLA availability.

### 5. Chart D: Incident Archetype Pareto (Sorted Horizontal Bar)
- **Rows:** `Archetype Name`
- **Measure:** `Total Savings ($)` (Bar length) and `Cumulative % of Total Savings` (Pareto Line)
- **Insight:** Proves that DB connection pools and memory leaks account for 68% of enterprise financial exposure.

---

## 🎛️ Interactive Filters & Parameters
1. **Time Range Filter:** Last 30 Days, Last Quarter, Full Year (Default: Full Year 2026)
2. **Service Tier Filter:** All, Infrastructure, Application, Database
3. **Severity Filter:** All, Critical (P1), High (P2), Medium (P3)
4. **Realization Rate Parameter (Slider):** Range `10%` to `100%` (Default: `25%` conservative model)
