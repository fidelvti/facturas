from __future__ import annotations

from pathlib import Path
import sqlite3

from .db import connect


TECHNICAL_COLUMNS = {
    "id",
    "invoice_id",
    "source_document_id",
    "migration_batch_id",
    "source_worksheet",
    "source_row_number",
    "ingestion_origin",
    "validation_status",
    "validation_notes",
    "extraction_status",
    "file_sha256",
    "created_at",
    "imported_at",
    "discovered_at",
}


def format_period(period_yyyymm: str | None) -> str:
    if period_yyyymm is None or len(period_yyyymm) != 6:
        return period_yyyymm or ""
    return f"{period_yyyymm[4:6]}/{period_yyyymm[:4]}"


def period_start_date_from_display(period: str | None) -> str:
    if period is None or len(period) != 7 or period[2] != "/":
        return period or ""
    return f"{period[3:7]}-{period[:2]}-01"


def get_agua_data(database_path: Path) -> list[dict[str, object]]:
    with connect(database_path) as connection:
        return _fetch_all(
            connection,
            """
            SELECT i.period_yyyymm, d.importe_total, d.lectura, d.consumo_m3
            FROM water_invoice_detail d
            JOIN invoice i ON i.id = d.invoice_id
            WHERE i.provider = 'agua'
            ORDER BY i.period_yyyymm DESC
            """,
            {
                "period_yyyymm": "Periodo",
                "importe_total": "Importe total",
                "lectura": "Lectura",
                "consumo_m3": "Consumo (m3)",
            },
        )


def get_gas_data(database_path: Path) -> dict[str, list[dict[str, object]]]:
    with connect(database_path) as connection:
        return {
            "potencia": _fetch_all(
                connection,
                """
                SELECT i.period_yyyymm, p.dias, p.plazo_fijo, p.total
                FROM gas_power_line p
                JOIN invoice i ON i.id = p.invoice_id
                WHERE i.provider = 'gas'
                ORDER BY i.period_yyyymm DESC, p.line_sequence
                """,
                {
                    "period_yyyymm": "Periodo",
                    "dias": "Dias",
                    "plazo_fijo": "Plazo fijo",
                    "total": "Total",
                },
            ),
            "consumo": _fetch_all(
                connection,
                """
                SELECT i.period_yyyymm, c.consumo, c.importe, c.total
                FROM gas_consumption_line c
                JOIN invoice i ON i.id = c.invoice_id
                WHERE i.provider = 'gas'
                ORDER BY i.period_yyyymm DESC, c.line_sequence
                """,
                {
                    "period_yyyymm": "Periodo",
                    "consumo": "Consumo",
                    "importe": "Importe unitario",
                    "total": "Total",
                },
            ),
            "otros": _fetch_all(
                connection,
                """
                SELECT i.period_yyyymm, o.imp_hc, o.alquiler, o.canon,
                       o.iva_rate, o.peajes, o.cargos
                FROM gas_other_charge_line o
                JOIN invoice i ON i.id = o.invoice_id
                WHERE i.provider = 'gas'
                ORDER BY i.period_yyyymm DESC, o.line_sequence
                """,
                {
                    "period_yyyymm": "Periodo",
                    "imp_hc": "Impuesto hidrocarburos",
                    "alquiler": "Alquiler",
                    "canon": "Canon",
                    "iva_rate": "IVA (%)",
                    "peajes": "Peajes",
                    "cargos": "Cargos",
                },
                percent_columns={"IVA (%)"},
            ),
        }


def get_luz_data(database_path: Path) -> dict[str, list[dict[str, object]]]:
    with connect(database_path) as connection:
        return {
            "potencia": _fetch_all(
                connection,
                """
                SELECT i.period_yyyymm, p.potencia, p.precio, p.dias, p.total
                FROM electricity_power_line p
                JOIN invoice i ON i.id = p.invoice_id
                WHERE i.provider = 'luz'
                ORDER BY i.period_yyyymm DESC, p.line_sequence
                """,
                {
                    "period_yyyymm": "Periodo",
                    "potencia": "Potencia",
                    "precio": "Precio unitario",
                    "dias": "Dias",
                    "total": "Total",
                },
            ),
            "consumo": _fetch_all(
                connection,
                """
                SELECT i.period_yyyymm, c.consumo, c.precio, c.total
                FROM electricity_consumption_line c
                JOIN invoice i ON i.id = c.invoice_id
                WHERE i.provider = 'luz'
                ORDER BY i.period_yyyymm DESC, c.line_sequence
                """,
                {
                    "period_yyyymm": "Periodo",
                    "consumo": "Consumo",
                    "precio": "Precio unitario",
                    "total": "Total",
                },
            ),
            "otros": _fetch_all(
                connection,
                """
                SELECT i.period_yyyymm, o.otros, o.alquiler, o.imp_elec_rate,
                       o.iva_rate, o.peaje_a, o.peaje_b, o.cargo_a, o.cargo_b
                FROM electricity_other_charge_line o
                JOIN invoice i ON i.id = o.invoice_id
                WHERE i.provider = 'luz'
                ORDER BY i.period_yyyymm DESC, o.line_sequence
                """,
                {
                    "period_yyyymm": "Periodo",
                    "otros": "Otros",
                    "alquiler": "Alquiler",
                    "imp_elec_rate": "Impuesto electricidad (%)",
                    "iva_rate": "IVA (%)",
                    "peaje_a": "Peaje potencia",
                    "peaje_b": "Peaje energia",
                    "cargo_a": "Cargo potencia",
                    "cargo_b": "Cargo energia",
                },
                percent_columns={"Impuesto electricidad (%)", "IVA (%)"},
            ),
        }


def get_payroll_data(database_path: Path) -> list[dict[str, object]]:
    with connect(database_path) as connection:
        return _fetch_all(
            connection,
            """
            SELECT period_yyyymm, guardias, gastos, dietas, bonus, total, irpf_percent
            FROM payroll_report
            WHERE employer = 'GFT'
            ORDER BY period_yyyymm DESC
            """,
            {
                "period_yyyymm": "Periodo",
                "guardias": "Guardias",
                "gastos": "Gastos",
                "dietas": "Dietas",
                "bonus": "Bonus",
                "total": "Total",
                "irpf_percent": "IRPF (%)",
            },
        )


def get_pagatelia_data(database_path: Path) -> list[dict[str, object]]:
    with connect(database_path) as connection:
        return _fetch_all(
            connection,
            """
            SELECT period_yyyymm, importe, total_count, factura
            FROM toll_transaction
            WHERE provider = 'pagatelia'
            ORDER BY period_yyyymm DESC, CAST(importe AS REAL)
            """,
            {
                "period_yyyymm": "Periodo",
                "importe": "Importe",
                "total_count": "Total",
                "factura": "Factura",
            },
        )


def _fetch_all(
    connection: sqlite3.Connection,
    sql: str,
    labels: dict[str, str],
    *,
    percent_columns: set[str] | None = None,
) -> list[dict[str, object]]:
    connection.row_factory = sqlite3.Row
    rows = connection.execute(sql).fetchall()
    result: list[dict[str, object]] = []
    percent_columns = percent_columns or set()
    for row in rows:
        item: dict[str, object] = {}
        for source, label in labels.items():
            value = row[source]
            if source == "period_yyyymm":
                item[label] = format_period(value)
            elif label in percent_columns and value not in (None, ""):
                item[label] = _to_number(value) * 100
            else:
                item[label] = _to_number(value)
        result.append(item)
    return result


def _to_number(value: object) -> object:
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    try:
        return float(value)
    except ValueError:
        return value
