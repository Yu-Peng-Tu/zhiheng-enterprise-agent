import concurrent.futures
import os
import threading
import uuid
from pathlib import Path
os.environ["DATABASE_URL"] = "sqlite:///./backend/data/test.db"
os.environ["REDIS_URL"] = ""
Path("backend/data/test.db").unlink(missing_ok=True)

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from app.main import app

client = TestClient(app)
from app.core.database import SessionLocal, run_compat_migrations
from app.models import Approval, Message, Ticket
from app.services.evaluation import count_unapproved_writes
from app.services.seed import seed_database
_db = SessionLocal()
seed_database(_db)
_db.close()

def test_health_and_seed_documents():
    assert client.get("/api/health").status_code == 200
    docs = client.get("/api/documents").json()
    assert len(docs) == 3
    assert all(doc["status"] == "ready" and doc["chunk_count"] >= 3 for doc in docs)

def test_upload_duplicate_and_empty_document():
    response = client.post("/api/documents", files={"file":("custom.md","# 内部规范\n\n## 密码重置\n密码重置工单需要人工审批。","text/markdown")})
    assert response.status_code == 202
    doc_id = response.json()["document"]["id"]
    detail = client.get(f"/api/documents/{doc_id}").json()
    assert detail["document"]["status"] == "ready"
    assert detail["document"]["chunk_count"] >= 2
    duplicate = client.post("/api/documents", files={"file":("custom.md","# 内部规范\n\n## 密码重置\n密码重置工单需要人工审批。","text/markdown")})
    assert duplicate.status_code == 409
    empty = client.post("/api/documents", files={"file":("empty.md","","text/markdown")})
    assert empty.status_code == 422

def test_grounded_chat_and_no_answer():
    grounded = client.post("/api/chat",json={"question":"退货验收后多久退款？"})
    assert grounded.status_code == 200
    data = grounded.json()
    assert "三个工作日" in data["answer"]
    assert data["citations"] and data["citations"][0]["document_name"] == "return-policy.md"
    assert data["citations"][0]["version"] == 1
    missing = client.post("/api/chat",json={"question":"火星基地几点开门？"}).json()
    assert "依据不足" in missing["answer"]
    assert missing["citations"] == []

def test_order_query_and_schema_validation():
    ok = client.post("/api/tools/orders/query",json={"order_id":"SQ100001"})
    assert ok.status_code == 200 and ok.json()["order"]["status"] == "delivered"
    missing = client.post("/api/tools/orders/query",json={"order_id":"SQ999999"})
    assert missing.status_code == 404
    invalid = client.post("/api/tools/orders/query",json={"order_id":"100001"})
    assert invalid.status_code == 422

def test_ticket_requires_approval_and_is_idempotent():
    draft = client.post("/api/tools/tickets/draft",json={"order_id":"SQ100001","ticket_type":"refund","reason":"商品存在质量问题","priority":"high"})
    assert draft.status_code == 201
    approval = draft.json()
    assert approval["status"] == "pending" and approval["ticket_id"] is None
    assert client.post("/api/approvals/nope/approve",json={}).status_code == 404
    approved = client.post(f"/api/approvals/{approval['id']}/approve",json={"reason":"核验通过"})
    assert approved.status_code == 200 and approved.json()["ticket_id"]
    ticket_id = approved.json()["ticket_id"]
    again = client.post(f"/api/approvals/{approval['id']}/approve",json={})
    assert again.status_code == 200 and again.json()["ticket_id"] == ticket_id
    assert len([t for t in client.get('/api/tickets').json() if t['id'] == ticket_id]) == 1

def test_reject_does_not_create_ticket():
    draft = client.post("/api/tools/tickets/draft",json={"order_id":"SQ100002","ticket_type":"logistics","reason":"物流七十二小时未更新","priority":"normal"}).json()
    rejected = client.post(f"/api/approvals/{draft['id']}/reject",json={"reason":"需要补充凭证"})
    assert rejected.status_code == 200 and rejected.json()["status"] == "rejected"
    assert rejected.json()["ticket_id"] is None

def test_chat_can_create_pending_draft():
    response = client.post("/api/chat",json={"question":"订单 SQ100005 要退货，请创建工单"}).json()
    assert response["approval"] and response["approval"]["status"] == "pending"
    assert "审批前不会创建工单" in response["answer"]

