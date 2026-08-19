"""
QR Code routes - CRUD, Bulk Operations & Styling for QR links
"""
import io
import csv
import zipfile
import logging
from flask import Blueprint, request, jsonify, send_file, current_app
from flask_login import login_required, current_user
from sqlalchemy import func

from app.extensions import db, limiter
from app.models import QrLink, CustomDomain, ScanEvent
from app.storage import google_drive_provider
from app.utils.short_code import generate_unique_short_code
from app.utils.validators import validate_destination_url, sanitize_filename
import segno

logger = logging.getLogger(__name__)
qr_bp = Blueprint("qr", __name__, url_prefix="/api/qr")


def _check_short_code_exists(code: str) -> bool:
    return QrLink.query.filter_by(short_code=code).first() is not None


def _generate_qr_image(url: str, fmt: str = "png", scale: int = 10, style: dict = None) -> bytes:
    """
    Generate a QR code image for the given URL with optional custom style.
    Supports dark/light colors and error correction level H.
    """
    style = style or {}
    dark_color = style.get("fg_color") or style.get("dark") or "#0f172a"
    light_color = style.get("bg_color") or style.get("light") or "#ffffff"

    # Transparent background support
    if style.get("transparent_bg"):
        light_color = None

    qr = segno.make(url, error="H")
    buf = io.BytesIO()

    if fmt == "svg":
        qr.save(buf, kind="svg", scale=scale, border=4, dark=dark_color, light=light_color)
    else:
        qr.save(buf, kind="png", scale=scale, border=4, dark=dark_color, light=light_color)

    buf.seek(0)
    return buf.read()


@qr_bp.route("/projects", methods=["GET"])
@login_required
def get_projects_and_tags():
    """Get all distinct projects/folders and tags for the current user."""
    projects_query = (
        db.session.query(QrLink.project_name, func.count(QrLink.id))
        .filter(QrLink.user_id == current_user.id, QrLink.project_name.isnot(None), QrLink.project_name != "")
        .group_by(QrLink.project_name)
        .all()
    )

    projects = [{"name": p[0], "count": p[1]} for p in projects_query]

    # Collect all unique tags
    links_with_tags = QrLink.query.filter(
        QrLink.user_id == current_user.id, QrLink.tags.isnot(None)
    ).all()
    tags_count = {}
    for link in links_with_tags:
        if isinstance(link.tags, list):
            for tag in link.tags:
                tag = str(tag).strip()
                if tag:
                    tags_count[tag] = tags_count.get(tag, 0) + 1

    tags = [{"name": k, "count": v} for k, v in sorted(tags_count.items())]

    return jsonify({"projects": projects, "tags": tags})


@qr_bp.route("", methods=["GET"])
@login_required
def list_qr_codes():
    """List all QR codes for the current user with search, filter, and pagination."""
    search = request.args.get("search", "").strip()
    qr_type = request.args.get("type", "").strip()
    project = request.args.get("project", "").strip()
    tag = request.args.get("tag", "").strip()
    sort = request.args.get("sort", "newest")  # newest, oldest, most_scanned
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 20))

    query = QrLink.query.filter_by(user_id=current_user.id)

    if search:
        query = query.filter(QrLink.title.ilike(f"%{search}%"))

    if qr_type in ("url", "file"):
        query = query.filter_by(type=qr_type)

    if project:
        query = query.filter_by(project_name=project)

    if tag:
        # JSON search or fallback
        query = query.filter(QrLink.tags.cast(db.String).ilike(f"%{tag}%"))

    if sort == "oldest":
        query = query.order_by(QrLink.created_at.asc())
    elif sort == "most_scanned":
        query = (
            query.outerjoin(ScanEvent, QrLink.id == ScanEvent.qr_link_id)
            .group_by(QrLink.id)
            .order_by(func.count(ScanEvent.id).desc())
        )
    else:
        query = query.order_by(QrLink.created_at.desc())

    # Paginate
    total = query.count()
    items = query.offset((page - 1) * per_page).limit(per_page).all()

    base_url = current_app.config["APP_BASE_URL"]
    return jsonify({
        "qr_codes": [qr.to_dict(base_url=base_url) for qr in items],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
    })


