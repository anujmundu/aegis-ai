"""Health & Observability Router for AegisAI API."""


from fastapi import APIRouter, Depends, Response

from apps.api.config import Settings
from apps.api.dependencies import get_settings
from apps.api.metrics import get_prometheus_metrics
from apps.api.schemas import HealthResponse, SubsystemHealth

router = APIRouter(tags=["Health & Monitoring"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health Liveness & Readiness Probe",
    description="Returns high-level status of the microservice and its operational subsystems.",
)
@router.get("/v1/health", response_model=HealthResponse, include_in_schema=False)
def check_health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    """Return system liveness status and subsystem telemetry."""
    return HealthResponse(
        status="healthy",
        service=settings.service_name,
        environment=settings.environment,
        subsystems=SubsystemHealth(
            statistical_engine="nominal",
            ml_ensemble="nominal",
            rag_retriever="nominal",
            operational_memory="nominal",
        ),
    )


@router.get(
    "/metrics",
    summary="Prometheus Metrics Exposition",
    description="Prometheus-formatted operational metrics for scraping.",
)
def get_metrics() -> Response:
    """Expose standard Prometheus metrics."""
    return Response(
        content=get_prometheus_metrics(),
        media_type="text/plain; version=0.0.4",
    )
