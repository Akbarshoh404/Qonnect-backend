"""
Device/browser detection from User-Agent string
"""
from typing import Optional

try:
    from user_agents import parse as ua_parse
    UA_AVAILABLE = True
except ImportError:
    UA_AVAILABLE = False


def parse_user_agent(ua_string: Optional[str]) -> dict:
    """
    Parse a User-Agent string into device/browser/OS info.
    
    Returns:
        dict with keys: device_type, browser, os
    """
    if not ua_string or not UA_AVAILABLE:
        return {"device_type": "unknown", "browser": "unknown", "os": "unknown"}

    try:
        ua = ua_parse(ua_string)

        if ua.is_mobile:
            device_type = "mobile"
        elif ua.is_tablet:
            device_type = "tablet"
        elif ua.is_bot:
            device_type = "bot"
        else:
            device_type = "desktop"

        browser = ua.browser.family or "unknown"
        os_name = ua.os.family or "unknown"

        return {
            "device_type": device_type,
            "browser": browser[:100],
            "os": os_name[:100],
        }
    except Exception:
        return {"device_type": "unknown", "browser": "unknown", "os": "unknown"}
