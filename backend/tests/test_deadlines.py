from datetime import datetime, timezone, timedelta
from app.workflow.deadline import compute_deadline_state, calculate_initial_due_date, calculate_extended_due_date

UTC = timezone.utc


def test_due_date_normal(policy):
    due = calculate_initial_due_date(datetime(2026, 9, 1, 10, tzinfo=UTC), policy)
    assert due.date().isoformat() == "2026-10-01" and due.hour == 23


def test_due_date_month_end(policy):
    assert calculate_initial_due_date(datetime(2026, 1, 31, tzinfo=UTC), policy).date().isoformat() == "2026-03-02"


def test_due_date_leap_year(policy):
    assert calculate_initial_due_date(datetime(2028, 1, 30, tzinfo=UTC), policy).date().isoformat() == "2028-02-29"


def test_naive_datetime_treated_as_utc(policy):
    assert calculate_initial_due_date(datetime(2026, 9, 1), policy).tzinfo is not None


def test_extension_adds_policy_days(policy):
    due = calculate_initial_due_date(datetime(2026, 9, 1, tzinfo=UTC), policy)
    assert (calculate_extended_due_date(due, policy).date() - due.date()).days == policy.sla.extension_days


def test_at_risk_boundary(policy):
    now = datetime(2026, 10, 1, 12, tzinfo=UTC)
    seven = datetime(2026, 10, 8, 23, 59, tzinfo=UTC)
    eight = datetime(2026, 10, 9, 23, 59, tzinfo=UTC)
    assert compute_deadline_state(now, seven, "NEW", policy, now)["deadline_status"] == "AT_RISK"
    assert compute_deadline_state(now, eight, "NEW", policy, now)["deadline_status"] == "ON_TRACK"


def test_overdue(policy):
    now = datetime(2026, 10, 10, tzinfo=UTC)
    st = compute_deadline_state(now - timedelta(days=40), now - timedelta(days=1), "PLAN_REVIEW", policy, now)
    assert st["deadline_status"] == "OVERDUE" and st["is_overdue"]


def test_closed_requests_are_never_overdue(policy):
    now = datetime(2026, 10, 10, tzinfo=UTC)
    st = compute_deadline_state(now - timedelta(days=60), now - timedelta(days=5), "CLOSED", policy, now)
    assert st["deadline_status"] == "COMPLETED" and not st["is_overdue"]


def test_timezone_aware_vs_naive_now(policy):
    due = datetime(2026, 10, 20, 23, 59, tzinfo=UTC)
    a = compute_deadline_state(datetime(2026, 9, 20), due, "NEW", policy, datetime(2026, 10, 1))
    b = compute_deadline_state(datetime(2026, 9, 20, tzinfo=UTC), due, "NEW", policy, datetime(2026, 10, 1, tzinfo=UTC))
    assert a == b
