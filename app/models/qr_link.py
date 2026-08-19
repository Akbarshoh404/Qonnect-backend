"""
QrLink model - the core entity of Qonnect
"""
from datetime import datetime, timezone
from app.extensions import db


class QrLink(db.Model):
    __tablename__ = "qr_links"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    # The stable short code embedded in the QR — never changes
    short_code = db.Column(db.String(20), unique=True, nullable=False, index=True)

    # 'url' or 'file'
    type = db.Column(db.String(10), nullable=False)

    # Human-readable name
    title = db.Column(db.String(255), nullable=False)

    # Project / Folder organization
    project_name = db.Column(db.String(100), nullable=True, index=True)

    # Tags list: ["marketing", "table-1", "vip"]
    tags = db.Column(db.JSON, nullable=True, default=list)

    # QR Design Studio styling config (colors, gradients, dot styles, corner eyes, center logo, CTA frames)
    style_config = db.Column(db.JSON, nullable=True)

    # Custom branded inactive / 404 fallback page config
    inactive_config = db.Column(db.JSON, nullable=True)

    # For URL type: the current redirect destination
    destination_url = db.Column(db.Text, nullable=True)

    # For file type: Google Drive metadata
    google_drive_file_id = db.Column(db.String(255), nullable=True)
    google_drive_folder_id = db.Column(db.String(255), nullable=True)
    original_filename = db.Column(db.String(500), nullable=True)
    mime_type = db.Column(db.String(255), nullable=True)
    file_size = db.Column(db.BigInteger, nullable=True)  # bytes

    # Optional custom domain
    custom_domain_id = db.Column(
        db.Integer, db.ForeignKey("custom_domains.id", ondelete="SET NULL"), nullable=True
    )

    is_active = db.Column(db.Boolean, default=True, nullable=False)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    user = db.relationship("User", back_populates="qr_links")
    custom_domain = db.relationship("CustomDomain", foreign_keys=[custom_domain_id])
    scan_events = db.relationship(
        "ScanEvent", back_populates="qr_link", lazy="dynamic", cascade="all, delete-orphan"
    )

    def get_public_url(self, base_url: str) -> str:
        """Return the stable public URL embedded in the QR code."""
        if self.custom_domain and self.custom_domain.verified:
            return f"https://{self.custom_domain.domain}/{self.short_code}"
        return f"{base_url}/q/{self.short_code}"

    def to_dict(self, base_url: str = "", include_scan_count: bool = True) -> dict:
        result = {
            "id": self.id,
            "short_code": self.short_code,
            "type": self.type,
            "title": self.title,
            "project_name": self.project_name or None,
            "tags": self.tags or [],
            "style_config": self.style_config or None,
            "inactive_config": self.inactive_config or None,
            "is_active": self.is_active,
            "public_url": self.get_public_url(base_url),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

        if self.type == "url":
            result["destination_url"] = self.destination_url

        if self.type == "file":
            result["original_filename"] = self.original_filename
            result["mime_type"] = self.mime_type
            result["file_size"] = self.file_size

        if self.custom_domain:
            result["custom_domain"] = self.custom_domain.domain

        if include_scan_count:
            result["scan_count"] = self.scan_events.count()

        return result

    def __repr__(self) -> str:
        return f"<QrLink {self.short_code} ({self.type})>"
