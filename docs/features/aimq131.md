# aimq131: Material order quantity details

Queries order-line quantities for one exact material item. See the
[README](../../README.md) for JSON transport and shared configuration.

## Usage

Save this request as UTF-8 and pass it with `erp-sim --request FILE`:

```json
{
  "command": "aimq131",
  "feature_args": {"item": "ITEM-001"}
}
```

| Feature field | Meaning |
| --- | --- |
| `item` | Required exact material identifier |

## Query behavior

Item identifiers accept ASCII letters, digits, underscore, dot and hyphen, up
to 80 characters, matching the `abmr001` item boundary. Wildcards and additional
screen filters are unsupported. The client opens the query dialog, submits the
item, checks the server echo, and collects every declared table row across pages.

## Outputs

```json
{
  "command": "aimq131",
  "output": "outputs/material-orders.json",
  "feature_args": {"item": "ITEM-001"}
}
```

The optional top-level `output` saves the same JSON response as stdout. Rows
retain ERP field IDs and source strings; `columns` maps each ID to its label.
Common IDs are `oeb01` (order), `oeb03` (line), `oeb12` (ordered quantity),
`on_order` (open quantity), `oeb15` (delivery date text) and `oeb05` (unit).
The response includes the echoed item, description, specification, line count,
unique order count and both quantity totals. Date text is not reinterpreted.

## Result checks

Full success requires exit zero, `ok`, `data.complete`, matching query and echoed
item, `row_count == expected_row_count == len(rows)`, totals matching the rows,
and `session.logout_verified`. Incomplete pages, mismatched quantities, failed
logout or a timeout are failures, never empty successes. A complete zero-row
response requires explicit zero counts and totals from ERP.

The native capture and one authorized production prototype query each returned
31 lines; an independent comparison of their 372 cells found no differences,
and the production query verified graceful logout. Synthetic end-to-end tests
cover pagination and mismatched conditions. Production multi-page and zero-row
cases have not been observed and are outside the verified live scope.

Request the response contract with:

```json
{"command":"schema","feature_args":{"kind":"response","feature":"aimq131"}}
```
