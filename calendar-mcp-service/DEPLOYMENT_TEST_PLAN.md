# Deployment Test Plan: Calendar MCP Service

## Services Tested
| Service | Port | Health Check |
|---------|------|--------------|
| calendar-mcp | 8000 | GET /health |

## Smoke Tests
| Test | Endpoint | Expected |
|------|----------|----------|
| Health check | GET /health | 200 OK, `{"status": "healthy", "version": "1.0.0"}` |
| Health content type | GET /health | 200 OK, `application/json` content type |
| MCP initialization | POST /initialize | 200 OK, protocolVersion `2024-11-05`, serverInfo present |
| MCP capabilities | POST /initialize | 200 OK, `tools` in capabilities |
| Tools discovery | POST /messages (`tools/list`) | 200 OK, all 6 tools listed with descriptions and schemas |
| Tools schema validation | POST /messages (`tools/list`) | Each tool has `description` and `inputSchema` |
| Unknown method error | POST /messages (`nonexistent/method`) | 200 OK, JSON-RPC error with code `-32601` |
| Unknown tool error | POST /messages (`tools/call` → `nonexistent_tool`) | 200 OK, JSON-RPC error present |
| SSE endpoint | GET /sse | 200 OK, `text/event-stream` content type |
| Unknown route (GET) | GET /nonexistent-route | 404 Not Found |
| Unknown route (POST) | POST /api/unknown | 404 Not Found |

## How to Run Locally
```bash
chmod +x scripts/deploy_test.sh
./scripts/deploy_test.sh
```

## CI Integration
These tests run in the `deploy-test` job in `.github/workflows/run-tests.yml`.

The `deploy_test.sh` script:
1. Builds and starts the Docker container via `docker compose -f docker-compose.test.yml up -d --build`
2. Waits up to 60s for the `/health` endpoint to respond
3. Runs `pytest tests/test_deployment.py -v --tb=short`
4. Tears down the container on exit (via trap)
5. Exits 0 on success, non-zero on failure

## Environment Configuration
| Variable | Value | Purpose |
|----------|-------|---------|
| `TESTING` | `true` | Disables external integrations in test mode |
| `DEFAULT_PROVIDER` | `google` | Sets default calendar provider |
| `GOOGLE_CLIENT_ID` | `test-client-id` | Stub OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | `test-client-secret` | Stub OAuth client secret |
| `OUTLOOK_CLIENT_ID` | `test-outlook-client-id` | Stub Outlook OAuth client ID |
| `OUTLOOK_CLIENT_SECRET` | `test-outlook-client-secret` | Stub Outlook OAuth client secret |
