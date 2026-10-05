from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime, ForeignKey, Float, UniqueConstraint, JSON
)
from sqlalchemy.orm import relationship as orm_relationship
from app.db.base import Base

def utc_now() -> datetime:
    return datetime.now(timezone.utc)

class StaffUser(Base):
    __tablename__ = "staff_users"

    id = Column(String(64), primary_key=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    password_hash = Column(String(256), nullable=False)
    role = Column(String(32), nullable=False)  # analyst, approver, auditor
    full_name = Column(String(128), nullable=False)
    created_at = Column(DateTime, default=utc_now)

class Request(Base):
    __tablename__ = "requests"

    id = Column(String(64), primary_key=True)  # e.g., REQ-2026-0001
    type = Column(String(32), nullable=False)  # ACCESS, CORRECTION, DELETION, UNSUPPORTED
    status = Column(String(64), nullable=False, default="NEW", index=True)
    requester_name = Column(String(128), nullable=False)
    requester_email = Column(String(128), nullable=False, index=True)
    account_id = Column(String(64), nullable=True)
    relationship = Column(String(32), default="self")  # self, authorized_agent
    description = Column(Text, nullable=False)
    received_at = Column(DateTime, default=utc_now)
    due_at = Column(DateTime, nullable=False)
    extended = Column(Boolean, default=False)
    extension_reason = Column(Text, nullable=True)
    subject_profile_id = Column(String(64), nullable=True)
    correlation_id = Column(String(64), nullable=False)
    created_by = Column(String(64), ForeignKey("staff_users.id"), nullable=False)
    plan_initiated_by = Column(String(64), nullable=True)      # user who last triggered the agent (four-eyes, POL-APR-3)
    authorization_on_file = Column(Boolean, default=False)     # POL-ID-3
    inventory_version = Column(Integer, default=1, nullable=False)  # FR-503
    extension_pending = Column(Boolean, default=False)
    extension_request_reason = Column(Text, nullable=True)
    extension_requested_by = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    # Relationships
    verification_checks = orm_relationship("VerificationCheck", back_populates="request", cascade="all, delete-orphan")
    plans = orm_relationship("Plan", back_populates="request", cascade="all, delete-orphan")
    inventory_items = orm_relationship("InventoryItem", back_populates="request", cascade="all, delete-orphan")
    proposed_actions = orm_relationship("ProposedAction", back_populates="request", cascade="all, delete-orphan")
    approvals = orm_relationship("Approval", back_populates="request", cascade="all, delete-orphan")
    tool_calls = orm_relationship("ToolCall", back_populates="request", cascade="all, delete-orphan")
    llm_runs = orm_relationship("LLMRun", back_populates="request", cascade="all, delete-orphan")
    exports = orm_relationship("Export", back_populates="request", cascade="all, delete-orphan")
    audit_events = orm_relationship("AuditEvent", back_populates="request", cascade="all, delete-orphan")
    fulfilment_record = orm_relationship("FulfilmentRecord", back_populates="request", uselist=False, cascade="all, delete-orphan")

class VerificationCheck(Base):
    __tablename__ = "verification_checks"

    id = Column(String(64), primary_key=True)
    request_id = Column(String(64), ForeignKey("requests.id"), nullable=False)
    level = Column(Integer, nullable=False)  # 1 or 2
    result = Column(String(32), nullable=False)  # PASSED, FAILED, LOCKED
    failed_fields = Column(JSON, default=list)  # list of strings
    otp_sent = Column(String(16), nullable=True)  # simulated OTP
    otp_attempts = Column(Integer, default=0)
    locked = Column(Boolean, default=False)
    performed_by = Column(String(64), ForeignKey("staff_users.id"), nullable=False)
    at = Column(DateTime, default=utc_now)

    request = orm_relationship("Request", back_populates="verification_checks")

class Plan(Base):
    __tablename__ = "plans"

    id = Column(String(64), primary_key=True)
    request_id = Column(String(64), ForeignKey("requests.id"), nullable=False)
    version = Column(Integer, default=1)
    interpretation_json = Column(JSON, nullable=False)
    plan_json = Column(JSON, nullable=False)
    source = Column(String(32), default="LLM")  # LLM, FALLBACK
    prompt_version = Column(String(32), default="v1")
    status = Column(String(32), default="ACTIVE")  # ACTIVE, SUPERSEDED
    created_at = Column(DateTime, default=utc_now)

    request = orm_relationship("Request", back_populates="plans")

class InventoryItem(Base):
    __tablename__ = "inventory_items"

    id = Column(String(64), primary_key=True)
    request_id = Column(String(64), ForeignKey("requests.id"), nullable=False)
    inventory_version = Column(Integer, default=1)
    source = Column(String(64), nullable=False)  # profiles, tickets, activity_logs
    record_id = Column(String(64), nullable=False)
    classification = Column(String(64), nullable=False)
    relevance = Column(String(32), nullable=False)  # RELEVANT, UNRELATED, UNCERTAIN
    decision = Column(String(64), nullable=False)  # INCLUDE, REDACT, EXCLUDE_RETENTION, EXCLUDE_UNRELATED, NEEDS_REVIEW
    reason = Column(Text, nullable=False)
    rule_ids = Column(JSON, default=list)
    override_by = Column(String(64), nullable=True)
    override_reason = Column(Text, nullable=True)
    raw_data_json = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=utc_now)

    request = orm_relationship("Request", back_populates="inventory_items")

