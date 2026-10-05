import json
import re
from typing import Any, Iterable, List, Set, Tuple
from app.redaction.rules import (
    RESTRICTED_SECURITY_FIELDS, RESTRICTED_INTERNAL_FIELDS, SSN_PATTERN, EMAIL_PATTERN, PHONE_PATTERN,
    FREE_TEXT_FIELDS, NAME_CUE_PATTERN,
)


def _walk_text(obj: Any, key: str = ""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk_text(v, k)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_text(v, key)
    elif isinstance(obj, str):
        yield key, obj


def scan_for_data_leaks(data: Any, allowed_values: Iterable[str], known_third_party_identifiers: List[str],
                        subject_name_parts: Set[str] = frozenset()) -> Tuple[bool, List[str]]:
    """Post-redaction scan (FR-605). Independent of the redaction code path:
    restricted keys, known third-party identifiers (verbatim, case-insensitive), SSNs, foreign e-mails,
    foreign phones and cue-based names in free text."""
    leaks: List[str] = []
    allowed = {str(a).lower().strip() for a in allowed_values if a}
    allowed_digits = {re.sub(r"\D", "", a) for a in allowed}
    serialized = json.dumps(data, default=str)

    for f in RESTRICTED_SECURITY_FIELDS:
        if f'"{f}"' in serialized:
            leaks.append(f"Security-restricted field '{f}' present in export (POL-RED-3)")
    for f in RESTRICTED_INTERNAL_FIELDS:
        if f'"{f}"' in serialized:
            leaks.append(f"Internal field '{f}' present in export (POL-RED-2)")
    low = serialized.lower()
    for ident in known_third_party_identifiers:
        if ident and ident.lower() in low:
            leaks.append(f"Third-party identifier '{ident}' present in export (POL-RED-1)")

    for key, text in _walk_text(data):
        for s in SSN_PATTERN.findall(text):
            leaks.append(f"Unmasked SSN pattern in '{key}' (POL-RED-1)")
        for e in EMAIL_PATTERN.findall(text):
            if e.lower() not in allowed:
                leaks.append(f"Foreign e-mail address '{e}' in '{key}' (POL-RED-1)")
        if key in FREE_TEXT_FIELDS:
            for p in PHONE_PATTERN.findall(text):
                if re.sub(r"\D", "", p) not in allowed_digits:
                    leaks.append(f"Foreign phone number '{p}' in '{key}' (POL-RED-1)")
            for m in NAME_CUE_PATTERN.finditer(text):
                cand = m.group(1)
                if not ({w.lower() for w in cand.split()} & set(subject_name_parts)):
                    leaks.append(f"Possible unredacted person name '{cand}' in '{key}' (POL-RED-1)")
    return bool(leaks), sorted(set(leaks))
