from sqlalchemy.orm import Session
from app.db.base import Base
from app.db.guards import drop_triggers, ensure_triggers


def reset_all_tables(db: Session) -> None:
    """Demo reset: wipe every table (FK-safe order) and re-install append-only triggers."""
    db.rollback()
    drop_triggers(db)
    for table in reversed(Base.metadata.sorted_tables):
        db.execute(table.delete())
    db.commit()
    ensure_triggers(db)
