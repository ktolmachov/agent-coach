# Security Policy

## Supported Surface

The supported public surface is the standalone deterministic diploma demo:
documentation, exported public contracts, framework-independent Agent Core,
deterministic mock adapters and a localhost-only Mock Agent API. It contains no
production authentication, no production data, no committed provider credentials
and no durable production persistence. An optional live-provider adapter may
call the official OpenAI SDK when a reviewer supplies a key locally. That
adapter is not the default demo path.

## Reporting Issues

Do not report security vulnerabilities in public issues.

Use GitHub Private Vulnerability Reporting or a GitHub Security Advisory when
it is enabled for this repository.

Fallback private security recipient: send the report in the private course LMS
submission thread addressed to the repository owner `ktolmachov` and the
diploma review supervisor. Include only the minimum details needed to reproduce
the issue.

Public issues are appropriate for ordinary defects, documentation questions and
non-sensitive enhancement requests.

## Public Safety Rules

- no secrets, credentials or realistic tokens;
- no learner data or production HomeTutor data;
- no HomeTutor runtime imports;
- no production auth simulation;
- deterministic offline defaults for demo code;
- localhost-only Mock API defaults;
- release evidence must identify the reviewed commit and must not be published
  from a dirty worktree.
