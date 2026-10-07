# abmr001: Product-structure BOM queries

Reads the ERP-generated product-structure text report for one main item.
See the [README](../../README.md) for transport and shared configuration.

## Usage

Save this JSON request to a UTF-8 file and pass it with `erp-sim --request FILE`:

```json
{
  "command": "abmr001",
  "feature_args": {"item": "11J20001R"}
}
```

| Feature field | Meaning |
| --- | --- |
| `item` | Required main-item identifier |
| `report_output` | Optional original UTF-8 text-report output path |

## Query behavior

Item identifiers accept ASCII letters, digits, underscore, dot and hyphen,
up to 80 characters. The query deliberately selects BOM-sequence ordering and
the ERP text-report format; other screen options retain ERP defaults.

After validating the returned conditions and report URL, the client acknowledges
the report request and completes ERP session cleanup before downloading the TXT.
The download runs in a disposable process with a 20-second absolute deadline,
including connection establishment and response reads. The CLI waits for report
parsing before returning; download failure retains the independently verified
logout status. The generated URL is temporary and is used immediately after cleanup.

## Outputs

```json
{
  "command": "abmr001",
  "output": "outputs/bom.json",
  "feature_args": {
    "item": "11J20001R",
    "report_output": "outputs/bom.txt"
  }
}
```

Top-level output saves the stdout JSON. Feature report_output saves the original
ERP UTF-8 report bytes. Both writes are atomic; the paths must differ and cannot
overwrite the request or selected configuration file. Both contain business data.
The generated report URL is excluded from responses.

## Result checks

Full success requires exit zero, ok, data.complete and session.logout_verified,
with component_count equal to the length of components. Source identifiers,
quantities and decimal values remain strings; parent_item and level describe
the reconstructed hierarchy.

The CLI rejects mismatched main items or ERP conditions, unparsed component rows,
broken hierarchy and unexpected report hosts/paths. The report HTTP endpoint
must be reachable. No general shell command is executed from ERP.

Request the result contract with:

```json
{"command":"schema","feature_args":{"kind":"response","feature":"abmr001"}}
```
