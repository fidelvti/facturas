from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
import sqlite3

from facturas.classify import gas_period_from_filename
from facturas.extractors.text import extract_document_text


@dataclass(frozen=True)
class GasPowerLine:
    dias: str
    plazo_fijo: str
    total: str


@dataclass(frozen=True)
class GasConsumptionLine:
    consumo: str
    importe: str
    total: str


@dataclass(frozen=True)
class GasOtherLine:
    imp_hc: str
    alquiler: str
    canon: str
    iva_rate: str
    peajes: str
    cargos: str


@dataclass(frozen=True)
class GasExtraction:
    period_yyyymm: str | None
    provider_invoice_id: str | None
    invoice_total: str | None
    power_lines: list[GasPowerLine] = field(default_factory=list)
    consumption_lines: list[GasConsumptionLine] = field(default_factory=list)
    other_line: GasOtherLine | None = None
    errors: list[str] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        return not self.errors


def ingest_gas_invoice(
    connection: sqlite3.Connection,
    source_path: Path,
    source_document_id: int,
    now: str,
) -> tuple[int | None, str, str, str | None]:
    text = extract_document_text(source_path)
    extraction = extract_gas_invoice(
        text,
        filename_period_yyyymm=gas_period_from_filename(
            source_path, default_year=_year_from_timestamp(now)
        ),
    )

    if not extraction.is_complete:
        return None, "incomplete", "manual_review", "; ".join(extraction.errors)

    invoice_id = _insert_gas_business_data(connection, source_document_id, extraction, now)
    return invoice_id, "extracted", "validated", None


def extract_gas_invoice(text: str, *, filename_period_yyyymm: str | None) -> GasExtraction:
    normalized = _normalize_text(text)
    errors: list[str] = []

    provider_invoice_id = _first_group(
        [r"(?im)n[úu]m\.\s*factura\s*:\s*([A-Z0-9]+)"],
        normalized,
    )
    invoice_total = _first_group(
        [r"(?im)^total\s+a\s+pagar\s+([0-9]+[,.][0-9]{2})\s*€?\s*$"],
        normalized,
    )
    power_lines = _extract_power_lines(normalized)
    consumption_lines = _extract_consumption_lines(normalized)
    other_line = _extract_other_line(normalized)

    if filename_period_yyyymm is None:
        errors.append("missing gas invoice period from filename")
    if provider_invoice_id is None:
        errors.append("missing provider invoice id")
    if invoice_total is None:
        errors.append("missing invoice total")
    if not power_lines:
        errors.append("missing gas fixed-term line")
    if not consumption_lines:
        errors.append("missing gas consumption lines")
    if other_line is None:
        errors.append("missing gas other-charge line")

    return GasExtraction(
        period_yyyymm=filename_period_yyyymm,
        provider_invoice_id=provider_invoice_id,
        invoice_total=_money_text(invoice_total) if invoice_total else None,
        power_lines=power_lines,
        consumption_lines=consumption_lines,
        other_line=other_line,
        errors=errors,
    )


def _extract_power_lines(text: str) -> list[GasPowerLine]:
    lines: list[GasPowerLine] = []
    for days, rate in re.findall(
        r"(?im)terme\s+fix\s+([0-9]+)\s+dies\s+([0-9]+[,.][0-9]+)\s*€\s*/dia",
        text,
    ):
        lines.append(GasPowerLine(days, _decimal_text(rate), _multiply(days, rate)))
    return lines


def _insert_gas_business_data(
    connection: sqlite3.Connection,
    source_document_id: int,
    extraction: GasExtraction,
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
            "gas",
            "gas",
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
    source_key = f"source_document:{source_document_id}"

    for sequence, line in enumerate(extraction.power_lines, start=1):
        connection.execute(
            """
            INSERT INTO gas_power_line (
                invoice_id, line_sequence, source_worksheet, source_row_number,
                dias, plazo_fijo, total
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (invoice_id, sequence, source_key, sequence, line.dias, line.plazo_fijo, line.total),
        )

    for sequence, line in enumerate(extraction.consumption_lines, start=1):
        connection.execute(
            """
            INSERT INTO gas_consumption_line (
                invoice_id, line_sequence, source_worksheet, source_row_number,
                consumo, importe, total
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (invoice_id, sequence, source_key, sequence, line.consumo, line.importe, line.total),
        )

    other = extraction.other_line
    if other is None:
        raise ValueError("Gas other line is required")
    connection.execute(
        """
        INSERT INTO gas_other_charge_line (
            invoice_id, line_sequence, source_worksheet, source_row_number,
            imp_hc, alquiler, canon, iva_rate, peajes, cargos
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            invoice_id,
            1,
            source_key,
            1,
            other.imp_hc,
            other.alquiler,
            other.canon,
            other.iva_rate,
            other.peajes,
            other.cargos,
        ),
    )
    return invoice_id


def _extract_consumption_lines(text: str) -> list[GasConsumptionLine]:
    lines: list[GasConsumptionLine] = []
    for consumo, rate in re.findall(
        r"(?im)per[ií]ode\s+de\s+[0-9.]+\s+a\s+[0-9.]+\s+([0-9]+)\s+kwh\s+([0-9]+[,.][0-9]+)\s*€\s*/kwh",
        text,
    ):
        lines.append(GasConsumptionLine(consumo, _decimal_text(rate), _multiply(consumo, rate)))
    return lines


def _extract_other_line(text: str) -> GasOtherLine | None:
    imp_hc = _first_group(
        [r"(?im)impost\s+especial\s+sobre\s+hidrocarburs\s+[0-9]+\s+kwh\s+[0-9]+[,.][0-9]+\s*€\s*/kwh\s+([0-9]+[,.][0-9]{2})\s*€"]
        ,
        text,
    )
    alquiler = _first_group(
        [r"(?im)lloguer\s+de\s+comptador\s+[0-9]+\s+dies\s+[0-9]+[,.][0-9]+\s*€\s*/dia\s+([0-9]+[,.][0-9]{2})\s*€"],
        text,
    )
    canon = _first_group([r"(?im)c[aà]non\s+de\s+finca\s+[0-9]+\s+([0-9]+[,.][0-9]{2})\s*€"], text)
    iva = _first_group([r"(?im)total\s+iva\s+([0-9]+)\s*%"], text)
    peajes = _first_group([r"(?im)import\s+de\s+peatges\s*:\s*([0-9]+[,.][0-9]{2})\s*€"], text)
    cargos = _first_group([r"(?im)import\s+de\s+c[aà]rrecs\s*:\s*([0-9]+[,.][0-9]{2})\s*€"], text)

    if not all([imp_hc, alquiler, canon, iva, peajes, cargos]):
        return None

    return GasOtherLine(
        imp_hc=_money_text(imp_hc),
        alquiler=_money_text(alquiler),
        canon=_money_text(canon),
        iva_rate=_percent_rate(iva),
        peajes=_money_text(peajes),
        cargos=_money_text(cargos),
    )


def _normalize_text(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text.replace("€", "€ "))


def _first_group(patterns: list[str], text: str) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    return None


def _multiply(*values: str) -> str:
    result = Decimal("1")
    for value in values:
        result *= Decimal(value.replace(",", "."))
    return format(result.normalize(), "f")


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


def _percent_rate(value: str) -> str:
    return format((Decimal(value.replace(",", ".")) / Decimal("100")).normalize(), "f")


def _year_from_timestamp(value: str) -> int:
    return int(value[:4])
