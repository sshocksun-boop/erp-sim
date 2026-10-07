# abmr001 product-structure BOM queries

Read this file for BOM requests by main item.
Read [Connection](connection.md) for shared transport and configuration.

```json
{
  "command": "abmr001",
  "feature_args": {"item": "11J20001R"}
}
```

item is required: ASCII letters, digits, underscore, dot or hyphen, at most
80 characters. Use the user's item without adding wildcards.
The flow selects BOM-sequence ordering and the ERP UTF-8 text report.

Use top-level output for the structured JSON and feature_args.report_output
for the original text report. Paths must differ and cannot overwrite input
request/configuration files. Both outputs contain business data.
Generated report URLs are not returned.

Full success requires exit zero, ok, data.complete, session.logout_verified and
component_count equal to components length. Preserve identifiers, sequences and
decimal values as strings; parent_item and level reconstruct the hierarchy.
A failed download, mismatched condition, unparsed row or broken hierarchy is an
error, not a partially successful BOM.

For the exact result contract:

```json
{"command":"schema","feature_args":{"kind":"response","feature":"abmr001"}}
```

The CLI acknowledges the report request and completes ERP cleanup before
downloading the TXT. Download has a separate 20-second absolute deadline. Wait
for the final JSON; successful logout alone does not mean the report succeeded.
A download failure can return an error with session.logout_verified=true.
