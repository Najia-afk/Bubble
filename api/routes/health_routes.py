"""Health check endpoints."""

from flask import Blueprint, jsonify
from datetime import datetime

health_bp = Blueprint('health', __name__)


@health_bp.route("/health", methods=['GET'])
def health_check():
    """Health check endpoint for Docker."""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "service": "bubble-api"
    }), 200
