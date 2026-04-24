"""IANA timezone utilities.

Provides functions for timezone validation, conversion, and normalization
using the IANA timezone database.
"""

import logging
from datetime import datetime
from typing import Optional

try:
    import zoneinfo
except ImportError:
    from backports import zoneinfo  # type: ignore

logger = logging.getLogger(__name__)


def validate_timezone(timezone: str) -> bool:
    """Validate if a timezone string is a valid IANA timezone.
    
    Args:
        timezone: Timezone string to validate.
        
    Returns:
        True if valid, False otherwise.
    """
    try:
        zoneinfo.ZoneInfo(timezone)
        return True
    except (zoneinfo.ZoneInfoNotFoundError, KeyError):
        return False


def get_utc_now() -> datetime:
    """Get the current time in UTC.
    
    Returns:
        Current datetime in UTC timezone.
    """
    return datetime.now(zoneinfo.ZoneInfo("UTC"))


def convert_timezone(
    dt: datetime,
    from_tz: Optional[str] = None,
    to_tz: str = "UTC",
) -> datetime:
    """Convert a datetime from one timezone to another.
    
    Args:
        dt: Datetime to convert.
        from_tz: Source timezone (uses dt's timezone if None).
        to_tz: Target timezone.
        
    Returns:
        Converted datetime.
        
    Raises:
        ValueError: If timezone is invalid.
    """
    if from_tz and dt.tzinfo is None:
        dt = dt.replace(tzinfo=zoneinfo.ZoneInfo(from_tz))
    
    target_tz = zoneinfo.ZoneInfo(to_tz)
    return dt.astimezone(target_tz)


def get_available_timezones() -> list[str]:
    """Get list of available IANA timezones.
    
    Returns:
        List of timezone strings.
    """
    try:
        return list(zoneinfo.available_timezones())
    except Exception:
        return ["UTC"]
