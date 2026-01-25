# =============================================================================
# Bubble - Data Access Layer
# All data comes from PostgreSQL - no hardcoded values
# =============================================================================

import logging
from typing import Dict, List, Optional, Set
from functools import lru_cache
from sqlalchemy.orm import Session

from api.application.models import (
    Chain, Mixer, Bridge, Case, CaseWallet, CaseMixerDeposit,
    CaseBridgeActivity, LabelCategory, WalletTag, MonitoredWallet,
    Alert, RpcEndpoint
)

logger = logging.getLogger(__name__)


class DataAccess:
    """
    Centralized data access layer.
    All queries go through here - no hardcoded data anywhere.
    """
    
    def __init__(self, session: Session):
        self.session = session
    
    # =========================================================================
    # CHAINS
    # =========================================================================
    
    def get_chains(self, active_only: bool = True) -> List[Chain]:
        """Get all chains."""
        q = self.session.query(Chain)
        if active_only:
            q = q.filter(Chain.is_active == True)
        return q.all()
    
    def get_chain(self, code: str) -> Optional[Chain]:
        """Get chain by code."""
        return self.session.query(Chain).filter(Chain.code == code).first()
    
    def get_chain_codes(self) -> List[str]:
        """Get list of active chain codes."""
        return [c.code for c in self.get_chains()]
    
    # =========================================================================
    # MIXERS
    # =========================================================================
    
    def get_mixers(self, chain_code: str = None) -> List[Mixer]:
        """Get mixers, optionally filtered by chain."""
        q = self.session.query(Mixer).filter(Mixer.is_active == True)
        if chain_code:
            q = q.filter(Mixer.chain_code == chain_code)
        return q.all()
    
    def get_mixer_addresses(self, chain_code: str = None) -> Set[str]:
        """Get set of mixer addresses (lowercase)."""
        mixers = self.get_mixers(chain_code)
        return {m.address.lower() for m in mixers}
    
    def is_mixer(self, address: str, chain_code: str = None) -> bool:
        """Check if address is a known mixer."""
        addr = address.lower()
        q = self.session.query(Mixer).filter(
            Mixer.address == addr,
            Mixer.is_active == True
        )
        if chain_code:
            q = q.filter(Mixer.chain_code == chain_code)
        return q.first() is not None
    
    # =========================================================================
    # BRIDGES
    # =========================================================================
    
    def get_bridges(self, chain_code: str = None) -> List[Bridge]:
        """Get bridges, optionally filtered by chain."""
        q = self.session.query(Bridge).filter(Bridge.is_active == True)
        if chain_code:
            q = q.filter(Bridge.chain_code == chain_code)
        return q.all()
    
    def get_bridge_addresses(self, chain_code: str = None) -> Set[str]:
        """Get set of bridge addresses (lowercase)."""
        bridges = self.get_bridges(chain_code)
        return {b.address.lower() for b in bridges}
    
    def is_bridge(self, address: str, chain_code: str = None) -> bool:
        """Check if address is a known bridge."""
        addr = address.lower()
        q = self.session.query(Bridge).filter(
            Bridge.address == addr,
            Bridge.is_active == True
        )
        if chain_code:
            q = q.filter(Bridge.chain_code == chain_code)
        return q.first() is not None
    
    # =========================================================================
    # CASES
    # =========================================================================
    
    def get_cases(self, status: str = None, severity: str = None) -> List[Case]:
        """Get cases with optional filters."""
        q = self.session.query(Case)
        if status:
            q = q.filter(Case.status == status)
        if severity:
            q = q.filter(Case.severity == severity)
        return q.order_by(Case.date_reported.desc()).all()
    
    def get_case(self, case_id: str) -> Optional[Case]:
        """Get case by ID with all related data."""
        return self.session.query(Case).filter(Case.id == case_id).first()
    
    def get_case_wallets(self, case_id: str) -> List[CaseWallet]:
        """Get all wallets for a case."""
        return self.session.query(CaseWallet).filter(
            CaseWallet.case_id == case_id
        ).all()
    
    def get_all_theft_addresses(self) -> List[CaseWallet]:
        """Get all theft/attacker addresses from all cases."""
        return self.session.query(CaseWallet).filter(
            CaseWallet.role.in_(['theft_origin', 'attacker'])
        ).all()
    
    # =========================================================================
    # WALLET TAGS
    # =========================================================================
    
    def get_wallet_tags(self, address: str, chain_code: str = None) -> List[WalletTag]:
        """Get all tags for a wallet."""
        addr = address.lower()
        q = self.session.query(WalletTag).filter(WalletTag.address == addr)
        if chain_code:
            q = q.filter(WalletTag.chain_code == chain_code)
        return q.all()
    
    def get_wallet_primary_tag(self, address: str, chain_code: str = None) -> Optional[str]:
        """Get highest priority tag for a wallet."""
        tags = self.get_wallet_tags(address, chain_code)
        if not tags:
            return None
        # Sort by category priority
        return max(tags, key=lambda t: t.category.priority if t.category else 0).tag
    
    def add_wallet_tag(self, address: str, chain_code: str, tag: str, 
                       source: str = 'manual', confidence: float = 1.0) -> WalletTag:
        """Add tag to wallet."""
        wt = WalletTag(
            address=address.lower(),
            chain_code=chain_code,
            tag=tag,
            source=source,
            confidence=confidence
        )
        self.session.add(wt)
        self.session.flush()
        return wt
    
    def is_tagged_as(self, address: str, tag: str) -> bool:
        """Check if wallet has specific tag."""
        addr = address.lower()
        return self.session.query(WalletTag).filter(
            WalletTag.address == addr,
            WalletTag.tag == tag
        ).first() is not None
    
    # =========================================================================
    # LABEL CATEGORIES
    # =========================================================================
    
    def get_label_categories(self) -> List[LabelCategory]:
        """Get all label categories."""
        return self.session.query(LabelCategory).order_by(
            LabelCategory.priority.desc()
        ).all()
    
    def get_label_category(self, name: str) -> Optional[LabelCategory]:
        """Get label category by name."""
        return self.session.query(LabelCategory).filter(
            LabelCategory.name == name
        ).first()
    
    # =========================================================================
    # MONITORED WALLETS
    # =========================================================================
    
    def get_monitored_wallets(self, chain_code: str = None, 
                               case_id: str = None) -> List[MonitoredWallet]:
        """Get monitored wallets with optional filters."""
        q = self.session.query(MonitoredWallet).filter(
            MonitoredWallet.is_active == True
        )
        if chain_code:
            q = q.filter(MonitoredWallet.chain_code == chain_code)
        if case_id:
            q = q.filter(MonitoredWallet.case_id == case_id)
        return q.all()
    
    def add_monitored_wallet(self, address: str, chain_code: str,
                              case_id: str = None, label: str = None) -> MonitoredWallet:
        """Add wallet to monitoring."""
        mw = MonitoredWallet(
            address=address.lower(),
            chain_code=chain_code,
            case_id=case_id,
            label=label,
            is_active=True
        )
        self.session.add(mw)
        self.session.flush()
        return mw
    
    def get_monitored_wallet(self, address: str, chain_code: str) -> Optional[MonitoredWallet]:
        """Get specific monitored wallet."""
        return self.session.query(MonitoredWallet).filter(
            MonitoredWallet.address == address.lower(),
            MonitoredWallet.chain_code == chain_code
        ).first()
    
    # =========================================================================
    # ALERTS
    # =========================================================================
    
    def get_alerts(self, wallet_id: int = None, chain_code: str = None,
                   alert_type: str = None, limit: int = 100) -> List[Alert]:
        """Get alerts with optional filters."""
        q = self.session.query(Alert)
        if wallet_id:
            q = q.filter(Alert.wallet_id == wallet_id)
        if chain_code:
            q = q.filter(Alert.chain_code == chain_code)
        if alert_type:
            q = q.filter(Alert.alert_type == alert_type)
        return q.order_by(Alert.timestamp.desc()).limit(limit).all()
    
    def create_alert(self, wallet_id: int, chain_code: str, alert_type: str,
                     amount: float = None, token: str = None,
                     counterparty: str = None, tx_hash: str = None,
                     risk_score: float = 0.0) -> Alert:
        """Create new alert."""
        alert = Alert(
            wallet_id=wallet_id,
            chain_code=chain_code,
            alert_type=alert_type,
            amount=amount,
            token=token,
            counterparty=counterparty,
            tx_hash=tx_hash,
            risk_score=risk_score
        )
        self.session.add(alert)
        self.session.flush()
        return alert
    
    def get_alert_stats(self) -> Dict:
        """Get alert statistics."""
        from sqlalchemy import func
        
        total = self.session.query(func.count(Alert.id)).scalar() or 0
        
        by_type = dict(self.session.query(
            Alert.alert_type,
            func.count(Alert.id)
        ).group_by(Alert.alert_type).all())
        
        by_chain = dict(self.session.query(
            Alert.chain_code,
            func.count(Alert.id)
        ).group_by(Alert.chain_code).all())
        
        high_risk = self.session.query(func.count(Alert.id)).filter(
            Alert.risk_score >= 0.7
        ).scalar() or 0
        
        wallet_count = self.session.query(
            func.count(MonitoredWallet.id)
        ).filter(MonitoredWallet.is_active == True).scalar() or 0
        
        return {
            'total_alerts': total,
            'alerts_by_type': by_type,
            'alerts_by_chain': by_chain,
            'high_risk_alerts': high_risk,
            'monitored_wallets': wallet_count
        }
    
    # =========================================================================
    # RPC ENDPOINTS
    # =========================================================================
    
    def get_rpc_endpoints(self, chain_code: str) -> List[RpcEndpoint]:
        """Get RPC endpoints for chain, ordered by priority."""
        return self.session.query(RpcEndpoint).filter(
            RpcEndpoint.chain_code == chain_code,
            RpcEndpoint.is_active == True
        ).order_by(RpcEndpoint.priority.desc()).all()
    
    def get_best_rpc(self, chain_code: str) -> Optional[str]:
        """Get best available RPC URL for chain."""
        import os
        endpoints = self.get_rpc_endpoints(chain_code)
        for ep in endpoints:
            if ep.requires_key:
                key = os.getenv(ep.key_env_var)
                if key:
                    return ep.url.replace(f'${{{ep.key_env_var}}}', key)
            else:
                return ep.url
        return None
