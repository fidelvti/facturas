from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
import sqlite3

from facturas.classify import electricity_period_from_filename
from facturas.extractors.text import extract_document_text


@dataclass(frozen=True)
class PowerLine:
    potencia: str
    precio: str
    dias: str
    total: str


@dataclass(frozen=True)
class ConsumptionLine:
    consumo: str
    precio: str
    total: str


@dataclass(frozen=True)
class OtherChargeLine:
    otros: str
    alquiler: str
    imp_elec_rate: str
    iva_rate: str
    peaje_a: str
    peaje_b: str
    cargo_a: str
    cargo_b: str


@dataclass(frozen=True)
class DiscountLine:
    label: str
    amount: str


@dataclass(frozen=True)
class ElectricityExtraction:
    period_yyyymm: str | None = None
    original_period_value: str | None = None
    provider_invoice_id: str | None = None
    invoice_total: str | None = None
    section_totals: dict[str, str] = field(default_factory=dict)
    power_lines: list[PowerLine] = field(default_factory=list)
    consumption_lines: list[ConsumptionLine] = field(default_factory=list)
    other_charge_lines: list[OtherChargeLine] = field(default_factory=list)
    discounts: list[DiscountLine] = field(default_factory=list)
    payable_total: str | None = None
    errors: list[str] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        return not self.errors


def ingest_electricity_invoice(
    connection: sqlite3.Connection,
    source_path: Path,
    source_document_id: int,
    now: str,
    current_year: int | None = None,
) -> tuple[int | None, str, str, str | None]:
    text = extract_document_text(source_path)
    extraction = extract_endesa_ocr_invoice(
        text,
        filename_period_yyyymm=electricity_period_from_filename(
            source_path, default_year=current_year or _year_from_timestamp(now)
        ),
    )

    if not extraction.is_complete:
        return None, "incomplete", "manual_review", "; ".join(extraction.errors)

    validation_errors = _validate_electricity_extraction(extraction)
    if validation_errors:
        return None, "extracted", "manual_review", "; ".join(validation_errors)

    invoice_id = _insert_electricity_business_data(
        connection, source_document_id, extraction, now
    )
    return invoice_id, "extracted", "validated", None


def extract_endesa_ocr_invoice(
    text: str,
    *,
    filename_period_yyyymm: str | None,
) -> ElectricityExtraction:
    errors: list[str] = []
    normalized = _normalize_ocr_text(text)

    provider_invoice_id = _first_group(
        [r"(?im)n[°ºo]\s*factura\s*[:=]\s*([A-Z0-9]+)"],
        normalized,
    )
    invoice_total = _first_group([r"(?im)^total\s+([0-9]+[,.][0-9]{2})\s*€?\s*$"], normalized)
    if invoice_total is None:
        invoice_total = _first_group([r"(?im)\btotal\s+([0-9]+[,.][0-9]{2})\s*€"], normalized)
    payable_total = _first_group(
        [r"(?im)^total\s+(?:importe\s+a\s+pagar|a\s+pagar)\s+([0-9]+[,.][0-9]{2})\s*€?\s*$"],
        normalized,
    )
    section_totals = _extract_section_totals(normalized)
    discounts = _extract_discounts(normalized)

    period_yyyymm = filename_period_yyyymm
    if period_yyyymm is None:
        errors.append("missing electricity invoice period from filename")

    power_lines = _extract_endesa_power_lines(normalized)
    consumption_lines = _extract_endesa_consumption_lines(normalized)
    other_line = _extract_endesa_other_line(normalized)

    if provider_invoice_id is None:
        errors.append("missing provider invoice id")
    if invoice_total is None:
        errors.append("missing original invoice total")
    if set(section_totals) != {"potencia", "energia", "varios", "impuestos"}:
        errors.append("missing one or more Endesa section totals")
    if discounts and payable_total is None:
        errors.append("missing payable total for invoice adjustments")
    if len(power_lines) < 1:
        errors.append("missing electricity power lines")
    if len(consumption_lines) < 1:
        errors.append("missing electricity consumption lines")
    if other_line is None:
        errors.append("missing electricity other-charge line")

    return ElectricityExtraction(
        period_yyyymm=period_yyyymm,
        original_period_value=filename_period_yyyymm,
        provider_invoice_id=provider_invoice_id,
        invoice_total=_decimal_text(invoice_total) if invoice_total else None,
        section_totals=section_totals,
        power_lines=power_lines,
        consumption_lines=consumption_lines,
        other_charge_lines=[other_line] if other_line else [],
        discounts=discounts,
        payable_total=_decimal_text(payable_total) if payable_total else None,
        errors=errors,
    )


