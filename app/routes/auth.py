"""
Authentication routes - Google OAuth 2.0
"""
import secrets
import logging
from datetime import datetime, timezone

from flask import Blueprint, request, redirect, session, jsonify, current_app
from flask_login import login_user, logout_user, login_required, current_user

from app.extensions import db, limiter
from app.models import User
from app.utils.crypto import encrypt_json

logger = logging.getLogger(__name__)
auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")


def _get_oauth_client():
    """Get configured Authlib Google OAuth client."""
    from authlib.integrations.flask_client import OAuth
    oauth = OAuth(current_app)
    oauth.register(
        name="google",
        client_id=current_app.config["GOOGLE_CLIENT_ID"],
        client_secret=current_app.config["GOOGLE_CLIENT_SECRET"],
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={
            "scope": "openid email profile https://www.googleapis.com/auth/drive.file",
            "access_type": "offline",
            "prompt": "consent",  # Always get refresh_token
        },
    )
    return oauth.google


@auth_bp.route("/google")
@limiter.limit("20 per minute")
def google_login():
    """
    Initiate Google OAuth. The redirect_uri uses the FRONTEND_URL so that
    the session cookie (set on the frontend origin) is sent back on callback.
    We use the Vite proxy path so cookies are consistent on port 5173.
    """
    state = secrets.token_urlsafe(32)
    session["oauth_state"] = state
    session.modified = True

    # Always use frontend-proxied callback so session cookies match
    redirect_uri = _get_callback_uri()
    client = _get_oauth_client()
    return client.authorize_redirect(redirect_uri, state=state)


@auth_bp.route("/callback")
@limiter.limit("20 per minute")
def google_callback():
    """Handle Google OAuth callback - completes login and redirects to dashboard."""
    frontend_url = current_app.config["FRONTEND_URL"]

    # State validation (CSRF protection)
    state = request.args.get("state")
    stored_state = session.pop("oauth_state", None)
    if not state or state != stored_state:
        logger.warning(f"OAuth state mismatch. got={state!r} stored={stored_state!r}")
        return redirect(f"{frontend_url}/?auth_error=state_mismatch")

    # Exchange code for tokens
    client = _get_oauth_client()
    try:
        token = client.authorize_access_token()
    except Exception as exc:
        logger.error(f"OAuth token exchange failed: {exc}")
        return redirect(f"{frontend_url}/?auth_error=token_exchange_failed")

    # Get user info from id_token or userinfo endpoint
    user_info = token.get("userinfo") or {}
    if not user_info:
        try:
            user_info = client.userinfo()
        except Exception as exc:
            logger.error(f"Userinfo request failed: {exc}")
            return redirect(f"{frontend_url}/?auth_error=userinfo_failed")

    google_sub = user_info.get("sub")
    email = user_info.get("email")
    if not google_sub or not email:
        return redirect(f"{frontend_url}/?auth_error=missing_user_info")

    # Upsert user
    user = User.query.filter_by(google_sub=google_sub).first()
    if not user:
        user = User(
            google_sub=google_sub,
            email=email,
            name=user_info.get("name"),
            avatar_url=user_info.get("picture"),
        )
        db.session.add(user)
        logger.info(f"New user: {email}")
    else:
        user.name = user_info.get("name", user.name)
        user.avatar_url = user_info.get("picture", user.avatar_url)
        logger.info(f"User login: {email}")

    # Encrypt and store OAuth tokens
    encryption_key = current_app.config.get("ENCRYPTION_KEY", "")
    token_data = {
        "access_token": token.get("access_token"),
        "refresh_token": token.get("refresh_token"),
        "token_expiry": (
            datetime.fromtimestamp(token["expires_at"], tz=timezone.utc).isoformat()
            if token.get("expires_at")
            else None
        ),
    }
    user.google_tokens_encrypted = encrypt_json(token_data, encryption_key)

    # If the token already includes Drive scope, mark drive as connected
    token_scope = token.get("scope", "")
    if "drive.file" in token_scope and not user.drive_folder_id:
        user.drive_folder_id = "pending"  # Will be created on first file upload

    db.session.commit()
    login_user(user, remember=True)

    logger.info(f"Auth OK for {email}")
    return redirect(f"{frontend_url}/dashboard")


@auth_bp.route("/me")
@login_required
def get_me():
    """Get current authenticated user info."""
    from app.storage import google_drive_provider
    return jsonify({
        "user": current_user.to_dict(),
        "drive_connected": google_drive_provider.is_connected(current_user),
    })


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    """Log out the current user."""
    logger.info(f"Logout: {current_user.email}")
    logout_user()
    session.clear()
    return jsonify({"message": "Logged out successfully"})


@auth_bp.route("/drive/connect")
@login_required
def drive_connect():
    """
    Connect/reconnect Google Drive. Re-runs OAuth consent so we always
    get a fresh refresh_token with drive.file scope.
    """
    state = secrets.token_urlsafe(32)
    session["oauth_state"] = state
    session["drive_reconnect"] = True
    session.modified = True

    redirect_uri = _get_callback_uri()
    client = _get_oauth_client()
    return client.authorize_redirect(redirect_uri, state=state)


def _get_callback_uri() -> str:
    """
    Return the OAuth callback URI.

    - Production: GOOGLE_REDIRECT_URI is set explicitly to the backend domain
      (e.g. https://qonnect-api.akbarshoh-dev.uz/api/auth/callback)
      and must be registered in Google Cloud Console.
    - Development: Falls back to frontend proxy path so session cookie stays
      on the same origin as the Vite dev server (localhost:5173).
    """
    explicit = current_app.config.get("GOOGLE_REDIRECT_URI", "")
    if explicit:
        return explicit

    # Dev fallback — Vite proxies /api/* to Flask
    frontend_url = current_app.config.get("FRONTEND_URL", "http://localhost:5173")
    return f"{frontend_url}/api/auth/callback"
