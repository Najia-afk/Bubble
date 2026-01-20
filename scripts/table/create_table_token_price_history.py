def create_table():
    try:
        connection = get_db_connection()
        cursor = connection.cursor()

        # Create table
        cursor.execute('''
            CREATE TABLE token_price_history (
                id SERIAL PRIMARY KEY,
                contract_address VARCHAR(255) NOT NULL,
                date DATE NOT NULL,
                timestamp TIMESTAMP NOT NULL,
                price FLOAT NOT NULL,
                volume FLOAT NOT NULL,
                market_cap FLOAT NOT NULL
            )
        ''')

        # Create index on contract_address
        cursor.execute('CREATE INDEX token_price_history_contract_address_idx ON token_price_history (contract_address)')

        # Create index on (contract_address, date)
        cursor.execute('CREATE INDEX token_price_history_contract_address_date_idx ON token_price_history (contract_address, date)')
        
        # Create index on (timestamp)
        cursor.execute('CREATE INDEX token_price_history_timestamp_idx ON token_price_history (timestamp)')


        connection.commit()
        print("Table token_price_history created successfully")

        # Close cursor and connection
        cursor.close()
        connection.close()
        print("PostgreSQL connection is closed")

    except (Exception, psycopg2.Error) as error :
        print ("Error while creating PostgreSQL table and index", error)

    finally:
        #closing database connection.
        if(connection):
                cursor.close()
                connection.close()
                print("PostgreSQL connection is closed")

create_table()
