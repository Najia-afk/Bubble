# Plan 07 — GraphQL & TigerGraph Integration

> **Agent Role:** Graph Agent
> **Priority:** P3 (Low — blocked by TigerGraph image access)
> **Est. Effort:** 2-3 sessions
> **Dependencies:** Plan 05 (infrastructure must handle TigerGraph container)

## Context

TigerGraph is fully disabled (commented out in docker-compose.yml). A schema exists (`cypher_app/scripts/schema.gsql`), a loader exists (`cypher_app/src/tigergraph_loader.py` with 2 TODOs), and Celery tasks are ready. GraphQL is read-only (5 query schemas, 0 mutations, 0 subscriptions). The `dashboard.js` has TigerGraph stat stubs.

## Objectives

### 1. Enable TigerGraph Container
- [ ] Uncomment TigerGraph service in `docker-compose.yml`
- [ ] Handle image access: check if `docker.tigergraph.com/tigergraph-dev:latest` is accessible
  - If not, investigate alternatives: TigerGraph Docker CE, or fallback to Neo4j
- [ ] Add TigerGraph health check to web container `depends_on`
- [ ] Update `config/settings.py` — `TIGERGRAPH_HOST`, `TIGERGRAPH_PORT`, `TIGERGRAPH_PASSWORD`
- [ ] Test: `docker compose up` brings TigerGraph online
- [ ] Initialize schema: run `cypher_app/scripts/init_schema.py` in startup

### 2. Fix TigerGraph Loader
- [ ] In `cypher_app/src/tigergraph_loader.py`:
  - Line ~183: Implement `amount_usd` calculation (use token price from `TokenPriceHistory`)
  - Line ~242: Implement bridge edge creation once schema supports it
- [ ] Add error handling — retry on connection failure, log skipped records
- [ ] Add batch loading — current implementation may be one-at-a-time
- [ ] Add progress tracking — log % complete for large loads

### 3. Graph Algorithms
- [ ] Implement in TigerGraph GSQL or client-side:
  - **PageRank** — identify most influential wallets
  - **Community Detection** (Louvain) — automatic wallet clustering
  - **Shortest Path** — fund flow path between any two wallets
  - **Connected Components** — identify isolated wallet clusters
- [ ] Expose via new endpoints:
  - `GET /api/graph/pagerank?investigation_id=X` → top-20 ranked wallets
  - `GET /api/graph/communities?investigation_id=X` → community assignments
  - `GET /api/graph/path?from=0x...&to=0x...` → shortest fund flow path
- [ ] Feed PageRank + community features into ML pipeline (`feature_engineer.py`)

### 4. GraphQL Enhancements
- [ ] Add mutations:
  - `createLabel(address, label, source)` — tag a wallet
  - `flagWallet(address, reason)` — mark wallet for review
  - `addToInvestigation(investigation_id, address)` — add wallet to case
- [ ] Add subscriptions (via graphene-subscriptions or Ariadne):
  - `onNewTransfer(investigation_id)` — real-time transfer stream
  - `onAlertFired(wallet_address)` — monitor alert notifications
- [ ] Add pagination to all list queries:
  - `transfers(first: 100, after: cursor)` — relay-style pagination
  - `walletTransfers(address, limit, offset)` — offset pagination
- [ ] Add investigation-level GraphQL queries:
  - `investigation(id) { wallets { address, role }, transfers { from, to, value } }`
  - `investigationStats(id) { walletCount, transferCount, totalVolume }`

### 5. Graph-Powered Features for ML
Once TigerGraph is running:
- [ ] Add to `feature_engineer.py`:
  - `pagerank_score` — wallet's PageRank in transfer graph
  - `community_id` — Louvain community assignment
  - `community_size` — number of wallets in same community
  - `betweenness_centrality` — how often wallet appears on shortest paths
  - `clustering_coefficient` — local clustering density
- [ ] Retrain model with graph features (expect F1 improvement)

## Constraints

- TigerGraph integration is optional — app must work without it
- All TigerGraph calls should timeout after 10s and fail gracefully
- GraphQL mutations must validate input (address format, etc.)
- Subscriptions need WebSocket support — verify nginx proxying
- If TigerGraph image isn't accessible, document the blocker and move on

## Success Criteria

- [ ] `docker compose up` starts TigerGraph (or is gracefully skipped)
- [ ] TigerGraph schema is initialized on first run
- [ ] PageRank endpoint returns ranked wallets for an investigation
- [ ] GraphQL mutations work for labeling wallets
- [ ] Graph features added to ML feature set
- [ ] Dashboard shows TigerGraph stats (connected/disconnected status)

## Key Files

| File | Action |
|------|--------|
| `docker-compose.yml` | Modify — uncomment TigerGraph |
| `cypher_app/src/tigergraph_loader.py` | Fix — TODOs, batch loading |
| `cypher_app/scripts/schema.gsql` | Review — bridge edges |
| `cypher_app/scripts/init_schema.py` | Review — startup hook |
| `graphql_app/schemas/combined_schema.py` | Modify — add mutations |
| `api/routes/graph_routes.py` | Modify — add algorithm endpoints |
| `api/services/feature_engineer.py` | Modify — add graph features |
| `static/js/dashboard.js` | Modify — wire TigerGraph stats |
| `config/settings.py` | Modify — TigerGraph config |
