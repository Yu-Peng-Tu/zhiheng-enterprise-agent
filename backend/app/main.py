import asyncio
import hashlib
import json
import re
import time
import uuid
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, UploadFile, File, BackgroundTasks, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, PlainTextResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from .core.config import settings, UPLOAD_DIR
from .core.database import get_db, SessionLocal
from .models import Document, Chunk, Task, Message, Order, Ticket, Approval, ToolCall, AuditEvent, EvalRun, Feedback
from .schemas import ChatRequest, OrderQuery, TicketDraftRequest, ApprovalDecision, FeedbackRequest, ReportRequest
from .services.seed import seed_database
from .services.documents import create_document, process_document
from .services.retrieval import retrieve
from .services.llm import llm_client
from .services.tools import query_order, create_ticket_draft, decide_approval, serialize_order, serialize_approval, ApprovalConflict, ORDER_STATES, TICKET_TYPES
from .services.evaluation import run_evaluation
from .services.audit import record
from .worker import index_document

@asynccontextmanager
async def lifespan(app: FastAPI):
    db = SessionLocal()
    try:
        seed_database(db)
    finally:
        db.close()
    yield

app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins.split(","), allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.exception_handler(LookupError)
def not_found_handler(request: Request, exc: LookupError):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=404, content={"detail":str(exc)})

@app.exception_handler(ApprovalConflict)
def approval_conflict_handler(request: Request, exc: ApprovalConflict):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=409, content={"detail":str(exc)})

@app.exception_handler(ValueError)
def value_handler(request: Request, exc: ValueError):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=422, content={"detail":str(exc)})

def doc_json(item: Document):
    return {"id":item.id,"filename":item.filename,"file_type":item.file_type.split("::",1)[0],"version":item.version,"status":item.status,"stage":item.stage,"error":item.error,"chunk_count":item.chunk_count,"active":item.active,"created_at":item.created_at.isoformat() if item.created_at else None}

def task_json(item: Task):
    return {"id":item.id,"kind":item.kind,"entity_id":item.entity_id,"status":item.status,"stage":item.stage,"progress":item.progress,"error":item.error,"retry_count":item.retry_count,"created_at":item.created_at.isoformat() if item.created_at else None,"updated_at":item.updated_at.isoformat() if item.updated_at else None}

def message_json(item: Message, approval: Approval | None = None):
    return {"id":item.id,"question":item.question,"answer":item.answer,"citations":item.citations,"mode":item.mode,"latency_ms":item.latency_ms,"token_usage":item.token_usage,"approval":serialize_approval(approval) if approval else None,"created_at":item.created_at.isoformat() if item.created_at else None}

def dispatch_document(document_id: str, background: BackgroundTasks):
    if settings.redis_url:
        from redis import Redis
        from rq import Queue
        Queue(connection=Redis.from_url(settings.redis_url)).enqueue(index_document, document_id)
    else:
        background.add_task(index_document, document_id)

@app.get("/api/health")
def health():
    return {"status":"ok","name":settings.app_name,"version":"1.0.0","llm_enabled":llm_client.enabled}

@app.get("/api/dashboard")
def dashboard(db: Session = Depends(get_db)):
    docs = db.query(Document).filter(Document.active.is_(True)).count()
    chunks = db.query(Chunk).filter(Chunk.active.is_(True)).count()
    tickets = db.query(Ticket).count()
    pending = db.query(Approval).filter(Approval.status == "pending").count()
    latest_eval = db.query(EvalRun).order_by(EvalRun.created_at.desc()).first()
    latest_eval_data = None
    if latest_eval:
        latest_eval_data = {
            "id":latest_eval.id,
            "dataset_version":latest_eval.dataset_version,
            "app_version":latest_eval.app_version,
            "created_at":latest_eval.created_at.isoformat() if latest_eval.created_at else None,
            "metrics":latest_eval.metrics,
        }
    return {"documents":docs,"chunks":chunks,"tickets":tickets,"pending_approvals":pending,"orders":db.query(Order).count(),"latest_eval":latest_eval_data}

