from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session
from app.db.models import ActivityLog

class ActivityLogAdapter:
    @staticmethod
    def get_by_id(db: Session, log_id: str) -> Optional[Dict[str, Any]]:
        log = db.query(ActivityLog).filter(ActivityLog.log_id == log_id).first()
        if not log:
            return None
        return {
            "log_id": log.log_id,
            "profile_id": log.profile_id,
            "event_type": log.event_type,
            "timestamp": log.timestamp.isoformat() if log.timestamp else None,
            "details": log.details,
            "ip_address": log.ip_address,
            "user_agent": log.user_agent,
            "risk_signal": log.risk_signal,
            "retention_class": log.retention_class
        }

    @staticmethod
    def search_by_profile_id(db: Session, profile_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        logs = db.query(ActivityLog).filter(ActivityLog.profile_id == profile_id).limit(limit).all()
        return [
            {
                "log_id": l.log_id,
                "profile_id": l.profile_id,
                "event_type": l.event_type,
                "timestamp": l.timestamp.isoformat() if l.timestamp else None,
                "details": l.details,
                "ip_address": l.ip_address,
                "user_agent": l.user_agent,
                "risk_signal": l.risk_signal,
                "retention_class": l.retention_class
            }
            for l in logs
        ]

    @staticmethod
    def anonymize(db: Session, log_id: str) -> Dict[str, Any]:
        """Replaces personal identifiers with tombstone tokens per policy."""
        log = db.query(ActivityLog).filter(ActivityLog.log_id == log_id).first()
        if not log:
            raise ValueError(f"Activity log {log_id} not found")
        log.profile_id = "[DELETED_SUBJECT]"
        log.details = "[ANONYMIZED_ACTIVITY_RECORD]"
        log.ip_address = "0.0.0.0"
        log.user_agent = "[REDACTED]"
        db.flush()
        return ActivityLogAdapter.get_by_id(db, log_id)

    @staticmethod
    def delete(db: Session, log_id: str) -> bool:
        log = db.query(ActivityLog).filter(ActivityLog.log_id == log_id).first()
        if not log:
            return False
        db.delete(log)
        db.flush()
        return True
