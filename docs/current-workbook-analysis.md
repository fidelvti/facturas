# Current Workbook Analysis

Workbook inspected: `data/_Facturas.xlsx`.

This analysis treats all workbook values as authoritative historical data. It does not recalculate formula totals, correct values, compare against invoice documents, or investigate historical discrepancies.

## Workbook Summary

The workbook contains 9 worksheets:

| Worksheet | Approx. data rows | Shape |
| --- | ---: | --- |
| `Agua` | 27 | One row per water billing period |
| `Gas - Potencia` | 52 | Gas fixed-term/power detail rows; multiple rows can share a period |
| `Gas - Consumo - Tabla 2` | 66 | Gas consumption detail rows; multiple rows can share a period |
| `Gas - Otros - Tabla 3` | 43 | Gas invoice-level/other charge rows; mostly one row per period, with a few repeated periods |
| `Luz - Potencia` | 126 | Electricity power detail rows; multiple rows can share a period |
| `Luz - Consumo - Tabla 2` | 132 | Electricity consumption detail rows; multiple rows can share a period |
| `Luz - Otros - Tabla 3` | 52 | Electricity invoice-level/other charge rows; mostly one row per period, with one repeated period |
| `Pagatelia` | 191 | Toll/payment rows; multiple rows per period |
| `Nóminas - GFT report` | 151 | One row per payroll period |

## General Structural Observations

- Period formats are inconsistent by worksheet:
  - Most utility sheets use numeric `YYYYMM` values, for example `202604`.
  - `Pagatelia` uses text `YYYYMM` values.
  - `Nóminas - GFT report` uses date-like text values representing the first day of the month, for example `2026-07-01`.
- The historical/future boundary is not based on `Periodo`, invoice date, or billing date. All records present in `_Facturas.xlsx` at the moment of initial migration are historical records; after go-live, any document processed by the new ingestion system is a new record, even if it refers to an earlier billing period.
- Several Gas and Luz worksheets contain formulas in `Total` columns. Their cached values are part of the workbook data and should be migrated as historical values, not recomputed.
- Gas and Luz are split into multiple worksheets that appear to describe different parts of the same provider invoice/period.
- Gas and Luz detail sheets have repeated periods, so the future schema must allow multiple line rows per invoice or period.
- Provider plus period must not be treated as a unique business key for the long-term system. Future data may include adjustments, corrective invoices, or multiple invoices in the same billing period.
- Monetary and rate values should be stored as exact decimal text or scaled integers during migration, not binary floating point.
- Existing row order matters for duplicated periods and should be preserved with a source worksheet row number or line sequence.

## Worksheet Details

## `Agua`

Approximate data rows: 27.

Period range observed: `202202` through `202606`.

Likely business key: `Periodo`, if water has at most one row per period.

Columns:

| Column | Apparent type | Meaning |
| --- | --- | --- |
| `Periodo` | Integer `YYYYMM` | Billing period/month. |
| `Importe total` | Decimal money | Total amount for the water invoice/period. |
| `Lectura` | Integer | Meter reading. Open question: whether this is current reading, closing reading, or another reading value. |
| `Consumo m3` | Integer quantity | Water consumption in cubic meters. |

Structural notes:

- `Periodo` is unique in this sheet.
- No nulls were observed in the used data range.
- This sheet appears to be invoice-level, not detail-line-level.

## `Gas - Potencia`

Approximate data rows: 52.

Period range observed: `202004` through `202608`.

Likely business key: source row identity, or `(Periodo, row sequence)`. `Periodo` alone is not unique.

Columns:

| Column | Apparent type | Meaning |
| --- | --- | --- |
| `Periodo` | Integer `YYYYMM` | Gas billing period/month. |
| `Días` | Integer quantity | Number of days covered by this fixed-term segment. |
| `Plazo fijo` | Decimal rate | Fixed-term daily rate. Open question: exact unit/name may be provider-specific. |
| `Total` | Formula with cached decimal money | Segment total, formula pattern `Días * Plazo fijo`. Preserve cached workbook value. |

Structural notes:

- 40 unique periods across 52 rows.
- 11 periods repeat, showing that one period can produce multiple fixed-term rows.
- `Total` is formula-derived in every data row, but the cached historical value should be migrated.

## `Gas - Consumo - Tabla 2`

Approximate data rows: 66.

Period range observed: `202004` through `202608`.

Likely business key: source row identity, or `(Periodo, row sequence)`. `Periodo` alone is not unique.

Columns:

