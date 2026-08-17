"""
Qonnect Backend - Flask Application WSGI Entrypoint
"""
import os
import sys

root_dir = os.path.dirname(os.path.abspath(__file__))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from app import create_app
from app.extensions import db

# Create genuine Flask application instance
app = create_app("production" if os.environ.get("VERCEL") else None)


class PathInfoMiddleware:
    """
    WSGI Middleware for Vercel Serverless Function runtime.
    Ensures PATH_INFO always reflects the actual client request URI.
    """
    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        raw_uri = (
            environ.get("REQUEST_URI")
            or environ.get("RAW_URI")
            or environ.get("HTTP_X_FORWARDED_URI")
            or environ.get("HTTP_X_MATCHED_PATH")
        )
        if raw_uri:
            path_only = raw_uri.split("?")[0]
            curr_path = environ.get("PATH_INFO", "")
            if curr_path in ("/api/index.py", "/api/index", "/wsgi.py", "/wsgi", "/api", "") or curr_path != path_only:
                environ["PATH_INFO"] = path_only
        return self.wsgi_app(environ, start_response)


# Wrap Flask's internal WSGI callable so app remains a valid Flask object
app.wsgi_app = PathInfoMiddleware(app.wsgi_app)
application = app

with app.app_context():
    try:
        db.create_all()
    except Exception as e:
        app.logger.warning(f"db.create_all warning: {e}")
