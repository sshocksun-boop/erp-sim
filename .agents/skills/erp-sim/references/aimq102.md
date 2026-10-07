# aimq102 material stock-quantity details

Read this file when querying dynamic stock quantities or per-warehouse
inventory for one exact material item.
Read [Connection](connection.md) for shared transport and configuration.

```json
{
  "command": "aimq102",
  "feature_args": {"item": "ITEM-001"}
}
```

`item` is required. It accepts ASCII letters, digits, underscore, dot and
hyphen, up to 80 characters. Wildcards and other filters are unsupported.
The query reads the aimq102 stock-detail screen, not order lines or BOMs.

Check exit zero, `ok`, `data.complete`, matching `query.item` and `data.item`,
`row_count == expected_row_count == len(rows)`, and verified logout. Rows use
ERP field IDs; `data.columns` supplies labels. `img02` is the warehouse,
`img10` the stock quantity, `img23` the usable-location flag and `img09` the
unit. Quantity fields remain source strings; `available_stock` must equal the
single-row `img10`. A verified zero-stock answer returns empty `rows` with zero
counts and `complete=true`; it is not an error. Multi-row answers stay
incomplete until verified, and unverified logout is a failure.

`projected_available_header` and `projected_available_table` are two distinct
ERP source values, not duplicates. For large results, use the top-level
`output` path and inspect the saved JSON.
