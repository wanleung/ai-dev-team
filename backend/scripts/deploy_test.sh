#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(dirname "$SCRIPT_DIR")"
PROJECT_DIR="$(dirname "$BACKEND_DIR")"
COMPOSE_FILE="$PROJECT_DIR/docker-compose.test.yml"
BASE_URL="${BASE_URL:-http://localhost:8099}"
MAX_WAIT=60
INTERVAL=3

cleanup() {
    echo "Tearing down test stack..."
    docker compose -f "$COMPOSE_FILE" down --remove-orphans 2>/dev/null || true
}

trap cleanup EXIT

echo "=== Deployment Smoke Test ==="
echo "Project: WordPress Database Integration Feature"
echo "Base URL: $BASE_URL"
echo ""

# Start the stack
echo "[1/4] Starting test stack..."
docker compose -f "$COMPOSE_FILE" up -d --build

# Wait for health
echo "[2/4] Waiting for service to be healthy..."
elapsed=0
while [ $elapsed -lt $MAX_WAIT ]; do
    if curl -sf "${BASE_URL}/health" > /dev/null 2>&1; then
        echo "Service is healthy after ${elapsed}s"
        break
    fi
    sleep $INTERVAL
    elapsed=$((elapsed + INTERVAL))
done

if [ $elapsed -ge $MAX_WAIT ]; then
    echo "FAIL: Service did not become healthy within ${MAX_WAIT}s"
    docker compose -f "$COMPOSE_FILE" logs
    exit 1
fi

# Run smoke tests
echo "[3/4] Running smoke tests..."
cd "$PROJECT_DIR"
if ! command -v pytest > /dev/null 2>&1; then
    echo "Installing test dependencies..."
    python3 -m pip install --break-system-packages pytest httpx > /dev/null 2>&1
fi
BASE_URL="$BASE_URL" python3 -m pytest backend/tests/test_deployment.py -v --tb=short

TEST_EXIT=$?

if [ $TEST_EXIT -ne 0 ]; then
    echo ""
    echo "FAIL: Smoke tests failed (exit code: $TEST_EXIT)"
    docker compose -f "$COMPOSE_FILE" logs
    exit $TEST_EXIT
fi

echo ""
echo "[4/4] All smoke tests passed!"
echo "=== Deployment Test Complete ==="
exit 0
