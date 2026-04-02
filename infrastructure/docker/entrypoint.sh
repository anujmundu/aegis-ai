#!/usr/bin/env bash
# ==============================================================================
# AegisAI: Production Docker Container Entrypoint
# ==============================================================================
set -e

echo "[aegis-entrypoint] Initializing AegisAI Container Runtime..."

# Wait for PostgreSQL database if configured
if [ -n "$DATABASE_URL" ] || [ -n "$POSTGRES_HOST" ]; then
    DB_HOST="${POSTGRES_HOST:-postgres}"
    DB_PORT="${POSTGRES_PORT:-5432}"
    echo "[aegis-entrypoint] Checking PostgreSQL availability at ${DB_HOST}:${DB_PORT}..."
    
    python - <<EOF
import socket
import time
import sys

host = "${DB_HOST}"
port = int("${DB_PORT}")
timeout = 30
start = time.time()

while True:
    try:
        with socket.create_connection((host, port), timeout=2.0):
            print(f"[aegis-entrypoint] PostgreSQL is online at {host}:{port}")
            sys.exit(0)
    except (socket.timeout, ConnectionRefusedError, OSError):
        if time.time() - start > timeout:
            print(f"[aegis-entrypoint] Warning: PostgreSQL not reachable after {timeout}s. Proceeding anyway.")
            sys.exit(0)
        time.sleep(1.0)
EOF
fi

# Wait for Redis if configured
if [ -n "$REDIS_URL" ] || [ -n "$REDIS_HOST" ]; then
    REDIS_H="${REDIS_HOST:-redis}"
    REDIS_P="${REDIS_PORT:-6379}"
    echo "[aegis-entrypoint] Checking Redis availability at ${REDIS_H}:${REDIS_P}..."
    
    python - <<EOF
import socket
import time
import sys

host = "${REDIS_H}"
port = int("${REDIS_P}")
timeout = 15
start = time.time()

while True:
    try:
        with socket.create_connection((host, port), timeout=2.0):
            print(f"[aegis-entrypoint] Redis is online at {host}:{port}")
            sys.exit(0)
    except (socket.timeout, ConnectionRefusedError, OSError):
        if time.time() - start > timeout:
            print(f"[aegis-entrypoint] Warning: Redis not reachable after {timeout}s. Proceeding anyway.")
            sys.exit(0)
        time.sleep(1.0)
EOF
fi

echo "[aegis-entrypoint] Subsystems verified. Handing execution over to command: $@"
exec "$@"
