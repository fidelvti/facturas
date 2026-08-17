from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
import unittest

from facturas.classify import (
    classify_source_document,
    electricity_period_from_filename,
    gas_period_from_filename,
    pagatelia_period_from_filename,
    payroll_period_from_filename,
    water_period_from_filename,
)
from facturas.db import connect
from facturas.extractors.electricity import extract_endesa_ocr_invoice
from facturas.extractors.gas import extract_gas_invoice
from facturas.extractors.pagatelia import extract_pagatelia_invoice
from facturas.extractors.payroll import extract_gft_payroll_report
from facturas.extractors.water import extract_water_invoice
from facturas.ingest import ingest_source_file


ELECTRICITY_TEXT = """
Nº factura: P26CON030173919
Potencia .... 20,92
Energía 32,24
Varios .... 1,42
Impuestos .... 14,79
TOTAL 69,37
PARA TI -5,00
TOTAL A PAGAR 64,37
P1 (punta-llano) 4,600 kw x 0,056532 eur/kw x 60 días
Pot. P3 4,600 kw x 0,019254 eur/kw x 60 días
Consumo 201,000 kwh x 0,108790 eur/kwh
Consumo 95,738 kwh x 0,108398 eur/kwh
Financiación bono social 60 días x 0,012345 eur/día
Alquiler del contador (60 días x 0,011818 eur/día)
Impuesto electricidad (55,88 eur x 5,11269632 %
IVA normal 21 %
Peaje de transporte y distribución, que ha sido de 35,95 €
( 27,35 € potencia, 8,60 € por energía
Cargos, que ha sido de 12,45 €
( 7,10 € potencia, 5,35 € por energía activa
"""

GAS_TEXT = """
Núm. factura: FE26137016725628
Total a pagar 34,76 €
Terme fix 60 dies 0,26663 €/dia
Període de 1.1 a 2.1 21 kWh 0,03613 €/kWh
Període de 2.1 a 3.1 13 kWh 0,041199 €/kWh
Impost especial sobre hidrocarburs 34 kWh 0,0015 €/kWh 0,05 €
Lloguer de comptador 60 dies 0,019 €/dia 1,14 €
Cànon de finca 1 10,24 €
Total IVA 21 %
Import de peatges: 11,82 €
Import de càrrecs: 0,09 €
"""

WATER_TEXT = """
DADES DE FACTURACIÓ
Núm. factura 13332026A200046480
CONSUM TOTAL 4 m3 TOTAL A PAGAR 47,73 €
Comptador Ø mm Lectura anterior Lectura actual Consum m3 Base fact.
I19BA340378W 15 08-04-26 348 05-06-26 352 4 Real
"""

PAYROLL_EMPTY_OPTIONALS_TEXT = """
RECIBO DE NOMINA
420 COMPENS.BENEF.SOCIAL 220,78
1051 IMP A CUENTA RENTA 220,780 20,6600 45,61
LIQUIDO A RECIBIR 175,17€
"""

PAYROLL_POPULATED_TEXT = """
RECIBO DE NOMINA
321 SUELDO BASE 30,000 65,6666 1970,00
698 COMIDA 158,60
1051 IMP A CUENTA RENTA 4110,840 22,5300 926,17
LIQUIDO A RECIBIR 2900,92€
"""

PAGATELIA_2608_TEXT = """
Factura de telepeaje
Detalles de pagos con mobe
Fecha Concepto Precio € Tipo IVA % Cuota IVA € Subtotal €
30-04-2022
13:38
Bra. Les Fonts Norte 2,2727 21 0,4773 2,75
01-05-2022
00:04
Pk Gràcia III 9,7107 21 2,0392 11,75
SUBTOTAL 11,9835 21 2,5165 14,50
"""

PAGATELIA_2609_TEXT = """
Factura de telepeaje
Detalles de cuotas, compras, comisiones y gastos
Fecha Concepto Precio € Tipo IVA % Cuota IVA € Subtotal €
25-05-2023 Cuota servicio mes de uso Francia
1,9835 21 0,4165 2,40
SUBTOTAL 1,9835 21 0,4165 2,40
Detalles de pagos con mobe
Fecha Concepto Precio € Tipo IVA % Cuota IVA € Subtotal €
28-04-2023
22:47
Bra. Les Fonts Sur 1,0909 21 0,2291 1,32
28-04-2023
22:48
Bra. Les Fonts Sur 1,0909 21 0,2291 1,32
SUBTOTAL 2,1818 21 0,4582 2,64
"""


