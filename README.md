# Bubble - Blockchain Analytics Platform

[![Python](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/Docker-24.0+-blue.svg)](https://www.docker.com/)
[![Flask](https://img.shields.io/badge/Flask-3.1-green.svg)](https://flask.palletsprojects.com/)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0-red.svg)](https://www.sqlalchemy.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15-blue.svg)](https://www.postgresql.org/)
[![Celery](https://img.shields.io/badge/Celery-5.6-green.svg)](https://docs.celeryq.dev/)
[![Tests](https://img.shields.io/badge/tests-22%20passing-brightgreen.svg)](#testing)

Production-grade blockchain analytics platform for tracking ERC-20 token transactions across multiple networks with automated data pipelines and graph visualization powered by TigerGraph.

## 🎯 Features

Track **any ERC-20 token** across multiple blockchains:
- 🔷 **Ethereum** (ETH)
- 🟡 **Binance Smart Chain** (BSC)
- 🟣 **Polygon** (POL)
- 🔵 **Base** (BASE)

### Core Capabilities:
- 🤖 **Fully Automated Workflow**: Add token → Auto-create tables → Fetch data → Sync to graph DB
- 📊 Real-time transaction monitoring with customizable date ranges
- 🕸️ Interactive graph visualization of transaction flows
- 🔍 Cluster detection for wallet analysis
- ⚡ Async batch processing with Celery (4 workers)
- 💾 PostgreSQL for relational data + TigerGraph for graph analytics
- 🎛️ Web-based admin interface for token management
- 📈 Price history tracking from CoinGecko API
- 🔄 Dynamic table generation per token/blockchain
- 🧪 Comprehensive test suite (22 tests, 100% passing)

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Nginx (Port 8080)                         │
│                Static Files + Reverse Proxy                  │
└────────────────┬────────────────────────────────────────────┘
                 │
┌────────────────┴────────────────────────────────────────────┐
│             Flask Web App (Port 5000)                        │
│  • REST API endpoints (Token CRUD, Data Fetch)               │
│  • GraphQL API (Token queries, Price history)                │
│  • Dashboard UI                                              │
│  • Admin Interface (Token Management)                        │
└────┬────────────────────┬──────────────────────┬────────────┘
     │                    │                      │
┌────┴─────┐    ┌─────────┴──────┐    ┌─────────┴──────────┐
│PostgreSQL│    │     Redis       │    │   TigerGraph       │
│  Port    │    │   Port 6379     │    │   Port 9000        │
│  5432    │    │  Message Broker │    │  Graph Database    │
│          │    │  Result Backend │    │  (Optional)        │
└────┬─────┘    └─────────┬───────┘    └────────────────────┘
     │                    │
     │          ┌─────────┴──────────┐
     │          │  Celery Workers     │
     │          │  • Blockchain fetch │
     └──────────┤  • TigerGraph sync  │
                │  • 4 concurrent     │
                └────────────────────┘
```

### Data Flow (Fully Automated):

```
1. User adds token via API/UI
   ↓
2. System auto-creates dynamic tables:
   - {symbol}_{trigram}_erc20_transfer_event
   - {trigram}_block_transfer_event
   ↓
3. User schedules data fetch
   ↓
4. Celery worker fetches from blockchain APIs
   ↓
5. Data stored in PostgreSQL (SQLAlchemy 2.0)
   ↓
6. Celery syncs to TigerGraph (graph relationships)
   ↓
7. GraphQL/REST API serves data to UI
```

---

## 🚀 Quick Start

### Installation

1. **Run the initialization script:**
```bash
chmod +x init_poc.sh
./init_poc.sh
```

This script will:
- ✅ Build Docker images (Python 3.12-slim base)
- ✅ Start all services (PostgreSQL, Redis, Flask, Celery, Nginx)
- ✅ Create base database schema
- ✅ Run pytest suite (19 tests)
- ✅ Launch web interface on port 8080

3. **Access the platform:**
- 🏠 **Dashboard**: http://localhost:8080
- 📈 **Visualizations**: http://localhost:8080/visualize
- ⚙️ **Admin Panel**: http://localhost:8080/admin
- 🔌 **API Docs**: http://localhost:8080/api/health
- 🌐 **GraphQL**: http://localhost:8080/graphql

4. **Test with GHST token (Aavegotchi):**
```bash
# Add token
curl -X POST http://localhost:8080/api/tokens/add \
  -H "Content-Type: application/json" \
  -d '{
    "contract_address": "0x385Eeac5cB85A38A9a07A70c73e0a3271CfB54A7",
    "blockchain": "polygon-pos",
    "trigram": "POL"
  }'

# Schedule data fetch (2 days)
curl -X POST http://localhost:8080/api/tokens/schedule_fetch \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "GHST",
    "chains": ["POL"],
    "start_date": "2026-01-19",
    "end_date": "2026-01-20"
  }'

# Check task progress
docker compose logs -f celery
```

---

## 🎯 Usage Workflow

### 1. Add a Token (Automated)

**Via API:**
```bash
curl -X POST http://localhost:8080/api/tokens/add \
  -H "Content-Type: application/json" \
  -d '{
    "contract_address": "0x...",
    "blockchain": "polygon-pos",
    "trigram": "POL"
  }'
```

The system automatically:
- ✅ Fetches token metadata from CoinGecko (symbol, name, decimals)
- ✅ Creates dynamic database tables:
  - `{symbol}_{trigram}_erc20_transfer_event`
  - `{trigram}_block_transfer_event`
- ✅ Sets up indexes and constraints
- ✅ Establishes foreign key relationships

**Via Admin UI** (`/admin`):
- Enter contract address
- Select blockchain(s)
- Click "Add Token"

### 2. Schedule Data Fetch

```bash
curl -X POST http://localhost:8080/api/tokens/schedule_fetch \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "GHST",
    "chains": ["POL", "BASE"],
    "start_date": "2026-01-01",
    "end_date": "2026-01-20",
    "fetch_mode": "both"
  }'
```

**fetch_mode options:**
- `"price_history"` - Only fetch price/volume data from CoinGecko
- `"transfers"` - Only fetch ERC-20 transfer events from blockchain scanners
- `"both"` - Fetch everything (default)

### 3. Monitor Data Collection

```bash
# Watch Celery worker logs
docker compose logs -f celery

# Check active tasks
curl http://localhost:8080/api/tasks/active

# List tokens
curl http://localhost:8080/api/tokens/list
```

### 4. Visualize & Query Data

- Navigate to `/visualize` to see transaction flow graphs
- Interactive visualization powered by vis.js and TigerGraph
- Cluster detection to identify related wallets
- 24-hour rolling window for recent activity

---
## 🛠️ Technology Stack

### Backend
- **Python 3.12-slim** (Debian-based, production standard from mission7)
- **Flask 3.1** - Web framework
- **SQLAlchemy 2.0** - ORM with modern async support
- **Celery 5.6** - Distributed task queue (4 workers, prefork pool)
- **Redis 7** - Message broker & result backend
- **PostgreSQL 15** - Primary database
- **Gunicorn** - WSGI HTTP server

### GraphQL & API
- **graphene 3.4** - GraphQL framework
- **graphene-sqlalchemy 3.0.0rc2** - SQLAlchemy integration
- **Flask-CORS** - CORS handling

### Graph Database (Optional)
- **TigerGraph** - Graph analytics & visualization
- Custom loader for PostgreSQL → TigerGraph sync

### Frontend
- **Vanilla JavaScript** - No framework overhead
- **vis.js** - Network graph visualization
- **Chart.js** - Time series charts
- **Bootstrap 5** - Responsive UI

### DevOps
- **Docker & Docker Compose** - Containerization
- **Nginx** - Reverse proxy & static file serving
- **pytest 9.0** - Testing framework
- **Multi-stage Docker builds** - Optimized image sizes

### External APIs
- **CoinGecko API** - Token metadata & price history
- **Polygonscan API** - Polygon blockchain data
- **Basescan API** - Base blockchain data
- **Etherscan API** - Ethereum blockchain data
- **BSCScan API** - BSC blockchain data

---
## 📂 Project Structure

```
Bubble/
├── app.py                      # Flask application entry point
├── wsgi.py                     # Gunicorn WSGI server
├── celery_worker.py            # Celery worker configuration
├── docker-compose.yml          # Docker orchestration
├── init_poc.sh                 # POC initialization script
│
├── docker/                     # Docker configurations
│   ├── Dockerfile.web          # Web application image
│   ├── Dockerfile.celery       # Celery worker image
│   └── nginx.conf              # Nginx reverse proxy config
│
├── api/                        # API layer
│   ├── routes.py               # REST endpoints
│   ├── application/            # Data models
│   │   └── erc20models.py      # SQLAlchemy models (dynamic)
│   ├── services/               # Business logic services
│   └── tasks/                  # Celery tasks
│       ├── tasks.py            # Original tasks
│       └── tigergraph_tasks.py # TigerGraph sync tasks
│
├── cypher_app/                 # TigerGraph integration
│   ├── src/
│   │   └── tigergraph_loader.py    # Data loader
│   ├── scripts/
│   │   ├── schema.gsql             # TigerGraph schema
│   │   └── init_schema.py          # Schema initialization
│   └── utils/
│       └── tigergraph_client.py    # TigerGraph client wrapper
│
├── graphql_app/                # GraphQL layer
│   ├── schemas/                # GraphQL schemas
│   ├── types/                  # GraphQL types
│   └── utils/                  # GraphQL utilities
│
├── scripts/                    # Data fetching scripts
│   └── src/
│       ├── fetch_erc20_info_coingecko.py       # Token info fetcher
│       ├── fetch_erc20_price_history_coingecko.py  # Price history
│       └── fetch_scan_token_erc20_transfert.py # Transfer events
│
├── templates/                  # HTML templates
│   ├── dashboard.html          # Main dashboard
│   ├── admin/                  # Admin interface
│   └── visualizations/         # Graph visualizations
│       └── transaction_flow.html
│
├── static/                     # Static assets
│   ├── css/
│   │   └── dashboard.css       # Styles
│   └── js/
│       ├── dashboard.js        # Dashboard logic
│       └── visualization.js    # Graph visualization
│
├── config/                     # Configuration
│   ├── settings.py             # Environment-based config
│   └── requirements.txt        # Python dependencies
│
└── utils/                      # Utilities
    ├── database.py             # Database connections
    └── logging_config.py       # Logging setup
```

---

## 🎮 API Usage

### Token Management

#### Add New Token
```bash
POST /api/tokens/add
Content-Type: application/json

{
  "contract_address": "0x385Eeac5cB85A38A9a07A70c73e0a3271CfB54A7",
  "blockchain": "polygon"
}
```

#### List Tokens
```bash
GET /api/tokens/list
```

#### Schedule Token Data Fetch
```bash
POST /api/tokens/schedule_fetch
Content-Type: application/json

{
  "symbol": "GHST",
  "chains": ["POL", "BASE"],
  "start_date": "2024-01-01",
  "end_date": "2024-12-31",
  "fetch_mode": "both"  # Options: "both", "price_only", "transfers_only"
}
```

### Token Price History
```bash
GET /api/get_token_price_history?symbols=ghst&startDate=2024-01-01&endDate=2024-01-31
```

### GraphQL Queries

```graphql
query GetTransferHistory {
  transferHistory(symbol: "GHST", chain: "POL", limit: 100) {
    from
    to
    value
    blockNumber
    timestamp
  }
}
```

---

## 🎨 Dashboard Features

### Main Dashboard (`/`)

The main dashboard displays:
- 📊 Transaction statistics per token/chain
- 💰 Total volume moved
- 🔗 Active wallets count
- 🌐 Network status

### Admin Interface (`/admin`)

Token management panel with:
- ➕ Add new tokens by contract address
- 🌐 Select multiple blockchains (multi-chain tracking)
- 📅 Set date ranges for historical data
- ⏱️ Schedule and monitor fetch tasks
- 📋 View all tracked tokens

### Transaction Flow Visualization (`/visualize`)

Interactive network graph showing:
- **Nodes**: Wallet addresses (colored by type)
  - 🔵 Regular wallets
  - 🔴 High-volume wallets
  - 🟢 Contracts/Exchanges
  - 🟡 Bridge contracts
  
- **Edges**: Token transfers (thickness = volume)

**Controls:**
- Filter by chain (Polygon, Base, ETH, BSC, or All)
- Filter by token
- Time window (1h, 6h, 12h, 24h)
- Minimum transaction value
- Cluster detection
- Export graph data (JSON)

---

---

## 🧪 Testing

Comprehensive test suite with 22 tests covering:
- ✅ Environment verification (Python 3.12, SQLAlchemy 2.0, graphene 3.x)
- ✅ Database models (Token, TokenPriceHistory, dynamic tables)
- ✅ API endpoints (health checks, token CRUD, data fetching)
- ✅ GHST production validation (complete dataflow)
- ✅ TigerGraph sync endpoints
- ✅ Error handling (404, 405, 500)

**Status: 22/22 tests passing (100%)**

### Run Tests

```bash
# Run all tests
docker compose exec web pytest

# Run with coverage
docker compose exec web pytest --cov=. --cov-report=html

# Run specific markers
docker compose exec web pytest -m ghst        # GHST production tests
docker compose exec web pytest -m unit        # Unit tests only
docker compose exec web pytest -m integration # Integration tests
docker compose exec web pytest -m api         # API endpoint tests
docker compose exec web pytest -m slow        # Long-running tests

# Verbose output
docker compose exec web pytest -v

# Stop on first failure
docker compose exec web pytest -x
```

### Test Structure

```
tests/
├── pytest.ini                    # Pytest configuration
├── test_environment.py           # Environment checks (Python, SQLAlchemy versions)
├── test_database_models.py       # Database model tests
└── test_api_endpoints.py         # API endpoint tests + GHST dataflow
```

### GHST Production Test

The `test_ghst_complete_dataflow` test validates the entire pipeline:
1. Add GHST token via API
2. Verify dynamic table creation
3. Schedule blockchain data fetch
4. Confirm Celery task execution
5. Validate data in PostgreSQL

```bash
# Run GHST validation
docker compose exec web pytest -m ghst -v
```

---

## 🔧 Development

### Manual Commands

**Start services:**
```bash
docker-compose up -d
```

**View logs:**
```bash
docker-compose logs -f web      # Flask app
docker-compose logs -f celery   # Celery worker
docker-compose logs -f nginx    # Nginx
docker-compose logs -f tigergraph  # TigerGraph
```

**Execute commands in containers:**
```bash
# Access Flask shell
docker-compose exec web python

# Run migration/setup scripts
docker-compose exec web python scripts/src/fetch_erc20_info_coingecko.py

# Initialize TigerGraph schema
docker-compose exec web python cypher_app/scripts/init_schema.py

# Manual Celery task testing
docker-compose exec celery celery -A celery_worker.celery_app inspect active
```

**Restart services:**
```bash
docker-compose restart web      # Restart Flask
docker-compose restart celery   # Restart worker
```

**Stop services:**
```bash
docker-compose down             # Stop all
docker-compose down -v          # Stop all + remove volumes (DELETES DATA)
```

**Database access:**
```bash
docker-compose exec postgres psql -U bubbleuser -d bubbledb
```

---

## 📊 Data Flow

### 1. Token Setup (via Admin UI)
```
User Input → Flask API → CoinGecko API → PostgreSQL → Dynamic Tables Created
```

### 2. Transfer Fetching (Rate Limited)
```
Polygonscan/Basescan API → Celery Task → PostgreSQL (bulk insert)
```

### 3. TigerGraph Sync (Async)
```
PostgreSQL → Celery Task → TigerGraph (vertices + edges)
```

### 4. Visualization
```
User → Flask → TigerGraph Query → Graph Data → vis.js
```

---

## 🐛 Troubleshooting

### Services Not Starting

**Check service status:**
```bash
docker-compose ps
```

**View service logs:**
```bash
docker-compose logs web
docker-compose logs celery
docker-compose logs postgres
docker-compose logs tigergraph
```

### Docker Issues

**Restart Docker Desktop:**
```bash
docker system prune -a  # Clean up unused images/containers
docker-compose down
docker-compose up -d --build
```

### TigerGraph Not Starting

```bash
# TigerGraph requires 8GB+ RAM
# Increase Docker Desktop memory allocation in settings

# Check TigerGraph logs
docker-compose logs tigergraph

# Restart TigerGraph
docker-compose restart tigergraph
```

### Database Connection Errors

```bash
# Check PostgreSQL status
docker-compose exec postgres pg_isready -U bubbleuser

# Check database exists
docker-compose exec postgres psql -U bubbleuser -l

# Reset database (DELETES ALL DATA)
docker-compose down -v
docker-compose up -d
```

### Celery Tasks Not Running

```bash
# Check Celery worker status
docker-compose logs celery

# Check Redis connection
docker-compose exec redis redis-cli ping

# Inspect active/scheduled tasks
docker-compose exec celery celery -A celery_worker.celery_app inspect active
docker-compose exec celery celery -A celery_worker.celery_app inspect scheduled
```

### API Rate Limit Errors

The system respects API rate limits automatically:
- **CoinGecko**: 50 calls/minute (free tier)
- **Etherscan/Polygonscan/Basescan/BSCscan**: 5 calls/second (free tier)

If you see rate limit errors, tasks will retry automatically with exponential backoff.

### Web Interface Not Loading

```bash
# Check Nginx status
docker-compose logs nginx

# Verify Flask is running
curl http://localhost:5000/health

# Check port conflicts
lsof -i :8080
```

---

## 📝 Notes

### Example Token Addresses

**GHST (Aavegotchi):**
- **Polygon**: `0x385eeac5cb85a38a9a07a70c73e0a3271cfb54a7`
- **Base**: `0x7645DD9B4d01D4A0C321e8399070c6AC90deBff0`

**USDT (Tether):**
- **Ethereum**: `0xdac17f958d2ee523a2206206994597c13d831ec7`
- **BSC**: `0x55d398326f99059ff775485246999027b3197955`
- **Polygon**: `0xc2132d05d31c914a87c6611c10748aeb04b58e8f`

### Dynamic Table Generation

The system automatically creates tables per token and blockchain:
- Format: `{symbol}_{trigram}_token_erc20_transfer_event`
- Example: `ghst_pol_token_erc20_transfer_event`

This allows tracking multiple tokens across multiple chains independently.

---

## 🔐 Security Notes

- **Never commit `.env` file** (already in .gitignore)
- API keys in `.env.example` are for demonstration only
- Replace with your own API keys from:
  - [CoinGecko](https://www.coingecko.com/en/api)
  - [Etherscan](https://etherscan.io/apis)
  - [BSCScan](https://bscscan.com/apis)
  - [PolygonScan](https://polygonscan.com/apis)
  - [BaseScan](https://basescan.org/apis)

---

**Built with:** Python 3.12, Flask, Celery, PostgreSQL, Redis, TigerGraph, Docker, vis.js

**License:** MIT

**Last Updated:** January 2026

**License:** MIT

**Last Updated:** January 2025
