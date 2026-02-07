# api/application/erc20models.py
"""
BACKWARD-COMPAT RE-EXPORT HUB.

All models have been split into domain modules:
  - base.py              → Base, logger, CHAIN_ID_TO_TRIGRAM, TRIGRAM_TO_CHAIN_ID
  - label_models.py      → LabelType, WalletLabel, KnownBridge
  - investigation_models.py → Investigation, InvestigationWallet, InvestigationToken, InvestigationTransfer
  - ml_models.py         → WalletScore, AuditLog, ModelMetadata
  - token_models.py      → Token, TokenPriceHistory, BlockTransferEvent, ERC20TransferEventBase,
                            dynamic generators, helper functions

This file re-exports everything so existing `from api.application.erc20models import X`
continues to work without any changes to 40+ importing files.
"""

# ── Base & Constants ──────────────────────────────────────
from api.application.base import Base, erc20models_logger, CHAIN_ID_TO_TRIGRAM, TRIGRAM_TO_CHAIN_ID

# ── Label Models ──────────────────────────────────────────
from api.application.label_models import LabelType, WalletLabel, KnownBridge

# ── Investigation Models ──────────────────────────────────
from api.application.investigation_models import (
    Investigation, InvestigationWallet, InvestigationToken, InvestigationTransfer
)

# ── ML & Audit Models ────────────────────────────────────
from api.application.ml_models import WalletScore, AuditLog, ModelMetadata

# ── Token & ERC20 Models ─────────────────────────────────
from api.application.token_models import (
    Token, TokenPriceHistory,
    BlockTransferEvent, ERC20TransferEventBase,
    generate_block_transfer_event_classes,
    generate_erc20_classes,
    adjust_erc20_transfer_event_relationships,
    apply_dynamic_unique_constraints,
    apply_dynamic_indexes,
    get_transfer_event_class,
    get_block_transfer_event_class,
)

__all__ = [
    # Base
    'Base', 'erc20models_logger', 'CHAIN_ID_TO_TRIGRAM', 'TRIGRAM_TO_CHAIN_ID',
    # Labels
    'LabelType', 'WalletLabel', 'KnownBridge',
    # Investigations
    'Investigation', 'InvestigationWallet', 'InvestigationToken', 'InvestigationTransfer',
    # ML & Audit
    'WalletScore', 'AuditLog', 'ModelMetadata',
    # Tokens & ERC20
    'Token', 'TokenPriceHistory', 'BlockTransferEvent', 'ERC20TransferEventBase',
    'generate_block_transfer_event_classes', 'generate_erc20_classes',
    'adjust_erc20_transfer_event_relationships',
    'apply_dynamic_unique_constraints', 'apply_dynamic_indexes',
    'get_transfer_event_class', 'get_block_transfer_event_class',
]
        


