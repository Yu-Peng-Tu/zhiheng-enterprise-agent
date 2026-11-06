#!/usr/bin/env python3
"""Run copied client probes plus delivery security checks without altering original evidence."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
from typing import Any

from delivery_common import ROOT, sha256_file
from version_fingerprint import generate_fingerprint

ARTIFACTS = ROOT / "frontend/artifacts"
ORIGINAL = ARTIFACTS / "client-acceptance"
PROBES = {
    "http": (ORIGINAL / "http_acceptance.py", "http-results.json"),
    "browser": (ORIGINAL / "browser_acceptance.mjs", "browser-results.json"),
}


def run_process(arguments: list[str], log_path: Path) -> int:
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(arguments, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            return process.wait()
        except KeyboardInterrupt:
            os.killpg(process.pid, signal.SIGTERM)
            return process.wait()


def read_summary(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    summary = payload.get("summary")
    return summary if isinstance(summary, dict) else None


def adapt_browser_copy(path: Path) -> str:
    """Accept fixed UI states in the run copy while preserving all original assertions."""
    text = path.read_text(encoding="utf-8")
    replacements = (
        (
            "const staleOrder = await page.locator('.order-focus').innerText();",
            "const staleOrder = await page.locator('.order-focus').count() ? await page.locator('.order-focus').innerText() : '';",
            1,
        ),
        (
            "await down.getByText('尚未上传文档', { exact: true }).waitFor();",
            "await down.locator('.documents-page').waitFor();\n  await down.waitForTimeout(500);",
            1,
        ),
        (
            "emptyText: await down.getByText('尚未上传文档', { exact: true }).innerText(),",
            "emptyText: await down.getByText('尚未上传文档', { exact: true }).count() ? await down.getByText('尚未上传文档', { exact: true }).innerText() : '',",
            1,
        ),
        (
            "errorMessages: await down.locator('.ant-message-error').count(),",
            "errorMessages: await down.locator('.ant-message-error, .error-state').count(),",
            2,
        ),
    )
    for old, new, expected_count in replacements:
        if text.count(old) != expected_count:
            raise RuntimeError(f"browser compatibility anchor changed in original probe: {old}")
        text = text.replace(old, new)
    path.write_text(text, encoding="utf-8")
    return sha256_file(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("http", "browser", "security", "all"), default="all")
    parser.add_argument("--output-dir", type=Path, help="new direct child of frontend/artifacts; default is delivery-<timestamp>")
    args = parser.parse_args()
    output = args.output_dir.expanduser().resolve() if args.output_dir else ARTIFACTS / f"delivery-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{os.getpid()}"
    if output.parent != ARTIFACTS:
        parser.exit(1, "ERROR: --output-dir must be a direct child of frontend/artifacts so copied probes resolve the project root\n")
    if output.exists():
        parser.exit(1, f"ERROR: output already exists; refusing to overwrite evidence: {output}\n")
    if not (ROOT / ".venv/bin/uvicorn").is_file():
        parser.exit(1, "ERROR: project .venv with uvicorn is required by the original client probes\n")
    output.mkdir(parents=True)
    selected = ["http", "browser", "security"] if args.suite == "all" else [args.suite]
    original_hashes = {name: sha256_file(source) for name, (source, _) in PROBES.items()}
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "suite": args.suite,
        "original_probe_sha256": original_hashes,
        "method": "Probes are copied to this isolated run directory. HTTP is unchanged; the browser copy only accepts fixed empty/order and visible-alert states.",
        "browser_copy_adaptations": [
            "an absent stale order panel is accepted and still asserted not to contain SQ100002",
            "an absent false empty-library message is accepted instead of awaited",
            "visible .error-state alerts and legacy .ant-message-error toasts both count as errors",
        ],
        "python": sys.version,
        "note": "A zero probe process code alone is not a pass; result summaries are checked separately.",
    }
    (output / "run-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    generate_fingerprint(ROOT, output / "source-sha256.txt")
    outcomes: dict[str, Any] = {}
    try:
        for suite in selected:
            adapted_hash = None
            if suite in PROBES:
                source, result_name = PROBES[suite]
                copied = output / source.name
                shutil.copyfile(source, copied)
                if suite == "browser":
                    adapted_hash = adapt_browser_copy(copied)
                command = [sys.executable, str(copied)] if suite == "http" else ["node", str(copied)]
            else:
                result_name = "security-results.json"
                command = [sys.executable, str(ROOT / "scripts/security_acceptance.py"), "--output-dir", str(output)]
            print(f"RUN {suite}: evidence {output}", flush=True)
            return_code = run_process(command, output / f"{suite}-execution.txt")
            summary = read_summary(output / result_name)
            failed = None if summary is None else summary.get("failed")
            passed = return_code == 0 and summary is not None and failed == 0
            outcomes[suite] = {
                "process_exit_code": return_code,
                "summary": summary,
                "passed": passed,
                "result_file": result_name,
                "adapted_copy_sha256": adapted_hash,
                "interpretation": "pass only when process exits 0 and result summary has failed=0",
            }
            compact = {key: summary.get(key) for key in ("total", "passed", "failed")} if summary else None
            print(f"END {suite}: exit={return_code}, summary={compact}, passed={passed}", flush=True)
    finally:
        for name, (source, _) in PROBES.items():
            if sha256_file(source) != original_hashes[name]:
                raise RuntimeError(f"original client probe changed during run: {source}")
        summary = {
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "suite": args.suite,
            "passed": bool(outcomes) and all(item["passed"] for item in outcomes.values()) and len(outcomes) == len(selected),
            "outcomes": outcomes,
        }
        (output / "delivery-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"suite": args.suite, "passed": summary["passed"], "evidence": str(output)}, ensure_ascii=False), flush=True)
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
