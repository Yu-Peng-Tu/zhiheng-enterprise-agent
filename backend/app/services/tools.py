import time
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session
from ..models import Order, Ticket, Approval, ToolCall
from .audit import record

ORDER_STATES = {"pending":"待付款","processing":"处理中","shipped":"配送中","delivered":"已签收","cancelled":"已取消"}
TICKET_TYPES = {"refund":"退款","return":"退货","exchange":"换货","logistics":"物流异常","other":"其他"}
DEMO_ACTOR = "演示管理员"

class ApprovalConflict(Exception):
    pass

def serialize_order(order: Order):
    return {"order_id":order.id,"customer_name":order.customer_name,"product":order.product,"status":order.status,"status_label":ORDER_STATES.get(order.status,order.status),"amount":order.amount,"ordered_at":order.ordered_at,"delivered_at":order.delivered_at,"logistics":order.logistics}

def query_order(db: Session, order_id: str):
    started = time.perf_counter()
    call = ToolCall(tool_name="orders.query", parameters={"order_id":order_id})
    db.add(call)
    order = db.get(Order, order_id)
    if not order:
        call.status, call.error = "not_found", "未找到订单"
        db.commit()
        return None, call
    call.status, call.result = "succeeded", serialize_order(order)
    call.latency_ms = int((time.perf_counter()-started)*1000)
    record(db, "tool", "order_queried", {"order_id":order_id,"call_id":call.id}, duration_ms=call.latency_ms)
    db.commit()
    return order, call

def create_ticket_draft(db: Session, data: dict):
    order = db.get(Order, data["order_id"])
    if not order:
        raise LookupError("未找到订单，无法创建工单草案")
    key = str(uuid.uuid4())
    draft = {"order_id":order.id,"ticket_type":data["ticket_type"],"reason":data["reason"],"priority":data["priority"]}
    approval = Approval(order_id=order.id, draft=draft, original_draft=deepcopy(draft), idempotency_key=key)
    db.add(approval)
    db.flush()
    record(db, "approval", "draft_created", {"approval_id":approval.id,"order_id":order.id})
    db.commit()
    return approval

def _decision_detail(approval, before, after, decided_at, reason, ticket_id=None):
    return {
        "approval_id":approval.id,
        "ticket_id":ticket_id,
        "before":deepcopy(before),
        "after":deepcopy(after),
        "actor":DEMO_ACTOR,
        "decision_reason":reason,
        "decided_at":decided_at.isoformat(),
    }

def _return_completed_decision(db, approval_id, approve):
    current = db.get(Approval, approval_id)
    if not current:
        raise LookupError("审批记录不存在")
    expected_status = "approved" if approve else "rejected"
    if current.status == expected_status:
        return current
    raise ApprovalConflict(f"该审批已{('批准' if current.status == 'approved' else '拒绝')}，不能执行相反决定")

def _recover_unique_conflict(db, approval_id, idempotency_key, reason, modifications):
    """The failed transaction is already rolled back; reconcile only an identical ticket."""
    existing = db.query(Ticket).filter(Ticket.idempotency_key == idempotency_key).first()
    current = db.get(Approval, approval_id)
    if not existing or not current:
        raise ApprovalConflict("工单唯一键冲突，且未找到可恢复的审批与工单")
    if current.status == "pending":
        before = deepcopy(current.original_draft or current.draft)
        after = deepcopy(before)
        after.update(modifications or {})
        after["reason"] = after["reason"].strip()
        decided_at = datetime.now(timezone.utc)
        result = db.execute(
            update(Approval)
            .where(Approval.id == approval_id, Approval.status == "pending")
            .values(status="approved", draft=after, original_draft=before, ticket_id=existing.id,
                    decision_reason=reason, actor=DEMO_ACTOR, decided_at=decided_at)
        )
        if result.rowcount != 1:
            db.rollback()
            return _return_completed_decision(db, approval_id, True)
        record(db, "approval", "approved_and_executed",
               _decision_detail(current, before, after, decided_at, reason, existing.id))
        db.commit()
        current = db.get(Approval, approval_id)
    if current.status == "approved" and current.ticket_id == existing.id:
        return current
    db.rollback()
    raise ApprovalConflict("工单唯一键冲突，审批与既有工单不一致")

def decide_approval(db: Session, approval_id: str, approve: bool, reason=None, modifications=None):
    # A conditional UPDATE serializes the decision on both SQLite and PostgreSQL.
    for attempt in range(8):
        try:
            approval = db.get(Approval, approval_id)
            if not approval:
                raise LookupError("审批记录不存在")
            if approval.status != "pending":
                return _return_completed_decision(db, approval_id, approve)
            idempotency_key = approval.idempotency_key
            before = deepcopy(approval.original_draft or approval.draft)
            after = deepcopy(before)
            if approve:
                allowed = {"ticket_type", "reason", "priority"}
                if set(modifications or {}) - allowed:
                    raise ValueError("包含不允许修改的字段")
                after.update(modifications or {})
                if (after.get("ticket_type") not in TICKET_TYPES
                        or not isinstance(after.get("reason"), str)
                        or not 2 <= len(after["reason"].strip()) <= 1000
                        or after.get("priority") not in {"low", "normal", "high", "urgent"}):
                    raise ValueError("修改后的工单参数不合法")
                after["reason"] = after["reason"].strip()
            decided_at = datetime.now(timezone.utc)
            target_status = "approved" if approve else "rejected"
            result = db.execute(
                update(Approval)
                .where(Approval.id == approval_id, Approval.status == "pending")
                .values(status=target_status, draft=after, original_draft=before,
                        decision_reason=reason, actor=DEMO_ACTOR, decided_at=decided_at)
                .execution_options(synchronize_session=False)
            )
            if result.rowcount != 1:
                db.rollback()
                return _return_completed_decision(db, approval_id, approve)
            db.expire_all()
            approval = db.get(Approval, approval_id)
            if not approve:
                record(db, "approval", "rejected",
                       _decision_detail(approval, before, after, decided_at, reason))
                db.commit()
                return db.get(Approval, approval_id)
            ticket = Ticket(id=f"GD{uuid.uuid4().hex[:8].upper()}", order_id=approval.order_id,
                            ticket_type=after["ticket_type"], reason=after["reason"],
                            priority=after["priority"], idempotency_key=idempotency_key)
            db.add(ticket)
            approval.ticket_id = ticket.id
            call = ToolCall(tool_name="tickets.create", parameters=after, status="succeeded", result={"ticket_id":ticket.id})
            db.add(call)
            record(db, "approval", "approved_and_executed",
                   _decision_detail(approval, before, after, decided_at, reason, ticket.id))
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                return _recover_unique_conflict(db, approval_id, idempotency_key, reason, modifications)
            return db.get(Approval, approval_id)
        except OperationalError as exc:
            db.rollback()
            message = str(exc).lower()
            if "locked" not in message and "busy" not in message:
                raise
            if attempt == 7:
                raise ApprovalConflict("审批存储当前繁忙，请稍后重试") from exc
            time.sleep(0.02 * (2 ** attempt))
    raise ApprovalConflict("审批存储当前繁忙，请稍后重试")

def serialize_approval(item: Approval):
    return {
        "id":item.id,
        "order_id":item.order_id,
        "draft":item.draft,
        "original_draft":deepcopy(item.original_draft if item.original_draft is not None else item.draft),
        "status":item.status,
        "decision_reason":item.decision_reason,
        "actor":item.actor,
        "decided_at":item.decided_at.isoformat() if item.decided_at else None,
        "ticket_id":item.ticket_id,
        "created_at":item.created_at.isoformat() if item.created_at else None,
    }
