import asyncio
import logging
from flask import g
from graphql import graphql
from graphql_app.schemas.fetch_last_token_price_history_schema import schema as last_token_price_history_schema
from utils.logging_config import setup_logging

# Use your custom logging setup
last_price_logger = setup_logging('last_token_price_history_service.log', log_level=logging.INFO)

async def fetch_last_token_price_history_async(symbols, session):
    # Modify the query to iterate over symbols
    query = """
    query LastTokenPriceHistory($symbols: [String]!, $limit: Int) {
        lastTokenPriceHistory(symbols: $symbols, limit: $limit) {
            symbol
            price
            }
        }
    """
    variables = {
        "symbols": symbols,
        "limit": 1
    }

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,  # Executor
        lambda: graphql(
            last_token_price_history_schema,
            query,
            variable_values=variables,
            context_value={'session': session}
        )
    )

    if result.errors:
        last_price_logger.error(f"GraphQL query errors: {result.errors}")
        return {"errors": [str(error) for error in result.errors]}

    data = result.data.get('lastTokenPriceHistory') if result.data else None
    if data is None:
        last_price_logger.error("No data returned from the GraphQL query")
        return {"error": "No data returned from the GraphQL query"}

    return data

async def get_last_token_price_history_service(symbols, session):
    """Execute the asynchronous fetch function within the event loop for a list of symbols."""
    try:
        result = await fetch_last_token_price_history_async(symbols, session)
        return result
    except Exception as e:
        last_price_logger.error(f"Error executing last token price history service for symbols {symbols}: {e}")
        return {"error": str(e)}
