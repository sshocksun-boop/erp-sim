# Locate and configure the command

Read this file when the CLI, JSON transport or configuration is not ready.

## Invocation

Prefer the installed CLI. For source work use the project's configured executable
(.venv/Scripts/erp-sim.exe on Windows or .venv/bin/erp-sim on POSIX).
Do not assume caller cwd is the repository. Use uv sync --locked for setup only;
do not reinstall on every query. Global installation is a separate user-requested
operation, and source edits do not update another installed version.

Submit one UTF-8 JSON object by `erp-sim --request FILE` or
`erp-sim --request -` with stdin. Close stdin after writing; EOF is required
within 10 seconds. The limit is 65536 bytes; a UTF-8 BOM is accepted.
A direct JSON argument is supported when passed as one argument. Avoid shell
string construction and Windows native-argument quoting ambiguities.

Offline discovery requests:

```json
{"command":"features"}
```

```json
{"command":"capabilities"}
```

```json
{"command":"version"}
```

Features maps program IDs and descriptions to JSON command values. Do not invent
a missing command. Old shell subcommands and flags are rejected in version 0.7.

## Connection inputs

JSON query root fields override equivalent ERP_SIM_* environment values,
explicit TOML and defaults. Omit optional fields to inherit; null is invalid.

| JSON root field | Environment |
| --- | --- |
| username, password | ERP_SIM_USERNAME, ERP_SIM_PASSWORD |
| hostname | ERP_SIM_HOSTNAME |
| config | ERP_SIM_CONFIG |
| listen_port | ERP_SIM_LISTEN_PORT |
| timeout, cleanup_timeout | ERP_SIM_TIMEOUT, ERP_SIM_CLEANUP_TIMEOUT |

Host, callback_host and telnet_port remain environment/TOML settings
(ERP_SIM_HOST, ERP_SIM_CALLBACK_HOST, ERP_SIM_TELNET_PORT).
TOML has a [connection] table; it rejects password keys. There is no automatic
.env or cwd configuration discovery. All relative paths use caller cwd,
including paths within a request file stored elsewhere.

Keep credentials out of reusable request files and logs. Prefer environment
credentials or protected stdin over inline argv credentials. The hostname is
part of ERP account-to-computer authentication; use only the authorized bound
identity and never return or copy it into shared examples.

Defaults: verified backend from packaged configuration, route-selected callback
IPv4, Telnet port 23, listener 6401, query timeout 150 and cleanup timeout 20.
Listeners must be in 6400..6500. The server must reach the callback listener;
outbound access alone is insufficient. Route selection does not authenticate.
Use an explicit reachable callback on multi-route/VPN/NAT setups when needed.

Operating center is inherited from login. No account-set selector exists.
Inspect returned account-set fields for plant-specific reporting.