@qr_bp.route("", methods=["POST"])
@login_required
@limiter.limit("60 per hour")
def create_qr():
    """Create a new QR code (URL or file) with optional design studio styles & project."""
    base_url = current_app.config["APP_BASE_URL"]
    body = request.get_json(silent=True) or {}

    def get(key, default=None):
        return request.form.get(key) if request.form.get(key) is not None else body.get(key, default)

    qr_type = get("type")
    if qr_type not in ("url", "file"):
        return jsonify({"error": "Type must be 'url' or 'file'"}), 400

    title = (get("title") or "").strip()
    if not title:
        return jsonify({"error": "Title is required"}), 400
    if len(title) > 255:
        return jsonify({"error": "Title is too long (max 255 characters)"}), 400

    project_name = (get("project_name") or "").strip() or None
    tags = get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]

    style_config = get("style_config")
    inactive_config = get("inactive_config")

    # Custom domain
    custom_domain_id = get("custom_domain_id")
    custom_domain = None
    if custom_domain_id:
        custom_domain = CustomDomain.query.filter_by(
            id=custom_domain_id, user_id=current_user.id, verified=True
        ).first()
        if not custom_domain:
            return jsonify({"error": "Domain not found or not verified"}), 400

    # Generate unique short code
    short_code = generate_unique_short_code(_check_short_code_exists)

    if qr_type == "url":
        destination_url = (get("destination_url") or "").strip()
        valid, err = validate_destination_url(destination_url)
        if not valid:
            return jsonify({"error": err}), 400

        qr_link = QrLink(
            user_id=current_user.id,
            short_code=short_code,
            type="url",
            title=title,
            project_name=project_name,
            tags=tags,
            style_config=style_config,
            inactive_config=inactive_config,
            destination_url=destination_url,
            custom_domain_id=custom_domain.id if custom_domain else None,
        )
        db.session.add(qr_link)
        db.session.commit()

        logger.info(f"Created URL QR {short_code} for user {current_user.id}")
        return jsonify({"qr_code": qr_link.to_dict(base_url=base_url)}), 201

    elif qr_type == "file":
        if not google_drive_provider.is_connected(current_user):
            return jsonify({"error": "Google Drive not connected. Please connect Drive first."}), 400

        if "file" not in request.files:
            return jsonify({"error": "No file provided"}), 400

        file = request.files["file"]
        if not file.filename:
            return jsonify({"error": "No file selected"}), 400

        # Validate file
        max_size = current_app.config["MAX_FILE_SIZE"]
        allowed_mimes = current_app.config["ALLOWED_MIME_TYPES"]

        file_data = file.read()
        if len(file_data) > max_size:
            return jsonify({"error": f"File too large. Maximum size is {max_size // (1024*1024)}MB"}), 400

        mime_type = file.content_type or "application/octet-stream"
        if mime_type not in allowed_mimes:
            return jsonify({"error": f"File type '{mime_type}' is not allowed"}), 400

        safe_filename = sanitize_filename(file.filename)

        qr_link = QrLink(
            user_id=current_user.id,
            short_code=short_code,
            type="file",
            title=title,
            project_name=project_name,
            tags=tags,
            style_config=style_config,
            inactive_config=inactive_config,
            original_filename=safe_filename,
            mime_type=mime_type,
            file_size=len(file_data),
            custom_domain_id=custom_domain.id if custom_domain else None,
        )
        db.session.add(qr_link)
        db.session.flush()

        try:
            folder_id = google_drive_provider.create_qr_folder(current_user, short_code)
            result = google_drive_provider.upload_file(
                user=current_user,
                folder_id=folder_id,
                file_data=io.BytesIO(file_data),
                filename=safe_filename,
                mime_type=mime_type,
            )
            qr_link.google_drive_file_id = result["file_id"]
            qr_link.google_drive_folder_id = folder_id
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.error(f"Drive upload failed: {e}")
            return jsonify({"error": "Failed to upload file to Google Drive. Please try again."}), 500

        logger.info(f"Created file QR {short_code} for user {current_user.id}")
        return jsonify({"qr_code": qr_link.to_dict(base_url=base_url)}), 201


