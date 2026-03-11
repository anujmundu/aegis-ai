"""Production HTTP Observability & Request Tracing Middleware.

Role:
- Instruments all incoming HTTP calls with Prometheus latency histograms and counters.
- Normalizes parametrized endpoints to prevent high-cardinality metric pollution.
- Injects standard tracing and response timing headers (`X-Response-Time`, `X-Trace-ID`).
"""

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from apps.api.metrics import track_http_request


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """Middleware for automated Prometheus HTTP instrumentation and request tracing."""

    async def dispatch(self, request: Request, call_next) -> Response:
        trace_id = request.headers.get("X-Trace-ID") or f"tr-{uuid.uuid4().hex[:12]}"
        start_time = time.perf_counter()

        status_code = 500
        try:
            response: Response = await call_next(request)
            status_code = response.status_code
        except Exception:
            duration = time.perf_counter() - start_time
            endpoint = self._resolve_endpoint_path(request)
            track_http_request(request.method, endpoint, 500, duration)
            raise

        duration = time.perf_counter() - start_time
        endpoint = self._resolve_endpoint_path(request)
        track_http_request(request.method, endpoint, status_code, duration)

        # Inject operational tracing headers
        response.headers["X-Response-Time"] = f"{duration * 1000.0:.2f}ms"
        response.headers["X-Trace-ID"] = trace_id

        return response

    def _resolve_endpoint_path(self, request: Request) -> str:
        """Resolve route template to avoid label explosion on dynamic path parameters."""
        route = request.scope.get("route")
        if route and hasattr(route, "path"):
            return route.path

        # Basic path parameter normalization fallback
        path = request.url.path
        parts = path.split("/")
        normalized = []
        for p in parts:
            # Mask potential UUIDs or numeric IDs
            if len(p) > 20 or p.isdigit() or p.startswith("tr-") or p.startswith("INC-"):
                normalized.append("{id}")
            else:
                normalized.append(p)
        return "/".join(normalized) or "/"