@app.get("/api/documents")
def documents(db: Session = Depends(get_db)):
    return [doc_json(item) for item in db.query(Document).order_by(Document.created_at.desc()).all()]

@app.post("/api/documents", status_code=202)
async def upload_document(background: BackgroundTasks, file: UploadFile = File(...), db: Session = Depends(get_db)):
    suffix = Path(file.filename).suffix.lower()
    if suffix not in {".pdf",".docx",".txt",".md"}:
        raise ValueError("仅支持 PDF、DOCX、TXT、MD 文件")
    content = await file.read()
    if not content:
        raise ValueError("不能上传空文件")
    if len(content) > 10 * 1024 * 1024:
        raise ValueError("单文件不能超过 10 MB")
    digest = hashlib.sha256(content).hexdigest()
    if db.query(Document).filter(Document.content_hash == digest).first():
        raise HTTPException(status_code=409, detail="相同内容的文档已存在，无需重复索引")
    path = UPLOAD_DIR / f"{uuid.uuid4().hex}{suffix}"
    path.write_bytes(content)
    document, task = create_document(db, file.filename, suffix, path, digest)
    dispatch_document(document.id, background)
    return {"document":doc_json(document),"task":task_json(task)}

@app.get("/api/documents/{document_id}")
def document_detail(document_id: str, db: Session = Depends(get_db)):
    document = db.get(Document, document_id)
    if not document:
        raise LookupError("文档不存在")
    chunks = db.query(Chunk).filter(Chunk.document_id == document_id).order_by(Chunk.ordinal).all()
    return {"document":doc_json(document),"chunks":[{"id":c.id,"ordinal":c.ordinal,"content":c.content,"locator":c.locator,"active":c.active} for c in chunks]}

@app.post("/api/documents/{document_id}/reindex", status_code=202)
def reindex_document(document_id: str, background: BackgroundTasks, db: Session = Depends(get_db)):
    document = db.get(Document, document_id)
    if not document:
        raise LookupError("文档不存在")
    task = db.query(Task).filter(Task.entity_id == document_id,Task.kind == "document_index").order_by(Task.created_at.desc()).first()
    if task:
        task.status,task.stage,task.progress,task.error = "queued","queued",0,None
        task.retry_count += 1
    document.status,document.stage,document.error = "pending","uploaded",None
    db.commit()
    dispatch_document(document_id, background)
    return {"document":doc_json(document),"task":task_json(task) if task else None}

@app.delete("/api/documents/{document_id}")
def delete_document(document_id: str, db: Session = Depends(get_db)):
    document = db.get(Document, document_id)
    if not document:
        raise LookupError("文档不存在")
    document.active,document.status = False,"deleted"
    db.query(Chunk).filter(Chunk.document_id == document_id).update({"active":False})
    record(db,"document","deactivated",{"document_id":document_id})
    db.commit()
    return {"ok":True,"document":doc_json(document)}

@app.post("/api/chat")
def chat(payload: ChatRequest, db: Session = Depends(get_db)):
    started = time.perf_counter()
    question = payload.question
    citations, approval = [], None
    order_match = re.search(r"SQ\d{6}", question, re.I)
    if order_match:
        order_id = order_match.group(0).upper()
        order, call = query_order(db, order_id)
        if not order:
            answer = "未找到该订单，请核对订单号。订单号应为 SQ 加 6 位数字。"
        elif re.search(r"工单|退货|退款|换货|维修", question):
            ticket_type = "refund" if "退款" in question else "return" if "退货" in question else "exchange" if "换货" in question else "other"
            approval = create_ticket_draft(db,{"order_id":order_id,"ticket_type":ticket_type,"reason":question,"priority":"high" if "未收到" in question else "normal"})
            answer = f"已核对订单 {order_id}（{order.product}，{ORDER_STATES.get(order.status,order.status)}），并生成工单草案。请检查参数并审批；审批前不会创建工单。"
        else:
            answer = f"订单 {order_id}：{order.product}\n状态：{ORDER_STATES.get(order.status,order.status)}\n金额：¥{order.amount:.2f}\n物流：{order.logistics}\n下单时间：{order.ordered_at}"
        mode, usage = "deterministic-tool", {"prompt_tokens":0,"completion_tokens":0}
    else:
        citations = retrieve(db, question)
        answer, mode, usage = llm_client.grounded_answer(question, citations)
    message = Message(question=question,answer=answer,citations=citations,mode=mode,latency_ms=int((time.perf_counter()-started)*1000),token_usage=usage,approval_id=approval.id if approval else None)
    db.add(message)
    db.flush()
    result = message_json(message, approval)
    record(db,"chat","message_created",{"message_id":message.id,"mode":mode,"citation_count":len(citations)},duration_ms=message.latency_ms)
    db.commit()
    return result

