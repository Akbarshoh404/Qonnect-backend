"""
Vercel Serverless Function entrypoint for Qonnect Flask Backend
"""
import os
import sys
import traceback

# Ensure all possible module paths are added so 'app' package is found
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
cwd = os.getcwd()

for p in (parent_dir, current_dir, cwd, "/var/task", "/var/task/app"):
    if p and p not in sys.path and os.path.exists(p):
        sys.path.insert(0, p)

try:
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

except Exception:
    err_traceback = traceback.format_exc()

    # Fallback WSGI application to display exact startup exception
    def app(environ, start_response):
        start_response("500 Internal Server Error", [("Content-Type", "text/plain; charset=utf-8")])
        return [f"Qonnect Backend Startup Error:\n\n{err_traceback}".encode("utf-8")]
