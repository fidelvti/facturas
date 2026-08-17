from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import pandas as pd

from facturas.dashboard_data import (
    TECHNICAL_COLUMNS,
    format_period,
    get_agua_data,
    get_gas_data,
    get_luz_data,
    get_pagatelia_data,
    get_payroll_data,
    period_start_date_from_display,
)
from facturas.db import connect, create_schema
from app import _chart_dataframe


class DashboardDataTests(unittest.TestCase):
    def test_format_period(self) -> None:
        self.assertEqual(format_period("202608"), "08/2026")
        self.assertEqual(format_period(None), "")
        self.assertEqual(format_period("bad"), "bad")

    def test_period_conversion_handles_year_boundaries(self) -> None:
        self.assertLess(
            period_start_date_from_display("12/2025"),
            period_start_date_from_display("01/2026"),
        )

    def test_agua_query_returns_business_columns(self) -> None:
        with _dashboard_database() as db_path:
            rows = get_agua_data(db_path)

        self.assertEqual(rows[0], {
            "Periodo": "08/2026",
            "Importe total": 47.73,
            "Lectura": 352.0,
            "Consumo (m3)": 4.0,
        })
        self.assertEqual([row["Periodo"] for row in rows], ["08/2026", "01/2026"])
        self.assertFalse(_exposes_technical_columns(rows[0]))

    def test_gas_query_returns_three_business_datasets(self) -> None:
        with _dashboard_database() as db_path:
            data = get_gas_data(db_path)

        self.assertEqual(set(data), {"potencia", "consumo", "otros"})
        self.assertEqual(len(data["potencia"]), 2)
        self.assertEqual(len(data["consumo"]), 3)
        self.assertEqual(data["potencia"][0]["Plazo fijo"], 0.26663)
        self.assertEqual(data["consumo"][1]["Importe unitario"], 0.041199)
        self.assertEqual([row["Periodo"] for row in data["consumo"]], ["08/2026", "08/2026", "12/2025"])
        for rows in data.values():
            for row in rows:
                self.assertFalse(_exposes_technical_columns(row))

    def test_luz_query_returns_three_business_datasets(self) -> None:
        with _dashboard_database() as db_path:
            data = get_luz_data(db_path)

        self.assertEqual(set(data), {"potencia", "consumo", "otros"})
        self.assertEqual(len(data["potencia"]), 3)
        self.assertEqual(len(data["consumo"]), 3)
        self.assertEqual(data["potencia"][0]["Precio unitario"], 0.056532)
        self.assertEqual(data["consumo"][1]["Precio unitario"], 0.108398)
        self.assertEqual([row["Periodo"] for row in data["potencia"]], ["08/2026", "08/2026", "12/2025"])
        for rows in data.values():
            for row in rows:
                self.assertFalse(_exposes_technical_columns(row))

    def test_payroll_query_preserves_optional_nulls(self) -> None:
        with _dashboard_database() as db_path:
            rows = get_payroll_data(db_path)

        self.assertEqual(rows[0], {
            "Periodo": "08/2026",
            "Guardias": None,
            "Gastos": None,
            "Dietas": None,
            "Bonus": None,
            "Total": 175.17,
            "IRPF (%)": 20.66,
        })
        self.assertEqual([row["Periodo"] for row in rows], ["08/2026", "12/2025"])
        self.assertFalse(_exposes_technical_columns(rows[0]))

    def test_pagatelia_query_returns_business_columns(self) -> None:
        with _dashboard_database() as db_path:
            rows = get_pagatelia_data(db_path)

        self.assertEqual(rows[0], {
            "Periodo": "08/2026",
            "Importe": 4.89,
            "Total": 3.0,
            "Factura": 14.67,
        })
        self.assertEqual([row["Periodo"] for row in rows], ["08/2026", "12/2025"])
        self.assertFalse(_exposes_technical_columns(rows[0]))

    def test_chart_periods_sort_ascending_and_preserve_duplicate_observations(self) -> None:
        with _dashboard_database() as db_path:
            gas = get_gas_data(db_path)["consumo"]
            luz = get_luz_data(db_path)["potencia"]

        gas_chart = _chart_dataframe(pd.DataFrame(gas))
        luz_chart = _chart_dataframe(pd.DataFrame(luz))
        gas_chart_periods = [
            value.strftime("%Y-%m-%d") for value in gas_chart["Periodo fecha"]
        ]
        luz_chart_periods = [
            value.strftime("%Y-%m-%d") for value in luz_chart["Periodo fecha"]
        ]

        self.assertEqual(gas_chart_periods, ["2025-12-01", "2026-08-01", "2026-08-01"])
        self.assertEqual(luz_chart_periods, ["2025-12-01", "2026-08-01", "2026-08-01"])
        self.assertEqual(len(gas_chart), 3)
        self.assertEqual(len(luz_chart), 3)


class _dashboard_database:
    def __enter__(self) -> Path:
        self._tmp = tempfile.TemporaryDirectory()
        db_path = Path(self._tmp.name) / "facturas.sqlite3"
        with connect(db_path) as connection:
            create_schema(connection)
            _insert_rows(connection)
        self.path = db_path
        return db_path

    def __exit__(self, *_args) -> None:
        self._tmp.cleanup()


