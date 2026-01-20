# config/settings.py
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Config:
    """Application configuration"""
    
    # Flask
    SECRET_KEY = os.getenv('FLASK_SECRET_KEY', 'dev-secret-key-change-in-production')
    FLASK_ENV = os.getenv('FLASK_ENV', 'development')
    DEBUG = FLASK_ENV == 'development'
    
    # PostgreSQL
    POSTGRES_HOST = os.getenv('POSTGRES_HOST', 'localhost')
    POSTGRES_PORT = os.getenv('POSTGRES_PORT', '5432')
    POSTGRES_DB = os.getenv('POSTGRES_DB', 'bubble_db')
    POSTGRES_USER = os.getenv('POSTGRES_USER', 'bubble_user')
    POSTGRES_PASSWORD = os.getenv('POSTGRES_PASSWORD', 'bubble_password')
    
    SQLALCHEMY_DATABASE_URI = f'postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Redis
    REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
    
    # Celery
    CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', REDIS_URL)
    CELERY_RESULT_BACKEND = os.getenv('CELERY_RESULT_BACKEND', REDIS_URL)
    
    # TigerGraph
    TIGERGRAPH_HOST = os.getenv('TIGERGRAPH_HOST', 'localhost')
    TIGERGRAPH_PORT = os.getenv('TIGERGRAPH_PORT', '9000')
    TIGERGRAPH_USERNAME = os.getenv('TIGERGRAPH_USERNAME', 'tigergraph')
    TIGERGRAPH_PASSWORD = os.getenv('TIGERGRAPH_PASSWORD', 'tigergraph')
    TIGERGRAPH_GRAPH_NAME = os.getenv('TIGERGRAPH_GRAPH_NAME', 'BubbleGraph')
    
    # API Keys
    ETHERSCAN_API_KEY = os.getenv('ETHERSCAN_API_KEY', '')
    BSCSCAN_API_KEY = os.getenv('BSCSCAN_API_KEY', '')
    POLYGONSCAN_API_KEY = os.getenv('POLYGONSCAN_API_KEY', '')
    BASESCAN_API_KEY = os.getenv('BASESCAN_API_KEY', '')
    
    # CoinGecko
    COINGECKO_API_URL = os.getenv('COINGECKO_API_URL', 'https://api.coingecko.com/api/v3')
    
    # Logging
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    LOG_DIR = os.getenv('LOG_DIR', './logs')


def get_config():
    """Legacy function for backward compatibility"""
    return {
        'CELERY_BROKER_URL': Config.CELERY_BROKER_URL,
        'result_backend': Config.CELERY_RESULT_BACKEND,
        'SECRET_KEY': Config.SECRET_KEY
    }