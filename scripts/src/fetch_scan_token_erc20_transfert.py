#fetch_scan_token_erc20_transfert.py
import os
import logging
import time
import argparse
import requests
from datetime import datetime
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import create_engine, select, update, func
from api.application.erc20models import Token, Base  # Ensure Base is imported from erc20models
import api.application.erc20models as erc20models  # For dynamic table creation functions
from utils.database import get_session_factory
from utils.logging_config import setup_logging
from sqlalchemy.exc import IntegrityError
from config.settings import Config

erc20_tansfert_logger = setup_logging('fetch_scan_token_erc20_transfert.log')

API_RATE_LIMIT_SLEEP = 30  # Sleep 30 seconds between API calls to respect rate limits

def get_api_key(trigram):
    """Get API key for blockchain scanner"""
    keys = {
        'ETH': Config.ETHERSCAN_API_KEY,
        'BSC': Config.BSCSCAN_API_KEY,
        'POL': Config.POLYGONSCAN_API_KEY,
        'BASE': Config.BASESCAN_API_KEY
    }
    return keys.get(trigram.upper(), Config.ETHERSCAN_API_KEY)

def get_api_url(trigram, contract_address, from_block, to_block='latest'):
    domain_mapping = {
        "ETH": "api.etherscan.io",
        "BSC": "api.bscscan.com",
        "POL": "api.polygonscan.com",
        "BASE": "api.basescan.org",
    }
    domain = domain_mapping.get(trigram.upper())
    if not domain:
        raise ValueError(f"Unsupported blockchain trigram: {trigram}")
    
    api_key = get_api_key(trigram)
    return f"https://{domain}/api?module=account&action=tokentx&contractaddress={contract_address}&startblock={from_block}&endblock={to_block}&sort=asc&apikey={api_key}"

def fetch_erc20_transfer_data(contract_address, from_block, to_block, trigram):
    url = get_api_url(trigram, contract_address, from_block, to_block)
    response = requests.get(url)
    if response.status_code == 200 and response.json().get("status") == "1":
        return response.json().get("result")
    else:
        erc20_tansfert_logger.info(f"Failed to fetch data for {contract_address}: {response.status_code}")
        return []

def get_transfer_event_class(symbol, trigram):
    class_name = f"{symbol.capitalize()}{trigram.capitalize()}ERC20TransferEvent"
    return getattr(erc20models, class_name, None)

def get_block_transfer_event_class(trigram):
    class_name = f"{trigram.capitalize()}BlockTransferEvent"
    return getattr(erc20models, class_name, None)

def process_and_store_transfers(data_list, contract_address, session, trigram):
    symbol = session.query(Token.symbol).filter(Token.contract_address == contract_address).scalar()
    TransferEventClass = get_transfer_event_class(symbol, trigram)
    BlockTransferEventClass = get_block_transfer_event_class(trigram)

    if not TransferEventClass or not BlockTransferEventClass:
        erc20_tansfert_logger.info(f"Class not found for symbol: {symbol}, trigram: {trigram}.")
        return

    # Sort data_list by 'blockNumber' key in ascending order
    sorted_data_list = sorted(data_list, key=lambda x: int(x.get("blockNumber", 0)))

    for data in sorted_data_list:
        block_event = session.query(BlockTransferEventClass).filter_by(hash=data.get("hash")).first()
        if not block_event:
            block_event = BlockTransferEventClass(
                block_number=data.get("blockNumber"),
                hash=data.get("hash"),
                block_hash=data.get("blockHash"),
                confirmations=data.get("confirmations"),
                timestamp=datetime.utcfromtimestamp(int(data.get("timeStamp"))),
            )
            session.add(block_event)
            

        # Check if a transfer event with the unique constraint already exists
        if session.query(TransferEventClass).filter_by(
            hash=data.get("hash"),
            from_contract_address=data.get("from"),
            to_contract_address=data.get("to"),
            value=data.get("value")
        ).first() is None:
            transfer_event = TransferEventClass(
                block_event_hash=block_event.hash if 'block_event' in locals() else data.get("hash"),
                hash=data.get("hash"),
                nonce=data.get("nonce"),
                from_contract_address=data.get("from"),
                to_contract_address=data.get("to"),
                value=data.get("value"),
                transaction_index=data.get("transactionIndex"),
            )
            session.add(transfer_event)

    try:
        session.commit()
        erc20_tansfert_logger.info(f"Stored {len(data_list)} transfers for {contract_address}")
    except Exception as e:
        session.rollback()
        erc20_tansfert_logger.info(f"Failed to store transfers for {contract_address}: {e}")


