# Plan 05 — Infrastructure & DevOps

> **Agent Role:** DevOps Agent
> **Priority:** P1 (High)
> **Est. Effort:** 2-3 sessions
> **Dependencies:** Plan 01 (secrets management must be done first)

## Context

Bubble runs on Docker Compose (6 containers: postgres, redis, web, celery, nginx, mlflow). There's no CI/CD, no monitoring, no log aggregation, and no Kubernetes manifests. ML models are saved to `/tmp/` (ephemeral). PostgreSQL exposes port 5432 on host. Redis has no password. TigerGraph is disabled. There are 20+ ad-hoc debug scripts in `scripts/`.

## Objectives

### 1. CI/CD Pipeline (GitHub Actions)
- [ ] Create `.github/workflows/ci.yml`:
  ```yaml
  on: [push, pull_request]
  jobs:
    test:
      - Setup Python 3.12
      - Install requirements
      - Run pytest --cov
      - Upload coverage report
    lint:
      - Run flake8/ruff
      - Run mypy (basic)
    build:
      - Build Docker images (don't push)
      - Verify compose up succeeds
  ```
- [ ] Create `.github/workflows/deploy.yml` (on push to `main`):
  - Build and push Docker images to registry
  - Deploy to staging/prod (placeholder — depends on hosting)
- [ ] Add branch protection rules documentation for `main` and `dev`

### 2. Docker Hardening
- [ ] `docker-compose.yml` changes:
  - Remove `ports: "5432:5432"` from postgres (keep only `expose`)
  - Add `requirepass` to Redis
  - Add resource limits (`mem_limit`, `cpus`) to all services
  - Add restart policies (`restart: unless-stopped`)
  - Add `models_data` volume for ML model persistence
- [ ] `docker-compose.prod.yml` overrides:
  - No port exposure except nginx:8080 (or 443 with TLS)
  - Production env vars only
  - Read-only filesystem where possible
  - Health check intervals tightened
- [ ] Create `docker/Dockerfile.web` optimizations:
  - Multi-stage build (builder + runtime)
  - Non-root user
  - `.dockerignore` review

### 3. Monitoring & Observability
- [ ] Add Prometheus container to `docker-compose.yml`
- [ ] Add `prometheus-flask-instrumentator` to web app
  - Request latency, status codes, active requests
- [ ] Add Celery Prometheus exporter for task metrics
- [ ] Create `docker/prometheus.yml` config scraping web + celery
- [ ] Add Grafana container with pre-built dashboard:
  - API latency P50/P95/P99
  - Error rate by endpoint
  - Celery task queue depth + duration
  - PostgreSQL connection pool stats
  - Redis memory usage
- [ ] Add structured logging (JSON format) for aggregation readiness
  - Update `utils/logging_config.py` to output JSON in production

### 4. Log Management
- [ ] Consolidate all log outputs:
  - `logs/` directory is volume-mounted — good
  - Add log rotation (max 100MB per file, keep 5 rotations)
  - Configure gunicorn access log format to include request_id
- [ ] Add request_id middleware to Flask app:
  - Generate UUID per request
  - Include in all log lines
  - Return in response headers (`X-Request-ID`)

### 5. Database Management
- [ ] Create `scripts/migrate.py` — Alembic migration setup
  - `alembic init` + configuration
  - Generate initial migration from current models
  - Add `alembic upgrade head` to Docker entrypoint
- [ ] Add PostgreSQL connection pooling config in `config/settings.py`:
  - `SQLALCHEMY_POOL_SIZE = 10`
  - `SQLALCHEMY_MAX_OVERFLOW = 20`
  - `SQLALCHEMY_POOL_TIMEOUT = 30`
- [ ] Add DB backup script: `scripts/backup_db.sh`
  - `pg_dump` to timestamped file
  - Keep last 7 daily backups
  - Cron job in docker-compose (or separate backup service)

### 6. Script Cleanup
- [ ] Audit all 20+ `_`-prefixed scripts in `scripts/`:
  - Identify which are still useful → promote to proper CLI commands
  - Identify which are obsolete → delete
  - Create `scripts/cli.py` using Click/Typer for consolidated commands:
    ```
    bubble init-db
    bubble train-model
    bubble run-pipeline --case-id=X
    bubble backup-db
    bubble check-health
    ```
- [ ] Remove dead imports and unused notebook helper files

### 7. Nginx Configuration
- [ ] Review `docker/nginx.conf` for security headers:
  - `X-Frame-Options: DENY`
  - `X-Content-Type-Options: nosniff`
  - `Content-Security-Policy`
  - `Strict-Transport-Security` (prep for HTTPS)
- [ ] Add gzip compression for API responses
- [ ] Add rate limiting at nginx level (backup to app-level)
- [ ] Add request body size limit (`client_max_body_size 10m`)

## Constraints

- Don't break the existing `docker compose up` workflow
- Keep `docker-compose.yml` for dev, `docker-compose.prod.yml` for production
- GitHub Actions should not require paid features
- Monitoring stack (Prometheus/Grafana) should be opt-in (separate compose profile)
- Database migrations must be backwards-compatible

## Success Criteria

- [ ] `git push` triggers CI: lint + test + build
- [ ] `docker compose up` still works with no manual config
- [ ] `docker compose --profile monitoring up` starts Prometheus + Grafana
- [ ] PostgreSQL port not exposed on host in prod compose
- [ ] Redis requires password
- [ ] ML models persist across `docker compose down && docker compose up`
- [ ] Structured JSON logs in production mode
- [ ] DB migrations via Alembic work

## Key Files

| File | Action |
|------|--------|
| `.github/workflows/ci.yml` | Create |
| `.github/workflows/deploy.yml` | Create |
| `docker-compose.yml` | Modify — security, volumes, limits |
| `docker-compose.prod.yml` | Modify — production hardening |
| `docker/nginx.conf` | Modify — security headers, gzip |
| `docker/prometheus.yml` | Create |
| `docker/grafana/dashboard.json` | Create |
| `utils/logging_config.py` | Modify — JSON structured logging |
| `scripts/cli.py` | Create — consolidated CLI |
| `scripts/migrate.py` | Create — Alembic setup |
| `config/settings.py` | Modify — pool config, monitoring |
| `config/requirements.txt` | Modify — add prometheus, alembic |
