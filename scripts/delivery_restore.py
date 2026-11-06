#!/usr/bin/env python3
"""Restore delivery backups only to explicit, previously unused targets."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import uuid

from delivery_backup import compose_command, run_checked
from delivery_common import (
    ROOT,
    copy_tree_without_links,
    inspect_safe_tar,
    secure_tree,
    sha256_file,
    sqlite_quick_check,
    sqlite_table_counts,
    utc_now,
    verify_backup,
)


def require_local_target(target: Path, confirmation: str, backup: Path) -> Path:
    target = target.expanduser().resolve()
    confirmed = Path(confirmation).expanduser().resolve()
    if target != confirmed:
        raise ValueError("--confirm-target must resolve to exactly the same path as --target-dir")
    if target.exists():
        raise FileExistsError(f"restore target already exists; refusing all overwrite: {target}")
    if target == ROOT or target == backup or target.is_relative_to(backup):
        raise ValueError("restore target must be outside the backup directory and project root")
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def restore_local(backup: Path, target: Path, confirmation: str) -> Path:
    backup = backup.expanduser().resolve()
    target = require_local_target(target, confirmation, backup)
    manifest = verify_backup(backup, "local")
    database = backup / manifest["local"]["database_payload"]
    sqlite_quick_check(database)
    stage = target.parent / f".{target.name}.restoring-{uuid.uuid4().hex}"
    stage.mkdir(mode=0o700)
    try:
        restored_db = stage / "app.db"
        shutil.copy2(database, restored_db)
        if sha256_file(restored_db) != manifest["files"][manifest["local"]["database_payload"]]["sha256"]:
            raise ValueError("restored SQLite hash differs from backup")
        sqlite_quick_check(restored_db)
        expected_counts = manifest["local"]["table_counts"]
        restored_counts = sqlite_table_counts(restored_db)
        if restored_counts != expected_counts:
            raise ValueError(f"restored table counts differ: expected {expected_counts}, got {restored_counts}")
        upload_files, upload_bytes = copy_tree_without_links(backup / "uploads", stage / "uploads")
        if upload_files != manifest["local"]["upload_files"] or upload_bytes != manifest["local"]["upload_bytes"]:
            raise ValueError("restored upload file count or byte count differs from backup")
        (stage / "RESTORE_INFO.json").write_text(json.dumps({
            "restored_at": utc_now(),
            "backup_created_at": manifest["created_at"],
            "source_backup_sha256": sha256_file(backup / "manifest.json"),
            "database": "app.db",
            "table_counts": restored_counts,
            "upload_files": upload_files,
            "upload_bytes": upload_bytes,
            "note": "Configuration snapshots were verified but not applied automatically; review them separately.",
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        secure_tree(stage)
        stage.replace(target)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return target


def valid_project_name(value: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9](?:[a-z0-9_-]{0,61}[a-z0-9])?", value))


def volume_exists(name: str) -> bool:
    result = subprocess.run(["docker", "volume", "inspect", name], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return result.returncode == 0


def compose_down(project: str) -> None:
    subprocess.run(compose_command(["down", "-v"], project), cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


def restore_compose(backup: Path, project: str, confirmation: str, cleanup: bool) -> dict:
    backup = backup.expanduser().resolve()
    if project != confirmation:
        raise ValueError("--confirm-project must exactly match --project-name")
    if not valid_project_name(project):
        raise ValueError("Compose project name must be 1-63 lowercase letters, digits, '-' or '_', ending alphanumeric")
    default_project = re.sub(r"[^a-z0-9_-]", "", ROOT.name.lower().replace(" ", "-")) or "enterprise-agent"
    if project == default_project:
        raise ValueError(f"refusing the normal demo Compose project name: {project}; choose an isolated restore project")
    manifest = verify_backup(backup, "compose")
    archive = backup / manifest["compose"]["uploads_payload"]
    upload_files = inspect_safe_tar(archive)
    run_checked(compose_command(["version"]))
    run_checked(["docker", "info"])
    for volume in ("postgres-data", "app-data"):
        name = f"{project}_{volume}"
        if volume_exists(name):
            raise FileExistsError(f"target Docker volume already exists; refusing to overwrite: {name}")
    existing_containers = run_checked(compose_command(["ps", "-q"], project)).stdout.strip()
    if existing_containers:
        raise RuntimeError(f"target Compose project already has containers: {project}")
    resources_created = False
    verification: dict[str, object] = {}
    try:
        # The project and volumes were proven absent above; clean even a partially failed up.
        resources_created = True
        run_checked(compose_command(["up", "-d", "postgres"], project))
        for _ in range(45):
            ready = subprocess.run(
                compose_command(["exec", "-T", "postgres", "pg_isready", "-U", "zhiheng", "-d", "zhiheng"], project),
                cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
            )
            if ready.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError("restored PostgreSQL did not become ready within 45 seconds")
        with (backup / manifest["compose"]["database_payload"]).open("rb") as dump:
            result = subprocess.run(compose_command([
                "exec", "-T", "postgres", "pg_restore", "-U", "zhiheng", "-d", "zhiheng",
                "--clean", "--if-exists", "--no-owner", "--no-privileges",
            ], project), cwd=ROOT, stdin=dump, capture_output=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"pg_restore failed: {result.stderr.decode('utf-8', errors='replace').strip()}")
        with archive.open("rb") as source:
            result = subprocess.run(compose_command([
                "run", "--rm", "--no-deps", "--entrypoint", "tar", "backend",
                "-C", "/app/backend/data", "-xf", "-",
            ], project), cwd=ROOT, stdin=source, capture_output=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"upload volume restore failed: {result.stderr.decode('utf-8', errors='replace').strip()}")
        query = ";".join(
            f"SELECT '{table}=' || count(*) FROM {table}" for table in ("documents", "approvals", "tickets", "audit_events")
        )
        counts = run_checked(compose_command([
            "exec", "-T", "postgres", "psql", "-At", "-U", "zhiheng", "-d", "zhiheng", "-c", query,
        ], project)).stdout.strip()
        listing = run_checked(compose_command([
            "run", "--rm", "--no-deps", "--entrypoint", "sh", "backend",
            "-c", "find /app/backend/data -type f -print",
        ], project)).stdout
        restored_upload_files = sum(1 for line in listing.splitlines() if line.strip())
        if restored_upload_files != upload_files:
            raise RuntimeError(f"upload archive has {upload_files} files but restored volume lists {restored_upload_files}")
        verification = {
            "status": "ok",
            "project": project,
            "database_counts": counts.splitlines(),
            "upload_files": restored_upload_files,
            "postgres_left_running": not cleanup,
            "backend_worker_started": False,
            "note": "Start backend/worker separately for application verification; RQ history is not restored.",
        }
        if cleanup:
            run_checked(compose_command(["down", "-v"], project))
            resources_created = False
        return verification
    except Exception:
        if resources_created:
            compose_down(project)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    local = subparsers.add_parser("local", help="restore SQLite and uploads to a new directory")
    local.add_argument("--backup-dir", type=Path, required=True)
    local.add_argument("--target-dir", type=Path, required=True)
    local.add_argument("--confirm-target", required=True, help="repeat the exact target path as an overwrite safeguard")
    compose = subparsers.add_parser("compose", help="restore to an isolated new Compose project and new volumes")
    compose.add_argument("--backup-dir", type=Path, required=True)
    compose.add_argument("--project-name", required=True)
    compose.add_argument("--confirm-project", required=True)
    compose.add_argument("--cleanup-after-verify", action="store_true", help="delete only the newly created drill project and volumes after verification")
    args = parser.parse_args()
    try:
        if args.command == "local":
            output = restore_local(args.backup_dir, args.target_dir, args.confirm_target)
            result = {"status": "ok", "target_dir": str(output), "database": str(output / "app.db")}
        else:
            result = restore_compose(args.backup_dir, args.project_name, args.confirm_project, args.cleanup_after_verify)
    except (OSError, RuntimeError, ValueError, sqlite3.Error, json.JSONDecodeError) as exc:
        parser.exit(1, f"ERROR: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
