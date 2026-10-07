---
name: erp-sim
description: "Query ERP orders, material order, stock or work-in-process quantities, or BOMs and create one explicitly authorized asfi301 production work order through the erp-sim JSON CLI. Use for cxmr4103, aimq131, aimq102, aimq136, abmr001, asfi301, result delivery, and erp-sim failures. Do not use for FQC quantities, direct database access, generic ERP writes, or simulator development."
---

# ERP operations with erp-sim

Use the packaged JSON-request CLI for authorized ERP operations.
Let it manage login, pagination and logout. Do not recreate the GDC UI workflow.

## Choose the required detail

Read only the reference needed for the current step.

| Need | Read |
| --- | --- |
| CLI transport, installation or connection setup | [Connection](references/connection.md) |
| Order dates, patterns or supported filters | [cxmr4103](references/cxmr4103.md) |
| Material order quantities by exact item | [aimq131](references/aimq131.md) |
| Material stock quantities by exact item | [aimq102](references/aimq102.md) |
| Material work-in-process details by exact item | [aimq136](references/aimq136.md) |
| BOM by main item | [abmr001](references/abmr001.md) |
| Create one production work order | [asfi301](references/asfi301.md) |
| Fields, JSON or table delivery | [Results](references/results.md) |
| Failure, timeout or uncertain logout | [Failures](references/failures.md) |

## Execute a request

1. Identify the ERP program and required inputs from the user and context.
   Resolve relative dates in Asia/Shanghai; example dates are never defaults.
   Ask only for required information that cannot be inferred.
2. Locate the installed CLI. Submit `{"command":"features"}` when implemented
   programs are unknown; use its `command` field. For an unfamiliar installation,
   submit `{"command":"capabilities"}` once. Both are offline.
3. Serialize one request object. Prefer `erp-sim --request -` with UTF-8 bytes on
   stdin and close the pipe; alternatively use `--request FILE`. A direct JSON
   argument must arrive as one argument without shell interpolation. Old
   subcommands and flags are unsupported. Capture stdout, stderr and exit code
   separately. Budget timeout + cleanup_timeout + 25 seconds (195 by default);
   add 20 seconds for abmr001 post-cleanup report download (215 by default).
4. Parse the single stdout JSON document. Full query success requires exit zero,
   ok, data.complete, matching query conditions and session.logout_verified.
   For order and material-detail queries, compare returned and expected counts.
   For BOM, compare
   component_count to the components array. For `asfi301`, require
   data.status=server_confirmed, the complete number, matching verified fields and
   verified logout. Null/error/partial data is not an empty successful result.
5. Return the requested format without silently omitting rows or substituting an
   old export. Preserve dates, query timestamp and order/detail count distinctions.

## Boundaries

Use only supported features and conditions. `cxmr4103` and `abmr001` are read-only.
`aimq131`, `aimq102` and `aimq136` are read-only. `asfi301` creates exactly one work order and requires explicit authorization and
`confirm_write=true`; never retry it automatically. Other ERP writes are unsupported.

Reuse authorized environment/TOML configuration; optional JSON top-level fields
override it. Never put passwords in TOML, responses, chat or committed requests.
A positional JSON password can appear in history and process arguments.

Each invocation owns one session; concurrent calls need distinct listener ports.
Do not terminate another process to free a port. On failure consult the failure
reference before retrying, especially after uncertain authentication or logout.
