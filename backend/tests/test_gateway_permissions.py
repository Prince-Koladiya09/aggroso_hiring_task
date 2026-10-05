import pytest
from helpers import *
from app.db.models import Request, ToolCall, ProposedAction
from app.tools.gateway import ToolGateway, ToolPermissionDeniedError


def gw(db): return ToolGateway(db)


def call(db, tool, args=None, role="analyst", caller="AGENT", rid=None):
    return gw(db).invoke(tool, args or {}, "usr_staff_analyst", role, caller=caller, request_id=rid)


def test_search_before_verification_denied_and_logged(db_session):
    with pytest.raises(ToolPermissionDeniedError) as e:
        call(db_session, "search_profiles", rid="REQ-2026-0001")
    assert e.value.reason == "INVALID_STATE_FOR_TOOL"          # not yet in PLANNING
    d = db_session.query(ToolCall).filter(ToolCall.status == "DENIED").first()
    assert d and d.tool == "search_profiles" and d.request_id == "REQ-2026-0001"


def test_search_in_planning_but_unverified_is_denied(db_session):
    r = db_session.query(Request).filter(Request.id == "REQ-2026-0001").first()
    r.status = "PLANNING"; db_session.commit()                   # forced state, but no PASSED verification
    with pytest.raises(ToolPermissionDeniedError) as e:
        call(db_session, "search_tickets", rid=r.id)
    assert e.value.reason == "UNVERIFIED_SUBJECT"


def test_write_tool_by_agent_denied(db_session):
    with pytest.raises(ToolPermissionDeniedError) as e:
        call(db_session, "delete_record", {"source": "profiles", "record_id": "prf_001"}, rid="REQ-2026-0003")
    assert e.value.reason == "DIRECT_WRITE_FORBIDDEN"


def test_write_tool_by_executor_without_approval_denied(db_session):
    r = db_session.query(Request).filter(Request.id == "REQ-2026-0002").first()
    r.status = "EXECUTING"; db_session.commit()
    with pytest.raises(ToolPermissionDeniedError) as e:
        call(db_session, "delete_record", {"source": "tickets", "record_id": "TCK-1009"}, caller="EXECUTOR", rid=r.id)
    assert e.value.reason in ("UNVERIFIED_SUBJECT", "NO_APPROVED_ACTION")


def test_write_with_unapproved_proposed_action_denied(client, auth, db_session):
    rid = planned(client, auth, "david", "DELETION", "Please delete all my personal data")
    pa = db_session.query(ProposedAction).filter(ProposedAction.request_id == rid, ProposedAction.source == "tickets").first()
    req = db_session.query(Request).filter(Request.id == rid).first()
    req.status = "EXECUTING"; db_session.commit()                # skipping the approval entirely
    with pytest.raises(ToolPermissionDeniedError) as e:
        call(db_session, "delete_record", {"proposed_action_id": pa.id, "source": pa.source, "record_id": pa.record_id,
                                           "strategy": pa.strategy}, caller="EXECUTOR", rid=rid)
    assert e.value.reason in ("ACTION_NOT_APPROVED",)


def test_unknown_tool_denied(db_session):
    with pytest.raises(ToolPermissionDeniedError) as e:
        call(db_session, "drop_all_tables")
    assert e.value.reason == "UNREGISTERED_TOOL"


def test_wrong_role_denied(db_session):
    with pytest.raises(ToolPermissionDeniedError) as e:
        call(db_session, "search_profiles", role="auditor", rid=None)
    assert e.value.reason == "ROLE_NOT_PERMITTED"


def test_llm_visible_tools_contain_no_write_tools():
    from app.tools.registry import get_llm_exposed_tools, TOOL_REGISTRY
    names = {t["name"] for t in get_llm_exposed_tools()}
    assert not names & {"apply_correction", "delete_record", "generate_export", "lookup_profile_for_verification"}
    assert all(TOOL_REGISTRY[n].tool_type == "read" for n in names)


def test_denied_calls_are_audited(db_session):
    from app.db.models import AuditEvent
    with pytest.raises(ToolPermissionDeniedError):
        call(db_session, "nope")
    assert db_session.query(AuditEvent).filter(AuditEvent.event_type == "TOOL_CALL_DENIED").count() == 1


def test_search_scope_comes_from_verified_subject_not_caller_args(client, auth, db_session):
    rid = planned(client, auth, "john", "ACCESS", "Please provide a copy of my data")
    req = db_session.query(Request).filter(Request.id == rid).first()
    req.status = "PLANNING"; db_session.commit()
    res = call(db_session, "search_profiles", {"profile_id": "prf_002", "email": "jane.smith@example.com"}, rid=rid)
    assert [p["profile_id"] for p in res["data"]] == ["prf_001"]    # args ignored
