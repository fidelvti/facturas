from __future__ import annotations

from datetime import datetime, timedelta
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from facturas.db import connect
from facturas.scan import activate_scanner, scan_new_files
from tests.test_ingest import (
    PAGATELIA_2608_TEXT,
    WATER_TEXT,
    _count,
    _write_text,
)


class ScannerTests(unittest.TestCase):
    def test_activation_stores_timestamp_and_processes_zero_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write_text(root / "agua08.txt", WATER_TEXT)
            db_path = root / "facturas.sqlite3"

            report = activate_scanner(root, db_path)

            self.assertEqual(report.status, "activated")
            self.assertIsNotNone(report.scanner_started_at)
            self.assertEqual(report.files_considered, 0)
            with connect(db_path) as connection:
                self.assertEqual(_count(connection, "source_document"), 0)
                self.assertEqual(
                    connection.execute(
                        "SELECT scanner_started_at FROM scanner_state WHERE id = 1"
                    ).fetchone()[0],
                    report.scanner_started_at,
                )

    def test_second_activation_does_not_reset_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "facturas.sqlite3"

            first = activate_scanner(root, db_path)
            second = activate_scanner(root, db_path)

            self.assertEqual(first.status, "activated")
            self.assertEqual(second.status, "already_activated")
            self.assertEqual(second.scanner_started_at, first.scanner_started_at)

    def test_supported_historical_file_older_than_scanner_start_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "facturas.sqlite3"
            report = activate_scanner(root, db_path)
            source = _write_text(root / "agua08.txt", WATER_TEXT)
            _set_mtime(source, _from_iso(report.scanner_started_at) - timedelta(seconds=10))

            scan = scan_new_files(root, db_path)

            self.assertEqual(scan.historical_ignored, 1)
            self.assertEqual(scan.files_considered, 0)
            with connect(db_path) as connection:
                self.assertEqual(_count(connection, "source_document"), 0)

    def test_supported_new_file_newer_than_scanner_start_is_ingested(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "facturas.sqlite3"
            report = activate_scanner(root, db_path)
            source = _write_text(root / "agua08.txt", WATER_TEXT)
            _set_mtime(source, _from_iso(report.scanner_started_at) + timedelta(seconds=10))

            scan = scan_new_files(root, db_path)

            self.assertEqual(scan.imported, 1)
            with connect(db_path) as connection:
                self.assertEqual(_count(connection, "source_document"), 1)
                self.assertEqual(_count(connection, "water_invoice_detail"), 1)

    def test_unsupported_new_file_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "facturas.sqlite3"
            report = activate_scanner(root, db_path)
            source = _write_text(root / "ticket08.txt", "ignored")
            _set_mtime(source, _from_iso(report.scanner_started_at) + timedelta(seconds=10))

            scan = scan_new_files(root, db_path)

            self.assertEqual(scan.unsupported_ignored, 1)
            self.assertEqual(scan.files_considered, 0)
            with connect(db_path) as connection:
                self.assertEqual(_count(connection, "source_document"), 0)

    def test_recursive_scan_finds_new_pagatelia_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            provider_dir = root / "pagatelia"
            provider_dir.mkdir()
            db_path = root / "facturas.sqlite3"
            report = activate_scanner(root, db_path)
            source = _write_text(provider_dir / "Pagatelia2305a.txt", PAGATELIA_2608_TEXT)
            _set_mtime(source, _from_iso(report.scanner_started_at) + timedelta(seconds=10))

            scan = scan_new_files(root, db_path)

            self.assertEqual(scan.imported, 1)
            with connect(db_path) as connection:
                periods = connection.execute(
                    "SELECT DISTINCT period_yyyymm FROM toll_transaction"
                ).fetchall()
                self.assertEqual(periods, [("202305",)])

    def test_duplicate_new_file_remains_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "facturas.sqlite3"
            report = activate_scanner(root, db_path)
            source = _write_text(root / "agua08.txt", WATER_TEXT)
            _set_mtime(source, _from_iso(report.scanner_started_at) + timedelta(seconds=10))

            first = scan_new_files(root, db_path)
            second = scan_new_files(root, db_path)

            self.assertEqual(first.imported, 1)
            self.assertEqual(second.skipped_duplicate, 1)
            with connect(db_path) as connection:
                self.assertEqual(_count(connection, "source_document"), 1)
                self.assertEqual(_count(connection, "water_invoice_detail"), 1)

    def test_failed_recognized_file_does_not_stop_valid_new_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "facturas.sqlite3"
            report = activate_scanner(root, db_path)
            start = _from_iso(report.scanner_started_at)
            bad = _write_text(root / "agua09.txt", "not a water invoice")
            good = _write_text(root / "agua08.txt", WATER_TEXT)
            _set_mtime(bad, start + timedelta(seconds=10))
            _set_mtime(good, start + timedelta(seconds=10))

            scan = scan_new_files(root, db_path)

            self.assertEqual(scan.imported, 1)
            self.assertEqual(scan.manual_review, 1)
            with connect(db_path) as connection:
                self.assertEqual(_count(connection, "source_document"), 2)
                self.assertEqual(_count(connection, "water_invoice_detail"), 1)

    def test_scanner_does_not_ingest_historical_or_unsupported_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "facturas.sqlite3"
            report = activate_scanner(root, db_path)
            start = _from_iso(report.scanner_started_at)
            historical = _write_text(root / "agua08.txt", WATER_TEXT)
            unsupported = _write_text(root / "ticket08.txt", "ignored")
            _set_mtime(historical, start - timedelta(seconds=10))
            _set_mtime(unsupported, start + timedelta(seconds=10))

            with patch("facturas.scan.ingest_source_file") as ingest:
                scan = scan_new_files(root, db_path)

            ingest.assert_not_called()
            self.assertEqual(scan.files_considered, 0)
            self.assertEqual(scan.historical_ignored, 1)
            self.assertEqual(scan.unsupported_ignored, 1)


def _from_iso(value: str | None) -> datetime:
    assert value is not None
    return datetime.fromisoformat(value)


def _set_mtime(path: Path, value: datetime) -> None:
    timestamp = value.timestamp()
    os.utime(path, (timestamp, timestamp))


if __name__ == "__main__":
    unittest.main()
