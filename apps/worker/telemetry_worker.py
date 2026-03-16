"""Continuous Telemetry Streaming & Background Ingestion Worker for AegisAI.

Role:
- Continuously generates multi-tier telemetry snapshots.
- Streams live telemetry to the AegisAI FastAPI microservice (`/v1/telemetry/snapshot`).
- Supports controlled incident injection scenarios for live observability demonstrations.
"""

import logging
import os
import signal
import time
from typing import Optional

import httpx

from data.schemas.events import AnomalyArchetype
from data.synthetic.telemetry_generator import MultiTierTelemetryGenerator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("aegisai.worker.telemetry")


class TelemetryStreamWorker:
    """Continuously publishes synthetic telemetry to the running AegisAI microservice."""

    def __init__(
        self,
        api_base_url: Optional[str] = None,
        tick_interval_seconds: float = 2.0,
        incident_interval_ticks: int = 50,
    ) -> None:
        self.api_base_url = api_base_url or os.getenv("AEGIS_API_URL", "http://aegis-api:8000")
        self.tick_interval_seconds = tick_interval_seconds
        self.incident_interval_ticks = incident_interval_ticks
        self.generator = MultiTierTelemetryGenerator(seed=int(time.time()))
        self.running = True

        signal.signal(signal.SIGINT, self._handle_exit)
        signal.signal(signal.SIGTERM, self._handle_exit)

    def _handle_exit(self, signum, frame):
        logger.info("Received termination signal (%s). Gracefully stopping telemetry worker...", signum)
        self.running = False

    def wait_for_api(self, max_retries: int = 30, retry_delay: float = 2.0) -> bool:
        """Poll API health endpoint until reachable."""
        health_url = f"{self.api_base_url}/v1/health"
        logger.info("Connecting to AegisAI API at %s...", health_url)

        with httpx.Client(timeout=3.0) as client:
            for attempt in range(1, max_retries + 1):
                try:
                    res = client.get(health_url)
                    if res.status_code == 200:
                        logger.info("Successfully connected to AegisAI API.")
                        return True
                except (httpx.ConnectError, httpx.TimeoutException, OSError):
                    pass

                logger.info(
                    "API not ready yet (attempt %d/%d). Retrying in %.1fs...",
                    attempt,
                    max_retries,
                    retry_delay,
                )
                time.sleep(retry_delay)

        logger.error("Could not reach AegisAI API after %d attempts.", max_retries)
        return False

    def run(self) -> None:
        """Start the continuous telemetry streaming loop."""
        logger.info("Starting Telemetry Stream Worker (tick_interval=%.1fs)...", self.tick_interval_seconds)

        if not self.wait_for_api():
            logger.warning("Proceeding in standalone generator mode (API unavailable).")

        tick_count = 0
        endpoint = f"{self.api_base_url}/v1/telemetry/snapshot"

        with httpx.Client(timeout=5.0) as client:
            while self.running:
                tick_count += 1

                # Select archetype: nominal by default, periodic incident for demo
                archetype = AnomalyArchetype.NOMINAL
                if tick_count % self.incident_interval_ticks == 0:
                    archetype = AnomalyArchetype.DB_CONNECTION_POOL_SATURATION
                    logger.warning("[DEMO] Injecting anomaly archetype: %s", archetype.value)

                snapshot = self.generator.generate_snapshot(archetype=archetype)

                try:
                    payload = snapshot.model_dump(mode="json")
                    res = client.post(endpoint, json=payload)
                    if res.status_code in (200, 201):
                        resp_data = res.json()
                        anom_status = resp_data.get("anomaly_detected", False)
                        logger.info(
                            "Tick #%d [%s] Service: %s, CPU: %.1f%%, Latency p99: %.1fms, Anomaly: %s",
                            tick_count,
                            snapshot.trace_id[:8],
                            snapshot.service_id,
                            snapshot.infrastructure.cpu_percent,
                            snapshot.application.latency_p99_ms,
                            anom_status,
                        )
                    else:
                        logger.warning("API responded with status %d: %s", res.status_code, res.text)
                except Exception as exc:
                    logger.warning("Failed to dispatch snapshot (tick #%d): %s", tick_count, exc)

                time.sleep(self.tick_interval_seconds)

        logger.info("Telemetry Stream Worker stopped cleanly.")


if __name__ == "__main__":
    worker = TelemetryStreamWorker()
    worker.run()
