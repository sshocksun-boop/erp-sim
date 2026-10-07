# Reported MAC address and login (2026-09-14)

## Code analysis

The simulator does not read the physical adapter MAC address. In
`src/erp_sim/protocol/handshake.py`, `client_greeting()` always reports
`hw-addr   =00-00-00-00-00-00` inside DCP `clientInfo`.

Telnet authentication uses the configured account and password. The shell
bootstrap exports the callback endpoint and two fresh session identifiers.
`SessionKeys` uses UUID v4; `app_id()` hashes the server process identifier and
`feid2`. Neither calculation uses the MAC address. The supported frontend
environment call returns `COMPUTERNAME`, not a MAC address.

These client-side facts do not establish what the server validates. A live
comparison is required to test acceptance of a different reported MAC.

## Live comparison

Two sequential sessions used the same settings object, including credentials,
backend, callback address, hostname, listener port and deadlines. Both queried
the same deliberately nonexistent order pattern for 2026-09-14. Each session
generated fresh session identifiers and received fresh server process challenges,
as normal authentication requires.

An isolated diagnostic wrapper changed only the `hw-addr` bytes returned by
`client_greeting()`. It asserted that replacing those bytes back reproduced the
original greeting exactly. No production code or Windows adapter setting changed.

| Case | Reported MAC | DCP greetings | Complete query | Rows | Verified logout | Error |
| --- | --- | --- | --- | --- | --- | --- |
| A | `00-00-00-00-00-00` | 3 | Yes | 0 | Yes | None |
| B | `02-11-22-33-44-55` | 3 | Yes | 0 | Yes | None |

Both sessions reached the ERP feature, completed the query and logged out
normally. Elapsed times were 35.59 and 35.55 seconds, respectively. Local raw
evidence and a credential-free summary are retained in the ignored
`runs/mac-ab-20260914-081711/` directory. All 48 offline unit tests also passed.

## Conclusion and scope

The tested account and backend accept both reported MAC values through the
current simulator login path. That path does not require the workstation's real
MAC to appear in `clientInfo`, nor is it bound to the all-zero default.

This experiment changed the application-level reported MAC only. It did not
change the physical network adapter MAC and therefore does not test DHCP,
switch/network admission policy, or the native GDC MDS login path. It also does
not establish acceptance of every possible MAC, account or server configuration.
