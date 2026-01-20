"""
TigerGraph Client Utility
Handles connection and operations with TigerGraph database
"""
import logging
from pyTigerGraph import TigerGraphConnection
from config.settings import Config
from utils.logging_config import setup_logging

tigergraph_logger = setup_logging('tigergraph_client.log')


class TigerGraphClient:
    """Singleton client for TigerGraph operations"""
    
    _instance = None
    _connection = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(TigerGraphClient, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        if self._connection is None:
            self._connect()
    
    def _connect(self):
        """Establish connection to TigerGraph"""
        try:
            self._connection = TigerGraphConnection(
                host=Config.TIGERGRAPH_HOST,
                graphname=Config.TIGERGRAPH_GRAPH_NAME,
                username=Config.TIGERGRAPH_USERNAME,
                password=Config.TIGERGRAPH_PASSWORD,
                restppPort=Config.TIGERGRAPH_PORT,
                gsPort="14240"
            )
            tigergraph_logger.info(f"Connected to TigerGraph at {Config.TIGERGRAPH_HOST}")
        except Exception as e:
            tigergraph_logger.error(f"Failed to connect to TigerGraph: {e}")
            raise
    
    def get_connection(self):
        """Get the TigerGraph connection"""
        if self._connection is None:
            self._connect()
        return self._connection
    
    def execute_query(self, query_name, params=None):
        """Execute a named query"""
        try:
            result = self._connection.runInstalledQuery(query_name, params=params or {})
            return result
        except Exception as e:
            tigergraph_logger.error(f"Error executing query {query_name}: {e}")
            raise
    
    def upsert_vertex(self, vertex_type, vertex_id, attributes):
        """Upsert a single vertex"""
        try:
            result = self._connection.upsertVertex(vertex_type, vertex_id, attributes)
            return result
        except Exception as e:
            tigergraph_logger.error(f"Error upserting vertex {vertex_type}:{vertex_id}: {e}")
            raise
    
    def upsert_edge(self, source_type, source_id, edge_type, target_type, target_id, attributes=None):
        """Upsert a single edge"""
        try:
            result = self._connection.upsertEdge(
                source_type, source_id, edge_type, target_type, target_id, attributes or {}
            )
            return result
        except Exception as e:
            tigergraph_logger.error(f"Error upserting edge {edge_type}: {e}")
            raise
    
    def upsert_vertices_bulk(self, vertex_type, vertices):
        """Bulk upsert vertices
        
        Args:
            vertex_type: Type of vertex
            vertices: List of (vertex_id, attributes) tuples
        """
        try:
            result = self._connection.upsertVertices(vertex_type, vertices)
            tigergraph_logger.info(f"Bulk upserted {len(vertices)} vertices of type {vertex_type}")
            return result
        except Exception as e:
            tigergraph_logger.error(f"Error bulk upserting vertices: {e}")
            raise
    
    def upsert_edges_bulk(self, source_type, edge_type, target_type, edges):
        """Bulk upsert edges
        
        Args:
            source_type: Source vertex type
            edge_type: Edge type
            target_type: Target vertex type
            edges: List of (source_id, target_id, attributes) tuples
        """
        try:
            result = self._connection.upsertEdges(source_type, edge_type, target_type, edges)
            tigergraph_logger.info(f"Bulk upserted {len(edges)} edges of type {edge_type}")
            return result
        except Exception as e:
            tigergraph_logger.error(f"Error bulk upserting edges: {e}")
            raise


# Global instance - Only create when TigerGraph is enabled
# Initialized lazily to avoid connection errors when TigerGraph is disabled
tg_client = None

def get_tg_client():
    """Get or create TigerGraph client instance"""
    global tg_client
    if tg_client is None:
        tg_client = TigerGraphClient()
    return tg_client
