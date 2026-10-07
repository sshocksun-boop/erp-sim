# Architecture and boundaries

Read this document before changing package layers, imports, shared runtime code,
configuration or error handling.

## Layer model

Treat the package as ordered layers. A higher layer may compose lower layers, but
lower layers must not import or branch on a higher layer's business concepts.

| Layer | Files | Owns |
| --- | --- | --- |
| Composition and public CLI | `__main__.py`, `cli.py` | JSON request transport, command selection, response envelopes, discovery and atomic output |
| Configuration and errors | `config.py`, `errors.py` | Configuration precedence, validation, credential boundaries and stable errors |
| Session orchestration | `session.py`, `navigation.py` | Socket lifecycle, callback routing, generic login/menu/logout and cleanup |
| Authentication and protocol | `auth/`, `protocol/` | Telnet authentication, bootstrap, framing, handshakes, AUI reconstruction and events |
| Business features | `features/` | One ERP program's inputs, event sequence, parsing and verified result |
| Public data contracts | `resources/` | Packaged request, error and feature response JSON Schemas |
| User and agent documentation | `README.md`, `docs/`, `.agents/skills/erp-sim/` | Shared usage, feature usage and agent operating rules |
| Verification | `tests/` | Offline tests mirroring logical layers and public contracts |

`request.py` owns bounded JSON transport and schema-based structural validation.
It must not import concrete drivers, sessions or configuration. Only cli selects
and executes a feature. Input-schema business metadata is allowed in resources.

The intended dependency graph is:

```text
cli -> request + config + errors + concrete features + session + resources
request -> errors + resources
session -> auth + navigation + protocol + errors
features -> navigation helpers + protocol + errors
navigation -> protocol + errors
auth -> protocol/config as required
protocol -> its own package + errors
```

## Enforced boundaries

- `cli.py` is the composition root and the only layer that selects a concrete
  feature implementation. Discovery metadata may also live there.
- `session.py` accepts a structural feature driver. It must not import concrete
  features or branch on ERP program IDs, item fields, order fields or report formats.
- `navigation.py` owns only screens shared by ERP programs. Feature-specific fields,
  buttons and conditions belong in `features/<program>.py`.
- Feature drivers use `Channel` and generic navigation/protocol helpers. They must
  not authenticate, create listeners, own sockets, implement logout or duplicate
  session cleanup.
- `auth/` and `protocol/` must not import `features/`, `session.py` or `cli.py` and
  must not contain ERP program IDs or business field semantics.
- Configuration loading belongs in `config.py`. Do not read environment variables,
  TOML or credentials directly from feature, session, navigation or protocol code.
- Stable user-facing errors belong in `errors.py`. Do not leak arbitrary exception
  strings, credentials, host identity or report URLs into public responses.
- Shared code is extracted only when semantics are truly identical across features,
  not merely similar in one trace or capture.

Architecture tests in `tests/test_architecture.py` reject higher-layer imports and
concrete ERP program names in shared runtime modules. Extend those tests when a
new shared layer or dependency rule is introduced; do not weaken them to bypass a
boundary violation.

## Module ownership

| Module | Responsibility |
| --- | --- |
| `protocol/dcp.py` | Incremental frame decoder and generic AUI reconstruction |
| `protocol/events.py` | Escaped events and per-channel event counters |
| `protocol/handshake.py` | Fresh session keys, challenge response and file announcements |
| `auth/telnet.py` | Incremental Telnet negotiation and prompt-driven authentication |
| `auth/bootstrap.py` | Fixed shell bootstrap using the same session keys |
| `navigation.py` | Login acceptance, frontend calls, menu launch and safe logout |
| `session.py` | Socket lifecycle, callback routing, deadlines and cleanup |
| `features/base.py` | Structural feature driver interface |
| `features/cxmr4103.py` | Order inputs, event ordering, pagination and verification |
| `features/abmr001.py` | BOM inputs, report validation, parsing and hierarchy verification |
| `features/aimq131.py` | Exact-item order-detail navigation, pagination and quantity verification |
| `features/asfi301.py` | Confirmed single-work-order input, guarded field validation and final-number verification |
| `config.py` | Configuration precedence, validation and credential boundaries |
| `request.py` | Bounded JSON transport and request validation |
| `cli.py` | JSON request composition, versioned responses, exit codes and atomic output |
| `resources/result.schema.json` | Public `cxmr4103` response schema |
| `resources/abmr001.schema.json` | Public `abmr001` response schema |
| `resources/aimq131.schema.json` | Public `aimq131` response schema |
| `resources/asfi301.schema.json` | Public `asfi301` response schema |

Mutable state belongs to a session, channel or feature instance. Do not wrap an
older simulator in a subprocess or import files from outside this project.

## Configuration boundary

`ERP_SIM_HOST` defaults to the verified backend `192.168.0.160`.
`ERP_SIM_CALLBACK_HOST` is optional; without it, `config.py` selects the OS IPv4
route to the effective ERP host before authentication. Route detection must remain
deterministic under mocks and free of ERP login side effects. Never fall back to
hostname lookup or an arbitrary first network adapter.

Configuration precedence is JSON request override, environment, explicit TOML, then
defaults. Passwords remain prohibited in TOML. Client hostname is credential-like
identity and must not appear in documentation examples, responses or diagnostics.
