from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
import unittest

from facturas.db import create_schema, table_counts, connect
from facturas.local import local_username
from facturas.migrate import migrate_workbook
from facturas.xlsx_reader import read_workbook


WORKBOOK = Path("data/_Facturas.xlsx")


class WorkbookMigrationTests(unittest.TestCase):
    def test_reader_finds_expected_sheets_and_row_counts(self) -> None:
        sheets = {sheet.name: sheet for sheet in read_workbook(WORKBOOK)}

        self.assertEqual(len(sheets), 9)
        self.assertEqual(len(sheets["Agua"].rows), 27)
        self.assertEqual(len(sheets["Gas - Potencia"].rows), 52)
        self.assertEqual(len(sheets["Gas - Consumo - Tabla 2"].rows), 66)
        self.assertEqual(len(sheets["Gas - Otros - Tabla 3"].rows), 43)
        self.assertEqual(len(sheets["Luz - Potencia"].rows), 126)
        self.assertEqual(len(sheets["Luz - Consumo - Tabla 2"].rows), 132)
        self.assertEqual(len(sheets["Luz - Otros - Tabla 3"].rows), 52)
        self.assertEqual(len(sheets["Pagatelia"].rows), 191)
        self.assertEqual(len(sheets["Nóminas - GFT report"].rows), 151)

    def test_schema_constraints_include_ingestion_origin_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.sqlite3"
            with connect(db_path) as connection:
                create_schema(connection)
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(
                        """
                        INSERT INTO invoice (
                            provider,
                            invoice_kind,
                            ingestion_origin,
                            created_at
                        )
                        VALUES ('agua', 'water', 'bad_origin', '2026-01-01T00:00:00+01:00')
                        """
                    )

    def test_local_username_default_is_available_for_future_audit(self) -> None:
        self.assertTrue(local_username())

    def test_migration_imports_once_and_second_run_skips(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "facturas.sqlite3"
            first = migrate_workbook(WORKBOOK, db_path)
            second = migrate_workbook(WORKBOOK, db_path)

            self.assertEqual(first.status, "imported")
            self.assertEqual(second.status, "skipped_existing_workbook")
            self.assertEqual(first.migration_batch_id, second.migration_batch_id)
            self.assertEqual(first.go_live_at, second.go_live_at)
            self.assertEqual(second.skipped_rows[0]["scope"], "workbook")

            with connect(db_path) as connection:
                counts = table_counts(connection)

            self.assertEqual(counts["migration_batch"], 1)
            self.assertEqual(counts["invoice"], 118)
            self.assertEqual(counts["invoice_adjustment"], 0)
            self.assertEqual(counts["water_invoice_detail"], 27)
            self.assertEqual(counts["gas_power_line"], 52)
            self.assertEqual(counts["gas_consumption_line"], 66)
            self.assertEqual(counts["gas_other_charge_line"], 43)
            self.assertEqual(counts["electricity_power_line"], 126)
            self.assertEqual(counts["electricity_consumption_line"], 132)
            self.assertEqual(counts["electricity_other_charge_line"], 52)
            self.assertEqual(counts["toll_transaction"], 191)
            self.assertEqual(counts["payroll_report"], 151)
            self.assertEqual(counts["manual_correction_audit"], 0)


if __name__ == "__main__":
    unittest.main()
