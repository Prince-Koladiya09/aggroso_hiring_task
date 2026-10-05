import hashlib
import json
from datetime import datetime, timezone
from typing import Any, List, Optional, Tuple


def canonical_json(data: Any) -> str:
    """Deterministic, key-sorted JSON without extra whitespace."""
    return json.dumps(data, sort_keys=True, separators=(',', ':'), default=str)


def normalize_ts(ts: Any) -> str:
    """SQLite returns naive datetimes; normalise aware/naive to the same UTC string so the
    hash computed at write time equals the hash recomputed after a DB round-trip."""
    if isinstance(ts, datetime):
        if ts.tzinfo is not None:
            ts = ts.astimezone(timezone.utc).replace(tzinfo=None)
        return ts.isoformat()
    return str(ts)


def compute_audit_hash(prev_hash: str, seq: int, event_type: str, payload: Any, timestamp: datetime,
                       actor_id: str = "", request_id: Optional[str] = None) -> str:
    raw = f"{prev_hash}|{seq}|{event_type}|{actor_id}|{request_id or ''}|{canonical_json(payload)}|{normalize_ts(timestamp)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def verify_chain(events: List[Any]) -> Tuple[bool, Optional[str], Optional[int]]:
    """Verify an ordered (seq asc) list of events. Returns (valid, reason, broken_seq)."""
    if not events:
        return True, None, None
    genesis = "0" * 64
    for i, ev in enumerate(events):
        expected_prev = genesis if i == 0 else events[i - 1].hash
        if ev.prev_hash != expected_prev:
            return False, f"Broken link at seq {ev.seq}: prev_hash mismatch", ev.seq
        recalculated = compute_audit_hash(
            prev_hash=ev.prev_hash, seq=ev.seq, event_type=ev.event_type, payload=ev.payload_json,
            timestamp=ev.at, actor_id=ev.actor_id, request_id=ev.request_id,
        )
        if recalculated != ev.hash:
            return False, f"Tampered record at seq {ev.seq}: content or hash mismatch", ev.seq
    return True, None, None