class ProposedAction(Base):
    __tablename__ = "proposed_actions"

    id = Column(String(64), primary_key=True)
    request_id = Column(String(64), ForeignKey("requests.id"), nullable=False)
    plan_id = Column(String(64), ForeignKey("plans.id"), nullable=False)
    kind = Column(String(32), nullable=False)  # CORRECTION, DELETION
    source = Column(String(64), nullable=False)
    record_id = Column(String(64), nullable=False)
    field = Column(String(64), nullable=True)  # for correction or specific field delete
    before_value = Column(Text, nullable=True)
    after_value = Column(Text, nullable=True)
    strategy = Column(String(64), default="HARD_DELETE")
    risk_text = Column(Text, nullable=False)
    rule_ids = Column(JSON, default=list)
    status = Column(String(32), default="PROPOSED")  # PROPOSED, APPROVED, REJECTED, EXECUTED, BLOCKED
    created_at = Column(DateTime, default=utc_now)

    request = orm_relationship("Request", back_populates="proposed_actions")
    action = orm_relationship("Action", back_populates="proposed_action", uselist=False)

class Approval(Base):
    __tablename__ = "approvals"

    id = Column(String(64), primary_key=True)
    request_id = Column(String(64), ForeignKey("requests.id"), nullable=False)
    scope = Column(String(32), nullable=False)  # PLAN, CORRECTION, DELETION, EXPORT, EXTENSION
    decision = Column(String(32), nullable=False)  # APPROVED, REJECTED
    approver_id = Column(String(64), ForeignKey("staff_users.id"), nullable=False)
    reason = Column(Text, nullable=False)
    action_set_hash = Column(String(128), nullable=True)
    inventory_version = Column(Integer, default=1)
    created_at = Column(DateTime, default=utc_now)

    request = orm_relationship("Request", back_populates="approvals")

