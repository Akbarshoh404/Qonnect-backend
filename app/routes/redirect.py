"""
Public redirect route - the core QR resolution engine.
Supports branded inactive/404 pages and portfolio attribution.
"""
import logging
from datetime import datetime, timezone
from flask import Blueprint, request, redirect, render_template_string, current_app, Response, jsonify

from app.extensions import db, limiter
from app.models import QrLink, CustomDomain, ScanEvent
from app.storage import google_drive_provider
from app.utils.geo import get_location, hash_ip
from app.utils.device import parse_user_agent

logger = logging.getLogger(__name__)
redirect_bp = Blueprint("redirect", __name__)

# Luxury Apple-minimalist template for inactive/404 pages with custom branding support
_BRANDED_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ title }} — Qonnect</title>
    <meta name="robots" content="noindex, nofollow">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Segoe UI', system-ui, sans-serif;
            background: #090c14;
            color: #f1f5f9;
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
            padding: 1.5rem;
            position: relative;
            overflow-x: hidden;
        }
        .glow {
            position: absolute;
            width: 450px;
            height: 450px;
            border-radius: 50%;
            background: radial-gradient(circle, rgba(99, 102, 241, 0.15), transparent 70%);
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            z-index: 0;
            pointer-events: none;
        }
        .card {
            background: rgba(18, 24, 38, 0.85);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 28px;
            padding: 3rem 2rem;
            text-align: center;
            max-width: 460px;
            width: 100%;
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
            position: relative;
            z-index: 1;
        }
        .logo-img {
            max-height: 56px;
            margin: 0 auto 1.5rem;
            display: block;
            border-radius: 12px;
        }
        .icon-badge {
            width: 56px;
            height: 56px;
            border-radius: 18px;
            background: rgba(99, 102, 241, 0.12);
            color: #818cf8;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.5rem;
            margin: 0 auto 1.5rem;
            border: 1px solid rgba(99, 102, 241, 0.25);
        }
        h1 {
            font-size: 1.5rem;
            font-weight: 700;
            letter-spacing: -0.02em;
            margin-bottom: 0.75rem;
            color: #ffffff;
        }
        p {
            color: #94a3b8;
            font-size: 0.95rem;
            line-height: 1.6;
            margin-bottom: 1.75rem;
        }
        .btn {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 0.5rem;
            padding: 0.75rem 1.5rem;
            border-radius: 14px;
            font-size: 0.875rem;
            font-weight: 600;
            background: #ffffff;
            color: #0f172a;
            text-decoration: none;
            transition: all 0.2s ease;
            box-shadow: 0 4px 14px rgba(0, 0, 0, 0.2);
        }
        .btn:hover {
            background: #f1f5f9;
            transform: translateY(-1px);
        }
        .footer-brand {
            margin-top: 2.25rem;
            padding-top: 1.5rem;
            border-top: 1px solid rgba(255, 255, 255, 0.05);
            font-size: 0.8rem;
            color: #64748b;
        }
        .footer-brand a {
            color: #818cf8;
            text-decoration: none;
            font-weight: 500;
        }
        .footer-brand a:hover {
            text-decoration: underline;
        }
    </style>
</head>
<body>
    <div class="glow"></div>
    <div class="card">
        {% if logo_url %}
            <img src="{{ logo_url }}" alt="Logo" class="logo-img">
        {% else %}
            <div class="icon-badge">🔗</div>
        {% endif %}

        <h1>{{ title }}</h1>
        <p>{{ message }}</p>

        {% if support_url %}
            <a href="{{ support_url }}" class="btn" target="_blank" rel="noopener">
                {{ support_label or "Contact Support" }} →
            </a>
        {% endif %}

        <div class="footer-brand">
            Powered by <strong>Qonnect</strong> · Made with ❤️ by <a href="https://akbarshoh-dev.uz" target="_blank" rel="noopener">Akbarshoh</a>
        </div>
    </div>
