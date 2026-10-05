from typing import List, Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.db.models import StaffUser
from app.core.security import decode_access_token

security = HTTPBearer(auto_error=False)


def get_current_user(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
                     db: Session = Depends(get_db)) -> StaffUser:
    """Role is derived server-side from the signed token + DB row on every call (NFR-1). No anonymous fallback."""
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    payload = decode_access_token(credentials.credentials)
    if not payload or "sub" not in payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    user = db.query(StaffUser).filter(StaffUser.id == payload["sub"]).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


def require_role(allowed_roles: List[str]):
    def role_checker(current_user: StaffUser = Depends(get_current_user)) -> StaffUser:
        if current_user.role not in allowed_roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail=f"Forbidden: role '{current_user.role}' may not perform this action (allowed: {', '.join(allowed_roles)}).")
        return current_user
    return role_checker