@app.get("/api/messages")
def messages(db: Session = Depends(get_db)):
    items = db.query(Message).order_by(Message.created_at.desc()).limit(30).all()
    approval_ids = {item.approval_id for item in items if item.approval_id}
    approval_map = {item.id:item for item in db.query(Approval).filter(Approval.id.in_(approval_ids)).all()} if approval_ids else {}
    return [message_json(item, approval_map.get(item.approval_id)) for item in items]

@app.post("/api/tools/orders/query")
def order_query(payload: OrderQuery, db: Session = Depends(get_db)):
    order, call = query_order(db,payload.order_id)
    if not order:
        raise LookupError("未找到订单")
    return {"order":call.result,"tool_call_id":call.id}

@app.post("/api/tools/tickets/draft", status_code=201)
def ticket_draft(payload: TicketDraftRequest, db: Session = Depends(get_db)):
    approval = create_ticket_draft(db,payload.model_dump())
    return serialize_approval(approval)

@app.get("/api/approvals")
def approvals(db: Session = Depends(get_db)):
    return [serialize_approval(item) for item in db.query(Approval).order_by(Approval.created_at.desc()).all()]

@app.post("/api/approvals/{approval_id}/approve")
def approve(approval_id: str, payload: ApprovalDecision, db: Session = Depends(get_db)):
    modifications = payload.modifications.model_dump(exclude_unset=True) if payload.modifications else None
    approval = decide_approval(db,approval_id,True,payload.reason,modifications)
    return serialize_approval(approval)

@app.post("/api/approvals/{approval_id}/reject")
def reject(approval_id: str, payload: ApprovalDecision, db: Session = Depends(get_db)):
    modifications = payload.modifications.model_dump(exclude_unset=True) if payload.modifications else None
    approval = decide_approval(db,approval_id,False,payload.reason,modifications)
    return serialize_approval(approval)

@app.get("/api/tickets")
def tickets(db: Session = Depends(get_db)):
    return [{"id":t.id,"order_id":t.order_id,"ticket_type":t.ticket_type,"reason":t.reason,"priority":t.priority,"status":t.status,"created_at":t.created_at.isoformat()} for t in db.query(Ticket).order_by(Ticket.created_at.desc()).all()]

@app.get("/api/orders")
def orders(db: Session = Depends(get_db)):
    return [serialize_order(item) for item in db.query(Order).order_by(Order.ordered_at.desc()).all()]

@app.get("/api/tasks")
def tasks(db: Session = Depends(get_db)):
    return [task_json(item) for item in db.query(Task).order_by(Task.created_at.desc()).limit(50).all()]

@app.post("/api/tasks/{task_id}/retry", status_code=202)
def retry_task(task_id: str, background: BackgroundTasks, db: Session = Depends(get_db)):
    task = db.get(Task,task_id)
    if not task:
        raise LookupError("任务不存在")
    if task.kind != "document_index":
        raise ValueError("该任务类型不支持重试")
    task.status,task.stage,task.progress,task.error = "queued","queued",0,None
    task.retry_count += 1
    document = db.get(Document,task.entity_id)
    if document:
        document.status,document.stage,document.error = "pending","uploaded",None
    db.commit()
    dispatch_document(task.entity_id,background)
    return task_json(task)