@qr_bp.route("/bulk", methods=["POST"])
@login_required
@limiter.limit("20 per hour")
def bulk_create_qr():
    """
    Bulk create QR codes from CSV or JSON array.
    Expected items: [{"title": "...", "destination_url": "...", "project_name": "...", "tags": [...]}]
    """
    base_url = current_app.config["APP_BASE_URL"]
    items = []

    if "file" in request.files:
        csv_file = request.files["file"]
        stream = io.StringIO(csv_file.stream.read().decode("utf-8", errors="ignore"))
        reader = csv.DictReader(stream)
        for row in reader:
            title = row.get("title") or row.get("Title") or row.get("name") or row.get("Name")
            url = row.get("url") or row.get("URL") or row.get("destination_url") or row.get("link")
            project = row.get("project") or row.get("project_name") or row.get("folder")
            tags = row.get("tags") or ""
            if title and url:
                items.append({
                    "title": str(title).strip(),
                    "destination_url": str(url).strip(),
                    "project_name": str(project).strip() if project else None,
                    "tags": [t.strip() for t in str(tags).split(",") if t.strip()],
                })
    else:
        body = request.get_json(silent=True) or {}
        items = body.get("items", [])
        project_override = body.get("project_name")
        style_override = body.get("style_config")

    if not items:
        return jsonify({"error": "No valid QR items provided"}), 400

    if len(items) > 100:
        return jsonify({"error": "Maximum 100 QR codes can be created at once"}), 400

    created_links = []
    errors = []

    for i, item in enumerate(items):
        title = item.get("title", f"QR {i+1}").strip()
        destination_url = item.get("destination_url", "").strip()

        valid, err = validate_destination_url(destination_url)
        if not valid:
            errors.append(f"Row {i+1} ({title}): {err}")
            continue

        short_code = generate_unique_short_code(_check_short_code_exists)
        project = item.get("project_name") or request.json.get("project_name") if request.is_json else None
        style = item.get("style_config") or (request.json.get("style_config") if request.is_json else None)

        qr_link = QrLink(
            user_id=current_user.id,
            short_code=short_code,
            type="url",
            title=title,
            project_name=project,
            tags=item.get("tags", []),
            style_config=style,
            destination_url=destination_url,
        )
        db.session.add(qr_link)
        created_links.append(qr_link)

    db.session.commit()
    logger.info(f"Bulk created {len(created_links)} QR codes for user {current_user.id}")

    return jsonify({
        "message": f"Successfully created {len(created_links)} QR codes",
        "qr_codes": [qr.to_dict(base_url=base_url) for qr in created_links],
        "errors": errors,
    }), 201


@qr_bp.route("/bulk/actions", methods=["POST"])
@login_required
def bulk_actions():
    """Perform bulk actions: 'pause', 'resume', 'move_project', 'add_tag', 'delete'."""
    data = request.json or {}
    action = data.get("action")
    ids = data.get("ids", [])

    if not ids or not isinstance(ids, list):
        return jsonify({"error": "IDs array is required"}), 400

    links = QrLink.query.filter(QrLink.id.in_(ids), QrLink.user_id == current_user.id).all()
    if not links:
        return jsonify({"error": "No matching QR codes found"}), 404

    if action == "pause":
        for link in links:
            link.is_active = False
    elif action == "resume":
        for link in links:
            link.is_active = True
    elif action == "move_project":
        project_name = (data.get("project_name") or "").strip() or None
        for link in links:
            link.project_name = project_name
    elif action == "add_tag":
        tag = (data.get("tag") or "").strip()
        if tag:
            for link in links:
                current_tags = list(link.tags or [])
                if tag not in current_tags:
                    current_tags.append(tag)
                    link.tags = current_tags
    elif action == "delete":
        for link in links:
            db.session.delete(link)
    else:
        return jsonify({"error": f"Unknown action '{action}'"}), 400

    db.session.commit()
    return jsonify({"message": f"Bulk action '{action}' completed for {len(links)} QR codes", "count": len(links)})


