"""
Database connection module for court processor
"""
import os
import psycopg2
from psycopg2.extras import RealDictCursor
import logging

logger = logging.getLogger(__name__)

def get_db_connection(cursor_factory=None):
    """
    Get database connection using environment variable or defaults
    """
    # Get DATABASE_URL from environment or construct from individual variables
    database_url = os.getenv('DATABASE_URL')
    
    if not database_url:
        # Construct from individual environment variables (Docker setup)
        db_host = os.getenv('DB_HOST', 'localhost')
        db_port = os.getenv('DB_PORT', '5432')
        db_name = os.getenv('DB_NAME', 'aletheia')
        db_user = os.getenv('DB_USER', 'aletheia')
        db_password = os.getenv('DB_PASSWORD', 'aletheia123')
        database_url = f'postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}'
    
    try:
        if cursor_factory:
            conn = psycopg2.connect(database_url, cursor_factory=cursor_factory)
        else:
            conn = psycopg2.connect(database_url)
        return conn
    except Exception as e:
        logger.error(f"Failed to connect to database: {e}")
        raise

def get_db_config():
    """
    Parse database configuration from DATABASE_URL or individual environment variables
    """
    database_url = os.getenv('DATABASE_URL')
    
    if not database_url:
        # Construct from individual environment variables (Docker setup)
        db_host = os.getenv('DB_HOST', 'db')
        db_port = os.getenv('DB_PORT', '5432')
        db_name = os.getenv('DB_NAME', 'aletheia')
        db_user = os.getenv('DB_USER', 'aletheia')
        db_password = os.getenv('DB_PASSWORD', 'aletheia123')
        database_url = f'postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}'
    
    # Parse the URL
    import re
    match = re.match(r'postgresql://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)', database_url)
    
    if match:
        return {
            'user': match.group(1),
            'password': match.group(2),
            'host': match.group(3),
            'port': match.group(4),
            'database': match.group(5)
        }
    else:
        # Fallback defaults
        return {
            'user': 'aletheia',
            'password': 'aletheia123',
            'host': 'db',
            'port': '5432',
            'database': 'aletheia'
        }