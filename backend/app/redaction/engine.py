"""Redaction pipeline (SRS 8.4): field rules -> pattern pass -> known third-party names -> optional
LLM suggestions (add-only) -> deterministic merge -> leak scan -> redaction diff."""
import copy
import html
import re
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from app.redaction.rules import (
    RESTRICTED_SECURITY_FIELDS, RESTRICTED_INTERNAL_FIELDS, POLICY_CONTROL_FIELDS, FREE_TEXT_FIELDS,
    EMAIL_PATTERN, PHONE_PATTERN, SSN_PATTERN, NAME_CUE_PATTERN,
)
from app.redaction.leak_scan import scan_for_data_leaks


class RedactionEngine:
    def __init__(self, subject_email: str, subject_name: str = "", subject_values: Optional[Iterable[str]] = None,
                 known_third_party_names: Optional[List[str]] = None,
                 suggested_terms: Optional[List[str]] = None):
        self.subject_email = (subject_email or "").lower().strip()
        self.subject_name = (subject_name or "").strip()
        self.subject_values = {str(v).strip().lower() for v in (subject_values or []) if v}
        self.subject_values.add(self.subject_email)
        self.subject_name_parts = {p.lower() for p in self.subject_name.split() if len(p) > 2}
        self.known_names = sorted({n.strip() for n in (known_third_party_names or []) if n and n.strip()
                                   and n.strip().lower() != self.subject_name.lower()}, key=len, reverse=True)
        # LLM suggestions can ONLY add redactions (never remove) - enforced by construction here.
        self.suggested = sorted({t.strip() for t in (suggested_terms or []) if t and len(t.strip()) > 2},
                                key=len, reverse=True)
        self.third_party_found: Set[str] = set()

    # ---------------------------------------------------------------- free text
    def _is_subject_name(self, candidate: str) -> bool:
        parts = {p.lower() for p in candidate.split()}
        return bool(parts & self.subject_name_parts)

    def redact_text(self, text: str) -> Tuple[str, List[Dict[str, Any]]]:
        reds: List[Dict[str, Any]] = []
        if not text or not isinstance(text, str):
            return text, reds
        out = text

        def sub_term(term: str, label: str, rtype: str, rule: str = "POL-RED-1"):
            nonlocal out
            pat = re.compile(re.escape(term), re.IGNORECASE)
            if pat.search(out):
                out = pat.sub(f"[REDACTED_{label} ({rule})]", out)
                reds.append({"target": term, "rule": rule, "type": rtype})
                self.third_party_found.add(term)

        for name in self.known_names:                       # directory names (other profiles, staff)
            sub_term(name, "THIRD_PARTY_NAME", "third_party_name")
        for m in NAME_CUE_PATTERN.finditer(out):            # cue-based names
            cand = m.group(1).strip()
            if cand and not self._is_subject_name(cand) and "[REDACTED" not in cand:
                sub_term(cand, "THIRD_PARTY_NAME", "third_party_name_heuristic")
        for term in self.suggested:                         # optional LLM add-only pass
            sub_term(term, "THIRD_PARTY_NAME", "llm_suggested")
        for ssn in sorted(set(SSN_PATTERN.findall(out))):
            sub_term(ssn, "SSN", "ssn")
        for em in sorted(set(EMAIL_PATTERN.findall(out))):
            if em.lower() not in self.subject_values:
                sub_term(em, "EMAIL", "third_party_email")
        for ph in sorted(set(PHONE_PATTERN.findall(out))):
            if ph.strip().lower() not in self.subject_values and re.sub(r"\D", "", ph) not in \
                    {re.sub(r"\D", "", v) for v in self.subject_values}:
                sub_term(ph, "PHONE", "third_party_phone")
        return out, reds

    # ---------------------------------------------------------------- records
    def process_record(self, record: Dict[str, Any]) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        cleaned = copy.deepcopy(record)
        reds: List[Dict[str, Any]] = []
        for f in RESTRICTED_SECURITY_FIELDS:
            if f in cleaned:
                cleaned.pop(f)
                reds.append({"field": f, "rule": "POL-RED-3", "type": "security_field", "original": "<removed>", "exported": "<removed>"})
        for f in RESTRICTED_INTERNAL_FIELDS:
            if f in cleaned:
                cleaned.pop(f)
                reds.append({"field": f, "rule": "POL-RED-2", "type": "internal_field", "original": "<removed>", "exported": "<removed>"})
        for f in POLICY_CONTROL_FIELDS:
            cleaned.pop(f, None)
        for tf in FREE_TEXT_FIELDS:
            if isinstance(cleaned.get(tf), str):
                orig = cleaned[tf]
                new, tr = self.redact_text(orig)
                if new != orig:
                    cleaned[tf] = new
                    for r in tr:
                        r["field"] = tf
                        r["original"], r["exported"] = orig, new
                        reds.append(r)
        return cleaned, reds

    def build_export(self, approved_items: List[Dict[str, Any]]) -> Dict[str, Any]:
        exported, reds_all, diff = [], [], []
        for item in approved_items:
            raw = item.get("raw_data", {})
            cleaned, item_reds = self.process_record(raw)
            exported.append({"source": item.get("source"), "record_id": item.get("record_id"),
                             "classification": item.get("classification"), "data": cleaned})
            for r in item_reds:
                r2 = {**r, "source": item.get("source"), "record_id": item.get("record_id")}
                reds_all.append(r2)
            for fld in sorted({r["field"] for r in item_reds if "field" in r and r["type"] not in ("security_field", "internal_field")}):
                diff.append({"source": item.get("source"), "record_id": item.get("record_id"), "field": fld,
                             "original": raw.get(fld), "exported": cleaned.get(fld),
                             "rules": sorted({r["rule"] for r in item_reds if r.get("field") == fld})})
            for r in item_reds:
                if r["type"] in ("security_field", "internal_field"):
                    diff.append({"source": item.get("source"), "record_id": item.get("record_id"), "field": r["field"],
                                 "original": f"<{r['field']} withheld>", "exported": "<removed>", "rules": [r["rule"]]})

        has_leak, leaks = scan_for_data_leaks(
            data=[e["data"] for e in exported], allowed_values=self.subject_values,
            known_third_party_identifiers=sorted(self.third_party_found | set(self.known_names)),
            subject_name_parts=self.subject_name_parts)
        return {
            "exported_records": exported,
            "redaction_report": {"total_redactions": len(reds_all),
                                 "redactions": [{k: v for k, v in r.items() if k not in ("original", "exported")} for r in reds_all],
                                 "diff": diff},
            "leak_scan": {"passed": not has_leak, "leaks_found": leaks},
            "html_view": self._html(exported),
        }

    @staticmethod
    def _html(records: List[Dict[str, Any]]) -> str:
        blocks = ""
        for r in records:
            rows = "".join(f"<tr><th>{html.escape(str(k))}</th><td>{html.escape(str(v))}</td></tr>"
                           for k, v in r["data"].items())
            blocks += (f"<section><h3>{html.escape(str(r['source']).upper())} &middot; {html.escape(str(r['record_id']))}</h3>"
                       f"<table>{rows}</table></section>")
        return ("<!DOCTYPE html><html><head><meta charset='utf-8'><title>Personal Data Access Export</title>"
                "<style>body{font-family:system-ui,sans-serif;padding:24px;color:#334155}"
                "table{border-collapse:collapse;width:100%;margin-bottom:16px}th,td{border:1px solid #e2e8f0;padding:6px 10px;text-align:left;font-size:13px}"
                "th{background:#f8fafc;width:200px}.d{background:#eff6ff;border-left:4px solid #3b82f6;padding:12px 16px;margin-bottom:24px;font-size:13px}</style></head><body>"
                "<h1>Personal Data Access Export</h1><div class='d'><strong>Notice:</strong> Prepared per the Acme Privacy Request Handling Policy v1.0 (mock). "
                "Other individuals' data, internal identifiers and security fields are redacted (POL-RED-1/2/3). Not legal advice; "
                "does not certify legal compliance.</div>" + blocks + "</body></html>")
