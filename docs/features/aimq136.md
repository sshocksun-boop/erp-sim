# aimq136: Material WIP quantity details

Queries work-in-process quantities per manufacturing work order for one exact
material item. See the [README](../../README.md) for JSON transport and shared
configuration.

## Usage

Save this request as UTF-8 and pass it with `erp-sim --request FILE`:

```json
{
  "command": "aimq136",
  "feature_args": {"item": "ITEM-001"}
}
```

| Feature field | Meaning |
| --- | --- |
| `item` | Required exact material identifier |

## Query behavior

Item identifiers accept ASCII letters, digits, underscore, dot and hyphen, up
to 80 characters, matching the `abmr001`, `aimq131` and `aimq102` item
boundary. Wildcards and additional screen filters are unsupported. The client
opens the query dialog and submits the item with a **single** accept: unlike
`aimq102`, no second result-dialog accept exists, and ERP answers the echo,
the header fields, the counters and every work-order row in one message.

The result carries the echoed item, description, specification, source code,
three row-sum totals and every declared work-order row across pages.
`formonly.cnt` and `formonly.cn2` counters are verified internally (`cnt` is
the item count and must echo `1` for the exact item; `cn2` is the row count)
and are not returned. Columns keep the AUI node (visual) order; `sfb82_n`
carries `tabIndex 18` while sitting fourth on screen, so never sort columns
by tabIndex.

## Outputs

```json
{
  "command": "aimq136",
  "output": "outputs/wip.json",
  "feature_args": {"item": "ITEM-001"}
}
```

The optional top-level `output` saves the same JSON response as stdout. Rows
use stable ERP field IDs and string source values. Common IDs are `sfb01`
(work order), `sfb04` (status code, untranslated), `sfb82` (department or
vendor), `sfb82_n` (department short name, may be empty), `sfb13`/`sfb15`
(planned start/end dates as page-source strings), `sfb08` (production
quantity), `woo_qty` (work-order WIP quantity) and `sub_qty` (subcontract WIP
quantity). `work_order_count` counts distinct work orders and equals
`row_count` in the verified scope. The three `*_total` fields are server
echo strings that must equal the decimal row sums.

## Result checks

Full success requires exit zero, `ok`, `data.complete`, matching query and
echoed item, `row_count == expected_row_count == len(rows)`, verified
internal counters and totals, and `session.logout_verified`. A zero-row
answer is a plausible business result but is not yet production-verified, so
it is returned as `INCOMPLETE_RESULT` with the collected evidence instead of
an empty success. Failed logout, mismatched counters, duplicate work orders
or totals that disagree with the rows are failures, never empty successes.

The verified production scope (2026-09-29) covers two exact-item queries with
five and four single-page rows, each with verified graceful logout; the
five-row query matched a native GDC capture cell-by-cell (63 checks, no
differences). Production zero-row, wrong-item and multi-page behavior remains
unverified.

Request the response contract with:

```json
{"command":"schema","feature_args":{"kind":"response","feature":"aimq136"}}
```
