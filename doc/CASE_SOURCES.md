# Case Sourcing Methodology

## OSINT Sources

Bubble cases are sourced from publicly available on-chain investigations by well-known blockchain investigators and security firms. All case data is derived from publicly posted findings on X (Twitter), blogs, and on-chain analysis.

## Key Investigators & Sources

### Individual Investigators

| Handle | Name | Specialty | Reliability | Notable Breaks |
|--------|------|-----------|-------------|----------------|
| **@zachxbt** | ZachXBT | On-chain forensics, scam exposure | Very High | $243M Genesis creditor theft, Monkey Drainer, multiple CEX fraud cases |
| **@taaboraa** | Tay | DeFi exploits, MEV analysis | High | Protocol exploit tracing, flash loan attacks |
| **@samczsun** | samczsun | Smart contract security (Paradigm) | Very High | Hundreds of protocol rescues, vulnerability disclosures |
| **@coffeebreak_YT** | Coffeezilla | Fraud investigation, YouTube/X | High | FTX, SafeMoon, Logan Paul CryptoZoo |
| **@officer_cia** | Officer CIA | Threat intelligence | High | Lazarus Group tracking, DPRK attribution |
| **@naborso** | Bor | On-chain analysis | High | Wallet clustering, exchange tracing |

### Security Firms

| Handle | Firm | Focus | Output |
|--------|------|-------|--------|
| **@SlowMist_Team** | SlowMist | Incident response, stolen fund tracking | MistTrack tool, hack analyses |
| **@PeckShieldAlert** | PeckShield | Real-time exploit alerts | Immediate hack detection, fund tracking |
| **@CertiKAlert** | CertiK | Smart contract auditing | Skynet alerts, incident analysis |
| **@BlockSecTeam** | BlockSec | Transaction simulation, MEV | Real-time attack detection |
| **@AnciliaInc** | Ancilia | On-chain monitoring | Exploit alerts, fund flow analysis |
| **@Chainalysis** | Chainalysis | Law enforcement intelligence | Reactor tool, compliance data |
| **@ellaborated** | Elliptic | Regulatory compliance | Wallet screening, sanctions |
| **@TRM_Labs** | TRM Labs | Blockchain intelligence | Risk scoring, investigation tools |

### Government & Regulatory

| Source | Type | Value |
|--------|------|-------|
| **OFAC SDN List** | Sanctions | Designated wallet addresses (Tornado Cash, Lazarus) |
| **FBI IC3** | Law enforcement | Reported cryptocurrency fraud cases |
| **Europol / EC3** | Law enforcement | Cross-border crypto crime data |

## Current Cases — Source Attribution

| Case ID | Source | Attribution |
|---------|--------|-------------|
| CASE-2026-001 | OSINT / Multiple X posts | Multi-chain drain reports from victims, corroborated by @zachxbt |
| CASE-2026-002 | OSINT / Security researchers | Trust Wallet supply chain reports, multiple researcher confirmation |
| CASE-2026-003 | OSINT / Victim report | Private key compromise, fund flow traced on-chain |
| CASE-2026-004 | @zachxbt | Danny/Meech ($243M Genesis theft) — extensively documented |
| CASE-2026-005 | @PeckShieldAlert, @SlowMist_Team | GANA Payment exploit — real-time alerts |
| CASE-2026-006 | OSINT / Google Play Store reports | Fake Hyperliquid app — community reports |
| CASE-2026-007 | @PeckShieldAlert, @zachxbt | Garden Finance exploit — $10.8M traced |
| CASE-2026-008 | OSINT / HyperEVM community | Hypurr NFT drain — community discovered, E2E validated |
| CASE-2026-009 | rekt.news, @PeckShieldAlert, @BlockscopeCo | TrueBit Protocol $26.2M overflow exploit — serial "relic hunter" |
| CASE-2026-010 | rekt.news, @CertiKAlert, @cosmoslabs_io | Saga IBC $7M bridge exploit — Ethermint codebase vuln |
| CASE-2026-011 | rekt.news, @CertiKAlert, CoinTelegraph | Step Finance $27.3M SOL drain — exec device compromise (Solana, documented only) |
| CASE-2026-012 | rekt.news | Makina $4.13M oracle manipulation — flash loan |
| CASE-2026-013 | rekt.news | Yearn Finance v4 $293K — legacy code recycled error |
| CASE-2026-014 | rekt.news | TMXTribe $1.4M logic bug — possible exit scam |

### Attack Vector Distribution (14 cases)

| Vector | Count | Example |
|--------|-------|---------|
| Smart Contract Exploit | 4 | GANA, Garden Finance, TrueBit, Makina |
| Key Compromise / Social Eng. | 3 | Private Key, Danny/Meech, Step Finance |
| Legacy Code | 2 | TrueBit (overflow), Yearn (recycled bug) |
| NFT/Token Drain | 2 | Hypurr, Multi-chain Wallet |
| Bridge/IBC Exploit | 1 | Saga IBC |
| Supply Chain | 1 | Trust Wallet Extension |
| Possible Exit Scam | 1 | TMXTribe |

### Chain Coverage

| Chain | Cases |
|-------|-------|
| Ethereum | 10 (CASE-001 through 010, 012-014) |
| Solana | 1 (CASE-011, documented only) |
| BSC | 2 (cross-chain in CASE-005, 007) |
| Multi-chain | 3 (CASE-001, 005, 007) |

## Case Selection Criteria

When selecting cases for the Bubble platform, prioritize:

1. **Public attribution** — Cases with on-chain evidence shared publicly
2. **Multi-chain activity** — Cases involving cross-chain transfers (tests our multi-chain tracing)
3. **Diverse attack vectors** — Smart contract exploits, phishing, key compromise, social engineering
4. **Mixer/bridge usage** — Cases where attackers use obfuscation (tests our detection)
5. **Range of severity** — From $100K scams to $100M+ exploits
6. **Actionable seed wallets** — Cases where attacker addresses are identified

## Adding New Cases

### From ZachXBT Thread
```bash
# 1. Identify case from X thread
# 2. Extract attacker/victim wallet addresses + chain info
# 3. Create case via API:
curl -X POST http://localhost:8080/api/cases \
  -H "Content-Type: application/json" \
  -d '{
    "case_id": "CASE-2026-009",
    "title": "Description from thread",
    "source": "osint",
    "status": "active",
    "severity": "critical",
    "attack_vector": "smart_contract_exploit",
    "total_stolen_usd": 5000000,
    "summary": "Summary from the investigation thread...",
    "wallets": [
      {"address": "0xATTACKER...", "chain_code": "ETH", "role": "attacker", "label": "exploiter"},
      {"address": "0xVICTIM...", "chain_code": "ETH", "role": "victim", "label": "protocol treasury"}
    ]
  }'

# 4. Run investigation skill
curl -X POST http://localhost:8080/api/cases/CASE-2026-009/run-skill \
  -H "Content-Type: application/json" \
  -d '{"max_depth": 3, "max_wallets": 100}'
```

### Validation Checklist
- [ ] Wallet addresses verified on block explorers
- [ ] Chain assignments confirmed
- [ ] Attack vector categorized
- [ ] Estimated loss cross-referenced
- [ ] Source attribution documented
- [ ] No PII or sensitive victim information included
