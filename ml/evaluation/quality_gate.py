"""Automated Model Quality Gate for AegisAI MLOps Pipeline.

Enforces strict production promotion criteria before models can be deployed:
- Precision >= 0.90
- Recall >= 0.88
- False Positive Rate (FPR) <= 0.025 (2.5%)
- Inference Latency p99 < 15.0ms
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List

from pydantic import BaseModel, Field

logger = logging.getLogger("aegisai.mlops.quality_gate")


class QualityGateFailureError(Exception):
    """Raised when a candidate model violates production quality thresholds."""

    pass


class QualityGateCheck(BaseModel):
    """Individual metric evaluation check."""

    metric_name: str
    observed_value: float
    threshold: float
    operator: str = Field(..., description=">= | <=")
    passed: bool
    detail: str


class QualityGateReport(BaseModel):
    """Consolidated Model Quality Gate evaluation report."""

    model_name: str
    model_version: str
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    overall_passed: bool
    checks: List[QualityGateCheck]
    verdict: str = Field(..., description="PROMOTED_TO_PRODUCTION | REJECTED_QUALITY_FAILURE")
    summary: str


class ModelQualityGate:
    """Enforces strict production readiness thresholds on ML models."""

    def __init__(
        self,
        min_precision: float = 0.90,
        min_recall: float = 0.88,
        max_fpr: float = 0.025,
        max_p99_latency_ms: float = 15.0,
    ) -> None:
        self.min_precision = min_precision
        self.min_recall = min_recall
        self.max_fpr = max_fpr
        self.max_p99_latency_ms = max_p99_latency_ms

    def evaluate(
        self,
        model_name: str,
        metrics: Dict[str, float],
        version: str = "1.0.0",
    ) -> QualityGateReport:
        """Evaluate candidate metrics against production SLAs."""
        checks: List[QualityGateCheck] = []

        # 1. Precision Check
        prec = float(metrics.get("precision", metrics.get("macro_precision", 0.0)))
        prec_pass = prec >= self.min_precision
        checks.append(
            QualityGateCheck(
                metric_name="precision",
                observed_value=round(prec, 4),
                threshold=self.min_precision,
                operator=">=",
                passed=prec_pass,
                detail=f"Precision {prec:.1%} {'meets' if prec_pass else 'violates'} minimum {self.min_precision:.1%}",
            )
        )

        # 2. Recall Check
        rec = float(metrics.get("recall", metrics.get("macro_recall", 0.0)))
        rec_pass = rec >= self.min_recall
        checks.append(
            QualityGateCheck(
                metric_name="recall",
                observed_value=round(rec, 4),
                threshold=self.min_recall,
                operator=">=",
                passed=rec_pass,
                detail=f"Recall {rec:.1%} {'meets' if rec_pass else 'violates'} minimum {self.min_recall:.1%}",
            )
        )

        # 3. False Positive Rate (FPR) Check
        fpr = float(metrics.get("fpr", metrics.get("false_positive_rate", 0.0)))
        fpr_pass = fpr <= self.max_fpr
        checks.append(
            QualityGateCheck(
                metric_name="false_positive_rate",
                observed_value=round(fpr, 4),
                threshold=self.max_fpr,
                operator="<=",
                passed=fpr_pass,
                detail=f"FPR {fpr:.2%} {'satisfies' if fpr_pass else 'exceeds'} ceiling of {self.max_fpr:.2%}",
            )
        )

        # 4. Latency p99 Check
        lat_p99 = float(metrics.get("p99_latency_ms", metrics.get("latency_p99_ms", 0.0)))
        lat_pass = lat_p99 < self.max_p99_latency_ms
        checks.append(
            QualityGateCheck(
                metric_name="p99_latency_ms",
                observed_value=round(lat_p99, 2),
                threshold=self.max_p99_latency_ms,
                operator="<",
                passed=lat_pass,
                detail=f"p99 Latency {lat_p99:.2f}ms {'satisfies' if lat_pass else 'exceeds'} SLA {self.max_p99_latency_ms:.1f}ms",
            )
        )

        overall_passed = all(c.passed for c in checks)
        verdict = "PROMOTED_TO_PRODUCTION" if overall_passed else "REJECTED_QUALITY_FAILURE"

        summary_lines = [
            f"=== Quality Gate Evaluation for {model_name} (v{version}) ===",
            f"Verdict: {verdict}",
        ]
        for c in checks:
            status_sym = "[PASS]" if c.passed else "[FAIL]"
            summary_lines.append(f"  {status_sym} {c.metric_name}: {c.detail}")

        summary_text = "\n".join(summary_lines)

        return QualityGateReport(
            model_name=model_name,
            model_version=version,
            overall_passed=overall_passed,
            checks=checks,
            verdict=verdict,
            summary=summary_text,
        )

    def enforce(
        self,
        model_name: str,
        metrics: Dict[str, float],
        version: str = "1.0.0",
    ) -> QualityGateReport:
        """Evaluate candidate metrics and raise QualityGateFailureError if any check fails."""
        report = self.evaluate(model_name, metrics, version)
        if not report.overall_passed:
            failed_checks = [c.detail for c in report.checks if not c.passed]
            raise QualityGateFailureError(
                f"Model '{model_name}' rejected by Quality Gate: {'; '.join(failed_checks)}"
            )
        return report
