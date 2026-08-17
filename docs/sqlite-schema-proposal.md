# SQLite Schema Proposal

This proposal is intentionally pragmatic. It preserves the historical workbook faithfully while supporting future automated ingestion with source-document provenance, duplicate detection, extraction status, and validation status.

No database is created in this task.

## Design Goals

- Preserve every historical workbook value as authoritative.
- Distinguish historical migrated records from future automatically ingested records.
- Allow multiple Gas/Luz detail rows per period or invoice.
- Support multiple invoices for the same provider and period. `provider + period_yyyymm` is a lookup, not a unique key.
- Keep original workbook provenance: worksheet name, Excel row number, original period value, and import batch.
- Avoid recalculating historical formulas while allowing future deterministic validation.
- Allow application-level manual corrections with an audit trail; users should not edit SQLite directly.
- Keep the schema small enough for a local SQLite/Streamlit application.

## Core Concepts

- `migration_batch`: one run that imports historical workbook data.
- `source_document`: a physical file known to the system. Historical workbook rows may not have source documents linked; future ingested invoices should.
- `invoice`: provider/period header for a bill-like record.
- Provider-specific detail tables: store the workbook shapes faithfully where the columns are provider-specific.
- `payroll_report`: payroll period rows from `Nóminas - GFT report`.
- `toll_transaction`: Pagatelia row-level historical and future toll/payment data.
- `manual_correction_audit`: append-only record of application-level corrections.

## Proposed Tables

```sql
CREATE TABLE migration_batch (
    id INTEGER PRIMARY KEY,
    source_workbook_path TEXT NOT NULL,
    workbook_sha256 TEXT,
    imported_at TEXT NOT NULL,
    go_live_at TEXT,
    notes TEXT
);
```

Purpose: records the one-time historical import and the explicit go-live point.

Boundary rule:

- All records present in `_Facturas.xlsx` at the moment of the initial migration are authoritative historical records.
- The boundary is based on ingestion/go-live state, not invoice period or invoice date.
- After go-live, any document processed by the new ingestion system is a new document, even if it refers to an earlier billing period.

```sql
CREATE TABLE source_document (
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
```

Purpose: future ingestion provenance and idempotency. Historical migrated workbook rows do not require a linked source document.

```sql
CREATE TABLE invoice (
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
```

Purpose: common invoice/period header. For historical rows, `source_worksheet` and `source_row_number` preserve workbook provenance. For future files, `source_document_id` and `file_sha256` support idempotency through `source_document`.

Notes:

- `provider_invoice_id` is nullable because the workbook does not contain explicit invoice numbers. Future extractors can populate it when a document exposes one.
- `invoice_total` is nullable because several workbook sheets have component totals but no explicit invoice total. For new Endesa electricity invoices, this means the printed invoice `TOTAL` before optional post-total discounts/adjustments.
- `amount_payable` is nullable and is intended for new invoices where the final payable amount is available. Historical rows may leave it `NULL`; do not reconstruct historical discounts.
- For `Agua`, `invoice_total` can store `Importe total`.
- For Gas and Luz, invoice totals should be filled only when supported by future source extraction or an agreed rule. Historical component totals should not be summed to invent missing invoice totals.
- Do not enforce uniqueness on `(provider, period_yyyymm)`. The model must allow adjustments, corrective invoices, or multiple invoices in one billing period.
- Use source-document idempotency for automated imports and source-row provenance for historical imports.

Suggested uniqueness indexes:

```sql
CREATE UNIQUE INDEX uq_invoice_historical_source_row
ON invoice(source_worksheet, source_row_number)
WHERE ingestion_origin = 'historical_workbook'
  AND source_worksheet IS NOT NULL
  AND source_row_number IS NOT NULL;

CREATE UNIQUE INDEX uq_invoice_provider_invoice_id
ON invoice(provider, provider_invoice_id)
WHERE provider_invoice_id IS NOT NULL;
```

