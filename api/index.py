"""
Vercel Serverless Function entrypoint for Qonnect Flask Backend
"""
import os
import sys
import json

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
    # Debug endpoint to inspect incoming Vercel WSGI environment variables
    path = environ.get("PATH_INFO", "")
    req_uri = environ.get("REQUEST_URI", "") or environ.get("RAW_URI", "")
    if "debug" in path or "debug" in req_uri:
        start_response("200 OK", [("Content-Type", "application/json")])
        safe_env = {
            k: str(v)
            for k, v in environ.items()
            if "SECRET" not in k and "KEY" not in k and "PASS" not in k and "TOKEN" not in k
        }
        return [json.dumps(safe_env, indent=2).encode("utf-8")]

    # Fix PATH_INFO if Vercel set it to entrypoint filename
    raw_uri = req_uri or environ.get("HTTP_X_FORWARDED_URI") or environ.get("HTTP_X_MATCHED_PATH")
    if raw_uri:
        path_only = raw_uri.split("?")[0]
        if path_only and path_only != path:
            environ["PATH_INFO"] = path_only

    return flask_app(environ, start_response)


application = app