def test_evaluation_and_audit():
    evaluated = client.post("/api/evaluations/run")
    assert evaluated.status_code == 200
    assert evaluated.json()["metrics"]["pass_rate"] == 1.0
    dashboard = client.get("/api/dashboard")
    assert dashboard.status_code == 200
    latest_eval = dashboard.json()["latest_eval"]
    assert latest_eval["metrics"] == evaluated.json()["metrics"]
    assert latest_eval["dataset_version"] == evaluated.json()["dataset_version"]
    audit = client.get("/api/audit").json()
    assert audit["events"] and audit["tool_calls"]

def test_report_and_feedback():
    message = client.post("/api/chat",json={"question":"七天无理由退货如何计算？"}).json()
    feedback = client.post("/api/feedback",json={"message_id":message["id"],"helpful":True})
    assert feedback.status_code == 201
    ticket = client.get("/api/tickets").json()[0]
    report = client.post("/api/reports",json={"order_id":ticket["order_id"],"ticket_id":ticket["id"]})
    assert report.status_code == 200 and "售后处理报告" in report.text

def test_document_deactivation():
    docs = client.get("/api/documents").json()
    custom = next(doc for doc in docs if doc["filename"] == "custom.md")
    deleted = client.delete(f"/api/documents/{custom['id']}")
    assert deleted.status_code == 200 and deleted.json()["document"]["active"] is False


def _new_draft(reason="回归测试原始原因", order_id="SQ100001"):
    response = client.post("/api/tools/tickets/draft", json={
        "order_id":order_id, "ticket_type":"return", "reason":reason, "priority":"normal"
    })
    assert response.status_code == 201, response.text
    return response.json()


def _ticket_count(approval_id):
    db = SessionLocal()
    try:
        approval = db.get(Approval, approval_id)
        return db.query(Ticket).filter(Ticket.idempotency_key == approval.idempotency_key).count()
    finally:
        db.close()


def test_eight_way_concurrent_approve_is_idempotent_and_audited_once():
    draft = _new_draft("八路并发批准回归")
    barrier = threading.Barrier(8)
    def approve_once(index):
        barrier.wait()
        return client.post(f"/api/approvals/{draft['id']}/approve", json={"reason":f"并发批准 {index}"})
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(approve_once, range(8)))
    assert [response.status_code for response in responses] == [200] * 8
    bodies = [response.json() for response in responses]
    assert len({body["ticket_id"] for body in bodies}) == 1
    assert all(body == bodies[0] for body in bodies)
    assert _ticket_count(draft["id"]) == 1
    events = client.get("/api/audit").json()["events"]
    matching = [event for event in events if event["action"] == "approved_and_executed" and event["detail"].get("approval_id") == draft["id"]]
    assert len(matching) == 1


def test_eight_way_mixed_decision_has_one_winner_and_no_500():
    draft = _new_draft("八路批准拒绝冲突回归")
    barrier = threading.Barrier(8)
    def decide_once(index):
        action = "approve" if index % 2 == 0 else "reject"
        barrier.wait()
        return action, client.post(f"/api/approvals/{draft['id']}/{action}", json={"reason":f"并发决定 {index}"})
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(decide_once, range(8)))
    assert all(response.status_code in {200, 409} for _, response in responses)
    successful = [response.json() for _, response in responses if response.status_code == 200]
    assert successful
    assert len({body["status"] for body in successful}) == 1
    assert all(body == successful[0] for body in successful)
    final = next(item for item in client.get("/api/approvals").json() if item["id"] == draft["id"])
    assert final["status"] == successful[0]["status"]
    assert _ticket_count(draft["id"]) == (1 if final["status"] == "approved" else 0)
    if final["status"] == "rejected":
        assert final["ticket_id"] is None


