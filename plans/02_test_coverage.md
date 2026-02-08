# Plan 02 — Test Coverage

> **Agent Role:** QA Agent
> **Priority:** P0 (Critical)
> **Est. Effort:** 3-4 sessions
> **Dependencies:** None — can run in parallel with Plan 01

## Context

Bubble has ~25 tests covering ~5% of the codebase. There are zero tests for services, Celery tasks, algorithms, GraphQL schemas, and 11 of 14 route blueprints. Existing tests use overly permissive assertions (`status_code in [200, 404, 500]`). No mocking infrastructure exists — tests require a live DB.

Current test files:
- `tests/test_api_endpoints.py` — 14 tests (health, tokens, frontend routes)
- `tests/test_database_models.py` — 4 tests (Token model structure)
- `tests/test_environment.py` — 5 tests (Python version, imports)

## Objectives

### Session 1: Testing Infrastructure
- [ ] Add `pytest-cov`, `pytest-mock`, `factory-boy`, `responses` to `config/requirements.txt`
- [ ] Create `tests/conftest.py` with fixtures:
  - `app` — Flask test app with `TESTING=True`, SQLite in-memory DB
  - `client` — Flask test client
  - `db_session` — Scoped SQLAlchemy session with rollback
  - `mock_redis` — fakeredis instance
  - `mock_celery` — Celery with `ALWAYS_EAGER=True`
  - `sample_investigation` — Factory for Investigation + InvestigationWallet + InvestigationTransfer
  - `sample_case` — Factory for Case + CaseWallet
- [ ] Update `pytest.ini` to add `--cov=api --cov-report=html --cov-report=term-missing`
- [ ] Fix existing tests to use proper fixtures, remove `status_code in [200, 404, 500]` patterns

### Session 2: Service & Algorithm Tests
- [ ] Create `tests/test_feature_engineer.py` — test all 50+ features, test placeholder feature
  - Files: `api/services/feature_engineer.py`
- [ ] Create `tests/test_wallet_classifier.py` — test classification pipeline, heuristic fallback
  - Files: `api/services/wallet_classifier.py`
- [ ] Create `tests/test_ml_trainer.py` — test training pipeline, model persistence, MLflow logging
  - Files: `api/services/ml_trainer.py`
- [ ] Create `tests/test_investigation_skill.py` — test 6-step pipeline, step failures, Redis state
  - Files: `api/services/investigation_skill.py`
- [ ] Create `tests/test_algorithms.py` — test graph_tracer, path_analyzer, wallet_heuristics
  - Files: `api/algorithms/graph_tracer.py`, `api/algorithms/path_analyzer.py`, `api/algorithms/wallet_heuristics.py`

### Session 3: Route & Task Tests
- [ ] Create `tests/test_case_routes.py` — CRUD operations, skill launch, status polling
  - Files: `api/routes/case_routes.py`
- [ ] Create `tests/test_investigation_routes.py` — graph endpoint, aggregation, max_edges, empty data
  - Files: `api/routes/investigation_routes.py`
- [ ] Create `tests/test_ml_routes.py` — training trigger, model list, model promotion
  - Files: `api/routes/ml_routes.py`
- [ ] Create `tests/test_monitor_routes.py` — add/remove watch, alert triggers
  - Files: `api/routes/monitor_routes.py`
- [ ] Create `tests/test_celery_tasks.py` — mock task execution, result handling, error recovery
  - Files: `api/tasks/*.py`

### Session 4: Integration & Edge Cases
- [ ] Create `tests/test_graphql_schemas.py` — query each of the 5 schemas
  - Files: `graphql_app/schemas/*.py`
- [ ] Create `tests/test_investigation_graph.py` — big-data edge aggregation, force-clamp, sampling
- [ ] Create `tests/test_value_normalization.py` — token decimals, spam token clamping, raw values
  - Specifically test the normalization logic in `investigation_routes.py` line ~294
- [ ] Add edge-case tests: empty investigations, 0-transfer wallets, missing token symbols
- [ ] Add stress test: 10,000 transfers through graph endpoint (ensure <2s response)
- [ ] Verify coverage ≥ 60% overall, ≥ 80% for services

## Constraints

- Tests must run WITHOUT Docker — use SQLite in-memory, fakeredis, mock Celery
- Tests must be independent — no shared state between test functions
- Use `@pytest.fixture` for all setup, never class-based test inheritance
- Mock external API calls (Etherscan, CoinGecko) — never hit real APIs in tests
- Each test file should import from its target module and test public API only

## Success Criteria

- [ ] `pytest --cov` passes with 0 failures
- [ ] Coverage ≥ 60% overall
- [ ] Every service in `api/services/` has at least 5 tests
- [ ] Every algorithm in `api/algorithms/` has at least 3 tests
- [ ] Every route blueprint has at least 3 endpoint tests
- [ ] `tests/conftest.py` provides reusable fixtures
- [ ] CI-ready: tests work without any external service

## Key Files

| File | Action |
|------|--------|
| `tests/conftest.py` | Create — shared fixtures |
| `tests/test_feature_engineer.py` | Create |
| `tests/test_wallet_classifier.py` | Create |
| `tests/test_ml_trainer.py` | Create |
| `tests/test_investigation_skill.py` | Create |
| `tests/test_algorithms.py` | Create |
| `tests/test_case_routes.py` | Create |
| `tests/test_investigation_routes.py` | Create |
| `tests/test_ml_routes.py` | Create |
| `tests/test_monitor_routes.py` | Create |
| `tests/test_celery_tasks.py` | Create |
| `tests/test_graphql_schemas.py` | Create |
| `tests/test_value_normalization.py` | Create |
| `config/requirements.txt` | Modify — add test deps |
| `pytest.ini` | Modify — add coverage config |
