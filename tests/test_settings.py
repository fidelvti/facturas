from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from facturas.db import connect, create_schema, get_current_year, set_current_year


class SettingsTests(unittest.TestCase):
    def test_settings_table_is_created_with_default_current_year(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "facturas.sqlite3"
            with connect(db_path) as connection:
                create_schema(connection)

                row = connection.execute(
                    "SELECT value FROM settings WHERE key = 'current_year'"
                ).fetchone()

            self.assertEqual(row, ("2026",))

    def test_get_current_year_returns_int_and_initializes_missing_setting(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "facturas.sqlite3"
            with connect(db_path) as connection:
                create_schema(connection)
                connection.execute("DELETE FROM settings WHERE key = 'current_year'")

                current_year = get_current_year(connection)

            self.assertEqual(current_year, 2026)
            self.assertIsInstance(current_year, int)

    def test_set_current_year_persists_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "facturas.sqlite3"
            with connect(db_path) as connection:
                create_schema(connection)
                set_current_year(connection, 2027)

            with connect(db_path) as connection:
                self.assertEqual(get_current_year(connection), 2027)


if __name__ == "__main__":
    unittest.main()