| Column | Apparent type | Meaning |
| --- | --- | --- |
| `Periodo` | Integer `YYYYMM` | Gas billing period/month. |
| `Consumo` | Integer quantity | Gas consumption quantity. Open question: unit is not stated in the sheet. |
| `Importe` | Decimal rate | Consumption unit price/rate. |
| `Total` | Formula with cached decimal money | Consumption segment total, formula pattern `Consumo * Importe`. Preserve cached workbook value. |

Structural notes:

- 40 unique periods across 66 rows.
- 23 periods repeat, showing that one period can produce multiple consumption rows.
- `Total` is formula-derived in every data row.

## `Gas - Otros - Tabla 3`

Approximate data rows: 43.

Period range observed: `202004` through `202608`.

Likely business key: source row identity, or `(Periodo, row sequence)`. `Periodo` is usually but not always unique.

Columns:

| Column | Apparent type | Meaning |
| --- | --- | --- |
| `Periodo` | Integer `YYYYMM` | Gas billing period/month. |
| `Imp HC` | Decimal money | Hydrocarbon tax or similar charge. Open question: exact provider label. |
| `Alquiler` | Decimal money | Equipment rental charge. |
| `Canon` | Decimal money | Canon/fixed regulatory charge. Open question: exact meaning. |
| `IVA` | Decimal rate | VAT rate, observed values include `0.21`, `0.10`, and `0.05`. |
| `Peajes` | Decimal money | Toll/access charge. |
| `Cargos` | Decimal money | Additional charges. |

Structural notes:

- 40 unique periods across 43 rows.
- 2 periods repeat.
- No formulas were observed in this sheet.
- Repeated periods mean this should still be modeled as detail rows or invoice charges, not forced to one row per period.

## `Luz - Potencia`

Approximate data rows: 126.

Period range observed: `202002` through `202607`.

Likely business key: source row identity, or `(Periodo, row sequence)`. `Periodo` alone is not unique.

Columns:

| Column | Apparent type | Meaning |
| --- | --- | --- |
| `Periodo` | Integer `YYYYMM` | Electricity billing period/month. |
| `Potencia` | Decimal quantity | Contracted power. Observed value is consistently `4.4`. |
| `Precio` | Decimal rate | Power price/rate. |
| `Días` | Integer quantity | Number of days covered by this segment. |
| `Total` | Formula with cached decimal money | Power segment total, formula pattern `Potencia * Precio * Días`. Preserve cached workbook value. |

Structural notes:

- 51 unique periods across 126 rows.
- 46 periods repeat, showing that one period commonly produces multiple power rows.
- `Total` is formula-derived in every data row.

## `Luz - Consumo - Tabla 2`

Approximate data rows: 132.

Period range observed: `202002` through `202607`.

Likely business key: source row identity, or `(Periodo, row sequence)`. `Periodo` alone is not unique.

Columns:

| Column | Apparent type | Meaning |
| --- | --- | --- |
| `Periodo` | Integer `YYYYMM` | Electricity billing period/month. |
| `Consumo` | Decimal quantity | Electricity consumption quantity. Some values are integers and later values include decimals. Open question: unit is not stated in the sheet, likely kWh but not proven by workbook alone. |
| `Precio` | Decimal rate | Consumption price/rate. |
| `Total` | Formula with cached decimal money | Consumption segment total, formula pattern `Consumo * Precio`. Preserve cached workbook value. |

Structural notes:

- 51 unique periods across 132 rows.
- 30 periods repeat.
- `Total` is formula-derived in every data row.

## `Luz - Otros - Tabla 3`

Approximate data rows: 52.

Period range observed: `202002` through `202607`.

Likely business key: source row identity, or `(Periodo, row sequence)`. `Periodo` is almost but not fully unique.

Columns:

| Column | Apparent type | Meaning |
| --- | --- | --- |
| `Periodo` | Integer `YYYYMM` | Electricity billing period/month. |
| `Otros` | Decimal money | Other charges. |
| `Alquiler` | Decimal money | Equipment rental charge. |
| `Imp.Elec.` | Decimal rate | Electricity tax rate or factor. Open question: exact interpretation. |
| `IVA` | Decimal rate | VAT rate, observed values include `0.21`, `0.10`, and `0.05`. |
| `Peaje A` | Decimal money, with one text-like numeric value | Access/toll charge A. One value is stored as text-like data (`8.02`) and should be preserved. |
| `Peaje B` | Decimal money | Access/toll charge B. |
| `Cargo A` | Decimal money | Additional charge A. |
| `Cargo B` | Decimal money | Additional charge B. |

Structural notes:

