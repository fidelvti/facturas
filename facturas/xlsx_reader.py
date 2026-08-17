from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
import re
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET
from zipfile import ZipFile


NS = {
    "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}


@dataclass(frozen=True)
class CellValue:
    value: str | None
    raw_value: str | None
    cell_type: str
    formula: str | None = None


@dataclass(frozen=True)
class Sheet:
    name: str
    headers: list[str]
    rows: list[dict[str, CellValue]]
    row_numbers: list[int]


def read_workbook(path: Path) -> list[Sheet]:
    with ZipFile(path) as archive:
        shared_strings = _read_shared_strings(archive)
        date_style_ids = _read_date_style_ids(archive)
        sheet_targets = _read_sheet_targets(archive)
        return [
            _read_sheet(archive, target, name, shared_strings, date_style_ids)
            for name, target in sheet_targets
        ]


def _read_shared_strings(archive: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    strings: list[str] = []
    for si in root.findall("a:si", NS):
        strings.append("".join(t.text or "" for t in si.findall(".//a:t", NS)))
    return strings


def _read_date_style_ids(archive: ZipFile) -> set[int]:
    root = ET.fromstring(archive.read("xl/styles.xml"))
    custom_formats: dict[int, str] = {}
    for num_fmt in root.findall("a:numFmts/a:numFmt", NS):
        custom_formats[int(num_fmt.attrib["numFmtId"])] = num_fmt.attrib["formatCode"]

    date_num_format_ids = {14, 15, 16, 17, 22}
    date_style_ids: set[int] = set()
    for index, xf in enumerate(root.findall("a:cellXfs/a:xf", NS)):
        num_fmt_id = int(xf.attrib.get("numFmtId", "0"))
        custom_format = custom_formats.get(num_fmt_id, "").lower()
        if num_fmt_id in date_num_format_ids or _looks_like_date_format(custom_format):
            date_style_ids.add(index)
    return date_style_ids


def _looks_like_date_format(format_code: str) -> bool:
    if not format_code:
        return False
    # Keep this conservative: accounting formats can contain symbols and decimals.
    if "0.00" in format_code or "#" in format_code or "€" in format_code:
        return False
    return any(token in format_code for token in ("yy", "dd", "mm/"))


def _read_sheet_targets(archive: ZipFile) -> list[tuple[str, str]]:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    rel_targets = {
        rel.attrib["Id"]: rel.attrib["Target"]
        for rel in rels.findall("rel:Relationship", NS)
    }

    sheets: list[tuple[str, str]] = []
    for sheet in workbook.findall("a:sheets/a:sheet", NS):
        rel_id = sheet.attrib[
            "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
        ]
        sheets.append((sheet.attrib["name"], "xl/" + rel_targets[rel_id]))
    return sheets


def _read_sheet(
    archive: ZipFile,
    target: str,
    name: str,
    shared_strings: list[str],
    date_style_ids: set[int],
) -> Sheet:
    root = ET.fromstring(archive.read(target))
    parsed_rows: list[tuple[int, dict[int, CellValue]]] = []
    for row in root.findall(".//a:sheetData/a:row", NS):
        row_number = int(row.attrib["r"])
        values: dict[int, CellValue] = {}
        for cell in row.findall("a:c", NS):
            column_number = _column_number(cell.attrib["r"])
            value = _parse_cell(cell, shared_strings, date_style_ids)
            if value.value is not None or value.formula is not None:
                values[column_number] = value
        if values:
            parsed_rows.append((row_number, values))

    if not parsed_rows:
        return Sheet(name=name, headers=[], rows=[], row_numbers=[])

    header_cells = parsed_rows[0][1]
    max_column = max(header_cells)
    headers = [
        header_cells[column].value or f"Column {column}"
        for column in range(1, max_column + 1)
    ]

    data_rows: list[dict[str, CellValue]] = []
    row_numbers: list[int] = []
    for row_number, cells in parsed_rows[1:]:
        row_data = {
            header: cells.get(index + 1, CellValue(None, None, "blank"))
            for index, header in enumerate(headers)
        }
        data_rows.append(row_data)
        row_numbers.append(row_number)

    return Sheet(name=name, headers=headers, rows=data_rows, row_numbers=row_numbers)


def _parse_cell(
    cell: ET.Element,
    shared_strings: list[str],
    date_style_ids: set[int],
) -> CellValue:
    cell_type = cell.attrib.get("t", "n")
    style_id = int(cell.attrib.get("s", "-1"))
    value_element = cell.find("a:v", NS)
    formula_element = cell.find("a:f", NS)
    raw_value = value_element.text if value_element is not None else None
    formula = formula_element.text if formula_element is not None else None

    if raw_value is None:
        return CellValue(None, None, cell_type, formula)

    if cell_type == "s":
        return CellValue(shared_strings[int(raw_value)], raw_value, cell_type, formula)

    if cell_type in {"str", "inlineStr"}:
        return CellValue(raw_value, raw_value, cell_type, formula)

    if style_id in date_style_ids:
        return CellValue(_excel_date_to_iso(raw_value), raw_value, "date", formula)

    return CellValue(_normalize_number_text(raw_value), raw_value, cell_type, formula)


def _normalize_number_text(raw_value: str) -> str:
    try:
        decimal = Decimal(raw_value)
    except Exception:
        return raw_value
    if decimal == decimal.to_integral_value():
        return str(decimal.quantize(Decimal("1")))
    return format(decimal.normalize(), "f")


def _excel_date_to_iso(raw_value: str) -> str:
    date = datetime(1899, 12, 30) + timedelta(days=float(raw_value))
    return date.date().isoformat()


def _column_number(cell_ref: str) -> int:
    letters = re.match(r"([A-Z]+)", cell_ref)
    if letters is None:
        raise ValueError(f"Invalid cell reference: {cell_ref}")
    number = 0
    for letter in letters.group(1):
        number = number * 26 + ord(letter) - 64
    return number

