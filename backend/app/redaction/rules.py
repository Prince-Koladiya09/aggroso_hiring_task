import re
from typing import Pattern

EMAIL_PATTERN: Pattern = re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]*[a-zA-Z0-9]')
PHONE_PATTERN: Pattern = re.compile(r'(?<![\w-])(?:\+?1[-. ]?)?\(?\d{3}\)?[-. ]?\d{3}[-. ]?\d{4}(?![\w-])')
SSN_PATTERN: Pattern = re.compile(r'\b\d{3}-\d{2}-\d{4}\b')
# Cue-based person-name detector for names that are in no directory ("our officer Marcus Vance").
NAME_CUE_PATTERN: Pattern = re.compile(
    r'\b(?:officer|manager|director|colleague|coworker|co-worker|contact|assistant|auditor|attorney|lawyer|'
    r'consultant|partner|spouse|husband|wife|brother|sister|mr\.?|mrs\.?|ms\.?|dr\.?|named|called|from|with|by)\s+'
    r'((?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2}))')

RESTRICTED_SECURITY_FIELDS = ["password_hash", "risk_score", "fraud_flag", "risk_signal"]
RESTRICTED_INTERNAL_FIELDS = ["internal_notes", "assigned_agent", "agent_id"]
POLICY_CONTROL_FIELDS = ["legal_hold", "retention_class"]   # internal controls, not subject data
FREE_TEXT_FIELDS = ["body", "subject", "details"]
