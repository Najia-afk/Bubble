# =============================================================================
# Bubble - Blockchain Analytics Platform
# Copyright (c) 2025-2026 All Rights Reserved.
# =============================================================================

#app.py
from flask import Flask, g, jsonify, request, render_template
from flask_cors import CORS
from sqlalchemy.orm import sessionmaker
import logging
from config.settings import Config, get_config
from utils.database import get_session_factory
import api.application.erc20models as erc20models
from utils.logging_config import setup_logging
import os

SessionFactory = get_session_factory()

def create_app():
    # Setup session factory
    app = Flask(__name__, 
                template_folder='templates',
                static_folder='static')
    
    # Load configuration
    app.config.from_object(Config)
    app_config = get_config()
    app.config.update(app_config)
    
    # Enable CORS
    CORS(app)
    
    app_logger = setup_logging('application.log')

    def initialize_dynamic_models():
        """Initialize dynamic models using a session."""
        session = SessionFactory()
        try:
            erc20models.generate_block_transfer_event_classes(session)
            erc20models.generate_erc20_classes(session)
            session.commit()
        except Exception as e:
            session.rollback()
            app_logger.error(f"Error during model initialization: {e}")
        finally:
            SessionFactory.remove()

    initialize_dynamic_models()

    @app.before_request
    def before_request():
        """Attach a new session to the application context at the beginning of each request."""
        if not hasattr(g, 'db_session'):
            g.db_session = SessionFactory()

    @app.teardown_request
    def teardown_request(exception=None):
        """Close and remove the session at the end of each request."""
        db_session = g.pop('db_session', None)
        if db_session is not None:
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

    @app.errorhandler(Exception)
    def handle_exception(e):
        """Handle uncaught exceptions."""
        app_logger.error(f"Unhandled exception: {e}")

        return jsonify(error=str(e)), 500

    # Import and initialize your routes after app creation to avoid circular imports
    from api.routes import init_api_routes
    from datetime import datetime
    init_api_routes(app)
    
    # Setup GraphQL endpoint (manual - no flask-graphql needed)
    from graphql_app.schemas.fetch_erc20_transfer_history_schema import schema as erc20_schema
    
    @app.route('/graphql', methods=['GET', 'POST'])
    def graphql_endpoint():
        """GraphQL endpoint with GraphiQL interface"""
        if request.method == 'GET':
            # Return GraphiQL HTML interface
            return '''<!DOCTYPE html>
<html>
<head>
    <title>Bubble GraphQL</title>
    <link href="https://unpkg.com/graphiql/graphiql.min.css" rel="stylesheet" />
</head>
<body style="margin: 0;">
    <div id="graphiql" style="height: 100vh;"></div>
    <script crossorigin src="https://unpkg.com/react/umd/react.production.min.js"></script>
    <script crossorigin src="https://unpkg.com/react-dom/umd/react-dom.production.min.js"></script>
    <script crossorigin src="https://unpkg.com/graphiql/graphiql.min.js"></script>
    <script>
        const fetcher = GraphiQL.createFetcher({ url: '/graphql' });
        ReactDOM.render(
            React.createElement(GraphiQL, { fetcher: fetcher }),
            document.getElementById('graphiql'),
        );
    </script>
</body>
</html>'''
        
        # POST - execute GraphQL query
        data = request.get_json()
        query = data.get('query', '')
        variables = data.get('variables', {})
        
        result = erc20_schema.execute(
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




