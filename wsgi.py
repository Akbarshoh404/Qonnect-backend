"""
Qonnect Backend - Flask Application WSGI Entrypoint
"""
import os
import sys
from urllib.parse import parse_qs

root_dir = os.path.dirname(os.path.abspath(__file__))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from app import create_app
from app.extensions import db

app = create_app("production" if os.environ.get("VERCEL") else None)


class PathInfoMiddleware:
    """
    WSGI Middleware for Vercel Serverless Function runtime.
    Restores original requested path from __path__ query param.
    """
    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        qs = environ.get("QUERY_STRING", "")
        if "__path__=" in qs:
            params = parse_qs(qs)
            if "__path__" in params and params["__path__"]:
                target_path = params["__path__"][0]
                environ["PATH_INFO"] = target_path if target_path.startswith("/") else f"/{target_path}"

        return self.wsgi_app(environ, start_response)


app.wsgi_app = PathInfoMiddleware(app.wsgi_app)
application = app

with app.app_context():
    try:
        db.create_all()
    except Exception as e:
        app.logger.warning(f"db.create_all warning: {e}")
