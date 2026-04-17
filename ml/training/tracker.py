"""MLOps Experiment Tracking & Model Registry Engine for AegisAI.

Provides:
- Parameter, metric, and artifact logging
- Confusion matrix serialization and reporting
- Dual-mode backend: Native MLflow integration with graceful local file-based fallback
- Model Registry abstraction tracking model versions, stages, and quality gate verdicts
"""

import json
import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("aegisai.mlops.tracker")


class MLOpsRun:
    """Represents an active or completed experiment run."""

    def __init__(
        self,
        run_id: str,
        run_name: str,
        experiment_name: str,
        run_dir: Path,
        mlflow_run: Optional[Any] = None,
        tracker: Optional[Any] = None,
    ) -> None:
        self.run_id = run_id
        self.run_name = run_name
        self.experiment_name = experiment_name
        self.run_dir = run_dir
        self.mlflow_run = mlflow_run
        self.tracker = tracker
        self.start_time = time.time()
        self.params: Dict[str, Any] = {}
        self.metrics: Dict[str, float] = {}
        self.tags: Dict[str, str] = {}
        self.status = "RUNNING"

    def __enter__(self) -> "MLOpsRun":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self.tracker:
            status = "FAILED" if exc_type else "FINISHED"
            self.tracker.end_run(status=status)


