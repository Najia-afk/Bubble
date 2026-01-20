#fetch_erc20_info_coingecko.py
import os
import logging
import time
import argparse
import requests
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import create_engine
from api.application.erc20models import Token, Base  # Ensure Base is imported from erc20models
import api.application.erc20models as erc20models  # For dynamic table creation functions
from utils.database import get_session_factory
from utils.logging_config import setup_logging

erc20_info_logger = setup_logging('fetch_erc20_info_coingecko.log')

def get_token_info(blockchain, contract_address):
    url = f'https://api.coingecko.com/api/v3/coins/{blockchain}/contract/{contract_address}'
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        return {
            "id": data["id"],
            "symbol": data["symbol"],
            "name": data["name"],
            "asset_platform_id": blockchain,
            "contract_address": contract_address,
            # 'trigram' is added in the `store_token_data` function
        }
    else:
        erc20_info_logger.error(f"Failed to fetch data for {contract_address} on {blockchain}: {response.status_code}")
        return None

def store_token_data_and_generate_tables(blockchain, contract_addresses, trigram):
    SessionFactory = get_session_factory()
    with SessionFactory() as session:
        try:
            Base.metadata.create_all(session.get_bind())
            for contract_address in contract_addresses:
                token_data = get_token_info(blockchain, contract_address)
                if token_data:
                    token_data['trigram'] = trigram
                    existing_token = session.query(Token).filter_by(contract_address=token_data['contract_address']).first()
                    if not existing_token:
                        token = Token(**token_data)
                        session.add(token)
                        session.commit()
                        erc20_info_logger.info(f"Added {token_data['name']} ({token_data['symbol']}) with trigram {trigram} on {blockchain}")
                    else:
                        erc20_info_logger.info(f"Token {token_data['name']} ({token_data['symbol']}) already exists.")
                    time.sleep(10)

            erc20models.generate_block_transfer_event_classes(session)
            erc20models.generate_erc20_classes(session)
            erc20models.apply_dynamic_unique_constraints()
            Base.metadata.create_all(session.get_bind())
            erc20models.adjust_erc20_transfer_event_relationships()
            erc20models.apply_dynamic_indexes(session)
            Base.metadata.create_all(session.get_bind())
            session.commit()

        except Exception as e:
            erc20_info_logger.error(f"An error occurred: {e}")
            # Further error handling or logging as needed

if __name__ == "__main__":
    # Set up argument parsing
    parser = argparse.ArgumentParser(description='Store token data and generate tables based on smart contracts.')
    parser.add_argument('--blockchain', type=str, required=True, help='Blockchain platform (e.g., ethereum)')
    parser.add_argument('--contract_addresses', type=str, required=True, nargs='+', help='List of contract addresses')
    parser.add_argument('--trigram', type=str, required=True, help='Trigram for the blockchain (e.g., ETH)')

    # Parse arguments
    args = parser.parse_args()

    # Convert the list of contract addresses from string format if necessary
    # If the input is already a list, this step can be skipped
    contract_addresses = args.contract_addresses

    # Call the function with command-line arguments
    store_token_data_and_generate_tables(args.blockchain, contract_addresses, args.trigram)


    #python3 -m scripts.src.fetch_erc20_info_coingecko --blockchain polygon-pos --contract_addresses 0x385eeac5cb85a38a9a07a70c73e0a3271cfb54a7 0x3801c3b3b5c98f88a9c9005966aa96aa440b9afc 0x44a6e0be76e1d9620a7f76588e4509fe4fa8e8c8 0x403e967b044d4be25170310157cb1a4bf10bdd0f 0x42e5e06ef5b90fe15f853f59299fc96259209c5c 0x6a3e7c3c6ef65ee26975b12293ca1aad7e1daed2 --trigram POLY
