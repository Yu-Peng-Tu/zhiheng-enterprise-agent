#!/usr/bin/env python3
"""Create non-destructive local SQLite or quiesced Docker Compose backups."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import uuid

from delivery_common import (
    ROOT,
    copy_tree_without_links,
    finalize_backup,
    inspect_safe_tar,
    snapshot_config,
    sqlite_quick_check,
    sqlite_table_counts,
)
from version_fingerprint import generate_fingerprint


def new_stage(output: Path) -> tuple[Path, Path]:
    output = output.expanduser().resolve()
    if output.exists():
        raise FileExistsError(f"backup output already exists; refusing to overwrite: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = output.parent / f".{output.name}.partial-{uuid.uuid4().hex}"
    stage.mkdir(mode=0o700)
    return output, stage


def add_common_materials(stage: Path) -> list[str]:
    config_files = snapshot_config(ROOT, stage / "config")
    generate_fingerprint(ROOT, stage / "version" / "source-sha256.txt")
    return config_files


def backup_local(database: Path, uploads: Path, output: Path) -> Path:
    database = database.expanduser().resolve()
    uploads = uploads.expanduser().resolve()
    output = output.expanduser().resolve()
    if not database.is_file():
        raise FileNotFoundError(f"SQLite database not found: {database}")
    if not uploads.is_dir():
        raise FileNotFoundError(f"upload directory not found: {uploads}")
    if output == uploads or output.is_relative_to(uploads):
        raise ValueError("backup output must not be inside the upload directory")
    output, stage = new_stage(output)
    try:
        target_db = stage / "database.sqlite3"
        source_uri = f"{database.as_uri()}?mode=ro"
        with sqlite3.connect(source_uri, uri=True) as source, sqlite3.connect(target_db) as target:
            source.backup(target)
        sqlite_quick_check(target_db)
        table_counts = sqlite_table_counts(target_db)
        upload_files, upload_bytes = copy_tree_without_links(uploads, stage / "uploads")
        config_files = add_common_materials(stage)
        finalize_backup(stage, output, "local", {
            "local": {
                "database_payload": target_db.name,
                "source_database_name": database.name,
                "restored_database_name": "app.db",
                "table_counts": table_counts,
                "upload_files": upload_files,
                "upload_bytes": upload_bytes,
            },
            "config_files": config_files,
            "consistency": {
                "sqlite": "Python sqlite3 online backup API; source opened read-only.",
                "uploads": "Regular files copied without links; stop writes for a strict cross-resource point in time.",
                "rq": "No queue or in-flight job state is included; drain or quiesce workers before backup.",
            },
        })
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return output


def compose_command(arguments: list[str], project: str | None = None) -> list[str]:
    command = ["docker", "compose"]
    if project:
        command.extend(["-p", project])
    return command + arguments


def run_checked(arguments: list[str], *, text: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(arguments, cwd=ROOT, capture_output=True, text=text, check=False)
    if result.returncode != 0:
        stderr = result.stderr if text else result.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(arguments)}\n{stderr.strip()}")
    return result


def run_to_file(arguments: list[str], target: Path) -> None:
    with target.open("wb") as handle:
        result = subprocess.run(arguments, cwd=ROOT, stdout=handle, stderr=subprocess.PIPE, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(arguments)}\n"
            f"{result.stderr.decode('utf-8', errors='replace').strip()}"
        )
    if target.stat().st_size == 0:
        raise RuntimeError(f"command produced an empty backup: {' '.join(arguments)}")


def backup_compose(output: Path) -> Path:
    output, stage = new_stage(output)
    try:
        run_checked(compose_command(["version"]))
        run_checked(compose_command(["config", "--quiet"]))
        running = set(run_checked(compose_command(["ps", "--status", "running", "--services"])).stdout.splitlines())
        active_writers = sorted({"backend", "worker"} & running)
        if active_writers:
            raise RuntimeError(
                f"active writers must be stopped before Compose backup: {', '.join(active_writers)}; "
                "run 'docker compose stop backend worker', then retry"
            )
        if "postgres" not in running:
            raise RuntimeError("postgres is not running; Compose backup requires the existing database container")
        run_to_file(compose_command([
            "exec", "-T", "postgres", "pg_dump", "-U", "zhiheng", "-d", "zhiheng",
            "--format=custom", "--no-owner", "--no-privileges",
        ]), stage / "database.pgdump")
        archive = stage / "uploads-volume.tar"
        run_to_file(compose_command([
            "run", "--rm", "--no-deps", "--entrypoint", "tar", "backend",
            "-C", "/app/backend/data", "-cf", "-", ".",
        ]), archive)
        upload_files = inspect_safe_tar(archive)
        config_files = add_common_materials(stage)
        compose_services = run_checked(compose_command(["config", "--services"])).stdout.splitlines()
        compose_volumes = run_checked(compose_command(["config", "--volumes"])).stdout.splitlines()
        finalize_backup(stage, output, "compose", {
            "compose": {
                "database_payload": "database.pgdump",
                "uploads_payload": archive.name,
                "upload_files": upload_files,
                "services": compose_services,
                "volumes": compose_volumes,
                "database_name": "zhiheng",
                "database_user": "zhiheng",
            },
            "config_files": config_files,
            "consistency": {
                "postgresql": "Single pg_dump custom-format snapshot taken while backend and worker were stopped.",
                "uploads": "app-data volume archived through a temporary backend container after writers stopped.",
                "rq": "Redis/RQ queue data is deliberately excluded; queued and in-flight jobs are not recoverable from this backup.",
                "cross_resource": "Database and upload archive are quiesced copies, not a distributed transaction.",
            },
        })
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    local = subparsers.add_parser("local", help="back up SQLite and uploads with the sqlite3 backup API")
    local.add_argument("--database", type=Path, default=ROOT / "backend/data/app.db")
    local.add_argument("--uploads", type=Path, default=ROOT / "backend/data/uploads")
    local.add_argument("--output-dir", type=Path, required=True)
    compose = subparsers.add_parser("compose", help="back up quiesced Compose PostgreSQL and app-data volume")
    compose.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "local":
            output = backup_local(args.database, args.uploads, args.output_dir)
        else:
            output = backup_compose(args.output_dir)
    except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
        parser.exit(1, f"ERROR: {exc}\n")
    print(json.dumps({"status": "ok", "backup_dir": str(output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