@qr_bp.route("/bulk/export", methods=["POST"])
@login_required
def bulk_export_zip():
    """Export selected QR codes as a single downloadable ZIP archive containing PNGs or SVGs."""
    data = request.json or {}
    ids = data.get("ids", [])
    fmt = data.get("format", "png").lower()
    size = int(data.get("size", 10))

    if fmt not in ("png", "svg"):
        fmt = "png"

    query = QrLink.query.filter(QrLink.user_id == current_user.id)
    if ids:
        query = query.filter(QrLink.id.in_(ids))

    qr_links = query.all()
    if not qr_links:
        return jsonify({"error": "No QR codes to export"}), 404

    base_url = current_app.config["APP_BASE_URL"]
    zip_buf = io.BytesIO()

    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for qr in qr_links:
            pub_url = qr.get_public_url(base_url)
            img_bytes = _generate_qr_image(pub_url, fmt=fmt, scale=size, style=qr.style_config)
            clean_title = sanitize_filename(qr.title or qr.short_code)
            filename = f"{qr.short_code}-{clean_title}.{fmt}"
            zf.writestr(filename, img_bytes)

    zip_buf.seek(0)
    return send_file(
        zip_buf,
        mimetype="application/zip",
        as_attachment=True,
        download_name="qonnect-qr-export.zip",
    )


@qr_bp.route("/<int:qr_id>", methods=["GET"])
@login_required
def get_qr(qr_id: int):
    """Get a specific QR code."""
    qr_link = QrLink.query.filter_by(id=qr_id, user_id=current_user.id).first_or_404()
    base_url = current_app.config["APP_BASE_URL"]
    return jsonify({"qr_code": qr_link.to_dict(base_url=base_url)})


@qr_bp.route("/<int:qr_id>", methods=["PATCH"])
@login_required
def update_qr(qr_id: int):
    """Update a QR code (title, destination, project, style, inactive page, active status)."""
    qr_link = QrLink.query.filter_by(id=qr_id, user_id=current_user.id).first_or_404()
    base_url = current_app.config["APP_BASE_URL"]
    data = request.json or {}

    if "title" in data:
        title = str(data["title"]).strip()
        if not title:
            return jsonify({"error": "Title cannot be empty"}), 400
        if len(title) > 255:
            return jsonify({"error": "Title too long"}), 400
        qr_link.title = title

    if "project_name" in data:
        qr_link.project_name = str(data["project_name"]).strip() if data["project_name"] else None

    if "tags" in data:
        qr_link.tags = data["tags"] if isinstance(data["tags"], list) else []

    if "style_config" in data:
        qr_link.style_config = data["style_config"]

    if "inactive_config" in data:
        qr_link.inactive_config = data["inactive_config"]

    if "is_active" in data:
        qr_link.is_active = bool(data["is_active"])

    if "destination_url" in data and qr_link.type == "url":
        valid, err = validate_destination_url(data["destination_url"])
        if not valid:
            return jsonify({"error": err}), 400
        qr_link.destination_url = data["destination_url"].strip()

    if "custom_domain_id" in data:
        if data["custom_domain_id"] is None:
            qr_link.custom_domain_id = None
        else:
            domain = CustomDomain.query.filter_by(
                id=data["custom_domain_id"], user_id=current_user.id, verified=True
            ).first()
            if not domain:
                return jsonify({"error": "Domain not found or not verified"}), 400
            qr_link.custom_domain_id = domain.id

    db.session.commit()
    logger.info(f"Updated QR {qr_id} for user {current_user.id}")
    return jsonify({"qr_code": qr_link.to_dict(base_url=base_url)})


@qr_bp.route("/<int:qr_id>", methods=["DELETE"])
@login_required
def delete_qr(qr_id: int):
    """Delete a QR code."""
    qr_link = QrLink.query.filter_by(id=qr_id, user_id=current_user.id).first_or_404()
    delete_drive_file = request.json.get("delete_drive_file", False) if request.json else False

    if qr_link.type == "file" and qr_link.google_drive_file_id and delete_drive_file:
        try:
            google_drive_provider.delete_file(current_user, qr_link.google_drive_file_id)
        except Exception as e:
            logger.warning(f"Failed to delete Drive file: {e}")

    db.session.delete(qr_link)
    db.session.commit()

    logger.info(f"Deleted QR {qr_id} for user {current_user.id}")
    return jsonify({"message": "QR code deleted"})


