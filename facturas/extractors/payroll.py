from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
import sqlite3

from facturas.classify import payroll_period_from_filename
from facturas.extractors.text import extract_document_text


@dataclass(frozen=True)
class PayrollExtraction:
    period_yyyymm: str | None
    guardias: str | None
    gastos: str | None
    dietas: str | None
    bonus: str | None
    total: str | None
    irpf_percent: str | None
    errors: list[str] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        return not self.errors


def ingest_payroll_report(
    connection: sqlite3.Connection,
    source_path: Path,
    source_document_id: int,
    now: str,
) -> tuple[int | None, str, str, str | None]:
    text = extract_document_text(source_path)
    extraction = extract_gft_payroll_report(
        text,
        filename_period_yyyymm=payroll_period_from_filename(
            source_path, default_year=_year_from_timestamp(now)
        ),
    )

    if not extraction.is_complete:
        return None, "incomplete", "manual_review", "; ".join(extraction.errors)

    payroll_id = _insert_payroll_report(connection, source_document_id, extraction, now)
    return payroll_id, "extracted", "validated", None


def extract_gft_payroll_report(
    text: str,
    *,
    filename_period_yyyymm: str | None,
) -> PayrollExtraction:
    normalized = _normalize_text(text)
    errors: list[str] = []

    total = _first_group(
        [r"(?im)liquido\s+a\s+recibir\s+([0-9]+[,.][0-9]{2})\s*€?"],
        normalized,
    )
    irpf_percent = _first_group(
        [
            r"(?im)imp\s+a\s+cuenta\s+renta\s+[0-9]+[,.][0-9]+\s+([0-9]+[,.][0-9]+)\s+[0-9]+[,.][0-9]{2}"
        ],
        normalized,
    )
    gastos = _normal_payroll_gastos(normalized)

    if filename_period_yyyymm is None:
        errors.append("missing payroll period from filename")
    if total is None:
        errors.append("missing payroll total")
    if irpf_percent is None:
        errors.append("missing payroll IRPF percent")

    return PayrollExtraction(
        period_yyyymm=filename_period_yyyymm,
        guardias=None,
        gastos=gastos,
        dietas=None,
        bonus=None,
        total=_money_text(total) if total else None,
        irpf_percent=_decimal_text(irpf_percent) if irpf_percent else None,
        errors=errors,
    )


def _normal_payroll_gastos(text: str) -> str | None:
    if "sueldo base" not in text.lower():
        return None
    comida = _first_group([r"(?im)^\s*698\s+COMIDA\s+([0-9]+[,.][0-9]{2})\s*$"], text)
    return _money_text(comida) if comida else None


def _insert_payroll_report(
    connection: sqlite3.Connection,
    source_document_id: int,
    extraction: PayrollExtraction,
    now: str,
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO payroll_report (
            employer,
            period_yyyymm,
            original_period_value,
            guardias,
            gastos,
            dietas,
            bonus,
            total,
            irpf_percent,
            ingestion_origin,
            source_document_id,
            created_at,
            validation_status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "GFT",
            extraction.period_yyyymm,
            extraction.period_yyyymm,
            extraction.guardias,
            extraction.gastos,
            extraction.dietas,
            extraction.bonus,
            extraction.total,
            extraction.irpf_percent,
            "automated",
            source_document_id,
            now,
            "validated",
        ),
    )
    return int(cursor.lastrowid)


def _normalize_text(text: str) -> str:
    normalized = text.replace("Í", "I").replace("í", "i")
    normalized = normalized.replace("Ó", "O").replace("ó", "o")
    normalized = normalized.replace("NOMINA", "NOMINA")
    return re.sub(r"[ \t]+", " ", normalized)


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
