# api/application/base.py
"""
Shared SQLAlchemy Base and chain constants.
All model modules import Base from here to share a single metadata registry.
"""
from sqlalchemy.ext.declarative import declarative_base
from utils.logging_config import setup_logging

Base = declarative_base()

erc20models_logger = setup_logging('erc20models.log')

# ── Chain ID ↔ Trigram Mappings ────────────────────────────

CHAIN_ID_TO_TRIGRAM = {
    1: 'ETH',
    56: 'BSC',
    137: 'POL',
    8453: 'BASE',
    42161: 'ARB',
    10: 'OP',
    43114: 'AVAX',
    250: 'FTM',
}

TRIGRAM_TO_CHAIN_ID = {v: k for k, v in CHAIN_ID_TO_TRIGRAM.items()}
