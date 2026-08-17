from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3

from .classify import classify_source_document
from .db import connect, create_schema
from .extractors.electricity import ingest_electricity_invoice
from .extractors.gas import ingest_gas_invoice
from .extractors.pagatelia import ingest_pagatelia_invoice
from .extractors.payroll import ingest_payroll_report
from .extractors.water import ingest_water_invoice


DATABASE_PATH = Path("data/facturas.sqlite3")
INGESTION_ORIGIN = "automated"


@dataclass
class IngestionReport:
    status: str
    source_document_id: int | None
    provider: str
    document_type: str
    file_sha256: str
    extraction_status: str
    validation_status: str
    invoice_id: int | None = None
    reason: str | None = None


def ingest_source_file(source_path: Path, database_path: Path = DATABASE_PATH) -> IngestionReport:
    source_path = source_path.expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(source_path)

    classification = classify_source_document(source_path)
    file_hash = _sha256(source_path)
    now = _local_timestamp()

    database_path.parent.mkdir(parents=True, exist_ok=True)
    with connect(database_path) as connection:
        create_schema(connection)
        duplicate = connection.execute(
            "SELECT id, provider, document_type, extraction_status, validation_status FROM source_document WHERE file_sha256 = ?",
            (file_hash,),
        ).fetchone()
        if duplicate is not None:
            return IngestionReport(
                status="skipped_duplicate",
                source_document_id=duplicate[0],
                provider=duplicate[1],
                document_type=duplicate[2],
                file_sha256=file_hash,
                extraction_status=duplicate[3],
                validation_status=duplicate[4],
                reason="file_sha256 already exists in source_document",
            )

        with connection:
            source_document_id = _insert_source_document(
                connection, source_path, classification, file_hash, now
            )

            if classification.provider not in {"luz", "gas", "agua", "gft", "pagatelia"}:
                _mark_source_document(
                    connection,
                    source_document_id,
                    extraction_status="unsupported",
                    validation_status="manual_review",
                )
                return IngestionReport(
                    status="manual_review",
                    source_document_id=source_document_id,
                    provider=classification.provider,
                    document_type=classification.document_type,
                    file_sha256=file_hash,
                    extraction_status="unsupported",
                    validation_status="manual_review",
                    reason=classification.reason,
                )

            provider_ingesters = {
                "luz": ingest_electricity_invoice,
                "gas": ingest_gas_invoice,
                "agua": ingest_water_invoice,
                "gft": ingest_payroll_report,
                "pagatelia": ingest_pagatelia_invoice,
            }
            try:
                invoice_id, extraction_status, validation_status, reason = provider_ingesters[
                    classification.provider
                ](connection, source_path, source_document_id, now)
            except Exception as exc:
                return _manual_review_report(
                    connection,
                    classification,
                    file_hash,
                    source_document_id,
                    "failed",
                    str(exc),
                )

            if validation_status != "validated" or invoice_id is None:
                return _manual_review_report(
                    connection,
                    classification,
                    file_hash,
                    source_document_id,
                    extraction_status,
                    reason or "extraction requires manual review",
                )
            return _imported_report(
                connection, classification, file_hash, source_document_id, invoice_id
            )


def _manual_review_report(
    connection: sqlite3.Connection,
    classification,
    file_hash: str,
    source_document_id: int,
    extraction_status: str,
    reason: str,
) -> IngestionReport:
    _mark_source_document(
        connection,
        source_document_id,
        extraction_status=extraction_status,
        validation_status="manual_review",
    )
    return IngestionReport(
        status="manual_review",
        source_document_id=source_document_id,
        provider=classification.provider,
        document_type=classification.document_type,
        file_sha256=file_hash,
        extraction_status=extraction_status,
        validation_status="manual_review",
        reason=reason,
    )


def _imported_report(
    connection: sqlite3.Connection,
    classification,
    file_hash: str,
    source_document_id: int,
    invoice_id: int,
) -> IngestionReport:
    _mark_source_document(
        connection,
        source_document_id,
        extraction_status="extracted",
        validation_status="validated",
    )
    return IngestionReport(
        status="imported",
        source_document_id=source_document_id,
        provider=classification.provider,
        document_type=classification.document_type,
        file_sha256=file_hash,
        extraction_status="extracted",
        validation_status="validated",
        invoice_id=invoice_id,
    )


def _insert_source_document(
    connection: sqlite3.Connection,
    source_path: Path,
    classification,
    file_hash: str,
    now: str,
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO source_document (
            path,
            filename,
            provider,
            document_type,
            file_sha256,
            file_size_bytes,
            discovered_at,
            imported_at,
            ingestion_origin,
            extraction_status,
            validation_status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(source_path),
            source_path.name,
            classification.provider,
            classification.document_type,
            file_hash,
            source_path.stat().st_size,
            now,
            now,
            INGESTION_ORIGIN,
            "pending",
            "pending",
        ),
    )
    return int(cursor.lastrowid)


def _mark_source_document(
    connection: sqlite3.Connection,
    source_document_id: int,
    *,
    extraction_status: str,
    validation_status: str,
) -> None:
    connection.execute(
        """
        UPDATE source_document
        SET extraction_status = ?, validation_status = ?
        WHERE id = ?
        """,
        (extraction_status, validation_status, source_document_id),
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _local_timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def main() -> None:
    parser = argparse.ArgumentParser(description="Manually ingest one new source document.")
    parser.add_argument("source_file", type=Path)
    parser.add_argument("--database", type=Path, default=DATABASE_PATH)
    args = parser.parse_args()
    report = ingest_source_file(args.source_file, args.database)
    print(json.dumps(report.__dict__, indent=2, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
