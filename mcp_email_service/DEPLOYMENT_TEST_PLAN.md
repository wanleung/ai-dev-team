# Deployment Test Plan: MCP Email Service (IMAP Integration)

## Services Tested
| Service | Port | Health Check |
|---------|------|--------------|
| mcp-email-service | 8000 | GET /health |

## Smoke Tests
| Test | Endpoint | Expected |
|------|----------|----------|
| Health check | GET /health | 200 OK with status=healthy |
| List accounts | GET /api/accounts | 200 OK with items/total |
| Create account | POST /api/accounts | 201 Created with account data |
| Get account by ID | GET /api/accounts/{id} | 200 OK with account details |
| Get nonexistent account | GET /api/accounts/99999 | 404 Not Found |
| List emails | GET /api/emails | 200 OK with items/total |
| Search emails | GET /api/emails?search=keyword | 200 OK with empty results |
| Get nonexistent email | GET /api/emails/99999 | 404 Not Found |
| Mark nonexistent email read | PATCH /api/emails/99999/read | 404 Not Found |
| Protected endpoint without auth | GET /api/accounts/1/emails/1/attachments/1 | 401 Unauthorized |
| Unknown route | GET /api/v1/nonexistent | 404 Not Found |

## How to Run Locally
```bash
chmod +x scripts/deploy_test.sh
./scripts/deploy_test.sh
```

## CI Integration
These tests run in the `deploy-test` job in `.github/workflows/run-tests.yml`.

## Test Configuration
- **Database**: SQLite (aiosqlite) - no external database required
- **Authentication**: X-User-ID header (simplified for testing)
- **Environment**: TESTING=true, DEBUG=true, SECRET_KEY=test-secret-key-for-deployment-tests
- **Health Check**: HTTP GET /health with 5s interval, 10 retries, 10s start period

## Cleanup
All test data is automatically cleaned up when the test script exits (docker compose down -v).
