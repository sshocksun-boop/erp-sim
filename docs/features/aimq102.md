# aimq102: Material stock-quantity details

Queries dynamic stock quantities and per-warehouse inventory for one exact
material item. See the [README](../../README.md) for JSON transport and shared
configuration.

## Usage

Save this request as UTF-8 and pass it with `erp-sim --request FILE`:

```json
{
  "command": "aimq102",
  "feature_args": {"item": "ITEM-001"}
}
```

| Feature field | Meaning |
| --- | --- |
| `item` | Required exact material identifier |

## Query behavior

Item identifiers accept ASCII letters, digits, underscore, dot and hyphen, up
to 80 characters, matching the `abmr001` and `aimq131` item boundary. Wildcards
and additional screen filters are unsupported. The client opens the query
dialog, submits the item, waits for the server echo to lock the field, then
confirms a second dialog accept before ERP delivers the result.

The result carries the echoed item, description, specification, nine item-master
fields, fifteen quantity fields and every declared warehouse row across pages.
`formonly.cnt` and `formonly.cn2` counters are verified internally against the
summary and stock grids and are not returned. `projected_available_header` and
`projected_available_table` keep both projected-available source strings
because ERP legitimately emits different values in the two positions.

## Outputs

```json
{
  "command": "aimq102",
  "output": "outputs/stock.json",
  "feature_args": {"item": "ITEM-001"}
}
```

The optional top-level `output` saves the same JSON response as stdout. Rows
use stable ERP field IDs and string source values. Common IDs are `img02`
(warehouse), `imd02` (warehouse name), `img03` (location), `img04` (lot),
`img23` (usable location flag), `img10` (stock quantity) and `img09` (unit).
`warehouse_count` counts distinct warehouses and can be smaller than
`row_count`.

## Result checks

Full success requires exit zero, `ok`, `data.complete`, matching query and
echoed item, `row_count == expected_row_count == len(rows)`, and
`session.logout_verified`. A single stock row must satisfy
`available_stock == img10`. A verified zero-row response requires the explicit
ERP zero echo (`cn2='0'`) and returns empty rows with zero counts. Multi-row
results are returned incomplete until production evidence covers them; failed
logout, mismatched counters or an inconsistent summary grid are failures, never
empty successes.

The verified production scope (2026-09-28) covers one single-warehouse row and
one zero-row query, each with verified graceful logout and a cell-by-cell
match against a native GDC capture for the single-row case. Production
multi-warehouse, multi-page and wrong-item behavior remains unverified.

Request the response contract with:

```json
{"command":"schema","feature_args":{"kind":"response","feature":"aimq102"}}
```
