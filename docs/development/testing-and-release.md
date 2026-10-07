# Testing and release

Read this document before adding tests, building packages, performing live
verification, committing or releasing changes.

## Package versioning

Use `MAJOR.MINOR.PATCH` for the package version:

- Increment MAJOR for a breaking change to a supported interface or behavior;
  reset MINOR and PATCH to zero.
- Increment MINOR for a compatible feature update or nonbreaking refactor;
  reset PATCH to zero.
- Increment PATCH for a bug fix or documentation-only update.

When a change includes multiple categories, use the highest applicable increment.
Keep `pyproject.toml`, the `erp-sim` entry in `uv.lock`, and
`src/erp_sim/__init__.py` in sync. The `version` and `capabilities` commands must
report that same package version. Request and response schema versions are
separate public contracts; follow the CLI documentation for their changes.

## Local checks

```powershell
uv sync --locked
uv run python -m unittest discover -s tests -v
uv run erp-sim --request examples/features.request.json
uv run erp-sim --request examples/capabilities.request.json
uv run erp-sim --request examples/request-schema.request.json
uv build
git diff --check
```

The runtime has no third-party dependencies. Development-only schema validation is
locked separately. Package resources must resolve through `importlib.resources`
independently of the working directory.

Tests must not depend on developer captures, ERP credentials, real orders, a home
directory or a reachable production server. Mock time and networking where useful,
but keep assertions tied to public behavior and protocol invariants.

## Required coverage

Maintain tests for byte fragmentation, UTF-8 boundaries, handshake vectors, event
escaping, authentication prompts, login/menu transitions, output isolation,
configuration precedence, JSON transport, strict request types and schema conformance, multiple-table pagination,
condition mismatch, empty results, deadlines, failed cleanup, state isolation,
schemas, architecture boundaries and documentation structure.

Every logical module needs meaningful success and failure tests. A change that
fixes a regression must add or strengthen a test that would have caught it.

## Live verification

Live checks are not unit tests. Use only explicitly authorized operations, fresh
trace directories and bounded deadlines. Write checks require an exact reviewed
request, a single submission and no automatic retry. Record only non-sensitive
counts or conclusions in committed documentation. Never commit live responses,
raw traces, report URLs, credentials or actual bound client hostnames.

Do not retry blindly after authentication, timeout or uncertain logout. Determine
session state and correct a concrete cause first.

## Commit and release discipline

Run the complete suite before every commit. Inspect the staged diff for secrets,
unrelated edits, generated files and accidental public API changes. Use imperative,
scoped Conventional Commit messages and keep each commit independently testable.

Update package and lock versions together for a release. Use a major schema
version bump for incompatible response changes. Build both wheel and source
distribution, verify ignored caches are absent, and test an isolated wheel install
when packaging behavior changes.

## Historical offline baseline (2026-09-16)

- Python 3.12 on Windows: 74 offline unit, schema, documentation, architecture and
  synthetic end-to-end tests pass.
- Architecture tests reject higher-layer imports and concrete ERP program names in
  shared runtime layers.
- Documentation tests enforce feature-guide structure and shared request-field ownership.
- Version `0.6.0` wheel and source distribution build successfully.

## Historical live baseline (2026-09-11)

- A standalone `S1702*` query for 2026-09-10 through 2026-09-11 returned 74 of 74
  details across 42 orders with verified conditions and normal logout.
- A nonexistent pattern returned an explicit complete zero-row result and normal
  logout.
- Both responses passed the published schema; an independent reconstruction
  matched all 3,922 source cells.
- The wheel and source distribution built successfully, and an isolated Python
  3.12 environment installed the wheel without network access or `uv`.
- With both host variables absent, the CLI selected the backend default and the
  callback IPv4 from the OS route, then logged out normally.
- An explicitly bound hostname completed a live empty query. An unbound neutral
  placeholder reached ERP and was rejected with `azz-910`, confirming that client
  hostname participates in computer binding.

Historical results document past validation only and do not guarantee current ERP
data or availability.

## JSON request migration (0.7)

The CLI no longer accepts legacy subcommands or flags. Offline tests exercise
JSON argv, file and stdin inputs, EOF timeout, malformed/oversized input,
secret-safe errors, protected input paths, configuration precedence and input
schema conformance. Existing feature end-to-end cases now enter through JSON;
orders use stdin and BOM uses a UTF-8 BOM request file.

