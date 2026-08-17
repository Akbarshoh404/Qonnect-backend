"""
Models package - import all models so SQLAlchemy discovers them
"""
from .user import User
from .qr_link import QrLink
from .custom_domain import CustomDomain
from .scan_event import ScanEvent

__all__ = ["User", "QrLink", "CustomDomain", "ScanEvent"]