def rotate_and_fetch(trigram):
    SessionFactory = get_session_factory()
    with SessionFactory() as session:
        erc20models.generate_block_transfer_event_classes(session)
        erc20models.generate_erc20_classes(session)
        # Continuously fetch and update tokens
        while True:
            # Fetch tokens that haven't been updated yet
            tokens = session.query(Token).filter(Token.transfert_erc20_tag == None, Token.trigram == trigram).order_by(Token.symbol).all()
            if not tokens:
                session.query(Token).filter(Token.trigram == trigram).update({Token.transfert_erc20_tag: None})
                session.commit()
                erc20_tansfert_logger.info(f"All tokens with trigram {trigram} have been reset for another round of updates.")
                continue

            for token in tokens:
                TransferEventClass = get_transfer_event_class(token.symbol, token.trigram)
                if not TransferEventClass:
                    erc20_tansfert_logger.info(f"No transfer event class found for {token.symbol} on {token.trigram}.")
                    continue
                
                # Assume get_block_transfer_event_class() returns the BlockTransferEvent subclass for the given trigram
                BlockTransferEventClass = get_block_transfer_event_class(trigram)
                
                # Perform a join to get the last block number
                last_block_number = session.query(func.max(BlockTransferEventClass.block_number)) \
                    .join(TransferEventClass, TransferEventClass.block_event_hash == BlockTransferEventClass.hash) \
                    .filter(BlockTransferEventClass.hash == TransferEventClass.block_event_hash) \
                    .scalar() or 0
                
                from_block = last_block_number - 1  # Assuming you want to start from the next block after the last
                to_block = 'latest'
                
                data_list = fetch_erc20_transfer_data(token.contract_address, from_block, to_block, token.trigram)
                if data_list:
                    process_and_store_transfers(data_list, token.contract_address, session, token.trigram)
                    token.transfert_erc20_tag = 1
                    session.commit()
                    erc20_tansfert_logger.info(f"Data fetched and stored for {token.symbol} on {token.trigram} up to block {to_block}.")
                else:
                    erc20_tansfert_logger.info(f"No new data to fetch for {token.symbol} on {token.trigram}.")
                
                time.sleep(API_RATE_LIMIT_SLEEP)  # Respect the API's rate limit


def fetch_transfers_for_token(token, trigram, session):
    """Fetch transfers for a specific token"""
    try:
        TransferEventClass = get_transfer_event_class(token.symbol, trigram)
        if not TransferEventClass:
            erc20_tansfert_logger.warning(f"No transfer event class found for {token.symbol} on {trigram}")
            return False
        
        BlockTransferEventClass = get_block_transfer_event_class(trigram)
        
        # Get last block number
        last_block_number = session.query(func.max(BlockTransferEventClass.block_number)) \
            .join(TransferEventClass, TransferEventClass.block_event_hash == BlockTransferEventClass.hash) \
            .filter(BlockTransferEventClass.hash == TransferEventClass.block_event_hash) \
            .scalar() or 0
        
        from_block = last_block_number - 1 if last_block_number > 0 else 0
        to_block = 'latest'
        
        data_list = fetch_erc20_transfer_data(token.contract_address, from_block, to_block, trigram)
        
        if data_list:
            process_and_store_transfers(data_list, token.contract_address, session, trigram)
            erc20_tansfert_logger.info(f"Fetched {len(data_list)} transfers for {token.symbol} on {trigram}")
            return True
        else:
            erc20_tansfert_logger.info(f"No new transfers for {token.symbol} on {trigram}")
            return True  # Success even if no new data
            
    except Exception as e:
        erc20_tansfert_logger.error(f"Error fetching transfers for {token.symbol}: {e}")
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Rotate and fetch ERC20 transfer data based on trigram.')
    parser.add_argument('--trigram', type=str, required=True, help='Trigram for the blockchain (e.g., ETH)')
    args = parser.parse_args()

    rotate_and_fetch(args.trigram)