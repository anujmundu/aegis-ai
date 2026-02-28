# ==============================================================================
# AegisAI: Production Multi-Stage Slim Dockerfile
# Target: Python 3.11 Debian Bookworm Slim
# ==============================================================================

# ------------------------------------------------------------------------------
# Stage 1: Build & Dependencies Compiler
# ------------------------------------------------------------------------------
FROM python:3.11-slim-bookworm AS builder

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install wheel & pip upgrades
RUN pip install --upgrade pip setuptools wheel

# Install dependencies from requirements.txt
COPY requirements.txt .
RUN pip install -r requirements.txt


# ------------------------------------------------------------------------------
# Stage 2: Hardened Runtime Container
# ------------------------------------------------------------------------------
FROM python:3.11-slim-bookworm AS runtime

LABEL maintainer="Anuj Mundu <anujmundu@users.noreply.github.com>" \
      description="AegisAI: Production AI Incident Intelligence & Autonomous Reliability Platform" \
      version="0.1.0"

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/app" \
    HOME="/home/aegis"

# Install runtime utilities only (curl for healthcheck, libpq5 for PostgreSQL)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libpq5 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create non-root system user and group (UID/GID 10001)
RUN groupadd -g 10001 aegis && \
    useradd -u 10001 -g aegis -m -s /bin/bash -d /home/aegis aegis

# Copy compiled virtual environment from builder stage
COPY --from=builder /opt/venv /opt/venv

WORKDIR /app

# Copy application source directories with non-root ownership
COPY --chown=aegis:aegis apps/ /app/apps/
COPY --chown=aegis:aegis ai/ /app/ai/
COPY --chown=aegis:aegis ml/ /app/ml/
COPY --chown=aegis:aegis data/ /app/data/
COPY --chown=aegis:aegis infrastructure/ /app/infrastructure/
COPY --chown=aegis:aegis pyproject.toml /app/pyproject.toml
COPY --chown=aegis:aegis README.md /app/README.md

# Make entrypoint script executable and secure directory permissions
RUN chmod +x /app/infrastructure/docker/entrypoint.sh && \
    mkdir -p /app/data/vector_index /app/experiments && \
    chown -R aegis:aegis /app /home/aegis

# Switch to non-root execution
USER aegis

# Expose standard REST API port
EXPOSE 8000

# Container healthcheck querying FastAPI liveness endpoint
HEALTHCHECK --interval=15s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/v1/health || exit 1

ENTRYPOINT ["/app/infrastructure/docker/entrypoint.sh"]
CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
