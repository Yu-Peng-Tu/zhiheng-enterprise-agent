from sqlalchemy.orm import Session
from ..models import AuditEvent

def record(db: Session, category: str, action: str, detail=None, task_id=None, duration_ms=0):
    event = AuditEvent(category=category, action=action, detail=detail or {}, task_id=task_id, duration_ms=duration_ms)
    db.add(event)
    return event
