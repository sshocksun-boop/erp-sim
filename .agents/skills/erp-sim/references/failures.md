# Failure handling

Read this file only after a nonzero exit or inconsistent response. Preserve the
exit code, `error.code`, `error.message`, query scope and logout status. Do not
infer no matching orders from a timeout, null data or an unverified response.

| Exit / error | Next action |
| --- | --- |
| `2 INVALID_ARGUMENT` | Correct the JSON request; inspect the request schema if necessary |
| `3 CONFIG_ERROR` | Check required configuration without displaying secrets |
| `4 AUTH_FAILED` | Check account/bootstrap availability; do not repeat login attempts blindly |
| `5 CONNECTION_FAILED` | Check server reachability, callback routing or the reported local I/O problem |
| `6 TIMEOUT` | Determine session/cleanup state before retrying; do not merely increase timeouts repeatedly |
| `7 PROTOCOL_ERROR` | Preserve available diagnostics and report an unsupported or changed protocol |
| `8 CONDITION_MISMATCH` | Do not present the response as satisfying the user's filter |
| `9 INCOMPLETE_RESULT` | Retain verified partial rows if useful and label them incomplete |
| `10 LOGOUT_UNVERIFIED` | Report that data may be complete but session cleanup is uncertain |
| `11 PORT_IN_USE` | Select an unused port in `6400..6500`; do not kill the existing process |
| `12 OUTPUT_ERROR` | Recover a complete captured stdout response if available; fix file/pipe handling without rerunning ERP unnecessarily |
| `70 INTERNAL_ERROR` | Report the failure and investigate implementation; do not fabricate data |
| `130 INTERRUPTED` | Check cleanup status; forced termination cannot guarantee logout |

If the caller truncated or lost stdout, first read the top-level `output` file when one
was requested. Parse errors are not business results. If data is complete but
`ok` is false, describe the remaining failure rather than marking the whole run
successful.

Retry only after a concrete cause has been corrected and a retry remains within
the authorized request. Stop when the same failure repeats or session state
cannot be established. Never switch to a guessed database, another account or
unrelated UI automation to conceal an unsupported operation.

For `asfi301`, `data.status=uncertain` means the create action was already sent but
the complete number was not verified. Never retry that request automatically.
Perform a separately authorized readback or manual check before deciding whether
another work order is needed.

For an authorized diagnostic run, set top-level verbose=true and a unique
trace_dir in the JSON request; the trace directory must not exist.
Keep stderr separate. Traces contain business data and session
identifiers; keep them local and outside version control. Do not enable traces
for routine successful calls or expose them in the final answer by default.
