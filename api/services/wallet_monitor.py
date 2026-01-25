# =============================================================================
# Bubble - Wallet Monitor Service (Database-driven)
# All data from PostgreSQL - no hardcoded values
# =============================================================================

import logging
from datetime import datetime
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass
import threading

from sqlalchemy.orm import Session

from api.services.data_access import DataAccess
from api.application.models import MonitoredWallet, Alert

logger = logging.getLogger(__name__)


@dataclass
class WalletAlertDTO:
    """Alert data transfer object."""
    address: str
    chain: str
    alert_type: str
    amount: float
    token: str
    counterparty: str
    tx_hash: str
    timestamp: datetime
    case_id: Optional[str] = None
    risk_score: float = 0.0


class WalletMonitorService:
    """
    Real-time wallet monitoring service.
    All known addresses (mixers, bridges) loaded from DB.
    """
    
    def __init__(self, session: Session):
        self.session = session
        self.data = DataAccess(session)
        self.alert_callbacks: List[Callable[[WalletAlertDTO], None]] = []
        self._running = False
        self._poll_interval = 30
        self._lock = threading.Lock()
        
        # Cache addresses from DB
        self._refresh_known_addresses()
    
    def _refresh_known_addresses(self):
        """Load known addresses from database."""
        self.known_mixers: Dict[str, set] = {}
        self.known_bridges: Dict[str, set] = {}
        
        for chain_code in self.data.get_chain_codes():
            self.known_mixers[chain_code] = self.data.get_mixer_addresses(chain_code)
            self.known_bridges[chain_code] = self.data.get_bridge_addresses(chain_code)
        
        total_mixers = sum(len(v) for v in self.known_mixers.values())
        total_bridges = sum(len(v) for v in self.known_bridges.values())
        logger.info(f"Loaded {total_mixers} mixers, {total_bridges} bridges from DB")
    
    def add_wallet(self, address: str, chain: str, case_id: str = None, 
                   label: str = "") -> MonitoredWallet:
        """Add wallet to monitoring."""
        existing = self.data.get_monitored_wallet(address, chain)
        if existing:
            return existing
        return self.data.add_monitored_wallet(address, chain, case_id, label)
    
    def remove_wallet(self, address: str, chain: str) -> bool:
        """Remove wallet from monitoring."""
        wallet = self.data.get_monitored_wallet(address, chain)
        if wallet:
            wallet.is_active = False
            return True
        return False
    
    def get_wallets(self, chain: str = None, case_id: str = None) -> List[MonitoredWallet]:
        """Get all monitored wallets."""
        return self.data.get_monitored_wallets(chain_code=chain, case_id=case_id)
    
    def get_alerts(self, chain: str = None, alert_type: str = None, 
                   limit: int = 100) -> List[Alert]:
        """Get recent alerts."""
        return self.data.get_alerts(chain_code=chain, alert_type=alert_type, limit=limit)
    
    def get_stats(self) -> Dict:
        """Get monitoring statistics."""
        return self.data.get_alert_stats()
    
    def _is_mixer(self, address: str, chain: str) -> bool:
        """Check if address is a known mixer."""
        addr = address.lower()
        return addr in self.known_mixers.get(chain, set())
    
    def _is_bridge(self, address: str, chain: str) -> bool:
        """Check if address is a known bridge."""
        addr = address.lower()
        return addr in self.known_bridges.get(chain, set())
    
    def _determine_alert_type(self, from_addr: str, to_addr: str, 
                               chain: str, amount: float) -> Optional[str]:
        """Determine alert type based on transaction details."""
        # Check mixer
        if self._is_mixer(to_addr, chain):
            return 'mixer'
        
        # Check bridge
        if self._is_bridge(to_addr, chain):
            return 'bridge'
        
        # Large transfer (>$10k equivalent)
        if amount > 10000:
            return 'large_transfer'
        
        return 'outgoing'
    
    def _calculate_risk_score(self, alert_type: str, amount: float, 
                               to_addr: str, chain: str) -> float:
        """Calculate risk score for transaction."""
        score = 0.0
        
        # Base scores by type
        type_scores = {
            'mixer': 0.9,
            'bridge': 0.5,
            'large_transfer': 0.6,
            'outgoing': 0.2,
            'incoming': 0.1
        }
        score = type_scores.get(alert_type, 0.3)
        
        # Adjust for amount
        if amount > 100000:
            score = min(1.0, score + 0.2)
        elif amount > 50000:
            score = min(1.0, score + 0.1)
        
        # Check if recipient has suspicious tags
        if self.data.is_tagged_as(to_addr, 'potential_hacker'):
            score = min(1.0, score + 0.3)
        elif self.data.is_tagged_as(to_addr, 'confirmed_hacker'):
            score = 1.0
        
        return round(score, 2)
    
    def process_transaction(self, wallet: MonitoredWallet, tx: Dict) -> Optional[Alert]:
        """Process transaction and create alert if needed."""
        from_addr = tx.get('from', '').lower()
        to_addr = tx.get('to', '').lower()
        value = float(tx.get('value', 0))
        tx_hash = tx.get('hash', '')
        
        wallet_addr = wallet.address.lower()
        
        # Determine direction
        if from_addr == wallet_addr:
            alert_type = self._determine_alert_type(from_addr, to_addr, 
                                                     wallet.chain_code, value)
            counterparty = to_addr
        else:
            alert_type = 'incoming'
            counterparty = from_addr
        
        risk_score = self._calculate_risk_score(alert_type, value, 
                                                 counterparty, wallet.chain_code)
        
        # Create alert
        alert = self.data.create_alert(
            wallet_id=wallet.id,
            chain_code=wallet.chain_code,
            alert_type=alert_type,
            amount=value,
            token=tx.get('token', wallet.chain_code),
            counterparty=counterparty,
            tx_hash=tx_hash,
            risk_score=risk_score
        )
        
        # Update wallet stats
        wallet.last_activity = datetime.utcnow()
        wallet.alert_count += 1
        if alert_type == 'incoming':
            wallet.total_in_usd += value
        else:
            wallet.total_out_usd += value
        
        # Notify callbacks
        dto = WalletAlertDTO(
            address=wallet.address,
            chain=wallet.chain_code,
            alert_type=alert_type,
            amount=value,
            token=tx.get('token', wallet.chain_code),
            counterparty=counterparty,
            tx_hash=tx_hash,
            timestamp=datetime.utcnow(),
            case_id=wallet.case_id,
            risk_score=risk_score
        )
        for callback in self.alert_callbacks:
            callback(dto)
        
        return alert
    
    def register_callback(self, callback: Callable[[WalletAlertDTO], None]):
        """Register alert callback."""
        self.alert_callbacks.append(callback)
    
    def refresh_cache(self):
        """Refresh cached addresses from DB."""
        self._refresh_known_addresses()


# =============================================================================
# FACTORY FUNCTION
# =============================================================================

_monitor_instance: Optional[WalletMonitorService] = None

def get_wallet_monitor(session: Session) -> WalletMonitorService:
    """Get or create wallet monitor instance."""
    global _monitor_instance
    if _monitor_instance is None:
        _monitor_instance = WalletMonitorService(session)
    return _monitor_instance
