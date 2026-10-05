"""Versioned prompt files (NFR-7) + data minimisation for LLM input (SRS 9.5)."""
import json
import re
from functools import lru_cache
from html import escape
from pathlib import Path
from typing import Any, Dict, List
from app.core.config import settings
from app.redaction.rules import (
    RESTRICTED_SECURITY_FIELDS, RESTRICTED_INTERNAL_FIELDS, POLICY_CONTROL_FIELDS,
    EMAIL_PATTERN, PHONE_PATTERN, SSN_PATTERN,
)

# Field NAMES per source that the LLM may be told about (values are never sent for restricted fields).
SHOWN_FIELDS = {
    "profiles": ["profile_id", "account_id", "full_name", "email", "phone", "address", "marketing_opt_in", "account_status"],
    "tickets": ["ticket_id", "requester_email", "subject", "status", "category", "created_at"],
    "activity_logs": ["log_id", "profile_id", "event_type", "timestamp"],
}
EXCERPT_FIELDS = {"tickets": "body", "activity_logs": "details"}


@lru_cache(maxsize=16)
def load_prompt(name: str) -> str:
    path = Path(settings.PROMPTS_DIR) / f"{name}.md"
    return path.read_text(encoding="utf-8")


def render(name: str, **values: Any) -> str:
    text = load_prompt(name)
    for k, v in values.items():
        text = text.replace("{" + k + "}", v if isinstance(v, str) else json.dumps(v, indent=2, default=str))
    return text


def mask_excerpt(text: str, limit: int) -> str:
    t = SSN_PATTERN.sub("[SSN]", text or "")
    t = EMAIL_PATTERN.sub("[EMAIL]", t)
    t = PHONE_PATTERN.sub("[PHONE]", t)
    t = t.replace("\n", " ")
    return t[:limit] + ("..." if len(t) > limit else "")


def _safe(v: Any) -> str:
    # escape angle brackets so record text can never close/open a <record> wrapper
    return escape(str(v), quote=True)


def records_to_xml(items: List[Dict[str, Any]], excerpt_chars: int) -> str:
    """Records are DATA. Only whitelisted fields + a short masked excerpt are sent; restricted values never are."""
    out = []
    for it in items:
        raw = it.get("raw_data", {}) or {}
        shown = {k: raw.get(k) for k in SHOWN_FIELDS.get(it["source"], []) if k in raw}
        restricted = [f for f in RESTRICTED_SECURITY_FIELDS + RESTRICTED_INTERNAL_FIELDS + POLICY_CONTROL_FIELDS if f in raw]
        excerpt = ""
        ef = EXCERPT_FIELDS.get(it["source"])
        if ef and raw.get(ef):
            excerpt = mask_excerpt(raw[ef], excerpt_chars)
        flags = []
        if raw.get("legal_hold"):
            flags.append("legal_hold=true")
        if raw.get("retention_class") not in (None, "standard"):
            flags.append(f"retention_class={raw.get('retention_class')}")
        out.append(
            f'<record source="{_safe(it["source"])}" id="{_safe(it["record_id"])}" classification="{_safe(it["classification"])}" '
            f'policy_flags="{_safe(",".join(flags))}">\n'
            f'  fields: {_safe(json.dumps(shown, default=str))}\n'
            f'  restricted_field_names_withheld: {_safe(",".join(restricted))}\n'
            f'  excerpt: {_safe(excerpt)}\n</record>')
    return "\n".join(out)
