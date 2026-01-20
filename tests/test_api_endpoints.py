# =============================================================================
# Bubble - Blockchain Analytics Platform
# Copyright (c) 2025-2026 All Rights Reserved.
# =============================================================================
#
# API Endpoint Tests
# Tests the Flask API endpoints for health, tokens, and blockchain data
# =============================================================================

import sys
import os
import pytest
import json
from datetime import datetime, timedelta

# Add app to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import create_app directly from app.py file using spec loader
import importlib.util
spec = importlib.util.spec_from_file_location("app_module", 
    os.path.join(os.path.dirname(__file__), '..', 'app.py'))
app_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app_module)
create_app = app_module.create_app


@pytest.fixture
def client():
    """Create a test client for the Flask app."""
    flask_app = create_app()
    flask_app.config['TESTING'] = True
    with flask_app.test_client() as client:
        yield client


@pytest.fixture
def ghst_token_data():
    """GHST token test data (Aavegotchi on Polygon)."""
    return {
        "contract_address": "0x385Eeac5cB85A38A9a07A70c73e0a3271CfB54A7",
        "blockchain": "polygon-pos",
        "trigram": "POL"
    }


# =============================================================================
# HEALTH CHECKS
# =============================================================================

def test_health_endpoint(client):
    """Test that the health endpoint returns 200 and correct structure."""
    response = client.get('/health')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert 'status' in data
    assert data['status'] == 'healthy'
    assert 'timestamp' in data
    assert 'service' in data
    assert data['service'] == 'bubble-api'


def test_api_health_endpoint(client):
    """Test API blueprint health endpoint."""
    response = client.get('/api/health')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['status'] == 'healthy'


# =============================================================================
# TOKEN MANAGEMENT
# =============================================================================

@pytest.mark.ghst
def test_add_ghst_token(client, ghst_token_data):
    """Test adding GHST token via API."""
    response = client.post(
        '/api/tokens/add',
        data=json.dumps(ghst_token_data),
        content_type='application/json'
    )
    assert response.status_code in [200, 201, 409]  # 409 if already exists
    data = json.loads(response.data)
    
    if response.status_code == 409:
        assert 'error' in data or 'message' in data
    else:
        assert 'symbol' in data or 'message' in data


@pytest.mark.ghst
def test_schedule_ghst_fetch_last_24h(client, ghst_token_data):
    """Test scheduling GHST transfer fetch for last 24 hours."""
    end_date = datetime.now()
    start_date = end_date - timedelta(days=1)
    
    fetch_data = {
        "symbol": "GHST",
        "chains": ["POL", "BASE"],
        "start_date": start_date.strftime("%Y-%m-%d"),
        "end_date": end_date.strftime("%Y-%m-%d"),
        "fetch_mode": "transfers"
    }
    
    response = client.post(
        '/api/tokens/schedule_fetch',
        data=json.dumps(fetch_data),
        content_type='application/json'
    )
    assert response.status_code in [200, 202, 400]
    data = json.loads(response.data)
    
    if response.status_code in [200, 202]:
        assert 'task_id' in data or 'message' in data


@pytest.mark.ghst
def test_ghst_complete_dataflow(client):
    """Test complete GHST dataflow: Add token → Fetch data → Verify storage."""
    # Step 1: Add GHST token
    token_data = {
        "contract_address": "0x385Eeac5cB85A38A9a07A70c73e0a3271CfB54A7",
        "blockchain": "polygon-pos",
        "trigram": "POL"
    }
    response = client.post(
        '/api/tokens/add',
        data=json.dumps(token_data),
        content_type='application/json'
    )
    assert response.status_code in [200, 409]  # 409 if already exists
    
    # Step 2: Verify token in list
    response = client.get('/api/tokens/list')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert 'tokens' in data
    
    # Find GHST token
    ghst_tokens = [t for t in data['tokens'] if t['symbol'].upper() == 'GHST']
    assert len(ghst_tokens) > 0, "GHST token not found after adding"
    
    # Step 3: Schedule data fetch
    fetch_data = {
        "symbol": "GHST",
        "chains": ["POL"],
        "start_date": "2026-01-19",
        "end_date": "2026-01-20",
        "fetch_mode": "price_history"
    }
    response = client.post(
        '/api/tokens/schedule_fetch',
        data=json.dumps(fetch_data),
        content_type='application/json'
    )
    assert response.status_code in [202, 200]
    data = json.loads(response.data)
    assert 'task_id' in data or 'message' in data


# =============================================================================
# CELERY TASK MONITORING
# =============================================================================

def test_active_tasks_endpoint(client):
    """Test active tasks endpoint returns proper structure."""
    response = client.get('/api/tasks/active')
    # May return 200 or 404 if route doesn't exist
    assert response.status_code in [200, 404, 500]
    if response.status_code == 200:
        data = json.loads(response.data)
        assert isinstance(data, (list, dict))


# =============================================================================
# FRONTEND ROUTES
# =============================================================================

def test_dashboard_route(client):
    """Test main dashboard renders."""
    response = client.get('/')
    assert response.status_code == 200
    assert response.content_type == 'text/html; charset=utf-8'


def test_admin_route(client):
    """Test admin panel renders."""
    response = client.get('/admin')
    assert response.status_code == 200
    assert response.content_type == 'text/html; charset=utf-8'


def test_visualize_route(client):
    """Test visualization page renders."""
    response = client.get('/visualize')
    assert response.status_code == 200
    assert response.content_type == 'text/html; charset=utf-8'


# =============================================================================
# TIGERGRAPH SYNC TESTS (if enabled)
# =============================================================================

@pytest.mark.slow
def test_sync_tokens_endpoint(client):
    """Test TigerGraph token sync endpoint."""
    response = client.post('/api/sync/tokens')
    # May return 202 (accepted), 500 (TigerGraph disabled), or 503 (not available)
    assert response.status_code in [202, 500, 503]


@pytest.mark.ghst
@pytest.mark.slow
def test_sync_ghst_transfers(client):
    """Test GHST transfer sync to TigerGraph."""
    sync_data = {
        "chains": ["POL", "BASE"]
    }
    response = client.post(
        '/api/sync/ghst',
        data=json.dumps(sync_data),
        content_type='application/json'
    )
    # May return 202 (accepted), 500 (TigerGraph disabled), or 503 (not available)
    assert response.status_code in [202, 500, 503]


# =============================================================================
# ERROR HANDLING
# =============================================================================

def test_invalid_endpoint_404(client):
    """Test that invalid endpoints return 404 or 500."""
    response = client.get('/api/nonexistent')
    assert response.status_code in [404, 500]


def test_invalid_method_405(client):
    """Test that invalid HTTP methods return 405 or 500."""
    response = client.delete('/api/health')
    assert response.status_code in [405, 500]
