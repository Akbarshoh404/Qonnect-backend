"""
Qonnect Configuration
"""
import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # Flask
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-in-production")
    DEBUG = os.environ.get("FLASK_DEBUG", "false").lower() == "true"

    # Database
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///qonnect.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # CORS — frontend origin (used for CORS + OAuth redirects)
    FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:5173")

    # Google OAuth
    GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    GOOGLE_REDIRECT_URI = os.environ.get(
        "GOOGLE_REDIRECT_URI", "http://localhost:5173/api/auth/callback"
    )

    # App
    APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:5173")
    DEFAULT_DOMAIN = os.environ.get("DEFAULT_DOMAIN", "localhost:5173")

    # Storage
    MAX_FILE_SIZE = int(os.environ.get("MAX_FILE_SIZE", str(50 * 1024 * 1024)))  # 50MB
    ALLOWED_MIME_TYPES = [
        # Documents
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-powerpoint",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "text/plain",
        "text/csv",
        # Images
        "image/jpeg",
        "image/png",
        "image/gif",
        "image/webp",
        "image/svg+xml",
        # Archives
        "application/zip",
        "application/x-rar-compressed",
        "application/x-7z-compressed",
        # Audio/Video
        "audio/mpeg",
        "audio/wav",
        "video/mp4",
        "video/quicktime",
    ]

    # Security — defaults for dev; production overrides below
    SESSION_COOKIE_SECURE = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = 86400 * 30  # 30 days

    # Encryption key for OAuth tokens (Fernet key, 32 bytes base64)
    ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY", "")

    # Rate limiting
    RATELIMIT_DEFAULT = "200 per day;50 per hour"
    RATELIMIT_STORAGE_URL = "memory://"

    # GeoIP
    GEOIP_DB_PATH = os.environ.get("GEOIP_DB_PATH", "")

    # Analytics retention (days)
    ANALYTICS_RETENTION_DAYS = int(os.environ.get("ANALYTICS_RETENTION_DAYS", "365"))

    # Admin dashboard secret
    ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "")


class DevelopmentConfig(Config):
    DEBUG = True
    SESSION_COOKIE_SECURE = False
    SESSION_COOKIE_SAMESITE = "Lax"


class ProductionConfig(Config):
    DEBUG = False
    # Cross-origin cookies: frontend (qonnect.akbarshoh-dev.uz) ≠ backend (qonnect-api.akbarshoh-dev.uz)
    # Must use SameSite=None + Secure so the browser sends the session cookie cross-origin
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_SAMESITE = "None"


config = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "default": DevelopmentConfig,
}
