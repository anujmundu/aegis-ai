"""AegisAI: Production AI Incident Intelligence & Autonomous Reliability Platform.

FastAPI Application Factory & ASGI Entrypoint.
"""

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from apps.api.dependencies import (
    get_contract_validator,
    get_hybrid_retriever,
    get_memory_coordinator,
    get_ml_ensemble,
    get_reliability_graph,
    get_statistical_engine,
)
from apps.api.middleware.observability import ObservabilityMiddleware
from apps.api.routers import analytics, detection, health, incidents, knowledge, telemetry

# Configure root logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("aegisai.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context manager initializing singletons and warming caches."""
    logger.info("Starting AegisAI Reliability Engine...")
    start_t = time.perf_counter()

    # Pre-warm singletons
    get_contract_validator()
    get_statistical_engine()
    get_ml_ensemble()
    get_hybrid_retriever()
    get_memory_coordinator()
    get_reliability_graph()

    warmup_s = time.perf_counter() - start_t
    logger.info("All subsystems pre-warmed in %.2fs. AegisAI Ready.", warmup_s)
    yield
    logger.info("Shutting down AegisAI Reliability Engine.")


def create_app() -> FastAPI:
    """Create and configure the production FastAPI application instance."""
    app = FastAPI(
        title="AegisAI — Autonomous Reliability Platform",
        description=(
            "Production AI Incident Intelligence & Autonomous Reliability Platform.\n\n"
            "Features:\n"
            "* Multi-Tier Telemetry Ingestion (Infra, App, DB, Business KPIs)\n"
            "* Real-Time Statistical Anomaly Detection (p99 < 15ms)\n"
            "* Deep Autoencoder + Isolation Forest + XGBoost Incident Classifier\n"
            "* Hybrid RRF Knowledge Retrieval (Runbooks & Postmortems)\n"
            "* LangGraph Multi-Agent Investigation & Anti-Hallucination Gate (>= 95% Grounding)\n"
            "* 3-Tier Stateful Operational Memory (Working, Episodic, Semantic)\n"
            "* Human-in-the-Loop Operator Remediation Safety Approval Webhooks\n"
        ),
        version="0.7.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # 1. CORS Middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 2. Prometheus Observability Middleware
    app.add_middleware(ObservabilityMiddleware)

    # 3. Timing and Correlation ID Middleware
    @app.middleware("http")
    async def add_process_time_and_correlation_id(request: Request, call_next):
        correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
        start_time = time.perf_counter()

        response: Response = await call_next(request)

        process_time_ms = (time.perf_counter() - start_time) * 1000.0
        response.headers["X-Process-Time-Ms"] = f"{process_time_ms:.2f}"
        response.headers["X-Correlation-ID"] = correlation_id
        return response

    # 3. Global Exception Handlers
    @app.exception_handler(HTTPException)
    async def custom_http_exception_handler(request: Request, exc: HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "status": "error",
                "code": exc.status_code,
                "detail": exc.detail,
                "path": str(request.url.path),
            },
        )

    # 4. Include Routers
    app.include_router(health.router)
    app.include_router(telemetry.router)
    app.include_router(detection.router)
    app.include_router(incidents.router)
    app.include_router(knowledge.router)
    app.include_router(analytics.router)

    # 5. Root Welcome Route
    @app.get("/", tags=["Root"])
    def root():
        return {
            "name": "AegisAI Autonomous Reliability Platform",
            "version": "0.7.0",
            "status": "ONLINE",
            "documentation": "/docs",
            "health_check": "/health",
            "metrics": "/metrics",
        }

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("apps.api.main:app", host="0.0.0.0", port=8000, reload=True)
