# CLI and documentation ownership

Read this document before changing request input, output contracts, README,
feature guides or skill syntax.

## Request ownership

Every operation is one JSON request. Only a positional JSON argument,
`--request FILE`, `--request -` and `--help` belong to argparse.
Do not reintroduce legacy subcommands or feature flags.

Top-level request fields own shared connection, authentication, session,
diagnostic and response options. `feature_args` owns business inputs and outputs
unique to a feature. The request transport never selects or executes a driver;
`cli.py` remains the composition root.

`resources/request.schema.json` is the input field definition source.
`request.py` reads it without caching mutable requests, checks its supported
schema vocabulary, strict types and dates, and returns a validated object.
Tests cross-check acceptance against the standard JSON Schema validator.
When adding a schema keyword, update the runtime validator and conformance tests.
Cross-field business rules such as date ordering remain in query objects.

Unknown properties, duplicate keys, explicit nulls, invalid UTF-8, unsupported
versions and non-finite numbers are errors. Do not echo raw input, unknown key
names, values, file paths or arbitrary exception representations in errors.
Limit input to 65536 bytes; stdin must reach EOF within 10 seconds.
Paths resolve against caller cwd. Reject output aliases of the request/config
files and aliases between JSON and BOM outputs before enabling output writes.
Structurally invalid requests must not write the requested output path.

JSON overrides environment, explicit TOML and defaults. Keep environment and
TOML configuration; passwords remain prohibited in TOML.
Discovery accepts only command, request_version, output and its feature_args.
It must never load credentials or perform route detection.

## Public response contract

- Stdout is one JSON document; logs go to stderr; only help is human-readable.
- Query responses retain schema version 2, source string values, verified
  conditions/completeness/logout and existing exit codes.
- Features/capabilities/version metadata use schema version 3.
- Requests use version 1 (default when omitted); request/discovery errors use
  the separately packaged request-error schema version 1.
- Feature discovery exposes a JSON `command`, not a shell subcommand.
- Schema discovery defaults to the request schema. Response selection requires
  kind=response and a feature; other kinds reject feature.
- Atomic output preserves existing targets on failure.

Use package versions for CLI releases; bump a response schema's major version
only when that response changes incompatibly. Input and response versions are
independent. Never serialize credentials, client identity or report URLs.

## Documentation ownership

README owns installation, transport, configuration, common fields, versions and
migration. Feature guides own business inputs, unique outputs and result checks,
in this order: Usage, Query behavior, Outputs, Result checks.
Use fenced JSON request examples that can be checked by the parser.
Do not duplicate connection/credential tables in feature guides.

Development documentation and AGENTS checks must invoke the new JSON transport.
Keep historical verification results explicitly historical.

## Skill contract

Maintain the English usage skill under `.agents/skills/erp-sim/`.
Its shared references own transport, connection, results and failures; feature
references own business requests. Update affected references, validate links and
check examples against the packaged input schema.
Do not update a globally installed skill or CLI merely by changing the checkout.
