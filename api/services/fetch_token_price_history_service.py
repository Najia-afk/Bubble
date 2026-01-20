#fetch_token_price_history_service.py
import asyncio
import logging
from flask import g
from graphql import graphql
from graphql_app.schemas.fetch_token_price_history_schema import schema as token_price_history_schema
from utils.logging_config import setup_logging

# Use your custom logging setup
price_logger = setup_logging('token_price_history_service.log', log_level=logging.INFO)

async def fetch_token_price_history_async(symbols, start_date, end_date, session):
    """Asynchronously fetch token price history for multiple symbols using GraphQL."""
    query = """
        query TokenPriceHistory($symbols: [String]!, $startDate: DateTime!, $endDate: DateTime!, $limit: Int) {
            tokenPriceHistory(symbols: $symbols, startDate: $startDate, endDate: $endDate, limit: $limit) {
                symbol
                contractAddress
                timestamp
                price
                volume
                marketCap
                source
            }
        }
    """
    variables = {
        "symbols": symbols,
        "startDate": start_date,
        "endDate": end_date,
        "limit": 100000000
    }


    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,  # Executor
        lambda: graphql(
            token_price_history_schema,
            query,
            variable_values=variables,
            context_value={'session': session}
        )
    )

    if result.errors:
        price_logger.error(f"GraphQL query errors: {result.errors}")
        return {"errors": [str(error) for error in result.errors]}

    data = result.data.get('tokenPriceHistory') if result.data else None
    if data is None:
        price_logger.error("No data returned from the GraphQL query")
        return {"error": "No data returned from the GraphQL query"}

    return data

async def get_token_price_history_service(symbols, start_date, end_date, session):
    # Directly await the asynchronous function
    try:
        result = await fetch_token_price_history_async(symbols, start_date, end_date, session)
        return result
    except Exception as e:
        price_logger.error(f"Error in fetching token price history: {e}")
        return {"error": str(e)}
