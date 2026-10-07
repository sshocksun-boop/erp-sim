# Create one asfi301 work order

Use only when the user explicitly authorizes creating a production work order.
Read the current request schema or feature guide for fields. The JSON request must
contain `confirm_write: true`; the CLI sends the final create action once and does
not retry it.

Multiline remarks use LF in the JSON string, for example `"line one\nline two"`.
The normalized value is checked against the final ERP form.
`expected_manufacturing_department` is optional. When supplied it guards the
ERP-derived manufacturing department; when omitted the derived identifier and
name must still be present.

Full success requires exit zero, `ok=true`, `data.status=server_confirmed`, matching
verified fields, a complete work-order number, and verified logout. This confirms
the server UI response, while `persistence_readback=not_performed` states that no
independent database readback occurred.

If the response status is `uncertain`, the create action may already have executed.
Do not repeat it. Preserve the trace and perform an authorized lookup before taking
further action.
