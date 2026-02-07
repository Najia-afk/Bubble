# ML Model Evaluation Report

> **Date**: 2026-02-07  
> **Evaluator**: Aria (AI Data Scientist)  
> **Full Analysis**: See [doc/ML_EVALUATION.md](../../doc/ML_EVALUATION.md)

---

## Model Registry Snapshot

| # | Model | Version | Stage | Accuracy | F1 | CV Score |
|---|-------|---------|-------|----------|-----|----------|
| 1 | wallet_classifier | `0df244afa2` | **Production** | 98.95% | 98.99% | 91.00% |
| 2 | wallet_classifier | `d34249cca1` | Staging | 98.95% | 98.99% | — |
| 3 | wallet_classifier | `cd9b0a8904` | Staging | 98.95% | 98.99% | — |

## Production Model Metrics

| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| Accuracy | 98.95% | >90% | ✅ Exceeds target |
| F1 Score | 98.99% | >85% | ✅ Exceeds target |
| Cross-Validation | 91.00% | >85% | ⚠️ 8% gap from test |
| Training Samples | 381 | >1000 | ❌ Below minimum |
| Feature Count | 10 | 30+ | ⚠️ Underutilized |
| Classes | 4 | — | ✅ |
| Drift Status | OK | OK | ✅ |

## Risk Assessment

| Risk | Level | Description |
|------|-------|-------------|
| Overfitting | **HIGH** | 8% CV gap, small dataset, all models identical performance |
| Feature Leakage | **MEDIUM** | Risk features may encode target labels |
| Data Size | **CRITICAL** | 381 samples for 10 features × 4 classes |
| Production Usage | **CRITICAL** | ML model not used — all E2E results from heuristics |

## E2E Validation: CASE-2026-008

| Component | Status |
|-----------|--------|
| Investigation Skill Pipeline | ✅ All 6 steps completed |
| Transfer Fetching | ✅ 323,319 transfers |
| Wallet Expansion | ✅ 10 new wallets at depth 1 |
| Classification | ⚠️ 50/50 via heuristics, 0/50 via ML model |
| Risk Scoring | ✅ CRITICAL (100/100) |
| Report Generation | ✅ Compiled |

## Recommendations Priority Matrix

| Priority | Action | Effort | Impact |
|----------|--------|--------|--------|
| P0 | Fix ML model loading in Celery | Low | Critical |
| P0 | Expand training data to 2000+ | Medium | Critical |
| P1 | Audit features for target leakage | Low | High |
| P1 | Close CV gap (91% → 95%+) | Medium | High |
| P2 | Use all 50+ features with selection | Medium | Medium |
| P2 | Add probability calibration | Low | Medium |
| P3 | Scheduled drift monitoring | Low | Low |
| P3 | A/B test ML vs heuristics | Medium | Medium |
