import re
from pathlib import Path
from datetime import datetime, timezone
from pypdf import PdfReader
from docx import Document as DocxDocument
from sqlalchemy.orm import Session
from ..models import Document, Chunk, Task
from .retrieval import embed
from .audit import record

def split_text(text: str, locator: str = "正文"):
    text = text.replace("\r", "")
    # Markdown 标题是天然语义边界；普通文档则按空行与长度切分。
    sections = re.split(r"\n(?=#{1,6}\s)|\n{2,}", text)
    chunks, current = [], ""
    for section in sections:
        section = section.strip()
        if not section:
            continue
        if section.startswith("#"):
            if current:
                chunks.append((current, locator))
            current = section
        elif len(current) + len(section) > 420 and current:
            chunks.append((current, locator))
            current = section
        else:
            current = f"{current}\n\n{section}".strip()
    if current:
        chunks.append((current, locator))
    return chunks

def parse_file(path: Path, file_type: str):
    suffix = file_type.lower()
    if suffix in {".txt", ".md"}:
        return split_text(path.read_text(encoding="utf-8"))
    if suffix == ".pdf":
        output = []
        for index, page in enumerate(PdfReader(str(path)).pages, 1):
            output.extend(split_text(page.extract_text() or "", f"第 {index} 页"))
        return output
    if suffix == ".docx":
        doc = DocxDocument(str(path))
        return split_text("\n\n".join(p.text for p in doc.paragraphs))
    raise ValueError("仅支持 PDF、DOCX、TXT、MD 文件")

def process_document(document_id: str, db: Session):
    document = db.get(Document, document_id)
    if not document:
        return
    task = db.query(Task).filter(Task.entity_id == document_id, Task.kind == "document_index").order_by(Task.created_at.desc()).first()
    try:
        document.status, document.stage, document.error = "processing", "parsing", None
        if task:
            task.status, task.stage, task.progress = "running", "parsing", 25
        db.commit()
        path = Path(document.file_type.split("::", 1)[1]) if "::" in document.file_type else None
        actual_type = document.file_type.split("::", 1)[0]
        if path is None or not path.exists():
            raise ValueError("原始文件不存在，无法建立索引")
        pieces = parse_file(path, actual_type)
        if not pieces:
            raise ValueError("文档没有可索引的文本内容")
        document.stage = "indexing"
        if task:
            task.stage, task.progress = "indexing", 65
        db.query(Chunk).filter(Chunk.document_id == document.id).delete()
        for ordinal, (content, locator) in enumerate(pieces):
            db.add(Chunk(document_id=document.id, ordinal=ordinal, content=content, locator=locator, embedding=embed(content)))
        document.chunk_count = len(pieces)
        document.status, document.stage = "ready", "ready"
        if task:
            task.status, task.stage, task.progress = "succeeded", "ready", 100
        record(db, "document", "index_succeeded", {"document_id":document.id,"chunks":len(pieces)}, task.id if task else None)
        db.commit()
    except Exception as exc:
        db.rollback()
        document = db.get(Document, document_id)
        document.status, document.stage, document.error = "failed", "failed", str(exc)
        if task:
            task = db.get(Task, task.id)
            task.status, task.stage, task.error = "failed", "failed", str(exc)
        record(db, "document", "index_failed", {"document_id":document_id,"error":str(exc)}, task.id if task else None)
        db.commit()

def create_document(db: Session, filename: str, suffix: str, path: Path, content_hash: str):
    document = Document(filename=filename, file_type=f"{suffix}::{path}", content_hash=content_hash)
    db.add(document)
    db.flush()
    task = Task(kind="document_index", entity_id=document.id, idempotency_key=f"index:{content_hash}")
    db.add(task)
    record(db, "document", "uploaded", {"document_id":document.id,"filename":filename}, task.id)
    db.commit()
    return document, task
