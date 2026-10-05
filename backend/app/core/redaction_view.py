from typing import Any, Dict

KEYS = {"profiles": ["full_name", "email", "account_status"], "tickets": ["subject", "status", "category"],
        "activity_logs": ["event_type", "timestamp"]}


def minimal_view(source: str, raw: Dict[str, Any]) -> Dict[str, Any]:
    """One-line, non-restricted summary of a record for lists and CSV."""
    return {k: raw.get(k) for k in KEYS.get(source, []) if raw and k in raw}
