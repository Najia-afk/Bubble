#!/bin/bash
# =============================================================================
# Bubble - GHST Token Example Script
# Fetch GHST transfers for last 24h on BASE and POL chains
# =============================================================================

export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"

echo "🫧 Bubble - GHST Token Example"
echo "================================"
echo ""

# Wait for services to be ready
echo "⏳ Waiting for services to start..."
sleep 10

# Health check
echo "🏥 Checking API health..."
curl -s http://localhost:8080/health | jq . || echo "API not ready yet, waiting..."
sleep 5

echo ""
echo "📋 Step 1: Add GHST Token"
echo "-------------------------"

# GHST token addresses (example - replace with actual addresses)
# Polygon: 0x385Eeac5cB85A38A9a07A70c73e0a3271CfB54A7
# Base: Check BaseScan for actual GHST contract

curl -X POST http://localhost:8080/api/tokens/add \
  -H "Content-Type: application/json" \
  -d '{
    "contract_address": "0x385Eeac5cB85A38A9a07A70c73e0a3271CfB54A7",
    "blockchain": "POL"
  }' | jq .

echo ""
echo ""
echo "⏰ Step 2: Fetch GHST transfers for last 24h"
echo "--------------------------------------------"

# Calculate dates (last 24 hours)
END_DATE=$(date +%Y-%m-%d)
START_DATE=$(date -v-1d +%Y-%m-%d)

echo "📅 Date range: $START_DATE to $END_DATE"
echo ""

# Trigger fetch for POL chain
echo "🟣 Fetching GHST on Polygon (POL)..."
curl -X POST http://localhost:8080/api/tokens/schedule_fetch \
  -H "Content-Type: application/json" \
  -d "{
    \"symbol\": \"GHST\",
    \"chains\": [\"POL\"],
    \"start_date\": \"$START_DATE\",
    \"end_date\": \"$END_DATE\",
    \"fetch_mode\": \"transfers\"
  }" | jq .

echo ""
echo ""

# Trigger fetch for BASE chain (if GHST exists on Base)
echo "🔵 Fetching GHST on Base..."
curl -X POST http://localhost:8080/api/tokens/schedule_fetch \
  -H "Content-Type: application/json" \
  -d "{
    \"symbol\": \"GHST\",
    \"chains\": [\"BASE\"],
    \"start_date\": \"$START_DATE\",
    \"end_date\": \"$END_DATE\",
    \"fetch_mode\": \"transfers\"
  }" | jq .

echo ""
echo ""
echo "📊 Step 3: Check active tasks"
echo "------------------------------"
curl -s http://localhost:8080/api/tasks/active | jq .

echo ""
echo ""
echo "✅ Commands sent! Check the dashboard at:"
echo "   🏠 http://localhost:8080"
echo "   ⚙️  http://localhost:8080/admin"
echo ""
echo "📝 To monitor Celery worker logs:"
echo "   docker compose logs -f celery"
echo ""