def _insert_electricity_business_data(
    connection: sqlite3.Connection,
    source_document_id: int,
    extraction: ElectricityExtraction,
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
            "luz",
            "electricity",
            extraction.period_yyyymm,
            extraction.original_period_value,
            extraction.provider_invoice_id,
            extraction.invoice_total,
            extraction.payable_total,
            "automated",
            source_document_id,
            now,
            "validated",
        ),
    )
    invoice_id = int(cursor.lastrowid)
    source_key = f"source_document:{source_document_id}"

    for discount in extraction.discounts:
        connection.execute(
            """
            INSERT INTO invoice_adjustment (
                invoice_id, description, amount, category
            )
            VALUES (?, ?, ?, ?)
            """,
            (invoice_id, discount.label, discount.amount, "discount"),
        )

    for sequence, line in enumerate(extraction.power_lines, start=1):
        connection.execute(
            """
            INSERT INTO electricity_power_line (
                invoice_id, line_sequence, source_worksheet, source_row_number,
                potencia, precio, dias, total
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                invoice_id,
                sequence,
                source_key,
                sequence,
                line.potencia,
                line.precio,
                line.dias,
                line.total,
            ),
        )

    for sequence, line in enumerate(extraction.consumption_lines, start=1):
        connection.execute(
            """
            INSERT INTO electricity_consumption_line (
                invoice_id, line_sequence, source_worksheet, source_row_number,
                consumo, precio, total
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                invoice_id,
                sequence,
                source_key,
                sequence,
                line.consumo,
                line.precio,
                line.total,
            ),
        )

    for sequence, line in enumerate(extraction.other_charge_lines, start=1):
        connection.execute(
            """
            INSERT INTO electricity_other_charge_line (
                invoice_id, line_sequence, source_worksheet, source_row_number,
                otros, alquiler, imp_elec_rate, iva_rate,
                peaje_a, peaje_b, cargo_a, cargo_b
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                invoice_id,
                sequence,
                source_key,
                sequence,
                line.otros,
                line.alquiler,
                line.imp_elec_rate,
                line.iva_rate,
                line.peaje_a,
                line.peaje_b,
                line.cargo_a,
                line.cargo_b,
            ),
        )
    return invoice_id


def _validate_electricity_extraction(extraction: ElectricityExtraction) -> list[str]:
    errors: list[str] = []
    if extraction.invoice_total is None:
        errors.append("missing invoice total")
    if extraction.payable_total is None:
        errors.append("missing amount payable")
    if set(extraction.section_totals) != {"potencia", "energia", "varios", "impuestos"}:
        errors.append("missing section totals for reconciliation")

    if not errors:
        section_sum = sum(_money(value) for value in extraction.section_totals.values())
        invoice_total = _money(extraction.invoice_total)
        if section_sum != invoice_total:
            errors.append(
                f"section totals {section_sum} do not equal invoice_total {invoice_total}"
            )

        adjustment_sum = sum(_money(discount.amount) for discount in extraction.discounts)
        amount_payable = _money(extraction.payable_total)
        if invoice_total + adjustment_sum != amount_payable:
            errors.append(
                f"invoice_total plus adjustments {invoice_total + adjustment_sum} does not equal amount_payable {amount_payable}"
            )

    return errors


def _extract_endesa_power_lines(text: str) -> list[PowerLine]:
    lines: list[PowerLine] = []
    pattern = (
        r"(?im)(?:p1\s*\(punta-llano\)|pot\.\s*p3)\s+"
        r"([0-9]+[,.][0-9]+)\s*kw\s*[xX]+\s*"
        r"([0-9]+[,.][0-9]+)\s*eur/kw\s*[xX]+\s*"
        r"([0-9]+)\s*d\S*as"
    )
    for potencia, precio, dias in re.findall(pattern, text):
        total = _multiply(potencia, precio, dias)
        lines.append(
            PowerLine(
                potencia=_decimal_text(potencia),
                precio=_decimal_text(precio),
                dias=_decimal_text(dias),
                total=total,
            )
        )
    return lines


def _extract_endesa_consumption_lines(text: str) -> list[ConsumptionLine]:
    lines: list[ConsumptionLine] = []
    pattern = (
        r"(?im)consumo\s+([0-9]+[,.][0-9]+)\s*kwh\s*[xX]+\s*"
        r"([0-9]+[,.][0-9]+)\s*eur/kwh"
    )
    for consumo, precio in re.findall(pattern, text):
        total = _multiply(consumo, precio)
        lines.append(
            ConsumptionLine(
                consumo=_decimal_text(consumo),
                precio=_decimal_text(precio),
                total=total,
            )
        )
    return lines


def _extract_endesa_other_line(text: str) -> OtherChargeLine | None:
    bono_factors = re.findall(
        r"(?im)financiaci\S+n\s+bono\s+social\s+([0-9]+)\s*d\S*as\s*[xX]+\s*([0-9]+[,.][0-9]+)\s*eur/d\S*a",
        text,
    )
    alquiler_factors = re.findall(
        r"(?im)alquiler\s+del\s+contador\s*\(\s*([0-9]+)\s*d\S*as\s*x\s*([0-9]+[,.][0-9]+)\s*eur/d\S*a\s*\)",
        text,
    )
    imp_elec_percent = _first_group(
        [r"(?im)impuesto\s+electricidad\s*\(\s*[0-9]+[,.][0-9]+\s*eur\s*x\s*([0-9]+[,.][0-9]+)\s*%"],
        text,
    )
    iva_percent = _first_group([r"(?im)iva\s+normal\s+([0-9]+)\s*%"], text)
    peajes = _first_group(
        [r"(?ims)peaje\s+de\s+transporte\s+y\s+distribuci\S+n,\s+que\s+ha\s+sido\s+.*?de\s+([0-9]+[,.][0-9]{2})\s*€"],
        text,
    )
    peaje_b = _first_group([r"(?im)\(\s*(?:[0-9]+[,.][0-9]+|[0-9]{2})\s*€\s*potencia,\s*([0-9]+[,.][0-9]{2})\s*€\s*por\s+energ\S+a"], text)
    cargos = _first_group([r"(?ims)cargos,\s+que\s+ha\s+sido\s+.*?de\s+([0-9]+[,.][0-9]{2})\s*€"], text)
    cargo_parts = re.search(
        r"(?im)\(\s*([0-9]+[,.][0-9]{2}).{0,20}potencia,\s*([0-9]+[,.][0-9]{2})\s*€\s*por\s+energ\S+a\s+activa",
        text,
    )
    cargo_b = cargo_parts.group(2) if cargo_parts else None

    if not bono_factors or not alquiler_factors or not imp_elec_percent or not iva_percent:
        return None
    if not peajes or not peaje_b or not cargos or not cargo_b:
        return None

    otros = _sum_decimals(
        [_multiply(days, rate) for days, rate in bono_factors],
        quantize="0.01",
    )
    alquiler = _sum_decimals(
        [_multiply(days, rate) for days, rate in alquiler_factors],
        quantize="0.01",
    )
    peaje_a = _subtract(peajes, peaje_b)
    cargo_a = _subtract(cargos, cargo_b)
    imp_elec_rate = _divide_percent(imp_elec_percent, places=9)
    iva_rate = _divide_percent(iva_percent, places=2)

    return OtherChargeLine(
        otros=otros,
        alquiler=alquiler,
        imp_elec_rate=imp_elec_rate,
        iva_rate=iva_rate,
        peaje_a=peaje_a,
        peaje_b=_decimal_text(peaje_b),
        cargo_a=cargo_a,
        cargo_b=_decimal_text(cargo_b),
    )


def _extract_discounts(text: str) -> list[DiscountLine]:
    discounts: list[DiscountLine] = []
    seen: set[tuple[str, str]] = set()
    for label, amount in re.findall(
        r"(?im)^([A-ZÁÉÍÓÚÜÑ ]{3,})\s+(-[0-9]+[,.][0-9]{2})\s*€?\s*$",
        text,
    ):
        normalized_label = " ".join(label.split())
        if normalized_label.startswith("TOTAL"):
            continue
        normalized_amount = _money_text(amount)
        key = (normalized_label, normalized_amount)
        if key not in seen:
            discounts.append(DiscountLine(label=normalized_label, amount=normalized_amount))
            seen.add(key)
    return discounts


def _extract_section_totals(text: str) -> dict[str, str]:
    labels = {
        "potencia": r"potencia",
        "energia": r"energ\S+a",
        "varios": r"varios",
        "impuestos": r"impuestos",
    }
    totals: dict[str, str] = {}
    for key, label_pattern in labels.items():
        value = _first_group(
            [rf"(?im)^{label_pattern}\s+\.{{3,}}\s*([0-9]+[,.][0-9]{{2}})\s*€?\s*$"],
            text,
        )
        if value is None and key == "energia":
            value = _first_group(
                [r"(?im)^energ\S+a\s+([0-9]+[,.][0-9]{2})\s*€?\s*$"],
                text,
            )
        if value is not None:
            totals[key] = _decimal_text(value)
    return totals


def _normalize_ocr_text(text: str) -> str:
    normalized = text.replace("€", "€ ")
    normalized = re.sub(r"\bO(?=,?\d)", "0", normalized)
    normalized = re.sub(r"\bD(?=,?\d)", "0", normalized)
    normalized = re.sub(r"[ \t]+", " ", normalized)
    return normalized


def _multiply(*values: str) -> str:
    result = Decimal("1")
    for value in values:
        result *= Decimal(value.replace(",", "."))
    return format(result.normalize(), "f")


def _sum_decimals(values: list[str], *, quantize: str | None = None) -> str:
    result = sum(Decimal(value.replace(",", ".")) for value in values)
    if quantize:
        result = result.quantize(Decimal(quantize))
    return format(result.normalize(), "f")


def _subtract(left: str, right: str) -> str:
    result = Decimal(left.replace(",", ".")) - Decimal(right.replace(",", "."))
    result = result.quantize(Decimal("0.01"))
    return format(result.normalize(), "f")


def _divide_percent(value: str, *, places: int) -> str:
    quant = Decimal("1").scaleb(-places)
    result = (Decimal(value.replace(",", ".")) / Decimal("100")).quantize(quant)
    return format(result.normalize(), "f")


def _money(value: str | None) -> Decimal:
    if value is None:
        raise ValueError("Money value cannot be None")
    return Decimal(value).quantize(Decimal("0.01"))


def _year_from_timestamp(value: str) -> int:
    return int(value[:4])


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
