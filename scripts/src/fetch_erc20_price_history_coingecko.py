#fetch_erc20_price_history_coingecko.py
import os
import logging
import time
import argparse
import requests
from datetime import datetime
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import create_engine, select, update, func
from sqlalchemy.dialects.postgresql import insert
from api.application.erc20models import Token, TokenPriceHistory 
from utils.database import get_session_factory
from utils.logging_config import setup_logging

erc20_price_logger = setup_logging('fetch_erc20_price_history_coingecko.log')


def get_token_price_history_data(contract_address, asset_platform_id, from_timestamp, to_timestamp, session):
    url = f'https://api.coingecko.com/api/v3/coins/{asset_platform_id}/contract/{contract_address}/market_chart/range?vs_currency=usd&from={from_timestamp}&to={to_timestamp}'
    headers = {'accept': 'application/json'}
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        data = response.json()
        prices, market_caps, volumes = data["prices"], data["market_caps"], data["total_volumes"]
        return [(contract_address, int(p[0] / 1000), datetime.fromtimestamp(int(p[0] / 1000)).strftime('%Y-%m-%d %H:%M:%S'), p[1], mc[1], v[1], 'coingecko') for p, mc, v in zip(prices, market_caps, volumes)]
    else:
        erc20_price_logger.error(f'Error fetching data for {contract_address}: {response.status_code}')
        return []

def store_token_price_history_data(data_list, session):
    for data in data_list:
        stmt = insert(TokenPriceHistory).values(
            contract_address=data[0],
            timestamp=datetime.fromtimestamp(data[1]),
            date=datetime.strptime(data[2], '%Y-%m-%d %H:%M:%S'),
            price=data[3],
            market_cap=data[4],
            volume=data[5],
            source=data[6]
        ).on_conflict_do_update(
            index_elements=['contract_address', 'timestamp', 'price'],  # Specify the conflict target
            set_=dict(
                date=datetime.strptime(data[2], '%Y-%m-%d %H:%M:%S'),
                market_cap=data[4],
                volume=data[5],
                source=data[6]
            )
        )
        session.execute(stmt)
    session.commit()


def fetch_and_store_price_history(contract_address, asset_platform_id, from_timestamp, to_timestamp, session):
    """Fetch and store price history for a specific token"""
    try:
        data_list = get_token_price_history_data(
            contract_address, 
            asset_platform_id, 
            from_timestamp, 
            to_timestamp, 
            session
        )
        
        if data_list:
            store_token_price_history_data(data_list, session)
            erc20_price_logger.info(f"Stored {len(data_list)} price points for {contract_address}")
            return True
        else:
            erc20_price_logger.warning(f"No price data returned for {contract_address}")
            return False
            
    except Exception as e:
        erc20_price_logger.error(f"Error fetching price history for {contract_address}: {e}")
        return False


def fetch_erc20_price_history():
    SessionFactory = get_session_factory()
    with SessionFactory() as session:
        while True:
            # Fetch distinct symbols for tokens without an updated history
            symbols = session.query(Token.symbol).filter(Token.history_tag == None).distinct().all()

            if not symbols:
                erc20_price_logger.info("No more tokens without updated history. Resetting tags.")
                session.query(Token).update({Token.history_tag: None}, synchronize_session=False)
                session.commit()
                continue  # Restart the loop after resetting
        
            for symbol_tuple in symbols:
                symbol = symbol_tuple[0]  # Extract symbol from the tuple
                # Fetch all tokens with this symbol that haven't had their history updated
                tokens = session.query(Token).filter(Token.symbol == symbol, Token.history_tag == None).all()
            
                for token in tokens:
                    last_timestamp_query = select(func.max(TokenPriceHistory.timestamp)).filter(TokenPriceHistory.contract_address == token.contract_address)
                    last_timestamp = session.scalar(last_timestamp_query) or 0
                    current_timestamp = int(datetime.now().timestamp())

                    data_list = get_token_price_history_data(token.contract_address, token.asset_platform_id, last_timestamp, current_timestamp, session)
                    if data_list:
                        store_token_price_history_data(data_list, session)
                        # Update history_tag for this token
                        token.history_tag = 1
                        erc20_price_logger.info(f"Updated price history for {token.symbol}")
            
                session.commit()  # Commit updates after processing all tokens for a symbol
                time.sleep(60)  # Throttle requests