@app.get("/api/tasks/{task_id}/events")
async def task_events(task_id: str):
    async def stream():
        for _ in range(120):
            db = SessionLocal()
            try:
                task = db.get(Task,task_id)
                if not task:
                    yield f"event: error\ndata: {json.dumps({'detail':'任务不存在'})}\n\n"
                    return
                yield f"data: {json.dumps(task_json(task),ensure_ascii=False)}\n\n"
                if task.status in {"succeeded","failed"}:
                    return
            finally:
                db.close()
            await asyncio.sleep(0.75)
    return StreamingResponse(stream(),media_type="text/event-stream")

@app.get("/api/audit")
def audit(db: Session = Depends(get_db)):
    events = db.query(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(100).all()
    calls = db.query(ToolCall).order_by(ToolCall.created_at.desc()).limit(50).all()
    return {"events":[{"id":e.id,"task_id":e.task_id,"category":e.category,"action":e.action,"detail":e.detail,"duration_ms":e.duration_ms,"created_at":e.created_at.isoformat()} for e in events],"tool_calls":[{"id":c.id,"tool_name":c.tool_name,"parameters":c.parameters,"status":c.status,"result":c.result,"error":c.error,"latency_ms":c.latency_ms,"created_at":c.created_at.isoformat()} for c in calls]}

@app.post("/api/evaluations/run")
def evaluate(db: Session = Depends(get_db)):
    run = run_evaluation(db)
    return {"id":run.id,"status":run.status,"metrics":run.metrics,"results":run.results,"dataset_version":run.dataset_version,"created_at":run.created_at.isoformat()}

@app.get("/api/evaluations")
def evaluations(db: Session = Depends(get_db)):
    return [{"id":r.id,"status":r.status,"metrics":r.metrics,"results":r.results,"dataset_version":r.dataset_version,"app_version":r.app_version,"token_usage":r.token_usage,"created_at":r.created_at.isoformat()} for r in db.query(EvalRun).order_by(EvalRun.created_at.desc()).limit(20).all()]

@app.post("/api/feedback", status_code=201)
def feedback(payload: FeedbackRequest, db: Session = Depends(get_db)):
    if not db.get(Message,payload.message_id):
        raise LookupError("消息不存在")
    item = Feedback(**payload.model_dump())
    db.add(item)
    db.commit()
    return {"id":item.id,"saved":True}

@app.post("/api/reports", response_class=PlainTextResponse)
def report(payload: ReportRequest, db: Session = Depends(get_db)):
    order = db.get(Order,payload.order_id)
    if not order:
        raise LookupError("订单不存在")
    ticket = db.get(Ticket,payload.ticket_id) if payload.ticket_id else None
    if payload.ticket_id and not ticket:
        raise LookupError("工单不存在")
    if ticket and ticket.order_id != order.id:
        raise ValueError("工单不属于指定订单，不能生成混合关联报告")
    content = f"# 售后处理报告\n\n- 订单：{order.id}\n- 商品：{order.product}\n- 订单状态：{ORDER_STATES.get(order.status,order.status)}\n- 金额：¥{order.amount:.2f}\n- 物流：{order.logistics}\n"
    if ticket:
        priorities = {"low":"低","normal":"普通","high":"高","urgent":"紧急"}
        ticket_states = {"open":"待处理","in_progress":"处理中","resolved":"已解决","closed":"已关闭"}
        content += f"\n## 工单\n\n- 工单号：{ticket.id}\n- 类型：{TICKET_TYPES.get(ticket.ticket_type,ticket.ticket_type)}\n- 优先级：{priorities.get(ticket.priority,ticket.priority)}\n- 原因：{ticket.reason}\n- 状态：{ticket_states.get(ticket.status,ticket.status)}\n"
    else:
        content += "\n## 工单\n\n尚未关联工单。\n"
    content += "\n> 本报告基于模拟业务数据生成，供流程验收使用。\n"
    return content

@app.get("/")
def root():
    return {"name":settings.app_name,"docs":"/docs","health":"/api/health"}
