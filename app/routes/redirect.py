"""
Public redirect route - the core QR resolution engine.
This is the most performance-critical endpoint.
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

# Minimal page shown when QR is disabled or not found
_DISABLED_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Link Unavailable — Qonnect</title>
    <meta name="robots" content="noindex, nofollow">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
               background: #0f0f13; color: #e2e8f0; display: flex;
               align-items: center; justify-content: center;
               min-height: 100vh; padding: 1rem; }
        .card { background: #1a1a2e; border: 1px solid #2d2d3d; border-radius: 16px;
                padding: 3rem 2rem; text-align: center; max-width: 420px; width: 100%; }
        .icon { font-size: 3rem; margin-bottom: 1.5rem; }
        h1 { font-size: 1.5rem; font-weight: 700; margin-bottom: 0.75rem; color: #f1f5f9; }
        p { color: #94a3b8; font-size: 1rem; line-height: 1.6; }
        .brand { margin-top: 2rem; font-size: 0.875rem; color: #4a5568; }
        .brand strong { color: #6366f1; }
    </style>
</head>
<body>
    <div class="card">
        <div class="icon">🔗</div>
        <h1>{{ title }}</h1>
        <p>{{ message }}</p>
        <div class="brand">Powered by <strong>Qonnect</strong></div>
    </div>
</body>
</html>"""


def _record_scan(qr_link_id: int) -> None:
    """Record a scan event. Runs in the same request for simplicity."""
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


def _resolve_qr_by_host_and_code(short_code: str) -> QrLink | None:
    """
    Resolve a QR link by considering the request hostname.
    Supports both default domain and custom domains.
    """
    host = request.host.split(":")[0]  # strip port

    # Check if this is a custom domain request
    domain = CustomDomain.query.filter_by(domain=host, verified=True).first()

    if domain:
        # Custom domain: find QR for this user's domain with this short code
        return QrLink.query.filter_by(
            short_code=short_code,
            custom_domain_id=domain.id,
        ).first()
    else:
        # Default domain: any QR with this short code
        return QrLink.query.filter_by(short_code=short_code).first()


@redirect_bp.route("/q/<short_code>")
@limiter.limit("120 per minute")
def resolve_qr(short_code: str):
    """
    The core dynamic QR redirect endpoint.
    Resolves a short code to its current destination and redirects.
    """
    # Add SEO robots header
    response_headers = {"X-Robots-Tag": "noindex, nofollow"}

    qr_link = QrLink.query.filter_by(short_code=short_code).first()

    if not qr_link:
        page = render_template_string(
            _DISABLED_PAGE,
            title="Link Not Found",
            message="This Qonnect link doesn't exist or may have been removed.",
        )
        return Response(page, status=404, headers=response_headers, content_type="text/html")

    if not qr_link.is_active:
        page = render_template_string(
            _DISABLED_PAGE,
            title="Link Unavailable",
            message="This Qonnect link is currently disabled.",
        )
        return Response(page, status=410, headers=response_headers, content_type="text/html")

    # Record scan (don't let analytics failure affect the redirect)
    _record_scan(qr_link.id)

    if qr_link.type == "url":
        return redirect(qr_link.destination_url, 302)

    elif qr_link.type == "file":
        # Serve the file through backend proxy (hides Drive URL)
        try:
            import io
            file_content = google_drive_provider.get_file_content(
                qr_link.user, qr_link.google_drive_file_id
            )
            if file_content is None:
                page = render_template_string(
                    _DISABLED_PAGE,
                    title="File Unavailable",
                    message="The file behind this QR code couldn't be retrieved. The owner may need to reconnect their Google Drive.",
                )
                return Response(page, status=503, headers=response_headers, content_type="text/html")

            from flask import send_file
            return send_file(
                io.BytesIO(file_content),
                mimetype=qr_link.mime_type or "application/octet-stream",
                as_attachment=True,
                download_name=qr_link.original_filename or "file",
            )
        except Exception as e:
            logger.error(f"File serve failed for {short_code}: {e}")
            page = render_template_string(
                _DISABLED_PAGE,
                title="File Unavailable",
                message="The file couldn't be retrieved. Please try again later.",
            )
            return Response(page, status=503, headers=response_headers, content_type="text/html")


@redirect_bp.route("/<short_code>")
@limiter.limit("120 per minute")
def resolve_custom_domain_qr(short_code: str):
    """
    Handle custom domain QR resolution.
    E.g. files.example.com/Ab82kL → resolves based on hostname.
    """
    host = request.host.split(":")[0]
    response_headers = {"X-Robots-Tag": "noindex, nofollow"}

    # Ignore system reserved words and routes
    if short_code in ("api", "health", "favicon.ico", "robots.txt", "dashboard", "login", "create", "settings", "admin", "q"):
        return jsonify({"error": "Not found"}), 404

    # Only handle custom domain requests here (not the default domain or api domain)
    default_domain = current_app.config.get("DEFAULT_DOMAIN", "")
    if host in (default_domain, "qonnect-api.akbarshoh-dev.uz", "qonnect.akbarshoh-dev.uz", "localhost", "127.0.0.1"):
        return jsonify({"error": "Not found"}), 404

    domain = CustomDomain.query.filter_by(domain=host, verified=True).first()
    if not domain:
        page = render_template_string(
            _DISABLED_PAGE,
            title="Domain Not Found",
            message="This domain is not configured with Qonnect.",
        )
        return Response(page, status=404, headers=response_headers, content_type="text/html")

    qr_link = QrLink.query.filter_by(
        short_code=short_code,
        custom_domain_id=domain.id,
    ).first()

    if not qr_link:
        page = render_template_string(
            _DISABLED_PAGE,
            title="Link Not Found",
            message="This Qonnect link doesn't exist.",
        )
        return Response(page, status=404, headers=response_headers, content_type="text/html")

    if not qr_link.is_active:
        page = render_template_string(
            _DISABLED_PAGE,
            title="Link Unavailable",
            message="This Qonnect link is currently disabled.",
        )
        return Response(page, status=410, headers=response_headers, content_type="text/html")

    _record_scan(qr_link.id)

    if qr_link.type == "url":
        return redirect(qr_link.destination_url, 302)
    else:
        # File: forward to standard file serve endpoint
        return redirect(f"/q/{short_code}", 302)
