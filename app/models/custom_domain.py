"""
CustomDomain model
"""
import secrets
from datetime import datetime, timezone
from app.extensions import db


class CustomDomain(db.Model):
    __tablename__ = "custom_domains"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    domain = db.Column(db.String(255), unique=True, nullable=False, index=True)
    verified = db.Column(db.Boolean, default=False, nullable=False)

    # DNS TXT record: _qonnect-verify.<domain> TXT <verification_token>
    verification_token = db.Column(db.String(64), nullable=True)
    verification_method = db.Column(db.String(50), default="dns_txt", nullable=False)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    user = db.relationship("User", back_populates="custom_domains")

    @staticmethod
    def generate_verification_token() -> str:
        return f"qonnect-verify-{secrets.token_urlsafe(24)}"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "domain": self.domain,
            "verified": self.verified,
            "verification_method": self.verification_method,
            "verification_token": self.verification_token,
            "dns_record_name": f"_qonnect-verify.{self.domain}",
            "dns_record_type": "TXT",
            "dns_record_value": self.verification_token,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return f"<CustomDomain {self.domain} verified={self.verified}>"
