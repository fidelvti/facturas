from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Iterable

from .db import create_schema, table_counts, connect
from .local import local_username
from .xlsx_reader import CellValue, Sheet, read_workbook


INGESTION_ORIGIN = "historical_workbook"
DEFAULT_DATABASE_PATH = Path("data/facturas.sqlite3")
DEFAULT_WORKBOOK_PATH = Path("data/_Facturas.xlsx")


@dataclass
class MigrationReport:
    status: str
    database_path: str
    migration_batch_id: int | None
    go_live_at: str | None
    workbook_sha256: str
    worksheet_rows: dict[str, int] = field(default_factory=dict)
    target_table_rows: dict[str, int] = field(default_factory=dict)
    skipped_rows: list[dict[str, str]] = field(default_factory=list)


def migrate_workbook(workbook_path: Path, database_path: Path) -> MigrationReport:
    workbook_path = workbook_path.resolve()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    workbook_sha256 = _sha256(workbook_path)
    sheets = read_workbook(workbook_path)
    worksheet_rows = {sheet.name: len(sheet.rows) for sheet in sheets}

    with connect(database_path) as connection:
        create_schema(connection)
        existing = connection.execute(
            "SELECT id, go_live_at FROM migration_batch WHERE workbook_sha256 = ?",
            (workbook_sha256,),
        ).fetchone()
        if existing is not None:
            return MigrationReport(
                status="skipped_existing_workbook",
                database_path=str(database_path),
                migration_batch_id=existing[0],
                go_live_at=existing[1],
                workbook_sha256=workbook_sha256,
                worksheet_rows=worksheet_rows,
                target_table_rows=table_counts(connection),
                skipped_rows=[
                    {
                        "scope": "workbook",
                        "reason": "workbook_sha256 already exists in migration_batch",
                    }
                ],
            )

        go_live_at = _local_timestamp()
        with connection:
            cursor = connection.execute(
                """
                INSERT INTO migration_batch (
                    source_workbook_path,
                    workbook_sha256,
                    imported_at,
                    go_live_at,
                    notes
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(workbook_path),
                    workbook_sha256,
                    go_live_at,
                    go_live_at,
                    f"Initial historical migration executed by {local_username()}",
                ),
            )
            migration_batch_id = int(cursor.lastrowid)
            _insert_sheets(connection, sheets, migration_batch_id, go_live_at)

        return MigrationReport(
            status="imported",
            database_path=str(database_path),
            migration_batch_id=migration_batch_id,
            go_live_at=go_live_at,
            workbook_sha256=workbook_sha256,
            worksheet_rows=worksheet_rows,
            target_table_rows=table_counts(connection),
            skipped_rows=[],
        )


def _insert_sheets(
    connection: sqlite3.Connection,
    sheets: list[Sheet],
    migration_batch_id: int,
    created_at: str,
) -> None:
    by_name = {sheet.name: sheet for sheet in sheets}

    _insert_water(connection, _required_sheet(by_name, "Agua"), migration_batch_id, created_at)
    _insert_gas(connection, by_name, migration_batch_id, created_at)
    _insert_electricity(connection, by_name, migration_batch_id, created_at)
    _insert_tolls(connection, _required_sheet(by_name, "Pagatelia"), migration_batch_id, created_at)
    _insert_payroll(
        connection,
        _required_sheet(by_name, "Nóminas - GFT report"),
        migration_batch_id,
        created_at,
    )


def _insert_water(
    connection: sqlite3.Connection,
    sheet: Sheet,
    migration_batch_id: int,
    created_at: str,
) -> None:
    _assert_headers(sheet, ["Periodo", "Importe total", "Lectura", "Consumo m3"])
    for row, row_number in zip(sheet.rows, sheet.row_numbers):
        period = _required(row, "Periodo")
        total = _required(row, "Importe total")
        invoice_id = _insert_invoice(
            connection,
            provider="agua",
            invoice_kind="water",
            period_yyyymm=_period_yyyymm(period.value),
            original_period_value=period.value,
            invoice_total=total.value,
            migration_batch_id=migration_batch_id,
            created_at=created_at,
            source_worksheet=sheet.name,
            source_row_number=row_number,
        )
        connection.execute(
            """
            INSERT INTO water_invoice_detail (
                invoice_id, importe_total, lectura, consumo_m3
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                invoice_id,
                total.value,
                _required(row, "Lectura").value,
                _required(row, "Consumo m3").value,
            ),
        )


