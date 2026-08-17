# SQLite Schema Proposal

This proposal is intentionally pragmatic. It preserves the historical workbook faithfully while supporting future automated ingestion with source-document provenance, duplicate detection, extraction status, and validation status.

No database is created in this task.

## Design Goals

- Preserve every historical workbook value as authoritative.
- Distinguish historical migrated records from future automatically ingested records.
- Allow multiple Gas/Luz detail rows per period or invoice.
- Keep original workbook provenance: worksheet name, Excel row number, original period value, and import batch.
- Avoid recalculating historical formulas while allowing future deterministic validation.
- Keep the schema small enough for a local SQLite/Streamlit application.

## Core Concepts

- `migration_batch`: one run that imports historical workbook data.
- `source_document`: a physical file known to the system. Historical workbook rows may not have source documents linked; future ingested invoices should.
- `invoice`: provider/period header for a bill-like record.
- Provider-specific detail tables: store the workbook shapes faithfully where the columns are provider-specific.
- `payroll_report`: payroll period rows from `Nóminas - GFT report`.
- `toll_transaction`: Pagatelia row-level historical and future toll/payment data.

## Proposed Tables

```sql
CREATE TABLE migration_batch (
    id INTEGER PRIMARY KEY,
    source_workbook_path TEXT NOT NULL,
    workbook_sha256 TEXT,
    imported_at TEXT NOT NULL,
    migration_boundary_date TEXT,
    notes TEXT
);
```

Purpose: records the one-time historical import and the explicit go-live boundary.

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
    invoice_total TEXT,
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

- `invoice_total` is nullable because several workbook sheets have component totals but no explicit invoice total.
- For `Agua`, `invoice_total` can store `Importe total`.
- For Gas and Luz, invoice totals should be filled only when supported by future source extraction or an agreed rule. Historical component totals should not be summed to invent missing invoice totals.
- Enforce uniqueness with indexes suited to the chosen record shape, for example one historical invoice per provider/period for utility headers, and row-level uniqueness in child tables.

Suggested uniqueness indexes:

```sql
CREATE UNIQUE INDEX uq_invoice_period_origin
ON invoice(provider, invoice_kind, period_yyyymm, ingestion_origin)
WHERE source_document_id IS NULL;

CREATE UNIQUE INDEX uq_invoice_source_document
ON invoice(source_document_id)
WHERE source_document_id IS NOT NULL;
```

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

For Gas, create one logical `invoice` per period where possible, then attach rows from the three component worksheets. Because the workbook itself stores rows separately, every detail row should retain source worksheet and row number.

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

Open design choice:

- Whether to create a single `invoice` header per gas period and attach all matching component rows, or create separate invoice headers per source worksheet row. A single header per period is more normalized; preserving row-level source metadata in child lines protects fidelity.

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

Open design choice:

- As with Gas, use one invoice header per electricity period unless future evidence shows multiple invoices can share a provider and period.

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

## Optional Audit Table

For maximum migration fidelity, add a generic cell/value audit table. This is useful if preserving exact original cell types, formulas, or formatting becomes important.

```sql
CREATE TABLE workbook_cell_audit (
    id INTEGER PRIMARY KEY,
    migration_batch_id INTEGER NOT NULL REFERENCES migration_batch(id),
    source_worksheet TEXT NOT NULL,
    source_row_number INTEGER NOT NULL,
    source_column_name TEXT NOT NULL,
    source_cell_ref TEXT,
    raw_value TEXT,
    normalized_value TEXT,
    cell_type TEXT,
    formula_text TEXT
);
```

Tradeoff: this increases storage and migration complexity, but it makes the migration highly auditable. For a small personal workbook, the cost is modest.

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
- `manual`: future manual correction or entry, if allowed.

Historical workbook rows should also carry:

- `migration_batch_id`.
- `source_worksheet`.
- `source_row_number`.
- Original values as text.

Future automated rows should carry:

- `source_document_id`.
- `file_sha256` through `source_document`.
- `extraction_status`.
- `validation_status`.
- `validation_notes` when discrepancies require review.

## Suggested Indexes

```sql
CREATE INDEX idx_invoice_provider_period ON invoice(provider, period_yyyymm);
CREATE INDEX idx_invoice_source_document ON invoice(source_document_id);
CREATE INDEX idx_toll_period ON toll_transaction(period_yyyymm);
CREATE INDEX idx_payroll_period ON payroll_report(period_yyyymm);
CREATE INDEX idx_source_document_hash ON source_document(file_sha256);
```

## Migration Approach Later

When implementation begins:

1. Create one `migration_batch` for `_Facturas.xlsx`.
2. Read each worksheet row without modifying the workbook.
3. Normalize periods into `period_yyyymm` while preserving original values.
4. Insert historical data with `ingestion_origin = 'historical_workbook'`.
5. Preserve source worksheet and row numbers.
6. For formulas, migrate cached values as business values and optionally formula text into audit fields.
7. Do not read or compare historical invoice documents during migration.

## Decisions Needed Before Implementation

- Confirm the go-live boundary date or rule that separates historical documents from future automated ingestion.
- Decide whether Gas/Luz should use one invoice header per provider-period or a more granular invoice identity if multiple invoices can share the same period.
- Decide whether to include the optional `workbook_cell_audit` table in the first migration.
- Confirm exact units and business meanings for ambiguous columns before building validation rules.
- Decide whether future manual edits are allowed in the database and, if so, how they should be audited.
