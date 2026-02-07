# =============================================================================
# Bubble - Blockchain Analytics Platform
# Copyright (c) 2025-2026 All Rights Reserved.
# =============================================================================

from flask import Flask, g, jsonify, request, render_template, redirect
from flask_cors import CORS
from flask_swagger_ui import get_swaggerui_blueprint
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import logging
from config.settings import Config, get_config
from utils.database import get_session_factory
import api.application.erc20models as erc20models
from utils.logging_config import setup_logging
import os

SessionFactory = get_session_factory()

SWAGGER_URL = '/api/docs'
API_URL = '/static/swagger.json'

def create_app():
    app = Flask(__name__, 
                template_folder='templates',
                static_folder='static')
    
    app.config.from_object(Config)
    app_config = get_config()
    app.config.update(app_config)
    
    CORS(app)
    
    swaggerui_blueprint = get_swaggerui_blueprint(
        SWAGGER_URL, API_URL,
        config={
            'app_name': "Bubble API",
            'layout': "BaseLayout",
            'deepLinking': True,
            'displayRequestDuration': True,
            'docExpansion': 'list'
        }
    )
    app.register_blueprint(swaggerui_blueprint, url_prefix=SWAGGER_URL)
    
    app_logger = setup_logging('application.log')

    def initialize_database():
        """Initialize database with core models and CSV data.
        Uses a PostgreSQL advisory lock to prevent race conditions
        when multiple Gunicorn workers start simultaneously.
        """
        from api.application.models import Base as CoreBase
        from scripts.init_db import DatabaseInitializer
        from sqlalchemy import text
        
        session = SessionFactory()
        try:
            engine = session.get_bind()
            
            # Use advisory lock (ID 42) to ensure only one worker inits the DB
            lock_acquired = session.execute(
                text("SELECT pg_try_advisory_lock(42)")
            ).scalar()
            
            if not lock_acquired:
                app_logger.info("Another worker is initializing the database, skipping")
                return
            
            try:
                # Create core tables from models.py
                CoreBase.metadata.create_all(engine, checkfirst=True)
                app_logger.info("Core tables created/verified")
                
                # Create ERC20/ML tables
                erc20models.Base.metadata.create_all(engine, checkfirst=True)
                app_logger.info("ERC20 tables created/verified")
                session.commit()
                
                # Load CSV data if not already done
                try:
                    initializer = DatabaseInitializer(engine.url.render_as_string(hide_password=False))
                    initializer.init_all(force=False)
                    app_logger.info("CSV data loaded")
                except Exception as e:
                    app_logger.warning(f"CSV init skipped: {e}")
                
                # Generate dynamic ERC20 models (only if tokens exist)
                try:
                    erc20models.generate_block_transfer_event_classes(session)
                    erc20models.generate_erc20_classes(session)
                    session.commit()
                except Exception as e:
                    session.rollback()
                    app_logger.warning(f"Dynamic model generation skipped: {e}")
                
                app_logger.info("Database initialization complete")
            finally:
                # Always release the advisory lock
                session.execute(text("SELECT pg_advisory_unlock(42)"))
                session.commit()
                
        except Exception as e:
            session.rollback()
            app_logger.error(f"Database initialization error: {e}")
            import traceback
            app_logger.error(traceback.format_exc())
        finally:
            SessionFactory.remove()

    initialize_database()

    @app.before_request
    def before_request():
        if not hasattr(g, 'db_session'):
            g.db_session = SessionFactory()

    @app.teardown_request
    def teardown_request(exception=None):
        db_session = g.pop('db_session', None)
        if db_session:
            db_session.close()
    
    @app.route('/health')
    def health_check():
        """Health check endpoint for Docker"""
        return jsonify({
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "service": "bubble-api"
        }), 200
    
    @app.route('/')
    def index():
        """Main dashboard"""
        return render_template('dashboard.html')
    
    @app.route('/admin')
    def admin():
        """Admin panel"""
        return render_template('admin/token_management.html')
    
    @app.route('/visualize')
    def visualize():
        """Visualization page"""
        return render_template('visualizations/transaction_flow.html')
    
    @app.route('/graph')
    def graph_page():
        """Full graph visualization - can load investigation data via query params"""
        investigation_id = request.args.get('investigation_id')
        return render_template('visualizations/transaction_flow.html', investigation_id=investigation_id)

    @app.route('/timeline')
    @app.route('/timeline/<int:investigation_id>')
    def timeline_page(investigation_id=None):
        """Interactive timeline visualization (vis.js)"""
        return render_template('visualizations/timeline.html')
    
    # ========================================================================
    # INVESTIGATION & ML PAGES
    # ========================================================================
    
    @app.route('/investigations')
    def investigations_page():
        """Redirect to Cases page"""
        return redirect('/cases')
    
    @app.route('/investigations/<int:investigation_id>')
    def investigation_detail_page(investigation_id):
        """Redirect to full graph page"""
        return redirect(f'/graph?investigation_id={investigation_id}')
    
    @app.route('/classify')
    def classify_page():
        """Wallet classification page with SHAP explainability"""
        return render_template('classify.html')
    
    @app.route('/models')
    def models_page():
        """ML models management page"""
        return render_template('models.html')
    
    @app.route('/audit')
    def audit_page():
        """Audit trail page for compliance"""
        return render_template('audit.html')
    
    @app.route('/cases')
    def cases_page():
        """Cases management page - external investigations"""
        return render_template('cases.html')
    
    @app.route('/monitor')
    def monitor_page():
        """Real-time wallet monitoring page"""
        return render_template('monitor.html')

    @app.errorhandler(Exception)
    def handle_exception(e):
        app_logger.error(f"Unhandled exception: {e}")
        return jsonify(error=str(e)), 500

    # Register API routes
    from api.routes import init_api_routes
    
    # Single API surface
    init_api_routes(app)
    
    # Setup GraphQL endpoint — combined schema (all domains)
    from graphql_app.schemas.combined_schema import combined_schema
    
    @app.route('/graphql', methods=['GET', 'POST'])
    def graphql_endpoint():
        """GraphQL endpoint with GraphiQL interface — all schemas merged."""
        if request.method == 'GET':
            # Return GraphiQL HTML interface
            return '''<!DOCTYPE html>
<html>
<head>
    <title>Bubble GraphQL Explorer</title>
    <style>
        body { margin: 0; height: 100vh; }
        #graphiql { height: 100vh; }
    </style>
    <link rel="stylesheet" href="https://unpkg.com/graphiql@3.0.6/graphiql.min.css" />
</head>
<body>
    <div id="graphiql">Loading GraphiQL...</div>
    <script src="https://unpkg.com/react@18/umd/react.production.min.js" crossorigin></script>
    <script src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js" crossorigin></script>
    <script src="https://unpkg.com/graphiql@3.0.6/graphiql.min.js" crossorigin></script>
    <script>
        const root = ReactDOM.createRoot(document.getElementById('graphiql'));
        root.render(
            React.createElement(GraphiQL, {
                fetcher: GraphiQL.createFetcher({ url: '/graphql' }),
                defaultEditorToolsVisibility: true,
            })
        );
    </script>
</body>
</html>'''
        
        # POST - execute GraphQL query
        data = request.get_json()
        query = data.get('query', '')
        variables = data.get('variables', {})
        
        result = combined_schema.execute(
            query,
            variables=variables,
            context={'session': g.db_session}
        )
        
        response = {'data': result.data}
        if result.errors:
            response['errors'] = [str(e) for e in result.errors]
        
        return jsonify(response)

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, host='0.0.0.0', port=5000)
