# Implementation Plan

This plan is self-contained for the public Agent Coach diploma demo. Each slice
ends with checks and a promotion report. The next slice does not start
automatically.

## D1 - Public Repository Foundation

Create package metadata, CI, documentation, smoke tests and public repository
rules. Do not add runtime code, contracts, fixtures or an API.

## D2 - Contract and Provenance Export

Add versioned public contracts and deterministic test vectors with a file-level
export manifest. The public CI must validate contracts without any private
checkout.

## D3 - Framework-Independent Agent Core

Introduce Agent Core behind explicit ports. Core code must avoid web framework,
network, provider, database, environment and fixture-loading dependencies.

## D4 - Deterministic Mock Adapters

Add offline planner, tool, security, clock and ephemeral run-store adapters
plus synthetic fixtures. Runs must be deterministic and write-free.

## D5 - Local Mock Agent API

Add a localhost demo API over the completed core and mock adapters. OpenAPI is
an executable artifact only after routes exist.

## D6 - Parity and Drift Gate

Add checks that detect drift between exported public contracts and their source
evidence.

## D7 - Diploma Review Kit and Release

Prepare reviewer instructions, evidence, release notes and final public-safety
checks. Do not publish production capability claims.

Any production network boundary, durable service deployment or ownership
cutover requires a separate future architecture decision.
