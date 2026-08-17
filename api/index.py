"""
Vercel Serverless Function entrypoint for Qonnect Flask Backend
"""
import os
import sys
import traceback

# Add backend directory to sys.path so 'app' package imports work cleanly
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

try:
    from app import create_app
    from app.extensions import db

    # Create Flask application instance
    app = create_app("production" if os.environ.get("VERCEL") else None)

    # Initialize database tables
    with app.app_context():
        try:
            db.create_all()
        except Exception as e:
            app.logger.warning(f"db.create_all warning: {e}")

except Exception:
    err_traceback = traceback.format_exc()

    # Fallback WSGI application to display exact startup exception
    def app(environ, start_response):
        start_response("500 Internal Server Error", [("Content-Type", "text/plain; charset=utf-8")])
        return [f"Qonnect Backend Startup Error:\n\n{err_traceback}".encode("utf-8")]