class MLOpsTracker:
    """Central MLOps Experiment Tracking and Model Registry client."""

    def __init__(
        self,
        experiment_name: str = "aegisai-anomaly-benchmark",
        tracking_uri: Optional[str] = None,
        base_dir: Optional[Path] = None,
    ) -> None:
        self.experiment_name = experiment_name
        self.tracking_uri = tracking_uri
        self.base_dir = base_dir or (
            Path(__file__).resolve().parent.parent.parent / "experiments" / experiment_name
        )
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.registry_file = self.base_dir.parent / "model_registry.json"

        self._active_run: Optional[MLOpsRun] = None
        self._mlflow = None

        # Attempt MLflow initialization
        try:
            import mlflow
            if tracking_uri:
                mlflow.set_tracking_uri(tracking_uri)
            mlflow.set_experiment(experiment_name)
            self._mlflow = mlflow
            logger.info("MLOpsTracker connected to MLflow backend (experiment='%s')", experiment_name)
        except Exception as e:
            logger.info("MLflow offline or unavailable (%s); operating in local structured mode.", e)
            self._mlflow = None

    @property
    def is_mlflow_connected(self) -> bool:
        """Return True if connected to an active MLflow tracking backend."""
        return self._mlflow is not None

    def start_run(self, run_name: Optional[str] = None) -> MLOpsRun:
        """Start a new experiment tracking run."""
        run_id = f"run-{uuid.uuid4().hex[:10]}"
        name = run_name or f"run-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"

        run_dir = self.base_dir / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "artifacts").mkdir(parents=True, exist_ok=True)

        mlflow_active_run = None
        if self._mlflow:
            try:
                if self._mlflow.active_run():
                    self._mlflow.end_run()
                mlflow_active_run = self._mlflow.start_run(run_name=name)
            except Exception as e:
                logger.warning("Failed to start MLflow run: %s", e)

        run = MLOpsRun(
            run_id=run_id,
            run_name=name,
            experiment_name=self.experiment_name,
            run_dir=run_dir,
            mlflow_run=mlflow_active_run,
            tracker=self,
        )
        self._active_run = run
        return run

    def log_param(self, key: str, value: Any) -> None:
        """Log a single hyperparameter."""
        if not self._active_run:
            raise RuntimeError("No active MLOps run. Call start_run() first.")

        self._active_run.params[key] = value
        if self._mlflow and self._active_run.mlflow_run:
            try:
                self._mlflow.log_param(key, value)
            except Exception as e:
                logger.warning("MLflow log_param failed: %s", e)

    def log_params(self, params: Dict[str, Any]) -> None:
        """Log multiple hyperparameters."""
        for k, v in params.items():
            self.log_param(k, v)

    def log_metric(self, key: str, value: float, step: Optional[int] = None) -> None:
        """Log a scalar metric."""
        if not self._active_run:
            raise RuntimeError("No active MLOps run. Call start_run() first.")

        self._active_run.metrics[key] = float(value)
        if self._mlflow and self._active_run.mlflow_run:
            try:
                self._mlflow.log_metric(key, float(value), step=step)
            except Exception as e:
                logger.warning("MLflow log_metric failed: %s", e)

    def log_metrics(self, metrics: Dict[str, float], step: Optional[int] = None) -> None:
        """Log multiple metrics."""
        for k, v in metrics.items():
            self.log_metric(k, v, step=step)

    def log_artifact(self, filepath: Path, artifact_path: Optional[str] = None) -> None:
        """Save a local file artifact to the run's artifact directory."""
        if not self._active_run:
            raise RuntimeError("No active MLOps run. Call start_run() first.")

        dest_dir = self._active_run.run_dir / "artifacts"
        if artifact_path:
            dest_dir = dest_dir / artifact_path
            dest_dir.mkdir(parents=True, exist_ok=True)

        dest_file = dest_dir / filepath.name
        dest_file.write_bytes(filepath.read_bytes())

        if self._mlflow and self._active_run.mlflow_run:
            try:
                self._mlflow.log_artifact(str(filepath), artifact_path=artifact_path)
            except Exception as e:
                logger.warning("MLflow log_artifact failed: %s", e)

    def log_dict(self, dictionary: Dict[str, Any], filename: str) -> None:
        """Save a Python dictionary as a JSON artifact."""
        if not self._active_run:
            raise RuntimeError("No active MLOps run. Call start_run() first.")

        art_file = self._active_run.run_dir / "artifacts" / filename
        art_file.parent.mkdir(parents=True, exist_ok=True)
        with open(art_file, "w", encoding="utf-8") as f:
            json.dump(dictionary, f, indent=2)

        if self._mlflow and self._active_run.mlflow_run:
            try:
                self._mlflow.log_dict(dictionary, filename)
            except Exception as e:
                logger.warning("MLflow log_dict failed: %s", e)

    def log_confusion_matrix(
        self,
        matrix_dict: Dict[str, Any],
        filename: str = "confusion_matrix.json",
    ) -> None:
        """Log confusion matrix data artifact."""
        self.log_dict(matrix_dict, filename)

    def set_tag(self, key: str, value: str) -> None:
        """Set an operational metadata tag on the active run."""
        if not self._active_run:
            raise RuntimeError("No active MLOps run. Call start_run() first.")

        self._active_run.tags[key] = value
        if self._mlflow and self._active_run.mlflow_run:
            try:
                self._mlflow.set_tag(key, value)
            except Exception as e:
                logger.warning("MLflow set_tag failed: %s", e)

    def end_run(self, status: str = "FINISHED") -> None:
        """Complete the active run and flush manifest to disk."""
        if not self._active_run:
            return

        run = self._active_run
        run.status = status
        duration = time.time() - run.start_time

        # Persist local run manifest
        manifest = {
            "run_id": run.run_id,
            "run_name": run.run_name,
            "experiment_name": run.experiment_name,
            "status": run.status,
            "duration_seconds": round(duration, 3),
            "start_time": run.start_time,
            "end_time": time.time(),
            "params": run.params,
            "metrics": run.metrics,
            "tags": run.tags,
        }

        with open(run.run_dir / "manifest.json", "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        if self._mlflow and run.mlflow_run:
            try:
                self._mlflow.end_run(status=status)
            except Exception as e:
                logger.warning("MLflow end_run failed: %s", e)

        self._active_run = None

    def register_model(
        self,
        model_name: str,
        version: str,
        stage: str,
        metrics: Dict[str, float],
        passed_quality_gate: bool,
    ) -> Dict[str, Any]:
        """Register a model artifact in the central Model Registry."""
        registry: List[Dict[str, Any]] = []
        if self.registry_file.exists():
            try:
                with open(self.registry_file, "r", encoding="utf-8") as f:
                    registry = json.load(f)
            except Exception:
                registry = []

        entry = {
            "model_name": model_name,
            "version": version,
            "stage": stage,  # Production | Staging | Archived
            "passed_quality_gate": passed_quality_gate,
            "metrics": metrics,
            "registered_at": datetime.now(timezone.utc).isoformat(),
        }

        # If promoting to Production, demote previous production versions to Archived
        if stage == "Production" and passed_quality_gate:
            for item in registry:
                if item.get("model_name") == model_name and item.get("stage") == "Production":
                    item["stage"] = "Archived"

        registry.append(entry)

        with open(self.registry_file, "w", encoding="utf-8") as f:
            json.dump(registry, f, indent=2)

        return entry

    def get_registered_models(self) -> List[Dict[str, Any]]:
        """List all entries in the model registry."""
        if not self.registry_file.exists():
            return []
        try:
            with open(self.registry_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        status = "FAILED" if exc_type else "FINISHED"
        self.end_run(status=status)
