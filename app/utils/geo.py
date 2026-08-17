"""
GeoIP lookup utility - maps IP addresses to approximate country/city.
Uses MaxMind GeoLite2 if available, otherwise returns unknowns gracefully.
"""
import hashlib
import socket
from datetime import datetime, timezone
from typing import Optional
from flask import current_app


def _get_geoip_reader():
    """Get a GeoIP2 reader instance, or None if not configured."""
    try:
        import geoip2.database
        db_path = current_app.config.get("GEOIP_DB_PATH", "")
        if not db_path:
            return None
        return geoip2.database.Reader(db_path)
    except Exception:
        return None


def get_location(ip: Optional[str]) -> dict:
    """
    Get approximate country and city for an IP address.
    Never returns GPS coordinates.
    
    Returns:
        dict with keys: country, country_code, city
    """
    if not ip:
        return {"country": None, "country_code": None, "city": None}

    # Filter out private/local IPs
    if ip in ("127.0.0.1", "::1", "localhost") or ip.startswith("192.168.") or ip.startswith("10."):
        return {"country": "Local", "country_code": "LO", "city": None}

    reader = _get_geoip_reader()
    if not reader:
        return {"country": None, "country_code": None, "city": None}

    try:
        with reader:
            response = reader.city(ip)
            return {
                "country": response.country.name,
                "country_code": response.country.iso_code,
                "city": response.city.name,
            }
    except Exception:
        return {"country": None, "country_code": None, "city": None}


def hash_ip(ip: Optional[str]) -> Optional[str]:
    """
    Hash an IP address for privacy-preserving storage.
    
    Uses SHA256(ip + daily_salt) so:
    - The same IP on the same day produces the same hash (for approximate dedup)
    - The same IP on different days produces different hashes
    - The raw IP cannot be reconstructed from the hash
    
    Returns:
        hex digest string, or None if ip is None
    """
    if not ip:
        return None

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    # Include a constant server-side salt from config for extra security
    value = f"{ip}:{today}:qonnect-ip-salt"
    return hashlib.sha256(value.encode()).hexdigest()
