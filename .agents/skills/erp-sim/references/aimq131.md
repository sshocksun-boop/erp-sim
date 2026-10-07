# aimq131 material order details

Read this file when querying order quantities for one exact material item.
Read [Connection](connection.md) for shared transport and configuration.

```json
{
  "command": "aimq131",
  "feature_args": {"item": "ITEM-001"}
}
```

`item` is required. It accepts ASCII letters, digits, underscore, dot and
hyphen, up to 80 characters. Wildcards and other filters are unsupported.
The query reads ERP order lines for the item, not BOM components or FQC output.

Check exit zero, `ok`, `data.complete`, matching `query.item` and `data.item`,
`row_count == expected_row_count == len(rows)`, quantity totals and verified
logout. Rows use ERP field IDs; `data.columns` supplies labels. `oeb01` is the
order number, `oeb03` the line, `oeb12` ordered quantity, and `on_order` open
quantity. Preserve quantity and delivery-date source strings. `order_count`
counts unique order numbers and may be smaller than the line count.

For large results, use the top-level `output` path and inspect the saved JSON.
Do not treat a partial page, mismatched totals or failed logout as an empty result.
