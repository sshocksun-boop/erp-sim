# aimq136 material work-in-process details

Read this file when querying work-in-process quantities per manufacturing
work order for one exact material item.
Read [Connection](connection.md) for shared transport and configuration.

```json
{
  "command": "aimq136",
  "feature_args": {"item": "ITEM-001"}
}
```

`item` is required. It accepts ASCII letters, digits, underscore, dot and
hyphen, up to 80 characters. Wildcards and other filters are unsupported.
The query reads the aimq136 WIP-detail screen, not stock, order lines or BOMs.

Check exit zero, `ok`, `data.complete`, matching `query.item` and `data.item`,
`row_count == expected_row_count == len(rows)`, and verified logout. Rows use
ERP field IDs; `data.columns` supplies labels. `sfb01` is the work order,
`sfb04` the untranslated status code, `sfb13`/`sfb15` the planned dates as
source strings, `sfb08` the production quantity, `woo_qty` the work-order WIP
quantity and `sub_qty` the subcontract WIP quantity. The three `*_total`
fields are server strings equal to the decimal row sums; `work_order_count`
counts distinct work orders.

A zero-row answer is currently returned as `INCOMPLETE_RESULT` with collected
evidence, not an empty success. Unverified logout is a failure. For large
results, use the top-level `output` path and inspect the saved JSON.
