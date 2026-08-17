"""
Analytics routes - scan statistics per QR code
"""
import logging
from datetime import datetime, timezone, timedelta
from collections import Counter

from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from sqlalchemy import func

from app.extensions import db, limiter
from app.models import QrLink, ScanEvent

logger = logging.getLogger(__name__)
analytics_bp = Blueprint("analytics", __name__, url_prefix="/api/qr")


def _get_period_start(period: str) -> datetime:
    """Return the start datetime for a given period string."""
    now = datetime.now(timezone.utc)
    periods = {
        "7d": timedelta(days=7),
        "30d": timedelta(days=30),
        "90d": timedelta(days=90),
        "1y": timedelta(days=365),
        "all": timedelta(days=36500),
    }
    delta = periods.get(period, timedelta(days=30))
    return now - delta


@analytics_bp.route("/<int:qr_id>/analytics", methods=["GET"])
@login_required
def get_analytics(qr_id: int):
    """Get analytics data for a specific QR code."""
    qr_link = QrLink.query.filter_by(id=qr_id, user_id=current_user.id).first_or_404()

    period = request.args.get("period", "30d")
    period_start = _get_period_start(period)

    # Base query scoped to this QR and period
    base_q = ScanEvent.query.filter(
        ScanEvent.qr_link_id == qr_link.id,
        ScanEvent.timestamp >= period_start,
    )

    total_scans = base_q.count()

    # Approximate unique visitors by distinct ip_hash
    unique_approx = db.session.query(
        func.count(func.distinct(ScanEvent.ip_hash))
    ).filter(
        ScanEvent.qr_link_id == qr_link.id,
        ScanEvent.timestamp >= period_start,
        ScanEvent.ip_hash.isnot(None),
    ).scalar() or 0

    # Today's scans
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    scans_today = ScanEvent.query.filter(
        ScanEvent.qr_link_id == qr_link.id,
        ScanEvent.timestamp >= today_start,
    ).count()

    # This week
    week_start = datetime.now(timezone.utc) - timedelta(days=7)
    scans_week = ScanEvent.query.filter(
        ScanEvent.qr_link_id == qr_link.id,
        ScanEvent.timestamp >= week_start,
    ).count()

    # This month
    month_start = datetime.now(timezone.utc) - timedelta(days=30)
    scans_month = ScanEvent.query.filter(
        ScanEvent.qr_link_id == qr_link.id,
        ScanEvent.timestamp >= month_start,
    ).count()

    # Scans over time (daily aggregation)
    daily_scans = db.session.query(
        func.date(ScanEvent.timestamp).label("date"),
        func.count(ScanEvent.id).label("count"),
    ).filter(
        ScanEvent.qr_link_id == qr_link.id,
        ScanEvent.timestamp >= period_start,
    ).group_by(func.date(ScanEvent.timestamp)).order_by("date").all()

    # Country breakdown
    country_data = db.session.query(
        ScanEvent.country,
        func.count(ScanEvent.id).label("count"),
    ).filter(
        ScanEvent.qr_link_id == qr_link.id,
        ScanEvent.timestamp >= period_start,
        ScanEvent.country.isnot(None),
    ).group_by(ScanEvent.country).order_by(func.count(ScanEvent.id).desc()).limit(10).all()

    # City breakdown
    city_data = db.session.query(
        ScanEvent.city,
        func.count(ScanEvent.id).label("count"),
    ).filter(
        ScanEvent.qr_link_id == qr_link.id,
        ScanEvent.timestamp >= period_start,
        ScanEvent.city.isnot(None),
    ).group_by(ScanEvent.city).order_by(func.count(ScanEvent.id).desc()).limit(10).all()

    # Device type
    device_data = db.session.query(
        ScanEvent.device_type,
        func.count(ScanEvent.id).label("count"),
    ).filter(
        ScanEvent.qr_link_id == qr_link.id,
        ScanEvent.timestamp >= period_start,
        ScanEvent.device_type.isnot(None),
    ).group_by(ScanEvent.device_type).order_by(func.count(ScanEvent.id).desc()).all()

    # Browser
    browser_data = db.session.query(
        ScanEvent.browser,
        func.count(ScanEvent.id).label("count"),
    ).filter(
        ScanEvent.qr_link_id == qr_link.id,
        ScanEvent.timestamp >= period_start,
        ScanEvent.browser.isnot(None),
    ).group_by(ScanEvent.browser).order_by(func.count(ScanEvent.id).desc()).limit(8).all()

    # OS
    os_data = db.session.query(
        ScanEvent.os,
        func.count(ScanEvent.id).label("count"),
    ).filter(
        ScanEvent.qr_link_id == qr_link.id,
        ScanEvent.timestamp >= period_start,
        ScanEvent.os.isnot(None),
    ).group_by(ScanEvent.os).order_by(func.count(ScanEvent.id).desc()).limit(8).all()

    return jsonify({
        "qr_id": qr_link.id,
        "period": period,
        "summary": {
            "total_scans": total_scans,
            "unique_approx": unique_approx,
            "scans_today": scans_today,
            "scans_week": scans_week,
            "scans_month": scans_month,
        },
        "scans_over_time": [
            {"date": str(row.date), "count": row.count}
            for row in daily_scans
        ],
        "by_country": [
            {"country": row.country or "Unknown", "count": row.count}
            for row in country_data
        ],
        "by_city": [
            {"city": row.city or "Unknown", "count": row.count}
            for row in city_data
        ],
        "by_device": [
            {"device": row.device_type or "unknown", "count": row.count}
            for row in device_data
        ],
        "by_browser": [
            {"browser": row.browser or "Unknown", "count": row.count}
            for row in browser_data
        ],
        "by_os": [
            {"os": row.os or "Unknown", "count": row.count}
            for row in os_data
        ],
    })