This migration does not authorize or perform a production ERP run.

Verification on Windows / Python 3.12, 2026-09-21:

- All 86 offline tests pass, including both features' synthetic end-to-end cases.
- Locked environment sync and JSON features/capabilities/request-schema checks pass.
- Version 0.7.0 wheel and source distribution build; packaged request, error and
  feature schemas are present, and archive inspection finds no capture/cache files.
- A separate environment installed the wheel offline without dependencies and
  passed seven discovery requests plus legacy-syntax rejection outside the checkout.
- No production ERP query or new native-capture comparison was performed.

## asfi301 integration (0.8)

The implementation is based on the 2026-09-18 native `asfi301` capture and the
separate 2026-09-21 explicitly authorized production validation. That validation
submitted one work order, received a server-assigned complete number and matching
final fields, observed 26 declared detail rows with 10 on the visible page, and
verified normal logout. Raw traces and business values remain outside this package.

Package verification on Windows / Python 3.12 includes 99 offline tests, a
synthetic end-to-end write with multiline remarks and one create action, response
schema checks, wheel/source builds, archive inspection and an isolated offline
wheel install. These packaging checks do not submit another production request.

## Synthetic end-to-end tests

Each feature owns a separate end-to-end test file, including its synthetic data,
server workflow and result assertions:

- `tests/test_e2e_cxmr4103.py` covers order queries.
- `tests/test_e2e_abmr001.py` covers product-structure BOMs.
- `tests/test_e2e_aimq131.py` covers material order-quantity details.
- `tests/test_e2e_asfi301.py` covers one confirmed work-order creation.

`tests/e2e_support.py` contains common subprocess execution and envelope checks.
`tests/e2e_backend.py` contains shared Telnet, DCP and HTTP transport and session
orchestration; it receives the feature workflow rather than branching on program
names. Add future features in their own test files instead of extending a central
feature switch.

The tests launch an isolated CLI subprocess from a temporary working directory
using real loopback sockets without mocking the CLI, session, authentication,
protocol or feature drivers. All identities, orders and reports are synthetic;
these tests do not connect to production ERP or read developer captures.

```powershell
uv run python -m unittest tests.test_e2e_cxmr4103 -v
uv run python -m unittest tests.test_e2e_abmr001 -v
uv run python -m unittest tests.test_e2e_asfi301 -v
```

- `test_cxmr4103_end_to_end` verifies login, session-key/app-id handshake, frontend
  calls, program launch, submitted and echoed conditions, overlapping result pages,
  a second unrelated table, omitted empty values, exact rows and counts, UTF-8
  labels, stdout/file equality, response schema and graceful logout.
- `test_abmr001_end_to_end` verifies the same session workflow plus main-item,
  sort and output selection, real HTTP report retrieval, component hierarchy,
  notes, string quantities, original report bytes, JSON output and response schema.
- `test_asfi301_end_to_end_submits_once_and_returns_number` verifies validated
  inputs, a multiline remark, the single create action, server-assigned number,
  final field echoes, paginated supporting detail, response schema and logout.
- Each feature also has a condition-mismatch end-to-end case. It must return exit
  code 8 with no accepted data and still log out normally. The BOM case must not
  download or save a report after rejected conditions.

The synthetic server asserts both feature exit and menu exit before sending DCP
and Telnet EOF. Tests require `session.logout_verified`, not merely closed local
sockets. A CLI invocation has a 40-second query deadline, 5-second cleanup deadline
and 60-second subprocess timeout; server reads and worker cleanup are also bounded.

Run these tests serially. They select a free callback port in 6400..6500. The BOM
peer also requires free loopback HTTP port 80 because the current feature accepts
only that report port; an occupied port fails explicitly and is never reclaimed.
These checks validate integration against a synthetic protocol peer. Historical
or newly authorized production runs remain separate evidence of ERP compatibility.

## What synthetic tests establish

A passing synthetic test establishes that the packaged client layers work together
for the scripted messages and outcomes. It does not establish that the synthetic
peer faithfully implements production ERP, or guarantee production success.
Although the peer does not import runtime protocol implementations, its scripts
are hand-authored and could share an incorrect protocol assumption with the client.
Client event checks currently require substrings rather than implementing a full
independent server-side event parser. There is no automatic conformance comparison
between this peer and native GDC traces or ERP exports.

