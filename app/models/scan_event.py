"""
ScanEvent model - records each QR scan
"""
from datetime import datetime, timezone
from app.extensions import db


class ScanEvent(db.Model):
    __tablename__ = "scan_events"

    id = db.Column(db.Integer, primary_key=True)
    qr_link_id = db.Column(
        db.Integer, db.ForeignKey("qr_links.id", ondelete="CASCADE"), nullable=False, index=True
    )

    timestamp = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True
    )

    # Privacy-preserving: SHA256(IP + daily_salt) — cannot reverse to raw IP
    ip_hash = db.Column(db.String(64), nullable=True, index=True)

    # Approximate location from GeoIP (not GPS)
    country = db.Column(db.String(100), nullable=True)
    country_code = db.Column(db.String(10), nullable=True)
    city = db.Column(db.String(200), nullable=True)

    # Device info from user agent
    user_agent = db.Column(db.Text, nullable=True)  # raw UA for debugging only
    device_type = db.Column(db.String(20), nullable=True)   # mobile, tablet, desktop
    browser = db.Column(db.String(100), nullable=True)
    os = db.Column(db.String(100), nullable=True)

    referrer = db.Column(db.Text, nullable=True)

    # Relationships
    qr_link = db.relationship("QrLink", back_populates="scan_events")

    def __repr__(self) -> str:
        return f"<ScanEvent qr={self.qr_link_id} at={self.timestamp}>"
