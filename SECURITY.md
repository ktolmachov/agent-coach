# Security Policy

## Supported Surface

D1 contains documentation, package metadata, CI configuration and an importable
package stub. It contains no network server, no Agent API, no tools, no model
provider clients and no data persistence.

## Reporting Issues

Please report security issues through the repository issue tracker or the
course review channel used for this diploma submission.

## Public Safety Rules

- no secrets, credentials or realistic tokens;
- no learner data or production HomeTutor data;
- no HomeTutor runtime imports;
- no production auth simulation;
- deterministic offline defaults for future demo code;
- localhost-only defaults once a local API exists in a later slice.
