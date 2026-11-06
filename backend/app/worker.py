from .core.database import SessionLocal
from .services.documents import process_document

def index_document(document_id: str):
    db = SessionLocal()
    try:
        process_document(document_id, db)
    finally:
        db.close()
