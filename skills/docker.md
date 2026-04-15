---
name: docker
description: Docker and container deployment guidance
version: 1.0.0
roles:
  architect: true
  engineer: true
  code_reviewer: true
  qa_engineer: true
  product_manager: false
  architect_reviewer: false
  pm_reviewer: false
tags: [docker, container, kubernetes, k8s, compose, dockerfile, helm, ci]
source: local
---

# Docker Skill

## For Architects
- Use multi-stage builds: `builder` stage compiles/installs, `runtime` stage is minimal (distroless or alpine)
- One service per container — no supervisord running multiple processes
- Externalise all config via environment variables; no baked-in environment-specific config
- Use named volumes for persistent data; never bind-mount host paths in production
- Health checks required on every service (`HEALTHCHECK` in Dockerfile or `healthcheck:` in compose)

## For Engineers
- Pin base image versions: `python:3.12.3-slim` not `python:latest`
- Run as non-root user: add `RUN useradd -m appuser && USER appuser`
- `.dockerignore` must exclude: `.git`, `node_modules`, `__pycache__`, `*.pyc`, `.env`
- Layer ordering: copy dependency files and install BEFORE copying source code (cache efficiency)
- Use `COPY --chown=appuser:appuser` when copying files for non-root containers

## For Code Reviewers
- Reject `FROM *:latest` — must pin a specific version tag
- Flag `USER root` in runtime stages
- Check `.dockerignore` exists and excludes sensitive files
- Verify `HEALTHCHECK` is defined
- Flag any secrets passed as `ENV` or `ARG` — use Docker secrets or runtime env injection

## For QA Engineers
- Run `docker scout cves` or `trivy image` to scan for known CVEs before release
- Test health check endpoint responds correctly before other tests start
- Verify container starts and passes health check within 30 seconds
- Test graceful shutdown: send `SIGTERM` and verify process exits cleanly within 10 seconds
- Integration test with `docker compose up` to verify all services connect