- 51 unique periods across 52 rows.
- 1 period repeats.
- No formulas were observed in this sheet.
- The text-like numeric value in `Peaje A` matters for faithful migration. It can be normalized into a decimal value only if the original cell text/type is also preserved.

## `Pagatelia`

Approximate data rows: 191.

Period range observed: `201809` through `202604`.

Likely business key: source row identity, or `(Periodo, source row number)`. `Periodo` is not unique.

Columns:

| Column | Apparent type | Meaning |
| --- | --- | --- |
| `Periodo` | Text `YYYYMM` | Toll/payment period. |
| `Importe` | Decimal money | Per-item amount. Values may be positive or negative. |
| `Total` | Integer quantity/count | Count or multiplier. Open question: exact business meaning. |
| `Factura` | Decimal money | Invoice/billed total for the row, apparently related to `Importe` and `Total`, but historical values must not be recalculated. |

Structural notes:

- 64 unique periods across 191 rows.
- 41 periods repeat.
- Positive and negative amounts are present.
- No nulls were observed in the used data range.
- Historical Pagatelia inconsistencies are accepted and should not be investigated or corrected.

## `Nóminas - GFT report`

Approximate data rows: 151.

Period range observed: `2014-01-01` through `2026-07-01`.

Likely business key: `Periodo`, if payroll has at most one row per month.

Columns:

| Column | Apparent type | Meaning |
| --- | --- | --- |
| `Periodo` | Date-like text, first day of month | Payroll period/month. |
| `Guardias` | Nullable decimal money or quantity | On-call/guardias value. Open question: whether this is money, hours, or another payroll component. |
| `Gastos` | Nullable decimal money | Expenses/reimbursements. |
| `Dietas` | Nullable decimal money | Allowances/per diem. |
| `Bonus` | Nullable decimal money | Bonus amount. |
| `Total` | Decimal money | Payroll total. |
| `% IRPF` | Decimal percent | Income tax withholding percentage. Values are stored like `22.52`, not `0.2252`. |

Structural notes:

- `Periodo` is unique in this sheet.
- Optional component columns are sparse:
  - `Guardias`: 28 non-null values, 123 nulls.
  - `Gastos`: 16 non-null values, 135 nulls.
  - `Dietas`: 17 non-null values, 134 nulls.
  - `Bonus`: 7 non-null values, 144 nulls.
- `Total` and `% IRPF` are populated for every row.

## Relationships Between Worksheets

- `Agua` stands alone as a water invoice/period table.
- The three Gas worksheets are related by `Periodo`:
  - `Gas - Potencia` contains fixed-term detail segments.
  - `Gas - Consumo - Tabla 2` contains consumption detail segments.
  - `Gas - Otros - Tabla 3` contains taxes, rental, tolls, and additional charges.
  - A single gas period may have multiple rows in any of these components.
- The three Luz worksheets are related by `Periodo`:
  - `Luz - Potencia` contains power detail segments.
  - `Luz - Consumo - Tabla 2` contains consumption detail segments.
  - `Luz - Otros - Tabla 3` contains tax, rental, toll, and additional charge values.
  - A single electricity period may have multiple rows in the power and consumption components.
- `Pagatelia` is period-based but row-level, with many rows per period.
- `Nóminas - GFT report` stands alone as a payroll period table.

## Migration-Relevant Peculiarities

- `Periodo` should be normalized for querying, but original period values should be preserved for auditability.
- Gas and Luz require invoice/period header records plus child component rows.
- Some worksheets have no explicit invoice total column, only component totals. Historical component totals should be migrated as given.
- Formula cells should preserve at least the cached value. Preserving the formula text as source metadata is useful but should not be used to recalculate historical values.
- `Nóminas - GFT report` has meaningful nulls in optional payroll component columns.
- `Luz - Otros - Tabla 3`.`Peaje A` includes one numeric-looking value stored as text. This should be recorded as a structural peculiarity, not silently treated as an error. A record-level field for this exceptional original value is enough; no generic cell-level audit table is planned.
- Workbook row numbers should be retained because several candidate natural keys are not unique.

## Open Questions

- Should `Periodo` represent invoice issue month, consumption/service month, payment month, or a manually chosen reporting month for each provider?
- What exact units should be assigned to Gas `Consumo`, Luz `Consumo`, and payroll `Guardias`?
- What are the exact provider meanings of Gas `Imp HC`, `Canon`, `Peajes`, `Cargos`, and Luz `Imp.Elec.`, `Peaje A/B`, `Cargo A/B`?
- For future ingestion, which workbook totals should become validation targets versus only analytical fields?
