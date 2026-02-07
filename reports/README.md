# Investigation Reports

This directory contains structured reports generated from the Bubble AML Investigation Platform.

## Structure

```
reports/
├── README.md                    # ← You are here
├── cases/                       # Per-case investigation reports
│   ├── CASE-2026-001.md         # Multi-chain EVM Wallet Drain
│   ├── CASE-2026-002.md         # Trust Wallet Extension Drain
│   ├── CASE-2026-003.md         # Private Key Compromise
│   ├── CASE-2026-004.md         # Danny/Meech Genesis Theft
│   ├── CASE-2026-005.md         # GANA Payment Protocol Exploit
│   ├── CASE-2026-006.md         # Fake Hyperliquid App Scam
│   ├── CASE-2026-007.md         # Garden Finance Exploit
│   └── CASE-2026-008.md         # Hypurr NFT Drain (E2E validated)
└── ml/
    └── model_evaluation.md      # ML pipeline evaluation report
```

## Report Generation

Reports are generated from:
1. **Investigation Skill** — Step 6 (Generate Report) compiles findings automatically
2. **API Data** — `GET /api/cases/{case_id}` and `GET /api/investigations/{id}`
3. **Skill Status** — `GET /api/cases/{case_id}/skill-status` with findings

## Status Legend

| Status | Meaning |
|--------|---------|
| ✅ E2E Validated | Full skill pipeline ran successfully |
| 🔄 In Progress | Investigation running, partial results |
| 📋 Documented | Case created with seed wallets, not yet investigated |
| ⚠️ Needs Review | Results require manual analyst review |

## Case Summary (2026-02-07)

| Case ID | Title | Severity | Est. Loss | Wallets | Risk | Status |
|---------|-------|----------|-----------|---------|------|--------|
| CASE-2026-001 | Multi-chain EVM Wallet Drain | High | $107K | 50 | — | 🔄 |
| CASE-2026-002 | Trust Wallet Extension Drain | Critical | $500K | 100 | — | 🔄 |
| CASE-2026-003 | Private Key Compromise | Critical | $1.1M | 60 | — | 🔄 |
| CASE-2026-004 | Danny/Meech Genesis Theft | Critical | $18.58M | 3 | — | 🔄 |
| CASE-2026-005 | GANA Payment Protocol Exploit | Critical | $3.1M | 60 | — | 🔄 |
| CASE-2026-006 | Fake Hyperliquid App Scam | Medium | $200K | 32 | — | 🔄 |
| CASE-2026-007 | Garden Finance Exploit | Critical | $10.8M | 80 | — | 🔄 |
| CASE-2026-008 | Hypurr NFT Drain | High | $400K | 50 | CRITICAL | ✅ E2E |
