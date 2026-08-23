# ADR 0001: Diploma Distribution Boundary

Date: 2026-08-23

Status: Accepted for public diploma distribution foundation

## Context

The diploma review needs a public project that can be cloned, installed and
examined without private infrastructure. The source architecture decision is
HomeTutor ADR-0007 at commit `397b251effeb3d2e3b751e44026c6ec429975fb6`.
This document is a public-safe derivative for the distribution repository.

## Decision

Agent Coach is maintained here as a standalone deterministic diploma demo. D1
creates only the repository foundation. Later slices may add public contracts,
framework-independent Agent Core, deterministic mock adapters and a local Mock
Agent API.

This decision does not authorize a production network service, production
MCP/API deployment, production auth, durable production state, learner data
movement or any switch from an embedded HomeTutor integration to a network
boundary.

## Ownership

HomeTutor remains the source system for the original private implementation and
architecture evidence. This repository is a public review surface, not a mirror
and not a production source of truth. Any ownership cutover or service boundary
change requires a separate future decision.

## Non-Goals

- production deployment;
- production service authentication;
- production data or learner records;
- write-enabled tools;
- private provider clients or credentials;
- dependency on a private checkout;
- durable production run storage.

## Planned Slices

- D1: public repository foundation;
- D2: public contracts and provenance manifest;
- D3: framework-independent Agent Core;
- D4: deterministic mock adapters and fixtures;
- D5: local Mock Agent API;
- D6: parity and drift checks;
- D7: diploma review kit and release evidence.

## Consequences

The repository can grow into a deterministic public demo while preserving a
clear boundary between review artifacts and private production systems. Future
production work must be decided independently before any network service,
durable storage, authentication or ownership change is introduced.
