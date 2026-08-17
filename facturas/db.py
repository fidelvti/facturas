from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS migration_batch (
    id INTEGER PRIMARY KEY,
    source_workbook_path TEXT NOT NULL,
    workbook_sha256 TEXT,
    imported_at TEXT NOT NULL,
    go_live_at TEXT,
    notes TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_migration_batch_workbook_sha256
ON migration_batch(workbook_sha256)
WHERE workbook_sha256 IS NOT NULL;

CREATE TABLE IF NOT EXISTS source_document (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL,
    filename TEXT NOT NULL,
    provider TEXT NOT NULL,
    document_type TEXT,
    file_sha256 TEXT,
    file_size_bytes INTEGER,
    discovered_at TEXT,
    imported_at TEXT,
    ingestion_origin TEXT NOT NULL CHECK (ingestion_origin IN ('historical_workbook', 'automated', 'manual')),
    extraction_status TEXT,
    validation_status TEXT,
    duplicate_of_source_document_id INTEGER REFERENCES source_document(id),
    UNIQUE(file_sha256)
);

CREATE TABLE IF NOT EXISTS invoice (
    id INTEGER PRIMARY KEY,
    provider TEXT NOT NULL,
    invoice_kind TEXT NOT NULL,
    period_yyyymm TEXT,
    original_period_value TEXT,
    provider_invoice_id TEXT,
    invoice_total TEXT,
    amount_payable TEXT,
    ingestion_origin TEXT NOT NULL CHECK (ingestion_origin IN ('historical_workbook', 'automated', 'manual')),
    migration_batch_id INTEGER REFERENCES migration_batch(id),
    source_document_id INTEGER REFERENCES source_document(id),
    source_worksheet TEXT,
    source_row_number INTEGER,
    created_at TEXT NOT NULL,
    validation_status TEXT,
    validation_notes TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_invoice_historical_source_row
ON invoice(source_worksheet, source_row_number)
WHERE ingestion_origin = 'historical_workbook'
  AND source_worksheet IS NOT NULL
  AND source_row_number IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_invoice_provider_invoice_id
ON invoice(provider, provider_invoice_id)
WHERE provider_invoice_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS invoice_adjustment (
    id INTEGER PRIMARY KEY,
    invoice_id INTEGER NOT NULL REFERENCES invoice(id),
    description TEXT NOT NULL,
    amount TEXT NOT NULL,
    category TEXT
);

CREATE TABLE IF NOT EXISTS water_invoice_detail (
    id INTEGER PRIMARY KEY,
    invoice_id INTEGER NOT NULL REFERENCES invoice(id),
    importe_total TEXT NOT NULL,
    lectura TEXT NOT NULL,
    consumo_m3 TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS gas_power_line (
    id INTEGER PRIMARY KEY,
    invoice_id INTEGER NOT NULL REFERENCES invoice(id),
    line_sequence INTEGER NOT NULL,
    source_worksheet TEXT NOT NULL,
    source_row_number INTEGER NOT NULL,
    dias TEXT NOT NULL,
    plazo_fijo TEXT NOT NULL,
    total TEXT NOT NULL,
    formula_text TEXT,
    UNIQUE(source_worksheet, source_row_number)
);

CREATE TABLE IF NOT EXISTS gas_consumption_line (
    id INTEGER PRIMARY KEY,
    invoice_id INTEGER NOT NULL REFERENCES invoice(id),
    line_sequence INTEGER NOT NULL,
    source_worksheet TEXT NOT NULL,
    source_row_number INTEGER NOT NULL,
    consumo TEXT NOT NULL,
    importe TEXT NOT NULL,
    total TEXT NOT NULL,
    formula_text TEXT,
    UNIQUE(source_worksheet, source_row_number)
);

CREATE TABLE IF NOT EXISTS gas_other_charge_line (
    id INTEGER PRIMARY KEY,
    invoice_id INTEGER NOT NULL REFERENCES invoice(id),
    line_sequence INTEGER NOT NULL,
    source_worksheet TEXT NOT NULL,
    source_row_number INTEGER NOT NULL,
    imp_hc TEXT NOT NULL,
    alquiler TEXT NOT NULL,
    canon TEXT NOT NULL,
    iva_rate TEXT NOT NULL,
    peajes TEXT NOT NULL,
    cargos TEXT NOT NULL,
    UNIQUE(source_worksheet, source_row_number)
);

CREATE TABLE IF NOT EXISTS electricity_power_line (
    id INTEGER PRIMARY KEY,
    invoice_id INTEGER NOT NULL REFERENCES invoice(id),
    line_sequence INTEGER NOT NULL,
    source_worksheet TEXT NOT NULL,
    source_row_number INTEGER NOT NULL,
    potencia TEXT NOT NULL,
    precio TEXT NOT NULL,
    dias TEXT NOT NULL,
    total TEXT NOT NULL,
    formula_text TEXT,
    UNIQUE(source_worksheet, source_row_number)
);

CREATE TABLE IF NOT EXISTS electricity_consumption_line (
    id INTEGER PRIMARY KEY,
    invoice_id INTEGER NOT NULL REFERENCES invoice(id),
    line_sequence INTEGER NOT NULL,
    source_worksheet TEXT NOT NULL,
    source_row_number INTEGER NOT NULL,
    consumo TEXT NOT NULL,
    precio TEXT NOT NULL,
    total TEXT NOT NULL,
    formula_text TEXT,
    UNIQUE(source_worksheet, source_row_number)
);

CREATE TABLE IF NOT EXISTS electricity_other_charge_line (
    id INTEGER PRIMARY KEY,
    invoice_id INTEGER NOT NULL REFERENCES invoice(id),
    line_sequence INTEGER NOT NULL,
    source_worksheet TEXT NOT NULL,
    source_row_number INTEGER NOT NULL,
    otros TEXT NOT NULL,
    alquiler TEXT NOT NULL,
    imp_elec_rate TEXT NOT NULL,
    iva_rate TEXT NOT NULL,
    peaje_a TEXT NOT NULL,
    peaje_b TEXT NOT NULL,
    cargo_a TEXT NOT NULL,
    cargo_b TEXT NOT NULL,
    original_peaje_a_value TEXT,
    original_peaje_a_cell_type TEXT,
    UNIQUE(source_worksheet, source_row_number)
);

CREATE TABLE IF NOT EXISTS toll_transaction (
    id INTEGER PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'pagatelia',
    period_yyyymm TEXT,
    original_period_value TEXT NOT NULL,
    importe TEXT NOT NULL,
    total_count TEXT NOT NULL,
    factura TEXT NOT NULL,
    ingestion_origin TEXT NOT NULL CHECK (ingestion_origin IN ('historical_workbook', 'automated', 'manual')),
    migration_batch_id INTEGER REFERENCES migration_batch(id),
    source_document_id INTEGER REFERENCES source_document(id),
    source_worksheet TEXT,
    source_row_number INTEGER,
    created_at TEXT NOT NULL,
    validation_status TEXT,
    validation_notes TEXT,
    UNIQUE(ingestion_origin, source_worksheet, source_row_number)
);

CREATE TABLE IF NOT EXISTS payroll_report (
    id INTEGER PRIMARY KEY,
    employer TEXT NOT NULL DEFAULT 'GFT',
    period_yyyymm TEXT,
    original_period_value TEXT NOT NULL,
    guardias TEXT,
    gastos TEXT,
    dietas TEXT,
    bonus TEXT,
    total TEXT NOT NULL,
    irpf_percent TEXT NOT NULL,
    ingestion_origin TEXT NOT NULL CHECK (ingestion_origin IN ('historical_workbook', 'automated', 'manual')),
    migration_batch_id INTEGER REFERENCES migration_batch(id),
    source_document_id INTEGER REFERENCES source_document(id),
    source_worksheet TEXT,
    source_row_number INTEGER,
    created_at TEXT NOT NULL,
    validation_status TEXT,
    validation_notes TEXT,
    UNIQUE(period_yyyymm, employer, ingestion_origin)
);

CREATE TABLE IF NOT EXISTS manual_correction_audit (
    id INTEGER PRIMARY KEY,
    table_name TEXT NOT NULL,
    record_id INTEGER NOT NULL,
    field_name TEXT NOT NULL,
    previous_value TEXT,
    new_value TEXT,
    changed_at TEXT NOT NULL,
    changed_by TEXT,
    reason TEXT
);

CREATE TABLE IF NOT EXISTS scanner_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    scanner_started_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_invoice_provider_period ON invoice(provider, period_yyyymm);
CREATE INDEX IF NOT EXISTS idx_invoice_source_document ON invoice(source_document_id);
CREATE INDEX IF NOT EXISTS idx_invoice_adjustment_invoice ON invoice_adjustment(invoice_id);
CREATE INDEX IF NOT EXISTS idx_toll_period ON toll_transaction(period_yyyymm);
CREATE INDEX IF NOT EXISTS idx_payroll_period ON payroll_report(period_yyyymm);
CREATE INDEX IF NOT EXISTS idx_source_document_hash ON source_document(file_sha256);
CREATE INDEX IF NOT EXISTS idx_manual_correction_record ON manual_correction_audit(table_name, record_id);
"""


BUSINESS_TABLES = [
    "migration_batch",
    "source_document",
    "invoice",
    "invoice_adjustment",
    "water_invoice_detail",
    "gas_power_line",
    "gas_consumption_line",
    "gas_other_charge_line",
    "electricity_power_line",
    "electricity_consumption_line",
    "electricity_other_charge_line",
    "toll_transaction",
    "payroll_report",
    "manual_correction_audit",
    "scanner_state",
]


def connect(database_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(database_path)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA_SQL)
    _ensure_invoice_amount_payable(connection)


def _ensure_invoice_amount_payable(connection: sqlite3.Connection) -> None:
    columns = {
        row[1]
        for row in connection.execute("PRAGMA table_info(invoice)").fetchall()
    }
    if "amount_payable" not in columns:
        connection.execute("ALTER TABLE invoice ADD COLUMN amount_payable TEXT")


def table_counts(connection: sqlite3.Connection) -> dict[str, int]:
    return {
        table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in BUSINESS_TABLES
    }
