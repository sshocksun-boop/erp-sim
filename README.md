# erp-sim

ERP protocol CLI for AI agents. Version 0.11 uses one JSON request per invocation.
Supported programs are the read-only `cxmr4103`, `abmr001`, `aimq131`, `aimq102` and
`aimq136` queries plus the explicitly confirmed `asfi301` production work-order
creation flow.

## Installation

Requires Python 3.12+. From a source checkout:

```powershell
uv sync --locked
uv run --quiet erp-sim --request examples/features.request.json
uv run --quiet erp-sim --request examples/capabilities.request.json
```

For a persistent installation, use `uv tool install .`. A released wheel can also
be installed with `uv tool install PATH_TO_WHEEL` or
`python -m pip install --user --no-deps PATH_TO_WHEEL`. The package has no
third-party runtime dependencies. `python -m erp_sim` supports the same inputs.

The maintained agent usage skill is
[.agents/skills/erp-sim/SKILL.md](.agents/skills/erp-sim/SKILL.md).
When installing it, preserve its references and agents directories and keep the
installed skill aligned with the installed software version. Changing a source
checkout does not update another installed CLI or skill.

## JSON request transport

All commands, including discovery, use JSON. Only transport and help are CLI options:

```text
erp-sim JSON
erp-sim --request request.json
erp-sim --request -
erp-sim --help
```

The first form requires the entire JSON document to arrive as ONE argument.
Shell quoting varies, especially with Windows PowerShell native executables.
Prefer a UTF-8 request file or pass bytes through stdin from a calling program.
Do not construct shell command strings from request values.

For example, save this document as `request.json`, then use
`erp-sim --request request.json`:

```json
{
  "request_version": "1",
  "command": "abmr001",
  "feature_args": {
    "item": "11J20001R",
    "report_output": "outputs/bom.txt"
  }
}
```

A programmatic caller can serialize a request without shell quoting:

```python
import json
import subprocess

request = {"command": "features"}
result = subprocess.run(
    ["erp-sim", "--request", "-"],
    input=json.dumps(request).encode("utf-8"),
    capture_output=True,
    timeout=15,
    check=False,
)
document = json.loads(result.stdout)
```

Input is limited to 65,536 bytes, encoded as UTF-8 with an optional BOM. Stdin
must reach EOF within 10 seconds; write one document and close the input pipe.
The CLI does not prompt or automatically read stdin when no arguments are given.
Unknown fields, duplicate keys, non-finite numbers, invalid Unicode, invalid
types and unsupported request versions are rejected before connecting to ERP.
Omit optional fields to inherit defaults; explicit `null` is invalid.
`request_version` defaults to `"1"`.

All relative paths resolve against the caller's working directory, including
paths inside a request file located elsewhere. Request files and selected TOML
configuration files cannot also be output targets. JSON and BOM outputs must be
different files. Structurally invalid requests do not write output files.

## Offline discovery

The following request documents require no credentials or network:

| Request | Result |
| --- | --- |
| `{"command":"features"}` | Program IDs, descriptions and JSON command values |
| `{"command":"capabilities"}` | Input fields, limits, configuration precedence, schema requests and exit codes |
| `{"command":"version"}` | Package and contract versions |
| `{"command":"schema"}` | Complete request JSON Schema |
| `{"command":"schema","feature_args":{"kind":"response","feature":"abmr001"}}` | BOM response Schema |
| `{"command":"schema","feature_args":{"kind":"response","feature":"cxmr4103"}}` | Order response Schema |
| `{"command":"schema","feature_args":{"kind":"response","feature":"aimq131"}}` | Material order-detail response Schema |
| `{"command":"schema","feature_args":{"kind":"response","feature":"aimq102"}}` | Material stock-detail response Schema |
| `{"command":"schema","feature_args":{"kind":"response","feature":"aimq136"}}` | Material WIP-detail response Schema |
| `{"command":"schema","feature_args":{"kind":"response","feature":"asfi301"}}` | Work-order creation response Schema |
| `{"command":"schema","feature_args":{"kind":"request_error"}}` | Request/discovery error Schema |

Source-checkout examples are in `examples/`. The `features` response uses
`command`, replacing the old `subcommand` property. Discovery metadata uses
schema version `"3"`; the query response contracts remain version `"2"`.
Malformed requests and discovery failures use the request-error version `"1"`,
with `ok: false`, `command` (null when not validated) and `error`. Do not apply a
feature result schema to failures rejected before request validation.

## Configure a connection

JSON query requests accept the following top-level fields:

