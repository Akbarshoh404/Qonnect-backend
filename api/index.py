"""
Vercel Serverless Function entrypoint for Qonnect Flask Backend
"""
import os
import sys

# Add parent directory to sys.path so 'app' package imports work cleanly
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app import create_app
from app.extensions import db

# Create Flask application instance
app = create_app("production" if os.environ.get("VERCEL") else None)

# Initialize database tables on serverless function cold-start
with app.app_context():
    try:
        db.create_all()
    except Exception as e:
        app.logger.error(f"Error during db.create_all: {e}")