`uq_invoice_historical_source_row` works for historical one-row invoice sheets such as `Agua`. Gas and Luz component sheets keep row uniqueness in their child tables because the header can group several workbook rows.

## Invoice Adjustments

```sql
CREATE TABLE invoice_adjustment (
    id INTEGER PRIMARY KEY,
    invoice_id INTEGER NOT NULL REFERENCES invoice(id),
    description TEXT NOT NULL,
    amount TEXT NOT NULL,
    category TEXT
);
```

Purpose: stores optional signed post-total adjustments for new invoices, for example `PARA TI | -5.00`. These rows are not reconstructed for historical migrated workbook data.

For new Endesa electricity invoices:

- `Potencia + Energía + Varios + Impuestos = invoice_total`.
- `invoice_total + signed invoice_adjustment.amount values = amount_payable`.
- Peajes and cargos remain informational breakdowns already included in the main sections and must not be added again during reconciliation.

## Water

```sql
CREATE TABLE water_invoice_detail (
    id INTEGER PRIMARY KEY,
    invoice_id INTEGER NOT NULL REFERENCES invoice(id),
    importe_total TEXT NOT NULL,
    lectura TEXT NOT NULL,
    consumo_m3 TEXT NOT NULL
);
```

Mapping from `Agua`:

- One `invoice` row per workbook row.
- `provider = 'agua'`.
- `invoice_kind = 'water'`.
- `invoice_total = Importe total`.

## Gas

For historical Gas data, create invoice headers that can group rows from the three component worksheets, but do not make `provider + period_yyyymm` unique. Because the workbook itself stores rows separately, every detail row should retain source worksheet and row number.

```sql
CREATE TABLE gas_power_line (
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
```

```sql
CREATE TABLE gas_consumption_line (
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
```

```sql
CREATE TABLE gas_other_charge_line (
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
```

Historical mapping:

- `provider = 'gas'`.
- `invoice_kind = 'gas'`.
- `period_yyyymm` comes from `Periodo`.
- Repeated periods are expected in child tables.
- Formula cached totals are stored as `total`; formula text may be stored in `formula_text` for audit only.

Historical migration rule:

- During the initial historical migration, group existing Gas workbook rows by period into one invoice-like header for analysis convenience. This is a migration convention for the legacy workbook only, not a uniqueness rule. The schema still supports later multiple Gas invoices for the same provider and period by allowing additional `invoice` rows with the same `period_yyyymm`.

## Electricity

```sql
CREATE TABLE electricity_power_line (
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
```

```sql
CREATE TABLE electricity_consumption_line (
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
```

```sql
CREATE TABLE electricity_other_charge_line (
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
```

Historical mapping:

- `provider = 'luz'`.
- `invoice_kind = 'electricity'`.
- `period_yyyymm` comes from `Periodo`.
- Repeated periods are expected in power and consumption child tables.
- `original_peaje_a_value` and `original_peaje_a_cell_type` preserve the one text-like numeric value observed in `Peaje A`.

Historical migration rule:

- During the initial historical migration, group existing Luz workbook rows by period into one invoice-like header for analysis convenience. This is a migration convention for the legacy workbook only, not a uniqueness rule. The schema still supports later multiple Luz invoices for the same provider and period by allowing additional `invoice` rows with the same `period_yyyymm`.

## Pagatelia

```sql
CREATE TABLE toll_transaction (
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
```

Purpose: keeps Pagatelia row-level data without forcing it into a one-invoice-per-period model.

Historical rule:

- Store `Importe`, `Total`, and `Factura` exactly as migrated.
- Do not recompute `Factura` from `Importe` and `Total`.
- Do not reconcile historical rows.

## Payroll

```sql
CREATE TABLE payroll_report (
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
```

Purpose: one row per payroll month, preserving sparse optional components.

Notes:

- `guardias` remains an open question: the sheet does not prove whether it is money, hours, or another quantity.
- `% IRPF` should be stored as the displayed percent number, for example `22.52`, not converted to `0.2252` unless a future calculation layer explicitly needs that.

## Manual Corrections

