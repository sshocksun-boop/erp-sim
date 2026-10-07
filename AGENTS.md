# Development instructions for agents

## Project contract

- This is an AI-agent-first, noninteractive ERP CLI. Preserve
  deterministic interfaces, stable schemas, explicit state and actionable errors.
- Keep CLI composition, configuration, session orchestration, authentication,
  protocol handling and individual ERP features independent. Do not place concrete
  feature branches in shared runtime layers.
- Put each ERP program in its own feature module, schema, guide, skill reference
  and synthetic offline tests.
- Keep normal stdout to one JSON document and logs on stderr. Never serialize
  credentials, client identity, arbitrary exception text or generated report URLs.
- Imports must be inert: no sockets, captured-file reads, generated session state,
  output configuration or argument parsing at import time.
- Never commit credentials, business exports, live traces, caches, virtual
  environments or workstation-specific paths.
- README and development documentation are English. User instructions override
  these repository defaults.

## Development documentation router

Read the complete document for the task before editing that area. Do not load
unrelated development documents by default.

| Task | Required document |
| --- | --- |
| Change package layers, imports, shared runtime code, configuration or errors | [Architecture and boundaries](docs/development/architecture.md) |
| Change CLI arguments, output contracts, README, feature guides or skill syntax | [CLI and documentation ownership](docs/development/cli-and-documentation.md) |
| Add or modify an ERP program | [Feature development](docs/development/feature-development.md) |
| Change framing, events, handshake, login, callback handling or navigation | [Protocol and session invariants](docs/development/protocol-and-session.md) |
| Add tests, build packages, run live verification or commit/release changes | [Testing and release](docs/development/testing-and-release.md) |

For cross-layer changes, read every matching document. CLI contract changes that
also alter a feature require both the CLI and feature documents; protocol changes
usually require the architecture, protocol and testing documents.

## Mandatory checks

Use the project environment and keep tests independent of ERP credentials, real
orders, local captures, home folders and production availability.

```powershell
uv sync --locked
uv run python -m unittest discover -s tests -v
uv run erp-sim --request examples/features.request.json
uv run erp-sim --request examples/capabilities.request.json
uv run erp-sim --request examples/request-schema.request.json
uv build
git diff --check
```

Before committing, inspect staged changes for secrets, unrelated edits, generated
files and accidental public API changes. Never commit failing tests.
