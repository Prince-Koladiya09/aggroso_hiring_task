import hashlib
from typing import Optional

def compute_action_idempotency_key(
    request_id: str,
    kind: str,
    source: str,
    record_id: str,
    field: Optional[str] = None,
    strategy: Optional[str] = "HARD_DELETE",
    after_value: Optional[str] = None
) -> str:
    """
    Computes deterministic idempotency key per PRD Section 11.1:
    SHA256(request_id | kind | source | record_id | field_or_"*" | strategy | SHA256(after_value or ""))
    """
    field_part = field if field else "*"
    strat_part = strategy if strategy else "HARD_DELETE"
    after_hash = hashlib.sha256((after_value or "").encode("utf-8")).hexdigest()

    raw_key = f"{request_id}|{kind}|{source}|{record_id}|{field_part}|{strat_part}|{after_hash}"
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
