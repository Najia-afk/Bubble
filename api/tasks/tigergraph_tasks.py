"""
Celery tasks for TigerGraph data synchronization.
Generalized for ANY token on ANY EVM chain - no hardcoded token references.
"""
from celery import shared_task
import logging
from cypher_app.src.tigergraph_loader import get_tg_loader
from utils.logging_config import setup_logging

logger = setup_logging('tigergraph_tasks.log')

# Supported chains - loaded from DB at runtime
SUPPORTED_CHAINS = ['ETH', 'POL', 'BSC', 'BASE', 'ARB', 'OP', 'AVAX', 'FTM']


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


@shared_task(name='sync_token_transfers_24h')
def sync_token_transfers_24h(token_symbol: str, chains: list = None):
    """
    Sync token transfers from last 24h to TigerGraph.
    Generalized for any token on any EVM chain.
    
    Args:
        token_symbol: Token symbol (e.g., 'USDT', 'WETH', 'LINK')
        chains: List of chain trigrams (e.g., ['ETH', 'POL', 'BASE'])
                Defaults to all supported chains
    """
    if chains is None:
        chains = SUPPORTED_CHAINS
    
    # Validate chains
    chains = [c.upper() for c in chains if c.upper() in SUPPORTED_CHAINS]
    
    if not chains:
        return {'status': 'error', 'message': 'No valid chains specified'}
    
    logger.info(f"Starting {token_symbol} transfer sync for chains: {chains}")
    
    tg_loader = get_tg_loader()
    results = {}
    
    for chain in chains:
        try:
            logger.info(f"Syncing {token_symbol} transfers for {chain}...")
            result = tg_loader.load_transfers_24h(token_symbol, chain)
            
            if result:
                results[chain] = 'success'
                logger.info(f"✓ {chain} {token_symbol} transfers synced")
            else:
                results[chain] = 'no_data'
                logger.warning(f"⚠ {chain} {token_symbol} - no data found")
                
        except Exception as e:
            results[chain] = f'error: {str(e)}'
            logger.error(f"✗ Error syncing {token_symbol} on {chain}: {e}")
    
    return {
        'status': 'completed', 
        'token': token_symbol,
        'results': results
    }


@shared_task(name='sync_investigation_addresses')
def sync_investigation_addresses(case_id: str = None):
    """
    Sync investigation case addresses to TigerGraph.
    Loads addresses from database and syncs their transfer history.
    
    Args:
        case_id: Optional specific case ID. If None, syncs all cases.
    """
    logger.info(f"Starting investigation address sync: {case_id or 'all cases'}")
    
    try:
        from utils.database import get_session_factory
        from api.services.data_access import DataAccess
        
        Session = get_session_factory()
        session = Session()
        data = DataAccess(session)
        
        cases = data.get_cases()
        
        if case_id:
            cases = [c for c in cases if c.id == case_id]
        
        if not cases:
            return {'status': 'error', 'message': f'No cases found: {case_id}'}
        
        tg_loader = get_tg_loader()
        results = {}
        
        for case in cases:
            case_results = {}
            
            for wallet in case.wallets:
                addr = wallet.address
                chain = wallet.chain_code.upper()
                
                if chain not in SUPPORTED_CHAINS:
                    case_results[addr[:10]] = f'unsupported_chain: {chain}'
                    continue
                
                try:
                    result = tg_loader.load_wallet_transfers(addr, chain)
                    case_results[addr[:10]] = 'success' if result else 'no_data'
                except Exception as e:
                    case_results[addr[:10]] = f'error: {str(e)}'
                    logger.error(f"Error syncing {addr} on {chain}: {e}")
            
            results[case.id] = case_results
        
        session.close()
        logger.info(f"Investigation sync completed: {len(cases)} cases")
        return {'status': 'completed', 'results': results}
        
    except Exception as e:
        logger.error(f"Investigation sync failed: {e}")
        return {'status': 'error', 'message': str(e)}


@shared_task(name='full_tigergraph_sync')
def full_tigergraph_sync(token_symbols: list = None, chains: list = None):
    """
    Perform full sync: tokens + transfers for specified tokens/chains.
    Generalized - no hardcoded token references.
    
    Args:
        token_symbols: List of token symbols to sync. If None, syncs all registered tokens.
        chains: List of chain trigrams. If None, uses all supported chains.
    """
    logger.info("Starting full TigerGraph sync...")
    
    if chains is None:
        chains = SUPPORTED_CHAINS
    
    tg_loader = get_tg_loader()
    results = {'tokens': None, 'transfers': {}}
    
    # Sync tokens first
    try:
        token_result = tg_loader.load_tokens()
        results['tokens'] = 'success' if token_result else 'failed'
    except Exception as e:
        results['tokens'] = f'error: {str(e)}'
        logger.error(f"Token sync error: {e}")
    
    # If no specific tokens, get all registered tokens
    if token_symbols is None:
        try:
            from api.application.erc20models import Token
            from api import db_session_factory
            
            with db_session_factory() as session:
                registered_tokens = session.query(Token.symbol).distinct().all()
                token_symbols = [t[0] for t in registered_tokens] if registered_tokens else []
        except Exception as e:
            logger.warning(f"Could not get registered tokens: {e}")
            token_symbols = []
    
    # Sync transfers for each token/chain combination
    for symbol in token_symbols:
        results['transfers'][symbol] = {}
        for chain in chains:
            try:
                transfer_result = tg_loader.load_transfers_24h(symbol, chain)
                results['transfers'][symbol][chain] = 'success' if transfer_result else 'no_data'
            except Exception as e:
                results['transfers'][symbol][chain] = f'error: {str(e)}'
                logger.error(f"Transfer sync error for {symbol} on {chain}: {e}")
    
    logger.info(f"Full sync completed: {results}")
    return {'status': 'completed', 'results': results}


# Legacy alias for backward compatibility (deprecated)
sync_ghst_transfers_24h = lambda token_symbol='USDT', chains=None: sync_token_transfers_24h(token_symbol, chains)
