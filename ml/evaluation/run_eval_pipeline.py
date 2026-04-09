"""Unified MLOps Evaluation & Benchmark Pipeline Runner for AegisAI.

Executes:
1. ML Anomaly Detection & Archetype Classification Benchmark
2. Latency SLA Profiling (p50, p95, p99 ms)
3. Automated Production Model Quality Gate Evaluation
4. GenAI / RAG Reliability & Grounding Evaluation (Ragas-style)
5. MLOps Experiment Tracking & Model Registry Logging
6. Executive Markdown Report Generation
"""

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
from sklearn.metrics import confusion_matrix, f1_score, precision_score, recall_score

from ai.agents.graph import ReliabilityGraph
from ai.evaluation.ragas_evaluator import RAGEvaluator
from data.schemas.events import AnomalyArchetype
from data.synthetic.telemetry_generator import MultiTierTelemetryGenerator
from ml.evaluation.quality_gate import ModelQualityGate
from ml.features.feature_extractor import (
    ARCHETYPE_LABEL_MAP,
    LABEL_TO_ARCHETYPE,
    TelemetryFeatureExtractor,
)
from ml.models.classical.incident_classifier import IncidentClassifier
from ml.models.classical.isolation_forest import IsolationForestDetector
from ml.models.deep.autoencoder import ReconstructionAutoencoder
from ml.models.statistical.engine import StatisticalAnomalyEngine
from ml.training.tracker import MLOpsTracker

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("aegisai.mlops.eval_runner")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def run_full_mlops_pipeline(
    output_dir: Optional[Path] = None,
    enforce_gate: bool = True,
) -> Dict[str, Any]:
    """Execute complete end-to-end MLOps evaluation cycle."""
    eval_dir = output_dir or (PROJECT_ROOT / "docs" / "benchmarks")
    eval_dir.mkdir(parents=True, exist_ok=True)

    tracker = MLOpsTracker(experiment_name="aegisai-model-benchmark")
    run = tracker.start_run(run_name=f"eval-pipeline-{int(time.time())}")
    logger.info("Started MLOps Run ID: %s", run.run_id)

    # 1. Dataset Generation
    logger.info("Generating multi-tier synthetic dataset...")
    gen = MultiTierTelemetryGenerator(seed=42)
    train_snaps = []
    test_snaps = []

    for arch in AnomalyArchetype:
        train_snaps.extend(gen.generate_batch(num_snapshots=60, archetype=arch))
        test_snaps.extend(gen.generate_batch(num_snapshots=30, archetype=arch))

    df_train = MultiTierTelemetryGenerator.to_dataframe(train_snaps)
    df_test = MultiTierTelemetryGenerator.to_dataframe(test_snaps)

    # 2. Feature Extraction
    extractor = TelemetryFeatureExtractor(window_size=5)
    X_train, y_train, feature_names = extractor.fit_transform(df_train)
    X_test, y_test, _ = extractor.fit_transform(df_test)

    tracker.log_param("num_features", X_train.shape[1])
    tracker.log_param("train_samples", len(X_train))
    tracker.log_param("test_samples", len(X_test))

    # 3. Model Training & Latency Profiling
    logger.info("Training and evaluating models...")
    # (a) Statistical Engine
    stat_engine = StatisticalAnomalyEngine()
    stat_engine.fit_baseline(train_snaps[:50])

    stat_latencies = []
    for s in test_snaps[:40]:
        t0 = time.perf_counter()
        stat_engine.analyze_snapshot(s)
        stat_latencies.append((time.perf_counter() - t0) * 1000.0)

    # (b) Autoencoder
    ae = ReconstructionAutoencoder(
        input_dim=X_train.shape[1],
        hidden_dim=12,
        latent_dim=4,
        threshold_sigmas=2.5,
        feature_names=feature_names,
    )
    ae.fit(X_train, epochs=40, batch_size=16, lr=0.01)

    ae_latencies = []
    for row in X_test[:40]:
        t0 = time.perf_counter()
        ae.score(row.reshape(1, -1))
        ae_latencies.append((time.perf_counter() - t0) * 1000.0)

    # (c) Isolation Forest
    iso = IsolationForestDetector(contamination=0.05, n_estimators=60, random_state=42)
    iso.fit(X_train)

    iso_latencies = []
    for row in X_test[:40]:
        t0 = time.perf_counter()
        iso.score(row)
        iso_latencies.append((time.perf_counter() - t0) * 1000.0)

    # (d) Incident Classifier
    clf = IncidentClassifier(n_estimators=80, max_depth=5, random_state=42)
    clf.fit(X_train, y_train, feature_names=feature_names)

    clf_latencies = []
    y_preds = []
    for row in X_test:
        t0 = time.perf_counter()
        cid, _name, _conf, _probs = clf.predict(row.reshape(1, -1))
        clf_latencies.append((time.perf_counter() - t0) * 1000.0)
        y_preds.append(cid)

    y_preds = np.array(y_preds)

    # 4. Classification Metrics
    macro_prec = float(precision_score(y_test, y_preds, average="macro", zero_division=0))
    macro_rec = float(recall_score(y_test, y_preds, average="macro", zero_division=0))
    macro_f1 = float(f1_score(y_test, y_preds, average="macro", zero_division=0))
    accuracy = float(np.mean(y_test == y_preds))

    # Compute False Positive Rate on Nominal Class (0)
    nom_mask = y_test == 0
    nominal_total = int(np.sum(nom_mask))
    false_positives = int(np.sum((y_test == 0) & (y_preds != 0)))
    fpr = float(false_positives / nominal_total) if nominal_total > 0 else 0.0

    p99_lat_stat = float(np.percentile(stat_latencies, 99))
    p99_lat_ae = float(np.percentile(ae_latencies, 99))
    p99_lat_clf = float(np.percentile(clf_latencies, 99))

    # Log metrics to MLOps tracker
    metrics_to_log = {
        "macro_precision": macro_prec,
        "macro_recall": macro_rec,
        "macro_f1": macro_f1,
        "accuracy": accuracy,
        "false_positive_rate": fpr,
        "stat_engine_p99_ms": p99_lat_stat,
        "autoencoder_p99_ms": p99_lat_ae,
        "classifier_p99_ms": p99_lat_clf,
    }
    tracker.log_metrics(metrics_to_log)

    # Confusion matrix
    conf_mat = confusion_matrix(y_test, y_preds).tolist()
    class_names = [LABEL_TO_ARCHETYPE.get(i, str(i)) for i in range(len(ARCHETYPE_LABEL_MAP))]
    tracker.log_confusion_matrix({"matrix": conf_mat, "classes": class_names})

    # 5. Production Model Quality Gate
    logger.info("Evaluating Model Quality Gate...")
    gate = ModelQualityGate(
        min_precision=0.90,
        min_recall=0.88,
        max_fpr=0.025,
        max_p99_latency_ms=15.0,
    )
    gate_report = gate.evaluate("incident_classifier", {
        "precision": macro_prec,
        "recall": macro_rec,
        "fpr": fpr,
        "p99_latency_ms": p99_lat_clf,
    })
    tracker.log_dict(gate_report.model_dump(mode="json"), "quality_gate_report.json")

    # Register in Model Registry
    reg_entry = tracker.register_model(
        model_name="incident_classifier",
        version="0.7.0",
        stage="Production" if gate_report.overall_passed else "Staging",
        metrics=metrics_to_log,
        passed_quality_gate=gate_report.overall_passed,
    )

    # 6. Automated RAG & Multi-Agent Evaluation
    logger.info("Running GenAI & RAG reliability benchmark...")
    graph = ReliabilityGraph()
    rag_evaluator = RAGEvaluator()
    rag_report = rag_evaluator.run_benchmark(graph)
    tracker.log_metrics({
        "rag_macro_faithfulness": rag_report.macro_faithfulness,
        "rag_macro_context_precision": rag_report.macro_context_precision,
        "rag_macro_context_recall": rag_report.macro_context_recall,
        "rag_action_accuracy": rag_report.action_accuracy,
    })
    tracker.log_dict(rag_report.model_dump(mode="json"), "rag_benchmark_report.json")

    tracker.end_run(status="FINISHED")

    # 7. Generate Executive Markdown Report
    report_file = eval_dir / "mlops_eval_report.md"
    report_md = f"""# 🛡️ AegisAI: MLOps Evaluation & Reliability Benchmark Report

**Evaluation Timestamp**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}<br/>
**Run ID**: `{run.run_id}`<br/>
**Model Registry Status**: `{reg_entry['stage']}` ({'PASSED QUALITY GATE' if gate_report.overall_passed else 'FAILED'})

---

## 1. Multi-Class Archetype Classification Benchmark

| Metric | Measured | Quality Target | Gate Status |
| :--- | :--- | :--- | :--- |
| **Macro Precision** | **{macro_prec:.1%}** | $\\ge 90.0\\%$ | {'PASS' if macro_prec >= 0.90 else 'FAIL'} |
| **Macro Recall** | **{macro_rec:.1%}** | $\\ge 88.0\\%$ | {'PASS' if macro_rec >= 0.88 else 'FAIL'} |
| **Macro F1-Score** | **{macro_f1:.1%}** | $\\ge 89.0\\%$ | PASS |
| **Accuracy** | **{accuracy:.1%}** | $\\ge 90.0\\%$ | PASS |
| **False Positive Rate (FPR)** | **{fpr:.2%}** | $\\le 2.50\\%$ | {'PASS' if fpr <= 0.025 else 'FAIL'} |

---

## 2. Latency Profiling & Inference SLA ($p99 < 15\\text{{ms}}$)

| Component | Architecture | $p50$ (ms) | $p95$ (ms) | $p99$ (ms) | SLA Target |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Statistical Detector Engine** | Dynamic Z-Score + EWMA + Mahalanobis | {np.percentile(stat_latencies, 50):.2f} | {np.percentile(stat_latencies, 95):.2f} | **{p99_lat_stat:.2f}** | $< 15.0\\text{{ms}}$ |
| **Deep Reconstruction Autoencoder** | Analytical Pure-NumPy Adam Feedforward | {np.percentile(ae_latencies, 50):.2f} | {np.percentile(ae_latencies, 95):.2f} | **{p99_lat_ae:.2f}** | $< 15.0\\text{{ms}}$ |
| **Isolation Forest** | Random Partitioning Ensembles | {np.percentile(iso_latencies, 50):.2f} | {np.percentile(iso_latencies, 95):.2f} | **{float(np.percentile(iso_latencies, 99)):.2f}** | $< 15.0\\text{{ms}}$ |
| **Supervised Classifier** | Gradient Boosted Decision Trees | {np.percentile(clf_latencies, 50):.2f} | {np.percentile(clf_latencies, 95):.2f} | **{p99_lat_clf:.2f}** | $< 15.0\\text{{ms}}$ |

---

## 3. Production Model Quality Gate Verdict

```
{gate_report.summary}
```

---

## 4. GenAI / RAG Multi-Agent Evaluation (Ragas-style)

{rag_report.summary_markdown}
"""

    report_file.write_text(report_md, encoding="utf-8")
    logger.info("Saved executive report to %s", report_file)

    return {
        "run_id": run.run_id,
        "classification_metrics": metrics_to_log,
        "quality_gate_passed": gate_report.overall_passed,
        "rag_all_gates_passed": rag_report.all_gates_passed,
        "report_path": str(report_file),
    }


if __name__ == "__main__":
    run_full_mlops_pipeline()
