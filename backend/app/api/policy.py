from fastapi import APIRouter
from app.policy.loader import get_policy

router = APIRouter(prefix="/policy", tags=["Organizational Policy"])

@router.get("")
def get_active_policy():
    policy = get_policy()
    return policy.model_dump()
