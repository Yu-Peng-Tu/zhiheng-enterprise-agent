import json
import time
from pathlib import Path
from sqlalchemy.orm import Session
from ..models import Approval, AuditEvent, EvalRun, Ticket
from .retrieval import retrieve
from .llm import llm_client
from .tools import query_order

DATASET = Path(__file__).resolve().parents[1] / "data" / "eval_cases.json"
UNAPPROVED_WRITES_SCOPE = "持久化 Ticket/Approval/审批审计关系一致性审计；不是渗透测试或越权写入安全保证"

def count_unapproved_writes(db: Session):
    """Count persisted tickets lacking a matching approval and execution audit event."""
    tickets = db.query(Ticket).all()
    approvals = db.query(Approval).filter(Approval.status == "approved", Approval.ticket_id.is_not(None)).all()
    approval_by_ticket = {approval.ticket_id:approval for approval in approvals}
    audited_pairs = set()
    events = db.query(AuditEvent).filter(AuditEvent.action == "approved_and_executed").all()
    for event in events:
        detail = event.detail or {}
        if detail.get("approval_id") and detail.get("ticket_id"):
            audited_pairs.add((detail["approval_id"], detail["ticket_id"]))
    unapproved = 0
    for ticket in tickets:
        approval = approval_by_ticket.get(ticket.id)
        valid = bool(
            approval
            and approval.idempotency_key == ticket.idempotency_key
            and approval.order_id == ticket.order_id
            and (approval.id, ticket.id) in audited_pairs
        )
        if not valid:
            unapproved += 1
    return unapproved, len(tickets)

def run_evaluation(db: Session):
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    run = EvalRun(dataset_version=dataset["version"])
    db.add(run)
    db.flush()
    results, token_total = [], {"prompt_tokens":0,"completion_tokens":0}
    for case in dataset["cases"]:
        started = time.perf_counter()
        passed, detail = False, {}
        if case["type"] == "rag":
            citations = retrieve(db, case["question"])
            answer, mode, usage = llm_client.grounded_answer(case["question"], citations)
            token_total["prompt_tokens"] += usage.get("prompt_tokens",0)
            token_total["completion_tokens"] += usage.get("completion_tokens",0)
            text_match = all(term in answer for term in case["must_contain"])
            citation_match = bool(citations) == case["expect_citation"] if case["expect_citation"] else "依据不足" in answer
            passed = text_match and citation_match
            detail = {"answer":answer,"citations":citations,"mode":mode,"usage":usage}
        elif case["type"] == "order":
            order, call = query_order(db, case["order_id"])
            passed = bool(order and order.status == case["expected_status"])
            detail = {"result":call.result,"error":call.error}
        elif case["type"] == "order_invalid":
            order, call = query_order(db, case["order_id"])
            passed = order is None and call.status == "not_found"
            detail = {"result":call.result,"error":call.error}
        results.append({"case_id":case["id"],"type":case["type"],"passed":passed,"latency_ms":int((time.perf_counter()-started)*1000),"detail":detail})
    unapproved_writes, tickets_checked = count_unapproved_writes(db)
    run.results = results
    run.status = "completed"
    run.token_usage = token_total
    run.metrics = {
        "total":len(results),
        "passed":sum(r["passed"] for r in results),
        "pass_rate":round(sum(r["passed"] for r in results)/len(results),4),
        "avg_latency_ms":round(sum(r["latency_ms"] for r in results)/len(results),1),
        "unapproved_writes":unapproved_writes,
        "unapproved_writes_tickets_checked":tickets_checked,
        "unapproved_writes_scope":UNAPPROVED_WRITES_SCOPE,
    }
    db.commit()
    return run
