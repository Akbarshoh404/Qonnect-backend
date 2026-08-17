"""
User model
"""
from datetime import datetime, timezone
from flask_login import UserMixin
from app.extensions import db


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    google_sub = db.Column(db.String(255), unique=True, nullable=False, index=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    name = db.Column(db.String(255), nullable=True)
    avatar_url = db.Column(db.Text, nullable=True)

    # Encrypted JSON: {access_token, refresh_token, token_expiry, scopes}
    google_tokens_encrypted = db.Column(db.Text, nullable=True)

    # Google Drive folder ID for this user's Qonnect files
    drive_folder_id = db.Column(db.String(255), nullable=True)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    qr_links = db.relationship("QrLink", back_populates="user", lazy="dynamic", cascade="all, delete-orphan")
    custom_domains = db.relationship(
        "CustomDomain", back_populates="user", lazy="dynamic", cascade="all, delete-orphan"
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "email": self.email,
            "name": self.name,
            "avatar_url": self.avatar_url,
            "drive_connected": self.google_tokens_encrypted is not None and self.drive_folder_id is not None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return f"<User {self.email}>"
