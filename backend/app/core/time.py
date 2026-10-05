from datetime import datetime, timezone
from typing import Optional

_fixed_now: Optional[datetime] = None

def get_now() -> datetime:
    """Returns current UTC datetime, or the fixed datetime if set for testing."""
    if _fixed_now is not None:
        return _fixed_now
    return datetime.now(timezone.utc)

def set_fixed_now(dt: Optional[datetime]) -> None:
    """Sets or clears a fixed datetime for deterministic testing."""
    global _fixed_now
    _fixed_now = dt

def format_iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    return dt.isoformat()
