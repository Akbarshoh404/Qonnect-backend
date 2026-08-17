"""
Vercel Serverless Function entrypoint for Qonnect Flask Backend
"""
import os
import sys

root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from app import create_app
from app.extensions import db

flask_app = create_app("production" if os.environ.get("VERCEL") else None)

with flask_app.app_context():
    try:
        db.create_all()
    except Exception as e:
        flask_app.logger.warning(f"db.create_all warning: {e}")


def app(environ, start_response):
    """
    WSGI wrapper for Vercel Serverless Function.
    Ensures PATH_INFO matches the actual incoming request path rather than
    the entrypoint filename (/api/index.py or /wsgi.py).
    """
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

    return flask_app(environ, start_response)


# WSGI alias
application = app
