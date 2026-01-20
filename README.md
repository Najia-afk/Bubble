# Bubble - Blockchain Analytics Platform

[![Python](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/Docker-24.0+-blue.svg)](https://www.docker.com/)
[![Flask](https://img.shields.io/badge/Flask-3.1-green.svg)](https://flask.palletsprojects.com/)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0-red.svg)](https://www.sqlalchemy.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15-blue.svg)](https://www.postgresql.org/)
[![Celery](https://img.shields.io/badge/Celery-5.6-green.svg)](https://docs.celeryq.dev/)
[![Tests](https://img.shields.io/badge/tests-22%20passing-brightgreen.svg)](#testing)
[![License](https://img.shields.io/badge/license-Source%20Available-orange.svg)](#license)

Production-grade blockchain analytics platform for tracking ERC-20 token transactions across multiple networks with automated data pipelines and graph visualization.

### ✨ Key Features
- **Multi-chain Support**: Ethereum, BSC, Polygon, Base
- **Automated Pipeline**: Add token → Create tables → Fetch data → Sync to graph DB
- **Async Processing**: Celery workers with Redis for distributed task queue
- **Interactive Visualization**: Transaction flow graphs powered by vis.js
- **GraphQL API**: Flexible queries for token data and transfers

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
├── docker/                     # Docker configurations
│   ├── Dockerfile.web          # Web application image
│   ├── Dockerfile.celery       # Celery worker image
│   └── nginx.conf              # Nginx reverse proxy
│
├── api/                        # API layer
│   ├── routes.py               # REST endpoints
│   ├── application/            # SQLAlchemy models
│   ├── services/               # Business logic
│   └── tasks/                  # Celery tasks
│
├── cypher_app/                 # TigerGraph integration
│   ├── src/                    # Data loaders
│   └── scripts/                # Schema initialization
│
├── graphql_app/                # GraphQL layer
│   ├── schemas/                # GraphQL schemas
│   └── types/                  # GraphQL types
│
├── scripts/                    # Data fetching scripts
│   └── src/                    # CoinGecko, blockchain scanners
│
├── templates/                  # HTML templates
├── static/                     # CSS, JS assets
├── config/                     # Configuration & requirements
├── tests/                      # Pytest test suite
└── docs/                       # Documentation & archives
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

| Service | URL |
|---------|-----|
| Dashboard | http://localhost:8080 |
| Admin Panel | http://localhost:8080/admin |
| Visualizations | http://localhost:8080/visualize |
| **API Docs (Swagger)** | http://localhost:8080/api/docs |
| GraphQL Explorer | http://localhost:8080/graphql |
| API Health | http://localhost:8080/api/health |

### Production Mode
```bash
docker compose -f docker-compose.prod.yml up -d --build
```

| Service | Port | Description |
|---------|------|-------------|
| Nginx | 8080 | Reverse proxy (external) |
| Flask/Gunicorn | 5000 | API (internal only) |
| PostgreSQL | 5432 | Database (internal only) |
| Redis | 6379 | Message broker (internal only) |

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

# API Keys (required)
COINGECKO_API_KEY=your_key
ETHERSCAN_API_KEY=your_key
BSCSCAN_API_KEY=your_key
POLYGONSCAN_API_KEY=your_key
BASESCAN_API_KEY=your_key
```

Get API keys from:
- [CoinGecko](https://www.coingecko.com/en/api)
- [Etherscan](https://etherscan.io/apis)
- [BSCScan](https://bscscan.com/apis)
- [PolygonScan](https://polygonscan.com/apis)
- [BaseScan](https://basescan.org/apis)

---

## 🔌 API Endpoints

### Token Management
```bash
# Add token
curl -X POST http://localhost:8080/api/tokens/add \
  -H "Content-Type: application/json" \
  -d '{"contract_address": "0x385Eeac5cB85A38A9a07A70c73e0a3271CfB54A7", "blockchain": "polygon-pos", "trigram": "POL"}'

# List tokens
curl http://localhost:8080/api/tokens/list

# Schedule data fetch
curl -X POST http://localhost:8080/api/tokens/schedule_fetch \
  -H "Content-Type: application/json" \
  -d '{"symbol": "GHST", "chains": ["POL"], "start_date": "2026-01-19", "end_date": "2026-01-20"}'
```

### GraphQL
```graphql
query {
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
```

---

## 🐛 Troubleshooting

| Issue | Solution |
|-------|----------|
| Services not starting | `docker compose logs <service>` |
| Database connection | `docker compose exec postgres pg_isready -U bubble_user` |
| Celery tasks stuck | `docker compose logs celery` then `docker compose restart celery` |
| Rate limit errors | Tasks retry automatically with exponential backoff |
| Port 8080 in use | `netstat -ano \| findstr :8080` (Windows) or `lsof -i :8080` (Linux) |

---

## 📝 Example Tokens

| Token | Chain | Contract Address |
|-------|-------|------------------|
| GHST | Polygon | `0x385eeac5cb85a38a9a07a70c73e0a3271cfb54a7` |
| GHST | Base | `0x7645DD9B4d01D4A0C321e8399070c6AC90deBff0` |
| USDT | Ethereum | `0xdac17f958d2ee523a2206206994597c13d831ec7` |
| USDT | Polygon | `0xc2132d05d31c914a87c6611c10748aeb04b58e8f` |

---

## 📚 Documentation

Additional documentation available in `docs/`:
- [docs/archive/](docs/archive/) - Historical demo scripts and validation reports

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

**Built with:** Python 3.12, Flask, Celery, PostgreSQL, Redis, TigerGraph, Docker
