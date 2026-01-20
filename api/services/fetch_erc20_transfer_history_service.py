# fetch_erc20_transfer_history_service.py
import asyncio
import logging
from flask import g
from graphql import graphql
from graphql_app.schemas.fetch_erc20_transfer_history_schema import schema as erc20_transfer_history_schema
from utils.logging_config import setup_logging

# Custom logging setup
erc20_transfer_logger = setup_logging('erc20_transfer_history_service.log', log_level=logging.INFO)

async def fetch_erc20_transfer_history_for_trigram(trigram, symbols, start_block, end_block, after, limit, session):
    """Asynchronously fetch ERC20 transfer history for a specified trigram and its symbols with pagination."""
    query = """
    query ERC20TransferEvents($trigram: String!, $symbols: [String]!, $startBlock: Int!, $endBlock: Int!, $after: String, $limit: Int) {
        erc20TransferEvents(trigram: $trigram, symbols: $symbols, startBlock: $startBlock, endBlock: $endBlock, after: $after, limit: $limit) {
            edges {
                node {
                    blockNumber
                    hash
                    tokenSymbol
                    transactionIndex
                    fromContractAddress
                    toContractAddress
                    value
                    confirmations
                    timestamp
                }
                cursor
            }
            pageInfo {
                hasNextPage
                endCursor
            }
        }
    }
    """
    variables = {
        "trigram": trigram,
        "symbols": symbols,
        "startBlock": start_block,
        "endBlock": end_block,
        "after": after,  # Now properly used
        "limit": limit # Now properly used
    }

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        lambda: graphql(
            erc20_transfer_history_schema,
            query,
            variable_values=variables,
            context_value={'session': session}
        )
    )

    if result.errors:
        error_messages = [str(error) for error in result.errors]
        erc20_transfer_logger.error(f"GraphQL query errors: {error_messages}")
        return {"errors": error_messages}

    data = result.data.get('erc20TransferEvents') if result.data else {"edges": [], "pageInfo": {}}
    return {"data": data}

async def fetch_erc20_transfer_history_chunk(trigram_info, session, after=None, limit=10000):
    """
    Fetch a chunk of ERC20 transfer history for a given trigram and its symbols,
    starting from a cursor ('after') up to a 'limit'.
    """
    result = await fetch_erc20_transfer_history_for_trigram(
        trigram=trigram_info['trigram'],
        symbols=trigram_info['symbols'],
        start_block=trigram_info['startBlock'],
        end_block=trigram_info['endBlock'],
        after=after,
        limit=limit,
        session=session
    )
    return result

async def get_erc20_transfer_history_service(trigrams_info, session):
    """
    Execute fetching ERC20 transfer history for multiple trigrams concurrently,
    handling pagination by fetching data in chunks until all data is retrieved.
    """
    all_data = []
    try:
        for trigram_info in trigrams_info:
            hasNextPage = True
            after_cursor = None
            while hasNextPage:
                # Fetch a chunk of data
                chunk_result = await fetch_erc20_transfer_history_chunk(trigram_info, session, after=after_cursor, limit=10000)
                
                # Check for errors in fetching data
                if "errors" in chunk_result:
                    print(f"Errors fetching data for {trigram_info['trigram']}: {chunk_result['errors']}")
                    break  # Exit the loop for this trigram in case of errors
                
                data = chunk_result.get("data", {})
                pageInfo = data.get("pageInfo", {})
                hasNextPage = pageInfo.get("hasNextPage", False)
                after_cursor = pageInfo.get("endCursor")  # Update the cursor for the next fetch
                
                # Aggregate fetched data
                all_data.extend(data.get("edges", []))

        # Return aggregated results from all fetches
        return all_data

    except Exception as e:
        erc20_transfer_logger.error(f"Unexpected error: {e}")
        return {"error": str(e)}
    
# asyncio.run(get_erc20_transfer_history_service(trigrams_info, session))