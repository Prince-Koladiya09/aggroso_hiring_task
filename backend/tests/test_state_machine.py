import itertools
import pytest
from app.db.models import Request
from app.workflow.state_machine import ALLOWED_TRANSITIONS, InvalidStateTransitionError, can_transition, transition_state


def test_every_illegal_transition_is_rejected(db_session):
    req = db_session.query(Request).first()
    states = list(ALLOWED_TRANSITIONS)
    for a, b in itertools.product(states, states):
        if b in ALLOWED_TRANSITIONS[a]:
            continue
        req.status = a
        with pytest.raises(InvalidStateTransitionError):
            transition_state(req, b, "u", "analyst", "x", db_session)
        assert req.status == a                       # unchanged on failure


def test_all_documented_paths_are_legal():
    path = ["NEW", "VERIFICATION_PENDING", "VERIFIED", "PLANNING", "PLAN_REVIEW", "PLAN_APPROVED", "AWAITING_ACTION_APPROVAL",
            "EXECUTING", "PARTIALLY_FAILED", "EXECUTING", "COMPLETED_PENDING_RECORD", "CLOSED"]
    for a, b in zip(path, path[1:]):
        assert can_transition(a, b), (a, b)
    assert can_transition("PLAN_APPROVED", "EXPORT_REVIEW") and can_transition("EXPORT_REVIEW", "COMPLETED_PENDING_RECORD")


def test_terminal_states_have_no_exits():
    for s in ("CLOSED", "REJECTED", "CANCELLED"):
        assert ALLOWED_TRANSITIONS[s] == set()


def test_valid_transition_writes_audit(db_session):
    from app.db.models import AuditEvent
    req = db_session.query(Request).filter(Request.status == "NEW").first()
    transition_state(req, "VERIFICATION_PENDING", "u", "analyst", "go", db_session)
    ev = db_session.query(AuditEvent).filter(AuditEvent.event_type == "REQUEST_STATUS_CHANGED").first()
    assert ev and ev.payload_json["new_status"] == "VERIFICATION_PENDING"
