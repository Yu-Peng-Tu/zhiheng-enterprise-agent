import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, Text, Integer, Float, Boolean, JSON, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from .core.database import Base

def uid():
    return str(uuid.uuid4())

def now():
    return datetime.now(timezone.utc)

class Document(Base):
    __tablename__ = "documents"
    id = Column(String, primary_key=True, default=uid)
    filename = Column(String, nullable=False)
    file_type = Column(String, nullable=False)
    content_hash = Column(String, nullable=False, unique=True)
    version = Column(Integer, default=1)
    status = Column(String, default="pending")
    stage = Column(String, default="uploaded")
    error = Column(Text)
    chunk_count = Column(Integer, default=0)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=now)
    chunks = relationship("Chunk", back_populates="document", cascade="all, delete-orphan")

class Chunk(Base):
    __tablename__ = "chunks"
    id = Column(String, primary_key=True, default=uid)
    document_id = Column(String, ForeignKey("documents.id"), nullable=False)
    ordinal = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    locator = Column(String, default="正文")
    embedding = Column(JSON, nullable=False)
    active = Column(Boolean, default=True)
    document = relationship("Document", back_populates="chunks")

class Task(Base):
    __tablename__ = "tasks"
    id = Column(String, primary_key=True, default=uid)
    kind = Column(String, nullable=False)
    entity_id = Column(String)
    status = Column(String, default="queued")
    stage = Column(String, default="queued")
    progress = Column(Integer, default=0)
    error = Column(Text)
    retry_count = Column(Integer, default=0)
    idempotency_key = Column(String, unique=True)
    created_at = Column(DateTime(timezone=True), default=now)
    updated_at = Column(DateTime(timezone=True), default=now, onupdate=now)

class Message(Base):
    __tablename__ = "messages"
    id = Column(String, primary_key=True, default=uid)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    citations = Column(JSON, default=list)
    mode = Column(String, default="offline")
    latency_ms = Column(Integer, default=0)
    token_usage = Column(JSON, default=dict)
    approval_id = Column(String, ForeignKey("approvals.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=now)
    approval = relationship("Approval")

class Order(Base):
    __tablename__ = "orders"
    id = Column(String, primary_key=True)
    customer_name = Column(String, nullable=False)
    product = Column(String, nullable=False)
    status = Column(String, nullable=False)
    amount = Column(Float, nullable=False)
    ordered_at = Column(String, nullable=False)
    delivered_at = Column(String)
    address = Column(String, default="模拟地址")
    logistics = Column(String, default="模拟物流")

class Ticket(Base):
    __tablename__ = "tickets"
    id = Column(String, primary_key=True)
    order_id = Column(String, ForeignKey("orders.id"), nullable=False)
    ticket_type = Column(String, nullable=False)
    reason = Column(Text, nullable=False)
    priority = Column(String, default="normal")
    status = Column(String, default="open")
    idempotency_key = Column(String, unique=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=now)

class Approval(Base):
    __tablename__ = "approvals"
    id = Column(String, primary_key=True, default=uid)
    order_id = Column(String, ForeignKey("orders.id"), nullable=False)
    draft = Column(JSON, nullable=False)
    original_draft = Column(JSON, nullable=True)
    status = Column(String, default="pending")
    decision_reason = Column(Text)
    actor = Column(String, nullable=True)
    idempotency_key = Column(String, unique=True, nullable=False)
    ticket_id = Column(String, ForeignKey("tickets.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=now)
    decided_at = Column(DateTime(timezone=True))

class ToolCall(Base):
    __tablename__ = "tool_calls"
    id = Column(String, primary_key=True, default=uid)
    tool_name = Column(String, nullable=False)
    parameters = Column(JSON, default=dict)
    status = Column(String, default="pending")
    result = Column(JSON)
    error = Column(Text)
    latency_ms = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=now)

class AuditEvent(Base):
    __tablename__ = "audit_events"
    id = Column(String, primary_key=True, default=uid)
    task_id = Column(String)
    category = Column(String, nullable=False)
    action = Column(String, nullable=False)
    detail = Column(JSON, default=dict)
    duration_ms = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=now)

class EvalRun(Base):
    __tablename__ = "eval_runs"
    id = Column(String, primary_key=True, default=uid)
    dataset_version = Column(String, default="retail-v1")
    app_version = Column(String, default="mvp-1.0")
    status = Column(String, default="running")
    metrics = Column(JSON, default=dict)
    results = Column(JSON, default=list)
    token_usage = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), default=now)

class Feedback(Base):
    __tablename__ = "feedback"
    id = Column(String, primary_key=True, default=uid)
    message_id = Column(String, ForeignKey("messages.id"), nullable=False)
    helpful = Column(Boolean, nullable=False)
    reason = Column(Text)
    created_at = Column(DateTime(timezone=True), default=now)
