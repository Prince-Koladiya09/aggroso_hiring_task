from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional
from app.policy.loader import PolicyModel
from app.workflow.state_machine import TERMINAL_STATES

def calculate_initial_due_date(received_at: datetime, policy: PolicyModel) -> datetime:
    """Calculates due date: received_at + fulfil_days calendar days at 23:59:59 UTC."""
    if received_at.tzinfo is None:
        received_at = received_at.replace(tzinfo=timezone.utc)
    base_due = received_at + timedelta(days=policy.sla.fulfil_days)
    return base_due.replace(hour=23, minute=59, second=59, microsecond=999999)

def calculate_extended_due_date(current_due_at: datetime, policy: PolicyModel) -> datetime:
    """Extends due date by extension_days calendar days."""
    if current_due_at.tzinfo is None:
        current_due_at = current_due_at.replace(tzinfo=timezone.utc)
    extended = current_due_at + timedelta(days=policy.sla.extension_days)
    return extended.replace(hour=23, minute=59, second=59, microsecond=999999)

def compute_deadline_state(
    received_at: datetime,
    due_at: datetime,
    status: str,
    policy: PolicyModel,
    now: Optional[datetime] = None
) -> Dict[str, Any]:
    """
    Pure deterministic deadline state evaluator.
    Returns:
    {
        "days_remaining": int,
        "is_overdue": bool,
        "is_at_risk": bool,
        "deadline_status": "OVERDUE" | "AT_RISK" | "ON_TRACK" | "COMPLETED",
        "due_at_iso": str
    }
    """
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    if due_at.tzinfo is None:
        due_at = due_at.replace(tzinfo=timezone.utc)

    if status in TERMINAL_STATES:
        return {
            "days_remaining": max(0, (due_at.date() - now.date()).days),
            "is_overdue": False,
            "is_at_risk": False,
            "deadline_status": "COMPLETED",
            "due_at_iso": due_at.isoformat()
        }

    # Days remaining calculation
    days_remaining = (due_at.date() - now.date()).days

    if now > due_at:
        deadline_status = "OVERDUE"
        is_overdue = True
        is_at_risk = False
    elif days_remaining <= policy.sla.at_risk_days:
        deadline_status = "AT_RISK"
        is_overdue = False
        is_at_risk = True
    else:
        deadline_status = "ON_TRACK"
        is_overdue = False
        is_at_risk = False

    return {
        "days_remaining": days_remaining,
        "is_overdue": is_overdue,
        "is_at_risk": is_at_risk,
        "deadline_status": deadline_status,
        "due_at_iso": due_at.isoformat()
    }
