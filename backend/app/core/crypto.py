"""Sealing of pre-images (FR-707). Demo-grade: Fernet key derived from SECRET_KEY."""
import base64
import hashlib
import json
from typing import Any, Optional
from cryptography.fernet import Fernet, InvalidToken
from app.core.config import settings


def _fernet() -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.SECRET_KEY.encode()).digest())
    return Fernet(key)


def seal(data: Any) -> dict:
    token = _fernet().encrypt(json.dumps(data, default=str).encode()).decode()
    return {"sealed": token}


def unseal(blob: Optional[dict]) -> Optional[Any]:
    if not blob:
        return None
    token = blob.get("sealed") if isinstance(blob, dict) else None
    if not token:
        return blob  # legacy / unsealed value
    try:
        return json.loads(_fernet().decrypt(token.encode()).decode())
    except (InvalidToken, ValueError):
        return {"error": "pre-image could not be unsealed (key changed?)"}
