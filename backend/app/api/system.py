from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.api.deps import require_role, get_current_user
from app.core.config import settings
from app.db.models import StaffUser
from app.db.seed_data import seed_database
from app.db.session import get_db

router = APIRouter(prefix="/system", tags=["System & Controls"])
APP_VERSION = "1.1.0"


@router.get("/health")
def health_check():
    return {"status": "healthy", "version": APP_VERSION, "app_env": settings.APP_ENV}


@router.get("/flags")
def flags(user: StaffUser = Depends(get_current_user)):
    return {"fault_injection_enabled": settings.FAULT_INJECTION_ENABLED, "simulate_llm_outage": settings.SIMULATE_LLM_OUTAGE,
            "mock_llm_forced": settings.FORCE_MOCK_LLM, "llm_provider": settings.LLM_PROVIDER, "llm_model": settings.LLM_MODEL,
            "demo_reset_enabled": settings.DEMO_RESET_ENABLED}


@router.post("/reset-demo")
def reset_demo_data(db: Session = Depends(get_db), user: StaffUser = Depends(require_role(["approver"]))):
    if not settings.DEMO_RESET_ENABLED:
        raise HTTPException(status_code=403, detail="Demo reset is disabled in this environment.")
    seed_database(db, force_reset=True)
    return {"message": "Demo data re-seeded (scenarios S1-S10). All sessions remain valid; audit chain restarted."}


@router.post("/toggle-fault-injection")
def toggle_fault_injection(enabled: bool, user: StaffUser = Depends(require_role(["approver", "analyst"]))):
    settings.FAULT_INJECTION_ENABLED = enabled
    return {"fault_injection_enabled": settings.FAULT_INJECTION_ENABLED}


@router.post("/toggle-llm-outage")
def toggle_llm_outage(enabled: bool, user: StaffUser = Depends(require_role(["approver", "analyst"]))):
    """S10: simulate the LLM being unavailable so the deterministic fallback planner is used."""
    settings.SIMULATE_LLM_OUTAGE = enabled
    return {"simulate_llm_outage": settings.SIMULATE_LLM_OUTAGE}


@router.post("/toggle-mock-llm")
def toggle_mock_llm(force_mock: bool, user: StaffUser = Depends(require_role(["approver", "analyst"]))):
    settings.FORCE_MOCK_LLM = force_mock
    return {"force_mock_llm": settings.FORCE_MOCK_LLM}