def _insert_gas(
    connection: sqlite3.Connection,
    sheets: dict[str, Sheet],
    migration_batch_id: int,
    created_at: str,
) -> None:
    gas_sheets = [
        _required_sheet(sheets, "Gas - Potencia"),
        _required_sheet(sheets, "Gas - Consumo - Tabla 2"),
        _required_sheet(sheets, "Gas - Otros - Tabla 3"),
    ]
    for sheet in gas_sheets:
        _assert_has_header(sheet, "Periodo")
    invoices = _invoice_headers_by_period(
        connection, "gas", "gas", gas_sheets, migration_batch_id, created_at
    )

    _insert_line_rows(
        connection,
        sheet=gas_sheets[0],
        invoices=invoices,
        table="gas_power_line",
        columns=["dias", "plazo_fijo", "total", "formula_text"],
        source_columns=["Días", "Plazo fijo", "Total", "Total"],
        formula_source="Total",
    )
    _insert_line_rows(
        connection,
        sheet=gas_sheets[1],
        invoices=invoices,
        table="gas_consumption_line",
        columns=["consumo", "importe", "total", "formula_text"],
        source_columns=["Consumo", "Importe", "Total", "Total"],
        formula_source="Total",
    )
    _insert_line_rows(
        connection,
        sheet=gas_sheets[2],
        invoices=invoices,
        table="gas_other_charge_line",
        columns=["imp_hc", "alquiler", "canon", "iva_rate", "peajes", "cargos"],
        source_columns=["Imp HC", "Alquiler", "Canon", "IVA", "Peajes", "Cargos"],
    )


def _insert_electricity(
    connection: sqlite3.Connection,
    sheets: dict[str, Sheet],
    migration_batch_id: int,
    created_at: str,
) -> None:
    electricity_sheets = [
        _required_sheet(sheets, "Luz - Potencia"),
        _required_sheet(sheets, "Luz - Consumo - Tabla 2"),
        _required_sheet(sheets, "Luz - Otros - Tabla 3"),
    ]
    for sheet in electricity_sheets:
        _assert_has_header(sheet, "Periodo")
    invoices = _invoice_headers_by_period(
        connection, "luz", "electricity", electricity_sheets, migration_batch_id, created_at
    )

    _insert_line_rows(
        connection,
        sheet=electricity_sheets[0],
        invoices=invoices,
        table="electricity_power_line",
        columns=["potencia", "precio", "dias", "total", "formula_text"],
        source_columns=["Potencia", "Precio", "Días", "Total", "Total"],
        formula_source="Total",
    )
    _insert_line_rows(
        connection,
        sheet=electricity_sheets[1],
        invoices=invoices,
        table="electricity_consumption_line",
        columns=["consumo", "precio", "total", "formula_text"],
        source_columns=["Consumo", "Precio", "Total", "Total"],
        formula_source="Total",
    )

    other_sheet = electricity_sheets[2]
    _assert_headers(
        other_sheet,
        [
            "Periodo",
            "Otros",
            "Alquiler",
            "Imp.Elec.",
            "IVA",
            "Peaje A",
            "Peaje B",
            "Cargo A",
            "Cargo B",
        ],
    )
    for sequence, (row, row_number) in enumerate(
        zip(other_sheet.rows, other_sheet.row_numbers), start=1
    ):
        period = _required(row, "Periodo")
        peaje_a = _required(row, "Peaje A")
        connection.execute(
            """
            INSERT INTO electricity_other_charge_line (
                invoice_id,
                line_sequence,
                source_worksheet,
                source_row_number,
                otros,
                alquiler,
                imp_elec_rate,
                iva_rate,
                peaje_a,
                peaje_b,
                cargo_a,
                cargo_b,
                original_peaje_a_value,
                original_peaje_a_cell_type
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                invoices[_period_yyyymm(period.value)],
                sequence,
                other_sheet.name,
                row_number,
                _required(row, "Otros").value,
                _required(row, "Alquiler").value,
                _required(row, "Imp.Elec.").value,
                _required(row, "IVA").value,
                peaje_a.value,
                _required(row, "Peaje B").value,
                _required(row, "Cargo A").value,
                _required(row, "Cargo B").value,
                peaje_a.value if peaje_a.cell_type == "s" else None,
                peaje_a.cell_type if peaje_a.cell_type == "s" else None,
            ),
        )


def _insert_tolls(
    connection: sqlite3.Connection,
    sheet: Sheet,
    migration_batch_id: int,
    created_at: str,
) -> None:
    _assert_headers(sheet, ["Periodo", "Importe", "Total", "Factura"])
    for row, row_number in zip(sheet.rows, sheet.row_numbers):
        period = _required(row, "Periodo")
        connection.execute(
            """
            INSERT INTO toll_transaction (
                provider,
                period_yyyymm,
                original_period_value,
                importe,
                total_count,
                factura,
                ingestion_origin,
                migration_batch_id,
                source_worksheet,
                source_row_number,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "pagatelia",
                _period_yyyymm(period.value),
                period.value,
                _required(row, "Importe").value,
                _required(row, "Total").value,
                _required(row, "Factura").value,
                INGESTION_ORIGIN,
                migration_batch_id,
                sheet.name,
                row_number,
                created_at,
            ),
        )


