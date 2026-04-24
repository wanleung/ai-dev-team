#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
COMPOSE_FILE="$PROJECT_DIR/docker-compose.test.yml"
BASE_URL="${BASE_URL:-http://localhost:8000}"
MAX_WAIT=60
INTERVAL=3

cleanup() {
    echo "==> Tearing down test stack..."
    docker compose -f "$COMPOSE_FILE" down --remove-orphans 2>/dev/null || true
}

trap cleanup EXIT

echo "==> Starting test stack..."
docker compose -f "$COMPOSE_FILE" up -d --build

echo "==> Waiting for backend to become healthy..."
elapsed=0
while [ $elapsed -lt $MAX_WAIT ]; do
    if python -c "import urllib.request; urllib.request.urlopen('${BASE_URL}/health')" 2>/dev/null; then
        echo "==> Backend is healthy after ${elapsed}s"
        break
    fi
    sleep $INTERVAL
    elapsed=$((elapsed + INTERVAL))
done

if [ $elapsed -ge $MAX_WAIT ]; then
    echo "==> ERROR: Backend did not become healthy within ${MAX_WAIT}s"
    docker compose -f "$COMPOSE_FILE" logs
    exit 1
fi

echo "==> Running deployment smoke tests..."
cd "$PROJECT_DIR"
export BASE_URL

if command -v pytest &> /dev/null; then
    pytest tests/test_deployment.py -v --tb=short
else
    pip install pytest httpx -q
    pytest tests/test_deployment.py -v --tb=short
fi

TEST_EXIT=$?

if [ $TEST_EXIT -eq 0 ]; then
    echo "==> All smoke tests passed!"
else
    echo "==> Smoke tests failed with exit code ${TEST_EXIT}"
    docker compose -f "$COMPOSE_FILE" logs
fi

exit $TEST_EXIT
