from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, declarative_base
from .config import settings

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

def run_compat_migrations(bind=engine):
    """Add this release's nullable columns without replacing an existing database."""
    with bind.begin() as connection:
        message_columns = {column["name"] for column in inspect(connection).get_columns("messages")}
        if "approval_id" not in message_columns:
            connection.execute(text("ALTER TABLE messages ADD COLUMN approval_id VARCHAR REFERENCES approvals(id)"))
        approval_columns = {column["name"] for column in inspect(connection).get_columns("approvals")}
        if "original_draft" not in approval_columns:
            connection.execute(text("ALTER TABLE approvals ADD COLUMN original_draft JSON"))
        if "actor" not in approval_columns:
            connection.execute(text("ALTER TABLE approvals ADD COLUMN actor VARCHAR"))

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