class Action(Base):
    __tablename__ = "actions"

    id = Column(String(64), primary_key=True)
    proposed_action_id = Column(String(64), ForeignKey("proposed_actions.id"), nullable=False)
    idempotency_key = Column(String(128), unique=True, nullable=False, index=True)
    status = Column(String(32), default="PENDING")  # PENDING, IN_PROGRESS, SUCCEEDED, FAILED, SUCCEEDED_RECONCILED
    attempts = Column(Integer, default=0)
    lease_expires_at = Column(DateTime, nullable=True)
    pre_image = Column(JSON, nullable=True)  # sealed (Fernet) - FR-707
    result_json = Column(JSON, nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    proposed_action = orm_relationship("ProposedAction", back_populates="action")
    attempts_history = orm_relationship("ActionAttempt", back_populates="action", cascade="all, delete-orphan")

class ActionAttempt(Base):
    __tablename__ = "action_attempts"

    id = Column(String(64), primary_key=True)
    action_id = Column(String(64), ForeignKey("actions.id"), nullable=False)
    attempt_no = Column(Integer, nullable=False)
    started_at = Column(DateTime, default=utc_now)
    ended_at = Column(DateTime, nullable=True)
    outcome = Column(String(32), nullable=False)  # SUCCEEDED, FAILED
    error = Column(Text, nullable=True)

    action = orm_relationship("Action", back_populates="attempts_history")

class ToolCall(Base):
    __tablename__ = "tool_calls"

    id = Column(String(64), primary_key=True)
    request_id = Column(String(64), ForeignKey("requests.id"), nullable=True)
    tool = Column(String(64), nullable=False)
    args_json = Column(JSON, default=dict)
    status = Column(String(32), nullable=False)  # OK, ERROR, DENIED
    denial_reason = Column(Text, nullable=True)
    result_summary = Column(Text, nullable=True)
    rows = Column(Integer, default=0)
    duration_ms = Column(Float, default=0.0)
    caller = Column(String(32), default="AGENT")  # AGENT, EXECUTOR, SYSTEM
    correlation_id = Column(String(64), nullable=False)
    at = Column(DateTime, default=utc_now)

    request = orm_relationship("Request", back_populates="tool_calls")

class LLMRun(Base):
    __tablename__ = "llm_runs"

    id = Column(String(64), primary_key=True)
    request_id = Column(String(64), ForeignKey("requests.id"), nullable=True)
    stage = Column(String(64), nullable=False)
    model = Column(String(64), nullable=False)
    prompt_version = Column(String(32), default="v1")
    input_hash = Column(String(128), nullable=False)
    output_json = Column(JSON, nullable=True)
    valid = Column(Boolean, default=True)
    error = Column(Text, nullable=True)
    tokens_in = Column(Integer, default=0)
    tokens_out = Column(Integer, default=0)
    latency_ms = Column(Float, default=0.0)
    at = Column(DateTime, default=utc_now)

    request = orm_relationship("Request", back_populates="llm_runs")

class Export(Base):
    __tablename__ = "exports"

    id = Column(String(64), primary_key=True)
    request_id = Column(String(64), ForeignKey("requests.id"), nullable=False)
    inventory_version = Column(Integer, default=1)
    content_json = Column(JSON, nullable=False)
    html_content = Column(Text, nullable=False)
    redaction_report_json = Column(JSON, nullable=False)
    leak_scan_result = Column(JSON, nullable=False)
    released_by = Column(String(64), nullable=True)
    released_at = Column(DateTime, nullable=True)

    request = orm_relationship("Request", back_populates="exports")

class AuditEvent(Base):
    __tablename__ = "audit_events"

    id = Column(String(64), primary_key=True)
    seq = Column(Integer, autoincrement=True, unique=True, index=True)
    request_id = Column(String(64), ForeignKey("requests.id"), nullable=True)
    actor_id = Column(String(64), nullable=False)
    actor_role = Column(String(32), nullable=False)
    event_type = Column(String(64), nullable=False, index=True)
    entity = Column(String(64), nullable=False)
    payload_json = Column(JSON, default=dict)
    prev_hash = Column(String(128), nullable=False)
    hash = Column(String(128), nullable=False)
    correlation_id = Column(String(64), nullable=False)
    at = Column(DateTime, default=utc_now)

    request = orm_relationship("Request", back_populates="audit_events")

class FulfilmentRecord(Base):
    __tablename__ = "fulfilment_records"

    id = Column(String(64), primary_key=True)
    request_id = Column(String(64), ForeignKey("requests.id"), unique=True, nullable=False)
    content_json = Column(JSON, nullable=False)
    narrative = Column(Text, nullable=False)
    narrative_source = Column(String(32), default="DETERMINISTIC")  # AI_DRAFTED | DETERMINISTIC | HUMAN_EDITED
    narrative_confirmed_by = Column(String(64), nullable=True)
    generated_at = Column(DateTime, default=utc_now)
    policy_version = Column(String(32), nullable=False)

    request = orm_relationship("Request", back_populates="fulfilment_record")

# ----------------- Mock Data Sources Models ----------------- #

class Profile(Base):
    __tablename__ = "profiles"

    profile_id = Column(String(64), primary_key=True)
    account_id = Column(String(64), unique=True, nullable=False, index=True)
    full_name = Column(String(128), nullable=False)
    email = Column(String(128), unique=True, nullable=False, index=True)
    phone = Column(String(64), nullable=False)
    dob = Column(String(32), nullable=False)
    address = Column(String(256), nullable=False)
    marketing_opt_in = Column(Boolean, default=False)
    account_status = Column(String(32), default="ACTIVE")
    password_hash = Column(String(256), nullable=False)  # RESTRICTED_SECURITY
    risk_score = Column(Float, default=0.0)  # RESTRICTED_SECURITY
    fraud_flag = Column(Boolean, default=False)  # RESTRICTED_SECURITY
    internal_notes = Column(Text, nullable=True)  # RESTRICTED_INTERNAL
    legal_hold = Column(Boolean, default=False)  # POLICY_CONTROL
    created_at = Column(DateTime, default=utc_now)

class Ticket(Base):
    __tablename__ = "tickets"

    ticket_id = Column(String(64), primary_key=True)
    requester_email = Column(String(128), nullable=False, index=True)
    requester_profile_id = Column(String(64), nullable=True, index=True)
    subject = Column(String(256), nullable=False)
    body = Column(Text, nullable=False)
    status = Column(String(32), default="CLOSED")
    category = Column(String(64), default="support")
    assigned_agent = Column(String(128), default="Support Agent 1")  # RESTRICTED_INTERNAL
    agent_id = Column(String(64), default="AGT-001")  # RESTRICTED_INTERNAL
    internal_notes = Column(Text, nullable=True)  # RESTRICTED_INTERNAL
    legal_hold = Column(Boolean, default=False)  # POLICY_CONTROL
    retention_class = Column(String(64), default="standard")  # standard, billing
    created_at = Column(DateTime, default=utc_now)

class ActivityLog(Base):
    __tablename__ = "activity_logs"

    log_id = Column(String(64), primary_key=True)
    profile_id = Column(String(64), nullable=False, index=True)
    event_type = Column(String(64), nullable=False)
    timestamp = Column(DateTime, default=utc_now)
    details = Column(Text, nullable=False)
    ip_address = Column(String(64), nullable=False)
    user_agent = Column(String(256), nullable=False)
    risk_signal = Column(String(64), default="LOW")  # RESTRICTED_SECURITY
    retention_class = Column(String(64), default="standard")  # standard, security_audit
