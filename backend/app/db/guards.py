"""Append-only / immutability guards (FR-901, FR-1002).

* ORM level: UPDATE/DELETE of audit_events and fulfilment_records through the session raises.
* SQLite level: triggers abort UPDATE/DELETE on audit_events even for raw SQL.
Demo reset temporarily removes the triggers inside `reset_all_tables`.
"""
from sqlalchemy import event, DDL, text
from sqlalchemy.orm import Session
from app.db.models import AuditEvent, FulfilmentRecord


class ImmutableRecordError(RuntimeError):
    pass


@event.listens_for(AuditEvent, "before_update")
def _audit_no_update(mapper, connection, target):
    raise ImmutableRecordError("audit_events is append-only: updates are not permitted (POL-AUD-1)")


@event.listens_for(AuditEvent, "before_delete")
def _audit_no_delete(mapper, connection, target):
    raise ImmutableRecordError("audit_events is append-only: deletes are not permitted (POL-AUD-1)")


@event.listens_for(FulfilmentRecord, "before_update")
def _record_no_update(mapper, connection, target):
    raise ImmutableRecordError("fulfilment_records are immutable once generated; add an addendum event instead")


@event.listens_for(FulfilmentRecord, "before_delete")
def _record_no_delete(mapper, connection, target):
    raise ImmutableRecordError("fulfilment_records are immutable and cannot be deleted")


_TRIGGERS = {
    "audit_events_no_update": "BEFORE UPDATE ON audit_events",
    "audit_events_no_delete": "BEFORE DELETE ON audit_events",
    "fulfilment_records_no_update": "BEFORE UPDATE ON fulfilment_records",
    "fulfilment_records_no_delete": "BEFORE DELETE ON fulfilment_records",
}


def _trigger_sql(name: str, clause: str) -> str:
    return (f"CREATE TRIGGER IF NOT EXISTS {name} {clause} "
            f"BEGIN SELECT RAISE(ABORT, 'append-only / immutable table'); END;")


def install_triggers_on_create(table, name_prefix: str):
    for name, clause in _TRIGGERS.items():
        if name.startswith(name_prefix):
            event.listen(table, "after_create", DDL(_trigger_sql(name, clause)).execute_if(dialect="sqlite"))


install_triggers_on_create(AuditEvent.__table__, "audit_events")
install_triggers_on_create(FulfilmentRecord.__table__, "fulfilment_records")


def ensure_triggers(db: Session) -> None:
    if db.get_bind().dialect.name != "sqlite":
        return
    for name, clause in _TRIGGERS.items():
        db.execute(text(_trigger_sql(name, clause)))
    db.commit()


def drop_triggers(db: Session) -> None:
    if db.get_bind().dialect.name != "sqlite":
        return
    for name in _TRIGGERS:
        db.execute(text(f"DROP TRIGGER IF EXISTS {name}"))
    db.commit()