| Field | Meaning |
| --- | --- |
| `username`, `password` | Explicit credentials; optional when configured elsewhere |
| `hostname` | Sensitive client identity reported to ERP |
| `config` | Explicit connection TOML path |
| `listen_port` | Callback listener port, 6400..6500 |
| `timeout`, `cleanup_timeout` | Positive query/cleanup budgets, at most 3600 seconds |
| `trace_dir`, `verbose` | New local diagnostics directory and boolean logging switch |
| `output` | Atomically save the same JSON emitted on stdout |

`output` is also allowed for discovery. Connection and diagnostics fields are
rejected for discovery instead of silently ignored. Business inputs and
feature-specific outputs belong in `feature_args`.

Precedence: explicit JSON request > `ERP_SIM_*` environment > explicit TOML >
defaults. Existing environment and TOML setup remains supported. Host, callback
host and Telnet port continue to be environment/TOML settings.

| Environment variable | Meaning/default |
| --- | --- |
| `ERP_SIM_USERNAME`, `ERP_SIM_PASSWORD` | Credentials when omitted from the request |
| `ERP_SIM_HOST` | Optional ERP server override; verified backend default is defined in config.py |
| `ERP_SIM_CALLBACK_HOST` | Local callback IPv4; otherwise detected from the route to the server |
| `ERP_SIM_TELNET_PORT` | Default 23 |
| `ERP_SIM_LISTEN_PORT` | Default 6401 |
| `ERP_SIM_TIMEOUT`, `ERP_SIM_CLEANUP_TIMEOUT` | Defaults 150 and 20 seconds |
| `ERP_SIM_HOSTNAME` | Client identity; defaults to the OS hostname |
| `ERP_SIM_CONFIG` | Explicit TOML path when request.config is absent |

Copy `connection.example.toml` to an ignored local file for non-secret settings.
TOML uses a `[connection]` table and rejects password keys. There is no automatic
.env or working-directory configuration lookup.

Request credentials are optional; prefer process environment for reusable
request files. An inline JSON password can appear in shell history or process
arguments. Stdin avoids putting the request in argv, but callers must still keep
their own logs and files free of secrets. Credentials, client identity and
generated report URLs never belong in public responses.

The server must reach the callback IPv4 listener. Route detection does not
authenticate. Supply a reachable explicit callback address on multi-route/VPN/NAT
systems when necessary. The operating center comes from the authorized account.
For orders, inspect each row's account-set fields instead of assuming a plant.
Each query uses one session; concurrent sessions require distinct listener ports.

`asfi301` is a write operation. Its request requires `confirm_write=true`, submits
one work order, and never retries automatically. If the response is uncertain,
verify the ERP state before issuing another request. See
[the asfi301 feature guide](docs/features/asfi301.md).

## Outputs and failures

Stdout contains exactly one JSON document; logs go to stderr. Only `--help` is
human-readable. Keep stdout, stderr and the process exit code separate.
For queries, check exit zero, `ok`, `data.complete`, matching conditions and
`session.logout_verified` before reporting success. For `asfi301`, use the checks
listed in its feature guide; its supporting detail table may be paginated.

Allow at least `timeout + cleanup_timeout + 25` seconds for query subprocesses
(195 seconds with defaults), including stdin ingestion. For `abmr001`, add
20 seconds for the bounded report download after ERP cleanup (215 by default). Do not retry automatically
after uncertain authentication, partial results or unverified logout.
Validated requests can save configuration/runtime failures to `output`.
A failed atomic write preserves the existing target.

## Migration from 0.6

This is an intentional breaking CLI change; there is no legacy parser.

| Former input | JSON input |
| --- | --- |
| ERP program subcommand | `command` |
| Root credential/configuration/diagnostic flags | Top-level fields using snake_case |
| `--pattern`, `--from`, `--to` | `feature_args.pattern`, `date_from`, `date_to` |
| `--item`, `--report-output` | `feature_args.item`, `report_output` |
| `--output` | Top-level `output` |
| `--format json` | Removed; responses are always JSON |

Update scripts, scheduled callers and installed skill copies together with the
CLI. Request version 1 and query response version 2 are independent.
The experiment changes input composition only; it makes no new production ERP
compatibility claim.

## Feature usage

- [cxmr4103 sales-order queries](docs/features/cxmr4103.md)
- [abmr001 product-structure BOM queries](docs/features/abmr001.md)
- [aimq131 material order-quantity details](docs/features/aimq131.md)
- [aimq102 material stock-quantity details](docs/features/aimq102.md)
- [aimq136 material WIP quantity details](docs/features/aimq136.md)
- [asfi301 production work-order creation](docs/features/asfi301.md)
