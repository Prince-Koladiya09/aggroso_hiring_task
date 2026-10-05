from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.agent.orchestrator import AgentOrchestrator
from app.api.deps import get_current_user, require_role
from app.approvals.validation import active_plan
from app.db.models import Request, Plan, ProposedAction, ToolCall, LLMRun, StaffUser
from app.db.session import get_db
from app.workflow.missing_info import missing_verification_items

router = APIRouter(prefix="/requests/{id}", tags=["Agent Workflow"])


@router.post("/agent/interpret")
def interpret_request(id: str, db: Session = Depends(get_db), user: StaffUser = Depends(require_role(["analyst"]))):
    """Agent reads the free text, flags type mismatch, lists missing verification info (deterministic checker wins)."""
    return AgentOrchestrator(db).interpret_only(id, user.id, user.role)


@router.post("/agent/run")
def trigger_agent_planning(id: str, db: Session = Depends(get_db), user: StaffUser = Depends(require_role(["analyst"]))):
    return AgentOrchestrator(db).run_planning_workflow(request_id=id, actor_id=user.id, actor_role=user.role)


@router.get("/plan")
def get_current_plan(id: str, db: Session = Depends(get_db), user: StaffUser = Depends(get_current_user)):
    req = db.query(Request).filter(Request.id == id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    plan = active_plan(db, id)
    if not plan:
        return {"plan": None, "message": "No active plan yet. Run the agent once verification has passed.",
                "missing_verification": missing_verification_items(db, req)}
    actions = db.query(ProposedAction).filter(ProposedAction.plan_id == plan.id).order_by(ProposedAction.created_at, ProposedAction.id).all()
    return {
        "id": plan.id, "version": plan.version, "source": plan.source, "prompt_version": plan.prompt_version,
        "inventory_version": req.inventory_version, "interpretation": plan.interpretation_json, "plan": plan.plan_json,
        "proposed_actions": [{"id": a.id, "kind": a.kind, "source": a.source, "record_id": a.record_id, "field": a.field,
                              "before_value": a.before_value, "after_value": a.after_value, "strategy": a.strategy,
                              "risk_text": a.risk_text, "rule_ids": a.rule_ids, "status": a.status} for a in actions],
        "created_at": plan.created_at.isoformat() if plan.created_at else None,
    }


@router.get("/tool-calls")
def get_request_tool_calls(id: str, db: Session = Depends(get_db), user: StaffUser = Depends(get_current_user)):
    calls = db.query(ToolCall).filter(ToolCall.request_id == id).order_by(ToolCall.at.desc()).all()
    return [{"id": c.id, "tool": c.tool, "status": c.status, "args": c.args_json, "denial_reason": c.denial_reason,
             "result_summary": c.result_summary, "rows": c.rows, "duration_ms": c.duration_ms, "caller": c.caller,
             "correlation_id": c.correlation_id, "at": c.at.isoformat() if c.at else None} for c in calls]


@router.get("/llm-runs")
def get_request_llm_runs(id: str, db: Session = Depends(get_db), user: StaffUser = Depends(get_current_user)):
    runs = db.query(LLMRun).filter(LLMRun.request_id == id).order_by(LLMRun.at.desc()).all()
    return [{"id": r.id, "stage": r.stage, "model": r.model, "prompt_version": r.prompt_version, "input_hash": r.input_hash[:16],
             "valid": r.valid, "tokens_in": r.tokens_in, "tokens_out": r.tokens_out, "latency_ms": r.latency_ms,
             "error": r.error, "at": r.at.isoformat() if r.at else None} for r in runs]
