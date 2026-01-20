# 🚀 Bubble - Demo Guide

**Status:** ✅ Production Ready  
**Architecture:** mission7 Security Standard  
**Tests:** 22/22 Passing (100%)

---

## Quick Start

### 1. Start Services
```bash
docker compose up -d --build
```

Wait ~30 seconds for services to be healthy, then verify:
```bash
docker compose ps
```

Expected output:
```
NAME              STATUS
bubble_postgres   Up (healthy)
bubble_redis      Up (healthy)
bubble_web        Up (healthy)
bubble_celery     Up (healthy)
bubble_nginx      Up (health: starting)
```

---

## 2. Test API Health

```bash
curl http://localhost:8080/health
```

Expected:
```json
{
  "service": "bubble-api",
  "status": "healthy",
  "timestamp": "2026-01-20T..."
}
```

---

## 3. Run Tests

```bash
docker compose exec web pytest -v
```

Expected: **22 tests passed** ✅

---

## 4. Demo: GHST Token Workflow

### a) List Tokens
```bash
curl http://localhost:8080/api/tokens/list | python3 -m json.tool
```

### b) Add New Token (Example: USDC)
```bash
curl -X POST http://localhost:8080/api/tokens/add \
  -H "Content-Type: application/json" \
  -d '{
    "contract_address": "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",
    "blockchain": "polygon-pos",
    "trigram": "POL"
  }'
```

### c) Schedule Price Fetch
```bash
curl -X POST http://localhost:8080/api/tokens/schedule_fetch \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "USDC",
    "chains": ["POL"],
    "start_date": "2026-01-19",
    "end_date": "2026-01-20"
  }'
```

### d) Check Celery Tasks
```bash
docker compose logs celery --tail=50
```

### e) Verify Data in PostgreSQL
```bash
docker compose exec postgres psql -U bubble_user -d bubble_db \
  -c "SELECT symbol, name, contract_address FROM token;"
```

```bash
docker compose exec postgres psql -U bubble_user -d bubble_db \
  -c "SELECT COUNT(*) as price_records FROM token_price_history;"
```

---

## 5. Security Validation

### ✅ Only Nginx Accessible (mission7 Standard)

**Test external access (should work):**
```bash
curl http://localhost:8080/health
# ✅ Works!
```

**Test direct services (should FAIL - good!):**
```bash
curl --connect-timeout 2 http://localhost:5000/health
# ❌ Connection refused (SECURED!)

curl --connect-timeout 2 http://localhost:5432
# ❌ Connection refused (SECURED!)

curl --connect-timeout 2 http://localhost:6379
# ❌ Connection refused (SECURED!)
```

**Result:** Only nginx exposed on 8080 - all backend services isolated! 🔒

---

## 6. Database Exploration

### Check Dynamic Tables (Auto-created per token)
```bash
docker compose exec postgres psql -U bubble_user -d bubble_db -c "\dt"
```

You should see:
- `token` - Main token registry
- `token_price_history` - Historical price data
- `ghst_pol_erc20_transfer_event` - GHST transfers on Polygon
- `pol_block_transfer_event` - Polygon block events

### View Price History
```bash
docker compose exec postgres psql -U bubble_user -d bubble_db -c "
  SELECT t.symbol, tph.date, tph.price, tph.volume 
  FROM token_price_history tph
  JOIN token t ON tph.contract_address = t.contract_address
  ORDER BY tph.date DESC
  LIMIT 10;
"
```

---

## 7. GraphQL Endpoint (Optional)

If GraphQL schema is registered:
```bash
curl -X POST http://localhost:8080/graphql \
  -H "Content-Type: application/json" \
  -d '{
    "query": "{ tokens { symbol name contractAddress } }"
  }'
```

---

## 8. Stop Services

```bash
docker compose down
```

Keep data:
```bash
docker compose down
```

Remove all data:
```bash
docker compose down -v
```

---

## 🔧 Troubleshooting

### Services not healthy?
```bash
docker compose ps
docker compose logs web
docker compose logs celery
```

### Reset everything:
```bash
docker compose down -v
docker system prune -af --volumes
docker compose up -d --build
```

### Check logs:
```bash
docker compose logs -f web      # Flask app
docker compose logs -f celery   # Task worker
docker compose logs -f nginx    # Reverse proxy
```

---

## 📊 Architecture Overview

```
External → nginx:8080 → web:5000 (Flask)
                           ↓
                        celery (workers)
                           ↓
                    ┌──────┴──────┐
                    ↓             ↓
              postgres:5432   redis:6379
              (SQLAlchemy)    (broker)
```

**Security:** All services isolated in Docker network, only nginx accessible externally.

---

## 🎯 Key Features Demonstrated

✅ **Automated Table Creation** - Dynamic tables per token/blockchain  
✅ **Multi-chain Support** - Ethereum, Polygon, etc.  
✅ **Async Task Processing** - Celery for data fetching  
✅ **RESTful API** - Flask with health checks  
✅ **Database ORM** - SQLAlchemy 2.0  
✅ **GraphQL** - graphene + graphene-sqlalchemy  
✅ **Mission7 Security** - Only nginx exposed  
✅ **Test Coverage** - 22/22 tests passing  

---

## 📝 Environment Variables

Default values in `.env`:
```
POSTGRES_DB=bubble_db
POSTGRES_USER=bubble_user
POSTGRES_PASSWORD=bubble_password
FLASK_ENV=development
REDIS_URL=redis://redis:6379/0
```

---

## 🚀 Production Deployment

For production:
1. Change `FLASK_ENV=production`
2. Update passwords in `.env`
3. Configure domain in nginx
4. Add SSL/TLS certificates
5. Scale celery workers as needed

---

**Enjoy your Bubble blockchain analytics platform!** 🫧
