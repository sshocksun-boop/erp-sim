# asfi301: Production work-order creation

Creates one production work order and returns the complete number assigned by ERP.
See the [README](../../README.md) for JSON transport and shared configuration.

## Usage

Save a request such as this as UTF-8 and run `erp-sim --request FILE`:

```json
{
  "command": "asfi301",
  "feature_args": {
    "prefix": "TST01",
    "department_vendor": "V001",
    "product": "ITEM-001",
    "quantity": 42,
    "remark": "第一行\n第二行",
    "expected_manufacturing_department": "D001",
    "confirm_write": true
  }
}
```

| Feature field | Meaning |
| --- | --- |
| `prefix` | Required five-character work-order prefix |
| `department_vendor` | Required department/vendor identifier |
| `product` | Required production-item identifier |
| `quantity` | Required positive integer production quantity |
| `remark` | Required text, 1..255 characters; JSON LF newlines are supported |
| `expected_manufacturing_department` | Optional guard for the ERP-derived manufacturing department |
| `confirm_write` | Must be exactly `true`; authorizes one create submission |

## Query behavior

This command performs a write. It opens `asfi301`, selects insert, enters the
requested values, handles the related `asfp301` confirmation when present, and
sends the main form confirmation once. Node IDs are discovered from the current
AUI tree and are never copied from a previous session.

When `expected_manufacturing_department` is supplied, the driver verifies the
ERP-derived manufacturing department against it before submission. When omitted,
the ERP-derived department and its name must still be present but no particular
department identifier is required.
It also verifies the department/vendor description and product description before
continuing. A mismatch stops the run before the final create action whenever the
mismatch is observable at that point.

The create action has no automatic retry. If the action was sent but the complete
number was not received, partial data reports status `uncertain`; do not repeat the
request without separately checking whether ERP created the order.

CRLF and CR in library-created requests normalize to LF. The public JSON contract
rejects CR and control characters other than LF. The exact LF-normalized remark is
compared with the server's final form value.

## Outputs

Successful data uses `status=server_confirmed` and contains the complete work-order
number, verified final fields, product name, the visible detail-page coverage,
warnings and `persistence_readback=not_performed`. `server_confirmed` means the ERP
screen returned the number and fields; it is not an independent database readback.

The detail object distinguishes the server's total row count from rows transmitted
on the visible page. `complete=false` is allowed for this supporting table and does
not invalidate successful number creation.

## Result checks

Full command success requires exit zero, `ok=true`,
`data.status=server_confirmed`, a complete work-order number, matching
`fields_verified`, and `session.logout_verified=true`. Preserve any warnings.

If `ok=false` and `data.status=uncertain`, the main create action may already have
executed. Do not automatically retry. Examine the isolated trace and perform an
authorized readback before deciding whether another work order is needed.

Request the response contract with:

```json
{"command":"schema","feature_args":{"kind":"response","feature":"asfi301"}}
```
