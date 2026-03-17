# 📊 Tableau Calculated Fields: AegisAI Executive Dashboard

This document details the exact Tableau formulas for creating the Executive Reliability & Financial ROI workbook.

---

## 1. Core Reliability & Volume Metrics

### `[Total Incidents]`
```tableau
COUNTD([Incident Id])
```

### `[Resolved Incidents]`
```tableau
COUNTD(IF [Status] = "RESOLVED" AND NOT [Is False Positive] THEN [Incident Id] END)
```

### `[False Positive Rate %]`
```tableau
COUNTD(IF [Is False Positive] THEN [Incident Id] END) / [Total Incidents] * 100
```

---

## 2. MTTR Reduction & Efficiency

### `[Baseline Avg MTTR (mins)]`
```tableau
AVG(IF NOT [Is False Positive] THEN [Baseline Mttr Minutes] END)
```

### `[AegisAI Avg MTTR (mins)]`
```tableau
AVG(IF NOT [Is False Positive] THEN [Actual Mttr Minutes] END)
```

### `[MTTR Reduction (mins)]`
```tableau
[Baseline Avg MTTR (mins)] - [AegisAI Avg MTTR (mins)]
```

### `[MTTR Reduction %]`
```tableau
([Baseline Avg MTTR (mins)] - [AegisAI Avg MTTR (mins)]) / [Baseline Avg MTTR (mins)] * 100
```

---

## 3. Financial Exposure & Net Savings

### `[Total Downtime Exposure Avoided ($)]`
```tableau
SUM([Downtime Savings Gross])
```

### `[Engineering Hours Reclaimed]`
```tableau
SUM([Engineering Hours Saved])
```

### `[Engineering Labor Cost Saved ($)]`
```tableau
SUM([Engineering Cost Saved])
```

### `[Gross Value Delivered ($)]`
```tableau
SUM([Total Gross Value Delivered])
```

### `[Realized Net Savings ($)]`
```tableau
// Conservative 25% realization model (grounded in docs/03_business_case.md)
[Gross Value Delivered ($)] * 0.25
```

---

## 4. Executive ROI & Breakeven

### `[Annual Platform Cost ($)]`
```tableau
15000.0
```

### `[Net Enterprise ROI %]`
```tableau
([Realized Net Savings ($)] - [Annual Platform Cost ($)]) / [Annual Platform Cost ($)] * 100
```

### `[Payback Period (Days)]`
```tableau
[Annual Platform Cost ($)] / ([Realized Net Savings ($)] / 365.0)
```

---

## 5. Visual Color Palette Recommendations
- **Avoided Downtime / Savings:** Emerald Green (`#10B981`)
- **Actual Downtime Incurred:** Coral Rose (`#F43F5E`)
- **P1 Critical Alert:** Crimson Red (`#E11D48`)
- **P2 High Alert:** Amber Orange (`#F59E0B`)
- **P3 Medium Alert:** Sky Blue (`#0EA5E9`)
- **AegisAI Brand Primary:** Indigo (`#6366F1`)
