# Protocol and session invariants

Read this document before changing framing, events, handshake, Telnet login,
callback handling, navigation or cleanup.

## Protocol invariants

- The application ID is the UUID formed from MD5 bytes of
  `"{" + proc_id + "}-" + feid2`. Use the exact `feid2` exported over Telnet.
- A callback must present this session's `feid` and a process challenge.
- Event sequence counters are local to each connection and start at zero.
- Frame decoding must handle arbitrary TCP, transport-frame, UTF-8 and AUI-message
  splits. A complete transport frame may still end in incomplete text or an
  incomplete AUI message; wait for another frame instead of rejecting it.
- Reject unsupported compression and malformed or incomplete protocol structures.
- AUI reconstruction is generic. Table extraction is enabled only by the feature's
  requested `key_column` and must accumulate absolute row positions across pages.
- Frontend calls may arrive before a menu form exists.
- Focus the quick-execution field before writing its program value.

## Authentication boundary

Telnet code owns negotiation, prompt-driven authentication and shell bootstrap.
Passwords must not enter traces, logs, responses, exceptions or TOML. Bootstrap is
fixed and uses the same fresh session keys as callback validation; features must
not issue shell commands.

Hostname participates in account-to-computer binding and is credential-like.
Authentication rejection must map to a stable `AUTH_FAILED` result without
repeated blind login attempts.

## Session lifecycle

`GdcSession` owns listeners, callback routing, deadlines, worker shutdown and all
socket cleanup. A `Channel` owns one callback's bytes, reconstructed AUI tree and
event counter. Channels and event sequences are independent.

Generic session order is:

```text
listen -> authenticate -> validate callback -> login -> menu -> feature
       -> close feature -> close menu -> verify Telnet/server shutdown
```

Close the feature before the parent menu. Confirm only the safe
`close_udmtree` action, never `closeall`. Socket closure alone does not prove a
normal logout. Complete feature data without verified graceful logout returns
`LOGOUT_UNVERIFIED`.

Timeout and interruption initiate bounded cleanup. Do not kill another process to
resolve a listener collision. A listener collision must return `PORT_IN_USE`, and
an incomplete or prematurely closed session must never become an empty success.

Shared session and navigation code must describe generic screen behavior only.
Concrete ERP program names, fields, ordering choices and report handling belong in
feature modules and are rejected by architecture tests.

Deferred result materialization runs only after session cleanup. Its deadline is
independent of the ERP query and cleanup budgets. Shared session code invokes the
optional driver lifecycle without interpreting business data. A failed deferred
step cannot erase verified logout or become a successful empty result.
