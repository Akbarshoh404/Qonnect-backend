"""
Admin routes - system overview dashboard
Only accessible with ADMIN_SECRET header.
"""
import logging
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import Blueprint, request, jsonify, current_app
from sqlalchemy import func

from app.extensions import db
from app.models import User, QrLink, ScanEvent, CustomDomain

logger = logging.getLogger(__name__)
admin_bp = Blueprint("admin", __name__, url_prefix="/api/admin")


def require_admin(f):
    """Token-based admin auth. Set ADMIN_SECRET in .env."""
    @wraps(f)
    def decorated(*args, **kwargs):
        secret = current_app.config.get("ADMIN_SECRET", "")
        if not secret:
            return jsonify({"error": "Admin access not configured"}), 403
        token = request.headers.get("X-Admin-Secret") or request.args.get("admin_secret")
        if token != secret:
            return jsonify({"error": "Forbidden"}), 403
        return f(*args, **kwargs)
    return decorated


@admin_bp.route("/stats")
@require_admin
def stats():
    """System-wide statistics."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)  # offset-naive for SQLite
    day_ago = now - timedelta(days=1)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)

    total_users = User.query.count()
    total_qr = QrLink.query.count()
    total_scans = ScanEvent.query.count()
    active_qr = QrLink.query.filter_by(is_active=True).count()

    new_users_today = User.query.filter(User.created_at >= day_ago).count()
    new_users_week = User.query.filter(User.created_at >= week_ago).count()
    scans_today = ScanEvent.query.filter(ScanEvent.timestamp >= day_ago).count()
    scans_week = ScanEvent.query.filter(ScanEvent.timestamp >= week_ago).count()
    scans_month = ScanEvent.query.filter(ScanEvent.timestamp >= month_ago).count()

    url_qr = QrLink.query.filter_by(type="url").count()
    file_qr = QrLink.query.filter_by(type="file").count()
    verified_domains = CustomDomain.query.filter_by(verified=True).count()

    return jsonify({
        "users": {
            "total": total_users,
            "new_today": new_users_today,
            "new_this_week": new_users_week,
        },
        "qr_codes": {
            "total": total_qr,
            "active": active_qr,
            "inactive": total_qr - active_qr,
            "url_type": url_qr,
            "file_type": file_qr,
        },
        "scans": {
            "total": total_scans,
            "today": scans_today,
            "this_week": scans_week,
            "this_month": scans_month,
        },
        "domains": {
            "verified": verified_domains,
        },
    })


@admin_bp.route("/users")
@require_admin
def list_users():
    """List all users with QR code counts."""
    users = (
        db.session.query(User, func.count(QrLink.id).label("qr_count"))
        .outerjoin(QrLink, User.id == QrLink.user_id)
        .group_by(User.id)
        .order_by(User.created_at.desc())
        .all()
    )
    return jsonify({
        "users": [
            {
                "id": u.id,
                "email": u.email,
                "name": u.name,
                "avatar_url": u.avatar_url,
                "drive_connected": bool(u.google_tokens_encrypted),
                "drive_folder_id": u.drive_folder_id,
                "qr_count": qr_count,
                "created_at": u.created_at.isoformat(),
            }
            for u, qr_count in users
        ]
    })


@admin_bp.route("/qr-codes")
@require_admin
def list_qr_codes():
    """List all QR codes across all users."""
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 50))

    query = (
        db.session.query(QrLink, User.email)
        .join(User, QrLink.user_id == User.id)
        .order_by(QrLink.created_at.desc())
    )

    total = query.count()
    items = query.offset((page - 1) * per_page).limit(per_page).all()
    base_url = current_app.config["APP_BASE_URL"]

    return jsonify({
        "qr_codes": [
            {**qr.to_dict(base_url=base_url), "owner_email": email}
            for qr, email in items
        ],
        "total": total,
        "page": page,
        "pages": (total + per_page - 1) // per_page,
    })


@admin_bp.route("/scans/recent")
@require_admin
def recent_scans():
    """Last 100 scan events."""
    scans = (
        db.session.query(ScanEvent, QrLink.short_code, QrLink.title)
        .join(QrLink, ScanEvent.qr_link_id == QrLink.id)
        .order_by(ScanEvent.timestamp.desc())
        .limit(100)
        .all()
    )
    return jsonify({
        "scans": [
            {
                "id": s.id,
                "short_code": code,
                "qr_title": title,
                "country": s.country,
                "device": s.device_type,
                "browser": s.browser,
                "scanned_at": s.timestamp.isoformat(),
            }
            for s, code, title in scans
        ]
    })
