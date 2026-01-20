"""
Generic Token Data Fetcher Task
Fetches price history and/or transfer events for any token on specified chains
"""
from celery import shared_task
import logging
from datetime import datetime
import time
from utils.logging_config import setup_logging
from utils.database import get_session_factory
from api.application.erc20models import Token
from scripts.src.fetch_erc20_price_history_coingecko import fetch_and_store_price_history
from scripts.src.fetch_scan_token_erc20_transfert import fetch_transfers_for_token

logger = setup_logging('fetch_token_data.log')


@shared_task(name='fetch_token_data_task')
def fetch_token_data_task(task_data):
    """
    Generic task to fetch token data
    
    Args:
        task_data: dict with keys:
            - symbol: Token symbol
            - chains: List of chain trigrams
            - start_date: Start date (YYYY-MM-DD)
            - end_date: End date (YYYY-MM-DD)
            - fetch_mode: 'price_history', 'transfers', or 'both'
    """
    symbol = task_data.get('symbol')
    chains = task_data.get('chains', [])
    start_date = task_data.get('start_date')
    end_date = task_data.get('end_date')
    fetch_mode = task_data.get('fetch_mode', 'both')
    
    logger.info(f"Starting fetch for {symbol} on chains {chains} from {start_date} to {end_date}")
    
    SessionFactory = get_session_factory()
    results = {}
    
    with SessionFactory() as session:
        try:
            # Get tokens for each chain
            for chain_trigram in chains:
                logger.info(f"Processing {symbol} on {chain_trigram}...")
                
                # Find token (case-insensitive)
                token = session.query(Token).filter(
                    Token.symbol.ilike(symbol),
                    Token.trigram.ilike(chain_trigram)
                ).first()
                
                if not token:
                    logger.warning(f"Token {symbol} not found on {chain_trigram}")
                    results[chain_trigram] = {
                        'status': 'error',
                        'message': 'Token not found'
                    }
                    continue
                
                chain_results = {}
                
                # Fetch price history
                if fetch_mode in ['price_history', 'both']:
                    try:
                        logger.info(f"Fetching price history for {symbol} on {chain_trigram}...")
                        
                        # Convert dates to timestamps
                        start_ts = int(datetime.strptime(start_date, "%Y-%m-%d").timestamp())
                        end_ts = int(datetime.strptime(end_date, "%Y-%m-%d").timestamp())
                        
                        # Use existing script
                        price_result = fetch_and_store_price_history(
                            token.contract_address,
                            token.asset_platform_id,
                            start_ts,
                            end_ts,
                            session
                        )
                        
                        chain_results['price_history'] = 'success' if price_result else 'failed'
                        
                        # Update token tag
                        token.history_tag = 1
                        session.commit()
                        
                        time.sleep(2)  # Rate limiting
                        
                    except Exception as e:
                        logger.error(f"Error fetching price history: {e}")
                        chain_results['price_history'] = f'error: {str(e)}'
                
                # Fetch transfer events
                if fetch_mode in ['transfers', 'both']:
                    try:
                        logger.info(f"Fetching transfers for {symbol} on {chain_trigram}...")
                        
                        # Use existing script
                        transfer_result = fetch_transfers_for_token(
                            token,
                            chain_trigram,
                            session
                        )
                        
                        chain_results['transfers'] = 'success' if transfer_result else 'failed'
                        
                        # Update token tag
                        token.transfert_erc20_tag = 1
                        session.commit()
                        
                        time.sleep(5)  # Rate limiting for scanner APIs
                        
                    except Exception as e:
                        logger.error(f"Error fetching transfers: {e}")
                        chain_results['transfers'] = f'error: {str(e)}'
                
                results[chain_trigram] = chain_results
            
            logger.info(f"Fetch completed for {symbol}: {results}")
            return {
                'status': 'completed',
                'symbol': symbol,
                'results': results
            }
            
        except Exception as e:
            logger.error(f"Error in fetch task: {e}")
            return {
                'status': 'error',
                'error': str(e)
            }
