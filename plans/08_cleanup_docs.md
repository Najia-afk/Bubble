# Plan 08 — Code Cleanup & Documentation

> **Agent Role:** Docs Agent
> **Priority:** P3 (Low)
> **Est. Effort:** 1 session
> **Dependencies:** All other plans (run last to document final state)

## Context

There are two doc directories (`doc/` and `docs/`), 20+ undocumented debug scripts, no contribution guide, no deployment guide, no changelog, and no data dictionary. The Swagger spec says "no auth" and "no rate limits." Some notebook helper files may be dead code.

## Objectives

### 1. Consolidate Documentation
- [ ] Merge `docs/` into `doc/` (move `docs/ML_ANALYSIS_REPORT.md` → `doc/ML_ANALYSIS_REPORT.md`)
- [ ] Move `docs/archive/` → `doc/archive/`
- [ ] Delete `docs/` directory
- [ ] Update all internal references to the new paths

### 2. Create Missing Docs
- [ ] Create `CONTRIBUTING.md` (root):
  - Development setup (Docker, Python, .env)
  - Branch strategy (dev → main)
  - PR process
  - Test requirements (run `pytest --cov` before submitting)
  - Code style (Python 3.12, type hints encouraged, max line 120)
- [ ] Create `doc/DEPLOYMENT.md`:
  - Production docker-compose.prod.yml usage
  - Required env vars (reference `.env.example`)
  - Database migration steps
  - SSL/TLS setup with nginx
  - Monitoring access (Prometheus/Grafana)
  - Backup/restore procedures
- [ ] Create `doc/DATA_DICTIONARY.md`:
  - Full schema for every table (columns, types, constraints)
  - Entity relationship diagram (Mermaid)
  - Index documentation
  - Common queries
- [ ] Create `CHANGELOG.md` (root):
  - Backfill from git log
  - Format: Keep a Changelog (keepachangelog.com)
- [ ] Create `doc/RUNBOOK.md`:
  - Common operational tasks
  - Incident response: "investigation stuck" → check Celery, Redis state
  - "ML model accuracy dropped" → check training data, retrain
  - "Graph page slow" → check edge count, enable aggregation

### 3. Update Swagger Spec
- [ ] Update `static/swagger.json`:
  - Add security schemes (Bearer JWT) once Plan 01 is done
  - Add rate limit headers documentation
  - Add missing endpoints (graph, monitor, audit)
  - Add request/response schemas for all endpoints
  - Add error response schemas (401, 403, 404, 500)

### 4. Script Cleanup
- [ ] Audit each `_`-prefixed script in `scripts/`:

  **Keep & document:**
  - `_step1_create.py` → document as "manual investigation creation"
  - `_step2_expand.py` → document as "manual wallet expansion"
  - `_step3_create_labels.py` → document as "manual label import"
  - `_assess.py` → document as "manual risk assessment"

  **Archive or delete:**
  - `_ck2.py`, `_ck3.py`, `_ck_final.py`, `_ck_v4.py` → debug checks, likely obsolete
  - `_retry6.py` → one-time retry, should be in task retry logic
  - `_check_train.py`, `_check_train2.py` → superseded by ML pipeline
  - `_db_check.py`, `_db_audit.py` → consolidate into `scripts/cli.py`
  - `_quick_status.py`, `_check_status.py` → consolidate into health endpoint

- [ ] Add docstrings to all surviving scripts
- [ ] Create `scripts/README.md` listing all scripts with their purpose

### 5. Notebook Cleanup
- [ ] Audit `notebooks/` helper files:
  - `_analyze_results.py`, `_debug_inv2_full.py`, `_debug_train.py`, etc.
  - If superseded by notebooks or `scripts/`, archive to `notebooks/archive/`
- [ ] Ensure all 6 notebooks have proper markdown headers explaining their purpose
- [ ] Clear notebook outputs to reduce repo size (use `nbstripout`)
- [ ] Add `notebooks/README.md` with execution order and prerequisites

### 6. Code Quality
- [ ] Add `pyproject.toml` or `.flake8` config:
  - `max-line-length = 120`
  - `extend-ignore = E203, W503`
- [ ] Add `.pre-commit-config.yaml`:
  - `ruff` linter
  - `black` formatter (or `ruff format`)
  - `nbstripout` for notebooks
  - `trailing-whitespace`, `end-of-file-fixer`
- [ ] Run linter on full codebase, fix critical issues
- [ ] Add type hints to public function signatures in `api/services/`

## Constraints

- Don't rename files that are imported by other modules (will break imports)
- Don't delete scripts that are still referenced in docs or other scripts
- Keep `notebooks/data/` as-is (data files, models) — only clean Python helpers
- Swagger spec changes must match actual API behavior
- Pre-commit hooks should be optional (don't enforce in CI initially)

## Success Criteria

- [ ] Single `doc/` directory with all documentation
- [ ] `CONTRIBUTING.md`, `CHANGELOG.md` exist in repo root
- [ ] `doc/DEPLOYMENT.md` and `doc/RUNBOOK.md` exist
- [ ] `doc/DATA_DICTIONARY.md` has full schema documentation
- [ ] `scripts/README.md` lists all scripts
- [ ] No more than 10 `_`-prefixed scripts remain in `scripts/`
- [ ] Swagger spec covers all endpoints with schemas
- [ ] `pre-commit run --all-files` passes

## Key Files

| File | Action |
|------|--------|
| `doc/` | Consolidate — merge `docs/` content here |
| `docs/` | Delete after merging |
| `CONTRIBUTING.md` | Create |
| `CHANGELOG.md` | Create |
| `doc/DEPLOYMENT.md` | Create |
| `doc/RUNBOOK.md` | Create |
| `doc/DATA_DICTIONARY.md` | Create |
| `scripts/README.md` | Create |
| `notebooks/README.md` | Create |
| `static/swagger.json` | Modify — full spec |
| `pyproject.toml` | Create — linter config |
| `.pre-commit-config.yaml` | Create |
| `scripts/_ck*.py` | Delete — obsolete debug scripts |
