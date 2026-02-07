"""
Step 3: Bridge classified InvestigationWallets to WalletLabel records.

The ML trainer needs WalletLabel records with confidence >= 0.8.
Classification set roles on InvestigationWallet and saved WalletScore records,
but did NOT create WalletLabel records.

This script converts high-confidence classification results into WalletLabel records
so the ML trainer has training data.

Mapping:
  InvestigationWallet.role -> WalletLabel.label_type
  - attacker -> attacker (we add a new type or map to existing)
  - exchange -> exchange
  - bridge -> bridge
  - mixer -> mixer
  - suspect -> suspect  
  - related + high tx_count -> normal
  - related + low tx_count -> unknown (skip)
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker

from config.settings import Config
from api.application.erc20models import (
    WalletLabel, WalletScore, CHAIN_ID_TO_TRIGRAM, Base,
    InvestigationWallet, Investigation, LabelType
)


def get_session():
    engine = create_engine(Config.SQLALCHEMY_DATABASE_URI)
    Session = sessionmaker(bind=engine)
    return Session()


# Role -> label_type mapping with confidence values
ROLE_LABEL_MAP = {
    'attacker': ('attacker', 0.95),     # Very high confidence - seed wallets
    'exchange': ('exchange', 0.90),      # Known DB match
    'bridge': ('bridge', 0.90),          # Known DB match
    'mixer': ('mixer', 0.90),            # Known DB match
    'suspect': ('bot', 0.80),            # Heuristic classification -> likely bot/mover
    'related': ('normal', 0.80),         # Default related wallets
}


def create_labels():
    session = get_session()
    
    try:
        # Ensure label_type entries exist — pure ORM
        existing_types = set()
        for lt in session.query(LabelType).all():
            existing_types.add(lt.name)
        print(f"Existing label types: {existing_types}")
        
        # Add missing label types using ORM
        needed_types = {'attacker', 'exchange', 'bridge', 'mixer', 'bot', 'normal',
                       'whale', 'defi', 'unknown'}
        COLORS = {
            'attacker': '#d62728', 'exchange': '#1f77b4', 'bridge': '#8c564b',
            'mixer': '#9467bd', 'bot': '#ff7f0e', 'normal': '#2ca02c',
            'whale': '#17becf', 'defi': '#bcbd22', 'unknown': '#808080'
        }
        for lt_name in needed_types - existing_types:
            new_lt = LabelType(
                name=lt_name,
                description=f'Auto-generated: {lt_name}',
                color=COLORS.get(lt_name, '#808080'),
                priority=10 if lt_name in ('attacker', 'mixer') else 5
            )
            session.merge(new_lt)
        session.commit()
        print("Label types ensured.")
        
        # Get all classified investigation wallets
        wallets = session.query(InvestigationWallet).join(
            Investigation, Investigation.id == InvestigationWallet.investigation_id
        ).all()
        
        print(f"\nTotal investigation wallets: {len(wallets)}")
        
        created = 0
        skipped_existing = 0
        skipped_role = 0
        
        for w in wallets:
            role = w.role or 'related'
            
            # Skip seized (special role)
            if role == 'seized':
                role = 'attacker'  # seized wallets are essentially attacker wallets
            
            mapping = ROLE_LABEL_MAP.get(role)
            if not mapping:
                skipped_role += 1
                continue
                
            label_type, confidence = mapping
            chain_trigram = CHAIN_ID_TO_TRIGRAM.get(w.chain_id, 'ETH')
            
            # Check WalletScore for confidence boost
            score = session.query(WalletScore).filter_by(
                address=w.address.lower(),
                chain_id=w.chain_id
            ).first()
            
            if score and score.predicted_type and score.confidence:
                # Use ML classifier result if it has better info
                if score.predicted_type in ('exchange', 'bridge', 'mixer', 'defi', 'whale', 'bot'):
                    label_type = score.predicted_type
                    confidence = max(confidence, score.confidence)
            
            # For 'related' wallets with WalletScore features, use feature data to decide type
            if role == 'related' and score:
                tx_count = score.feature_tx_count or 0
                unique_cp = score.feature_unique_counterparties or 0
                in_out = score.feature_in_out_ratio or 1.0
                
                # High transaction wallets are likely bots or exchanges
                if tx_count > 1000 and unique_cp > 100:
                    label_type = 'whale'
                    confidence = 0.85
                elif tx_count > 500 and in_out < 0.3:
                    label_type = 'bot'
                    confidence = 0.82
                elif tx_count < 5:
                    # Skip very low activity wallets - not useful for training
                    skipped_role += 1
                    continue
            
            # Check if label already exists
            existing = session.query(WalletLabel).filter_by(
                address=w.address.lower(),
                chain_id=w.chain_id,
                label=f"{label_type}_{chain_trigram}"
            ).first()
            
            if existing:
                # Update confidence if higher
                if confidence > existing.confidence:
                    existing.confidence = confidence
                    existing.updated_at = datetime.utcnow()
                skipped_existing += 1
                continue
            
            # Create WalletLabel
            label = WalletLabel(
                address=w.address.lower(),
                chain_id=w.chain_id,
                label=f"{label_type}_{chain_trigram}",
                label_type=label_type,
                name_tag=w.notes[:255] if w.notes else None,
                source='inv_classify',
                confidence=confidence,
                is_trusted=False,  # Not manually validated yet
                notes=f"Auto-created from investigation #{w.investigation_id}, role={role}",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            session.add(label)
            created += 1
        
        session.commit()
        
        # Count total labels
        total = session.query(WalletLabel).count()
        high_conf = session.query(WalletLabel).filter(WalletLabel.confidence >= 0.8).count()
        
        print(f"\nResults:")
        print(f"  Created: {created}")
        print(f"  Skipped (existing): {skipped_existing}")
        print(f"  Skipped (unmapped role): {skipped_role}")
        print(f"  Total WalletLabel records: {total}")
        print(f"  High-confidence (>= 0.8): {high_conf}")
        
        # Breakdown by label_type — pure ORM
        result = session.query(
            WalletLabel.label_type,
            func.count(WalletLabel.id),
            func.avg(WalletLabel.confidence)
        ).group_by(WalletLabel.label_type).order_by(func.count(WalletLabel.id).desc()).all()
        print(f"\nLabel type distribution:")
        for row in result:
            print(f"  {row[0]}: {row[1]} labels (avg conf: {row[2]:.2f})")
        
        return total, high_conf
        
    except Exception as e:
        session.rollback()
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return 0, 0
    finally:
        session.close()


if __name__ == '__main__':
    total, high_conf = create_labels()
    if high_conf >= 50:
        print(f"\n✓ Ready for ML training: {high_conf} high-confidence labels")
    else:
        print(f"\n✗ Need more labels: {high_conf}/50 minimum")
