"""
Input validation utilities
"""
import re
from urllib.parse import urlparse


# Dangerous/local destination patterns to block
_BLOCKED_HOSTS = {
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "::1",
}

_PRIVATE_IP_PATTERN = re.compile(
    r"^(10\.|172\.(1[6-9]|2[0-9]|3[01])\.|192\.168\.|169\.254\.)"
)

# Filename sanitization
_UNSAFE_FILENAME_RE = re.compile(r'[^\w\s\-\.]')


def validate_destination_url(url: str) -> tuple[bool, str]:
    """
    Validate a URL is safe to use as a QR destination.
    
    Returns:
        (is_valid, error_message)
    """
    if not url:
        return False, "URL is required."

    url = url.strip()

    if len(url) > 2048:
        return False, "URL is too long (max 2048 characters)."

    try:
        parsed = urlparse(url)
    except Exception:
        return False, "Invalid URL format."

    if parsed.scheme not in ("http", "https"):
        return False, "Only HTTP and HTTPS URLs are allowed."

    if not parsed.netloc:
        return False, "URL must have a valid hostname."

    host = parsed.hostname or ""

    if host in _BLOCKED_HOSTS:
        return False, "Local and loopback addresses are not allowed."

    if _PRIVATE_IP_PATTERN.match(host):
        return False, "Private IP addresses are not allowed."

    return True, ""


def sanitize_filename(filename: str) -> str:
    """
    Return a safe filename, stripping dangerous characters.
    Does NOT preserve path separators.
    """
    # Strip path separators first
    filename = filename.replace("\\", "").replace("/", "")

    # Keep only safe characters
    safe = _UNSAFE_FILENAME_RE.sub("_", filename)

    # Limit length
    if len(safe) > 255:
        name, _, ext = safe.rpartition(".")
        safe = name[:250] + "." + ext if ext else safe[:255]

    return safe or "file"


def validate_domain(domain: str) -> tuple[bool, str]:
    """
    Validate a custom domain string.
    
    Returns:
        (is_valid, error_message)
    """
    if not domain:
        return False, "Domain is required."

    domain = domain.strip().lower()

    # Remove protocol prefix if accidentally included
    domain = domain.removeprefix("http://").removeprefix("https://")

    # Basic domain pattern: labels separated by dots
    pattern = re.compile(
        r"^(?:[a-zA-Z0-9]"
        r"(?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?"
        r"\.)+[a-zA-Z]{2,}$"
    )

    if not pattern.match(domain):
        return False, "Invalid domain format. Use a valid hostname like 'files.example.com'."

    if len(domain) > 253:
        return False, "Domain name is too long."

    return True, domain  # returns normalized domain as second value
