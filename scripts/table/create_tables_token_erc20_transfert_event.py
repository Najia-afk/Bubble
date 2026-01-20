#!/usr/bin/python3
import psycopg2
import sys
sys.path.append("/etc/bubble/PostgresDB/config/")
from PostgresDB_config import get_db_connection


def create_table():
    try:
        connection = get_db_connection()
        cursor = connection.cursor()

        # Get a list of ERC20 contract addresses on the Polygon network with the name starting by "Aavegotchi"
        get_contract_addresses_query = '''SELECT symbol, contract_address
                                           FROM token
                                           WHERE erc = 'erc20' AND asset_platform_id = 'polygon-pos' AND (name LIKE 'Aavegotchi%' OR name LIKE 'GAX%') '''
        cursor.execute(get_contract_addresses_query)
        contract_addresses = cursor.fetchall()

        # Create the block_transfer_event table
        create_block_table_query = '''CREATE TABLE block_transfer_event  (
                                       id SERIAL PRIMARY KEY,
                                       block_number BIGINT,
                                       hash TEXT,
                                       block_hash TEXT,
                                       confirmations INT); '''
        cursor.execute(create_block_table_query)
        connection.commit()
        print("Table 'block_transfer_event' created successfully in PostgreSQL")

        # Create indexes for the block_transfer_event table
        create_block_index1_query = '''CREATE INDEX block_transfer_event_block_number_idx 
                                       ON block_transfer_event (block_number); '''
        cursor.execute(create_block_index1_query)
        connection.commit()
        print("Index 'block_transfer_event_block_number_idx' created successfully in PostgreSQL")
        
        create_block_index3_query = '''CREATE INDEX block_transfer_event_hash_idx 
                                       ON block_transfer_event (hash); '''
        cursor.execute(create_block_index3_query)
        connection.commit()
        print("Index 'block_transfer_event_hash_idx' created successfully in PostgreSQL")

        # Create a dynamic table for each contract address
        for contract_address in contract_addresses:
            symbol = contract_address[0]
            contract_address = contract_address[1]

            create_erc20_transfer_table_query = f'''CREATE TABLE {symbol}_erc20_poly  (
                                                    id SERIAL PRIMARY KEY,
                                                    time_stamp TIMESTAMP,
                                                    hash TEXT,
                                                    nonce INT,
                                                    from_contract_address TEXT,
                                                    to_contract_address TEXT,
                                                    value FLOAT,
                                                    transaction_index INT); '''
            cursor.execute(create_erc20_transfer_table_query)
            connection.commit()
            print(f"Table '{symbol}_erc20_poly' created successfully in PostgreSQL")

            # Drop any existing index on the hash field for the {symbol}_erc20_poly table
            drop_index_query = f'''DROP INDEX IF EXISTS {symbol}_erc20_poly_hash_idx; '''
            cursor.execute(drop_index_query)
            connection.commit()
        
            # Create an index on the hash field for the {symbol}_erc20_poly table
            create_index_query = f'''CREATE INDEX {symbol}_erc20_poly_hash_idx 
                                    ON {symbol}_erc20_poly (hash); '''
            cursor.execute(create_index_query)
            connection.commit()
            print(f"Index '{symbol}_erc20_poly_hash_idx' created successfully in PostgreSQL")
            
            # Create an index on the time_stamp field for the {symbol}_erc20_poly table
            create_index2_query = f'''CREATE INDEX {symbol}_erc20_poly_time_stamp_idx 
                                    ON {symbol}_erc20_poly (time_stamp); '''
            cursor.execute(create_index2_query)
            connection.commit()
            print(f"Index '{symbol}_erc20_poly_time_stamp_idx' created successfully in PostgreSQL")

            # Drop any existing composite index on the {symbol}_erc20_poly table
            drop_composite_index_query = f'''DROP INDEX IF EXISTS {symbol}_erc20_poly_composite_idx; '''
            cursor.execute(drop_composite_index_query)
            connection.commit()

            # Create a composite index on the {symbol}_erc20_poly table
            create_composite_index_query = f'''CREATE INDEX {symbol}_erc20_poly_composite_idx 
                                                ON {symbol}_erc20_poly (hash, nonce, 
                                                from_contract_address, to_contract_address); '''
            cursor.execute(create_composite_index_query)
            connection.commit()
            print(f"Composite index 'token_erc20_transfer_event_{contract_address}_composite_idx' created successfully in PostgreSQL")

    except (Exception, psycopg2.Error) as error :
        print ("Error while creating PostgreSQL tables and indexes", error)

    finally:
        #closing database connection.
        if(connection):
                cursor.close()
                connection.close()
                print("PostgreSQL connection is closed")

create_table()
