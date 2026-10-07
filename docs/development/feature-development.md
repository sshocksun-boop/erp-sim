# Feature development

Read this document before adding or changing an ERP program.

## Feature driver contract

Implement the `Feature` protocol in a separate `features/<program>.py` module.
Declare `program` and `key_column`, maintain per-instance `done` and `result`, and
implement `advance(channel)`.

A deferred driver may additionally expose `erp_done` and `finish()`. Set
`erp_done` only after acknowledging the final ERP interaction. This starts normal
cleanup without claiming a complete result. After connections are released, the
session invokes `finish()` if no earlier execution error occurred, even when
logout could not be verified. That method must bound its own work, assign the
verified result and set `done`; errors preserve the independent logout status.

Use `channel.tree`, `channel.quiet()`, `channel.emit()` and `channel.send()` rather
than managing sockets or authentication. Use generic navigation helpers for
shared control lookup. Keep every business field, ERP choice, event order, parser
and result verification rule in the feature module.

Use a string `key_column` only when the feature consumes a paginated ERP table.
Use `None` for non-table flows such as generated reports. Do not teach `AuiTree` or
the session layer about a concrete feature merely to support a different result
shape.

The session composes login, menu launch, one fresh feature driver and logout. Reuse
settings, never an already-run driver. Multi-feature reuse of one authenticated
connection is not implemented and must not be claimed.

## Required artifacts

Every feature must provide:

1. A dedicated feature module and validated query input object.
2. A JSON command named after the ERP program ID with a request-schema branch.
3. A packaged response JSON Schema.
4. Feature registration in discovery and capabilities.
5. A focused `docs/features/<program>.md` guide.
6. A focused skill reference and routing entry.
7. Synthetic offline tests for success, malformed input, protocol mismatch,
   incomplete data and feature-specific safety rules.

Do not expose generic business actions to avoid implementing a proper feature
boundary. Live verification is supplementary and requires explicit authorization;
it never replaces deterministic fixtures.

## Acceptance checklist

Before accepting a new or changed feature, verify all of the following:

1. Shared request fields remain top-level and are rejected in feature_args.
2. Feature request fields contain only business inputs and unique outputs.
3. No concrete feature branch or name was added to session, navigation, auth or
   protocol code; only the CLI composition root selects the feature.
4. The feature guide uses the standard section order and does not repeat root
   credential, connection, timeout, diagnostic or shared output tables.
5. README, CLI help, capabilities, skill references and tests use the same syntax.
6. Query conditions and every returned record, or write inputs and the returned
   server identifier, are verified before success.
7. Query data completeness or write confirmation, plus verified graceful logout,
   is required.
8. Offline tests cover behavior, failure paths, schema validation, state isolation
   and secret non-disclosure.

## Current feature invariants

For `cxmr4103`, send the start-date value with end-date focus, then send the
end-date value with the accept action. Select the result table by `oea01_1`, never
the first `DisplayArray`. Validate returned conditions and every row's pattern and
date. Verify absolute row-index coverage; the first page is not completion. A
verified zero-row result is distinct from missing or unverified data.

For `abmr001`, retain BOM-item ordering and ERP text output. Validate the requested
main item, selected conditions, report host/path, every parsed component row and
the hierarchy. Never execute a general shell command returned by ERP. The
structured component count must equal the component array length.

For `aimq131`, use an exact item identifier, enter the query dialog before
submitting it, verify the server item echo, select the `s_sr` DisplayArray by
its table name and field IDs, then cover every absolute row position. Verify
line keys and both quantity totals before reporting completion. The current
live evidence covers one 31-line page; production multi-page and zero-row cases
remain unverified.

For `aimq102`, submit the exact item with the first dialog accept, wait for the
server echo to lock the field, then send the second result-dialog accept. Select
the `s_img` DisplayArray by table name, verify the `cnt`/`cn2` counters against
the summary and stock tables separately (`cnt` counts items, `cn2` counts stock
rows including the explicit `'0'` zero echo), compare summary quantity columns
numerically because the grid rescales decimals to its column width, and keep
both projected-available source strings. A single row must satisfy
`available_stock == img10`; verified zero rows are complete, while multi-row
results stay incomplete until production evidence covers them.

For `aimq136`, submit the exact item with one single accept; submitting the
condition already runs the query and no second accept exists. Select the `s_sr`
DisplayArray by table name, keep columns in AUI node order (`sfb82_n` carries
`tabIndex 18` in the fourth visual position), verify `cn2` against the table
size and `cnt == '1'` for the exact item, require distinct `sfb01` work orders
and the three row-sum totals (`sum_qty`/`sum_woo`/`sum_sub`) to equal the
decimal row sums. Zero-row answers are not yet production-verified and must
fail closed as `INCOMPLETE_RESULT` with the collected evidence.

For `asfi301`, require the explicit `confirm_write=true` request guard, validate
derived department/vendor and product values before submission, compare the
manufacturing department to the optional expected value when supplied, and emit
the final create action once. Set the result to uncertain immediately before submission so
transport failures cannot imply a safe retry. Accept success only after ERP returns
the complete number and all final fields match. Supporting detail pagination does
not replace number and field verification.
