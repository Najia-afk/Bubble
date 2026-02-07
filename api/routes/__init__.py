"""
api.routes — Blueprint registry.

Each domain has its own module with a single Flask Blueprint.
This package replaces the former monolithic ``api/routes.py`` (3 200+ lines).

Usage in ``app.py``::

    from api.routes import init_api_routes
    init_api_routes(app)
"""

from .health_routes import health_bp
from .graph_routes import graph_bp
from .token_routes import token_bp
from .sync_routes import sync_bp
from .label_routes import label_bp
from .investigation_routes import investigation_bp
from .case_routes import case_bp
from .classify_routes import classify_bp
from .ml_routes import ml_bp
from .audit_routes import audit_bp
from .legacy_routes import legacy_bp
from .monitor_routes import monitor_bp
from .feature_routes import feature_bp
from .notebook_routes import notebook_bp

_ALL_BLUEPRINTS = [
    health_bp,
    graph_bp,
    token_bp,
    sync_bp,
    label_bp,
    investigation_bp,
    case_bp,
    classify_bp,
    ml_bp,
    audit_bp,
    legacy_bp,
    monitor_bp,
    feature_bp,
    notebook_bp,
]


def init_api_routes(app):
    """Register every API blueprint under ``/api``."""
    for bp in _ALL_BLUEPRINTS:
        app.register_blueprint(bp, url_prefix='/api')
