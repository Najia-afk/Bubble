# Plan 01 — Security & Authentication

> **Agent Role:** Security Agent
> **Priority:** P0 (Critical)
> **Est. Effort:** 2-3 sessions
> **Dependencies:** None — do this FIRST

## Context

The Bubble platform has **zero authentication**. Every API endpoint, every admin page, every ML operation is publicly accessible. Default credentials (`bubble_password`, `dev-secret-key-change-in-production`) are hardcoded in settings.py. This is the #1 blocker for any production deployment.

## Objectives

### 1. JWT Authentication System
- [ ] Create `api/services/auth_service.py` — JWT token generation, validation, refresh
- [ ] Create `api/routes/auth_routes.py` — `/api/auth/login`, `/api/auth/refresh`, `/api/auth/logout`
- [ ] Create `api/application/user_models.py` — `User` model with `id`, `email`, `password_hash`, `role` (admin/analyst/viewer), `created_at`
- [ ] Add `Flask-JWT-Extended` + `bcrypt` to `config/requirements.txt`
- [ ] Add auth middleware decorator `@require_auth(role='analyst')` for route protection
- [ ] Add `init_db.py` migration to create `user` table + default admin user

### 2. Route Protection
- [ ] Protect all `/api/*` routes requiring at least `viewer` role
- [ ] Protect ML training/model endpoints requiring `analyst` role
- [ ] Protect admin endpoints (`/admin/*`, audit log) requiring `admin` role
- [ ] Keep `/api/health` and `/api/auth/*` public (no token required)
- [ ] Return 401/403 with clear error messages

### 3. Secrets Management
- [ ] Replace hardcoded `SECRET_KEY` in `config/settings.py` with `os.environ['SECRET_KEY']` (no default)
- [ ] Replace default DB password — require env var, fail fast if missing in production
- [ ] Add `.env.example` file with all required env vars documented
- [ ] Ensure `FLASK_ENV=production` enforces all secrets are set (no defaults)

### 4. API Security Hardening
- [ ] Add rate limiting via `Flask-Limiter` — 100 req/min for API, 10 req/min for auth
- [ ] Add CORS origin whitelist (not wildcard `*`)
- [ ] Add request size limits (10MB max)
- [ ] Add input validation on wallet address params (regex `^0x[a-fA-F0-9]{40}$`)
- [ ] Add SQL injection protection audit on raw query paths

### 5. Redis Security
- [ ] Add `requirepass` to Redis config in docker-compose.yml
- [ ] Update all `REDIS_URL` references to include password
- [ ] Add TLS option for prod compose

## Constraints

- Do NOT break the existing API contract — existing frontend calls must work
- JWT tokens should be passed as `Authorization: Bearer <token>` header
- Use `bcrypt` for password hashing, never store plaintext
- Default admin user: `admin@bubble.local` / password from env var `ADMIN_PASSWORD`
- Token expiry: access = 15min, refresh = 7 days

## Success Criteria

- [ ] `pytest` passes — no regressions
- [ ] `curl http://localhost:8080/api/investigations` returns 401 without token
- [ ] `curl -H "Authorization: Bearer <token>" http://localhost:8080/api/investigations` returns 200
- [ ] `/api/health` returns 200 without token
- [ ] No hardcoded credentials in any `.py` file (grep for 'password', 'secret')
- [ ] `.env.example` documents all required env vars

## Key Files

| File | Action |
|------|--------|
| `config/settings.py` | Modify — remove defaults, require env vars |
| `config/requirements.txt` | Modify — add Flask-JWT-Extended, bcrypt, Flask-Limiter |
| `api/services/auth_service.py` | Create |
| `api/routes/auth_routes.py` | Create |
| `api/application/user_models.py` | Create |
| `app.py` | Modify — register auth blueprint, init JWT |
| `scripts/init_db.py` | Modify — add user table + admin seed |
| `docker-compose.yml` | Modify — Redis requirepass |
| `.env.example` | Create |
| `static/swagger.json` | Modify — add security schemes |
