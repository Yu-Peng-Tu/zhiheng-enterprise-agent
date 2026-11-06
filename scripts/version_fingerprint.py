#!/usr/bin/env python3
"""Generate SHA-256 fingerprints for source and delivery materials without Git."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys

from delivery_common import ROOT, sha256_file

REQUIRED_FILES = (
    ".env.example",
    "docker-compose.yml",
    "backend/Dockerfile",
    "backend/requirements.txt",
    "frontend/Dockerfile",
    "frontend/nginx.conf",
    "frontend/package.json",
    "frontend/package-lock.json",
    "frontend/playwright.config.ts",
    "frontend/vite.config.ts",
    "package.json",
    "PRD.md",
    "PROJECT_CONTEXT.md",
    "README.md",
    "frontend/artifacts/client-acceptance/initial-report.md",
    "frontend/artifacts/client-acceptance/http_acceptance.py",
    "frontend/artifacts/client-acceptance/browser_acceptance.mjs",
)
MATERIAL_DIRECTORIES = (
    "backend/app",
    "backend/tests",
    "frontend/src",
    "frontend/tests",
    "scripts",
    "docs",
)


def material_files(root: Path) -> list[Path]:
    files = {root / relative for relative in REQUIRED_FILES}
    for relative in MATERIAL_DIRECTORIES:
        directory = root / relative
        if directory.is_dir():
            files.update(
                path for path in directory.rglob("*")
                if path.is_file() and "__pycache__" not in path.parts and path.suffix not in {".pyc", ".pyo"}
            )
    result = sorted(files, key=lambda path: path.relative_to(root).as_posix())
    missing = [path.relative_to(root).as_posix() for path in result if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"required fingerprint materials missing: {', '.join(missing)}")
    return result


def generate_fingerprint(root: Path, output: Path, overwrite: bool = False) -> int:
    output = output.expanduser().resolve()
    if output.exists() and not overwrite:
        raise FileExistsError(f"fingerprint output already exists: {output}; use --overwrite to replace it")
    files = material_files(root)
    lines = [
        "# Zhiheng delivery source fingerprint",
        f"# generated_at: {datetime.now(timezone.utc).isoformat()}",
        "# identity: directory SHA-256 baseline; this project is not a Git repository",
        "# format: sha256  relative/path",
    ]
    for path in files:
        lines.append(f"{sha256_file(path)}  {path.relative_to(root).as_posix()}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.partial")
    if temporary.exists():
        raise FileExistsError(f"stale fingerprint temporary file exists: {temporary}")
    try:
        temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    return len(files)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="new output file, or an existing file with --overwrite")
    parser.add_argument("--overwrite", action="store_true", help="explicitly replace the fingerprint output only")
    args = parser.parse_args()
    try:
        count = generate_fingerprint(ROOT, args.output, args.overwrite)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"ERROR: {exc}\n")
    print(f"Fingerprinted {count} files: {args.output.expanduser().resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