def _insert_payroll(
    connection: sqlite3.Connection,
    sheet: Sheet,
    migration_batch_id: int,
    created_at: str,
) -> None:
    _assert_headers(sheet, ["Periodo", "Guardias", "Gastos", "Dietas", "Bonus", "Total", "% IRPF"])
    for row, row_number in zip(sheet.rows, sheet.row_numbers):
        period = _required(row, "Periodo")
        connection.execute(
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
                migration_batch_id,
                source_worksheet,
                source_row_number,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "GFT",
                _period_yyyymm(period.value),
                period.value,
                row["Guardias"].value,
                row["Gastos"].value,
                row["Dietas"].value,
                row["Bonus"].value,
                _required(row, "Total").value,
                _required(row, "% IRPF").value,
                INGESTION_ORIGIN,
                migration_batch_id,
                sheet.name,
                row_number,
                created_at,
            ),
        )


def _invoice_headers_by_period(
    connection: sqlite3.Connection,
    provider: str,
    invoice_kind: str,
    sheets: Iterable[Sheet],
    migration_batch_id: int,
    created_at: str,
) -> dict[str, int]:
    period_originals: dict[str, str] = {}
    for sheet in sheets:
        for row in sheet.rows:
            period = _required(row, "Periodo").value
            period_originals.setdefault(_period_yyyymm(period), period)

    return {
        period: _insert_invoice(
            connection,
            provider=provider,
            invoice_kind=invoice_kind,
            period_yyyymm=period,
            original_period_value=original,
            invoice_total=None,
            migration_batch_id=migration_batch_id,
            created_at=created_at,
            source_worksheet=None,
            source_row_number=None,
        )
        for period, original in sorted(period_originals.items())
    }


def _insert_invoice(
    connection: sqlite3.Connection,
    *,
    provider: str,
    invoice_kind: str,
    period_yyyymm: str,
    original_period_value: str | None,
    invoice_total: str | None,
    migration_batch_id: int,
    created_at: str,
    source_worksheet: str | None,
    source_row_number: int | None,
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO invoice (
            provider,
            invoice_kind,
            period_yyyymm,
            original_period_value,
            invoice_total,
            ingestion_origin,
            migration_batch_id,
            source_worksheet,
            source_row_number,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            provider,
            invoice_kind,
            period_yyyymm,
            original_period_value,
            invoice_total,
            INGESTION_ORIGIN,
            migration_batch_id,
            source_worksheet,
            source_row_number,
            created_at,
        ),
    )
    return int(cursor.lastrowid)


def _insert_line_rows(
    connection: sqlite3.Connection,
    *,
    sheet: Sheet,
    invoices: dict[str, int],
    table: str,
    columns: list[str],
    source_columns: list[str],
    formula_source: str | None = None,
) -> None:
    _assert_headers(sheet, ["Periodo", *[c for c in source_columns if c != formula_source]])
    db_columns = ["invoice_id", "line_sequence", "source_worksheet", "source_row_number", *columns]
    placeholders = ", ".join("?" for _ in db_columns)
    sql = f"INSERT INTO {table} ({', '.join(db_columns)}) VALUES ({placeholders})"
    for sequence, (row, row_number) in enumerate(zip(sheet.rows, sheet.row_numbers), start=1):
        period = _required(row, "Periodo")
        values: list[str | int | None] = [
            invoices[_period_yyyymm(period.value)],
            sequence,
            sheet.name,
            row_number,
        ]
        for source_column, db_column in zip(source_columns, columns):
            cell = _required(row, source_column)
            values.append(cell.formula if db_column == "formula_text" else cell.value)
        connection.execute(sql, values)


def _required_sheet(sheets: dict[str, Sheet], name: str) -> Sheet:
    try:
        return sheets[name]
    except KeyError as exc:
        raise ValueError(f"Workbook is missing required worksheet: {name}") from exc


def _assert_headers(sheet: Sheet, headers: list[str]) -> None:
    missing = [header for header in headers if header not in sheet.headers]
    if missing:
        raise ValueError(f"Worksheet {sheet.name!r} is missing columns: {missing}")


def _assert_has_header(sheet: Sheet, header: str) -> None:
    _assert_headers(sheet, [header])


def _required(row: dict[str, CellValue], column: str) -> CellValue:
    cell = row[column]
    if cell.value is None:
        raise ValueError(f"Required value is blank in column {column!r}")
    return cell


def _period_yyyymm(value: str | None) -> str:
    if value is None:
        raise ValueError("Period value cannot be blank")
    if len(value) == 6 and value.isdigit():
        return value
    if len(value) >= 7 and value[4] == "-" and value[:4].isdigit():
        return value[:4] + value[5:7]
    raise ValueError(f"Unsupported period format: {value!r}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _local_timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate historical _Facturas.xlsx data.")
    parser.add_argument("--workbook", type=Path, default=DEFAULT_WORKBOOK_PATH)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE_PATH)
    args = parser.parse_args()

    report = migrate_workbook(args.workbook, args.database)
    print(json.dumps(report.__dict__, indent=2, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
