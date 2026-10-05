from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.security import verify_password, create_access_token
from app.db.models import StaffUser
from app.db.session import get_db
from app.api.deps import get_current_user

router = APIRouter(prefix="/auth", tags=["Authentication"])

# Mock, documented credentials for reviewers (README). Never real credentials.
DEMO_PASSWORDS = {
    "alex.analyst": "analyst_password123!", "jordan.approver": "approver_password123!",
    "morgan.approver": "approver_password123!", "sam.auditor": "auditor_password123!",
}


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(StaffUser).filter(StaffUser.username == req.username).first()
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")
    token = create_access_token({"sub": user.id, "role": user.role, "username": user.username})
    return {"access_token": token, "token_type": "bearer",
            "user": {"id": user.id, "username": user.username, "role": user.role, "full_name": user.full_name}}


@router.get("/me")
def get_me(user: StaffUser = Depends(get_current_user)):
    return {"id": user.id, "username": user.username, "role": user.role, "full_name": user.full_name}


@router.get("/test-accounts")
def list_test_accounts(db: Session = Depends(get_db)):
    """Seeded mock accounts shown on the login screen for reviewers (FR UI-1). Disabled with SHOW_TEST_ACCOUNTS=false."""
    if not settings.SHOW_TEST_ACCOUNTS:
        return []
    return [{"id": u.id, "username": u.username, "role": u.role, "full_name": u.full_name,
             "sample_password": DEMO_PASSWORDS.get(u.username)} for u in db.query(StaffUser).order_by(StaffUser.role, StaffUser.username).all()]
