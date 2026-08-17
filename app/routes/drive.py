"""
Google Drive status routes
"""
import logging
from flask import Blueprint, jsonify
from flask_login import login_required, current_user

from app.storage import google_drive_provider

logger = logging.getLogger(__name__)
drive_bp = Blueprint("drive", __name__, url_prefix="/api/drive")


@drive_bp.route("/status", methods=["GET"])
@login_required
def drive_status():
    """Get the current user's Google Drive connection status."""
    connected = google_drive_provider.is_connected(current_user)
    return jsonify({
        "connected": connected,
        "drive_folder_id": (
            current_user.drive_folder_id
            if connected and current_user.drive_folder_id not in (None, "pending", "")
            else None
        ),
    })


@drive_bp.route("/disconnect", methods=["POST"])
@login_required
def disconnect_drive():
    """Disconnect Google Drive (removes stored tokens)."""
    from app.extensions import db

    current_user.google_tokens_encrypted = None
    current_user.drive_folder_id = None
    db.session.commit()

    logger.info(f"Drive disconnected for user {current_user.id}")
    return jsonify({"message": "Google Drive disconnected"})
