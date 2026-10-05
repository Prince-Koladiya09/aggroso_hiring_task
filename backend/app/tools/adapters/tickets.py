from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session
from sqlalchemy import or_
from app.db.models import Ticket

class TicketAdapter:
    @staticmethod
    def get_by_id(db: Session, ticket_id: str) -> Optional[Dict[str, Any]]:
        t = db.query(Ticket).filter(Ticket.ticket_id == ticket_id).first()
        if not t:
            return None
        return {
            "ticket_id": t.ticket_id,
            "requester_email": t.requester_email,
            "requester_profile_id": t.requester_profile_id,
            "subject": t.subject,
            "body": t.body,
            "status": t.status,
            "category": t.category,
            "assigned_agent": t.assigned_agent,
            "agent_id": t.agent_id,
            "internal_notes": t.internal_notes,
            "legal_hold": t.legal_hold,
            "retention_class": t.retention_class,
            "created_at": t.created_at.isoformat() if t.created_at else None
        }

    @staticmethod
    def search(
        db: Session,
        email: Optional[str] = None,
        profile_id: Optional[str] = None,
        mention_query: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        query = db.query(Ticket)
        filters = []
        if email:
            filters.append(Ticket.requester_email == email.strip().lower())
        if profile_id:
            filters.append(Ticket.requester_profile_id == profile_id)

        if mention_query:
            # Mention search flags tickets mentioning data subject
            query = query.filter(or_(*filters, Ticket.body.ilike(f"%{mention_query}%")))
        elif filters:
            query = query.filter(or_(*filters))
        else:
            return []

        results = query.limit(limit).all()
        return [
            {
                "ticket_id": t.ticket_id,
                "requester_email": t.requester_email,
                "requester_profile_id": t.requester_profile_id,
                "subject": t.subject,
                "body": t.body,
                "status": t.status,
                "category": t.category,
                "assigned_agent": t.assigned_agent,
                "agent_id": t.agent_id,
                "internal_notes": t.internal_notes,
                "legal_hold": t.legal_hold,
                "retention_class": t.retention_class,
                "created_at": t.created_at.isoformat() if t.created_at else None
            }
            for t in results
        ]

    @staticmethod
    def delete(db: Session, ticket_id: str) -> bool:
        t = db.query(Ticket).filter(Ticket.ticket_id == ticket_id).first()
        if not t:
            return False
        db.delete(t)
        db.flush()
        return True