class IngestionTests(unittest.TestCase):
    def test_classifies_supported_filenames(self) -> None:
        cases = [
            ("luz08.txt", "luz", "electricity_invoice"),
            ("gas08.txt", "gas", "gas_invoice"),
            ("agua08.txt", "agua", "water_invoice"),
            ("gft08.txt", "gft", "payroll_report"),
            ("Pagatelia2608.txt", "pagatelia", "toll_invoice"),
        ]
        for filename, provider, document_type in cases:
            with self.subTest(filename=filename):
                classification = classify_source_document(Path("/tmp") / filename)
                self.assertEqual(classification.provider, provider)
                self.assertEqual(classification.document_type, document_type)
                self.assertEqual(classification.confidence, "high")

    def test_extracts_periods_from_filename(self) -> None:
        self.assertEqual(electricity_period_from_filename(Path("luz08.txt"), default_year=2026), "202608")
        self.assertEqual(gas_period_from_filename(Path("gas10.txt"), default_year=2026), "202610")
        self.assertEqual(water_period_from_filename(Path("agua12.txt"), default_year=2026), "202612")
        self.assertEqual(payroll_period_from_filename(Path("gft09.txt"), default_year=2026), "202609")
        self.assertEqual(pagatelia_period_from_filename(Path("Pagatelia2305a.txt")), "202305")
        self.assertEqual(pagatelia_period_from_filename(Path("Pagatelia2305b.txt")), "202305")
        self.assertIsNone(electricity_period_from_filename(Path("luz13.txt"), default_year=2026))
        self.assertIsNone(pagatelia_period_from_filename(Path("Pagatelia2613.txt")))

    def test_parses_electricity_text(self) -> None:
        extraction = extract_endesa_ocr_invoice(
            ELECTRICITY_TEXT,
            filename_period_yyyymm=electricity_period_from_filename(Path("luz08.txt"), default_year=2026),
        )

        self.assertEqual(extraction.errors, [])
        self.assertEqual(extraction.period_yyyymm, "202608")
        self.assertEqual(extraction.provider_invoice_id, "P26CON030173919")
        self.assertEqual(extraction.invoice_total, "69.37")
        self.assertEqual(extraction.payable_total, "64.37")
        self.assertEqual(extraction.section_totals, {
            "potencia": "20.92",
            "energia": "32.24",
            "varios": "1.42",
            "impuestos": "14.79",
        })
        self.assertEqual(extraction.discounts[0].amount, "-5.00")
        self.assertEqual(len(extraction.power_lines), 2)
        self.assertEqual(len(extraction.consumption_lines), 2)
        self.assertEqual(len(extraction.other_charge_lines), 1)

    def test_parses_gas_text(self) -> None:
        extraction = extract_gas_invoice(
            GAS_TEXT,
            filename_period_yyyymm=gas_period_from_filename(Path("gas08.txt"), default_year=2026),
        )

        self.assertEqual(extraction.errors, [])
        self.assertEqual(extraction.period_yyyymm, "202608")
        self.assertEqual(extraction.provider_invoice_id, "FE26137016725628")
        self.assertEqual(extraction.invoice_total, "34.76")
        self.assertEqual(extraction.power_lines[0].total, "15.9978")
        self.assertEqual(extraction.consumption_lines[1].total, "0.535587")
        self.assertIsNotNone(extraction.other_line)

    def test_parses_water_text(self) -> None:
        extraction = extract_water_invoice(
            WATER_TEXT,
            filename_period_yyyymm=water_period_from_filename(Path("agua08.txt"), default_year=2026),
        )

        self.assertEqual(extraction.errors, [])
        self.assertEqual(extraction.provider_invoice_id, "13332026A200046480")
        self.assertEqual(extraction.invoice_total, "47.73")
        self.assertEqual(extraction.lectura, "352")
        self.assertEqual(extraction.consumo_m3, "4")

    def test_parses_payroll_text_with_optional_fields_empty(self) -> None:
        extraction = extract_gft_payroll_report(
            PAYROLL_EMPTY_OPTIONALS_TEXT,
            filename_period_yyyymm=payroll_period_from_filename(Path("gft08.txt"), default_year=2026),
        )

        self.assertEqual(extraction.errors, [])
        self.assertIsNone(extraction.guardias)
        self.assertIsNone(extraction.gastos)
        self.assertIsNone(extraction.dietas)
        self.assertIsNone(extraction.bonus)
        self.assertEqual(extraction.total, "175.17")
        self.assertEqual(extraction.irpf_percent, "20.66")

    def test_parses_populated_payroll_gastos_regression_text(self) -> None:
        extraction = extract_gft_payroll_report(
            PAYROLL_POPULATED_TEXT,
            filename_period_yyyymm=payroll_period_from_filename(Path("gft09.txt"), default_year=2026),
        )

        self.assertEqual(extraction.errors, [])
        self.assertIsNone(extraction.guardias)
        self.assertEqual(extraction.gastos, "158.60")
        self.assertIsNone(extraction.dietas)
        self.assertIsNone(extraction.bonus)
        self.assertEqual(extraction.total, "2900.92")
        self.assertEqual(extraction.irpf_percent, "22.53")

    def test_parses_pagatelia_single_list_text(self) -> None:
        extraction = extract_pagatelia_invoice(
            PAGATELIA_2608_TEXT,
            filename_period_yyyymm=pagatelia_period_from_filename(Path("Pagatelia2608.txt")),
        )

        self.assertEqual(extraction.errors, [])
        self.assertEqual(extraction.movement_list_count, 1)
        self.assertEqual(extraction.movements, ["2.75", "11.75"])
        self.assertEqual(
            [(row.importe, row.total, row.factura) for row in extraction.grouped_amounts],
            [("2.75", "1", "2.75"), ("11.75", "1", "11.75")],
        )
        self.assertEqual(extraction.printed_total, "14.50")

    def test_parses_pagatelia_two_list_text_and_groups_across_lists(self) -> None:
        extraction = extract_pagatelia_invoice(
            PAGATELIA_2609_TEXT,
            filename_period_yyyymm=pagatelia_period_from_filename(Path("Pagatelia2609.txt")),
        )

        self.assertEqual(extraction.errors, [])
        self.assertEqual(extraction.movement_list_count, 2)
        self.assertEqual(extraction.movements, ["2.40", "1.32", "1.32"])
        self.assertEqual(
            [(row.importe, row.total, row.factura) for row in extraction.grouped_amounts],
            [("1.32", "2", "2.64"), ("2.40", "1", "2.40")],
        )
        self.assertEqual(extraction.printed_total, "5.04")

    def test_successful_database_insertions_and_duplicate_skip(self) -> None:
        cases = [
            ("luz08.txt", ELECTRICITY_TEXT, "invoice", 1),
            ("gas08.txt", GAS_TEXT, "invoice", 1),
            ("agua08.txt", WATER_TEXT, "water_invoice_detail", 1),
            ("gft08.txt", PAYROLL_EMPTY_OPTIONALS_TEXT, "payroll_report", 1),
            ("Pagatelia2609.txt", PAGATELIA_2609_TEXT, "toll_transaction", 2),
        ]
        for filename, text, table, expected_rows in cases:
            with self.subTest(filename=filename):
                with tempfile.TemporaryDirectory() as tmpdir:
                    root = Path(tmpdir)
                    source = _write_text(root / filename, text)
                    db_path = root / "facturas.sqlite3"

                    first = ingest_source_file(source, db_path)
                    second = ingest_source_file(source, db_path)

                    self.assertEqual(first.status, "imported")
                    self.assertEqual(second.status, "skipped_duplicate")
                    with connect(db_path) as connection:
                        self.assertEqual(_count(connection, "source_document"), 1)
                        self.assertEqual(_count(connection, table), expected_rows)

    def test_payroll_insertion_preserves_optional_nulls(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "facturas.sqlite3"
            ingest_source_file(_write_text(root / "gft08.txt", PAYROLL_EMPTY_OPTIONALS_TEXT), db_path)

            with connect(db_path) as connection:
                report = connection.execute(
                    """
                    SELECT guardias, gastos, dietas, bonus, total, irpf_percent
                    FROM payroll_report
                    """
                ).fetchone()

        self.assertEqual(report, (None, None, None, None, "175.17", "20.66"))

    def test_bad_supported_documents_go_to_manual_review(self) -> None:
        cases = [
            ("luz09.txt", "not an Endesa invoice", "invoice"),
            ("gas09.txt", "not a gas invoice", "invoice"),
            ("agua09.txt", "not a water invoice", "invoice"),
            ("gft09.txt", "not a payroll report", "payroll_report"),
            ("Pagatelia2610.txt", "not a Pagatelia movement list", "toll_transaction"),
        ]
        for filename, text, table in cases:
            with self.subTest(filename=filename):
                with tempfile.TemporaryDirectory() as tmpdir:
                    root = Path(tmpdir)
                    source = _write_text(root / filename, text)
                    db_path = root / "facturas.sqlite3"

                    report = ingest_source_file(source, db_path)

                    self.assertEqual(report.status, "manual_review")
                    self.assertEqual(report.validation_status, "manual_review")
                    with connect(db_path) as connection:
                        self.assertEqual(_count(connection, "source_document"), 1)
                        self.assertEqual(_count(connection, table), 0)


def _write_text(path: Path, text: str) -> Path:
    path.write_text(text.strip() + "\n", encoding="utf-8")
    return path


def _count(connection: sqlite3.Connection, table: str) -> int:
    return connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


if __name__ == "__main__":
    unittest.main()
