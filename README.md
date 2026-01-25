# Bubble - Blockchain Investigation & Analytics Platform

[![Python](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/Docker-24.0+-blue.svg)](https://www.docker.com/)
[![Flask](https://img.shields.io/badge/Flask-3.1-green.svg)](https://flask.palletsprojects.com/)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0-red.svg)](https://www.sqlalchemy.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15-blue.svg)](https://www.postgresql.org/)
[![Celery](https://img.shields.io/badge/Celery-5.6-green.svg)](https://docs.celeryq.dev/)
[![Tests](https://img.shields.io/badge/tests-22%20passing-brightgreen.svg)](#testing)
[![License](https://img.shields.io/badge/license-Source%20Available-orange.svg)](#license)

Production-grade blockchain investigation platform for tracking illicit fund flows, managing crypto fraud cases, and monitoring suspicious wallets across multiple EVM networks.

## ✨ Key Features

### 🔍 Investigation Management
- **Case Tracking**: Create and manage fraud investigations with status workflows
- **Multi-chain Support**: Ethereum, BSC, Polygon, Base with unified interface
- **Wallet Classification**: Automatic categorization (victims, suspects, exchanges, bridges, mixers)
- **Estimated Loss Calculation**: Real-time USD valuation from on-chain transfers + token prices

### 📊 Visualization & Analysis
- **Interactive Graph Explorer**: Transaction flow visualization powered by vis.js
- **Full-page Graph View**: Dedicated investigation graphs with filtering controls
- **Sankey Diagrams**: Fund flow visualization between wallet categories
- **Dynamic Filters**: Filter by minimum value, chain, token type

### 🔔 Real-time Monitoring
- **Suspect Wallet Tracking**: Auto-populate from investigation attacker wallets
- **Activity Alerts**: Detect mixer deposits, bridge transfers, large movements
- **Last Activity Tracking**: Monitor when suspects last moved funds and destinations
- **Risk Scoring**: Automated risk assessment for transactions

### 🛠️ Developer Tools
- **REST API**: Comprehensive endpoints for all operations
- **GraphQL API**: Flexible queries with GraphiQL explorer
- **Swagger Documentation**: Interactive API documentation at `/api/docs/`
- **Async Processing**: Celery workers for distributed task execution

---

## 📁 Project Structure

```
Bubble/
├── app.py                      # Flask application factory
├── wsgi.py                     # Gunicorn WSGI entry point
├── celery_worker.py            # Celery worker configuration
├── docker-compose.yml          # Development stack
├── docker-compose.prod.yml     # Production stack
│
├── api/                        # API layer
│   ├── routes.py               # REST endpoints
│   ├── application/            # SQLAlchemy models
│   │   ├── models.py           # Core models (Chain, Case, Alert)
│   │   └── erc20models.py      # Investigation & transfer models
│   ├── services/               # Business logic
│   │   ├── data_access.py      # Database access layer
│   │   ├── wallet_monitor.py   # Real-time monitoring service
│   │   └── ml_trainer.py       # ML model training
│   └── tasks/                  # Celery tasks
│       ├── investigation_tasks.py
│       └── monitor_tasks.py
│
├── config/                     # Configuration
│   ├── settings.py             # App configuration
│   ├── requirements.txt        # Python dependencies
│   └── data/                   # Reference data (chains, mixers, bridges)
│
├── templates/                  # HTML templates
│   ├── dashboard.html          # Main dashboard with case stats
│   ├── cases.html              # Case & investigation management
│   ├── monitor.html            # Real-time wallet monitoring
│   └── visualizations/         # Graph visualization templates
│
├── scripts/                    # Utility scripts
│   ├── init_db.py              # Database initialization
│   └── cleanup_docker.ps1      # Docker cleanup utility
│
├── tests/                      # Pytest test suite
└── docs/                       # Documentation
```

---

## 🚀 Quick Start

### Prerequisites
- Docker & Docker Compose
- API keys (see [Configuration](#configuration))

### Development Mode
```bash
docker compose up -d --build
```

### Access Points

| Service | URL | Description |
|---------|-----|-------------|
| Dashboard | http://localhost:8080 | Main dashboard with case statistics |
| Cases | http://localhost:8080/cases | Case & investigation management |
| Monitor | http://localhost:8080/monitor | Real-time wallet monitoring |
| Graph View | http://localhost:8080/graph?investigation_id=X | Full-page investigation graph |
| API Docs | http://localhost:8080/api/docs/ | Swagger documentation |
| GraphQL | http://localhost:8080/graphql | GraphiQL explorer |
| Admin | http://localhost:8080/admin | Token management panel |

### Production Mode
```bash
docker compose -f docker-compose.prod.yml up -d --build
```

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
│  • REST API    • GraphQL API    • Dashboard UI               │
└────┬────────────────────┬──────────────────────┬────────────┘
     │                    │                      │
┌────┴─────┐    ┌─────────┴──────┐    ┌─────────┴──────────┐
│PostgreSQL│    │     Redis       │    │   TigerGraph       │
│  5432    │    │     6379        │    │   9000 (optional)  │
└────┬─────┘    └─────────┬───────┘    └────────────────────┘
     │          ┌─────────┴──────────┐
     └──────────┤  Celery Workers     │
                │  (4 concurrent)     │
                └────────────────────┘
```

---

## ⚙️ Configuration

### Environment Variables

Create a `.env` file at the project root:

```env
# Database
POSTGRES_DB=bubble_db
POSTGRES_USER=bubble_user
POSTGRES_PASSWORD=your_secure_password

# Flask
FLASK_ENV=development
SECRET_KEY=your_secret_key

# API Keys (required for blockchain data)
COINGECKO_API_KEY=your_key
ETHERSCAN_API_KEY=your_key
BSCSCAN_API_KEY=your_key
POLYGONSCAN_API_KEY=your_key
BASESCAN_API_KEY=your_key
```

### Database Initialization

On first run, seed the reference data:
```bash
docker compose exec web python -c "from scripts.init_db import DatabaseInitializer; DatabaseInitializer().init_all()"
```

---

## 🔌 API Endpoints

### Cases & Investigations
```bash
# List all cases
curl http://localhost:8080/api/cases

# Get case details with investigations
curl http://localhost:8080/api/cases/CASE-2026-001

# Get investigation graph data
curl http://localhost:8080/api/investigations/1/graph
```

### Wallet Monitoring
```bash
# Get suspect wallets from investigations
curl http://localhost:8080/api/monitor/suspects

# Add wallet to monitoring
curl -X POST http://localhost:8080/api/monitor/wallets \
  -H "Content-Type: application/json" \
  -d '{"address": "0x...", "chain": "ETH", "label": "Suspect 1"}'

# Remove wallet from monitoring
curl -X DELETE "http://localhost:8080/api/monitor/wallets/0x...?chain=ETH"

# Get monitoring alerts
curl http://localhost:8080/api/monitor/alerts
```

### Token Management
```bash
# Add token to track
curl -X POST http://localhost:8080/api/tokens/add \
  -H "Content-Type: application/json" \
  -d '{"contract_address": "0x...", "blockchain": "polygon-pos", "trigram": "POL"}'

# Schedule data fetch
curl -X POST http://localhost:8080/api/tokens/schedule_fetch \
  -H "Content-Type: application/json" \
  -d '{"symbol": "USDT", "chains": ["ETH", "POL"], "start_date": "2026-01-01", "end_date": "2026-01-25"}'
```

### GraphQL
```graphql
query {
  transferHistory(symbol: "USDT", chain: "ETH", limit: 100) {
    from
    to
    value
    blockNumber
    timestamp
  }
}
```

---

## 🧪 Testing

**Status: 22/22 tests passing (100%)**

```bash
# Run all tests
docker compose exec web pytest

# Run with coverage
docker compose exec web pytest --cov=. --cov-report=html

# Run by marker
docker compose exec web pytest -m unit        # Unit tests
docker compose exec web pytest -m integration # Integration tests
docker compose exec web pytest -m api         # API tests
```

---

## 🔧 Development Commands

```bash
# View logs
docker compose logs -f web
docker compose logs -f celery

# Database shell
docker compose exec postgres psql -U bubble_user -d bubble_db

# Restart services
docker compose restart web celery

# Stop all services
docker compose down

# Stop and remove volumes (DELETES DATA)
docker compose down -v

# Sync local changes to running container
docker cp api/routes.py bubble_web:/app/api/routes.py
docker restart bubble_web
```

---

## 🐛 Troubleshooting

| Issue | Solution |
|-------|----------|
| Services not starting | `docker compose logs <service>` |
| Database connection | `docker compose exec postgres pg_isready -U bubble_user` |
| Foreign key errors | Run database initialization to seed reference data |
| Celery tasks stuck | `docker compose logs celery` then `docker compose restart celery` |
| Rate limit errors | Tasks retry automatically with exponential backoff |
| Port 8080 in use | `netstat -ano \| findstr :8080` (Windows) or `lsof -i :8080` (Linux) |

---

## 🗺️ Roadmap

- [ ] Multi-tenant support with role-based access
- [ ] Automated wallet clustering with ML
- [ ] Exchange deposit address identification
- [ ] PDF report generation for investigations
- [ ] Webhook notifications for alerts
- [ ] Support for additional chains (Arbitrum, Optimism, Avalanche)

---

## 📜 License

**Source Available License** - Free for educational and personal use.

| Use Case | Allowed | Cost |
|----------|---------|------|
| Learning / Education | ✅ | Free |
| Personal Projects | ✅ | Free |
| Portfolio | ✅ | Free |
| Commercial / Business | ⚠️ | [Contact](https://datascience-adventure.xyz/contact) |

See [LICENSE](LICENSE) for full terms.

---

**Built with:** Python 3.12 • Flask • Celery • PostgreSQL • Redis • vis.js • Docker
