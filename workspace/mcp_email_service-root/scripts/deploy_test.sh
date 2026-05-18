#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
COMPOSE_FILE="$PROJECT_ROOT/docker-compose.test.yml"
PROJECT="mcp-email-service-test"
MAX_WAIT=60
INTERVAL=3
EXIT_CODE=0

cleanup() {
    echo "==> Tearing down test stack..."
    docker compose -f "$COMPOSE_FILE" -p "$PROJECT" down -v --remove-orphans 2>/dev/null || true
}

trap cleanup EXIT

echo "==> Starting test stack..."
docker compose -f "$COMPOSE_FILE" -p "$PROJECT" up -d --build

echo "==> Waiting for mcp-email-service to become healthy..."
ELAPSED=0
while [ $ELAPSED -lt $MAX_WAIT ]; do
    HEALTH=$(docker compose -f "$COMPOSE_FILE" -p "$PROJECT" ps -q mcp-email-service 2>/dev/null | head -1)
    if [ -n "$HEALTH" ]; then
        STATUS=$(docker inspect --format='{{.State.Health.Status}}' "$HEALTH" 2>/dev/null || echo "starting")
        if [ "$STATUS" = "healthy" ]; then
            echo "   Service is healthy after ${ELAPSED}s"
            break
        fi
    fi
    sleep $INTERVAL
    ELAPSED=$((ELAPSED + INTERVAL))
done

if [ $ELAPSED -ge $MAX_WAIT ]; then
    echo "ERROR: Service did not become healthy within ${MAX_WAIT}s"
    docker compose -f "$COMPOSE_FILE" -p "$PROJECT" logs mcp-email-service
    exit 1
fi

PORT=$(docker compose -f "$COMPOSE_FILE" -p "$PROJECT" port mcp-email-service 8000 2>/dev/null | cut -d: -f2)
if [ -z "$PORT" ]; then
    PORT=8000
fi

export BASE_URL="http://localhost:${PORT}"
echo "==> Running smoke tests against ${BASE_URL}..."

cd "$PROJECT_ROOT"

if command -v pytest &>/dev/null; then
    pytest tests/test_deployment.py -v --tb=short || EXIT_CODE=$?
elif command -v python3 &>/dev/null; then
    python3 -m pytest tests/test_deployment.py -v --tb=short || EXIT_CODE=$?
else
    echo "ERROR: pytest not found. Install with: pip install pytest httpx"
    EXIT_CODE=1
fi

if [ $EXIT_CODE -eq 0 ]; then
    echo "==> All deployment smoke tests passed!"
else
    echo "==> Deployment smoke tests FAILED (exit code: ${EXIT_CODE})"
    docker compose -f "$COMPOSE_FILE" -p "$PROJECT" logs mcp-email-service
fi

exit $EXIT_CODE
