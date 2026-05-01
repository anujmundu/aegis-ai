"""Unit and Integration Tests for MLOps, Experiment Tracking & Automated Evaluation (Phase 8).

Covers:
- ModelQualityGate (enforcing precision >= 0.90, recall >= 0.88, FPR <= 0.025, p99 latency < 15ms)
- MLOpsTracker (run lifecycle, hyperparameter, metric, confusion matrix, artifact logging, model registry)
- RAGEvaluator (faithfulness, context precision, context recall, remediation action appropriateness)
- Full End-to-End MLOps Pipeline Runner (model training, evaluation, gate check, artifact export)
"""

from pathlib import Path

import pytest

from ai.evaluation.ragas_evaluator import RAGEvaluator
from ml.evaluation.quality_gate import ModelQualityGate, QualityGateFailureError
from ml.evaluation.run_eval_pipeline import run_full_mlops_pipeline
from ml.training.tracker import MLOpsTracker


class TestModelQualityGate:
    """Tests for production Model Quality Gate."""

    def test_passing_quality_gate(self):
        gate = ModelQualityGate(
            min_precision=0.90,
            min_recall=0.88,
            max_fpr=0.025,
            max_p99_latency_ms=15.0,
        )
        metrics = {
            "precision": 0.945,
            "recall": 0.920,
            "fpr": 0.012,
            "p99_latency_ms": 3.8,
        }
        report = gate.evaluate("incident_classifier", metrics, version="0.7.0")
        assert report.overall_passed is True
        assert report.verdict == "PROMOTED_TO_PRODUCTION"
        assert all(c.passed for c in report.checks)

        # Enforce should not raise
        enforced = gate.enforce("incident_classifier", metrics, version="0.7.0")
        assert enforced.overall_passed is True

    def test_failing_quality_gate_precision(self):
        gate = ModelQualityGate(min_precision=0.90)
        metrics = {
            "precision": 0.84,  # Below 0.90
            "recall": 0.91,
            "fpr": 0.01,
            "p99_latency_ms": 4.5,
        }
        report = gate.evaluate("candidate_model", metrics)
        assert report.overall_passed is False
        assert report.verdict == "REJECTED_QUALITY_FAILURE"

        with pytest.raises(QualityGateFailureError, match="rejected by Quality Gate"):
            gate.enforce("candidate_model", metrics)

    def test_failing_quality_gate_latency(self):
        gate = ModelQualityGate(max_p99_latency_ms=15.0)
        metrics = {
            "precision": 0.95,
            "recall": 0.93,
            "fpr": 0.01,
            "p99_latency_ms": 22.4,  # Violates 15ms SLA
        }
        report = gate.evaluate("slow_model", metrics)
        assert report.overall_passed is False
        assert report.verdict == "REJECTED_QUALITY_FAILURE"


class TestMLOpsTracker:
    """Tests for MLOpsTracker local file tracking and model registry."""

    def test_run_lifecycle_and_artifacts(self, tmp_path: Path):
        tracker = MLOpsTracker(
            experiment_name="test-experiment",
            base_dir=tmp_path / "experiments" / "test-experiment",
        )

        with tracker.start_run("test-run-001") as run:
            tracker.log_param("learning_rate", 0.01)
            tracker.log_param("model_type", "xgboost")
            tracker.log_metric("accuracy", 0.955)
            tracker.log_metric("f1_score", 0.948)
            tracker.set_tag("environment", "test")

            # Log dictionary and confusion matrix artifacts
            sample_cm = {"matrix": [[50, 2], [1, 47]], "classes": ["NOMINAL", "ANOMALY"]}
            tracker.log_confusion_matrix(sample_cm)

            # Log custom file artifact
            dummy_file = tmp_path / "dummy_weights.bin"
            dummy_file.write_bytes(b"MODEL_BINARY_WEIGHTS_12345")
            tracker.log_artifact(dummy_file, artifact_path="checkpoints")

        # Inspect persisted manifest
        manifest_path = run.run_dir / "manifest.json"
        assert manifest_path.exists()

        import json
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert data["run_name"] == "test-run-001"
        assert data["status"] == "FINISHED"
        assert data["params"]["learning_rate"] == 0.01
        assert data["metrics"]["accuracy"] == 0.955
        assert (run.run_dir / "artifacts" / "confusion_matrix.json").exists()
        assert (run.run_dir / "artifacts" / "checkpoints" / "dummy_weights.bin").exists()

    def test_model_registry_versioning(self, tmp_path: Path):
        tracker = MLOpsTracker(
            experiment_name="test-registry",
            base_dir=tmp_path / "experiments" / "test-registry",
        )

        # Register v1
        entry_v1 = tracker.register_model(
            model_name="incident_classifier",
            version="1.0.0",
            stage="Production",
            metrics={"f1": 0.91},
            passed_quality_gate=True,
        )
        assert entry_v1["stage"] == "Production"

        # Register v2 as Production
        entry_v2 = tracker.register_model(
            model_name="incident_classifier",
            version="2.0.0",
            stage="Production",
            metrics={"f1": 0.96},
            passed_quality_gate=True,
        )
        assert entry_v2["stage"] == "Production"

        # Verify v1 was demoted to Archived
        models = tracker.get_registered_models()
        assert len(models) == 2
        v1_entry = next(m for m in models if m["version"] == "1.0.0")
        v2_entry = next(m for m in models if m["version"] == "2.0.0")
        assert v1_entry["stage"] == "Archived"
        assert v2_entry["stage"] == "Production"


class TestRAGEvaluator:
    """Tests for GenAI RAG Reliability and Grounding Evaluator."""

    def test_rag_synthetic_benchmark(self):
        from ai.agents.graph import ReliabilityGraph
        graph = ReliabilityGraph()
        evaluator = RAGEvaluator()

        report = evaluator.run_benchmark(graph)
        assert report.total_scenarios_evaluated == 5
        assert report.macro_faithfulness >= 0.95
        assert report.macro_context_precision >= 0.70
        assert report.macro_context_recall >= 0.80
        assert report.action_accuracy == 1.0
        assert report.all_gates_passed is True
        assert len(report.scenario_breakdown) == 5
        assert "Automated GenAI & RAG Reliability Benchmark Report" in report.summary_markdown


class TestFullMLOpsPipelineRunner:
    """Tests for the full end-to-end MLOps pipeline."""

    def test_run_eval_pipeline_end_to_end(self, tmp_path: Path):
        result = run_full_mlops_pipeline(output_dir=tmp_path)
        assert "run_id" in result
        assert result["quality_gate_passed"] is True
        assert result["rag_all_gates_passed"] is True
        assert Path(result["report_path"]).exists()

        report_text = Path(result["report_path"]).read_text(encoding="utf-8")
        assert "AegisAI: MLOps Evaluation & Reliability Benchmark Report" in report_text
        assert "Macro Precision" in report_text
        assert "Latency Profiling" in report_text
