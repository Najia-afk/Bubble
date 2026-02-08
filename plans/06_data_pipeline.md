# Plan 06 — Data Pipeline Hardening

> **Agent Role:** Data Agent
> **Priority:** P2 (Medium)
> **Est. Effort:** 1-2 sessions
> **Dependencies:** Plan 03 (ML pipeline fixes)

## Context

The data pipeline syncs blockchain transfers via Etherscan API into PostgreSQL. Current issues: 30-second hard sleep between API calls (no adaptive backoff), no data validation layer, raw blockchain data goes directly to models, the value normalization had a double-division bug (now clamped but root cause needs proper fix), and there's no freshness monitoring.

## Objectives

### 1. Fix Value Normalization at Source
- [ ] In `api/tasks/investigation_sync_tasks.py` line ~147:
  - When `tokenDecimal` is `0` or missing from API response, attempt to look up decimals from:
    1. `InvestigationToken` table (if we synced it before)
    2. Known token list (ETH=18, USDT=6, USDC=6, etc.)
    3. On-chain call via Etherscan `getabi` (if available)
    4. Default to 18 (EVM standard) as last resort
  - Log a warning when falling back to default
- [ ] Remove the backend clamp in `investigation_routes.py` (line ~307) once source normalization is reliable
- [ ] Add a `normalization_method` column to `InvestigationTransfer`:
  - `'api'` — API provided decimals
  - `'lookup'` — looked up from known list
  - `'default'` — assumed 18
  - `'raw'` — could not normalize

### 2. Adaptive API Rate Limiting
- [ ] Replace 30-second `time.sleep()` in `scripts/src/fetch_scan_token_erc20_transfert.py` with:
  ```python
  class AdaptiveRateLimiter:
      def __init__(self, base_delay=0.2, max_delay=30):
          self.delay = base_delay
      def wait(self):
          time.sleep(self.delay)
      def on_success(self):
          self.delay = max(self.base_delay, self.delay * 0.8)
      def on_rate_limit(self):
          self.delay = min(self.max_delay, self.delay * 2)
      def on_error(self):
          self.delay = min(self.max_delay, self.delay * 1.5)
  ```
- [ ] Apply same pattern to `investigation_sync_tasks.py` Etherscan calls
- [ ] Track API usage metrics (calls/minute, rate-limit hits)

### 3. Data Validation Layer
- [ ] Create `api/services/data_validator.py`:
  - `validate_transfer(transfer_dict) -> (is_valid, issues[])`:
    - Address format: `^0x[a-fA-F0-9]{40}$`
    - Value: non-negative, finite, not NaN
    - Timestamp: after 2015-01-01 (Ethereum genesis), before now + 1 day
    - Block number: positive integer
    - Token symbol: max 20 chars, alphanumeric
  - `validate_wallet(address) -> (is_valid, issues[])`:
    - Valid hex address
    - Checksum validation (EIP-55)
  - `flag_suspicious_transfer(transfer) -> list[str]`:
    - Value > 1e12 (>$1T) → flag as "extreme value"
    - Self-transfer (from == to) → flag as "self-transfer"
    - Zero-value → flag as "zero-value spam"
- [ ] Integrate validator into sync pipeline — log warnings, don't reject (soft validation)
- [ ] Store validation flags in new `InvestigationTransfer.flags` JSON column

### 4. Deduplication
- [ ] Current deduplication uses `(tx_hash, from, to, token_contract)` as unique key
- [ ] Verify this is enforced at DB level (unique constraint or `ON CONFLICT DO NOTHING`)
- [ ] Add batch dedup check before insert — skip known keys early (save DB round-trips)
- [ ] Create `scripts/dedup_transfers.py` — one-time cleanup of any existing duplicates

### 5. Data Freshness Monitoring
- [ ] Create `api/services/data_freshness.py`:
  - `check_investigation_freshness(investigation_id) -> dict`:
    - Last transfer timestamp vs now
    - Total transfers synced
    - Status: `fresh` (<1h), `stale` (1-24h), `outdated` (>24h)
  - `check_global_freshness() -> dict`:
    - Active investigations with stale data
    - Last sync timestamp per investigation
- [ ] Add `/api/health/data` endpoint returning freshness status
- [ ] Add Celery periodic task: check freshness every hour, log warnings for stale investigations
- [ ] Surface freshness status in investigation detail page (badge: "Data as of X hours ago")

### 6. Spam Token Filtering
- [ ] Create `config/data/spam_tokens.json` — list of known spam token contracts
  - Source: Pre-populate from Etherscan's known spam list
  - Format: `{ "0x...": { "symbol": "FAKE", "reason": "airdrop spam" } }`
- [ ] During sync, flag transfers involving spam tokens with `flags=['spam_token']`
- [ ] In graph endpoint, add `?exclude_spam=true` (default: true) to filter out spam transfers
- [ ] In graph summary/metrics, exclude spam from volume calculations
- [ ] Keep spam transfers in DB (for audit trail) but mark them

## Constraints

- Don't delete data — always soft-flag, never drop transfers
- Backward compatible — existing investigations should still work
- API rate limits: Etherscan free tier = 5 calls/sec, Pro = 10 calls/sec
- Validation should be non-blocking (log + flag, don't reject)
- Spam list should be easy to update (JSON file, not hardcoded)

## Success Criteria

- [ ] `token_decimals=0` transfers are properly normalized using lookup/default
- [ ] No 30-second hard sleeps — adaptive delay between 0.2s and 30s
- [ ] All synced transfers pass validation (address, value, timestamp format)
- [ ] `/api/health/data` returns freshness status for all active investigations
- [ ] Spam tokens filtered from graph view by default
- [ ] Existing data not broken by any migration

## Key Files

| File | Action |
|------|--------|
| `api/tasks/investigation_sync_tasks.py` | Modify — fix decimals lookup, adaptive rate limit |
| `api/routes/investigation_routes.py` | Modify — add `?exclude_spam`, remove hard clamp when ready |
| `api/services/data_validator.py` | Create |
| `api/services/data_freshness.py` | Create |
| `api/application/investigation_models.py` | Modify — add `flags` column |
| `config/data/spam_tokens.json` | Create |
| `scripts/dedup_transfers.py` | Create |
| `scripts/src/fetch_scan_token_erc20_transfert.py` | Modify — adaptive rate limiter |
