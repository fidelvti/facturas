from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime
import json
from pathlib import Path

from .classify import classify_source_document
from .db import connect, create_schema
from .ingest import IngestionReport, ingest_source_file


@dataclass
class ScanReport:
    status: str
    scanner_started_at: str | None
    scanned_root: str
    files_considered: int = 0
    historical_ignored: int = 0
    unsupported_ignored: int = 0
    imported: int = 0
    skipped_duplicate: int = 0
    manual_review: int = 0
    reports: list[dict] = field(default_factory=list)


def activate_scanner(root: Path, database_path: Path) -> ScanReport:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with connect(database_path) as connection:
        create_schema(connection)
        existing = _scanner_started_at(connection)
        if existing is not None:
            return ScanReport(
                status="already_activated",
                scanner_started_at=existing,
                scanned_root=str(root.expanduser().resolve()),
            )

        started_at = _local_timestamp()
        with connection:
            connection.execute(
                "INSERT INTO scanner_state (id, scanner_started_at) VALUES (1, ?)",
                (started_at,),
            )
        return ScanReport(
            status="activated",
            scanner_started_at=started_at,
            scanned_root=str(root.expanduser().resolve()),
        )


def scan_new_files(root: Path, database_path: Path) -> ScanReport:
    root = root.expanduser().resolve()
    database_path = database_path.expanduser().resolve()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with connect(database_path) as connection:
        create_schema(connection)
        started_at = _scanner_started_at(connection)

    if started_at is None:
        return ScanReport(
            status="not_activated",
            scanner_started_at=None,
            scanned_root=str(root),
        )

    cutoff = datetime.fromisoformat(started_at)
    report = ScanReport(
        status="scanned",
        scanner_started_at=started_at,
        scanned_root=str(root),
    )
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.resolve() == database_path:
            continue
        classification = classify_source_document(path)
        if classification.confidence != "high":
            report.unsupported_ignored += 1
            continue

        modified_at = datetime.fromtimestamp(path.stat().st_mtime).astimezone()
        if modified_at <= cutoff:
            report.historical_ignored += 1
            continue

        report.files_considered += 1
        try:
            ingestion = ingest_source_file(path, database_path)
        except Exception as exc:
            report.manual_review += 1
            report.reports.append({"path": str(path), "status": "failed", "reason": str(exc)})
            continue

        report.reports.append({"path": str(path), **ingestion.__dict__})
        if ingestion.status == "imported":
            report.imported += 1
        elif ingestion.status == "skipped_duplicate":
            report.skipped_duplicate += 1
        elif ingestion.status == "manual_review":
            report.manual_review += 1
    return report


def _scanner_started_at(connection) -> str | None:
    row = connection.execute(
        "SELECT scanner_started_at FROM scanner_state WHERE id = 1"
    ).fetchone()
    return row[0] if row else None


def _local_timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan a source tree for new supported invoices.")
    parser.add_argument("source_root", type=Path)
    parser.add_argument("--database", type=Path, default=Path("data/facturas.sqlite3"))
    parser.add_argument("--activate", action="store_true")
    args = parser.parse_args()

    if args.activate:
        report = activate_scanner(args.source_root, args.database)
    else:
        report = scan_new_files(args.source_root, args.database)
    print(json.dumps(report.__dict__, indent=2, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
