#!/usr/bin/env python3
"""
Initialize TigerGraph schema and create graph
"""
import sys
import os
import time
import logging

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from cypher_app.utils.tigergraph_client import get_tg_client
from utils.logging_config import setup_logging

logger = setup_logging('tigergraph_init.log')


def init_graph():
    """Initialize TigerGraph graph and schema"""
    try:
        tg = get_tg_client()
        conn = tg.get_connection()
        
        # Read schema file
        schema_path = os.path.join(os.path.dirname(__file__), 'schema.gsql')
        with open(schema_path, 'r') as f:
            schema_gsql = f.read()
        
        logger.info("Creating TigerGraph schema...")
        
        # Execute schema creation
        # Note: This requires admin privileges and graph creation permissions
        # For development, you might need to manually create the graph first
        try:
            result = conn.gsql(schema_gsql)
            logger.info(f"Schema creation result: {result}")
        except Exception as e:
            logger.warning(f"Schema execution returned: {e}")
            logger.info("If graph already exists, this is expected. Continuing...")
        
        # Verify graph exists
        graphs = conn.getGraphs()
        logger.info(f"Available graphs: {graphs}")
        
        if 'BubbleGraph' in graphs or 'BubbleGraph' in str(graphs):
            logger.info("✓ BubbleGraph is ready")
            return True
        else:
            logger.error("✗ BubbleGraph not found")
            return False
            
    except Exception as e:
        logger.error(f"Error initializing TigerGraph: {e}")
        return False


if __name__ == "__main__":
    print("Initializing TigerGraph schema...")
    success = init_graph()
    if success:
        print("✓ TigerGraph initialized successfully")
        sys.exit(0)
    else:
        print("✗ TigerGraph initialization failed")
        sys.exit(1)
