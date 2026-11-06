#!/usr/bin/env python3
"""Verify write approval controls and audit-derived metrics on an isolated SQLite database."""
from __future__ import annotations

import argparse
import concurrent.futures
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "frontend/artifacts"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True, help="new direct child of frontend/artifacts")
    args = parser.parse_args()
    output = args.output_dir.expanduser().resolve()
    if output.parent != ARTIFACTS:
        parser.exit(1, "ERROR: --output-dir must be a direct child of frontend/artifacts\n")
    output.mkdir(parents=True, exist_ok=True)
    result_path = output / "security-results.json"
    database = output / "security-acceptance.db"
    if result_path.exists() or database.exists():
        parser.exit(1, "ERROR: security evidence already exists; choose a new output directory\n")

    results: list[dict[str, Any]] = []
    independent: dict[str, Any] = {}
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    server: subprocess.Popen | None = None

    def record(case: str, passed: bool, expected: Any, actual: Any) -> None:
        item = {"case": case, "passed": bool(passed), "expected": expected, "actual": actual}
        results.append(item)
        print(f"{'PASS' if passed else 'FAIL'} {case}", flush=True)

    def make_draft(client: httpx.Client, reason: str) -> dict[str, Any]:
        response = client.post("/api/tools/tickets/draft", json={
            "order_id": "SQ100001", "ticket_type": "return", "reason": reason, "priority": "normal",
        })
        response.raise_for_status()
        return response.json()

    def tickets(client: httpx.Client) -> list[dict[str, Any]]:
        response = client.get("/api/tickets")
        response.raise_for_status()
        return response.json()

    def audit_derived_unapproved(client: httpx.Client) -> dict[str, Any]:
        audit_response = client.get("/api/audit")
        audit_response.raise_for_status()
        events = audit_response.json()["events"]
        approved_ids = {
            event.get("detail", {}).get("ticket_id")
            for event in events if event.get("action") == "approved_and_executed"
        }
        all_tickets = tickets(client)
        orphan_ids = [ticket["id"] for ticket in all_tickets if ticket["id"] not in approved_ids]
        return {
            "ticket_ids": [ticket["id"] for ticket in all_tickets],
            "approved_ticket_ids": sorted(value for value in approved_ids if value),
            "unapproved_ticket_ids": orphan_ids,
            "unapproved_writes": len(orphan_ids),
        }

    def run_evaluation(client: httpx.Client) -> dict[str, Any]:
        response = client.post("/api/evaluations/run")
        response.raise_for_status()
        return response.json()["metrics"]

    env = os.environ.copy()
    env.update({
        "PYTHONPATH": str(ROOT / "backend"),
        "DATABASE_URL": f"sqlite:///{database}",
        "REDIS_URL": "",
        "LLM_API_KEY": "",
    })
    log_path = output / "security-server.log"
    try:
        with log_path.open("w", encoding="utf-8") as log:
            server = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
                cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
            )
            with httpx.Client(base_url=base, timeout=45.0) as client:
                for _ in range(120):
                    try:
                        if client.get("/api/health").status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    if server.poll() is not None:
                        raise RuntimeError(f"isolated backend exited with {server.returncode}; see {log_path}")
                    time.sleep(0.1)
                else:
                    raise TimeoutError("isolated backend readiness")

                pending_reason = "交付安全探针-仅草案"
                pending = make_draft(client, pending_reason)
                pending_tickets = [item for item in tickets(client) if item["reason"] == pending_reason]
                record("draft does not write a ticket", not pending_tickets and pending["status"] == "pending",
                       "pending approval and zero matching tickets", {"approval": pending, "tickets": pending_tickets})

                rejected_reason = "交付安全探针-拒绝"
                rejected = make_draft(client, rejected_reason)
                reject_response = client.post(f"/api/approvals/{rejected['id']}/reject", json={"reason": "交付验收拒绝"})
                rejected_tickets = [item for item in tickets(client) if item["reason"] == rejected_reason]
                record("rejection does not write a ticket",
                       reject_response.status_code == 200 and reject_response.json()["status"] == "rejected" and not rejected_tickets,
                       "rejected approval and zero matching tickets",
                       {"status": reject_response.status_code, "body": reject_response.json(), "tickets": rejected_tickets})

                sequential_reason = "交付安全探针-顺序重复"
                sequential = make_draft(client, sequential_reason)
                first = client.post(f"/api/approvals/{sequential['id']}/approve", json={})
                second = client.post(f"/api/approvals/{sequential['id']}/approve", json={})
                sequential_tickets = [item for item in tickets(client) if item["reason"] == sequential_reason]
                record("sequential replay returns one ticket",
                       first.status_code == second.status_code == 200
                       and first.json().get("ticket_id") == second.json().get("ticket_id")
                       and len(sequential_tickets) == 1,
                       "two 200 responses, same ticket ID, exactly one stored ticket",
                       {"first": first.status_code, "second": second.status_code, "tickets": sequential_tickets})

                concurrent_reason = "交付安全探针-并发"
                concurrent_draft = make_draft(client, concurrent_reason)
                barrier = threading.Barrier(8)

                def approve_once(_: int) -> dict[str, Any]:
                    with httpx.Client(base_url=base, timeout=45.0) as concurrent_client:
                        barrier.wait()
                        response = concurrent_client.post(f"/api/approvals/{concurrent_draft['id']}/approve", json={})
                        try:
                            body = response.json()
                        except ValueError:
                            body = response.text
                        return {"status": response.status_code, "body": body}

                with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                    responses = list(pool.map(approve_once, range(8)))
                concurrent_tickets = [item for item in tickets(client) if item["reason"] == concurrent_reason]
                response_ticket_ids = {
                    item["body"].get("ticket_id") for item in responses if isinstance(item["body"], dict)
                }
                record("concurrent approval writes exactly one ticket",
                       all(item["status"] == 200 for item in responses)
                       and len(response_ticket_ids) == 1 and len(concurrent_tickets) == 1,
                       "eight 200 responses, one ticket ID, one stored ticket",
                       {"responses": responses, "tickets": concurrent_tickets})

                before = audit_derived_unapproved(client)
                before_metrics = run_evaluation(client)
                independent["before_fault_injection"] = before
                independent["metrics_before"] = before_metrics
                record("clean-run metric matches independent audit derivation",
                       before["unapproved_writes"] == 0
                       and isinstance(before_metrics.get("unapproved_writes"), int)
                       and before_metrics.get("unapproved_writes") == before["unapproved_writes"],
                       "integer unapproved_writes equals independently derived zero",
                       {"independent": before, "metrics": before_metrics})

                # Negative control: insert one synthetic orphan ticket only into this isolated database.
                # It has no approved_and_executed audit event and must make the next metric increase by one.
                orphan_id = "GD-UNAPPROVED-FAULT-INJECTION"
                with sqlite3.connect(database, timeout=30) as connection:
                    connection.execute(
                        "INSERT INTO tickets (id, order_id, ticket_type, reason, priority, status, idempotency_key, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (orphan_id, "SQ100001", "return", "隔离库审计负控，不是真实业务写入", "normal", "open",
                         f"fault-{time.time_ns()}", datetime.now(timezone.utc).isoformat()),
                    )
                    connection.commit()
                after = audit_derived_unapproved(client)
                after_metrics = run_evaluation(client)
                independent["after_fault_injection"] = after
                independent["metrics_after"] = after_metrics
                record("metric changes with audit evidence instead of remaining constant",
                       after["unapproved_writes"] == 1
                       and isinstance(after_metrics.get("unapproved_writes"), int)
                       and after_metrics.get("unapproved_writes") == after["unapproved_writes"]
                       and after_metrics.get("unapproved_writes") == before_metrics.get("unapproved_writes") + 1,
                       "one injected orphan ticket makes unapproved_writes increase from 0 to 1",
                       {"independent": after, "metrics": after_metrics})
    except Exception as exc:
        record("security probe completed without execution error", False, "no exception", f"{type(exc).__name__}: {exc}")
    finally:
        if server is not None and server.poll() is None:
            os.killpg(server.pid, signal.SIGTERM)
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(server.pid, signal.SIGKILL)
                server.wait(timeout=5)
        summary = {"total": len(results), "passed": sum(item["passed"] for item in results), "failed": sum(not item["passed"] for item in results)}
        payload = {
            "summary": summary,
            "scope": "isolated SQLite; synthetic orphan-ticket negative control; no daily demo database",
            "database": str(database),
            "results": results,
            "independent_derivation": independent,
        }
        result_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False), flush=True)
    return 0 if results and all(item["passed"] for item in results) else 1


if __name__ == "__main__":
    sys.exit(main())
