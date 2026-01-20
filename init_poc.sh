#!/bin/bash
# Initialize Bubble - Blockchain Analytics Platform
# This script sets up and launches the entire Bubble platform locally

set -e  # Exit on error

# Add Docker to PATH if needed
export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"

echo "=================================="
echo "🫧 Bubble Platform Initialization"
echo "=================================="
echo ""

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Error: Docker is not running. Please start Docker Desktop."
    exit 1
fi

echo "✓ Docker is running"
echo ""

# Create .env file if it doesn't exist
if [ ! -f .env ]; then
    echo "Creating .env file from template..."
    cp .env.example .env
    echo "✓ .env file created (using default values)"
fi

echo "✓ Environment configuration ready"
echo ""

# Build Docker images
echo "=================================="
echo "Building Docker images..."
echo "=================================="
docker compose build

echo ""
echo "✓ Docker images built successfully"
echo ""

# Start services
echo "=================================="
echo "Starting services..."
echo "=================================="
docker compose up -d postgres redis

echo "Waiting for databases to be ready..."
sleep 10

# Check PostgreSQL
echo "Checking PostgreSQL..."
docker compose exec -T postgres pg_isready -U bubble_user || {
    echo "❌ PostgreSQL is not ready"
    exit 1
}
echo "✓ PostgreSQL is ready"

# Check Redis
echo "Checking Redis..."
docker compose exec -T redis redis-cli ping || {
    echo "❌ Redis is not ready"
    exit 1
}
echo "✓ Redis is ready"

echo ""
echo "✓ All databases are ready"
echo ""

# Start application services
echo "=================================="
echo "Starting application services..."
echo "=================================="
docker compose up -d web celery nginx

echo "Waiting for services to be ready..."
sleep 5

echo ""
echo "✓ All services started"
echo ""

# Run pytest to validate setup
echo "=================================="
echo "🧪 Running tests (like mission7)..."
echo "=================================="
echo ""
docker compose exec -T web pytest tests/ -v --tb=short -m "not slow" || {
    echo "⚠️  Some tests failed, but continuing..."
}
echo ""
echo "✓ Tests completed"
echo ""

# Initialize GHST as production validation token
echo "=================================="
echo "🎮 Initializing GHST (production validation)..."
echo "=================================="
docker compose exec -T web python -c "
from api.application.erc20models import Token
from utils.database import get_session_factory
SessionFactory = get_session_factory()
session = SessionFactory()
existing = session.query(Token).filter_by(symbol='GHST', blockchain='POL').first()
if not existing:
    ghst = Token(
        symbol='GHST',
        contract_address='0x385Eeac5cB85A38A9a07A70c73e0a3271CfB54A7',
        blockchain='POL',
        name='Aavegotchi',
        decimals=18
    )
    session.add(ghst)
    session.commit()
    print('✓ GHST token initialized')
else:
    print('✓ GHST token already exists')
session.close()
"
echo ""

# TigerGraph initialization commented out - enable when TigerGraph is available
# echo "=================================="
# echo "Initializing TigerGraph schema..."
# echo "=================================="
# docker compose exec -T web python cypher_app/scripts/init_schema.py
# echo ""
# echo "✓ TigerGraph schema initialized"
# echo ""

# Display success message
echo "=================================="
echo "🎉 Bubble Platform is ready!"
echo "=================================="
echo ""
echo "Access the application:"
echo "  🏠 Dashboard:      http://localhost:8080"
echo "  📈 Visualizations: http://localhost:8080/visualize"
echo "  ⚙️  Admin Panel:    http://localhost:8080/admin  ← Start here!"
echo "  🔌 API:            http://localhost:8080/api"
echo "  🌐 GraphQL:        http://localhost:8080/graphql"
echo ""
echo "🧪 Run tests like mission7:"
echo "  docker compose exec web pytest tests/ -v"
echo "  docker compose exec web pytest tests/ -m ghst  # GHST validation tests"
echo ""
echo "🎮 Test GHST (production validation):"
echo "  ./ghst_example.sh"
echo "  # Or manually fetch last 24h on POL + BASE"
echo ""
echo "Getting started:"
echo "  1. Navigate to http://localhost:8080/admin"
echo "  2. GHST token already initialized ✓"
echo "  3. Select chains (POL, BASE) and date range"
echo "  4. Click 'Schedule Fetch' to get transfer data"
echo "  5. Monitor task progress in Active Tasks panel"
echo "  6. View graph visualization at /visualize"
echo ""
echo "Service endpoints:"
echo "  PostgreSQL:     localhost:5432"
echo "  Redis:          localhost:6379"
echo "  # TigerGraph:   localhost:9000 (disabled - enable in docker-compose.yml)"
echo ""
echo "View logs:"
echo "  docker compose logs -f web"
echo "  docker compose logs -f celery"
echo ""
echo "Stop services:"
echo "  docker compose down"
echo ""
echo "=================================="
