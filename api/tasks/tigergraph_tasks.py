"""
Celery tasks for TigerGraph data synchronization
"""
from celery import shared_task
import logging
from cypher_app.src.tigergraph_loader import get_tg_loader
from utils.logging_config import setup_logging

logger = setup_logging('tigergraph_tasks.log')


@shared_task(name='sync_tokens_to_tigergraph')
def sync_tokens_to_tigergraph():
    """Sync all tokens from PostgreSQL to TigerGraph"""
    logger.info("Starting token sync to TigerGraph...")
    try:
        tg_loader = get_tg_loader()
        result = tg_loader.load_tokens()
        if result:
            logger.info("✓ Token sync completed successfully")
            return {'status': 'success', 'message': 'Tokens synced to TigerGraph'}
        else:
            logger.error("✗ Token sync failed")
            return {'status': 'error', 'message': 'Token sync failed'}
    except Exception as e:
        logger.error(f"Error in token sync task: {e}")
        return {'status': 'error', 'message': str(e)}


@shared_task(name='sync_ghst_transfers_24h')
def sync_ghst_transfers_24h(token_symbol='GHST', chains=None):
    """Sync GHST transfers from last 24h to TigerGraph"""
    if chains is None:
        chains = ['POL', 'BASE']
    
    logger.info(f"Starting GHST transfer sync for chains: {chains}")
    
    tg_loader = get_tg_loader()
    results = {}
    for chain in chains:
        try:
            logger.info(f"Syncing {token_symbol} transfers for {chain}...")
            result = tg_loader.load_transfers_24h(token_symbol, chain)
            
            if result:
                results[chain] = 'success'
                logger.info(f"✓ {chain} transfers synced")
            else:
                results[chain] = 'failed'
                logger.error(f"✗ {chain} transfers failed")
                
        except Exception as e:
            results[chain] = f'error: {str(e)}'
            logger.error(f"✗ Error syncing {chain}: {e}")
    
    return {'status': 'completed', 'results': results}


@shared_task(name='full_tigergraph_sync')
def full_tigergraph_sync():
    """Perform full sync: tokens + GHST transfers"""
    logger.info("Starting full TigerGraph sync...")
    
    tg_loader = get_tg_loader()
    results = {}
    
    # Sync tokens first
    try:
        token_result = tg_loader.load_tokens()
        results['tokens'] = 'success' if token_result else 'failed'
    except Exception as e:
        results['tokens'] = f'error: {str(e)}'
        logger.error(f"Token sync error: {e}")
    
    # Sync GHST transfers for both chains
    for chain in ['POL', 'BASE']:
        try:
            transfer_result = tg_loader.load_transfers_24h('GHST', chain)
            results[f'ghst_{chain.lower()}'] = 'success' if transfer_result else 'failed'
        except Exception as e:
            results[f'ghst_{chain.lower()}'] = f'error: {str(e)}'
            logger.error(f"Transfer sync error for {chain}: {e}")
    
    logger.info(f"Full sync completed: {results}")
    return {'status': 'completed', 'results': results}