@pytest.mark.parametrize("field,value", [
    ("reason", None), ("reason", 123), ("reason", ["bad"]),
    ("reason", ""), ("reason", "  \t"), ("reason", "长" * 1001),
    ("ticket_type", None), ("ticket_type", 123), ("ticket_type", ["bad"]), ("ticket_type", "invalid"),
    ("priority", None), ("priority", 123), ("priority", ["bad"]), ("priority", "critical"),
])
def test_invalid_modification_values_return_422_and_preserve_pending(field, value):
    draft = _new_draft(f"非法修改回归 {field} {type(value).__name__} {len(str(value))}")
    response = client.post(f"/api/approvals/{draft['id']}/approve", json={"modifications":{field:value}})
    assert response.status_code == 422, response.text
    current = next(item for item in client.get("/api/approvals").json() if item["id"] == draft["id"])
    assert current["status"] == "pending"
    assert current["ticket_id"] is None and current["decided_at"] is None
    assert _ticket_count(draft["id"]) == 0


@pytest.mark.parametrize("modifications", [
    {"order_id":"SQ100002"}, {"unknown":"value"}, {"reason":"有效原因", "extra":1},
])
def test_unknown_modification_fields_return_422_without_write(modifications):
    draft = _new_draft("未知修改字段回归")
    response = client.post(f"/api/approvals/{draft['id']}/approve", json={"modifications":modifications})
    assert response.status_code == 422
    assert _ticket_count(draft["id"]) == 0
    current = next(item for item in client.get("/api/approvals").json() if item["id"] == draft["id"])
    assert current["status"] == "pending" and current["draft"] == current["original_draft"]


@pytest.mark.parametrize("question", ["", " ", "   ", "\t\n", "　"])
def test_whitespace_chat_returns_422_and_does_not_create_message(question):
    db = SessionLocal()
    before = db.query(Message).count()
    db.close()
    response = client.post("/api/chat", json={"question":question})
    assert response.status_code == 422
    db = SessionLocal()
    assert db.query(Message).count() == before
    db.close()


def test_chat_trims_before_length_validation():
    accepted = client.post("/api/chat", json={"question":"  七天无理由退货如何计算？  "})
    assert accepted.status_code == 200
    assert accepted.json()["question"] == "七天无理由退货如何计算？"
    boundary = client.post("/api/chat", json={"question":" " + "长" * 2000 + " "})
    assert boundary.status_code == 200 and len(boundary.json()["question"]) == 2000
    assert client.post("/api/chat", json={"question":" " + "长" * 2001 + " "}).status_code == 422


def test_report_rejects_missing_and_cross_order_ticket():
    draft = _new_draft("报告关联异常回归", "SQ100001")
    approved = client.post(f"/api/approvals/{draft['id']}/approve", json={}).json()
    missing = client.post("/api/reports", json={"order_id":"SQ100001", "ticket_id":"GD-NOT-EXIST"})
    cross = client.post("/api/reports", json={"order_id":"SQ100002", "ticket_id":approved["ticket_id"]})
    assert missing.status_code == 404
    assert cross.status_code == 422


def test_approval_and_audit_retain_before_after_actor_and_decision_time():
    draft = _new_draft("修改前原始原因-回归保留")
    response = client.post(f"/api/approvals/{draft['id']}/approve", json={
        "reason":"演示管理员复核", "modifications":{"reason":"  修改后执行原因  ", "priority":"urgent"}
    })
    assert response.status_code == 200
    approved = response.json()
    assert approved["original_draft"]["reason"] == "修改前原始原因-回归保留"
    assert approved["draft"]["reason"] == "修改后执行原因"
    assert approved["draft"]["priority"] == "urgent"
    assert approved["actor"] == "演示管理员" and approved["decided_at"]
    replay = client.post(f"/api/approvals/{draft['id']}/approve", json={
        "reason":"演示管理员复核", "modifications":{"reason":"  修改后执行原因  ", "priority":"urgent"}
    })
    assert replay.status_code == 200 and replay.json() == approved
    conflict = client.post(f"/api/approvals/{draft['id']}/reject", json={"reason":"相反决定"})
    assert conflict.status_code == 409
    event = next(event for event in client.get("/api/audit").json()["events"]
                 if event["action"] == "approved_and_executed" and event["detail"].get("approval_id") == draft["id"])
    assert event["detail"]["before"]["reason"] == "修改前原始原因-回归保留"
    assert event["detail"]["after"]["reason"] == "修改后执行原因"
    assert event["detail"]["actor"] == "演示管理员" and event["detail"]["decided_at"]