Production validation requires independent evidence for the exact client revision
and identified ERP environment:

1. Review the workflow against native GDC captures and server-originated reports;
   retain trace provenance outside the package, and independently check field and
   event semantics rather than deriving expected behavior from client code alone.
2. After explicit authorization, run bounded CLI operations against real ERP.
   Queries should include representative pagination/BOM hierarchy and empty/error
   cases. A write check must use one reviewed request and no automatic retry.
   Verify server-echoed inputs, complete counts or assigned identifiers, output
   schemas and graceful logout with callback and Telnet server EOF evidence.
3. Compare returned rows and component fields against an independent native export
   for the same query and business snapshot. Record differences and uncovered
   cases; schema validity or internal counts alone are not a data correctness check.
4. Keep the default offline suite credential-free. Keep live checks separate and
   opt-in, with fresh evidence directories. Revalidate after relevant client or ERP
   changes; a successful live run supports only the environment and cases tested.

Synthetic integration coverage alone adds no native-trace conformance or
production evidence and does not upgrade historical live evidence into proof for
a later package revision.

## aimq131 integration (2026-09-28)

The implementation follows a native GDC capture and one explicitly authorized
read-only production query made by an external prototype before migration.
The production query returned 31 of 31 lines and verified graceful logout.
All 372 captured cells matched the earlier native result. Raw traces, the
queried material identifier and business rows remain outside this package.

The package exposes an exact-item JSON query and a version 2 response with the
same table shape as `cxmr4103`. Synthetic end-to-end tests cover pagination,
condition mismatch and graceful logout; offline feature tests cover zero rows,
missing rows, invalid quantities and total mismatches. Production multi-page
and zero-row behavior remains unverified. No second production query was made
after the package migration; packaged CLI composition was checked offline.

## aimq102 integration (0.10.0, 2026-09-28)

The implementation follows the 2026-09-28 native `aimq102` capture and three
explicitly authorized read-only production queries made by an external
prototype before migration: one single-warehouse row verified cell-by-cell
against the native capture (45 checks, no differences), one zero-stock result
with the explicit `cn2='0'` echo, and one additional single-row query. All
three verified graceful logout. The same evidence fixed the counter semantics
(`cnt` = item count, `cn2` = stock-row count), the zero-row success path and
the numeric comparison for grid quantities that rescale decimals to the column
width. Raw traces, credentials and business rows remain outside this package.

The package exposes an exact-item JSON query and a version 2 flat response
(header fields, fifteen quantity strings, one table contract, `warehouse_count`).
Synthetic end-to-end tests cover the two-accept workflow, single-row success,
verified zero rows, condition mismatch and graceful logout; offline feature
tests add counter mismatch, summary text/quantity mismatch, decimal-scale
tolerance, invalid quantities, pagination progress and the incomplete
multi-row result. Production multi-warehouse, multi-page and wrong-item cases
remain unverified. No production query was made after the package migration;
packaged CLI composition was checked offline.

## aimq136 integration (0.11.0, 2026-09-29)

The implementation follows the 2026-09-29 native `aimq136` capture and two
explicitly authorized read-only production queries made by an external
prototype before migration: one five-row single-page result verified
cell-by-cell against the native capture (63 checks, no differences) and one
four-row single-page result on a second material. Both verified graceful
logout, and both cross-checked the work-order WIP total against the
independent `aimq102` header evidence for the same materials. The single-
accept workflow (submitting the item runs the query), the `cn2` row counter,
the `cnt == '1'` item counter and the three row-sum totals are production
evidence; raw traces, credentials and business rows remain outside this
package.

The package exposes an exact-item JSON query and a version 2 flat response
(header fields, three total strings, one table contract, `work_order_count`).
Synthetic end-to-end tests cover the single-accept workflow, paginated
success, condition mismatch and graceful logout; offline feature tests add
counter mismatches, total mismatch, missing totals, invalid quantities,
duplicate work orders, pagination progress and the fail-closed zero-row
result. Production zero-row, wrong-item and multi-page behavior remains
unverified. No production query was made after the package migration;
packaged CLI composition was checked offline.
