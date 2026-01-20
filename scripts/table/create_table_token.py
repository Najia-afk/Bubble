#!/usr/bin/python3
import psycopg2
import sys
sys.path.append("/etc/bubble/PostgresDB/config/")
from PostgresDB_config import get_db_connection


def create_table():
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        
        create_table_query = '''CREATE TABLE token (
            id varchar(255) PRIMARY KEY,
            symbol varchar(255) NOT NULL,
            name varchar(255) NOT NULL,
            asset_platform_id varchar(255) NOT NULL,
            erc varchar(255) NOT NULL,
            contract_address varchar(255) NOT NULL
            project_tag varchar(255) NULL,
            history_tag INTEGER NULL,
            transfert_erc20_tag INTEGER NULL); '''

        cursor.execute(create_table_query)
        connection.commit()
        print("Table created successfully in PostgreSQL ")

    except (Exception, psycopg2.Error) as error :
        print ("Error while creating PostgreSQL table", error)

    finally:
        #closing database connection.
        if(connection):
                cursor.close()
                connection.close()
                print("PostgreSQL connection is closed")

create_table()
