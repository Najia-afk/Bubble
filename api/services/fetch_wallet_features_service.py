# fetch_wallet_features_service.py
"""
Service layer for wallet feature extraction via GraphQL.
Used by ML trainer and feature engineer — single point of access.
"""
import logging
from typing import Dict, List, Optional, Tuple
from graphql import graphql_sync
from graphql_app.schemas.wallet_features_schema import schema as wallet_features_schema
from utils.logging_config import setup_logging

wallet_features_service_logger = setup_logging('wallet_features_service.log', log_level=logging.INFO)


def fetch_wallet_features(address: str, session, investigation_id: int = None) -> Optional[Dict]:
    """
    Fetch aggregate transaction features for a single wallet via GraphQL.
    
    Args:
        address: Wallet address
        session: SQLAlchemy session
        investigation_id: Optional investigation filter
        
    Returns:
        Dict of features or None if no transactions found
    """
    inv_arg = f', investigationId: {investigation_id}' if investigation_id else ''
    
    query = f'''
    {{
        walletFeatures(address: "{address}"{inv_arg}) {{
            address
            txCount
            uniqueCounterparties
            avgTxValue
            maxTxValue
            inOutRatio
            totalVolume
            outCount
            inCount
            uniqueSenders
            uniqueReceivers
        }}
    }}
    '''
    
    result = graphql_sync(
        wallet_features_schema.graphql_schema,
        query,
        context_value={'session': session}
    )
    
    if result.errors:
        wallet_features_service_logger.error(f"GraphQL error for {address}: {result.errors}")
        return None
    
    data = result.data.get('walletFeatures')
    if not data:
        return None
    
    return {
        'tx_count': data['txCount'],
        'unique_counterparties': data['uniqueCounterparties'],
        'avg_tx_value': data['avgTxValue'],
        'max_tx_value': data['maxTxValue'],
        'in_out_ratio': data['inOutRatio'],
        'total_volume': data['totalVolume'],
        'out_count': data['outCount'],
        'in_count': data['inCount'],
        'unique_senders': data['uniqueSenders'],
        'unique_receivers': data['uniqueReceivers'],
    }


def fetch_wallet_features_batch(
    addresses: List[str], session, investigation_id: int = None
) -> List[Dict]:
    """
    Fetch features for many wallets in a SINGLE optimized GraphQL query.
    Scans investigation_transfer once, groups by wallet.
    
    Args:
        addresses: List of wallet addresses
        session: SQLAlchemy session
        investigation_id: Optional investigation filter
        
    Returns:
        List of feature dicts (one per wallet that has transactions)
    """
    if not addresses:
        return []
    
    # Build GraphQL query with address list
    addr_list = ', '.join(f'"{a}"' for a in addresses)
    inv_arg = f', investigationId: {investigation_id}' if investigation_id else ''
    
    query = f'''
    {{
        walletFeaturesBatch(addresses: [{addr_list}]{inv_arg}) {{
            totalRequested
            totalFound
            features {{
                address
                txCount
                uniqueCounterparties
                avgTxValue
                maxTxValue
                inOutRatio
                totalVolume
                outCount
                inCount
                uniqueSenders
                uniqueReceivers
            }}
        }}
    }}
    '''
    
    wallet_features_service_logger.info(f"Batch feature request for {len(addresses)} wallets")
    
    result = graphql_sync(
        wallet_features_schema.graphql_schema,
        query,
        context_value={'session': session}
    )
    
    if result.errors:
        wallet_features_service_logger.error(f"GraphQL batch error: {result.errors}")
        return []
    
    batch = result.data.get('walletFeaturesBatch')
    if not batch:
        return []
    
    wallet_features_service_logger.info(
        f"Batch result: {batch['totalFound']}/{batch['totalRequested']} wallets"
    )
    
    features_list = []
    for feat in batch['features']:
        features_list.append({
            'address': feat['address'],
            'tx_count': feat['txCount'],
            'unique_counterparties': feat['uniqueCounterparties'],
            'avg_tx_value': feat['avgTxValue'],
            'max_tx_value': feat['maxTxValue'],
            'in_out_ratio': feat['inOutRatio'],
            'total_volume': feat['totalVolume'],
            'out_count': feat['outCount'],
            'in_count': feat['inCount'],
            'unique_senders': feat['uniqueSenders'],
            'unique_receivers': feat['uniqueReceivers'],
        })
    
    return features_list


def fetch_validated_labels(session, min_confidence: float = 0.8, chain: str = None) -> List[Dict]:
    """
    Fetch validated wallet labels via GraphQL for ML training.
    
    Args:
        session: SQLAlchemy session
        min_confidence: Minimum confidence threshold
        chain: Optional chain trigram filter
        
    Returns:
        List of {address, chain_id, label_type, confidence}
    """
    from graphql_app.schemas.wallet_labels_schema import schema as labels_schema
    
    chain_arg = f', chain: "{chain}"' if chain else ''
    
    query = f'''
    {{
        validatedLabels(minConfidence: {min_confidence}{chain_arg}) {{
            total
            labels {{
                address
                chainId
                labelType
                confidence
                source
            }}
            distribution {{
                labelType
                count
                avgConfidence
            }}
        }}
    }}
    '''
    
    result = graphql_sync(
        labels_schema.graphql_schema,
        query,
        context_value={'session': session}
    )
    
    if result.errors:
        wallet_features_service_logger.error(f"Labels query error: {result.errors}")
        return []
    
    data = result.data.get('validatedLabels')
    if not data:
        return []
    
    wallet_features_service_logger.info(
        f"Labels: {data['total']} total, distribution: "
        f"{[(d['labelType'], d['count']) for d in data['distribution']]}"
    )
    
    return [
        {
            'address': lbl['address'],
            'chain_id': lbl['chainId'],
            'label_type': lbl['labelType'],
            'confidence': lbl['confidence'],
            'source': lbl['source'],
        }
        for lbl in data['labels']
    ]
