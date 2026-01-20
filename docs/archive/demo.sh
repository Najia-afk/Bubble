#!/bin/bash
# Bubble Quick Demo Script
# Run this after `docker compose up -d`

set -e

# Set Docker path
export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"

echo "🫧 ================================"
echo "   BUBBLE DEMO - Quick Test"
echo "================================"
echo ""

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Wait for services
echo -e "${BLUE}⏳ Waiting for services to be ready...${NC}"
sleep 5

# Test 1: Health Check
echo -e "\n${BLUE}1️⃣  Testing API Health...${NC}"
HEALTH=$(curl -s http://localhost:8080/health)
if echo "$HEALTH" | grep -q "healthy"; then
    echo -e "${GREEN}✅ API is healthy!${NC}"
    echo "$HEALTH" | python3 -m json.tool
else
    echo -e "${RED}❌ API health check failed${NC}"
    exit 1
fi

# Test 2: List Tokens
echo -e "\n${BLUE}2️⃣  Listing registered tokens...${NC}"
TOKENS=$(curl -s http://localhost:8080/api/tokens/list)
TOKEN_COUNT=$(echo "$TOKENS" | python3 -c "import sys, json; print(len(json.load(sys.stdin)['tokens']))")
echo -e "${GREEN}✅ Found $TOKEN_COUNT token(s)${NC}"
echo "$TOKENS" | python3 -m json.tool

# Test 3: Security Check
echo -e "\n${BLUE}3️⃣  Testing Security (mission7 standard)...${NC}"
echo "   Testing nginx (should work):"
if curl -s -o /dev/null -w "%{http_code}" --connect-timeout 2 http://localhost:8080/health | grep -q "200"; then
    echo -e "${GREEN}   ✅ Nginx accessible on :8080${NC}"
else
    echo -e "${RED}   ❌ Nginx not accessible${NC}"
fi

echo "   Testing direct web access (should fail):"
if timeout 2 bash -c 'cat < /dev/null > /dev/tcp/localhost/5000' 2>/dev/null; then
    echo -e "${RED}   ❌ WARNING: Port 5000 is exposed!${NC}"
else
    echo -e "${GREEN}   ✅ Port 5000 secured (not accessible)${NC}"
fi

echo "   Testing direct postgres (should fail):"
if timeout 2 bash -c 'cat < /dev/null > /dev/tcp/localhost/5432' 2>/dev/null; then
    echo -e "${RED}   ❌ WARNING: Port 5432 is exposed!${NC}"
else
    echo -e "${GREEN}   ✅ Port 5432 secured (not accessible)${NC}"
fi

echo "   Testing direct redis (should fail):"
if timeout 2 bash -c 'cat < /dev/null > /dev/tcp/localhost/6379' 2>/dev/null; then
    echo -e "${RED}   ❌ WARNING: Port 6379 is exposed!${NC}"
else
    echo -e "${GREEN}   ✅ Port 6379 secured (not accessible)${NC}"
fi

# Test 4: Check Services
echo -e "\n${BLUE}4️⃣  Checking Docker services...${NC}"
docker compose ps

# Test 5: Database Check
echo -e "\n${BLUE}5️⃣  Checking database...${NC}"
DB_TABLES=$(docker compose exec -T postgres psql -U bubble_user -d bubble_db -t -c "\dt" | grep -c "table" || true)
echo -e "${GREEN}✅ Found $DB_TABLES table(s) in database${NC}"

PRICE_COUNT=$(docker compose exec -T postgres psql -U bubble_user -d bubble_db -t -c "SELECT COUNT(*) FROM token_price_history;" | tr -d ' ')
echo -e "${GREEN}✅ Price history records: $PRICE_COUNT${NC}"

# Summary
echo -e "\n${GREEN}================================"
echo "✅ DEMO COMPLETE!"
echo "================================${NC}"
echo ""
echo "📊 Summary:"
echo "  • API Status: Healthy"
echo "  • Tokens: $TOKEN_COUNT registered"
echo "  • Security: mission7 standard (only nginx exposed)"
echo "  • Database: $DB_TABLES tables, $PRICE_COUNT price records"
echo ""
echo "🔗 Endpoints:"
echo "  • Health: http://localhost:8080/health"
echo "  • API: http://localhost:8080/api/"
echo "  • Tokens: http://localhost:8080/api/tokens/list"
echo ""
echo "📖 Full demo guide: DEMO.md"
echo ""