@qr_bp.route("/<int:qr_id>/replace-file", methods=["POST"])
@login_required
@limiter.limit("20 per hour")
def replace_file(qr_id: int):
    """Replace the file behind an existing file QR. The short code stays the same."""
    qr_link = QrLink.query.filter_by(id=qr_id, user_id=current_user.id).first_or_404()

    if qr_link.type != "file":
        return jsonify({"error": "This QR code is not a file QR"}), 400

    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "No file selected"}), 400

    max_size = current_app.config["MAX_FILE_SIZE"]
    allowed_mimes = current_app.config["ALLOWED_MIME_TYPES"]

    file_data = file.read()
    if len(file_data) > max_size:
        return jsonify({"error": f"File too large. Maximum size is {max_size // (1024*1024)}MB"}), 400

    mime_type = file.content_type or "application/octet-stream"
    if mime_type not in allowed_mimes:
        return jsonify({"error": f"File type '{mime_type}' is not allowed"}), 400

    safe_filename = sanitize_filename(file.filename)

    try:
        folder_id = qr_link.google_drive_folder_id
        if not folder_id:
            folder_id = google_drive_provider.create_qr_folder(current_user, qr_link.short_code)

        result = google_drive_provider.replace_file(
            user=current_user,
            old_file_id=qr_link.google_drive_file_id,
            folder_id=folder_id,
            file_data=io.BytesIO(file_data),
            filename=safe_filename,
            mime_type=mime_type,
            trash_old=True,
        )

        qr_link.google_drive_file_id = result["file_id"]
        qr_link.google_drive_folder_id = folder_id
        qr_link.original_filename = safe_filename
        qr_link.mime_type = mime_type
        qr_link.file_size = len(file_data)
        db.session.commit()

        logger.info(f"Replaced file for QR {qr_id}, user {current_user.id}")
        base_url = current_app.config["APP_BASE_URL"]
        return jsonify({
            "message": "File replaced successfully. Your QR code has not changed.",
            "qr_code": qr_link.to_dict(base_url=base_url),
        })

    except Exception as e:
        db.session.rollback()
        logger.error(f"File replacement failed: {e}")
        return jsonify({"error": "Failed to replace file. Please try again."}), 500


@qr_bp.route("/<int:qr_id>/image", methods=["GET"])
def get_qr_image(qr_id: int):
    """Get the QR code image as PNG or SVG with customized styles."""
    qr_link = QrLink.query.filter_by(id=qr_id).first_or_404()
    fmt = request.args.get("format", "png").lower()
    size = int(request.args.get("size", 10))

    if fmt not in ("png", "svg"):
        return jsonify({"error": "Format must be 'png' or 'svg'"}), 400

    if size < 1 or size > 30:
        size = 10

    base_url = current_app.config["APP_BASE_URL"]
    public_url = qr_link.get_public_url(base_url)

    img_data = _generate_qr_image(public_url, fmt=fmt, scale=size, style=qr_link.style_config)

    mimetype = "image/png" if fmt == "png" else "image/svg+xml"
    filename = f"qonnect-{qr_link.short_code}.{fmt}"

    return send_file(
        io.BytesIO(img_data),
        mimetype=mimetype,
        as_attachment=True,
        download_name=filename,
    )


@qr_bp.route("/<int:qr_id>/download", methods=["GET"])
@login_required
def download_file(qr_id: int):
    """Proxy download a file from Google Drive."""
    qr_link = QrLink.query.filter_by(id=qr_id, user_id=current_user.id).first_or_404()

    if qr_link.type != "file":
        return jsonify({"error": "Not a file QR"}), 400

    try:
        file_content = google_drive_provider.get_file_content(current_user, qr_link.google_drive_file_id)
        if file_content is None:
            return jsonify({"error": "File not found in Google Drive"}), 404

        return send_file(
            io.BytesIO(file_content),
            mimetype=qr_link.mime_type or "application/octet-stream",
            as_attachment=True,
            download_name=qr_link.original_filename or "file",
        )
    except Exception as e:
        logger.error(f"Download failed: {e}")
        return jsonify({"error": "Failed to download file"}), 500
