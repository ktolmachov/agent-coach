# Security Policy

## Supported Surface

D1 contains documentation, package metadata, CI configuration and an importable
package stub. It contains no network server, no Agent API, no tools, no model
provider clients and no data persistence.

## Reporting Issues

Do not report security vulnerabilities in public issues.

Use GitHub Private Vulnerability Reporting or a GitHub Security Advisory when
it is enabled for this repository. If that private channel is unavailable, use
the non-public course review channel for this diploma submission and include
only the minimum details needed to reproduce the issue.

Public issues are appropriate for ordinary defects, documentation questions and
non-sensitive enhancement requests.

## Public Safety Rules

- no secrets, credentials or realistic tokens;
- no learner data or production HomeTutor data;
- no HomeTutor runtime imports;
- no production auth simulation;
- deterministic offline defaults for future demo code;
- localhost-only defaults once a local API exists in a later slice.
