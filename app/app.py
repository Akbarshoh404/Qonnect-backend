"""
Flask Application Factory
"""
import logging
import os
from flask import Flask, jsonify, request
from flask_login import LoginManager

from .config import config
from .extensions import db, migrate, cors, limiter, login_manager
from .models import User


def create_app(config_name: str | None = None) -> Flask:
    """Create and configure the Flask application."""
    if config_name is None:
        config_name = os.environ.get("FLASK_ENV", "development")

    app = Flask(__name__)
    app.config.from_object(config.get(config_name, config["default"]))

    # Configure logging
    _configure_logging(app)

    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)
    limiter.init_app(app)

    cors.init_app(
        app,
        resources={r"/api/*": {"origins": app.config["FRONTEND_URL"]}},
        supports_credentials=True,
    )

    login_manager.init_app(app)
    login_manager.login_view = None  # API returns 401, frontend handles redirect

    @login_manager.user_loader
    def load_user(user_id: str):
        return User.query.get(int(user_id))

    @login_manager.unauthorized_handler
    def unauthorized():
        return jsonify({"error": "Authentication required"}), 401

    # Register blueprints
    from .routes import auth_bp, qr_bp, redirect_bp, analytics_bp, domains_bp, drive_bp, admin_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(qr_bp)
    app.register_blueprint(redirect_bp)
    app.register_blueprint(analytics_bp)
    app.register_blueprint(domains_bp)
    app.register_blueprint(drive_bp)
    app.register_blueprint(admin_bp)

    # Register Authlib OAuth integration at app level
    from authlib.integrations.flask_client import OAuth
    oauth = OAuth(app)
    app.extensions["oauth"] = oauth

    # Security headers
    @app.after_request
    def add_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

    # Health check
    @app.route("/api/health")
    @app.route("/health")
    @app.route("/")
    def health():
        return jsonify({"status": "ok", "service": "qonnect"})

    # Global error handlers
    @app.errorhandler(404)
    def not_found(e):
        return jsonify({
            "error": "Not found",
            "requested_path": request.path,
            "path_info": request.environ.get("PATH_INFO"),
            "raw_uri": request.environ.get("REQUEST_URI") or request.environ.get("RAW_URI"),
        }), 404

    @app.errorhandler(Exception)
    def handle_exception(e):
        import traceback
        app.logger.error(f"Unhandled Exception: {e}")
        return jsonify({
            "error": "Internal Server Error",
            "exception_type": type(e).__name__,
            "message": str(e),
            "traceback": traceback.format_exc()
        }), 500

    @app.errorhandler(429)
    def rate_limit_exceeded(e):
        return jsonify({"error": "Too many requests. Please slow down."}), 429

    return app


def _configure_logging(app: Flask) -> None:
    """Set up application logging."""
    level = logging.DEBUG if app.config.get("DEBUG") else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Never log sensitive data
    logging.getLogger("googleapiclient.discovery").setLevel(logging.WARNING)
    logging.getLogger("google.auth").setLevel(logging.WARNING)