</body>
</html>"""


def _render_fallback_page(title: str, message: str, inactive_config: dict = None, status_code: int = 404):
    inactive_config = inactive_config or {}
    custom_title = inactive_config.get("title") or title
    custom_message = inactive_config.get("message") or message
    logo_url = inactive_config.get("logo_url")
    support_url = inactive_config.get("support_url")
    support_label = inactive_config.get("support_label")

    page = render_template_string(
        _BRANDED_PAGE,
        title=custom_title,
        message=custom_message,
        logo_url=logo_url,
        support_url=support_url,
        support_label=support_label,
    )
    return Response(
        page,
        status=status_code,
        headers={"X-Robots-Tag": "noindex, nofollow"},
        content_type="text/html",
    )


def _record_scan(qr_link_id: int) -> None:
    """Record a scan event."""
    try:
        ip = request.headers.get("X-Forwarded-For", request.remote_addr or "")
        if "," in ip:
            ip = ip.split(",")[0].strip()

        ua_string = request.headers.get("User-Agent", "")
        device_info = parse_user_agent(ua_string)
        location = get_location(ip)
        ip_hashed = hash_ip(ip)

        event = ScanEvent(
            qr_link_id=qr_link_id,
            timestamp=datetime.now(timezone.utc),
            ip_hash=ip_hashed,
            country=location.get("country"),
            country_code=location.get("country_code"),
            city=location.get("city"),
            user_agent=ua_string[:500] if ua_string else None,
            device_type=device_info.get("device_type"),
            browser=device_info.get("browser"),
            os=device_info.get("os"),
            referrer=request.referrer[:500] if request.referrer else None,
        )
        db.session.add(event)
        db.session.commit()
    except Exception as e:
        logger.warning(f"Failed to record scan: {e}")
        db.session.rollback()


@redirect_bp.route("/q/<short_code>")
@limiter.limit("120 per minute")
def resolve_qr(short_code: str):
    """The core dynamic QR redirect endpoint."""
    qr_link = QrLink.query.filter_by(short_code=short_code).first()

    if not qr_link:
        return _render_fallback_page(
            title="Link Not Found",
            message="This Qonnect link doesn't exist or may have been removed.",
            status_code=404,
        )

    if not qr_link.is_active:
        return _render_fallback_page(
            title="Link Temporarily Unavailable",
            message="The owner has paused this QR code. Please check back later.",
            inactive_config=qr_link.inactive_config,
            status_code=410,
        )

    # Record scan
    _record_scan(qr_link.id)

    if qr_link.type == "url":
        return redirect(qr_link.destination_url, 302)

    elif qr_link.type == "file":
        try:
            import io
            file_content = google_drive_provider.get_file_content(
                qr_link.user, qr_link.google_drive_file_id
            )
            if file_content is None:
                return _render_fallback_page(
                    title="File Unavailable",
                    message="The file behind this QR code could not be retrieved from Google Drive.",
                    inactive_config=qr_link.inactive_config,
                    status_code=503,
                )

            from flask import send_file
            return send_file(
                io.BytesIO(file_content),
                mimetype=qr_link.mime_type or "application/octet-stream",
                as_attachment=True,
                download_name=qr_link.original_filename or "file",
            )
        except Exception as e:
            logger.error(f"File serve failed for {short_code}: {e}")
            return _render_fallback_page(
                title="File Unavailable",
                message="The file could not be retrieved. Please try again later.",
                inactive_config=qr_link.inactive_config,
                status_code=503,
            )


@redirect_bp.route("/<short_code>")
@limiter.limit("120 per minute")
def resolve_custom_domain_qr(short_code: str):
    """Handle custom domain QR resolution (e.g. qr.brand.com/xK9z)."""
    if request.path.startswith("/api") or short_code in ("api", "health", "favicon.ico", "robots.txt", "dashboard", "login", "create", "settings", "admin", "q"):
        return jsonify({"error": "Not found"}), 404

    host = request.host.split(":")[0]
    default_domain = current_app.config.get("DEFAULT_DOMAIN", "")

    if host in (default_domain, "qonnect-api.akbarshoh-dev.uz", "qonnect.akbarshoh-dev.uz", "localhost", "127.0.0.1"):
        return jsonify({"error": "Not found"}), 404

    domain = CustomDomain.query.filter_by(domain=host, verified=True).first()
    if not domain:
        return _render_fallback_page(
            title="Domain Not Verified",
            message="This custom domain is not registered or verified in Qonnect.",
            status_code=404,
        )

    qr_link = QrLink.query.filter_by(short_code=short_code, custom_domain_id=domain.id).first()
    if not qr_link:
        return _render_fallback_page(
            title="Link Not Found",
            message="This QR code link does not exist on this domain.",
            status_code=404,
        )

    if not qr_link.is_active:
        return _render_fallback_page(
            title="Link Temporarily Unavailable",
            message="This QR code is currently paused by the owner.",
            inactive_config=qr_link.inactive_config,
            status_code=410,
        )

    _record_scan(qr_link.id)

    if qr_link.type == "url":
        return redirect(qr_link.destination_url, 302)
    else:
        return redirect(f"/q/{short_code}", 302)
