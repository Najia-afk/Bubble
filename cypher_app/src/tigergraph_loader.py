"""
TigerGraph Data Loader
Syncs data from PostgreSQL to TigerGraph
"""
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Set
from sqlalchemy import text

from cypher_app.utils.tigergraph_client import get_tg_client
from utils.database import get_session_factory
from utils.logging_config import setup_logging
from api.application.erc20models import Token, TokenPriceHistory, WalletLabel, KnownBridge, CHAIN_ID_TO_TRIGRAM, TRIGRAM_TO_CHAIN_ID

logger = setup_logging('tigergraph_loader.log')


class TigerGraphLoader:
    """Loads data from PostgreSQL into TigerGraph"""
    
    def __init__(self):
        self.tg = get_tg_client()
        self.session_factory = get_session_factory()
    
    def load_tokens(self, session=None):
        """Load tokens from PostgreSQL to TigerGraph"""
        close_session = False
        if session is None:
            session = self.session_factory()
            close_session = True
        
        try:
            tokens = session.query(Token).all()
            logger.info(f"Loading {len(tokens)} tokens into TigerGraph...")
            
            # Prepare vertices
            token_vertices = []
            chain_vertices = {}
            exists_on_edges = []
            
            for token in tokens:
                # Token vertex
                token_vertices.append((
                    token.contract_address,
                    {
                        'symbol': token.symbol,
                        'name': token.name,
                        'coingecko_id': token.id or '',
                        'first_tracked': datetime.now()
                    }
                ))
                
                # Chain vertex (collect unique chains)
                if token.trigram not in chain_vertices:
                    chain_vertices[token.trigram] = {
                        'name': token.trigram.upper(),
                        'asset_platform_id': token.asset_platform_id,
                        'scanner_url': self._get_scanner_url(token.trigram),
                        'block_time': self._get_block_time(token.trigram)
                    }
                
                # ExistsOn edge
                exists_on_edges.append((
                    token.contract_address,
                    token.trigram,
                    {
                        'deployed_at': datetime.now(),
                        'contract_address': token.contract_address
                    }
                ))
            
            # Bulk upsert tokens
            if token_vertices:
                self.tg.upsert_vertices_bulk('Token', token_vertices)
                logger.info(f"✓ Loaded {len(token_vertices)} tokens")
            
            # Bulk upsert chains
            chain_list = [(k, v) for k, v in chain_vertices.items()]
            if chain_list:
                self.tg.upsert_vertices_bulk('Chain', chain_list)
                logger.info(f"✓ Loaded {len(chain_list)} chains")
            
            # Bulk upsert ExistsOn edges
            if exists_on_edges:
                edges_formatted = [(e[0], e[1], e[2]) for e in exists_on_edges]
                self.tg.upsert_edges_bulk('Token', 'ExistsOn', 'Chain', edges_formatted)
                logger.info(f"✓ Loaded {len(exists_on_edges)} ExistsOn edges")
            
            return True
            
        except Exception as e:
            logger.error(f"Error loading tokens: {e}")
            return False
        finally:
            if close_session:
                session.close()
    
    def load_transfers_24h(self, token_symbol: str, chain_trigram: str, session=None):
        """Load ERC20 transfer events from last 24h for a specific token"""
        close_session = False
        if session is None:
            session = self.session_factory()
            close_session = True
        
        try:
            # Get the token
            token = session.query(Token).filter(
                Token.symbol == token_symbol.upper(),
                Token.trigram == chain_trigram.upper()
            ).first()
            
            if not token:
                logger.error(f"Token {token_symbol} not found on {chain_trigram}")
                return False
            
            # Build dynamic table name
            table_name = f"{token_symbol.lower()}_{chain_trigram.lower()}_erc20_transfer_event"
            
            # Query last 24h of transfers
            cutoff_time = datetime.now() - timedelta(hours=24)
            
            query = text(f"""
                SELECT 
                    e.hash as tx_hash,
                    e.from_contract_address,
                    e.to_contract_address,
                    e.value,
                    b.timestamp,
                    b.block_number,
                    b.block_hash
                FROM {table_name} e
                JOIN {chain_trigram.lower()}_block_transfer_event b ON e.block_event_hash = b.hash
                WHERE b.timestamp >= :cutoff_time
                ORDER BY b.timestamp DESC
                LIMIT 10000
            """)
            
            result = session.execute(query, {'cutoff_time': cutoff_time})
            transfers = result.fetchall()
            
            if not transfers:
                logger.info(f"No transfers found for {token_symbol} on {chain_trigram} in last 24h")
                return True
            
            logger.info(f"Processing {len(transfers)} transfers for {token_symbol}...")
            
            # Collect unique wallets and prepare data
            wallets = set()
            wallet_vertices = []
            transfer_edges = []
            bridge_edges = []
            
            # Load labels and bridges from PostgreSQL
            chain_id = TRIGRAM_TO_CHAIN_ID.get(chain_trigram.upper(), 1)
            wallet_labels_map = self._load_wallet_labels(session, chain_id)
            known_bridges = self._load_known_bridges(session, chain_id)
            
            logger.info(f"Loaded {len(wallet_labels_map)} wallet labels and {len(known_bridges)} known bridges")
            
            for transfer in transfers:
                from_addr = transfer.from_contract_address
                to_addr = transfer.to_contract_address
                
                wallets.add(from_addr)
                wallets.add(to_addr)
                
                # Transfer edge
                transfer_edges.append((
                    from_addr,
                    to_addr,
                    {
                        'token_address': token.contract_address,
                        'amount': float(transfer.value),
                        'amount_usd': 0.0,  # TODO: Calculate USD value
                        'tx_hash': transfer.tx_hash,
                        'block_number': int(transfer.block_number),
                        'timestamp': transfer.timestamp,
                        'chain_trigram': chain_trigram.upper()
                    }
                ))
                
                # Check if this is a bridge transaction
                from_is_bridge = from_addr.lower() in known_bridges
                to_is_bridge = to_addr.lower() in known_bridges
                
                if from_is_bridge or to_is_bridge:
                    bridge_addr = from_addr.lower() if from_is_bridge else to_addr.lower()
                    bridge_info = known_bridges.get(bridge_addr, {})
                    
                    bridge_edges.append({
                        'from_wallet': from_addr,
                        'to_wallet': to_addr,
                        'bridge_address': bridge_addr,
                        'protocol': bridge_info.get('protocol', 'unknown'),
                        'direction': bridge_info.get('direction', 'unknown'),
                        'tx_hash': transfer.tx_hash,
                        'amount': float(transfer.value),
                        'timestamp': transfer.timestamp,
                        'chain_trigram': chain_trigram.upper()
                    })
            
            # Create wallet vertices with labels
            for addr in wallets:
                addr_lower = addr.lower()
                labels = wallet_labels_map.get(addr_lower, [])
                is_bridge = addr_lower in known_bridges
                
                wallet_vertices.append((
                    addr,
                    {
                        'first_seen': datetime.now(),
                        'last_seen': datetime.now(),
                        'total_transactions': 0,
                        'total_volume_usd': 0.0,
                        'is_contract': is_bridge,  # Bridges are contracts
                        'labels': labels
                    }
                ))
            
            # Bulk load wallets
            if wallet_vertices:
                self.tg.upsert_vertices_bulk('Wallet', wallet_vertices)
                logger.info(f"✓ Loaded {len(wallet_vertices)} wallets")
            
            # Bulk load transfers
            if transfer_edges:
                self.tg.upsert_edges_bulk('Wallet', 'Transfer', 'Wallet', transfer_edges)
                logger.info(f"✓ Loaded {len(transfer_edges)} transfers")
            
            # Log bridge transactions detected
            if bridge_edges:
                logger.info(f"✓ Detected {len(bridge_edges)} bridge transactions")
                # TODO: Create Bridge edges in TigerGraph when schema supports it
                # self.tg.upsert_edges_bulk('Wallet', 'Bridge', 'Wallet', bridge_edges)
            
            return True
            
        except Exception as e:
            logger.error(f"Error loading transfers: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
        finally:
            if close_session:
                session.close()
    
    def _get_scanner_url(self, trigram: str) -> str:
        """Get blockchain scanner URL for trigram"""
        urls = {
            'ETH': 'https://api.etherscan.io/api',
            'BSC': 'https://api.bscscan.com/api',
            'POL': 'https://api.polygonscan.com/api',
            'BASE': 'https://api.basescan.org/api'
        }
        return urls.get(trigram.upper(), '')
    
    def _get_block_time(self, trigram: str) -> float:
        """Get average block time for chain"""
        times = {
            'ETH': 12.0,
            'BSC': 3.0,
            'POL': 2.0,
            'BASE': 2.0
        }
        return times.get(trigram.upper(), 10.0)
    
    def _load_wallet_labels(self, session, chain_id: int) -> Dict[str, List[str]]:
        """Load wallet labels from PostgreSQL for a specific chain"""
        try:
            labels = session.query(WalletLabel).filter(
                WalletLabel.chain_id == chain_id
            ).all()
            
            # Group labels by address
            labels_map = {}
            for label in labels:
                addr = label.address.lower()
                if addr not in labels_map:
                    labels_map[addr] = []
                
                # Build label string with type if available
                label_str = label.label
                if label.label_type:
                    label_str = f"{label.label_type}:{label.label}"
                if label.is_trusted:
                    label_str += ":trusted"
                
                labels_map[addr].append(label_str)
            
            return labels_map
            
        except Exception as e:
            logger.warning(f"Could not load wallet labels: {e}")
            return {}
    
    def _load_known_bridges(self, session, chain_id: int) -> Dict[str, Dict]:
        """Load known bridge addresses from PostgreSQL for a specific chain"""
        try:
            bridges = session.query(KnownBridge).filter(
                KnownBridge.chain_id == chain_id,
                KnownBridge.is_active == True
            ).all()
            
            bridges_map = {}
            for bridge in bridges:
                bridges_map[bridge.address.lower()] = {
                    'protocol': bridge.protocol,
                    'direction': bridge.direction,
                    'name': bridge.name
                }
            
            return bridges_map
            
        except Exception as e:
            logger.warning(f"Could not load known bridges: {e}")
            return {}
    
    def get_wallet_labels(self, address: str, chain_trigram: str = None) -> List[Dict]:
        """Get labels for a wallet address from PostgreSQL"""
        session = self.session_factory()
        try:
            query = session.query(WalletLabel).filter(
                WalletLabel.address == address.lower()
            )
            
            if chain_trigram:
                chain_id = TRIGRAM_TO_CHAIN_ID.get(chain_trigram.upper())
                if chain_id:
                    query = query.filter(WalletLabel.chain_id == chain_id)
            
            labels = query.all()
            
            return [
                {
                    'label': label.label,
                    'label_type': label.label_type,
                    'name_tag': label.name_tag,
                    'source': label.source,
                    'is_trusted': label.is_trusted,
                    'chain': CHAIN_ID_TO_TRIGRAM.get(label.chain_id, 'UNKNOWN')
                }
                for label in labels
            ]
        finally:
            session.close()


# Global instance - Only create when TigerGraph is enabled
# Initialized lazily to avoid connection errors when TigerGraph is disabled
tg_loader = None

def get_tg_loader():
    """Get or create TigerGraph loader instance"""
    global tg_loader
    if tg_loader is None:
        tg_loader = TigerGraphLoader()
    return tg_loader