def test_rejected_replay_is_same_and_later_approve_is_conflict():
    draft = _new_draft("拒绝重放与冲突回归")
    rejected = client.post(f"/api/approvals/{draft['id']}/reject", json={"reason":"凭证不足"})
    assert rejected.status_code == 200
    replay = client.post(f"/api/approvals/{draft['id']}/reject", json={"reason":"凭证不足"})
    assert replay.status_code == 200 and replay.json() == rejected.json()
    approve = client.post(f"/api/approvals/{draft['id']}/approve", json={})
    assert approve.status_code == 409
    assert approve.json()["detail"] and _ticket_count(draft["id"]) == 0


def test_chat_and_history_return_same_persistent_approval_contract():
    response = client.post("/api/chat", json={"question":"订单 SQ100003 要退货，请创建工单"})
    assert response.status_code == 200
    created = response.json()
    assert created["approval"]
    assert {"id", "order_id", "draft", "status", "ticket_id"} <= set(created["approval"])
    history = client.get("/api/messages").json()
    restored = next(item for item in history if item["id"] == created["id"])
    assert restored["approval"] == created["approval"]
    db = SessionLocal()
    assert db.get(Message, created["id"]).approval_id == created["approval"]["id"]
    db.close()
    approved = client.post(f"/api/approvals/{created['approval']['id']}/approve", json={}).json()
    restored_after = next(item for item in client.get("/api/messages").json() if item["id"] == created["id"])
    assert restored_after["approval"]["status"] == "approved"
    assert restored_after["approval"]["ticket_id"] == approved["ticket_id"]


def test_unique_conflict_recovery_rolls_back_and_reuses_existing_ticket():
    draft = _new_draft("唯一冲突回滚恢复回归")
    db = SessionLocal()
    approval = db.get(Approval, draft["id"])
    existing = Ticket(id=f"GD{uuid.uuid4().hex[:8].upper()}", order_id=approval.order_id,
                      ticket_type=approval.draft["ticket_type"], reason=approval.draft["reason"],
                      priority=approval.draft["priority"], idempotency_key=approval.idempotency_key)
    db.add(existing)
    db.commit()
    existing_id = existing.id
    db.close()
    response = client.post(f"/api/approvals/{draft['id']}/approve", json={})
    assert response.status_code == 200, response.text
    assert response.json()["ticket_id"] == existing_id
    assert _ticket_count(draft["id"]) == 1
    assert client.get("/api/approvals").status_code == 200


def test_unapproved_write_metric_uses_real_persistent_relationships():
    baseline_response = client.post("/api/evaluations/run")
    assert baseline_response.status_code == 200
    baseline = baseline_response.json()["metrics"]
    assert "不是渗透测试" in baseline["unapproved_writes_scope"]
    assert baseline["unapproved_writes"] == 0
    db = SessionLocal()
    orphan = Ticket(id=f"GD{uuid.uuid4().hex[:8].upper()}", order_id="SQ100001", ticket_type="other",
                    reason="隔离指标异常记录", priority="normal", idempotency_key=str(uuid.uuid4()))
    db.add(orphan)
    db.commit()
    try:
        measured, checked = count_unapproved_writes(db)
        assert measured == baseline["unapproved_writes"] + 1
        assert checked == baseline["unapproved_writes_tickets_checked"] + 1
        measured_response = client.post("/api/evaluations/run").json()["metrics"]
        assert measured_response["unapproved_writes"] == baseline["unapproved_writes"] + 1
    finally:
        db.rollback()
        db.delete(db.get(Ticket, orphan.id))
        db.commit()
        db.close()


def test_legacy_sqlite_columns_are_added_by_idempotent_migration():
    legacy_engine = create_engine("sqlite:///:memory:")
    with legacy_engine.begin() as connection:
        connection.execute(text("CREATE TABLE approvals (id VARCHAR PRIMARY KEY, draft JSON)"))
        connection.execute(text("CREATE TABLE messages (id VARCHAR PRIMARY KEY, question TEXT)"))
    run_compat_migrations(legacy_engine)
    run_compat_migrations(legacy_engine)
    approval_columns = {column["name"] for column in inspect(legacy_engine).get_columns("approvals")}
    message_columns = {column["name"] for column in inspect(legacy_engine).get_columns("messages")}
    assert {"original_draft", "actor"} <= approval_columns
    assert "approval_id" in message_columns
    legacy_engine.dispose()

