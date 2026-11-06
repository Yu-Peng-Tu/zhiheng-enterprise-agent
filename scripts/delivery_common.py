#!/usr/bin/env python3
"""Shared, dependency-free helpers for delivery backup and restore tools."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import tarfile
from datetime import datetime, timezone
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_NAME = "manifest.json"
SUMS_NAME = "SHA256SUMS.txt"
FORMAT_VERSION = 1

CONFIG_FILES = (
    ".env.example",
    "docker-compose.yml",
    "backend/Dockerfile",
    "backend/requirements.txt",
    "frontend/Dockerfile",
    "frontend/nginx.conf",
    "frontend/package.json",
    "frontend/package-lock.json",
    "package.json",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_relative_path(value: str) -> Path:
    pure = PurePosixPath(value)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValueError(f"unsafe archive path: {value!r}")
    return Path(*pure.parts)


def copy_tree_without_links(source: Path, destination: Path) -> tuple[int, int]:
    """Copy a regular-file tree, rejecting links and special files."""
    if not source.is_dir():
        raise FileNotFoundError(f"upload directory not found: {source}")
    file_count = 0
    byte_count = 0
    for current, dirnames, filenames in os.walk(source):
        current_path = Path(current)
        for name in list(dirnames):
            item = current_path / name
            if item.is_symlink():
                raise ValueError(f"symbolic links are not supported in uploads: {item}")
        for name in filenames:
            item = current_path / name
            if item.is_symlink() or not item.is_file():
                raise ValueError(f"only regular files are supported in uploads: {item}")
            relative = item.relative_to(source)
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)
            file_count += 1
            byte_count += item.stat().st_size
    for current, dirnames, _ in os.walk(source):
        current_path = Path(current)
        for name in dirnames:
            (destination / (current_path / name).relative_to(source)).mkdir(parents=True, exist_ok=True)
    destination.mkdir(parents=True, exist_ok=True)
    return file_count, byte_count


def snapshot_config(root: Path, destination: Path) -> list[str]:
    copied: list[str] = []
    for relative in CONFIG_FILES:
        source = root / relative
        if not source.is_file():
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied.append(relative)
    return copied


def secure_tree(root: Path) -> None:
    for current, dirnames, filenames in os.walk(root):
        current_path = Path(current)
        for name in dirnames:
            (current_path / name).chmod(0o700)
        for name in filenames:
            (current_path / name).chmod(0o600)
    root.chmod(0o700)


def file_entries(stage: Path, exclude: set[str] | None = None) -> dict[str, dict[str, Any]]:
    excluded = exclude or set()
    entries: dict[str, dict[str, Any]] = {}
    for path in sorted(item for item in stage.rglob("*") if item.is_file()):
        relative = path.relative_to(stage).as_posix()
        if relative in excluded:
            continue
        entries[relative] = {"sha256": sha256_file(path), "size": path.stat().st_size}
    return entries


def finalize_backup(stage: Path, output: Path, backup_type: str, metadata: dict[str, Any]) -> None:
    manifest = {
        "format_version": FORMAT_VERSION,
        "backup_type": backup_type,
        "created_at": utc_now(),
        "secrets_included": False,
        "hash_algorithm": "sha256",
        "hash_note": "Hashes detect accidental changes; they do not provide encryption or authenticity.",
        "files": file_entries(stage, {MANIFEST_NAME, SUMS_NAME}),
        **metadata,
    }
    (stage / MANIFEST_NAME).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [f"{item['sha256']}  {relative}" for relative, item in file_entries(stage, {SUMS_NAME}).items()]
    (stage / SUMS_NAME).write_text("\n".join(lines) + "\n", encoding="utf-8")
    secure_tree(stage)
    stage.replace(output)
    secure_tree(output)


def verify_backup(backup: Path, expected_type: str | None = None) -> dict[str, Any]:
    manifest_path = backup / MANIFEST_NAME
    sums_path = backup / SUMS_NAME
    if not manifest_path.is_file() or not sums_path.is_file():
        raise ValueError(f"not a delivery backup (manifest or checksums missing): {backup}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("format_version") != FORMAT_VERSION:
        raise ValueError(f"unsupported backup format: {manifest.get('format_version')!r}")
    if expected_type and manifest.get("backup_type") != expected_type:
        raise ValueError(f"expected {expected_type!r} backup, got {manifest.get('backup_type')!r}")
    for line in sums_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        expected, relative = line.split("  ", 1)
        path = backup / safe_relative_path(relative)
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"backup checksum mismatch: {relative}")
    for relative, item in manifest["files"].items():
        path = backup / safe_relative_path(relative)
        if not path.is_file():
            raise ValueError(f"backup payload missing: {relative}")
        if path.stat().st_size != item["size"] or sha256_file(path) != item["sha256"]:
            raise ValueError(f"backup payload mismatch: {relative}")
    return manifest


def sqlite_quick_check(path: Path) -> None:
    uri = f"{path.resolve().as_uri()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        rows = [row[0] for row in connection.execute("PRAGMA quick_check").fetchall()]
    if rows != ["ok"]:
        raise ValueError(f"SQLite quick_check failed for {path}: {rows}")


def sqlite_table_counts(path: Path) -> dict[str, int]:
    uri = f"{path.resolve().as_uri()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        names = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()]
        counts: dict[str, int] = {}
        for name in names:
            quoted = name.replace('"', '""')
            counts[name] = connection.execute(f'SELECT COUNT(*) FROM "{quoted}"').fetchone()[0]
    return counts


def inspect_safe_tar(path: Path) -> int:
    count = 0
    with tarfile.open(path, mode="r:*") as archive:
        for member in archive:
            name = member.name
            pure = PurePosixPath(name)
            normalized = PurePosixPath(*[part for part in pure.parts if part != "."])
            if pure.is_absolute() or ".." in pure.parts or not normalized.parts:
                if name in {".", "./"}:
                    continue
                raise ValueError(f"unsafe tar member path: {name}")
            if member.issym() or member.islnk() or member.isdev():
                raise ValueError(f"links and device entries are not allowed in upload archive: {name}")
            if member.isfile():
                count += 1
    return count
