#!/usr/bin/env python3
"""Destructive-safety and round-trip tests for delivery tools; uses temporary copies only."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BACKUP = ROOT / "scripts/delivery_backup.py"
RESTORE = ROOT / "scripts/delivery_restore.py"
FINGERPRINT = ROOT / "scripts/version_fingerprint.py"
TEMP_ROOT = ROOT / "delivery-evidence/tmp"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class DeliveryToolSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="tool-test-", dir=TEMP_ROOT)
        self.base = Path(self.temporary.name)
        self.source = self.base / "source"
        self.uploads = self.source / "uploads"
        self.uploads.mkdir(parents=True)
        self.database = self.source / "sample.db"
        with sqlite3.connect(self.database) as connection:
            connection.execute("CREATE TABLE evidence (id TEXT PRIMARY KEY, value TEXT NOT NULL)")
            connection.execute("INSERT INTO evidence VALUES ('one', '原始数据')")
            connection.commit()
        (self.uploads / "nested").mkdir()
        (self.uploads / "nested/policy.md").write_text("退货政策\n", encoding="utf-8")
        (self.uploads / "manifest.txt").write_text("upload-v1\n", encoding="utf-8")
        self.backup = self.base / "backup"
        self.restored = self.base / "restored"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_tool(self, arguments: list[str | Path], expected: int = 0) -> subprocess.CompletedProcess:
        result = subprocess.run(
            [sys.executable, *[str(item) for item in arguments]],
            cwd=ROOT, capture_output=True, text=True, check=False,
        )
        if result.returncode != expected:
            self.fail(
                f"unexpected exit {result.returncode}, wanted {expected}: {result.args}\n"
                f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
            )
        return result

    def make_backup(self) -> None:
        self.run_tool([BACKUP, "local", "--database", self.database, "--uploads", self.uploads, "--output-dir", self.backup])

    def test_01_round_trip_preserves_source_and_contents(self) -> None:
        source_hash = digest(self.database)
        self.make_backup()
        self.assertEqual(digest(self.database), source_hash)
        self.run_tool([
            RESTORE, "local", "--backup-dir", self.backup, "--target-dir", self.restored,
            "--confirm-target", str(self.restored),
        ])
        self.assertEqual(digest(self.restored / "app.db"), digest(self.backup / "database.sqlite3"))
        self.assertEqual((self.restored / "uploads/nested/policy.md").read_text(encoding="utf-8"), "退货政策\n")
        with sqlite3.connect(self.restored / "app.db") as connection:
            self.assertEqual(connection.execute("SELECT * FROM evidence").fetchall(), [("one", "原始数据")])
        info = json.loads((self.restored / "RESTORE_INFO.json").read_text(encoding="utf-8"))
        self.assertEqual(info["table_counts"], {"evidence": 1})
        self.assertEqual(info["upload_files"], 2)

    def test_02_backup_refuses_existing_output(self) -> None:
        self.backup.mkdir()
        sentinel = self.backup / "do-not-delete.txt"
        sentinel.write_text("keep", encoding="utf-8")
        result = self.run_tool([
            BACKUP, "local", "--database", self.database, "--uploads", self.uploads, "--output-dir", self.backup,
        ], expected=1)
        self.assertIn("refusing to overwrite", result.stderr)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")

    def test_03_restore_refuses_existing_target(self) -> None:
        self.make_backup()
        self.restored.mkdir()
        sentinel = self.restored / "daily-data.txt"
        sentinel.write_text("keep", encoding="utf-8")
        result = self.run_tool([
            RESTORE, "local", "--backup-dir", self.backup, "--target-dir", self.restored,
            "--confirm-target", str(self.restored),
        ], expected=1)
        self.assertIn("refusing all overwrite", result.stderr)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")
        self.assertFalse((self.restored / "app.db").exists())

    def test_04_restore_requires_exact_confirmation(self) -> None:
        self.make_backup()
        result = self.run_tool([
            RESTORE, "local", "--backup-dir", self.backup, "--target-dir", self.restored,
            "--confirm-target", str(self.base / "another-target"),
        ], expected=1)
        self.assertIn("must resolve to exactly", result.stderr)
        self.assertFalse(self.restored.exists())

    def test_05_restore_rejects_tampered_payload(self) -> None:
        self.make_backup()
        with (self.backup / "uploads/manifest.txt").open("a", encoding="utf-8") as handle:
            handle.write("tampered\n")
        result = self.run_tool([
            RESTORE, "local", "--backup-dir", self.backup, "--target-dir", self.restored,
            "--confirm-target", str(self.restored),
        ], expected=1)
        self.assertIn("mismatch", result.stderr)
        self.assertFalse(self.restored.exists())

    def test_06_backup_rejects_output_inside_uploads(self) -> None:
        result = self.run_tool([
            BACKUP, "local", "--database", self.database, "--uploads", self.uploads,
            "--output-dir", self.uploads / "recursive-backup",
        ], expected=1)
        self.assertIn("must not be inside", result.stderr)
        self.assertFalse((self.uploads / "recursive-backup").exists())

    def test_07_fingerprint_is_sha256_and_non_overwriting(self) -> None:
        output = self.base / "source-sha256.txt"
        self.run_tool([FINGERPRINT, "--output", output])
        lines = [line for line in output.read_text(encoding="utf-8").splitlines() if line and not line.startswith("#")]
        self.assertGreater(len(lines), 20)
        self.assertTrue(any(line.endswith("  backend/app/main.py") for line in lines))
        for line in lines:
            self.assertRegex(line.split("  ", 1)[0], r"^[0-9a-f]{64}$")
        original = output.read_bytes()
        self.run_tool([FINGERPRINT, "--output", output], expected=1)
        self.assertEqual(output.read_bytes(), original)


if __name__ == "__main__":
    unittest.main(verbosity=2)