def _insert_rows(connection) -> None:
    connection.executescript(
        """
        INSERT INTO invoice (
            id, provider, invoice_kind, period_yyyymm, original_period_value,
            invoice_total, amount_payable, ingestion_origin, created_at
        )
        VALUES
            (1, 'agua', 'water', '202608', '202608', '47.73', '47.73', 'automated', '2026-08-17T12:00:00+02:00'),
            (2, 'gas', 'gas', '202608', '202608', '34.76', '34.76', 'automated', '2026-08-17T12:00:00+02:00'),
            (3, 'luz', 'electricity', '202608', '202608', '69.37', '64.37', 'automated', '2026-08-17T12:00:00+02:00'),
            (4, 'agua', 'water', '202601', '202601', '40.00', '40.00', 'automated', '2026-01-17T12:00:00+02:00'),
            (5, 'gas', 'gas', '202512', '202512', '30.00', '30.00', 'automated', '2025-12-17T12:00:00+02:00'),
            (6, 'luz', 'electricity', '202512', '202512', '60.00', '60.00', 'automated', '2025-12-17T12:00:00+02:00');

        INSERT INTO water_invoice_detail (invoice_id, importe_total, lectura, consumo_m3)
        VALUES
            (1, '47.73', '352', '4'),
            (4, '40.00', '300', '3');

        INSERT INTO gas_power_line (
            invoice_id, line_sequence, source_worksheet, source_row_number,
            dias, plazo_fijo, total
        )
        VALUES
            (2, 1, 'test', 1, '60', '0.26663', '15.9978'),
            (5, 1, 'test2', 1, '60', '0.20000', '12.00');

        INSERT INTO gas_consumption_line (
            invoice_id, line_sequence, source_worksheet, source_row_number,
            consumo, importe, total
        )
        VALUES
            (2, 1, 'test', 1, '21', '0.03613', '0.75873'),
            (2, 2, 'test', 2, '13', '0.041199', '0.535587'),
            (5, 1, 'test2', 2, '10', '0.03000', '0.30000');

        INSERT INTO gas_other_charge_line (
            invoice_id, line_sequence, source_worksheet, source_row_number,
            imp_hc, alquiler, canon, iva_rate, peajes, cargos
        )
        VALUES
            (2, 1, 'test', 1, '0.05', '1.14', '10.24', '0.21', '11.82', '0.09'),
            (5, 1, 'test2', 1, '0.04', '1.00', '9.00', '0.21', '10.00', '0.08');

        INSERT INTO electricity_power_line (
            invoice_id, line_sequence, source_worksheet, source_row_number,
            potencia, precio, dias, total
        )
        VALUES
            (3, 1, 'test', 1, '4.6', '0.056532', '60', '15.602928'),
            (3, 2, 'test', 2, '4.6', '0.019254', '60', '5.314104'),
            (6, 1, 'test2', 1, '4.6', '0.050000', '60', '13.80000');

        INSERT INTO electricity_consumption_line (
            invoice_id, line_sequence, source_worksheet, source_row_number,
            consumo, precio, total
        )
        VALUES
            (3, 1, 'test', 1, '201', '0.108790', '21.86679'),
            (3, 2, 'test', 2, '95.738', '0.108398', '10.377924902'),
            (6, 1, 'test2', 1, '100', '0.100000', '10.00000');

        INSERT INTO electricity_other_charge_line (
            invoice_id, line_sequence, source_worksheet, source_row_number,
            otros, alquiler, imp_elec_rate, iva_rate,
            peaje_a, peaje_b, cargo_a, cargo_b
        )
        VALUES
            (3, 1, 'test', 1, '0.74', '0.71', '0.051126963', '0.21', '27.35', '8.60', '7.10', '5.35'),
            (6, 1, 'test2', 1, '0.70', '0.70', '0.051126963', '0.21', '20.00', '8.00', '7.00', '5.00');

        INSERT INTO payroll_report (
            employer, period_yyyymm, original_period_value,
            guardias, gastos, dietas, bonus, total, irpf_percent,
            ingestion_origin, created_at
        )
        VALUES
            ('GFT', '202608', '202608', NULL, NULL, NULL, NULL, '175.17', '20.66', 'automated', '2026-08-17T12:00:00+02:00'),
            ('GFT', '202512', '202512', NULL, NULL, NULL, NULL, '2800.00', '22.00', 'automated', '2025-12-17T12:00:00+02:00');

        INSERT INTO toll_transaction (
            provider, period_yyyymm, original_period_value,
            importe, total_count, factura, ingestion_origin,
            source_worksheet, source_row_number, created_at
        )
        VALUES
            ('pagatelia', '202608', '202608', '4.89', '3', '14.67', 'automated', 'test', 1, '2026-08-17T12:00:00+02:00'),
            ('pagatelia', '202512', '202512', '2.12', '1', '2.12', 'automated', 'test2', 1, '2025-12-17T12:00:00+02:00');
        """
    )


def _exposes_technical_columns(row: dict[str, object]) -> bool:
    normalized = {key.lower().replace(" ", "_") for key in row}
    return bool(normalized & TECHNICAL_COLUMNS)


if __name__ == "__main__":
    unittest.main()
