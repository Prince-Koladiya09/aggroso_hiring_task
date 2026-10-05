from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session
from app.db.models import Profile

class ProfileAdapter:
    @staticmethod
    def get_by_id(db: Session, profile_id: str) -> Optional[Dict[str, Any]]:
        prf = db.query(Profile).filter(Profile.profile_id == profile_id).first()
        if not prf:
            return None
        return {
            "profile_id": prf.profile_id,
            "account_id": prf.account_id,
            "full_name": prf.full_name,
            "email": prf.email,
            "phone": prf.phone,
            "dob": prf.dob,
            "address": prf.address,
            "marketing_opt_in": prf.marketing_opt_in,
            "account_status": prf.account_status,
            "password_hash": prf.password_hash,
            "risk_score": prf.risk_score,
            "fraud_flag": prf.fraud_flag,
            "internal_notes": prf.internal_notes,
            "legal_hold": prf.legal_hold,
            "created_at": prf.created_at.isoformat() if prf.created_at else None
        }

    @staticmethod
    def search_by_identifier(db: Session, email: Optional[str] = None, account_id: Optional[str] = None, profile_id: Optional[str] = None) -> List[Dict[str, Any]]:
        query = db.query(Profile)
        conditions = []
        if profile_id:
            conditions.append(Profile.profile_id == profile_id)
        if email:
            conditions.append(Profile.email == email.strip().lower())
        if account_id:
            conditions.append(Profile.account_id == account_id.strip())

        if not conditions:
            return []

        results = query.filter(*conditions).all()
        return [
            {
                "profile_id": p.profile_id,
                "account_id": p.account_id,
                "full_name": p.full_name,
                "email": p.email,
                "phone": p.phone,
                "dob": p.dob,
                "address": p.address,
                "marketing_opt_in": p.marketing_opt_in,
                "account_status": p.account_status,
                "password_hash": p.password_hash,
                "risk_score": p.risk_score,
                "fraud_flag": p.fraud_flag,
                "internal_notes": p.internal_notes,
                "legal_hold": p.legal_hold,
                "created_at": p.created_at.isoformat() if p.created_at else None
            }
            for p in results
        ]

    @staticmethod
    def _to_dict(p) -> Dict[str, Any]:
        return {
            "profile_id": p.profile_id, "account_id": p.account_id, "full_name": p.full_name, "email": p.email,
            "phone": p.phone, "dob": p.dob, "address": p.address, "marketing_opt_in": p.marketing_opt_in,
            "account_status": p.account_status, "password_hash": p.password_hash, "risk_score": p.risk_score,
            "fraud_flag": p.fraud_flag, "internal_notes": p.internal_notes, "legal_hold": p.legal_hold,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        }

    @staticmethod
    def lookup_for_verification(db: Session, email: Optional[str] = None, account_id: Optional[str] = None,
                                name: Optional[str] = None) -> List[Dict[str, Any]]:
        """Candidate profiles for identity verification (FR-204).
        Exact email / account-ID matches first; if none, fall back to a normalised-name match so that
        two people with the same name are reported as ambiguous instead of being auto-picked."""
        found: Dict[str, Any] = {}
        if email:
            for p in db.query(Profile).filter(Profile.email == email.strip().lower()).all():
                found[p.profile_id] = p
        if account_id:
            for p in db.query(Profile).filter(Profile.account_id == account_id.strip()).all():
                found[p.profile_id] = p
        if not found and name:
            norm = "".join(name.lower().split())
            for p in db.query(Profile).all():
                if "".join(p.full_name.lower().split()) == norm:
                    found[p.profile_id] = p
        return [ProfileAdapter._to_dict(p) for p in found.values()]

    @staticmethod
    def update_field(db: Session, profile_id: str, field: str, new_value: Any) -> Dict[str, Any]:
        prf = db.query(Profile).filter(Profile.profile_id == profile_id).first()
        if not prf:
            raise ValueError(f"Profile {profile_id} not found")
        if not hasattr(prf, field):
            raise ValueError(f"Unknown profile field {field}")

        if field == "marketing_opt_in" and isinstance(new_value, str):
            new_value = new_value.strip().lower() in ("1", "true", "yes", "y", "on")
        setattr(prf, field, new_value)
        db.flush()
        return ProfileAdapter.get_by_id(db, profile_id)

    @staticmethod
    def delete(db: Session, profile_id: str) -> bool:
        prf = db.query(Profile).filter(Profile.profile_id == profile_id).first()
        if not prf:
            return False
        db.delete(prf)
        db.flush()
        return True
