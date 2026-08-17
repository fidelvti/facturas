from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
import sqlite3
import subprocess
import tempfile

from facturas.classify import pagatelia_period_from_filename


@dataclass(frozen=True)
class PagateliaGroupedAmount:
    importe: str
    total: str
    factura: str


@dataclass(frozen=True)
class PagateliaExtraction:
    period_yyyymm: str | None
    movement_list_count: int
    movements: list[str] = field(default_factory=list)
    grouped_amounts: list[PagateliaGroupedAmount] = field(default_factory=list)
    printed_total: str | None = None
    errors: list[str] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        return not self.errors


def ingest_pagatelia_invoice(
    connection: sqlite3.Connection,
    source_path: Path,
    source_document_id: int,
    now: str,
) -> tuple[int | None, str, str, str | None]:
    text = extract_pagatelia_final_page_text(source_path)
    extraction = extract_pagatelia_invoice(
        text,
        filename_period_yyyymm=pagatelia_period_from_filename(source_path),
    )

    if not extraction.is_complete:
        return None, "incomplete", "manual_review", "; ".join(extraction.errors)

    first_id = _insert_pagatelia_business_data(connection, source_document_id, extraction, now)
    return first_id, "extracted", "validated", None


def extract_pagatelia_invoice(
    text: str,
    *,
    filename_period_yyyymm: str | None,
) -> PagateliaExtraction:
    normalized = _normalize_text(text)
    blocks = _movement_list_blocks(normalized)
    movements = _extract_movements(blocks)
    grouped = _group_movements(movements)
    printed_total = _printed_total(normalized)
    errors: list[str] = []

    if filename_period_yyyymm is None:
        errors.append("missing Pagatelia period from filename")
    if not blocks:
        errors.append("missing Pagatelia movement list")
    if not movements:
        errors.append("missing Pagatelia movement amounts")

    return PagateliaExtraction(
        period_yyyymm=filename_period_yyyymm,
        movement_list_count=len(blocks),
        movements=movements,
        grouped_amounts=grouped,
        printed_total=printed_total,
        errors=errors,
    )


def extract_pagatelia_final_page_text(path: Path) -> str:
    if path.suffix.lower() in {".txt", ".text"}:
        return path.read_text(encoding="utf-8-sig")
    direct_text = _extract_final_page_text_direct(path)
    if _has_enough_pagatelia_text(direct_text):
        return direct_text
    rendered_text = _extract_final_page_text_with_local_ocr(path)
    if rendered_text.strip():
        return rendered_text
    return path.read_bytes().decode("latin-1", errors="ignore")


def _insert_pagatelia_business_data(
    connection: sqlite3.Connection,
    source_document_id: int,
    extraction: PagateliaExtraction,
    now: str,
) -> int:
    first_id: int | None = None
    source_key = f"source_document:{source_document_id}"
    for sequence, group in enumerate(extraction.grouped_amounts, start=1):
        cursor = connection.execute(
            """
            INSERT INTO toll_transaction (
                provider,
                period_yyyymm,
                original_period_value,
                importe,
                total_count,
                factura,
                ingestion_origin,
                source_document_id,
                source_worksheet,
                source_row_number,
                created_at,
                validation_status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "pagatelia",
                extraction.period_yyyymm,
                extraction.period_yyyymm,
                group.importe,
                group.total,
                group.factura,
                "automated",
                source_document_id,
                source_key,
                sequence,
                now,
                "validated",
            ),
        )
        if first_id is None:
            first_id = int(cursor.lastrowid)
    if first_id is None:
        raise ValueError("Pagatelia grouped amounts are required")
    return first_id


def _movement_list_blocks(text: str) -> list[str]:
    pattern = (
        r"(?ims)fecha\s+concepto\s+precio\s*€\s+tipo\s+iva\s*%\s+cuota\s+iva\s*€\s+subtotal\s*€"
        r"(.*?)^SUBTOTAL\b.*?$"
    )
    return [match.strip() for match in re.findall(pattern, text)]


def _extract_movements(blocks: list[str]) -> list[str]:
    movements: list[str] = []
    for block in blocks:
        for line in block.splitlines():
            decimal_values = re.findall(r"-?[0-9]+[,.][0-9]+", line)
            if decimal_values:
                movements.append(_money_text(decimal_values[-1]))
    return movements


def _group_movements(movements: list[str]) -> list[PagateliaGroupedAmount]:
    counts = Counter(movements)
    return [
        PagateliaGroupedAmount(
            importe=amount,
            total=str(count),
            factura=_multiply(amount, str(count)),
        )
        for amount, count in sorted(counts.items(), key=lambda item: Decimal(item[0]))
    ]


def _printed_total(text: str) -> str | None:
    totals = re.findall(r"(?im)^SUBTOTAL\s+.*?([0-9]+[,.][0-9]{2})\s*$", text)
    if totals:
        return _money_text(_sum_decimals([_money_text(value) for value in totals]))
    return None


def _extract_final_page_text_direct(path: Path) -> str:
    try:
        import pypdfium2 as pdfium
    except Exception:
        return ""

    pdf = pdfium.PdfDocument(str(path))
    try:
        page = pdf[len(pdf) - 1]
        return page.get_textpage().get_text_range()
    except Exception:
        return ""
    finally:
        pdf.close()


def _extract_final_page_text_with_local_ocr(path: Path) -> str:
    try:
        import pypdfium2 as pdfium
    except Exception:
        return ""
    if not _has_tesseract():
        return ""

    with tempfile.TemporaryDirectory(prefix="facturas-pagatelia-ocr-") as tmpdir:
        image_path = Path(tmpdir) / "final-page.png"
        pdf = pdfium.PdfDocument(str(path))
        try:
            page = pdf[len(pdf) - 1]
            page.render(scale=4).to_pil().save(image_path)
            result = subprocess.run(
                ["tesseract", str(image_path), "stdout", "-l", "eng", "--psm", "6"],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            return result.stdout
        finally:
            pdf.close()


def _has_enough_pagatelia_text(text: str) -> bool:
    lowered = text.lower()
    return (
        len(text.strip()) > 200
        and "factura de telepeaje" in lowered
        and "subtotal" in lowered
    )


def _has_tesseract() -> bool:
    try:
        result = subprocess.run(
            ["tesseract", "--version"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return False
    return result.returncode == 0


def _normalize_text(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text.replace("€", "€ "))


def _money_text(value: str) -> str:
    try:
        decimal = Decimal(value.replace(",", "."))
    except InvalidOperation as exc:
        raise ValueError(f"Invalid money value: {value}") from exc
    return format(decimal.quantize(Decimal("0.01")), "f")


def _multiply(left: str, right: str) -> str:
    return format((Decimal(left) * Decimal(right)).quantize(Decimal("0.01")), "f")


def _sum_decimals(values: list[str]) -> str:
    return format(sum(Decimal(value) for value in values).quantize(Decimal("0.01")), "f")
