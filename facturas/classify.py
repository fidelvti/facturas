from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


@dataclass(frozen=True)
class DocumentClassification:
    provider: str
    document_type: str
    confidence: str
    reason: str


def classify_source_document(path: Path) -> DocumentClassification:
    name = path.name.lower()
    parts = [part.lower() for part in path.parts]

    if re.match(r"^luz\d{2}", name):
        return DocumentClassification(
            provider="luz",
            document_type="electricity_invoice",
            confidence="high",
            reason="filename starts with luzXX",
        )

    if re.match(r"^gas\d{2}", name):
        return DocumentClassification(
            provider="gas",
            document_type="gas_invoice",
            confidence="high",
            reason="filename starts with gasXX",
        )

    if re.match(r"^agua\d{2}", name):
        return DocumentClassification(
            provider="agua",
            document_type="water_invoice",
            confidence="high",
            reason="filename starts with aguaXX",
        )

    if re.match(r"^gft\d{2}", name):
        return DocumentClassification(
            provider="gft",
            document_type="payroll_report",
            confidence="high",
            reason="filename starts with gftXX",
        )

    if re.match(r"^pagatelia\d{2}(?:-\d+)?\.", name):
        return DocumentClassification(
            provider="pagatelia",
            document_type="toll_invoice",
            confidence="high",
            reason="filename starts with pagateliaMM",
        )

    if re.match(r"^pagatelia\d{4}", name):
        return DocumentClassification(
            provider="pagatelia",
            document_type="toll_invoice",
            confidence="high",
            reason="filename starts with PagateliaYYMM",
        )

    if "luz" in parts or "electricity" in parts:
        return DocumentClassification(
            provider="luz",
            document_type="electricity_invoice",
            confidence="medium",
            reason="folder path contains luz/electricity",
        )

    return DocumentClassification(
        provider="unknown",
        document_type="unknown",
        confidence="none",
        reason="no reliable filename or folder convention matched",
    )


def electricity_period_from_filename(path: Path, *, default_year: int | None = None) -> str | None:
    return _period_from_prefixed_filename(path, "luz", default_year=default_year)


def gas_period_from_filename(path: Path, *, default_year: int | None = None) -> str | None:
    return _period_from_prefixed_filename(path, "gas", default_year=default_year)


def water_period_from_filename(path: Path, *, default_year: int | None = None) -> str | None:
    return _period_from_prefixed_filename(path, "agua", default_year=default_year)


def payroll_period_from_filename(path: Path, *, default_year: int | None = None) -> str | None:
    return _period_from_prefixed_filename(path, "gft", default_year=default_year)


def pagatelia_period_from_filename(path: Path) -> str | None:
    match = re.match(r"^pagatelia(?P<year>[0-9]{2})(?P<month>[0-9]{2})", path.name.lower())
    if not match:
        return None
    month = int(match.group("month"))
    if month < 1 or month > 12:
        return None
    return f"20{match.group('year')}{month:02d}"


def active_pagatelia_period_from_filename(
    path: Path,
    *,
    default_year: int,
) -> str | None:
    match = re.match(r"^pagatelia(?P<month>[0-9]{2})(?:-[0-9]+)?\.", path.name.lower())
    if not match:
        return None
    month = int(match.group("month"))
    if month < 1 or month > 12:
        return None
    return f"{default_year}{month:02d}"


def _period_from_prefixed_filename(
    path: Path,
    prefix: str,
    *,
    default_year: int | None = None,
) -> str | None:
    match = re.match(rf"^{prefix}(?P<month>[0-9]{{2}})", path.name.lower())
    if not match:
        return None
    month = int(match.group("month"))
    if month < 1 or month > 12:
        return None
    year = default_year
    if year is None:
        year_match = re.search(r"(20[0-9]{2})", path.name)
        if year_match:
            year = int(year_match.group(1))
    if year is None:
        return None
    return f"{year}{month:02d}"
