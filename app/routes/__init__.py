"""
Routes package
"""
from .auth import auth_bp
from .qr import qr_bp
from .redirect import redirect_bp
from .analytics import analytics_bp
from .domains import domains_bp
from .drive import drive_bp
from .admin import admin_bp

__all__ = ["auth_bp", "qr_bp", "redirect_bp", "analytics_bp", "domains_bp", "drive_bp", "admin_bp"]