```sql
CREATE TABLE manual_correction_audit (
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
```

Purpose: supports future application-level corrections without requiring direct SQLite edits.

Rules:

- Corrections should be made through application code, not by hand-editing SQLite.
- Every correction should insert one audit row per changed field.
- `previous_value` and `new_value` are stored as text to match the schema's faithful decimal/text preservation strategy.
- `table_name` and `record_id` identify the affected record. SQLite cannot enforce a polymorphic foreign key here, so the application layer must validate the target table and record.
- `ingestion_origin = 'manual'` is for manual records or correction records where applicable. For edits to existing records, keep the original record's ingestion origin and use this audit table to record the manual change.

## Period Normalization

Store both:

- `original_period_value`: exactly what the workbook/source contained.
- `period_yyyymm`: normalized text `YYYYMM` for querying and relationships.

Rules for historical migration:

- Numeric `202604` becomes `period_yyyymm = '202604'`, original value preserved.
- Text `'202604'` remains `period_yyyymm = '202604'`, original value preserved.
- Date-like payroll value `'2026-07-01'` becomes `period_yyyymm = '202607'`, original value preserved.

## Historical Versus Future Records

Every business table has `ingestion_origin`:

- `historical_workbook`: migrated from `_Facturas.xlsx`.
- `automated`: parsed from a future source document after go-live.
- `manual`: future application-created manual entry or correction record.

Historical workbook rows should also carry:

- `migration_batch_id`.
- `source_worksheet`.
- `source_row_number`.
- Original values as text.
- Historical records are defined by presence in `_Facturas.xlsx` at initial migration time, not by their invoice period.

Future automated rows should carry:

- `source_document_id`.
- `file_sha256` through `source_document`.
- `extraction_status`.
- `validation_status`.
- `validation_notes` when discrepancies require review.
- Future automated rows are defined by being processed after go-live, even if their billing period is earlier than the go-live date.

New-file scanner rule:

- At scanner activation, store a single `scanner_started_at` timestamp.
- Do not inspect, register, hash, classify, extract, or import files already present under `_print`.
- During later scans, recognized files whose filesystem modification time is not later than `scanner_started_at` are ignored as historical.
- Recognized files newer than `scanner_started_at` are handed to the existing ingestion pipeline, where SHA256 duplicate handling remains the safeguard for new files.
- Unsupported filenames are ignored without creating `source_document` records.

Manual corrections:

- Users should correct records through the application, not direct database editing.
- Each field-level change should be recorded in `manual_correction_audit`.
- The corrected business record may keep its original `ingestion_origin`; the audit row is the evidence of manual intervention.

## Suggested Indexes

```sql
CREATE INDEX idx_invoice_provider_period ON invoice(provider, period_yyyymm);
CREATE INDEX idx_invoice_source_document ON invoice(source_document_id);
CREATE INDEX idx_toll_period ON toll_transaction(period_yyyymm);
CREATE INDEX idx_payroll_period ON payroll_report(period_yyyymm);
CREATE INDEX idx_source_document_hash ON source_document(file_sha256);
CREATE INDEX idx_manual_correction_record ON manual_correction_audit(table_name, record_id);
```

## Migration Approach Later

When implementation begins:

1. Create one `migration_batch` for `_Facturas.xlsx`.
2. Read each worksheet row without modifying the workbook.
3. Normalize periods into `period_yyyymm` while preserving original values.
4. Insert historical data with `ingestion_origin = 'historical_workbook'`.
5. Preserve source worksheet and row numbers.
6. For formulas, migrate cached values as business values and optionally preserve formula text on the relevant record-level table where a `formula_text` column exists.
7. Do not read or compare historical invoice documents during migration.

## Decisions Needed Before Implementation

- Choose the concrete `go_live_at` timestamp to record in `migration_batch` when the migration is actually run.
- Confirm whether `changed_by` in `manual_correction_audit` can default to a simple local username/app user label for this personal system.
- Before each future extractor is implemented, clarify provider-specific ambiguous fields and units enough to build validation rules.
