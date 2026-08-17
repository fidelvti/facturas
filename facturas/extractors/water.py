from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
import sqlite3

from facturas.classify import water_period_from_filename
from facturas.extractors.text import extract_document_text


@dataclass(frozen=True)
class WaterExtraction:
    period_yyyymm: str | None
    provider_invoice_id: str | None
    invoice_total: str | None
    lectura: str | None
    consumo_m3: str | None
    errors: list[str] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        return not self.errors


def ingest_water_invoice(
    connection: sqlite3.Connection,
    source_path: Path,
    source_document_id: int,
    now: str,
) -> tuple[int | None, str, str, str | None]:
    text = extract_document_text(source_path)
    extraction = extract_water_invoice(
        text,
        filename_period_yyyymm=water_period_from_filename(
            source_path, default_year=_year_from_timestamp(now)
        ),
    )

    if not extraction.is_complete:
        return None, "incomplete", "manual_review", "; ".join(extraction.errors)

    invoice_id = _insert_water_business_data(connection, source_document_id, extraction, now)
    return invoice_id, "extracted", "validated", None


def extract_water_invoice(text: str, *, filename_period_yyyymm: str | None) -> WaterExtraction:
    normalized = _normalize_text(text)
    errors: list[str] = []

    provider_invoice_id = _first_group(
        [r"(?im)n[úu]m\.\s*factura\s+([A-Z0-9]+)"],
        normalized,
    )
    invoice_total = _first_group(
        [r"(?im)total\s+a\s+pagar\s+([0-9]+[,.][0-9]{2})\s*€?"],
        normalized,
    )
    consumo_m3 = _first_group(
        [r"(?im)consum\s+total\s+([0-9]+(?:[,.][0-9]+)?)\s*m3"],
        normalized,
    )
    lectura = _first_group(
        [
            r"(?im)^[A-Z0-9]+\s+[0-9]+\s+[0-9]{2}-[0-9]{2}-[0-9]{2}\s+[0-9]+\s+[0-9]{2}-[0-9]{2}-[0-9]{2}\s+([0-9]+)\s+[0-9]+(?:[,.][0-9]+)?\s+Real\s*$"
        ],
        normalized,
    )

    if filename_period_yyyymm is None:
        errors.append("missing water invoice period from filename")
    if provider_invoice_id is None:
        errors.append("missing provider invoice id")
    if invoice_total is None:
        errors.append("missing invoice total")
    if lectura is None:
        errors.append("missing current meter reading")
    if consumo_m3 is None:
        errors.append("missing water consumption")

    return WaterExtraction(
        period_yyyymm=filename_period_yyyymm,
        provider_invoice_id=provider_invoice_id,
        invoice_total=_money_text(invoice_total) if invoice_total else None,
        lectura=_decimal_text(lectura) if lectura else None,
        consumo_m3=_decimal_text(consumo_m3) if consumo_m3 else None,
        errors=errors,
    )


def _insert_water_business_data(
    connection: sqlite3.Connection,
    source_document_id: int,
    extraction: WaterExtraction,
    now: str,
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO invoice (
            provider,
            invoice_kind,
            period_yyyymm,
            original_period_value,
            provider_invoice_id,
            invoice_total,
            amount_payable,
            ingestion_origin,
            source_document_id,
            created_at,
            validation_status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "agua",
            "water",
            extraction.period_yyyymm,
            extraction.period_yyyymm,
            extraction.provider_invoice_id,
            extraction.invoice_total,
            extraction.invoice_total,
            "automated",
            source_document_id,
            now,
            "validated",
        ),
    )
    invoice_id = int(cursor.lastrowid)
    connection.execute(
        """
        INSERT INTO water_invoice_detail (
            invoice_id, importe_total, lectura, consumo_m3
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            invoice_id,
            extraction.invoice_total,
            extraction.lectura,
            extraction.consumo_m3,
        ),
    )
    return invoice_id


def _normalize_text(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text.replace("€", "€ "))


def _first_group(patterns: list[str], text: str) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    return None


def _decimal_text(value: str) -> str:
    try:
        decimal = Decimal(value.replace(",", "."))
    except InvalidOperation as exc:
        raise ValueError(f"Invalid decimal value: {value}") from exc
    if decimal == decimal.to_integral_value():
        return str(decimal.quantize(Decimal("1")))
    return format(decimal.normalize(), "f")


def _money_text(value: str) -> str:
    try:
        decimal = Decimal(value.replace(",", "."))
    except InvalidOperation as exc:
        raise ValueError(f"Invalid money value: {value}") from exc
    return format(decimal.quantize(Decimal("0.01")), "f")


def _year_from_timestamp(value: str) -> int:
    return int(value[:4])
