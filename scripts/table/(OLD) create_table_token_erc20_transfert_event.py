#!/usr/bin/python3
import psycopg2
import sys
sys.path.append("/etc/bubble/PostgresDB/config/")
from PostgresDB_config import get_db_connection


def create_table():
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        
        create_table_query = '''CREATE TABLE token_erc20_transfer_event  (
            id SERIAL PRIMARY KEY,
            block_number BIGINT,
            time_stamp TIMESTAMP,
            hash TEXT,
            nonce INT,
            block_hash TEXT,
            from_contract_address TEXT,
            contract_address TEXT,
            to_contract_address TEXT,
            value FLOAT,
            transaction_index INT,
            gas INT,
            gas_price NUMERIC,
            gas_used INT,
            cumulative_gas_used INT,
            input TEXT,
            confirmations INT); '''

        cursor.execute(create_table_query)
        connection.commit()
        print("Table created successfully in PostgreSQL ")
        
        create_index_query = '''CREATE INDEX token_erc20_transfer_event_contract_address_idx 
            ON token_erc20_transfer_event (contract_address); '''
        cursor.execute(create_index_query)
        connection.commit()
        print("Index on contract_address field created successfully in PostgreSQL ")
        
        create_composite_index_query = '''CREATE INDEX token_erc20_transfer_event_composite_idx 
            ON token_erc20_transfer_event (block_number, hash, nonce, from_contract_address, contract_address, 
            to_contract_address, value, transaction_index, input); '''
        cursor.execute(create_composite_index_query)
        connection.commit()
        print("Composite index created successfully in PostgreSQL ")

    except (Exception, psycopg2.Error) as error :
        print ("Error while creating PostgreSQL table and indexes", error)

    finally:
        #closing database connection.
        if(connection):
                cursor.close()
                connection.close()
                print("PostgreSQL connection is closed")

create_table()
