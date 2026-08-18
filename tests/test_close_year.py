from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from facturas.close_year import close_year
from facturas.db import connect, create_schema, get_current_year


class CloseYearTests(unittest.TestCase):
    def test_dry_run_does_not_move_files_or_advance_current_year(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            print_root, db_path = _make_print_tree(Path(tmpdir))
            source = _write(print_root / "inbox" / "luz" / "luz08.pdf")

            report = close_year(print_root, db_path)

            self.assertEqual(report.status, "dry_run")
            self.assertTrue(source.exists())
            self.assertFalse((print_root / "archivo" / "2026" / "luz" / "luz08.pdf").exists())
            self.assertEqual(_current_year(db_path), 2026)

    def test_apply_moves_files_keeps_provider_folders_and_advances_year(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            print_root, db_path = _make_print_tree(Path(tmpdir))
            source = _write(print_root / "inbox" / "gas" / "gas12.pdf")

            report = close_year(print_root, db_path, apply=True)

            destination = print_root / "archivo" / "2026" / "gas" / "gas12.pdf"
            self.assertEqual(report.status, "applied")
            self.assertFalse(source.exists())
            self.assertTrue(destination.exists())
            for provider in ["agua", "gas", "luz", "gft", "pagatelia", "phone"]:
                self.assertTrue((print_root / "inbox" / provider).is_dir())
            self.assertEqual(_current_year(db_path), 2027)

    def test_destination_collision_aborts_without_advancing_year(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            print_root, db_path = _make_print_tree(Path(tmpdir))
            source = _write(print_root / "inbox" / "agua" / "agua01.pdf")
            _write(print_root / "archivo" / "2026" / "agua" / "agua01.pdf")

            with self.assertRaisesRegex(ValueError, "destination already exists"):
                close_year(print_root, db_path, apply=True)

            self.assertTrue(source.exists())
            self.assertEqual(_current_year(db_path), 2026)

    def test_unknown_provider_folder_aborts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            print_root, db_path = _make_print_tree(Path(tmpdir))
            (print_root / "inbox" / "unknown").mkdir()

            with self.assertRaisesRegex(ValueError, "unknown provider folders"):
                close_year(print_root, db_path, apply=True)

            self.assertEqual(_current_year(db_path), 2026)

    def test_direct_files_under_inbox_abort(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            print_root, db_path = _make_print_tree(Path(tmpdir))
            _write(print_root / "inbox" / "luz08.pdf")

            with self.assertRaisesRegex(ValueError, "files directly"):
                close_year(print_root, db_path, apply=True)

            self.assertEqual(_current_year(db_path), 2026)

    def test_ds_store_directly_under_inbox_does_not_abort(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            print_root, db_path = _make_print_tree(Path(tmpdir))
            system_file = _write(print_root / "inbox" / ".DS_Store")
            invoice = _write(print_root / "inbox" / "luz" / "luz08.pdf")

            report = close_year(print_root, db_path, apply=True)

            self.assertEqual(report.status, "applied")
            self.assertTrue(system_file.exists())
            self.assertFalse(invoice.exists())
            self.assertTrue((print_root / "archivo" / "2026" / "luz" / "luz08.pdf").exists())
            self.assertEqual(_current_year(db_path), 2027)

    def test_appledouble_files_inside_provider_folders_are_not_moved(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            print_root, db_path = _make_print_tree(Path(tmpdir))
            system_file = _write(print_root / "inbox" / "gas" / "._gas12.pdf")
            invoice = _write(print_root / "inbox" / "gas" / "gas12.pdf")

            report = close_year(print_root, db_path, apply=True)

            self.assertEqual(report.status, "applied")
            self.assertTrue(system_file.exists())
            self.assertFalse(invoice.exists())
            self.assertFalse((print_root / "archivo" / "2026" / "gas" / "._gas12.pdf").exists())
            self.assertTrue((print_root / "archivo" / "2026" / "gas" / "gas12.pdf").exists())
            self.assertEqual(_current_year(db_path), 2027)


def _make_print_tree(tmpdir: Path) -> tuple[Path, Path]:
    print_root = tmpdir / "_print"
    for provider in ["agua", "gas", "luz", "gft", "pagatelia", "phone"]:
        (print_root / "inbox" / provider).mkdir(parents=True, exist_ok=True)
    db_path = tmpdir / "facturas.sqlite3"
    with connect(db_path) as connection:
        create_schema(connection)
    return print_root, db_path


def _write(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("content", encoding="utf-8")
    return path


def _current_year(db_path: Path) -> int:
    with connect(db_path) as connection:
        return get_current_year(connection)


if __name__ == "__main__":
    unittest.main()
