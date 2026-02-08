# Bubble — Agent Task Plans

## Overview

This directory contains structured task plans for **Claude 4.6 agents** working autonomously on the Bubble codebase. Each plan is a self-contained mission brief with context, objectives, success criteria, and file references.

## Agent Assignment

| Plan | Agent Role | Priority | Est. Effort | Dependencies |
|------|-----------|----------|-------------|--------------|
| [01_security_auth.md](01_security_auth.md) | **Security Agent** | P0 | 2-3 sessions | None |
| [02_test_coverage.md](02_test_coverage.md) | **QA Agent** | P0 | 3-4 sessions | None |
| [03_ml_pipeline.md](03_ml_pipeline.md) | **ML Agent** | P1 | 2-3 sessions | None |
| [04_frontend_ux.md](04_frontend_ux.md) | **Frontend Agent** | P2 | 2-3 sessions | 01 (auth) |
| [05_infrastructure.md](05_infrastructure.md) | **DevOps Agent** | P1 | 2-3 sessions | 01 (secrets) |
| [06_data_pipeline.md](06_data_pipeline.md) | **Data Agent** | P2 | 1-2 sessions | 03 (ML) |
| [07_graphql_tigergraph.md](07_graphql_tigergraph.md) | **Graph Agent** | P3 | 2-3 sessions | 05 (infra) |
| [08_cleanup_docs.md](08_cleanup_docs.md) | **Docs Agent** | P3 | 1 session | All above |

## How to Use These Plans

Each plan follows this format:

```
## Context       — What the agent needs to know
## Objectives    — Numbered tasks with file paths
## Constraints   — Rules and boundaries
## Success       — Measurable completion criteria
## Files         — Key files to read/modify
```

**Agents should:**
1. Read the full plan before starting
2. Use `manage_todo_list` to track progress
3. Run `docker compose up --build -d` to test changes
4. Commit after each logical unit of work
5. Never break existing functionality — run `pytest` before committing

## Current State (Feb 2026)

- **Branch:** `dev` (6 commits ahead of origin)
- **Docker:** 6 containers (postgres, redis, web, celery, nginx, mlflow)
- **Tests:** ~25 tests, ~5% coverage
- **Auth:** None — all endpoints public
- **ML:** ExtraTrees champion (F1=0.8882), but classifier disconnected from production model
- **TigerGraph:** Disabled (commented out in docker-compose.yml)
- **Graph Viz:** vis.js — fully functional with big-data support, clustering, summary panel
