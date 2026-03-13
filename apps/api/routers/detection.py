"""Machine Learning Anomaly Detection & Incident Classification Router."""

import time

from fastapi import APIRouter, Depends

from apps.api.dependencies import MLEnsembleContainer, get_ml_ensemble
from apps.api.schemas import DetectionResponse
from data.schemas.events import TelemetrySnapshot

router = APIRouter(prefix="/v1", tags=["ML Anomaly Detection & Inference"])


@router.post(
    "/detect",
    response_model=DetectionResponse,
    summary="Multi-Model ML Anomaly Inference & Classification",
    description="Executes behavioral feature extraction, Deep Autoencoder reconstruction, Isolation Forest scoring, and XGBoost archetype classification.",
)
def detect_anomalies(
    snapshot: TelemetrySnapshot,
    ensemble: MLEnsembleContainer = Depends(get_ml_ensemble),
) -> DetectionResponse:
    """Run full ML diagnostic ensemble on telemetry snapshot."""
    start_t = time.perf_counter()

    # 1. Feature Extraction (streaming transform)
    stream_vec = ensemble.extractor.transform_snapshot(snapshot)

    # 2. Deep Autoencoder Inference & Attribution
    ae_mse, ae_is_anom, _ae_z, ae_attr = ensemble.autoencoder.score(stream_vec)
    top_features = [
        {"feature": k, "attribution_score": round(float(v), 4)}
        for k, v in sorted(ae_attr.items(), key=lambda kv: kv[1], reverse=True)[:4]
    ]

    # 3. Isolation Forest Scoring
    iso_score, iso_is_anom = ensemble.isolation_forest.score(stream_vec[0])

    # 4. XGBoost Archetype Classification
    _class_id, archetype_name, archetype_conf, _prob_dict = ensemble.classifier.predict(stream_vec)

    # Ensemble Weighted Score
    norm_ae = min(ae_mse / ensemble.autoencoder.threshold, 1.0) if ensemble.autoencoder.threshold > 0 else 0.0
    ensemble_score = 0.5 * norm_ae + 0.5 * iso_score

    overall_anomaly = bool(
        ae_is_anom or iso_is_anom or (archetype_name != "NOMINAL" and archetype_conf > 0.75)
    )
    inference_ms = (time.perf_counter() - start_t) * 1000.0

    # Prometheus Observability Instrumentation
    from apps.api.metrics import track_model_inference
    track_model_inference(
        archetype=str(archetype_name),
        confidence=float(archetype_conf),
        duration_seconds=inference_ms / 1000.0,
    )

    return DetectionResponse(
        service_id=snapshot.service_id,
        trace_id=snapshot.trace_id,
        is_anomaly=overall_anomaly,
        ensemble_anomaly_score=round(float(ensemble_score), 4),
        isolation_forest_anomaly=iso_is_anom,
        isolation_forest_score=round(float(iso_score), 4),
        autoencoder_reconstruction_error=round(float(ae_mse), 4),
        predicted_archetype=str(archetype_name),
        archetype_confidence=round(float(archetype_conf), 4),
        top_contributing_features=top_features,
        inference_time_ms=round(inference_ms, 2),
    )
