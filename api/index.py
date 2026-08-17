"""
Vercel Serverless Function entrypoint for Qonnect Flask Backend
"""
import os
import sys

# Add root backend directory to sys.path so 'app' package is found as a proper package
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from app import create_app
from app.extensions import db

# Create Flask application instance
app = create_app("production" if os.environ.get("VERCEL") else None)

# Initialize database tables on cold start
with app.app_context():
    try:
        db.create_all()
    except Exception as e:
        app.logger.warning(f"db.create_all warning: {e}")
