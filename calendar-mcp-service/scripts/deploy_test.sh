#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
COMPOSE_FILE="$PROJECT_DIR/docker-compose.test.yml"
BASE_URL="${BASE_URL:-http://localhost:8000}"
MAX_WAIT=60
INTERVAL=3

cleanup() {
    echo "🧹 Tearing down test stack..."
    docker compose -f "$COMPOSE_FILE" down --remove-orphans 2>/dev/null || true
}

trap cleanup EXIT

echo "🚀 Starting Calendar MCP Service test stack..."
docker compose -f "$COMPOSE_FILE" up -d --build

echo "⏳ Waiting for service to become healthy..."
elapsed=0
while [ $elapsed -lt $MAX_WAIT ]; do
    if curl -sf "$BASE_URL/health" > /dev/null 2>&1; then
        echo "✅ Service is healthy after ${elapsed}s"
        break
    fi
    sleep $INTERVAL
    elapsed=$((elapsed + INTERVAL))
done

if [ $elapsed -ge $MAX_WAIT ]; then
    echo "❌ Service failed to become healthy within ${MAX_WAIT}s"
    echo "📋 Container logs:"
    docker compose -f "$COMPOSE_FILE" logs
    exit 1
fi

echo "🧪 Running deployment smoke tests..."
cd "$PROJECT_DIR"
pip install -q httpx pytest > /dev/null 2>&1
python -m pytest tests/test_deployment.py -v --tb=short

TEST_RESULT=$?

if [ $TEST_RESULT -eq 0 ]; then
    echo "✅ All deployment smoke tests passed!"
else
    echo "❌ Smoke tests failed with exit code $TEST_RESULT"
    exit $TEST_RESULT
fi

exit 0
