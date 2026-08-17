# AGENTS.md

## Project goal

Build a local personal invoice ingestion and analysis system for macOS.

The current workflow is manual:
- invoices and related documents are stored in iCloud Drive under `Data/_print`
- selected values are manually copied into `_Facturas.xlsx`
- the goal is to migrate the existing spreadsheet data into a local database and use that database as the datastore going forward
- new documents added to `_print` should eventually be detected, parsed, validated and imported automatically
- the data should be exploitable through a dashboard

This is a personal/local system. Prefer simple, maintainable solutions over infrastructure-heavy ones.

## Critical historical-data rule

All existing historical data is accepted as final.

This rule overrides any temptation to recalculate, reconcile, repair or reinterpret old records.

Specifically:
- all data already present in `_Facturas.xlsx` is authoritative historical data for migration purposes
- all documents already stored in `iCloud Drive/Data/_print` are archival source documents
- DO NOT recalculate historical invoices from those documents
- DO NOT reconcile historical documents against `_Facturas.xlsx`
- DO NOT correct historical inconsistencies
- DO NOT attempt to make old Pagatelia records reconcile
- DO NOT replace historical spreadsheet values with values re-extracted from old source documents

Known historical inconsistencies, especially in Pagatelia, are accepted.

The new system must preserve the historical spreadsheet data as-is and start applying automated extraction, calculation, validation and reconciliation only to NEW documents processed after the new system goes live.

The migration boundary / go-live point must therefore be explicit and auditable.

## Current document layout

The user's iCloud folder is conceptually:

`iCloud Drive/Data/_print`

Inside it:

### Historical year folders
- `2020`
- `2021`
- `2022`
- `2023`
- `2024`
- `2025`

These contain archived invoices from those years.

### Provider folders
These contain documents from the beginning of the available history, without yearly subfolders:
- `alarma`
- `movistar+`
- `pagatelia`
- `tickets`
- `vida_laboral`

### Current-year files in `_print`
2026 invoices are stored directly in `_print`.

Filename conventions include:
- `aguaXX...`
- `gasXX...`
- `gftXX...`
- `laiXX...`
- `luzXX...`
- `telfXX...`

where `XX` is the invoice month.

Examples:
- `luz02...` = electricity invoice for February
- `agua04...` = water invoice for April
- `gft06...` = payroll document associated with June

Do not assume filename alone contains every field needed from a document, but use filename/folder conventions for document classification when reliable.

The existing iCloud folder structure should remain in place. The software must read from it; source documents should not be moved into the code repository.

## Existing spreadsheet

The legacy workbook is `_Facturas.xlsx`.

It was populated manually and should be treated as:
1. the authoritative source for historical structured data
2. a functional specification for which fields matter
3. the source for the one-time initial database migration

It must NOT remain the long-term operational datastore after migration.

Known worksheets:
- `Agua`
- three Gas-related worksheets
- three Luz-related worksheets
- `Pagatelia`
- `Nóminas`

Known relationships:
- `Agua` contains data extracted from `aguaXX` documents
- the three Gas worksheets contain data extracted from `gasXX` documents
- the three Luz worksheets contain data extracted from `luzXX` documents
- `Nóminas` contains data extracted from `gftXX` documents
- `Pagatelia` contains toll-payment data historically entered/verified manually

Important: Gas and Luz may require multiple detail rows per invoice. Do not force a one-row-per-invoice schema for all invoice detail data.

Historical spreadsheet values must be migrated without trying to reconstruct them from old invoices.

## Architecture direction

Default preferences unless evidence suggests otherwise:
- Python
- SQLite as the local database
- Streamlit for the first dashboard
- filesystem-based local processing
- deterministic code for calculations and validation
- AI/document models only for extraction tasks where they add value

Principle:
**AI may read/extract; deterministic code should calculate and validate.**

Do not introduce PostgreSQL, Docker, cloud databases, message queues, microservices or other heavy infrastructure unless there is a concrete need.

## Data integrity

For NEW imported source documents, store enough metadata to support:
- source filename/path
- document/provider type
- invoice period
- import timestamp
- duplicate detection, ideally with a file hash
- extraction status
- validation/reconciliation status
- original invoice total where applicable

The system must be idempotent: processing the same new file twice must not create duplicate business data.

Preserve the original documents. Never modify, move or rename source invoices unless explicitly requested.

Historical migrated records should be distinguishable from records created by the new automated ingestion process.

## Pagatelia

Pagatelia has historical inconsistencies caused in part by irregular billing timing and difficult manual reconciliation.

Those inconsistencies are accepted.

For historical Pagatelia data:
- migrate the values from `_Facturas.xlsx` as-is
- do not reprocess old Pagatelia source documents
- do not attempt historical reconciliation
- do not identify or repair historical discrepancies unless the user explicitly requests a separate investigation in the future

For NEW Pagatelia documents after go-live:
- extract the required data
- validate/reconcile the new invoice according to the agreed rules
- surface discrepancies for manual review rather than silently changing data

## Development workflow

Do not start by building the filesystem watcher.

Use these phases:

1. Inspect and document the current workbook structure without challenging historical values.
2. Design the SQLite schema, including provenance that distinguishes migrated historical rows from newly ingested rows.
3. Build a faithful one-time migration/import from `_Facturas.xlsx`.
4. Define an explicit go-live boundary after which documents are considered new.
5. Create parsers/extractors for representative NEW invoice types.
6. Validate the new-document ingestion workflow.
7. Add automatic folder watching only after extraction and validation are reliable.
8. Build/refine the dashboard on top of the database.

## First-task rule

For the first task in this repository:
- inspect `_Facturas.xlsx`
- describe each worksheet, columns, data types, row cardinality and relationships
- propose a normalized but pragmatic SQLite schema
- identify structural ambiguities or risks
- treat all workbook values as authoritative historical data
- DO NOT compare the workbook with historical invoice documents
- DO NOT investigate historical Pagatelia discrepancies
- DO NOT implement the full application yet
- DO NOT modify the workbook
- DO NOT invent fields not supported by the workbook or clearly required for new-document ingestion

Prefer producing concise analysis documents in `docs/` before implementation.

## Coding guidelines

- Keep modules small and explicit.
- Prefer standard library solutions when reasonable.
- Add type hints.
- Add tests for parsing, period normalization, calculations, validation and duplicate handling.
- Keep provider-specific extraction logic isolated.
- Avoid hidden business logic in the UI/dashboard layer.
- Store monetary values safely; do not rely on binary floating-point for accounting calculations.
- Make transformations reproducible.
- Log failures clearly and preserve enough context for manual review.

## Collaboration

The user wants to work iteratively and understand the system while it is being built.

Before large architectural changes:
- explain the proposed change briefly
- state the tradeoff
- prefer the simplest option that satisfies the current need

Do not overengineer.
