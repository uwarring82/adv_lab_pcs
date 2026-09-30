# Security policy

## Design assumptions

The spectrometer dashboard is a **local, single-user lab tool**:

- The server binds to `127.0.0.1` only, so it is reachable from the lab PC itself and
  nowhere else.
- There is **no authentication**. Anyone who can reach the port can control the
  spectrometer, change its settings and read all data.
- Every request is validated against hard limits (memory, instrument time, detector
  size) so that a bad request cannot exhaust the PC or block the instrument
  indefinitely; see [docs/api.md](docs/api.md#limits).

Do not expose the service on a network (for example with `--host 0.0.0.0`) unless you
put your own access control in front of it.

The Windows setup scripts run as administrator by design (they install drivers and
change power settings). Read them before running them, and run them only from a
trusted copy of this repository.

## Supported versions

Security fixes go into the latest version on the default branch.

## Reporting a vulnerability

Please **do not open a public issue**. Report it privately through GitHub's
[private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
(the repository's *Security* tab → *Report a vulnerability*). Include what you found,
how to reproduce it and what an attacker could do with it. You will get an answer
as soon as the maintainer can look at it; this is a university teaching project
without an on-call team.
